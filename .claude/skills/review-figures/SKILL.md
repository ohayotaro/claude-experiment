---
name: review-figures
description: Multimodal review of rendered figures via Gemini. Critiques chart choice, color, typography, composition, accessibility, and data honesty. Recommended after /analyze-results.
when_to_use: After /analyze-results has produced figures under data/results/<run_id>/figures/. Re-runnable after fixes.
inputs:
  - run_id (required) — defaults to the most recent run if omitted
  - Optional: a specific figure path to review just one figure
outputs:
  - data/results/<run_id>/figures/review.md
  - .claude/logs/cli/<ISO>-gemini-vizreview-*.md (per figure)
delegated_agent: viz-reviewer
next_skill: fix-and-re-run (data-analyst), or proceed with downstream use of the figures
---

# /review-figures

Catches chart-type misuse, palette problems, axis dishonesty, and unreadable typography **before** figures are embedded in any report, slide, or downstream artefact.

## Steps for the orchestrator

1. **Resolve the target.**
   - If the user names a `run_id`, use that.
   - If the user gives a single figure path, scope to that one figure.
   - Otherwise, default to the most recent `run_id` under `data/results/` that contains a non-empty `figures/` subdirectory.
2. **Pre-flight.**
   - Gemini availability via `.claude/logs/setup-status.json`. If absent, abort and inform the user — Claude cannot reliably critique rendered figures alone. Suggest installing Gemini CLI or skipping this skill.
   - Verify `data/results/<run_id>/figures/` exists and has at least one figure.
3. **Launch** `viz-reviewer` with the run_id (or single path).
4. **Receive** the structured review. Surface to the user (in Japanese, polite, no emojis):
   - Per-figure verdicts (ready / needs-minor-polish / needs-rework / not-suitable-for-this-claim).
   - Aggregate counts: blockers / majors / minors.
   - Top 3 cross-figure issues.
   - Path to `figures/review.md`.
5. **Recommend next step**:
   - All `ready` → safe to embed in any downstream report or share externally.
   - Any `needs-rework` or `not-suitable-for-this-claim` → return to `data-analyst` to redraw, then re-run `/review-figures`.
   - Only `needs-minor-polish` → user judgment; minor fixes can land later.
6. **Update Zone C** lightly: `last_skill_run: review-figures`. Do not change `current_phase`.

## Common variants

- **Single-figure focused review**: user pastes a figure path or asks "review fig3 only" — pass that single path.
- **Re-review after redraw**: subsequent invocations overwrite `figures/review.md` with the new findings; the old one is retrievable from git history.
- **Pre-share check**: invoke once more right before figures are shared with collaborators or embedded in `/write-report`, to catch any post-analysis tweaks.

## Hard rules

- **Do not edit figure files or `src/analysis/`.** Reviews are advisory.
- **Do not skip Gemini.** A "review" without seeing the actual rendered figure is not a review — abort if Gemini is unavailable.
- The skill writes to `data/results/<run_id>/figures/review.md`. This is an analysis output and is appropriate to commit to git for the historical record. (`data/raw/` and `data/processed/` are gitignored; `data/results/<run_id>/` is generally tracked.)
