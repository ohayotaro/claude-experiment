---
name: design-experiment
description: Register a new experiment in Zone B `experiments:` and write its methodology stub. Captures variables, success criteria, inference_kind, runtime/target/compute_target overrides, safety_class, optional config schema, and (for device/HIL) device_id / bench_id.
when_to_use: After /init-experiment. Once per experiment being defined. Re-runnable to edit an existing entry.
inputs: User answers via AskUserQuestion (Japanese)
outputs:
  - CLAUDE.md Zone B `experiments:` updated (entry added or modified)
  - docs/research/methodology.md updated (per-experiment section)
  - src/experiments/<experiment_id>/ scaffolded (run.py launcher, config.example.yaml, config.schema.json if requested)
  - docs/research/hardware/<device_id>.md placeholder (device/HIL only)
delegated_agent: orchestrator (no subagent; the orchestrator handles the registry edit + methodology drafting inline)
next_skill: /review-script (for the scaffolded run.py), then /build-experiment (native) → /run-experiment
---

# /design-experiment

Registers one experiment and writes its methodology. Subsequent skills resolve the entry via `CLAUDE.md` §Resolution.

## Steps

1. **Resolve `experiment_id`.**
   - If the user supplies one, validate it (regex `^[a-z0-9][a-z0-9-]{0,31}$`, lowercase only, no leading/trailing hyphen, no path separators).
   - Reject reserved names: `template`, `_template`, `latest`, `current`.
   - If absent, ask via `AskUserQuestion`.
   - If an entry with this id already exists, ask whether to edit or abort.
2. **Ask the user** (Japanese) for the experiment's parameters via `AskUserQuestion`:
   - 説明（description）— one-line free text.
   - 共通ファミリ（family）— optional; if multiple experiments compare against each other on the same metrics, share a family.
   - ランタイム（runtime）— inherit project default or override: `python-uv` / `cpp-cmake` / `rust-cargo` / `make`.
   - 実行ターゲット（execution_target）— inherit project default or override: `sim` / `device` / `hil`.
   - 計算ターゲット（compute_target）— inherit project default or override: `local` / `cluster` / `device` / `hil`.
   - エントリポイント（entrypoint）— required path relative to repo root. **Always a stable launcher script under `src/`**, conventionally `src/experiments/<id>/run.py`. For native runtimes, the launcher reads the resolved `build_id` and dispatches to the binary under `data/builds/<build_id>/...`; the registry never points directly at a built binary (binaries are non-stable across rebuilds). See `.claude/agents/experiment-runner.md` §"Native".
   - 推論種別（inference_kind）— `descriptive` / `comparison` / `sweep-inference` / `none`. Drives whether `statistical-rigor.md` applies fully. Default `descriptive`.
   - 主要指標（primary_outcome）— what gets measured.
   - 副次指標（secondary_outcomes）— optional list.
   - 成功基準（success_criteria）— what counts as the run passing.
   - 設定スキーマ（config_schema）— optional path to a JSON schema for the experiment's config; recommended for `inference_kind ∈ {comparison, sweep-inference}` so sweep parameters are validated.
   - 安全クラス（safety_class）— `none` (default for sim) / `calibration-required` / `destructive`. Required field.
   - **If** `execution_target ∈ {device, hil}`:
     - `device_id` — required.
     - 装置モデル — captured to populate `docs/research/hardware/<device_id>.md`.
     - 校正の有効期限（hours; default 24）.
   - **If** `execution_target == hil`:
     - `bench_id` — required.
     - `watchdog_ms_max` — bench's documented maximum.
3. **Validate cross-field constraints**:
   - `safety_class == none` AND `execution_target == hil` → warn the user (HIL with no safety class is unusual; confirm).
   - `safety_class == destructive` AND `execution_target == sim` → reject; destructive is meaningless for sim.
   - `compute_target == cluster` AND `runtime == python-uv` → allowed but warn that the user should confirm the cluster has uv installed.
4. **Append (or update) the experiments registry entry** in `CLAUDE.md` Zone B. Format:
   ```yaml
   - id: <id>
     family: <family or null>
     runtime: <runtime>
     execution_target: <target>
     compute_target: <compute>
     entrypoint: <path>
     safety_class: <class>
     config_schema: <path or null>
     device_id: <string or null>
     bench_id: <string or null>
   ```
5. **Write methodology section** in `docs/research/methodology.md` under an `## <experiment_id>` heading. Include:
   - Description.
   - `inference_kind` and which sections of `statistical-rigor.md` apply.
   - Primary / secondary outcomes.
   - Success criteria.
   - Pre-registered statistical test(s), threshold, and stopping rule (for `comparison` / `sweep-inference`).
   - Seed policy (single seed / multi-seed replication count).
   - For device/HIL: calibration freshness tolerance, ambient conditions to record, expected exit_state distribution under nominal operation.
6. **Scaffold `src/experiments/<experiment_id>/`** (only if absent):
   - `run.py` — launcher template appropriate to the runtime. For native, this is the Python driver that locates the binary; for python-uv, it is the experiment driver itself.
   - `config.example.yaml` — minimal example config.
   - `config.schema.json` — if the user specified one; else stub with a TODO comment.
   - For device/HIL: `device/__init__.py`, `device/calibrate.py` stub, `device/abort.py` stub (signal-handler boilerplate).
7. **For device/HIL**: create `docs/research/hardware/<device_id>.md` if absent, with vendor/model/firmware/datasheet-pointer headers. **For HIL**, additionally create `docs/research/hardware/<bench_id>.md` with bench identification, `watchdog_ms_max` (the value `device-operator` enforces), coupling specifics, and a pointer to the bench self-check procedure. The user fills in details, optionally with `/ask-gemini` for datasheet extraction.
8. **Update Zone C**: `current_phase: design`, `last_experiment_id: <id>`, `next_action: "Run /review-script src/experiments/<id>/run.py before /run-experiment"`.
9. **Report** to the user (Japanese) a summary of the new (or modified) entry and the scaffolded files.

## Idempotence rules

- Re-running with the same `experiment_id` updates the registry entry and the methodology section, but never overwrites existing source files under `src/experiments/<id>/`.
- The methodology section is updated by replacing the content of the `## <experiment_id>` heading down to the next `## ` heading. Other experiments' sections are untouched.

## Hard rules

- Refuse to register a device/HIL experiment when `ethics.hil_safety_owner` is null in Zone B. Surface this in Japanese and point the user to `/init-experiment` to set it.
- Refuse to register `safety_class: destructive` for `execution_target: sim`.
- Do not modify Zone A.
- Do not modify other experiments' registry entries or methodology sections.
