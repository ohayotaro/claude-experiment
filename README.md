# Experiment Orchestrator

> Claude Code (Opus 4.7, 1M context) as orchestrator, coordinating Codex CLI and Gemini CLI as specialized agents for **code-first experimental research** — simulation, real-device, and hardware-in-the-loop. The codebase and its recorded runs are the artefact; reports are optional.

```
Claude Code (Orchestrator) ─┬─ Codex CLI       (pre-run review, debugging, contract critique)
                             ├─ Gemini CLI      (datasheets, manuals, figures, multimodal)
                             ├─ build-engineer  (CMake / Cargo / Make / toolchain, MPI, containers)
                             └─ device-operator (calibration, telemetry, safe-stop)
```

- **8 role-based agents** — `experiment-runner`, `build-engineer`, `device-operator`, `data-analyst`, `script-reviewer`, `viz-reviewer`, `codex-debugger`, `gemini-explore`
- **11 core skills** shipped today (`init-experiment`, `design-experiment`, `build-experiment`, `run-experiment`, `analyze-results`, plus `review-script`, `review-figures`, `lint`, `checkpoint`, `ask-codex`, `ask-gemini`); device/HIL helpers (`lock-device`, `calibrate-device`, `collect-data`, `sweep-experiment`, `write-report`) ship next
- **6 rules** for research integrity, statistical rigor, reproducibility, safety (HIL hard rule), agent routing, and language policy
- **7 hooks** — agent router, CLI logger, error→codex, reproducibility check, **safety check** (blocks unsafe device/HIL Bash launches), session-start (with orphan-run reaper), session-end (with held-lock warning)
- **3 runtimes** at v1 — Python (`uv`), C++ (`cmake`), Rust (`cargo`) plus a generic `make` slot. Native binaries get content-addressable `build_id`s under `data/builds/<build_id>/`
- **3 execution targets** — `sim`, `device`, `hil`. A sim-precompute-then-device-playback workflow is modeled as two runs sharing an `experiment_family`
- **HPC scheduler aware** — `compute_target: cluster` captures Slurm/PBS/LSF/SGE/Kubernetes job metadata

---

## このテンプレートは何のため？

`claude-research` が **論文を最終成果物**にした研究テンプレなのに対し、本テンプレートは **実験コード自体（と再現可能な run の記録）が成果物** となるプロジェクト向けです。CFD ソルバ開発、ロボット制御、MEMS 計測、数値手法ベンチマーク、HIL 試験など、論文化が optional なワークフロー全般を想定しています。

論文を出すこと自体は妨げません（`/write-report` skill が次フェーズで来ます）が、パイプラインの中心は **build → run → collect → analyze** であって lit-review → hypothesis → IMRaD ではありません。

## Quick start

