---
name: sweep-experiment
description: Parameter sweep for one experiment. Generates a list of configs from a sweep specification, invokes /run-experiment for each, and groups the resulting run_ids under a shared sweep_id recorded in every metadata.json.
when_to_use: After /design-experiment + /build-experiment (if native), when you want to vary one or more parameters across a controlled grid or sample. Most useful for sim experiments; device/HIL sweeps inherit the full safety preflight per run.
inputs:
  - <id> — required experiment_id
  - --spec <path> — required path to a sweep spec YAML/JSON (see "Sweep spec" below)
  - --max-parallel <n> — optional (default 1); for sim only — device/HIL sweeps are always serial under the shared lock
  - --dry-run — propagated to every per-run invocation (device/HIL only)
  - --resume <sweep_id> — pick up a previously-started sweep, skip runs already in `data/results/` for that sweep_id
outputs:
  - data/sweeps/<sweep_id>/manifest.json — sweep spec snapshot, list of resolved configs, list of run_ids
  - data/sweeps/<sweep_id>/summary.csv — per-run summary (run_id, exit_state, primary outcome if parseable)
  - data/results/<run_id>/ for each grid point, each tagged with `metadata.sweep_id == <sweep_id>`
delegated_agent: orchestrator (drives the sweep); each per-run invocation delegates to experiment-runner (+ device-operator on device/HIL) via /run-experiment
next_skill: /analyze-results --sweep <sweep_id>
---

# /sweep-experiment

A sweep is N runs of the same experiment with different configs. The runs share an `experiment_family` (inherited from the registry) AND a `sweep_id` (allocated here). This is the canonical way to run replications (varying only the seed) and parameter studies (varying any subset of config fields).

## Sweep spec

A YAML or JSON file describing how to generate the grid of configs. Three styles supported:

```yaml
# (1) Grid — cartesian product
kind: grid
base_config: src/experiments/<id>/config.example.yaml   # required
overrides:
  seed: [1, 2, 3, 4, 5]
  learning_rate: [1e-3, 1e-4]
# → 5 × 2 = 10 runs

# (2) List — explicit list of overrides
kind: list
base_config: src/experiments/<id>/config.example.yaml
configs:
  - {seed: 1, learning_rate: 1e-3}
  - {seed: 1, learning_rate: 1e-4}
  - {seed: 2, learning_rate: 1e-3}

# (3) Random — N samples from per-key distributions
kind: random
base_config: src/experiments/<id>/config.example.yaml
n: 20
sampler:
  seed: {kind: int_range, low: 1, high: 1000}
  learning_rate: {kind: loguniform, low: 1e-5, high: 1e-2}
  hidden_size: {kind: choice, values: [64, 128, 256, 512]}
master_seed: 42   # the sampler itself is seeded for reproducibility
```

The spec file MUST be committed to the repo (the sweep manifest records its path and content hash).

## Steps for the orchestrator

1. **Resolve `<id>`** per `CLAUDE.md` §Resolution. Verify the registry entry exists.
2. **Load and validate the spec.** Parse the spec file, validate against the experiment's `config_schema` (every generated config must pass). If `config_schema: null`, warn the user — unvalidated sweeps are footguns.
3. **Pre-flight.**
   - For native runtimes: verify a matching `build_id` exists (the sweep does NOT rebuild per run; one build serves the whole sweep). Refuse with a remediation hint if absent.
   - For device/HIL: read `device_id` (and `bench_id` for HIL) from the registry entry; verify `data/locks/<device_id>.lock` is held by this session AND a fresh calibration is available. Refuse with explicit remediation `/lock-device <device_id>` / `/calibrate-device <experiment_id>` using the resolved values.
   - If `--max-parallel > 1` and `execution_target ∈ {device, hil}`: refuse — physical runs cannot be parallelized under one lock.
4. **Allocate or reuse `sweep_id`**:
   - On a fresh invocation (no `--resume`): allocate `<experiment_id>-sweep-<UTC ISO with hyphens>` (e.g. `solver-baseline-sweep-2026-05-14T13-00-00`). Create `data/sweeps/<sweep_id>/`.
   - On `--resume <sweep_id>`: reuse the existing sweep_id and load the existing manifest. Refuse if the manifest's `finished_at` is non-null (a completed sweep cannot be resumed; re-run as a fresh sweep instead).
