---
name: lint
description: Run ruff + mypy + pytest on the project (or on touched modules) and present results in a tidy summary. Convenience skill — no agent delegation.
when_to_use: Quick health check before /run-experiment, after large edits, or before committing. Complementary to /review-script (which is a Codex-backed semantic review).
inputs:
  - Optional: "all" (default) or a path / module name to scope the run
outputs:
  - Inline summary to the user
  - .claude/logs/lint/<ISO>.md (full output captured for later inspection)
delegated_agent: orchestrator (no subagent — direct Bash)
next_skill: any
---

# /lint

Runs the static / dynamic checks the project already configures in `pyproject.toml`. This is **not** a substitute for `/review-script` — `/lint` catches mechanical issues; `/review-script` catches semantic issues like data leakage or wrong test choice.

## Steps for the orchestrator

1. **Pre-flight.** `uv` available. `pyproject.toml` exists with `[project.optional-dependencies] dev` containing `ruff`, `mypy`, `pytest`. Run `uv sync --extra dev` if `.venv/` is missing or stale.
2. **Determine scope.**
   - Default: full project (`src/` + `tests/`).
   - User may pass a path (`src/experiments/foo.py`) or a directory.
3. **Create the log directory** `.claude/logs/lint/` and pick a path `.claude/logs/lint/<ISO>.md`.
4. **Run, in order, capturing each step's output:**
   ```bash
   uv run ruff check <scope>
   uv run ruff format --check <scope>
   uv run mypy <scope>
   uv run pytest <scope or tests/ — pytest scope rule below>
   ```
   - For pytest: if scope is a path under `src/`, translate to corresponding tests under `tests/` if a 1-to-1 file exists; otherwise run the full `tests/` suite.
   - Each step independent — do not stop on first failure. Collect all results.
5. **Write the log file** with sections per tool, exit code, and stderr/stdout.
6. **Print to user** (Japanese, polite, no emojis): a one-line per-tool result and the path to the full log. Example:
   ```
   [lint] 結果サマリ:
     ruff check     : OK (0 issues)
     ruff format    : OK
     mypy           : 2 issues
     pytest         : 14 passed, 1 failed
   詳細ログ: .claude/logs/lint/2026-05-03T11-22-33.md
   ```
7. **If anything failed**, suggest concrete next actions:
   - ruff issues → `uv run ruff check --fix <scope>` for auto-fixable ones, then re-run `/lint`.
   - format issues → `uv run ruff format <scope>`.
   - mypy issues → ask `experiment-runner` (for src/) or the user to address; usually annotation/type fixes.
   - pytest failures → `codex-debugger` agent (the `error-to-codex` hook will also fire on the underlying Bash failure).

## Hard rules

- **Read-only by default.** Never run `ruff check --fix` or `ruff format` (without `--check`) inside `/lint`. The user explicitly opts into mutation.
- **Do not run scripts under `src/experiments/`.** `pytest tests/` only; experiment scripts are not tests.
- If `uv sync` is needed, ask the user before running it (it can take time on first install).
