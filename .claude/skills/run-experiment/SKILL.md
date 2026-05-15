---
name: run-experiment
description: Authoritative preflight + execution of one experiment run. Resolves the registry entry, computes hashes, performs the full safety-hil §1 checks for device/HIL, writes initial run metadata, delegates execution to experiment-runner (and device-operator for device/HIL), finalizes the run on every exit path.
when_to_use: After /design-experiment (and /build-experiment for native runtimes). Re-runnable for replications (different seeds) and for re-execution after fixes.
inputs:
  - experiment_id (optional — resolved per CLAUDE.md §Resolution; confirms with user when registry has multiple entries)
  - --seed <n> (optional — overrides methodology default)
  - --config <path> (optional — overrides default config.example.yaml; the resolved config is snapshotted into the run dir)
  - --build-id <id> (optional — overrides the latest matching build; ignored for python-uv)
  - --dry-run (device/HIL only — runs in safe mode, no actuation; satisfies the dry-run rehearsal precondition)
  - --override-safety=<check_name>:<reason> (last-resort, single-check, logged; requires hil_safety_owner to confirm)
  - --sweep-id <id> (set by /sweep-experiment per run — stamps `metadata.sweep_id`; the user does NOT typically pass this manually)
  - --sweep-index <i> (set by /sweep-experiment per run — informational; also stamped into args)
outputs:
  - data/results/<run_id>/ (metadata.json, config.snapshot.yaml, log.txt, results/, telemetry/ if device/HIL, cleanup_log.txt if device/HIL)
delegated_agent: experiment-runner (sim) | experiment-runner + device-operator (device/HIL)
next_skill: /analyze-results
---

# /run-experiment

This skill is the **authoritative preflight layer** per `.claude/rules/safety-hil.md`. The `safety-check` hook is a coarse gate; this skill verifies every precondition before delegating execution.

> **Availability** — sim, device, and HIL paths are all operational. The
> device / HIL workflow requires `/lock-device <device_id>` to acquire the
> lock first and `/calibrate-device <experiment_id>` to produce a fresh
> calibration before this skill will pass §8. If either is missing, the
> preflight aborts cleanly with the matching remediation skill named in the
> error message.

## Steps

1. **Resolve `experiment_id`** per `CLAUDE.md` §Resolution. If multiple entries exist and the user did not pass one, ask.
2. **Resolve runtime / execution_target / compute_target** per §Resolution. Log each:
   ```
   [resolution] field=runtime source=registry value=cpp-cmake
   [resolution] field=execution_target source=registry value=sim
   [resolution] field=compute_target source=cli value=cluster
   ```
   The same log lines are persisted to the run's `log.txt`.
3. **Allocate `run_id`** as `<UTC ISO-8601 with hyphens>_<8-char hash>` (per `reproducibility.md` §1, e.g. `2026-05-14T12-34-56_a1b2c3d4`). Create `data/results/<run_id>/`. If `--sweep-id` was passed, record the sweep_id and the sweep_index in `args` so `repro.write_initial_metadata` stamps them into `metadata.sweep_id` and `metadata.args.sweep_index`.
4. **Resolve the config**:
   - Load `--config <path>` if passed; else the experiment's `config.example.yaml`.
   - Apply CLI overrides (e.g. `--seed`).
   - Validate against `config_schema` if the registry entry specifies one. On validation failure, abort with `status: blocked`.
   - Write the resolved config to `data/results/<run_id>/config.snapshot.yaml`. Compute and store `config_snapshot_sha256`.
5. **Resolve `build_id`** (native runtimes only):
   - If user passed `--build-id`, use it (verify the manifest exists and `manifest.exit_state == success`; on `smoke_failed` warn and require explicit confirmation; on `failed` refuse).
   - Else find the most recent healthy `data/builds/*/manifest.json` whose `runtime` matches the resolved runtime AND whose `source_tree_hash` equals `repro.compute_source_tree_hash()` for the current working tree. (`source_tree_hash` is computed from the working tree files, independent of `git_rev`; a dirty tree yields a different hash even at the same commit, so dirty trees will not match a clean build.) If none, abort with a hint to run `/build-experiment` first.
   - For `python-uv`, this step is a no-op; `build_id = null`.
