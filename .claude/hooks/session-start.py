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
import shutil
import subprocess
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

# External CLI partners probed once per session and recorded into
# .claude/logs/setup-status.json so skills/agents can read a single source
# of truth instead of probing the PATH themselves.
_PROBED_CLIS = ("codex", "gemini")


def _probe_cli(name: str) -> dict[str, object]:
    """Best-effort check for one external CLI. Returns a small dict suitable
    for inclusion in setup-status.json.

    Never raises: the probe is advisory. A timeout or non-zero exit yields
    `available: false` with the reason recorded.
    """
    path = shutil.which(name)
    if not path:
        return {"available": False, "path": None, "version": None, "reason": "not on PATH"}
    try:
        proc = subprocess.run(
            [name, "--version"],
            capture_output=True,
            text=True,
            timeout=5.0,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        return {
            "available": False,
            "path": path,
            "version": None,
            "reason": f"version probe failed: {e!r}",
        }
    version = (proc.stdout or proc.stderr or "").strip().splitlines()[0] if (proc.stdout or proc.stderr) else None
    return {
        "available": proc.returncode == 0,
        "path": path,
        "version": version,
        "reason": None if proc.returncode == 0 else f"exit={proc.returncode}",
    }


def _write_setup_status(root: Path) -> None:
    """Probe known external CLIs and write .claude/logs/setup-status.json.

    Skills MUST read this file (not the PATH directly) so the orchestrator
    can short-circuit decisions cleanly. See .claude/rules/agent-routing.md
    §"Fallback policy".
    """
    out: dict[str, object] = {
        "$schema_version": "1",
        "probed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    for name in _PROBED_CLIS:
        result = _probe_cli(name)
        out[f"{name}_available"] = bool(result["available"])
        out[f"{name}_path"] = result["path"]
        out[f"{name}_version"] = result["version"]
        if result.get("reason"):
            out[f"{name}_reason"] = result["reason"]
    target = root / ".claude" / "logs" / "setup-status.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, target)


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


def _scan_unacknowledged_unsafe_runs(root: Path) -> list[tuple[str, str, str]]:
    """Per safety-hil.md §3: any device/HIL run with exit_state in
    {crash, interrupted} indicates the cleanup handler MAY have been skipped.
    The next session-start MUST refuse new device runs on the same device
    until the user confirms the device is in a safe state.

    We do this by leaving a sentinel file at
        data/locks/<device_id>.unsafe-state-needs-ack
    whose body is JSON `{run_id, exit_state, device_id, written_at}`. The
    `safety-check` hook reads this and blocks any new device run on the same
    device_id. The user clears the sentinel via:
        rm data/locks/<device_id>.unsafe-state-needs-ack
    after physically verifying the device, OR a future
        /lock-device <device_id> --confirm-safe
    invocation (not yet implemented; the file delete is the manual path).

    Returns the list of (device_id, run_id, exit_state) tuples for which a
    new sentinel was created this scan.
    """
    results_dir = root / "data" / "results"
    locks_dir = root / "data" / "locks"
    if not results_dir.is_dir():
        return []
    locks_dir.mkdir(parents=True, exist_ok=True)
    created: list[tuple[str, str, str]] = []
    for meta_path in results_dir.glob("*/metadata.json"):
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("execution_target") not in ("device", "hil"):
            continue
        exit_state = data.get("exit_state")
        if exit_state not in ("crash", "interrupted"):
            continue
        device_id = (data.get("device") or {}).get("device_id") if isinstance(data.get("device"), dict) else None
        if not device_id:
            continue
        sentinel = locks_dir / f"{device_id}.unsafe-state-needs-ack"
        if sentinel.exists():
            continue  # already flagged; awaiting user ack
        # If the operator has previously confirmed via a `.safe-ack` cleared
        # path, skip. (We do not track that here — manual rm of the sentinel
        # is the ack signal.)
        body = {
            "run_id": data.get("run_id"),
            "exit_state": exit_state,
            "device_id": device_id,
            "written_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "_note": (
                "Created because the named run ended in 'crash' or 'interrupted', "
                "which means the cleanup handler may not have run. Verify the "
                "device is in a safe state, then `rm` this file to clear the "
                "block. See .claude/rules/safety-hil.md §3."
            ),
        }
        try:
            sentinel.write_text(json.dumps(body, indent=2), encoding="utf-8")
            created.append((device_id, str(data.get("run_id")), exit_state))
        except OSError:
            continue
    return created


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
    unsafe_flagged = _scan_unacknowledged_unsafe_runs(root)
    _write_setup_status(root)

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
    if unsafe_flagged:
        lines.append(
            f"[session-start] device/HIL の異常終了が {len(unsafe_flagged)} 件あります。"
            " 物理的に安全状態を確認した上で、対応する "
            "`data/locks/<device_id>.unsafe-state-needs-ack` を削除してください。"
            " 削除するまで該当 device での新規 run は `safety-check` フックでブロックされます。"
        )
        for device_id, run_id, exit_state in unsafe_flagged:
            lines.append(f"  - device_id={device_id} run_id={run_id} exit_state={exit_state}")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
