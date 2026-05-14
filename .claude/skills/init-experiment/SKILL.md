---
name: init-experiment
description: Bootstrap a new experimental codebase. Interactively collects domain, project name, objective, runtime, execution_target_default, compute_target, safety owner; writes CLAUDE.md Zone B; scaffolds docs/, src/, data/, notebooks/, tests/. Run this first.
when_to_use: First skill in a fresh project. Also re-runnable to update Zone B.
inputs: User answers via AskUserQuestion (Japanese)
outputs:
  - CLAUDE.md (Zone B updated; experiments: starts empty, to be populated by /design-experiment)
  - docs/research/{methodology,analysis,incidents}.md (placeholders)
  - docs/research/hardware/ (empty — populated when device/HIL experiments are added)
  - src/{experiments,analysis,utils}/__init__.py
  - src/utils/repro.py (reproducibility metadata helper for the resolved runtime)
  - src/utils/viz.py (if Python is the resolved runtime)
  - data/{raw,processed,results,builds,calibrations,locks}/.gitkeep
  - tests/test_smoke.py
  - notebooks/.gitkeep
  - .gitignore (with sensible defaults for the resolved runtime)
delegated_agent: orchestrator (no subagent)
next_skill: /design-experiment
---

# /init-experiment

Initializes an experimental codebase from the orchestrator template. The orchestrator runs this directly — no subagent.

## Steps

1. **Read** `CLAUDE.md` and `.claude/logs/setup-status.json` (if present).
2. **Ask the user** (Japanese) for the project parameters via `AskUserQuestion`. Suggested questions and defaults:
   - 研究分野（domain）— free text. Examples: cfd, robotics, mems, battery, control-systems, numerical-methods.
   - プロジェクト名（project_name）— short identifier.
   - 目的（objective）— one-line free text. What the codebase is supposed to demonstrate or measure. Translate to English internally.
   - ランタイム（runtime）— `python-uv` (default) / `cpp-cmake` / `rust-cargo` / `make` / `mixed`.
   - デフォルトの実行ターゲット（execution_target_default）— `sim` (default) / `device` / `hil`. Per-experiment overrides come later via `/design-experiment`.
   - デフォルトの計算ターゲット（compute.default_target）— `local` (default) / `cluster` / `device` / `hil`.
   - HPC スケジューラ（compute.scheduler.kind）— `none` (default) / `slurm` / `pbs` / `lsf` / `sge` / `kubernetes`. If non-none, also ask for `default_partition` and `default_walltime`.
   - レポート出力をデフォルト有効にするか（reports.default_kind）— `memo` (default) / `datacard` / `paper` / `none`.
   - 図表スタイル（viz_preferences.default_profile）— `default` (default) / `publication` / `presentation` / custom.
   - データ機微度（ethics.data_sensitivity）— none / low / medium / high.
   - IRB 必要か（ethics.irb_required）— bool.
   - **If** `execution_target_default ∈ {device, hil}` OR the user signals they plan to add device/HIL experiments: 安全オーナー（ethics.hil_safety_owner）— required, the human name responsible for safety on this project. Refuse to proceed without this.
3. **Build a Zone B YAML** from the answers. Preserve free-text fields verbatim (Japanese OK in Zone B). Keep `status: initialized`. The `experiments:` list starts empty:
   ```yaml
   experiments: []
   ```
4. **Write Zone B** by replacing the content between `<!-- ZONE_B_BEGIN -->` and `<!-- ZONE_B_END -->` in `CLAUDE.md`. Do not touch Zone A or Zone C.
5. **Scaffold directories** (idempotent):
   ```
   docs/research/
   docs/research/hardware/
   src/experiments/  src/analysis/  src/utils/
   src/native/        # only if runtime ∈ {cpp-cmake, rust-cargo, make, mixed}
   data/raw/  data/processed/  data/results/
   data/builds/  data/calibrations/  data/locks/
   notebooks/
   tests/
   ```
