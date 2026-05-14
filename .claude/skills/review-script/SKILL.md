---
name: review-script
description: Pre-run review of an experiment or analysis script (Python / C++ glue / Rust glue). Codex-backed strict checks for statistics, data leakage, reproducibility, numerical edge cases, cleanup-handler presence (device/HIL), and test coverage. Recommended before /run-experiment.
when_to_use: After authoring or modifying a script under src/experiments/ or src/analysis/, before invoking /run-experiment. Also re-runnable after fixes.
inputs:
  - Path to a script under src/experiments/ or src/analysis/ (required)
  - Optionally: a specific concern to focus on (free-text)
outputs:
  - .claude/logs/review/<script-slug>-<n>.md
  - .claude/logs/cli/<ISO>-codex-script-review-*.md
delegated_agent: script-reviewer
next_skill: /run-experiment (if zero blockers), or fix and re-run /review-script
---

# /review-script

The pre-run review pass. Catches statistical errors, data leakage, missing reproducibility hooks, missing cleanup handlers (mandatory for device/HIL entrypoints — see `.claude/rules/safety-hil.md` §1 item 6), and numerical pitfalls **before** the script writes anything to `data/results/`.

## Steps for the orchestrator

1. **Resolve the target.** The user names a path (or asks "review the latest experiment script" — in that case, take the most recently modified file under `src/experiments/`).
2. **Pre-flight.**
   - Codex availability check via `.claude/logs/setup-status.json`. If missing, warn the user and offer a Claude-subagent fallback (weaker).
   - Verify the script path exists and is under `src/experiments/` or `src/analysis/`.
   - For experiment scripts: verify `docs/research/methodology.md` exists. If not, abort and suggest `/design-experiment` first — a script without a locked methodology cannot be reviewed against intended design.
3. **Launch** `script-reviewer` with the script path and any user-specified focus area.
4. **Receive** the structured review. Surface to the user (in Japanese, polite form, no emojis):
   - Overall verdict.
   - Counts of blockers / majors / minors / nits.
   - Top 3 issues with one-line summary.
   - Path to the full review file.
5. **Recommend next step** based on verdict:
   - `ready-to-run` → `/run-experiment` is safe.
   - `needs-minor-fix` → suggest `experiment-runner` apply minor fixes, then `/run-experiment` (no re-review required).
   - `needs-major-fix` → suggest `experiment-runner` apply fixes, then `/review-script` again.
   - `reject` → significant rework needed; do not invoke `/run-experiment` until re-review passes.
6. **Update Zone C** lightly: `last_skill_run: review-script`, `next_action` per verdict. Do not change `current_phase`.

## Common variants

- **Focused review**: user asks "check only for data leakage" — pass that as the focus area; the agent narrows the Codex prompt accordingly.
- **Re-review after fix**: subsequent invocations get `<slug>-2.md`, `<slug>-3.md`, etc. The reviewer reads the previous review file to verify each prior issue is addressed (or explicitly deferred).

## Hard rules

- **Do not run the script.** This is a static review only. Execution is `/run-experiment`'s job.
- **Do not auto-apply fixes.** The reviewer returns suggestions; only the user or `experiment-runner` applies them.
- **Do not edit `docs/research/`.** Reviews live under `.claude/logs/review/`, not under `docs/`.
