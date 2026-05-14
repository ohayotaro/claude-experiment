#!/usr/bin/env python3
"""SessionStart hook. Read CLAUDE.md Zone B and Zone C, print a concise status
to the user (Japanese), and run the orphan-run reaper.

Project policy: comments and code are English; the user-facing string is
Japanese (.claude/rules/language.md).
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def _project_root() -> Path:
    root = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(root).resolve() if root else Path.cwd().resolve()


ZONE_B = re.compile(r"<!-- ZONE_B_BEGIN -->(.*?)<!-- ZONE_B_END -->", re.DOTALL)
ZONE_C = re.compile(r"<!-- ZONE_C_BEGIN -->(.*?)<!-- ZONE_C_END -->", re.DOTALL)
KV_RE = re.compile(r"^\s*([a-zA-Z_][\w]*)\s*:\s*(.+?)\s*$", re.MULTILINE)

# Orphan-run reaper threshold (hours). A run whose metadata.json has
# finished_at == null AND mtime older than this AND whose recorded PID (if any)
# is no longer running is patched to exit_state=interrupted.
ORPHAN_GRACE_H = 1.0


def parse_kv(block: str) -> dict[str, str]:
    out: dict[str, str] = {}
    in_yaml = False
    for line in block.splitlines():
        if line.strip().startswith("```"):
            in_yaml = not in_yaml
            continue
        if not in_yaml:
            continue
        m = KV_RE.match(line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        # PermissionError means the PID exists but is owned by another user.
        # Treat as alive — we cannot reap it.
        return isinstance(sys.exc_info()[1], PermissionError)
    except OSError:
        return False


def _reap_orphan_runs(root: Path) -> int:
    """Patch metadata.json files for runs whose process died before writing
    finished_at. Returns the number of patched files. Never deletes data.
    """
    results_dir = root / "data" / "results"
    if not results_dir.is_dir():
        return 0
    cutoff = time.time() - ORPHAN_GRACE_H * 3600.0
    patched = 0
    for meta_path in results_dir.glob("*/metadata.json"):
        try:
            stat = meta_path.stat()
        except OSError:
            continue
        if stat.st_mtime > cutoff:
            continue
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("finished_at") is not None:
            continue
        recorded_pid = data.get("pid")
        if isinstance(recorded_pid, int) and _pid_alive(recorded_pid):
            continue
        data["exit_state"] = "interrupted"
        data["finished_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        data["reaper"] = True
        try:
            meta_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            patched += 1
        except OSError:
            continue
    return patched


def main() -> int:
    root = _project_root()
    p = root / "CLAUDE.md"
    if not p.exists():
        return 0
    text = p.read_text(encoding="utf-8")
    zb = ZONE_B.search(text)
    zc = ZONE_C.search(text)
    b = parse_kv(zb.group(1)) if zb else {}
    c = parse_kv(zc.group(1)) if zc else {}

    reaped = _reap_orphan_runs(root)

    status = b.get("status", "uninitialized")
    if status == "uninitialized":
        print(
            "[session-start] 実験プロジェクトは未初期化です。"
            "最初に `/init-experiment` を実行してください。"
        )
        return 0

    project_name = b.get("project_name", "(未設定)")
    objective = b.get("objective", "(未設定)")
    phase = c.get("current_phase", "not_started")
    next_action = c.get("next_action", "(未設定)")
    last_run = c.get("last_run_id", "null")
    last_build = c.get("last_build_id", "null")
    held = c.get("held_locks", "[]")

    lines = [
        "[session-start] 実験プロジェクトを読み込みました。",
        f"  プロジェクト: {project_name}",
        f"  目的: {objective}",
        f"  現在のフェーズ: {phase}（最終 run_id: {last_run} / build_id: {last_build}）",
        f"  保持中のロック: {held}",
        f"  次のアクション: {next_action}",
    ]
    if reaped:
        lines.append(f"[session-start] 中断された run を {reaped} 件、interrupted として記録しました。")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