前提ツールは下記 [Prerequisites](#prerequisites)。プロジェクトディレクトリで:

```bash
cd /path/to/your-project
git clone --depth 1 https://github.com/ohayotaro/claude-experiment.git .starter \
  && cp -r .starter/.claude .starter/CLAUDE.md . \
  && rm -rf .starter
claude
```

Claude Code 起動後:

```
/init-experiment    # domain / project_name / objective / runtime / execution_target / scheduler / safety owner
```

ウィザード完了後:

- `CLAUDE.md` Zone B にプロジェクト情報が記録され、`status: initialized` になります
- `src/utils/{repro.py,viz.py}` が `.claude/templates/python-uv/` から配置されます（runtime に関わらず Python 製ヘルパは常時必要）
- `docs/`, `src/`, `data/`, `tests/`, `notebooks/` をスキャフォールドします
- `data/builds/`, `data/calibrations/`, `data/locks/` も作成します（device/HIL を使わなくても layout は同じ）

その後の流れ:

```
/design-experiment <id>      # 実験 1 件を Zone B registry に登録
/review-script <path>        # 実行前レビュー（device/HIL は cleanup handler 必須）
/build-experiment <id>       # native runtime のみ（python-uv はスキップ）
/run-experiment <id>         # authoritative preflight + 実行 + metadata 完全記録
/analyze-results <run_id>    # 事前登録した解析（inference_kind に応じて統計厳格化）
/review-figures <run_id>     # Gemini で図のチェック
```

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Claude Code | latest | `npm i -g @anthropic-ai/claude-code` |
| Codex CLI | ≥0.130 | `brew install codex` (macOS) or `npm i -g @openai/codex` |
| Gemini CLI | latest | `npm i -g @google/gemini-cli` |
| Git | any | system package manager |
| Python | ≥3.12 | for hooks and the Python launcher; runs the analysis layer regardless of experiment runtime |
| `uv` | latest | `brew install uv` or `curl -LsSf https://astral.sh/uv/install.sh \| sh` |

Native runtimes additionally need (per-experiment basis):

| Runtime | Need |
|---|---|
| `cpp-cmake` | `cmake ≥3.20`, a C++20 compiler, optionally MPI |
| `rust-cargo` | `rustc ≥1.80` / `cargo` |
| `make` | GNU make + whatever the Makefile invokes |

Codex / Gemini は推奨ですが必須ではありません。Codex が無いと `/review-script`, `/ask-codex`, `codex-debugger` の品質が落ちます。Gemini が無いと `/review-figures`, `/ask-gemini` が `status: blocked` を返します。

## What gets copied into your project

```
your-project/
├── CLAUDE.md                       # 3-Zone orchestrator contract
├── pyproject.toml                  # uv non-package mode + dev deps
├── .gitignore                      # data/raw, data/processed, .venv/, in-tree build/
├── .claude/
│   ├── settings.json               # hook wiring
│   ├── routing-keywords.json
│   ├── rules/   (6 .md)            # integrity / repro / safety-hil / stats / routing / language
│   ├── hooks/   (7 .py)            # agent-router, error-to-codex, log-cli-tools,
│   │                               #   reproducibility-check, safety-check,
│   │                               #   session-start, session-end
│   ├── agents/  (8 .md)            # experiment-runner, build-engineer, device-operator,
│   │                               #   data-analyst, script-reviewer, viz-reviewer,
│   │                               #   codex-debugger, gemini-explore
│   ├── skills/  (11 SKILL.md)      # 5 core + 6 operations / adapters
│   └── templates/                  # repro.py + viz.py + per-runtime build stubs
└── docs/research/                  # methodology, analysis, incidents, hardware/<id>.md
```

`docs/`, `src/`, `data/`, `tests/`, `notebooks/` are scaffolded by `/init-experiment` and never owned by template updates after that.

## Reproducibility contract (highlights)

Every run produces `data/results/<run_id>/`:

```
metadata.json          # top-level + (sim | device | hil) block + optional scheduler block
config.snapshot.yaml   # immutable copy of the resolved experiment config
log.txt
results/               # raw outputs
figures/               # produced by /analyze-results
telemetry/             # device / HIL only
cleanup_log.txt        # device / HIL only
```

`metadata.json` records, on top of the obvious fields, `pid`, `entrypoint_sha256`, `config_snapshot_sha256`, and (for native runs) a `build_id` cross-reference to `data/builds/<build_id>/manifest.json`. The full schema and per-field writer responsibility are in `.claude/rules/reproducibility.md` §§2, 3, 9.

Native builds are content-addressable: same source + same toolchain ⇒ same `build_id` (cache hit, no rebuild). The manifest records `compiler_version`, `build_flags`, `mpi.version`, `container.digest`, every produced binary's SHA-256, and a smoke-test result.

The `reproducibility-check` hook validates run metadata and build manifests on every write under `data/results/` or `data/builds/`. The orphan-run reaper in `session-start.py` patches `exit_state: interrupted` onto runs whose wrapper died before `finalize_metadata` could be called.

## Safety contract (HIL hard rule)

For any run with resolved `execution_target ∈ {device, hil}`, enforcement is layered:

| Layer | Authority |
|---|---|
| `safety-check` hook (`PreToolUse: Bash`) | Coarse gate — blocks obvious direct entrypoint launches when locks / calibration / bench self-check are missing. Verifies the lock is held by **this session's process chain**, not just "some live PID". |
| `/run-experiment` skill | Authoritative preflight — resolves config, computes hashes, verifies every precondition in `safety-hil.md` §1, gathers operator confirmation, writes safety fields into metadata. |
| `device-operator` agent | Operational executor — calibration, bench self-check, telemetry, abort / safe-stop. |

Three escape hatches: `--dry-run` (recorded as `metadata.device.dry_run`), `safety_class: none` (declares a read-only experiment), and `--override-safety=<check>:<reason>` (single-check, logged, requires `hil_safety_owner` to confirm interactively). The lock check and operator-confirmation check cannot be overridden.

> **Phase availability** — the sim path is fully operational today. Device / HIL paths additionally require `/lock-device`, `/calibrate-device`, and `/collect-data` skills, which ship in the next batch. Until then, a device / HIL `/run-experiment` invocation aborts cleanly at the lock or calibration check; no unsafe launch is possible.

## Skills

11 skills shipped today. Full spec for each is at `.claude/skills/<name>/SKILL.md`. The "Owner" column lists the agent or external CLI that performs the heavy work; the orchestrator drives the flow but does not implement.

### Setup

| Skill | Purpose | Owner |
|---|---|---|
| `/init-experiment` | Domain, project name, objective, runtime, execution_target_default, compute_target, scheduler, safety owner. Populates Zone B and copies starter scripts into `src/utils/`. | — |
| `/design-experiment <id>` | Register one experiment in `experiments:` registry; write per-experiment methodology section; scaffold `src/experiments/<id>/`. | — |

### Build / Run / Analyze

| Skill | Purpose | Owner |
|---|---|---|
| `/build-experiment [<id>]` | Native runtimes: produce `data/builds/<build_id>/manifest.json` with full toolchain provenance; reuse on input match. `python-uv`: `uv sync` only. | build-engineer |
| `/run-experiment [<id>]` | Authoritative preflight (incl. `safety-hil.md` §1 for device/HIL) + execution. Writes `data/results/<run_id>/`. | experiment-runner (+ device-operator on device/HIL) |
| `/analyze-results <run_id>` | Pre-registered analysis honoring `inference_kind` from methodology. Appends to `docs/research/analysis.md`; generates figures via `src/utils/viz.py`. | data-analyst |

### Operations

| Skill | Purpose | Owner |
|---|---|---|
| `/review-script <path>` | Pre-run strict review (statistics, leakage, reproducibility, cleanup-handler for device/HIL). Writes verdict consumed by `/run-experiment`. | script-reviewer + Codex |
| `/review-figures <run_id>` | Multimodal review of rendered figures (chart choice, color, typography, accessibility). | viz-reviewer + Gemini |
| `/lint` | Run `ruff` + `mypy` + `pytest` on touched modules. | — |
| `/checkpoint` | Snapshot current phase, last `run_id` / `build_id`, held locks, recent artifacts, next action into Zone C. | — |

### Adapters

| Skill | Purpose | Owner |
|---|---|---|
| `/ask-codex` | One-shot Codex call for quick logical / statistical sanity checks. Does not write to `docs/`. | Codex |
| `/ask-gemini` | One-shot Gemini call for datasheet / manual / figure lookups. Does not write to `docs/`. | Gemini |

### Next batch (work in progress)

| Skill | Purpose |
|---|---|
| `/lock-device <id>` | Acquire `data/locks/<id>.lock` for a device or HIL bench. Required by safety-check before any device run. |
| `/calibrate-device <id>` | Run the experiment's calibration script, save artefact to `data/calibrations/<ref>.<ext>`, record metadata sidecar. |
| `/collect-data <run_id>` | Post-run ingestion of raw telemetry into `data/processed/`. |
| `/sweep-experiment <id>` | Parameter sweep producing run_ids grouped under a `sweep_id`. |
| `/write-report` | Optional output: technical memo, data card, or paper (per Zone B `reports.default_kind`). |

## Agents

| Agent | Backed by | Best at |
|---|---|---|
| `experiment-runner` | Sonnet | Writing the experiment driver (Python / native launcher), launching the run, capturing metadata |
| `build-engineer` | Sonnet | CMake / Cargo / Make, toolchain selection, cross-compilation, container/MPI setup, build manifest |
| `device-operator` | Sonnet | Device init, calibration, run start/abort/safe-stop, telemetry capture, cleanup |
| `data-analyst` | Opus | Statistical analysis, effect sizes, CIs, plotting |
| `script-reviewer` | Codex | Strict pre-run review of scripts (incl. device/HIL cleanup-handler verification) |
| `viz-reviewer` | Gemini | Multimodal review of rendered figures |
| `codex-debugger` | Codex | Root-cause analysis of script / build / runtime failures (Python, native, MPI) |
| `gemini-explore` | Gemini | Web / PDF / image / video lookups (datasheets, manuals, vendor docs) |

Every agent emits a YAML `handoff:` block (schema in `.claude/rules/agent-routing.md`) so the orchestrator can plan downstream work. When an external CLI is unavailable, agents emit `status: blocked` — they never silently degrade.

## Architecture

```
┌────────────────────────────────────────────────────────────┐
│      Claude Code (Opus 4.7, 1M)  — Orchestrator            │
├──────────────────┬──────────────┬──────────────────────────┤
│  Sonnet Subagents│  Codex CLI   │  Gemini CLI              │
│ experiment-runner│ pre-run rev. │ datasheets / manuals     │
│ build-engineer   │ debugging    │ figures / oscilloscope   │
│ device-operator  │ contracts    │ vendor docs              │
├──────────────────┴──────────────┴──────────────────────────┤
│  Opus Subagent: data-analyst (statistics + plotting)       │
└────────────────────────────────────────────────────────────┘
```

## Language protocol

| Channel | Language |
|---|---|
| Orchestrator ↔ User | Japanese (default) — polite form, no emojis |
| Agent ↔ Agent | English (fixed) |
| Agent ↔ Codex / Gemini | English (fixed) |
| Code / commit / docs / metadata | English (fixed) |
| Hook user-facing strings | Japanese (polite, `[hook-name]` prefix) |
| Operator-facing device prompts | Japanese OK (operator-facing chat, not stored) |

The single Japanese surface is the user ↔ orchestrator dialogue. Everything else is English so logs, handoffs, metadata files, and analysis scripts are uniform. See `.claude/rules/language.md`.

## Provenance

Forked from the same author's [`claude-research`](https://github.com/ohayotaro/claude-research) (paper-centric research template) by full copy-and-prune, then redesigned for code-first experimentation. The Phase 1–5 design audit was performed by a multi-pass Codex review; the resulting fixes are baked into the contracts in `.claude/rules/`.

Sibling templates by the same author:

- [`claude-orchestrator`](https://github.com/ohayotaro/claude-orchestrator) — financial trading specialization
- [`claude-fullstack-orchestrator`](https://github.com/ohayotaro/claude-fullstack-orchestrator) — web / mobile / backend
- [`claude-research`](https://github.com/ohayotaro/claude-research) — paper-centric research

## License

This template is yours to use however you like. The agents, skills, rules, prompts, hooks, and starter scripts are released into your project alongside your own license — pick one that suits the project (MIT / Apache 2.0 / CC-BY for data, etc.).
