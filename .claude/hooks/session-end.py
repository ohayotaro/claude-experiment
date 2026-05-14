#!/usr/bin/env python3
"""SessionEnd hook. Append a one-line session summary to .claude/logs/sessions.log
and warn about any device/HIL lock files that look like they are still held by
this session.

Does NOT modify Zone C — that is /checkpoint's job, run intentionally by the
orchestrator. We only persist a lightweight breadcrumb here so a human can
audit when each session ended. The lock warning is best-effort: we check
data/locks/*.lock files whose recorded pid is alive and is in this session's
process chain.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _project_root() -> Path:
    root = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(root).resolve() if root else Path.cwd().resolve()


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True


def _pid_in_self_chain(target_pid: int) -> bool:
    cur = os.getpid()
    seen: set[int] = set()
    for _ in range(64):
        if cur == target_pid:
            return True
        if cur in seen or cur <= 1:
            return False
        seen.add(cur)
        try:
            out = os.popen(f"ps -o ppid= -p {cur} 2>/dev/null").read().strip()
            cur = int(out) if out else 0
        except (OSError, ValueError):
            return False
    return False


def _scan_held_locks(root: Path) -> list[Path]:
    """Return lock files whose recorded pid is alive AND in our chain."""
    held: list[Path] = []
    lock_dir = root / "data" / "locks"
    if not lock_dir.is_dir():
        return held
    for lp in lock_dir.glob("*.lock"):
        try:
            data = json.loads(lp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        pid = data.get("pid")
        if not isinstance(pid, int):
            continue
        if not _pid_alive(pid):
            continue
        if _pid_in_self_chain(pid):
            held.append(lp)
    return held


def main() -> int:
    raw = sys.stdin.read() or "{}"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = {}
    reason = payload.get("reason", "unknown")
    ts = datetime.now(timezone.utc).isoformat()
    root = _project_root()
    log = root / ".claude" / "logs" / "sessions.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as f:
        f.write(f"{ts} session_end reason={reason}\n")

    held = _scan_held_locks(root)
    if held:
        lines = ["[session-end] このセッションが保持中のロックがあります:"]
        for lp in held:
            lines.append(f"  - {lp}")
        lines.append(
            "  実機を離れる前に `/lock-device --release <id>` を実行してください。"
        )
        print("\n".join(lines))

    if reason == "logout":
        print(
            "[session-end] セッションを終了します。"
            "進捗の永続化が必要な場合は、次回開始前に `/checkpoint` を実行してください。"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
