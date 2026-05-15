# Safety: device and HIL runs (HARD rule)

This is a **hard rule**. The enforcement is layered:

| Layer | What it does | Authority |
|---|---|---|
| `safety-check` hook (`PreToolUse: Bash`) | **Coarse gate** — blocks obvious ad-hoc Bash launches of device/HIL entrypoints when lock/calibration/self-check files are missing. | Catches direct shell launches that bypass the skill. Cannot resolve full config or check rehearsal equivalence. |
| `/run-experiment` skill | **Authoritative preflight** — resolves the experiment config, computes snapshots and hashes, verifies every precondition in §1, gathers operator confirmation, writes safety fields into metadata. | This is the only path that can launch a device/HIL run cleanly. |
| `device-operator` agent | Operational counterpart to the skill — runs calibration, self-check, telemetry capture, abort/safe-stop. | Reports `status: blocked` if any §1 precondition is not satisfied. |

If the hook blocks, the user is told to use `/run-experiment` instead. The
skill then either proceeds or refuses with a specific reason.

The scope is any run whose resolved `execution_target ∈ {device, hil}`, OR
any build/run sequence that drives a real-world actuator. Pure simulation
runs are out of scope.

The user is the safety owner. Zone B `ethics.hil_safety_owner` MUST be set
(non-null) before any device/HIL skill will operate; `/init-experiment`
enforces this for projects with such experiments.

---

## 1. Preconditions for launch

A device or HIL run MUST satisfy ALL of the following before
`/run-experiment` is allowed to execute the entrypoint. The skill is the
authoritative enforcement layer. Failures surface as `status: blocked` from
`device-operator` and a refusal message from the skill. The `safety-check`
hook covers the subset of these that it can validate (marked HOOK below).

1. **Lock held.** [HOOK + SKILL] The session holds an exclusive lock at
   `data/locks/<device_id>.lock`. HIL additionally holds
   `data/locks/<bench_id>.lock`. Every lock file's body is the JSON object
   `{pid, operator, acquired_at}`. If a stale lock exists from a prior
   session and that PID is no longer running, the `/lock-device` skill MAY
   break it, but only with explicit user confirmation and only after writing
   the prior lock's contents to
   `data/locks/<device_id>.lock.broken-<timestamp>` (same pattern for bench).

2. **Fresh calibration.** [HOOK + SKILL] A calibration sidecar exists at
   `data/calibrations/<device_id>.latest.json` (written by `/calibrate-device`)
   AND `(now - performed_at) / 3600 <= tolerance_h` where `tolerance_h` is
   declared in `docs/research/methodology.md` per experiment (default 24h).
   Both layers MUST recompute the age from the sidecar's `performed_at`
   timestamp at check time — a `calibration_age_h` value already written into
   a prior run's metadata is a frozen snapshot, not the current age, and is
   NOT a valid input to the freshness check.

3. **Interlocks armed (HIL only).** [HOOK: file existence + freshness only |
   SKILL: full semantic check] The bench self-check artefact
   `data/locks/<bench_id>.selfcheck.json` must exist and have an mtime within
   the last hour — the hook verifies both. The semantic content
   (`hil.interlocks.e_stop_armed == true` AND `hil.interlocks.watchdog_ms_used`
   is a positive integer not exceeding the bench's documented
   `watchdog_ms_max`) is parsed and verified by `/run-experiment` step 8.3;
   the hook deliberately does not parse the JSON since the schema is
   bench-specific.

4. **Dry-run plan reviewed.** [SKILL only] For any run whose
   `safety_class ∈ {calibration-required, destructive}` (declared in Zone B
   `experiments[].safety_class`), a `dry_run: true` rehearsal MUST have been
   executed within the last 24h, with `exit_state: success`, against the
   same `config_snapshot_sha256` as this run. The rehearsal `run_id` is
   recorded in `metadata.device.dry_run_rehearsal_run_id`. The rehearsal does
   not actuate the device; it exercises the control loop with the device in
   safe-mode.

5. **Operator-in-loop confirmation.** [SKILL only] For `safety_class:
   destructive`, an `AskUserQuestion` prompt MUST be answered "proceed" by
   the user immediately before launch. This confirmation is recorded in
   `metadata.device.operator_confirmation_at` (ISO-8601 UTC).

