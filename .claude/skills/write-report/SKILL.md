---
name: write-report
description: Optional output skill. Produce a technical memo, data card, or short paper from one experiment, one sweep, or the whole project, depending on Zone B `reports.default_kind` (or an explicit override). Never auto-produces; user must invoke.
when_to_use: After analysis is complete and the user is ready to communicate results outward (internal memo, public data card, conference paper). Skip entirely if `reports.default_kind: none`.
inputs:
  - --kind <memo|datacard|paper> — optional override of Zone B default
  - --scope <run_id|sweep_id|project> — required; what to write about
  - --venue <name> — required when kind=paper
  - --rewrite — optional; replace an existing draft instead of appending a new version
outputs:
  - docs/reports/<kind>/<slug>/draft.md (for memo, datacard) — Markdown
  - docs/reports/paper/<slug>/draft.md (for paper, when paper_format == markdown_bibtex)
  - docs/reports/paper/<slug>/main.tex (for paper, when paper_format == latex)
  - docs/reports/<kind>/<slug>/changelog.md — bullet log appended on every write
delegated_agent: data-analyst (sources numbers from data/processed/ + docs/research/analysis.md); orchestrator handles assembly
next_skill: /review-figures (if not already done), then external publication workflow (user-driven, this template does not auto-submit)
---

# /write-report

The template defers reporting. The pipeline's first-class outputs are `data/results/<run_id>/`, `data/builds/<build_id>/`, and `docs/research/analysis.md`. A report is a **derived view** of those, formatted for a specific audience. This skill produces that derived view; it never invents numbers.

## Kinds

| Kind | Audience | Length | Format | Required sources |
|---|---|---|---|---|
| `memo` | Internal collaborators, future-you | 1–3 pages | Markdown | One run or one sweep; `analysis.md` section for it. |
| `datacard` | Public data users, dataset consumers | 1–2 pages | Markdown | The whole project, OR one sweep treated as a published dataset. |
| `paper` | Conference / journal reviewers | 4–8 pages | Markdown+BibTeX or LaTeX (per Zone B / venue) | Methodology, analysis (one or many runs), discussion. References to `data/results/` and `data/builds/` for reproducibility appendix. |

When Zone B `reports.default_kind: none` AND `--kind` is NOT passed, the skill refuses unconditionally with `[write-report] このプロジェクトはレポート出力を off (reports.default_kind: none) にしています。出力したい場合は Zone B を更新してください。`

When the user explicitly passes `--kind <memo|datacard|paper>` while Zone B says `none`, the skill warns once that the project default disagrees and proceeds. Explicit user intent overrides the default, but the project default is not silently mutated.

## Steps for the orchestrator

1. **Resolve `--kind`.** Use `--kind` if passed (any of `memo | datacard | paper`); else Zone B `reports.default_kind`. If resolved to `none`, refuse per the policy above.
2. **Resolve `--scope`.**
   - `<run_id>` → single-run report (memo only).
   - `<sweep_id>` → sweep-level report (memo or datacard).
   - `project` → whole-project report (paper or datacard).
   - For `kind: paper`, only `<sweep_id>` or `project` make sense (a single run rarely justifies a paper).
3. **Resolve `--venue`** when `kind: paper`. Required field; controls front matter (anonymization rules, length limit, citation style).
4. **Allocate `<slug>`** — short kebab-case identifier the user picks at first invocation. Stored in `docs/reports/<kind>/<slug>/`.
5. **Pre-flight.**
   - For runs / sweeps in scope: `metadata.exit_state: success` (skip non-success runs and report exclusion counts).
   - `docs/research/analysis.md` has a `## Run <run_id>` or `## Sweep <sweep_id>` section for every scope entry. If not, abort with `/analyze-results` remediation.
   - For `kind: paper`: figures under each in-scope `data/results/<run_id>/figures/` have been through `/review-figures` (warn the user if any have unresolved blockers).
6. **Gather source material.** Delegate to `data-analyst` to assemble:
   - The numbers (effect sizes, CIs, descriptive stats) from `analysis.md` and from `data/processed/`.
   - The figures (paths only; the report references them).
   - The methodology (from `docs/research/methodology.md`).
   - The reproducibility appendix bullets: `run_ids`, `build_ids` referenced, `seeds`, `git_rev`, key `package_versions`.
7. **Assemble the draft** per template skeleton (kind-specific, below). Write to `docs/reports/<kind>/<slug>/draft.md` (or `main.tex` for paper+latex).
8. **Append to changelog.** `docs/reports/<kind>/<slug>/changelog.md`:
   ```markdown
   ## <ISO-8601 UTC> — version N
   - <one-line summary of what changed since the previous draft>
   - Scope: <run_id | sweep_id | project>
   - Source analysis section(s): <list>
   ```
9. **Update Zone C**: `current_phase: report`, `last_skill_run: write-report`. No change to `last_run_id` / `last_sweep_id`.
10. **Report** (Japanese): kind, scope, draft path, excluded runs, what is intentionally NOT in the draft (e.g. raw data, calibration sidecars — those stay in `data/`).

## Template skeletons

### memo

```markdown
# <title>

**Scope**: <run_id or sweep_id>
**Date**: <ISO>
**Author**: <from git config user.name>

## Question
1–2 sentences.

## Method
1 paragraph + pointer to docs/research/methodology.md.

## Result
The numbers, with effect sizes and CIs. Reference figures by relative path.

## What this does and does not show
Honest framing of scope.

## Reproducibility
- run_id / sweep_id: ...
- build_id: ...
- git_rev: ...
- seeds: ...
```

### datacard

```markdown
# Data card: <title>

## Dataset summary
What was measured / simulated, by whom, when.

## Provenance
- Source experiments: <list of run_ids or sweep_ids>
- Methodology: docs/research/methodology.md
- Calibration: data/calibrations/<refs> (device/HIL only)

## Schema
Columns / files, units, types, missingness.

## Known limitations
What the data should NOT be used for.

## License
(user fills in)

## Citation
(user fills in)
```

### paper

When `paper_format: markdown_bibtex`, the skeleton is the IMRaD sections (Introduction, Related Work, Method, Results, Discussion, Conclusion) with venue-specific length guidance. When `paper_format: latex`, the skeleton is a minimal LaTeX article with `\bibliography{}`. Either way, the report is a draft — the user is the author.

## Hard rules

- **Numbers must trace.** Every number that appears in the report must be backed by a file under `data/results/`, `data/processed/`, or `docs/research/analysis.md`. The skill rejects free-text numerical claims that cannot be traced.
- **Figures live in `data/results/<run_id>/figures/`** and are referenced by relative path. The report does NOT copy figures into `docs/reports/`; this is a hard rule because copies drift.
- **Excluded runs are listed in the report**, not hidden. Selective inclusion is `research-integrity.md` violation.
- **The skill never auto-submits** anywhere. A `paper` draft is a draft.
- **`docs/reports/` is gitignored by default for `kind: paper`** until the user explicitly commits (papers under review are confidential; data cards typically are not). The skill warns about this once.

## Examples

| User input | Effect |
|---|---|
| `/write-report --kind memo --scope 2026-05-14T12-34-56_a1b2c3d4` | Single-run memo. |
| `/write-report --scope solver-baseline-sweep-...` | Sweep-level memo (uses Zone B default kind). |
| `/write-report --kind datacard --scope project` | Project-level data card. |
| `/write-report --kind paper --scope project --venue "NeurIPS 2026"` | IMRaD draft. |
| `/write-report --kind paper --scope project --venue "..." --rewrite` | Replace the existing paper draft (after iteration). |
