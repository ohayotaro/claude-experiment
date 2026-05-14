---
name: lock-device
description: Acquire (or release) a `data/locks/<id>.lock` file for a device or HIL bench. Required before any device/HIL `/run-experiment` invocation. Safely breaks stale locks held by dead PIDs with explicit user confirmation.
when_to_use: Before the first device/HIL run of a session; before re-running after a crash that may have left a lock pinned; at session end to release.
inputs:
  - <id> — required positional argument; matches the `device_id` or `bench_id` in Zone B `experiments:`
  - --release (optional flag — release the lock instead of acquiring)
  - --force (optional flag — break a stale lock held by a dead PID, after writing the prior lock to `<id>.lock.broken-<timestamp>`)
outputs:
  - data/locks/<id>.lock — JSON file with `{pid, operator, acquired_at}` (acquire path)
  - data/locks/<id>.lock.broken-<timestamp> — backup of broken stale lock (--force path only)
  - CLAUDE.md Zone C `held_locks` list updated
delegated_agent: orchestrator (no subagent; coordinates with device-operator only when probing the device after a force-break)
next_skill: /calibrate-device (if calibration is stale), /run-experiment (otherwise)
---

# /lock-device

Manages exclusive access to a device or HIL bench via a JSON lock file at `data/locks/<id>.lock`. The body schema is fixed per `.claude/rules/safety-hil.md`:

```json
{
  "pid": 12345,
  "operator": "ryotaro",
  "acquired_at": "2026-05-14T12:34:56Z"
}
```

The `safety-check` hook reads this file and verifies the recorded PID is in the current session's process chain before allowing any device entrypoint to launch. If your session terminates without releasing the lock, the `session-end` hook warns and the next session's `session-start` reports it.

## Steps for the orchestrator

### Acquire (default)

1. **Resolve `<id>`.** Must match either `experiments[].device_id` or `experiments[].bench_id` in Zone B. Reject any other value with a clear error.
2. **Inspect existing lock.** Read `data/locks/<id>.lock` if present.
   - If absent → proceed to step 4.
   - If present and the recorded `pid` is alive AND in this session's process chain → already held by us; report success without rewriting the file.
   - If present and the recorded `pid` is alive but NOT in this session's chain → **refuse** with `[lock-device] このセッションでは取得できません: 別セッション (pid=<n>, operator=<name>) が保持中です。`
   - If present and the recorded `pid` is dead → STALE; go to step 3.
3. **Stale lock handling.** Show the user the stale lock contents (pid, operator, acquired_at, age in hours) in Japanese and require explicit `--force` OR an interactive confirmation via `AskUserQuestion`. On confirmation:
   - Move the existing file to `data/locks/<id>.lock.broken-<UTC timestamp>` (preserves audit trail).
   - Proceed to step 4.
4. **Probe the device (HIL only).** For HIL benches, ask `device-operator` to run a quick reachability check before claiming the lock. If the bench is unresponsive, abort with `status: blocked` — locking a bench you cannot reach is misleading.
5. **Write the lock.** Atomic write (tmp + `os.replace`) of `{pid: os.getpid(), operator: <from Zone B `ethics.hil_safety_owner` or `git config user.name`>, acquired_at: <ISO-8601 UTC>}`.
6. **Update Zone C `held_locks`** with `{kind: device|bench, id: <id>, lock_path: data/locks/<id>.lock}`.
7. **Report** (Japanese): id, kind, operator. Next-step suggestions reference the **experiment_id**, not the lock id (multiple experiments may share one device): if calibration is needed, `/calibrate-device <experiment_id>`; once fresh, `/run-experiment <experiment_id>`. List the experiment_ids in Zone B whose `device_id` or `bench_id` matches this lock id so the user can pick.

### Release (--release)

1. **Resolve `<id>`.**
2. **Read the existing lock.** If absent, report success (idempotent).
3. **Verify ownership.** Recorded `pid` MUST be in this session's process chain. If not, refuse with `[lock-device] 別セッションが保持中のロックです。--force があれば外せますが、別セッションに迷惑をかける前に確認してください。`
4. **Delete the file.** No backup needed — release is the normal exit path.
5. **Remove from Zone C `held_locks`.**
6. **Report** (Japanese): id, kind, "release 完了".

## Hard rules

- A device/HIL run is the only legitimate consumer of the lock. The skill never reads or writes anything under the device itself; that is `device-operator`'s job.
- The lock file body is the JSON `{pid, operator, acquired_at}` exactly. Do not add fields; the `safety-check` hook parses with `json.loads` and tolerates extra keys but the schema is the contract.
- **`--force` only breaks stale locks** (recorded PID is no longer alive). Per `safety-hil.md`, a lock held by a live PID — even one in another Claude Code session — is NOT a stale lock and the skill MUST refuse to break it. To release another session's lock, the human operator must terminate that session first (or sit at its terminal and run `--release` there).
- `--release` only releases a lock the current session owns. `--force --release` is NOT a valid combination and the skill rejects it.
- Never delete files under `data/locks/` directly; always use this skill.

## Examples

| User input | Effect |
|---|---|
| `/lock-device mems-01` | Acquire the lock for `mems-01`. |
| `/lock-device mems-01 --release` | Release the lock; remove Zone C entry. |
| `/lock-device hil-bench-3 --force` | Break a STALE lock (recorded PID is dead) after confirmation; acquire. The skill refuses if the recorded PID is still alive. |
