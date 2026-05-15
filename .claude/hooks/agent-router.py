#!/usr/bin/env python3
"""UserPromptSubmit hook: suggest a specialized agent based on prompt keywords.

Reads .claude/routing-keywords.json and prints a short user-facing hint when
the user's prompt looks like it should be delegated.

Strict on language: comments and code are English; the user-facing string is
Japanese (project policy in .claude/rules/language.md).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Single-ASCII-word keywords like "run" / "script" / "figure" / "image" /
# "chart" / "python" / "plot" appear inside unrelated prompts very often and
# over-trigger naive substring matching. For these, require word-boundary
# matches. Multi-word phrases ("review my script", "/run-experiment", etc.)
# already have natural boundaries and Japanese keywords don't carve into
# Latin word-boundary regex, so we keep substring matching for those.
_SINGLE_WORD_ASCII = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


def _project_root() -> Path:
    import os
    root = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(root).resolve() if root else Path.cwd().resolve()


def load_routing_table() -> dict[str, list[str]]:
    p = _project_root() / ".claude" / "routing-keywords.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _keyword_matches(prompt_lower: str, keyword: str) -> bool:
    """Match `keyword` against `prompt_lower`. Single-word ASCII keywords use
    word-boundary regex to avoid over-triggering on substrings (e.g. "run"
    inside "running" or "Trunk"). Multi-word phrases and non-ASCII (Japanese,
    Chinese, etc.) keywords use plain substring matching — word boundaries
    don't behave the way we want for those.
    """
    kw = keyword.lower()
    if _SINGLE_WORD_ASCII.match(kw):
        return re.search(r"\b" + re.escape(kw) + r"\b", prompt_lower) is not None
    return kw in prompt_lower


def _scan(prompt_lower: str, mapping: dict[str, list[str]]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for name, keywords in mapping.items():
        if name.startswith("_") or not isinstance(keywords, list):
            continue
        for kw in keywords:
            if isinstance(kw, str) and _keyword_matches(prompt_lower, kw):
                out.append((name, kw))
                break
    return out


def find_agent_matches(prompt: str, table: dict) -> list[tuple[str, str]]:
    return _scan(prompt.lower(), table)


def find_skill_matches(prompt: str, table: dict) -> list[tuple[str, str]]:
    skill_hints = table.get("_skill_hints", {})
    if not isinstance(skill_hints, dict):
        return []
    return _scan(prompt.lower(), skill_hints)


def main() -> int:
    raw = sys.stdin.read() or "{}"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return 0
    prompt = payload.get("prompt", "")
    if not prompt.strip():
        return 0

    table = load_routing_table()
    if not table:
        return 0

    agent_hits = find_agent_matches(prompt, table)
    skill_hits = find_skill_matches(prompt, table)
    if not agent_hits and not skill_hits:
        return 0

    lines: list[str] = []
    if agent_hits:
        lines.append("[agent-router] 推奨エージェント:")
        for agent, kw in agent_hits[:3]:
            lines.append(f"  - {agent}（キーワード: {kw}）")
    if skill_hits:
        lines.append("[agent-router] ショートカット skill:")
        for skill, kw in skill_hits[:3]:
            lines.append(f"  - {skill}（キーワード: {kw}）")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
