# Experiment Orchestrator

> Claude Code (Opus 4.7, 1M context) as orchestrator, coordinating Codex CLI and Gemini CLI as specialized agents for **code-first experimental research** — simulation, real-device, and hardware-in-the-loop. The codebase and its recorded runs are the artefact; reports are optional.

```
Claude Code (Orchestrator) ─┬─ Codex CLI       (pre-run review, debugging, contract critique)
                             ├─ Gemini CLI      (datasheets, manuals, figures, multimodal)
                             ├─ build-engineer  (CMake / Cargo / Make / toolchain, MPI, containers)
                             └─ device-operator (calibration, telemetry, safe-stop)
```

- **8 role-based agents** — `experiment-runner`, `build-engineer`, `device-operator`, `data-analyst`, `script-reviewer`, `viz-reviewer`, `codex-debugger`, `gemini-explore`
- **16 skills** across 4 buckets — 5 pipeline (`init-experiment` → `design-experiment` → `build-experiment` → `run-experiment` → `analyze-results`), 4 device/HIL helpers (`lock-device`, `calibrate-device`, `collect-data`, `sweep-experiment`), 4 operations (`review-script`, `review-figures`, `lint`, `checkpoint`), 3 output / adapters (`write-report`, `ask-codex`, `ask-gemini`)
- **6 rules** for research integrity, statistical rigor, reproducibility, safety (HIL hard rule), agent routing, and language policy
- **7 hooks** — agent router, CLI logger, error→codex, reproducibility check, **safety check** (blocks unsafe device/HIL Bash launches), session-start (with orphan-run reaper), session-end (with held-lock warning)
- **3 runtimes** at v1 — Python (`uv`), C++ (`cmake`), Rust (`cargo`) plus a generic `make` slot. Native binaries get content-addressable `build_id`s under `data/builds/<build_id>/`
- **3 execution targets** — `sim`, `device`, `hil`. A sim-precompute-then-device-playback workflow is modeled as two runs sharing an `experiment_family`
- **HPC scheduler aware** — `compute_target: cluster` captures Slurm/PBS/LSF/SGE/Kubernetes job metadata

## Scope