5. **Resolve the grid.** Materialize every config in the sweep as a concrete dict. For `random` specs, seed the sampler with `master_seed` and record the resolved configs verbatim in the manifest.
6. **Write the sweep manifest** at `data/sweeps/<sweep_id>/manifest.json`:
   ```json
   {
     "sweep_id": "<sweep_id>",
     "experiment_id": "<id>",
     "spec_path": "<path>",
     "spec_sha256": "<sha256>",
     "kind": "grid|list|random",
     "n_runs": <int>,
     "started_at": "<ISO>",
     "configs": [
       { "index": 0, "overrides": {...}, "config_snapshot_sha256_expected": "..." },
       ...
     ],
     "run_ids": [],
     "finished_at": null
   }
   ```
7. **For each config**, in order:
   a. If `--resume <sweep_id>` was passed and an existing `run_id` for this index already lives in `data/results/` with `metadata.sweep_id == <sweep_id>` AND `exit_state: success`, skip.
   b. Materialize the config to a temp file.
   c. Invoke `/run-experiment <id> --config <temp_config> --sweep-id <sweep_id> --sweep-index <i>`. The `--sweep-id` and `--sweep-index` flags are defined in `/run-experiment` inputs; the skill writes `metadata.sweep_id = <sweep_id>` via `repro.write_initial_metadata` (which reads sweep_id from the args dict).
   d. Append the resulting `run_id` to `manifest.run_ids[]`.
   e. Append a row to `data/sweeps/<sweep_id>/summary.csv`: `index, run_id, exit_state, wall_clock_s, primary_outcome` (the latter only when the driver emits a parseable `[outcome] key=value` line — otherwise leave blank).
   f. **On non-success exit_state**: log the failure but continue. The sweep is best-effort; users will analyze partial sweeps. Exception: `safe-stop` triggers a hard halt of the sweep — the orchestrator surfaces the incident and asks the user how to proceed (resume after fixing, or abandon).
8. **Update the manifest** with `finished_at` once the loop exits.
9. **Update Zone C**: `last_sweep_id: <sweep_id>`, `last_skill_run: sweep-experiment`. Phase stays `run`.
10. **Report** (Japanese): sweep_id, total configs, successes / failures / aborted-sweep counts, path to `summary.csv`, next suggested action (`/analyze-results --sweep <sweep_id>`).

## Parallelism

- Sim, `--max-parallel > 1`: launch up to N driver processes concurrently. Each gets a unique `run_id`. The sweep skill waits for all to finish before writing `manifest.finished_at`.
- Cluster (sim + `compute_target: cluster`): each config is submitted as a separate scheduler job; the skill builds the job script per config and submits, then polls for completion. `--max-parallel` here means "concurrent jobs in queue" (rate-limit-aware).
- Device / HIL: always serial.

## Hard rules

- Every run in a sweep MUST have `metadata.sweep_id == <sweep_id>` and `metadata.experiment_family == experiments[id].family`. The skill enforces this when invoking `/run-experiment`.
- Failed runs are NOT excluded from `manifest.run_ids[]`. They are recorded with their actual `exit_state`. Cherry-picking which sweep runs to keep is `research-integrity.md` selective reporting.
- The sweep manifest is **immutable** once `finished_at` is set. A re-run with the same spec produces a new `sweep_id`. `--resume` works only while `finished_at` is still null.
- For inference (statistical comparison across the sweep), the experiment's methodology MUST have `inference_kind: sweep-inference`. The `statistical-rigor.md` multi-comparison correction applies.
- Never delete `data/sweeps/<sweep_id>/`. Stale sweeps stay as the audit trail.

## Examples

| User input | Effect |
|---|---|
| `/sweep-experiment solver-baseline --spec sweeps/seeds.yaml` | Run the experiment for every seed in the spec, serial. |
| `/sweep-experiment solver-baseline --spec sweeps/grid.yaml --max-parallel 8` | Sim sweep, up to 8 concurrent drivers. |
| `/sweep-experiment solver-baseline --spec sweeps/random.yaml --resume solver-baseline-sweep-2026-05-14T13-00-00` | Resume an interrupted sweep, skipping already-successful indices. |
| `/sweep-experiment mems-actuator --spec sweeps/duty.yaml --dry-run` | Device sweep in safe-mode (no actuation); produces the rehearsal record needed for a non-dry-run. |
