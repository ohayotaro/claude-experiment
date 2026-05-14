---
name: build-experiment
description: For native runtimes (cpp-cmake / rust-cargo / make), compile and produce data/builds/<build_id>/manifest.json with full provenance, reusing an existing build when source+toolchain inputs match. For python-uv, run `uv sync` only — no build_id is produced.
when_to_use: After /design-experiment for a new native experiment. Re-runnable after any source or toolchain change. Optional but harmless to invoke on a python-uv experiment (it just ensures the env is in sync).
inputs:
  - experiment_id (optional — if omitted, build the registry's first non-python-uv entry, or `uv sync` if all entries are python-uv)
  - --rebuild (optional flag forcing fresh build; ignored for python-uv)
  - --container (optional override — name of the container image to build inside; ignored for python-uv)
outputs:
  - data/builds/<build_id>/ (manifest.json, build.log, produced binaries) — native only; python-uv produces no manifest.
  - .claude/logs/uv-sync.log — python-uv only.
delegated_agent: build-engineer (native runtimes only; python-uv path is handled inline by the orchestrator)
next_skill: /run-experiment
---

# /build-experiment

For native runtimes (`cpp-cmake` / `rust-cargo` / `make`) the skill wraps `build-engineer` and produces an immutable build manifest. For `runtime: python-uv` the skill runs `uv sync` and does NOT produce a `build_id` or manifest; runs of pure-Python experiments record `build_id: null` in their metadata.

## Steps

1. **Resolve `experiment_id`** (per `CLAUDE.md` §Resolution). If the user passed one, use it. If absent and exactly one experiment exists in Zone B, confirm with the user before defaulting. If multiple exist, ask.
2. **Read the registry entry**. Extract `runtime`, `entrypoint`, `compute_target`.
3. **Branch on runtime**.
   - `python-uv`: run `uv sync` (lock + install). Record `pyproject.toml` SHA-256 and `uv.lock` SHA-256 to `.claude/logs/uv-sync.log` for diagnostics. Do NOT create a `build_id`; runs of this experiment record `build_id: null`. No build manifest is produced (`data/builds/` stays empty for pure-Python projects). Skip to step 8.
   - `cpp-cmake` / `rust-cargo` / `make`: continue.
4. **Delegate to `build-engineer`** with the registry entry, the `--rebuild` flag (if any), and the `--container` override (if any). The agent:
   - Probes the toolchain.
   - Computes the candidate `build_id` from inputs.
   - Reuses an existing matching build OR compiles afresh.
   - Writes `data/builds/<build_id>/manifest.json`.
   - Runs a smoke test on the produced binary.
5. **Receive** the agent's structured handoff. Verify (the manifest schema is in `.claude/rules/reproducibility.md` §3.2):
   - `data/builds/<build_id>/manifest.json` exists and parses.
   - `manifest.exit_state` is one of `success`, `smoke_failed`, `failed`.
   - For `success`: artifact files exist on disk with matching SHA-256, and `manifest.smoke_test.exit_code == 0`.
6. **On `failed` or `smoke_failed`**: surface the agent's report to the user (Japanese) including the path to `build.log`. Suggest `/ask-codex` with the relevant build-log slice, or invoke `codex-debugger` if the user wants a structured root-cause analysis. Do NOT delete the partial build directory.
7. **On `success`**: surface a one-paragraph summary including `build_id`, smoke-test result, and whether the build was cache-reused.
8. **Update Zone C**: `last_build_id: <id or null>`, `current_phase: build` (only if it was earlier in the pipeline), `next_action: "Run /run-experiment <experiment_id>"`.

## Hard rules

- The skill never modifies a manifest after `build-engineer` has written it. Manifests are immutable.
- The skill never deletes anything under `data/builds/`. The user does that consciously when reclaiming disk.
- The skill never proceeds to `/run-experiment` automatically — the user runs it explicitly.
- If `build-engineer` reports a toolchain probe failure (missing compiler / MPI), the skill surfaces the missing item and the suggested install command, then exits without attempting a partial build.
- For container builds: refuse to proceed if the container engine (Docker / Podman) is not on PATH. Do not fall back to host build.

## Examples

| User input | Effect |
|---|---|
| `/build-experiment solver-baseline` | Builds (or reuses) the `solver-baseline` experiment with default settings. |
| `/build-experiment solver-baseline --rebuild` | Forces a clean build even if a matching `build_id` exists. |
| `/build-experiment solver-baseline --container=hpc-base:2026-04` | Builds inside the named container image. |
