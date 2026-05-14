---
name: checkpoint
description: Persist current progress, recent artifacts, and next action into CLAUDE.md Zone C. Run before ending a session.
when_to_use: At natural pauses, before /exit, or when handing off to a future session.
inputs:
  - Current session state (skills run, artifacts produced)
outputs:
  - CLAUDE.md Zone C updated
delegated_agent: orchestrator (no subagent)
next_skill: any
---

# /checkpoint

## Steps for the orchestrator

1. **Summarize this session** in 2–4 bullets:
   - Skills executed.
   - Artifacts produced (file paths).
   - Decisions made (especially methodology lock-ins, scope changes, registry edits, calibration updates).
2. **Determine current phase** by looking at which artifacts exist:
   - `not_started` → Zone B status is still `uninitialized`.
   - `design` → `docs/research/methodology.md` exists for the active experiment, no runs yet.
   - `build` → at least one `data/builds/<build_id>/manifest.json` exists for native runtimes; no run yet.
   - `run` → at least one `data/results/<run_id>/metadata.json` with `exit_state: success`.
   - `collect` → telemetry / raw outputs are present but not yet ingested into `data/processed/`.
   - `analyze` → `docs/research/analysis.md` updated.
   - `report` → `/write-report` has produced output (only if the project opts in to reports).
3. **Determine next action** by consulting the experiment pipeline:
   `design → build → run → collect → analyze → (optional) report`.
   Iterate within a phase as needed (e.g. multiple seeds, sweeps).
4. **Write Zone C** by replacing content between `<!-- ZONE_C_BEGIN -->` and `<!-- ZONE_C_END -->`. Format:

```yaml
current_phase: <phase>
active_agent: <last delegate or null>
last_skill_run: <name>
last_experiment_id: <experiment_id or null>
last_build_id: <build_id or null>
last_run_id: <run_id or null>
last_sweep_id: <sweep_id or null>
recent_artifacts:
  - <path1>
  - <path2>
held_locks:
  - {kind: device|bench, id: <device_id or bench_id>, lock_path: <path>}
next_action: "<one-line user-facing instruction>"
notes: |
  <2–4 line free-text — decisions, blockers, parallel tracks, calibration drift>
```

`last_experiment_id` is a **hint only**. Skills MUST NOT use it as a silent default — when an `experiment_id` is needed, resolve per `CLAUDE.md` §Resolution (CLI > registry > project-default). The hint may be surfaced in prompts ("前回は <id> を扱っていました — 続けますか？") to reduce friction.

`held_locks` is informational. If any locks are still held when the session ends, surface this prominently to the user so they can release with `/lock-device --release` before walking away from the bench.

5. **Report** to user (Japanese): summary of what was saved, including which experiment was last touched and any locks still held.
