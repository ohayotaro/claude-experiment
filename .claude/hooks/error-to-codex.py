#!/usr/bin/env python3
"""PostToolUse + PostToolUseFailure hook on Bash. When a `python` / `pytest`
/ `uv run` / `cmake --build` / `cargo build|run|test` / `make` / `mpirun`
command exits non-zero (or fails outright) with a recognizable traceback or
build-error signature, suggest delegating to codex-debugger.

We do not auto-launch the agent — only nudge. Auto-launch would surprise
users during routine debugging.

The hook payload schema we expect downstream codex-debugger to receive
(via the orchestrator) is:
  {run_id_or_build_id?, script_or_target_path?, traceback_or_stderr, env, last_commit?}
matching .claude/rules/agent-routing.md §"Hook → agent payload schemas".
We surface a structured snippet here; the orchestrator builds the rest.
"""

from __future__ import annotations

import json
import re
import sys

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

    is_failure = phase == "PostToolUseFailure" or (
        exit_code not in (0, None)
    )
    if not is_failure:
        return 0
    if not any(p.search(cmd) for p in RUNNER_PATTERNS):
        return 0

    combined = stderr + "\n" + stdout
    if not any(sig.search(combined) for sig in FAILURE_SIGNATURES):
        return 0

    last_lines = "\n".join(combined.strip().splitlines()[-6:])
    print(
        "[error-to-codex] 実行が失敗しました。"
        "`codex-debugger` に root-cause 解析を依頼することを推奨します。\n"
        f"末尾抜粋:\n{last_lines}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
