---
name: ask-codex
description: Ad-hoc one-shot Codex call for quick logical / mathematical / statistical sanity checks. Does NOT update methodology.md, analysis.md, or any review file.
when_to_use: "Codex, is this proof correct?" / "check this stats reasoning" / "spot the logical hole in this argument" — anything that needs strict logical verification but does not warrant a full peer-review pass.
inputs:
  - User prompt (free-text), typically including a snippet of math, code, or argument
outputs:
  - Codex response shown inline (Japanese-translated summary)
  - .claude/logs/cli/<ISO>-codex-*.md (full I/O captured by log-cli-tools hook)
delegated_agent: orchestrator (direct codex CLI call)
next_skill: any
---

# /ask-codex

A lightweight escape hatch to Codex outside the formal `/review-script` and `/design-experiment` pipelines. **Does not modify any `docs/` or `src/` file**.

## Steps for the orchestrator

1. **Check Codex availability.** Read `.claude/logs/setup-status.json`. If `codex_available: false`, warn the user and offer to fall back to a Claude subagent acting as a strict critic (weaker).
2. **Frame the question for Codex.** Codex performs better with explicit role + format. Default prompt scaffold:
   ```
   You are a strict logical / statistical / mathematical reviewer. Given the
   following <argument | proof | code | claim>, do exactly:
   1. State whether it is correct (yes / no / partially / unverifiable).
   2. If wrong, identify the specific step that fails.
   3. If correct, identify any unstated assumption.
   4. If statistical, check assumptions of the chosen test.
   Be terse. No flattery.

   <CONTENT>
   ```
3. **Invoke Codex.**
   ```bash
   codex exec - <<'EOF'
   <prompt>
   EOF
   ```
   The `log-cli-tools.py` hook captures the I/O.
4. **Translate the verdict for the user** (Japanese), and show the cli log path for the full English response.
5. **Do not auto-apply fixes.** If Codex proposes a code/proof correction, surface it to the user and let them decide whether to invoke `experiment-runner` or `build-engineer` to apply.

## Hard rules

- One-shot. For multi-issue strict review of a script before execution, use `/review-script`.
- For methodology design (test choice, sample size, success criteria), use `/design-experiment` — it has the right context and pre-registration semantics.
- Never write to `docs/` or `src/` from this skill.
- If the user pastes an entire experiment driver, suggest `/review-script` instead.

## Examples

| User says (Japanese) | Orchestrator dispatches |
|---|---|
| "この t-test の自由度の使い方合ってる？" | role=statistical reviewer, focused on df / variance assumption |
| "この lemma の証明、step 3 が怪しい気がする" | role=mathematical reviewer, asked to verify step 3 specifically |
| "この関数のロジック、エッジケース漏れてる？" | role=code reviewer, asked to enumerate edge cases |
