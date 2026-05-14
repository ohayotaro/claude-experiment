# Language policy

There is exactly one Japanese-language surface in this repository: **the chat between the user and the orchestrator**. Everything else is English.

## Japanese (Japanese-speaking user only)

- Orchestrator's chat replies to the user.
- `AskUserQuestion` question text and option labels.
- `/init-experiment` interactive Q&A.
- Hook user-facing warning / status / block strings (e.g. safety-check's "校正情報が古い" message).
- Skill execution status output shown to the user.
- `session-start.py` / `session-end.py` screen output.

## English (everything else)

- All code: Python in `src/`, `tests/`, `scripts/`, hooks under `.claude/hooks/`. Including comments and variable names.
- All native source in `src/` (C++, Rust). Comments and identifiers stay English.
- All agent definitions under `.claude/agents/*.md` (frontmatter, body, handoff contracts).
- All skill definitions under `.claude/skills/**/SKILL.md`.
- All rules under `.claude/rules/*.md` including this file.
- `CLAUDE.md` (Zones A, B, C).
- `README.md` is bilingual by exception: the primary user audience is Japanese-speaking, so onboarding sections (Quick start, update flow explanations, troubleshooting) may be primarily Japanese. Authoritative reference content (skill / agent tables, layout, Credits) stays in English so it matches the source-of-truth files those tables describe.
- All `docs/research/*.md` (design, methodology, analysis, discussion).
- All run metadata (`data/results/<run_id>/metadata.json`), build manifests (`data/builds/<build_id>/manifest.json`), config snapshots, and lock files.
- All experiment config files (`config.yaml`, JSON schemas).
- All agent → agent / agent → Codex / agent → Gemini delegation prompts and responses.
- All logs under `.claude/logs/` and run logs (`data/results/<run_id>/log.txt`).
- `.codex/AGENTS.md`, `.gemini/GEMINI.md`.
- Keyword lists in `routing-keywords.json` (datasheets and toolchain docs are largely English).
- Commit messages and PR descriptions.
- Agent scratch / chain-of-thought notes.

## Boundary cases

- **Hook code with user-facing strings.** Python source is English; only the literal user-facing string is Japanese. Example: `print("[safety-check] 校正情報が古い: " + calibration_ref)` — variable names and surrounding code stay English. Avoid emojis in user-facing strings; prefix with a bracketed tag like `[hook-name]` or `[hint]` instead.
- **User free-text input.** When the user types an objective or experiment description in Japanese, store it verbatim in `CLAUDE.md` Zone B. Agents translate to English when they materialize content under `docs/research/`.
- **Operator instructions for device runs.** If a device run requires a human operator to physically interact with hardware, the on-screen instructions emitted by `device-operator` agent and `/run-experiment` MAY be in Japanese (this is operator-facing chat, not stored artifact). The recorded log under `data/results/<run_id>/log.txt` stays English.
- **When unsure, choose English.** Keep the rule simple.

## Why this split

- Specialist agents are addressed by Codex / Gemini, which prefer English.
- Logs are searched by other agents and replayed across runs; consistency matters.
- Run metadata is consumed by analysis scripts and external tools; it must be machine-parseable English.
- The user reads chat replies in their native language for speed.
