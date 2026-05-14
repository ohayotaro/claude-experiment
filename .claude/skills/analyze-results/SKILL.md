---
name: analyze-results
description: Run the pre-registered analysis on one or more completed runs. Produce effect sizes (or descriptive stats), CIs, and figures. Honors `inference_kind` from methodology to scope statistical-rigor.md activation.
when_to_use: After /run-experiment.
inputs:
  - run_id (one or more — single run, sweep, or explicit list)
  - docs/research/methodology.md (read — the experiment's pre-registered analysis plan)
outputs:
  - docs/research/analysis.md (one ## Run <run_id> or ## Sweep <sweep_id> section appended per invocation)
  - data/results/<run_id>/figures/{*.png,*.pdf}
  - src/analysis/<name>_analysis.py (the script that produced the analysis; committed for reproducibility)
delegated_agent: data-analyst
next_skill: /review-figures (recommended), or `/write-report` (ships after the core skills) when ready to communicate outwards
---

# /analyze-results

## Steps for the orchestrator

1. **Pre-flight.**
   - For each requested `run_id`, verify `data/results/<run_id>/metadata.json` exists and `exit_state` is `success`. Refuse to include `crash` / `aborted` runs in confirmatory analysis (they may be included as exploratory context with explicit labeling).
   - Resolve the `experiment_id` and look up `inference_kind` in `docs/research/methodology.md`. Pass this to `data-analyst` — `statistical-rigor.md` applies fully for `comparison` / `sweep-inference`, partially for `descriptive`, not at all for `none`.
   - If the user passes multiple `run_id`s with mismatched `experiment_id`, ask whether to analyze them as one cross-experiment comparison (advanced) or one by one.
2. **Launch** `data-analyst` with the run(s), the methodology, and the resolved `inference_kind`.
3. **Receive** results. The agent labels confirmatory vs exploratory and provides effect sizes / CIs (or descriptive statistics for `inference_kind: descriptive`).
4. **Sanity check** in the orchestrator: every reported number traces to a file under `data/results/<run_id>/`. If any number cannot be sourced, return to `data-analyst` with the gap.
5. **Honor exclusions explicitly.** If `data-analyst` excluded a run (e.g. `safe-stop`, `crash`, outlier per pre-registered rule), the analysis section MUST list the excluded `run_id` and the rule. Selective inclusion without disclosure is forbidden (`.claude/rules/research-integrity.md`).
6. **Update Zone C**: `current_phase: analyze`, `next_action: "Run /review-figures, then /write-report (if you plan to share the result)"`.

## Idempotence rule

`/analyze-results` **always appends** a new `## Run <run_id>` (or `## Sweep <sweep_id>`) section to `docs/research/analysis.md`. It never rewrites or removes a previously-recorded run. Use `/analyze-results --rewrite <run_id>` (or manually edit the file) if you genuinely need to replace a prior section — and document why under "Deviations" within the new section.

## Failure modes

- All requested runs failed → refuse to produce a confirmatory analysis. Suggest the user investigate via `/ask-codex` or `codex-debugger`, then re-run.
- Methodology absent for the resolved experiment → abort with a pointer to `/design-experiment`.
- `data-analyst` reports the analysis cannot be performed as pre-registered (e.g. assumption violated) → record the issue as an exploratory note; never silently switch tests.