6. **Cleanup path present.** [SKILL — relies on prior `script-reviewer`
   verdict] The entrypoint code must declare a cleanup handler (signal
   handler for SIGINT/SIGTERM, or framework equivalent) that leaves the
   device in a safe state on any exit path. `script-reviewer` writes its
   verdict to `data/results/<verdict_run_id>/script_review.json` and records
   the reviewed `entrypoint_sha256`. The verdict is trusted as long as the
   current run's `metadata.entrypoint_sha256` matches; when it changes, the
   skill re-runs `script-reviewer` before launch.

---

## 2. Escape hatches

There are exactly three escape hatches. Anything else is a violation.

| Escape | What it does | How to invoke |
|---|---|---|
| `dry_run: true` in run config | Disables actuation; the run exercises code paths but the `device-operator` interposes a safe-mode wrapper. Safety-check still requires lock + interlocks but waives calibration freshness and operator-confirmation. | Set `dry_run: true` in the experiment config before invoking `/run-experiment`. |
| `safety_class: none` in Zone B `experiments[]` entry | Declares the experiment never actuates anything destructive (e.g. read-only sensor sweep). Skips operator-confirmation and dry-run requirement. Does NOT skip lock, calibration freshness, or interlock checks. | Set `safety_class: none` in the experiment registry entry. The setting is reviewed by the user during `/init-experiment` / `/design-experiment`. |
| `--override-safety=<check_name>:<reason>` flag on `/run-experiment` | Allows ONE specific check to be skipped with a recorded justification. Valid `check_name` values: `calibration`, `dry_run_rehearsal`, `bench_selfcheck`, `cleanup_verdict`. The `lock` and `operator_confirmation` checks CANNOT be overridden. Requires `hil_safety_owner` to type the override interactively (cannot be automated). Logged to `metadata.device.safety_overrides[]` with `{check_name, reason, override_at, operator}`. | Last-resort manual override. The CHANGELOG entry MUST cite the reason. |

There is no global "disable safety" flag.

---

## 3. Exit states and cleanup

Every device/HIL run, regardless of outcome, MUST:

1. Run the cleanup handler (return device to home / power-down / disarm
   interlocks) on every termination path.
2. Write `cleanup_log.txt` documenting which cleanup steps ran and their
   outcome.
3. Record final `exit_state` in `metadata.json`. The values
   `aborted` and `safe-stop` indicate the cleanup path ran intentionally.
   `crash` and `interrupted` indicate the cleanup MAY have been skipped — in
   that case the next session-start performs a forced device check and refuses
   any new device run until the user confirms the device is in a safe state.

`safe-stop` specifically means a safety interlock fired (e-stop, watchdog,
out-of-bounds sensor reading). Treat `safe-stop` runs as incidents: the
`/run-experiment` skill emits an incident summary and prompts the user to
file an entry in `docs/research/incidents.md` before launching the next run.

---

## 4. What the orchestrator must refuse

The orchestrator MUST refuse, and emit a clear Japanese explanation to the
user, when:

- The user asks to run a device/HIL experiment without going through
  `/run-experiment`. Ad-hoc Bash execution of the entrypoint is not allowed
  for device/HIL targets.
- The user asks to delete or move `data/locks/`, `data/calibrations/`, or any
  `cleanup_log.txt`.
- The user asks to suppress or comment out the cleanup handler in the
  entrypoint source.
- The user asks to backdate `calibration_age_h` or `operator_confirmation_at`.

Refusal is not optional. The user can still do all of the above by editing
files themselves with `Edit` / `Bash` directly, but the orchestrator does not
participate.

---

## 5. Why this is a hard rule

Soft safety rules get bypassed under time pressure. A miscalibrated actuator
or an unprotected HIL bench can damage hardware costing far more than the
inconvenience of one extra confirmation. The escape hatches are deliberately
narrow so that "I'm in a hurry" cannot reach the destructive path without
either:

(a) declaring the experiment intrinsically non-destructive,
(b) running a successful dry-run rehearsal, or
(c) invoking the named override flag with a logged reason.

If any of these feel onerous, that is the design working. They are cheaper
than the incident.