6. **Compute `entrypoint_sha256`** from the registry's `entrypoint` path. The registry MUST point to a stable launcher under `src/` (e.g. `src/experiments/<id>/run.py`), NEVER to a built binary under `data/builds/<build_id>/` — see `.claude/agents/experiment-runner.md` §"Native". If the registry entry violates this, abort with a clear remediation message.
7. **Write initial metadata** to `data/results/<run_id>/metadata.json` via `src/utils/repro.write_initial_metadata(...)`. This populates everything known before launch (top-level + the appropriate target block skeleton).
8. **For `execution_target ∈ {device, hil}`, perform the authoritative safety preflight per `safety-hil.md` §1**.

   **Pre-step: parse `--override-safety` and `--dry-run` first.** Both flags
   change which sub-steps below MUST run; applying them after the checks
   would defeat the escape hatch (the run would already have been
   blocked / launched). Specifically:
   - Parse `--override-safety=<check_name>:<reason>` into a set of skipped
     checks. Valid `check_name`: `calibration`, `dry_run_rehearsal`,
     `bench_selfcheck`, `cleanup_verdict`. Reject any other name. The
     `lock` and `operator_confirmation` checks are NEVER skippable.
   - For each parsed override, require `hil_safety_owner` to type the
     override interactively via `AskUserQuestion` (the answer must be
     their name from Zone B). Record `{check_name, reason, override_at,
     operator}` into `metadata.device.safety_overrides[]` via
     `repro.patch_metadata` BEFORE running the corresponding check so the
     audit trail survives a crash inside the check.
   - If `--dry-run` was passed, record `metadata.device.dry_run = true`
     via `repro.patch_metadata` BEFORE step 8.2.

   Sub-checks (each MAY be skipped per the table below):

   | # | Check | Skipped when |
   |---|---|---|
   | 8.1 | Lock verification | never |
   | 8.2 | Calibration freshness | `--dry-run` OR `--override-safety=calibration` OR `safety_class: none` |
   | 8.3 | (HIL) Interlocks armed | `--override-safety=bench_selfcheck` |
   | 8.4 | Dry-run rehearsal equivalence | `--dry-run` OR `--override-safety=dry_run_rehearsal` OR `safety_class ∉ {calibration-required, destructive}` |
   | 8.5 | Operator-in-loop confirmation | `--dry-run` OR `safety_class != destructive` |
   | 8.6 | Cleanup-handler verdict | `--override-safety=cleanup_verdict` |

   Sub-step details:
   1. **Lock verification.** Read `data/locks/<device_id>.lock` (and `data/locks/<bench_id>.lock` for HIL). Verify it is held by this session's PID chain. If not, abort with `status: blocked` and suggest `/lock-device <device_id>`. Lock is NEVER skipped.
   2. **Calibration freshness.** Read the most recent `data/calibrations/<calibration_ref>.meta.json` for this `device_id` (`calibration_ref` is device-scoped per `/calibrate-device`); compute `age_h = now - performed_at`. Verify `age_h <= tolerance` (default 24h or per-experiment override in methodology). On stale, abort with the explicit remediation `/calibrate-device <experiment_id>`. Do not read `calibration_age_h` from a prior run's metadata — that value is a frozen snapshot, not the current age.
   3. **(HIL) Interlocks armed.** Read `data/locks/<bench_id>.selfcheck.json`. Verify `interlocks.e_stop_armed == true`, `watchdog_ms_used <= watchdog_ms_max`, file mtime within last hour. On failure, request `device-operator` to re-run the self-check (skill A in the agent's workflow).
   4. **Dry-run rehearsal equivalence.** Scan `data/results/*/metadata.json` for a run with same `experiment_id`, `device.dry_run == true`, `exit_state: success`, `config_snapshot_sha256` matching this run's, and `started_at` within the last 24h. If none, abort with a clear message asking the user to first run `/run-experiment <id> --dry-run`. Record the matched `run_id` in `metadata.device.dry_run_rehearsal_run_id`.
   5. **Operator-in-loop confirmation.** Issue an `AskUserQuestion` to the user requiring an explicit "proceed" / "abort". Record the ISO-8601 UTC timestamp in `metadata.device.operator_confirmation_at`. If aborted, write `exit_state: aborted`, finalize, and return. This check is NEVER skipped via `--override-safety`; the only path that skips it is `--dry-run` (no actuation) or `safety_class != destructive`.
   6. **Cleanup-handler verdict.** Look for `data/results/<verdict_run_id>/script_review.json` whose `entrypoint_sha256` matches the current run's `entrypoint_sha256` (field name is `entrypoint_sha256` per `script-reviewer.md`). If absent, invoke `/review-script` synchronously and abort on blockers.
9. _(reserved — override parsing now happens inside step 8 pre-step so the audit trail is recorded BEFORE the check it skips.)_
10. _(reserved — `metadata.device.dry_run` is now stamped inside step 8 pre-step before any conditional check.)_
11. **Delegate execution**. The skill hands every downstream agent a fully resolved payload, not loose context:
    - To `experiment-runner` (always): `{run_id, experiment_id, run_dir, resolved, config_snapshot_path, build_id, args}` where `resolved` is the dict from step 2 and `run_dir = data/results/<run_id>/`.
    - To `device-operator` (device/hil only): the same payload plus `{device_id, bench_id (hil only), hardware_spec_path (= docs/research/hardware/<bench_id>.md for hil or <device_id>.md for device), watchdog_ms_max (read from the hardware spec), calibration_tolerance_h}`.
    - Sim path: invoke `experiment-runner` only.
    - Device path: invoke `device-operator` for run setup, then `experiment-runner` for the driver, then `device-operator` again for cleanup. Pass the same `run_dir` so all three writers append to the same metadata file via `repro.patch_metadata`.
    - HIL path: same as device, with the bench arming sequence interleaved (`device-operator` re-confirms `<bench_id>.selfcheck.json` and writes `hil.interlocks` before `experiment-runner` is invoked).
12. **Finalize** on every exit path (success / crash / aborted / safe-stop / interrupted):
    - Call `src/utils/repro.finalize_metadata(run_id, exit_state)`. Idempotent.
    - For device/HIL: confirm `cleanup_log.txt` exists and is non-empty.
    - For `safe-stop`: nudge the user to add an entry to `docs/research/incidents.md` (the device-operator already appended a one-liner; the user typically wants to add context).
13. **Update Zone C**: `last_run_id: <id>`, `current_phase: run`, `next_action: "Review run-id <id> with /analyze-results"`.
14. **Report** to the user (Japanese) a summary: run_id, exit_state, wall-clock time, key outcome metrics (if the driver emits them on stdout in a parseable line), and the next suggested skill.

## Failure handling

- Any §8 precondition failure → `status: blocked`, no execution attempted. The orchestrator surfaces the reason and the remediation skill.
- Driver crash → `exit_state: crash`. The `error-to-codex` hook routes the traceback to `codex-debugger`. Cleanup runs first for device/HIL.
- Operator abort during execution (Ctrl-C, or `device-operator` receives an abort signal) → `exit_state: aborted`. Cleanup runs.
- Interlock trip mid-run → `exit_state: safe-stop`. `device-operator` records the incident.
- Wrapper process killed -9 / host loss → `finished_at` is null. The `session-start.py` reaper patches it on next session start.

## Hard rules

- The skill is the **only** path that should launch device/HIL runs. The `safety-check` hook will block direct Bash launches.
- The skill never modifies the registry, methodology, or safety rules.
- The skill never bypasses the lock check or the operator-confirmation check, even with `--override-safety`.
- For sim runs, the skill is the **recommended** but not enforced path. A user may directly run `uv run python src/experiments/<id>/run.py --seed N`; the `reproducibility-check` hook will warn if the resulting metadata is incomplete. Encourage skill usage in onboarding docs.

## Examples

| User input | Effect |
|---|---|
| `/run-experiment solver-baseline` | Resolve, preflight, launch (sim or device per registry). |
| `/run-experiment solver-baseline --seed 7` | Same, with seed overridden. |
| `/run-experiment mems-actuator --dry-run` | Device run in safe-mode; produces the rehearsal record for later non-dry-run. |
| `/run-experiment mems-actuator` (after a successful dry-run with same config) | Real device run. Operator-in-loop confirm if `safety_class: destructive`. |
| `/run-experiment mems-actuator --override-safety=calibration:emergency-rerun` | Skips the calibration check with logged reason; requires safety-owner to confirm interactively. |
