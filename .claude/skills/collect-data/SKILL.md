---
name: collect-data
description: Post-run ingestion of raw outputs (results/ and telemetry/) under data/results/<run_id>/ into normalized files under data/processed/. Idempotent — re-running on the same run_id produces byte-identical processed files.
when_to_use: After /run-experiment (or /sweep-experiment) when the analysis stage needs cleaned / merged / reshaped data. Optional for trivial experiments whose raw outputs are already analysis-ready.
inputs:
  - <run_id> | --sweep <sweep_id> — required; either a single run_id or a sweep_id to ingest all of its successful runs
  - --processor <name> (optional — pick a specific processor when the experiment has more than one; default = the experiment registry's `processors[0]` per CLAUDE.md Zone B)
  - --rewrite (optional flag — overwrite existing processed files; otherwise skipped if present)
outputs:
  - data/processed/<experiment_id>/<run_id_or_sweep_id>/ — normalized files written by the processor
  - data/processed/<experiment_id>/<run_id_or_sweep_id>/.processor.json — record of which processor was applied, input file hashes, output file hashes, processor version
  - docs/research/analysis.md — touched only if the user explicitly asks (this skill does NOT analyze; that is /analyze-results)
delegated_agent: data-analyst (light delegation — the agent runs the processor script and verifies output schema; this skill is the wrapper)
next_skill: /analyze-results <run_id> or /analyze-results --sweep <sweep_id>
---

# /collect-data

Bridges the raw-output and analysis layers. The raw outputs in `data/results/<run_id>/results/` and `data/results/<run_id>/telemetry/` are experiment-specific bags of files (CSV/Parquet/NPZ/binary checkpoints/oscilloscope traces). This skill applies a project-defined **processor** to reshape them into a stable schema under `data/processed/`, suitable for `/analyze-results` to consume without per-experiment branching.

## Processors

A processor is a Python script under `src/analysis/processors/<name>.py` that exports a single function:

```python
def process(run_dir: Path, out_dir: Path, *, run_metadata: dict) -> dict:
    """Read raw outputs from run_dir/results/ (and run_dir/telemetry/ if present),
    write normalized files into out_dir, and return a JSON-serializable dict
    summarizing what was written (file paths, schemas, sample counts).
    """
```

The experiment's Zone B entry MAY declare which processors apply via a `processors` list:

```yaml
- id: solver-baseline
  ...
  processors:
    - name: scalar-summary
      script: src/analysis/processors/scalar_summary.py
```

If unset, `/collect-data` looks for a default at `src/analysis/processors/default.py`.

## Steps for the orchestrator

1. **Resolve the input.** Either a single `run_id` or `--sweep <sweep_id>`. For a sweep, expand to the list of successful `run_id`s (skip `exit_state ∈ {crash, aborted, safe-stop, interrupted}` and report the exclusion count).
2. **Resolve the processor.** Look up the experiment's Zone B `experiments[id].processors` list:
   - If `--processor <name>` was passed, use the entry with matching `name`.
   - Else use `processors[0]` from the registry entry.
   - If the registry entry has no `processors` field, fall back to `src/analysis/processors/default.py` if present.
   - If no processor is resolvable, abort with a clear remediation: edit the experiment's Zone B entry to declare a `processors:` list, or create `src/analysis/processors/default.py`.
3. **Pre-flight check.** Verify each input `run_dir` exists, has `metadata.json` with `exit_state: success`, and has non-empty `results/`. Refuse to process runs missing metadata — the processor needs `run_metadata` to disambiguate config.
4. **Compute input hashes.** SHA-256 every file under each `run_dir/results/` and `run_dir/telemetry/`. Hold the dict in memory; do NOT write `.processor.json` yet.
5. **Idempotence check (BEFORE running the processor).** Read any existing `data/processed/<experiment_id>/<run_id_or_sweep_id>/.processor.json`. If it exists AND its `processor.script_sha256` matches the resolved processor's hash AND its recorded input hashes match the just-computed ones, **skip** (unless `--rewrite`) and report `[collect-data] 既に処理済み: <path>`. This is the canonical idempotence gate — placed before processor execution to avoid the expensive recompute on the happy path.
6. **Run the processor.** Delegate to `data-analyst` (lightweight role for this skill): import the processor module, call `process(run_dir, out_dir, run_metadata=...)` for each input. Capture exceptions; on failure, skip that run, record the failure in the `failures[]` list, and continue.
7. **Compute output hashes.** SHA-256 every file the processor wrote under `out_dir`. Build the `outputs[]` list.
8. **Write `.processor.json`** atomically at `data/processed/<experiment_id>/<run_id_or_sweep_id>/.processor.json`:
   ```json
   {
     "experiment_id": "<id>",
     "scope": {"kind": "run|sweep", "id": "<run_id or sweep_id>"},
     "processor": {"name": "<name>", "script_path": "<path>", "script_sha256": "<sha256>"},
     "processed_at": "<ISO-8601 UTC>",
     "inputs": [
       {"run_id": "...", "files": [{"path": "results/out.csv", "sha256": "..."}, ...]}
     ],
     "outputs": [
       {"path": "<rel_to_processed>", "sha256": "...", "rows": <int_if_tabular>, "schema": [<col_names_if_tabular>]}
     ],
     "failures": [{"run_id": "...", "reason": "..."}]
   }
   ```
9. **Update Zone C**: `current_phase: collect`, `last_skill_run: collect-data`. No change to `last_run_id`.
10. **Report** (Japanese): scope (run / sweep), processor name, processed file count, output path, excluded runs (failures + non-success runs), next suggested action (`/analyze-results <run_id>` or `/analyze-results --sweep <sweep_id>`).

## Hard rules

- The processor is the ONLY writer to `data/processed/<experiment_id>/`. Manual edits violate `research-integrity.md` data handling.
- The processor MUST be deterministic given the same inputs. The skill verifies this on `--rewrite`: a fresh run should produce identical output hashes.
- Failed processor invocations are recorded under `failures[]`, NOT silently dropped.
- Non-success runs (crash / aborted / safe-stop / interrupted) are excluded from collection and reported as exclusions — they are not "missing data", they are explicit non-data.
- Never delete files under `data/processed/`. If a processor needs to change schema, write to a new sub-directory (e.g. `<sweep_id>-v2/`) or bump the processor version.

## Why a separate skill, not part of /analyze-results

`/collect-data` is operationally distinct from `/analyze-results`:

- For sim, collection is often trivial — the same skill exists for symmetry.
- For device/HIL, the raw telemetry is typically large, oscilloscope-format, and needs vendor-specific decoders that are slow. Separating ingestion from analysis lets the user re-run analysis (cheap) without re-ingesting (expensive).
- Different failure modes: a processor bug is fixed in `src/analysis/processors/`; an analysis bug is fixed in `src/analysis/<name>_analysis.py`.

## Examples

| User input | Effect |
|---|---|
| `/collect-data 2026-05-14T12-34-56_a1b2c3d4` | Ingest one run with the experiment's default processor. |
| `/collect-data --sweep solver-baseline-sweep-2026-05-14T13-00-00` | Ingest every successful run in the sweep. |
| `/collect-data 2026-05-14T12-34-56_a1b2c3d4 --processor merge-traces` | Use a named processor. |
| `/collect-data --sweep <id> --rewrite` | Re-process even if `.processor.json` already exists; verifies determinism. |
