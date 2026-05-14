# Agent routing

The orchestrator is Claude Opus. It does **not** implement; it integrates results from specialists. This file is the canonical routing matrix.

For `execution_target` resolution (per-run target is one of sim / device / hil; there is no `mixed` value at run scope — see `.claude/rules/reproducibility.md` §2). For safety preconditions on device/HIL runs, see `.claude/rules/safety-hil.md`. The orchestrator MUST resolve `experiment_id` before delegating to `experiment-runner`, `build-engineer`, or `device-operator`.

## Specialists

| Agent | Backed by | Best at |
|---|---|---|
| `experiment-runner` | Sonnet | Writing the experiment driver (Python/C++/Rust glue), launching the run, capturing metadata, handling exit states |
| `build-engineer` | Sonnet | Native build systems (CMake / Cargo / Make), toolchain selection, cross-compilation, container/MPI setup, producing `build_id` |
| `device-operator` | Sonnet | Physical device initialization, calibration sequence, start/abort/safe-stop, telemetry capture; reads safety-hil.md |
| `gemini-explore` | Gemini CLI | Multimodal: PDFs (datasheets, manuals), figures, vendor screenshots, web docs |
| `data-analyst` | Opus | Statistical analysis, effect sizes, CIs, plotting |
| `script-reviewer` | Codex | Strict pre-run review of experiment / analysis scripts (statistics, leakage, reproducibility, numerical edge cases, test coverage) |
| `viz-reviewer` | Gemini | Multimodal review of rendered figures (chart choice, color, typography, composition, accessibility) |
| `codex-debugger` | Codex | Root-cause analysis of script / build / runtime failures |

## Routing triggers

The `agent-router` hook (`.claude/hooks/agent-router.py`) reads `.claude/routing-keywords.json` and suggests agents based on user prompts.

| Trigger | Suggested agent |
|---|---|
| "implement", "script", "run", "code this up", "execute" | `experiment-runner` |
| "build", "compile", "CMake", "Cargo", "Makefile", "toolchain", "MPI", "cross-compile" | `build-engineer` |
| "device", "calibrate", "telemetry", "abort", "e-stop", "safe-stop", "DAQ", "instrument" | `device-operator` |
| "datasheet", "manual", "figure", "image", "chart", "screenshot", "video" | `gemini-explore` |
| "analyze", "statistics", "p-value", "effect size", "plot" | `data-analyst` |
| "review my script", "code review", "leakage", "before running" | `script-reviewer` (delegates to Codex) |
| "review the figures", "figure quality", "chart looks", "color choice" | `viz-reviewer` (delegates to Gemini) |
| "error", "exception", "stacktrace", "doesn't work", "debug", "crash", "core dump" | `codex-debugger` |

## When to NOT delegate

The orchestrator handles these directly:
- Short clarifying Q&A with the user.
- Choosing between two paths the user has presented.
- Reading Zone B / Zone C of `CLAUDE.md`.
- Routing decisions (which agent next).
- Resolving `experiment_id` against the Zone B registry.
- Anything under ~10 lines of output that doesn't require deep context.

## Parallelism

- `build-engineer` and `experiment-runner` can run in parallel during initial setup: one wires the build, the other drafts the run driver.
- `data-analyst` and `experiment-runner` can run in parallel once a previous run's data is in `data/processed/`: analyst plots while runner prepares the next replicate.
- `device-operator` is **never** parallel with another device-operator on the same `device_id` — the resource lock enforces this.
- `script-reviewer` is always serial (it reads finished code).

## Standard handoff schema

Every agent that completes a step appends a YAML handoff block as the **last section** of its written output (or in its reply to the orchestrator if the output is purely conversational). The orchestrator parses this to plan the next step.

```yaml
handoff:
  agent: <my-agent-name>
  status: success | partial | blocked
  artifacts:                      # files (re-)written this turn
    - path: data/results/...
      kind: run-output | build-manifest | metadata | log | analysis | figure | script | config-snapshot | lock
      summary: <one-line>
  open_risks:                     # list[str] — short
    - "..."
  next_agent_inputs:              # what the next agent needs from me
    primary_input: <path or null>
    notes: "..."
  recommended_next:               # may be null if the orchestrator decides
    skill: /<skill-name>
    rationale: <one-sentence>
```

`status: blocked` means the agent stopped because of an upstream contract issue (missing build_id, stale calibration, unresolved experiment_id, blocked by safety-hil) and is asking the orchestrator for a decision before continuing. Always-required fields are `agent`, `status`. Other fields are optional but encouraged.

## Hook → agent payload schemas

When a hook surfaces a delegation suggestion, it implies the orchestrator will pass a structured payload to the target agent. These contracts are documented in the relevant agent + the hook source:

- `error-to-codex` → `codex-debugger`: `{run_id_or_build_id, script_or_target_path, traceback_or_stderr, env, last_commit}`.
- `safety-check` → `device-operator`: `{experiment_id, device_id, bench_id?, reason, calibration_ref?, calibration_age_h?, lock_held: bool, bench_selfcheck_age_min?}`. The hook fills only the fields it could resolve from the filesystem; `/run-experiment` fills the rest during its own preflight.
- `agent-router` → user-facing hint only; no payload contract.

## Fallback policy (single source of truth)

When an external CLI partner is unavailable (`codex_available: false` or `gemini_available: false` in `.claude/logs/setup-status.json`):

1. The agent that needs the partner **fails loudly** with a clear `status: blocked` handoff and reports the missing dependency.
2. The orchestrator (not the agent) then decides whether to (a) ask the user to install/auth the CLI, (b) substitute an Opus subagent acting in the missing role with a reduced quality warning, or (c) pause the pipeline.

Agents must NOT silently degrade to a Claude `WebFetch` or other in-process fallback. Silent degradation has produced inconsistent retrieval policy in similar templates. The `research-keyword-detector`-class hooks print a warning but do not enact a fallback.
