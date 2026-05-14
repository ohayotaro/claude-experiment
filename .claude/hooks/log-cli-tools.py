#!/usr/bin/env python3
"""PreToolUse + PostToolUse + PostToolUseFailure hook on Bash that captures
every `codex` and `gemini` invocation into .claude/logs/cli/.

Pre and post are paired by `tool_use_id` from the payload (not by command
hash) so concurrent or repeated identical commands never collide. Failure
events are written too so the pre-log's `_pending_` placeholders never
remain stale.

Stdout / stderr go through a redaction pass for known secret patterns
(API keys, bearer tokens, password=...) and are truncated to a hard cap.
"""

from __future__ import annotations

import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

CLI_RE = re.compile(r"(?:^|\s)(codex|gemini)(?:\s|$)")
MAX_BLOCK_BYTES = 200_000  # per stdout/stderr field

# Patterns that almost certainly should not land in committed-or-shared logs.
_REDACT_PATTERNS = [
    (re.compile(r"\b(sk-[A-Za-z0-9]{20,})", re.IGNORECASE), "[REDACTED-OPENAI-KEY]"),
    (re.compile(r"\b(AKIA[0-9A-Z]{16})\b"), "[REDACTED-AWS-KEY]"),
    (re.compile(r"\b(ghp_[A-Za-z0-9]{30,})\b"), "[REDACTED-GH-PAT]"),
    (re.compile(r"\b(xox[abprs]-[A-Za-z0-9-]{10,})\b"), "[REDACTED-SLACK]"),
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-]{16,}"), r"\1 [REDACTED]"),
    (re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key)\s*[=:]\s*\S+"),
     r"\1=[REDACTED]"),
]


def _project_root() -> Path:
    root = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(root).resolve() if root else Path.cwd().resolve()


def _log_dir() -> Path:
    return _project_root() / ".claude" / "logs" / "cli"


def slug(s: str, n: int = 24) -> str:
    s = re.sub(r"\s+", "-", s.strip())
    s = re.sub(r"[^A-Za-z0-9._-]", "", s)
    return s[:n] or "x"


def redact(text: str) -> str:
    if not text:
        return text
    for pat, repl in _REDACT_PATTERNS:
        text = pat.sub(repl, text)
    if len(text.encode("utf-8", errors="ignore")) > MAX_BLOCK_BYTES:
        text = text[: MAX_BLOCK_BYTES // 2] + "\n...[TRUNCATED]...\n"
    return text


def log_path_for(tool: str, cmd: str, key: str) -> Path:
    """Filename uses microsecond timestamp + sanitized tool_use_id (or uuid).

    The key is used both for filename uniqueness and as the pairing token
    between pre and post records.
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%f")
    short = slug(cmd[:60])
    safe_key = re.sub(r"[^A-Za-z0-9_-]", "_", key)[:24]
    return _log_dir() / f"{ts}-{tool}-{short}-{safe_key}.md"


def find_existing_log(tool: str, key: str) -> Path | None:
    safe_key = re.sub(r"[^A-Za-z0-9_-]", "_", key)[:24]
    candidates = sorted(_log_dir().glob(f"*-{tool}-*-{safe_key}.md"))
    return candidates[-1] if candidates else None


def main() -> int:
    raw = sys.stdin.read() or "{}"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return 0

    phase = payload.get("hook_event_name", "")
    inp = payload.get("tool_input", {}) or {}
    cmd = inp.get("command", "") or ""
    m = CLI_RE.search(cmd)
    if not m:
        return 0
    tool = m.group(1)

    # Pair pre and post by tool_use_id when available; fall back to a fresh
    # uuid (which means the pre/post will not pair, but we still get records).
    key = (
        payload.get("tool_use_id")
        or payload.get("toolUseId")
        or inp.get("tool_use_id")
        or uuid.uuid4().hex[:12]
    )

    _log_dir().mkdir(parents=True, exist_ok=True)

    if phase == "PreToolUse":
        ts = datetime.now(timezone.utc).isoformat()
        p = log_path_for(tool, cmd, key)
        p.write_text(
            f"# {tool} call\n"
            f"_started: {ts}_\n"
            f"_tool_use_id: {key}_\n\n"
            f"## Command\n```\n{cmd}\n```\n\n"
            f"## Stdout\n_pending_\n\n"
            f"## Stderr\n_pending_\n",
            encoding="utf-8",
        )
        return 0

    if phase in ("PostToolUse", "PostToolUseFailure"):
        existing_path = find_existing_log(tool, key)
        target = existing_path or log_path_for(tool, cmd, key)
        response = payload.get("tool_response", {}) or {}
        stdout = redact(response.get("stdout", "") or "")
        stderr = redact(response.get("stderr", "") or "")
        ec = response.get("exit_code")
        err_field = response.get("error", "")
        ts = datetime.now(timezone.utc).isoformat()
        is_failure = phase == "PostToolUseFailure" or (
            isinstance(ec, int) and ec != 0
        )

        finished_block = (
            f"\n_finished: {ts} (exit={ec}{', FAILURE' if is_failure else ''})_\n\n"
            f"## Stdout\n```\n{stdout}\n```\n\n"
            f"## Stderr\n```\n{stderr}\n```\n"
        )
        if err_field:
            finished_block += f"\n## Error field\n```\n{redact(str(err_field))}\n```\n"

        try:
            existing = target.read_text(encoding="utf-8")
        except FileNotFoundError:
            existing = (
                f"# {tool} call (no pre-log captured)\n"
                f"_tool_use_id: {key}_\n\n"
                f"## Command\n```\n{cmd}\n```\n"
            )
        if "_pending_" in existing:
            existing = existing.replace(
                "## Stdout\n_pending_\n\n## Stderr\n_pending_\n", ""
            )
        target.write_text(existing.rstrip() + finished_block, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