This template is for projects where **the experimental codebase and its recorded runs are the deliverable** — CFD solvers, robot controllers, MEMS measurement, numerical-method benchmarks, HIL test rigs. Writing a paper is allowed but not the centerpiece; `/write-report` ships as an optional output skill. For paper-centric research (literature review → IMRaD → peer review → submission), use the sibling template [`claude-research`](https://github.com/ohayotaro/claude-research) instead.

The pipeline is `design → build → run → collect → analyze → (optional) report`, not `lit-review → hypothesis → IMRaD`.

## Quick start

Install prerequisites first (see [Prerequisites](#prerequisites)). Then, in your project directory:

```bash
cd /path/to/your-project
git clone --depth 1 https://github.com/ohayotaro/claude-experiment.git .starter \
  && cp -r .starter/.claude .starter/CLAUDE.md . \
  && rm -rf .starter
claude
```

Inside Claude Code:

```
/init-experiment    # domain / project_name / objective / runtime / execution_target /
                    # compute_target / scheduler / safety owner / viz preference
```

After the wizard, `CLAUDE.md` Zone B describes your project, `src/utils/{repro.py,viz.py}` are placed from `.claude/templates/python-uv/` (regardless of the resolved runtime — analysis still runs in Python), and `docs/`, `src/`, `data/`, `tests/`, `notebooks/` are scaffolded. The standard `data/` layout includes `data/builds/`, `data/calibrations/`, and `data/locks/` for native builds and device/HIL workflows.

Subsequent flow. Argument conventions: `<experiment_id>` matches an entry in Zone B `experiments:`; `<device_id|bench_id>` matches the lock file name under `data/locks/`. The two are intentionally distinct — multiple experiments can share one device.

```
/design-experiment <experiment_id>          # register an experiment
/review-script <path>                        # pre-run strict review (cleanup-handler check for device/HIL)
/build-experiment <experiment_id>            # native runtimes only (python-uv → uv sync)
/lock-device <device_id|bench_id>            # device / HIL only — acquire the lock
/calibrate-device <experiment_id>            # device / HIL only — fresh calibration sidecar
/run-experiment <experiment_id>              # authoritative preflight + execution + metadata
   ↳ /sweep-experiment <experiment_id> ...   # alt. — N runs sharing one sweep_id
/collect-data <run_id> | --sweep <sweep_id>  # optional — ingest raw outputs into data/processed/
/analyze-results <run_id> | --sweep <id>     # pre-registered analysis (honors inference_kind)
/review-figures <run_id>                     # Gemini-backed multimodal critique
/write-report --scope <run_id|sweep_id|project>   # optional — memo / data card / paper
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

Codex and Gemini are recommended but not blocking. Without Codex, `/review-script`, `/ask-codex`, and `codex-debugger` fall back to Opus subagents acting as critics (weaker). Without Gemini, `/review-figures` and `/ask-gemini` emit `status: blocked` and the orchestrator decides.

## What gets copied into your project

```
your-project/
├── CLAUDE.md                       # 3-Zone orchestrator contract
├── pyproject.toml                  # uv non-package mode + dev deps
├── .gitignore                      # data/raw, data/processed, .venv/, in-tree build/
├── .claude/
│   ├── settings.json               # hook wiring (PostToolUseFailure, PreToolUse Bash, ${CLAUDE_PROJECT_DIR})
│   ├── routing-keywords.json
│   ├── rules/                      # 6 domain rules
│   ├── hooks/                      # 7 Python hooks
│   ├── agents/                     # 8 role-based agents
│   ├── skills/                     # 16 skill definitions
│   └── templates/                  # repro.py + viz.py + per-runtime build stubs
└── docs/research/                  # methodology, analysis, incidents, hardware/<id>.md
```

`docs/`, `src/`, `data/`, `tests/`, `notebooks/` are scaffolded by `/init-experiment` and left alone afterward. The template owns nothing outside the four paths above plus `CLAUDE.md` Zone A.

## Reproducibility contract

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

Native builds are content-addressable: same source + same toolchain ⇒ same `build_id` (cache hit, no rebuild). `build_id` is a pure 16-character lowercase hex digest of the inputs — no timestamp, so identical inputs always collide on the cache. Wall-clock lives in `manifest.started_at` / `finished_at`. The manifest records `compiler_version`, `build_flags`, `mpi.version`, `container.digest`, every produced binary's SHA-256, and a smoke-test result.

The `reproducibility-check` hook validates run metadata and build manifests on every write under `data/results/` or `data/builds/`. The orphan-run reaper in `session-start.py` patches `exit_state: interrupted` onto runs whose wrapper died before `finalize_metadata` could be called.

## Safety contract (HIL hard rule)

For any run with resolved `execution_target ∈ {device, hil}`, enforcement is layered:

| Layer | Authority |
|---|---|
| `safety-check` hook (`PreToolUse: Bash`) | Coarse gate — blocks obvious direct entrypoint launches when locks / calibration / bench self-check are missing. Verifies the lock is held by **this session's process chain**, not just "some live PID". |
| `/run-experiment` skill | Authoritative preflight — resolves config, computes hashes, verifies every precondition in `safety-hil.md` §1, gathers operator confirmation, writes safety fields into metadata. |
| `device-operator` agent | Operational executor — calibration, bench self-check, telemetry, abort / safe-stop. |

Three escape hatches: `--dry-run` (recorded as `metadata.device.dry_run`), `safety_class: none` (declares a read-only experiment), and `--override-safety=<check>:<reason>` (single-check, logged, requires `hil_safety_owner` to confirm interactively). The lock check and operator-confirmation check cannot be overridden.

Sim, device, and HIL paths are all operational. For device/HIL, run `/lock-device <id>` to acquire the lock, `/calibrate-device <id>` to produce a fresh calibration, then `/run-experiment <id>`. Each non-sim run aborts cleanly if any precondition fails; no unsafe launch is possible.

## Skills

16 skills organized by bucket. Full spec for each is at `.claude/skills/<name>/SKILL.md`. The "Owner" column lists the agent or external CLI that performs the heavy work; the orchestrator drives the flow but does not implement.

### Pipeline

| Skill | Purpose | Owner |
|---|---|---|
| `/init-experiment` | Domain, project name, objective, runtime, execution_target_default, compute_target, scheduler, safety owner. Populates Zone B and copies starter scripts into `src/utils/`. | — |
| `/design-experiment <id>` | Register one experiment in `experiments:` registry; write per-experiment methodology section; scaffold `src/experiments/<id>/`. | — |
| `/build-experiment [<id>]` | Native runtimes: produce `data/builds/<build_id>/manifest.json` with full toolchain provenance; reuse on input match. `python-uv`: `uv sync` only. | build-engineer |
| `/run-experiment [<id>]` | Authoritative preflight (incl. `safety-hil.md` §1 for device/HIL) + execution. Writes `data/results/<run_id>/`. | experiment-runner (+ device-operator on device/HIL) |
| `/analyze-results <run_id>` | Pre-registered analysis honoring `inference_kind` from methodology. Appends to `docs/research/analysis.md`; generates figures via `src/utils/viz.py`. | data-analyst |

### Device / HIL helpers

| Skill | Purpose | Owner |
|---|---|---|
| `/lock-device <id>` | Acquire `data/locks/<id>.lock` for a device or HIL bench. Required by `safety-check` before any device run. Breaks stale locks (dead PID) with two-layer confirmation. | — |
| `/calibrate-device <id>` | Run the experiment's calibration script under `device-operator`, save artefact + sidecar to `data/calibrations/`. | device-operator |
| `/collect-data <run_id>` or `/collect-data --sweep <sweep_id>` | Post-run ingestion of raw telemetry into `data/processed/`. Idempotent (cache-hit check runs before the processor). | data-analyst (processor) |
| `/sweep-experiment <id>` | Parameter sweep (grid / list / random) producing run_ids grouped under a shared `sweep_id`. Serial on device/HIL, parallel-capable on sim. | orchestrator (+ experiment-runner per run) |

### Operations

| Skill | Purpose | Owner |
|---|---|---|
| `/review-script <path>` | Pre-run strict review (statistics, leakage, reproducibility, cleanup-handler for device/HIL). Writes verdict consumed by `/run-experiment`. | script-reviewer + Codex |
| `/review-figures <run_id>` | Multimodal review of rendered figures (chart choice, color, typography, accessibility). | viz-reviewer + Gemini |
| `/lint` | Run `ruff` + `mypy` + `pytest` on touched modules. | — |
| `/checkpoint` | Snapshot current phase, last `run_id` / `build_id`, held locks, recent artifacts, next action into Zone C. | — |

### Output / adapters

| Skill | Purpose | Owner |
|---|---|---|
| `/write-report` | Optional output: technical memo, data card, or paper (per Zone B `reports.default_kind`). Never auto-submits. | data-analyst + orchestrator |
| `/ask-codex` | One-shot Codex call for quick logical / statistical sanity checks. Does not write to `docs/`. | Codex |
| `/ask-gemini` | One-shot Gemini call for datasheet / manual / figure lookups. Does not write to `docs/`. | Gemini |

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

- **Codex** receives English-only structured prompts and returns severity-tagged comments (`blocker | major | minor | nit`) with `id`, `category`, `comment`, `suggested_fix` per issue.
- **Gemini** receives multimodal input (URLs, file paths) and returns markdown with explicit source URLs / DOIs, or strict JSON when the caller specifies.
- **Sonnet subagents** are role-named (e.g. `experiment-runner`, `build-engineer`), runtime-aware via Zone B Resolution.
- All agents emit a YAML `handoff:` block (schema in `.claude/rules/agent-routing.md`) with `agent`, `status`, `artifacts`, `recommended_next` so the orchestrator can plan downstream work.
- When an external CLI is unavailable, agents emit `status: blocked` — they never silently degrade. The orchestrator decides whether to fall back, ask the user to install the CLI, or pause.

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
