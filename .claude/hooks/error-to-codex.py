#!/usr/bin/env python3
"""PostToolUse + PostToolUseFailure hook on Bash. When a `python` / `pytest`
/ `uv run` / `cmake --build` / `cargo build|run|test` / `make` / `mpirun`
command exits non-zero (or fails outright) with a recognizable traceback or
build-error signature, surface a structured payload for `codex-debugger`.

We do not auto-launch the agent — only nudge. Auto-launch would surprise
users during routine debugging.

The payload schema follows `.claude/rules/agent-routing.md` §"Hook → agent
payload schemas":

    {
      "run_id_or_build_id":   <id or null>,
      "script_or_target_path": <path or null>,
      "traceback_or_stderr":  <head + tail excerpt of stderr+stdout>,
      "env": {
        "cwd": ...,
        "platform": ...,
        "python_version": ...,
        "shell": ...
      },
      "last_commit": <git rev or null>
    }

We emit two things on stdout:

1. A Japanese one-line nudge for the user.
2. A fenced ```json ... ``` block holding the payload. The orchestrator
   extracts the JSON block and passes it to `codex-debugger` when the user
   accepts the suggestion. The fenced form is robust against the chat
   harness re-wrapping or truncating non-JSON content.
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

# Failure signatures we recognize and surface.
PY_TB = re.compile(r"Traceback \(most recent call last\):", re.MULTILINE)
RUST_PANIC = re.compile(r"\bthread '.*' panicked at\b|\bcargo:warning=error\b|\berror\[E\d+\]:")
CMAKE_ERR = re.compile(r"\bCMake Error\b|\bninja: build stopped:|error: linker command failed")
MAKE_ERR = re.compile(r"^make(\[\d+\])?: \*\*\* ", re.MULTILINE)
MPI_ERR = re.compile(r"mpirun\b.*\bexited on signal\b|\bMPI_ABORT\b")
CXX_ERR = re.compile(r"^.+: error: ", re.MULTILINE)

FAILURE_SIGNATURES = [PY_TB, RUST_PANIC, CMAKE_ERR, MAKE_ERR, MPI_ERR, CXX_ERR]

# Commands we look at. Token-boundary matching so "echo python" or
# "/usr/bin/uv-not-uv" don't trigger; we anchor on whitespace boundaries plus
# the actual program name as the FIRST token of a pipeline segment.
# We also accept `uv run <script.py>` without an explicit `python` token
# (uv resolves the shebang).
RUNNER_PATTERNS = [
    re.compile(r"(^|\s|[;&|]\s*)uv\s+run\s+(python\s|[^\s-][^\s]*\.py\b)"),
    re.compile(r"(^|\s|[;&|]\s*)python3?\s"),
    re.compile(r"(^|\s|[;&|]\s*)pytest\b"),
    re.compile(r"(^|\s|[;&|]\s*)cmake\s+(--build|-S|--install)\b"),
    re.compile(r"(^|\s|[;&|]\s*)cargo\s+(build|run|test|check|bench)\b"),
    re.compile(r"(^|\s|[;&|]\s*)make\b"),
    re.compile(r"(^|\s|[;&|]\s*)ninja\b"),
    re.compile(r"(^|\s|[;&|]\s*)mpirun\b"),
    re.compile(r"(^|\s|[;&|]\s*)srun\b"),
]

# Path extraction for run_id / build_id and script/target.
_RUN_ID_PATH = re.compile(r"data/results/([A-Za-z0-9_.\-:T]+)/?")
_BUILD_ID_PATH = re.compile(r"data/builds/([A-Za-z0-9]+)/?")
_PY_SCRIPT = re.compile(r"(?:python3?|uv\s+run(?:\s+python)?)\s+(\S+\.py)\b")
_CMAKE_TARGET = re.compile(r"cmake\s+--build\s+(\S+)\b")
_CARGO_MANIFEST = re.compile(r"cargo\s+(?:build|run|test|check|bench)\b.*?--manifest-path[= ](\S+)")
_MAKE_TARGET = re.compile(r"\bmake\s+([A-Za-z][\w./-]*)\b")

# Excerpt sizing — keep head + tail because stack traces and "error:" lines
# typically appear at the tail, but the build context (target, file) appears
# at the head. A pure-head truncation drops the actual failure.
_EXCERPT_HEAD_LINES = 20
_EXCERPT_TAIL_LINES = 40
_EXCERPT_MAX_BYTES = 8000


def _project_root() -> Path:
    root = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(root).resolve() if root else Path.cwd().resolve()


def _extract_run_or_build_id(text: str) -> str | None:
    m = _RUN_ID_PATH.search(text)
    if m:
        return m.group(1)
    m = _BUILD_ID_PATH.search(text)
    if m:
        return m.group(1)
    return None


def _extract_script_or_target(cmd: str) -> str | None:
    for pat in (_PY_SCRIPT, _CMAKE_TARGET, _CARGO_MANIFEST, _MAKE_TARGET):
        m = pat.search(cmd)
        if m:
            return m.group(1)
    return None


def _head_tail_excerpt(text: str) -> str:
    """Return a head + tail excerpt of `text` capped at _EXCERPT_MAX_BYTES.

    Build / runtime errors usually have key context at the head (target /
    file being built, command line printed by the build system) and at the
    tail (actual error message, traceback frames). A pure-head truncation —
    which is the easy default — silently drops the tail where the real
    failure lives. We keep both.
    """
    text = text.strip()
    if not text:
        return ""
    lines = text.splitlines()
    if len(lines) <= _EXCERPT_HEAD_LINES + _EXCERPT_TAIL_LINES:
        excerpt = "\n".join(lines)
    else:
        head = lines[:_EXCERPT_HEAD_LINES]
        tail = lines[-_EXCERPT_TAIL_LINES:]
        excerpt = "\n".join(head) + "\n...[TRUNCATED " + str(len(lines) - _EXCERPT_HEAD_LINES - _EXCERPT_TAIL_LINES) + " LINES]...\n" + "\n".join(tail)
    data = excerpt.encode("utf-8", errors="replace")
    if len(data) > _EXCERPT_MAX_BYTES:
        # Tail-favor on byte budget too: keep the last 2/3 of the budget.
        keep_head = _EXCERPT_MAX_BYTES // 3
        keep_tail = _EXCERPT_MAX_BYTES - keep_head
        excerpt = (
            data[:keep_head].decode("utf-8", errors="replace")
            + "\n...[TRUNCATED]...\n"
            + data[-keep_tail:].decode("utf-8", errors="replace")
        )
    return excerpt


def _last_commit() -> str | None:
    root = _project_root()
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    rev = proc.stdout.strip()
    return rev or None


def _env_block() -> dict[str, object]:
    return {
        "cwd": str(_project_root()),
        "platform": f"{platform.system().lower()}-{platform.machine().lower()}",
        "python_version": ".".join(map(str, sys.version_info[:3])),
        "shell": os.environ.get("SHELL", ""),
    }


def main() -> int:
    raw = sys.stdin.read() or "{}"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return 0
    inp = payload.get("tool_input", {}) or {}
    cmd = inp.get("command", "")
    response = payload.get("tool_response", {}) or {}
    stderr = response.get("stderr", "") or ""
    stdout = response.get("stdout", "") or ""
    exit_code = response.get("exit_code")
    phase = payload.get("hook_event_name", "")

    is_failure = phase == "PostToolUseFailure" or (exit_code not in (0, None))
    if not is_failure:
        return 0
    if not any(p.search(cmd) for p in RUNNER_PATTERNS):
        return 0

    combined = stderr + "\n" + stdout
    if not any(sig.search(combined) for sig in FAILURE_SIGNATURES):
        return 0

    structured = {
        "run_id_or_build_id": _extract_run_or_build_id(combined) or _extract_run_or_build_id(cmd),
        "script_or_target_path": _extract_script_or_target(cmd),
        "traceback_or_stderr": _head_tail_excerpt(combined),
        "env": _env_block(),
        "last_commit": _last_commit(),
        "exit_code": exit_code,
        "command": cmd,
    }

    print(
        "[error-to-codex] 実行が失敗しました。"
        "`codex-debugger` に root-cause 解析を依頼することを推奨します。"
        " 下記の JSON payload を渡してください:"
    )
    print("```json")
    print(json.dumps(structured, indent=2, ensure_ascii=False))
    print("```")
    return 0


if __name__ == "__main__":
    sys.exit(main())