6. **Create placeholder files** (only if they do not exist):
   - `docs/research/methodology.md` — header only, with a "How to register a new experiment" note pointing to `/design-experiment`.
   - `docs/research/analysis.md` — header only.
   - `docs/research/incidents.md` — header only. Used by `device-operator` to log safe-stop events. Only meaningful for projects that will run device/HIL (sim-only projects can ignore it). Created either way for layout consistency.
   - `src/experiments/__init__.py`, `src/analysis/__init__.py`, `src/utils/__init__.py` (empty).
   - **Runtime-scoped starter scripts**. The launcher (Python) and the analysis layer are common across all runtimes, so `repro.py` and `viz.py` are always copied from `.claude/templates/python-uv/` regardless of `runtime`. Runtime-specific files are added on top:
     - For `python-uv`: just `repro.py` and `viz.py`.
     - For `cpp-cmake`: same Python helpers + a top-level `CMakeLists.txt` stub.
     - For `rust-cargo`: same Python helpers + a `Cargo.toml` stub with a workspace pointing at `src/native/`.
     - For `make`: same Python helpers + a top-level `Makefile` stub.
     - For `mixed`: same Python helpers; native bootstrap is deferred to `/design-experiment` per experiment.

     `repro.py` implements the six public functions in `.claude/rules/reproducibility.md` §9.3 (`make_run_id`, `set_seed`, `hash_file`, `write_initial_metadata`, `patch_metadata`, `finalize_metadata`) plus the three secondary read helpers (`read_build_manifest`, `verify_binary_hash`, `compute_source_tree_hash`).
   - `tests/test_smoke.py` — imports each src module to check the package is wired.
   - `data/raw/.gitkeep`, `data/processed/.gitkeep`, `data/results/.gitkeep`, `data/builds/.gitkeep`, `data/calibrations/.gitkeep`, `data/locks/.gitkeep`, `notebooks/.gitkeep`.
   - `.gitignore` from `.claude/templates/<runtime>/.gitignore` if it exists, else a generic one (always ignore: `build/`, `target/`, `__pycache__/`, `*.pyc`, `.venv/`, `data/raw/*` except `*.README.md`, `data/processed/*` except `.gitkeep`).
7. **Append** to `.claude/logs/init-experiment.log` an ISO-stamped record.
8. **Update Zone C** of `CLAUDE.md` to set `current_phase: design` and `next_action: "Run /design-experiment to register your first experiment"`.
9. **Report** to the user (Japanese) a summary: paths created, next suggested skill, plus a reminder to commit (`git add -A && git commit -m "init experiment scaffold"`) — but do not run git commands without confirmation.

## Idempotence rules

- Re-running `/init-experiment` is allowed and **only** rewrites Zone B. It does **not** overwrite any existing `docs/research/*.md` content (only creates them if absent).
- It does **not** touch existing files under `src/`, `data/`, `tests/`, or `notebooks/`.
- It does **not** modify an existing `experiments:` registry. To add an experiment, use `/design-experiment`.

## Hard rules

- Do not delete user content. If a placeholder already has more than the header, leave it alone.
- Do not change Zone A.
- For device/HIL projects: refuse to set `status: initialized` until `ethics.hil_safety_owner` is non-null. Surface this explicitly to the user in Japanese.
- The `git_clean` check in any later experiment requires this repo to be a git repo. After scaffold, suggest `git init && git add -A && git commit -m "init experiment scaffold"` — but do not run without confirmation.

## Source of starter scripts

Starter scripts live under `.claude/templates/<runtime>/` and are copied
verbatim. The template repo tracks them as real source files so they can be
linted and tested without inline copies in this SKILL.md. See
`.claude/templates/README.md` for the full structure and the contract for
adding a new runtime.

For `runtime: python-uv`:

| Copy from | Copy to |
|---|---|
| `.claude/templates/python-uv/repro.py` | `src/utils/repro.py` |
| `.claude/templates/python-uv/viz.py` | `src/utils/viz.py` |
| `.claude/templates/python-uv/pyproject.toml` | `pyproject.toml` (only if absent) |
| `.claude/templates/python-uv/.gitignore` | `.gitignore` (only if absent) |

For native runtimes, the same pattern applies with the runtime-specific build manifest stub (`CMakeLists.txt`, `Cargo.toml`, `Makefile`).
