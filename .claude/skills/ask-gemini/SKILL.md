---
name: ask-gemini
description: Ad-hoc one-shot Gemini call for quick web / multimodal lookups (vendor docs, datasheets, oscilloscope captures, prior numerical methods). Does NOT persist any artifact under docs/.
when_to_use: "Quick: find vendor docs for X" / "describe this oscilloscope capture" / "summarize this datasheet" — anything multimodal that does not warrant a deeper retrieval pass.
inputs:
  - User prompt (free-text)
  - Optional: file path (PDF / image / audio / video)
outputs:
  - Gemini response shown inline to the user (Japanese-translated summary by orchestrator)
  - .claude/logs/cli/<ISO>-gemini-*.md (full I/O captured by log-cli-tools hook)
delegated_agent: gemini-explore (or direct gemini CLI call from orchestrator)
next_skill: any
---

# /ask-gemini

A lightweight escape hatch to Gemini for quick lookups. **Does not modify any `docs/` file** — pure read-only retrieval.

## Steps for the orchestrator

1. **Check Gemini availability.** Read `.claude/logs/setup-status.json` (`gemini_available`). If Gemini is unavailable, return `status: blocked` with the missing dependency named. **Do not silently substitute Claude `WebFetch` or any other in-process retrieval** — `agent-routing.md` §"Fallback policy" forbids skill-level degradation. The orchestrator (not this skill) decides whether to ask the user to install Gemini CLI, accept a degraded substitute with a recorded quality warning, or skip the lookup.
2. **Translate the user's intent into a structured Gemini prompt.** Always specify output format. Defaults:
   - "find vendor docs for X" → request a JSON list of N hits with `title, source_url, vendor, document_kind, one_paragraph_summary`. Mark unofficial mirrors.
   - "describe this figure / image / capture" → markdown with axis labels, units, key trends, numerical values where extractable.
   - "summarize this PDF / datasheet / manual" → markdown with sections: identification (part number / standard), operating conditions, key specs, anything that affects measurement procedure.
3. **Invoke Gemini.**
   ```bash
   gemini -p "<structured prompt>" [--file <path>]
   ```
   The `log-cli-tools.py` hook captures both prompt and response to `.claude/logs/cli/`.
4. **Translate the result for the user** (Japanese summary), and **show the cli log path** so they can read the full English response if needed.
5. **Do not write to `docs/`.** If the user wants the result captured, suggest copying the relevant snippet into `docs/research/hardware/<device_id>.md` (for vendor specs) or `docs/research/methodology.md` (for measurement procedure references) manually.

## Hard rules

- One-shot only. Do not chain multiple Gemini calls within one `/ask-gemini` invocation.
- If Gemini returns no source URL/DOI/part-number for a factual claim, surface that clearly to the user — do not silently treat it as fact.
- Never modify any file under `docs/` or `data/` from this skill.

## Examples

| User says (Japanese) | Orchestrator dispatches |
|---|---|
| "AD7124 のデータシートで input range をまとめて" | summarize-PDF prompt scoped to input range / common-mode, with `--file` |
| "この波形（path）の周波数と振幅は？" | image-description prompt, focused question |
| "MPI 5.x の collective の最新仕様を3つだけ" | structured JSON request, 3 entries, official sources preferred |
