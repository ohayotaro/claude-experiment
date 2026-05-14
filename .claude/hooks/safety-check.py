#!/usr/bin/env python3
"""PreToolUse hook on Bash. Coarse safety gate for device/HIL runs.

Per .claude/rules/safety-hil.md, this hook is the COARSE LAYER. It catches
obvious ad-hoc Bash launches of device/HIL entrypoints that bypass
/run-experiment. The authoritative preflight lives in /run-experiment; this
hook cannot resolve experiment configs, compute SHA-256 hashes, or gather
operator confirmation.

Behavior: when the Bash command looks like a direct invocation of an
entrypoint listed in Zone B as having `execution_target ∈ {device, hil}`,
verify that:

1. The device lock file is held by the current PID (or its parent chain).
2. (HIL only) The bench lock is also held.
3. A calibration file referenced in the experiment's last metadata exists
   and is fresh (calibration_age_h <= 24).
4. (HIL only) A bench self-check file exists from within the last hour.

On failure, EXIT 2 with a Japanese explanation that points the user to
/run-experiment.

Limitations (documented in safety-hil.md):
- Cannot detect launches that don't match the registered entrypoint string
  (e.g. user wraps it in a custom shell function).
- Cannot validate dry-run rehearsal equivalence, operator confirmation, or
  cleanup-handler presence. Those are the skill's job.

If anything in this hook's own parsing fails, it MUST NOT block. A spurious
block is worse than a missed coarse gate (the skill still catches it). On any
unexpected error, fall through with exit 0.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

CALIBRATION_FRESHNESS_DEFAULT_H = 24.0
BENCH_SELFCHECK_FRESHNESS_H = 1.0


def _project_root() -> Path:
    root = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(root).resolve() if root else Path.cwd().resolve()


def _block(message: str) -> int:
    """Emit a block message and exit 2 (PreToolUse hook blocking convention)."""
    sys.stderr.write(f"[safety-check] {message}\n")
    return 2


def _read_zone_b_experiments() -> list[dict[str, Any]]:
    """Read CLAUDE.md Zone B, return the parsed experiments: list as a list of
    dicts. Returns empty list on any failure. Does not import PyYAML — uses a
    minimal line-by-line YAML reader sufficient for the registry's documented
    shape.
    """
    claude_md = _project_root() / "CLAUDE.md"
    if not claude_md.exists():
        return []
    try:
        text = claude_md.read_text(encoding="utf-8")
    except OSError:
        return []
    m = re.search(r"<!-- ZONE_B_BEGIN -->(.*?)<!-- ZONE_B_END -->", text, re.DOTALL)
    if not m:
        return []
    zone_b = m.group(1)

    # Find the experiments: block. Stop at next top-level YAML key (ethics:,
    # reports:, viz_preferences:, or the closing ``` fence).
    lines = zone_b.splitlines()
    in_yaml = False
    in_experiments = False
    body: list[str] = []
    for line in lines:
        s = line.strip()
        if s.startswith("```"):
            in_yaml = not in_yaml
            continue
        if not in_yaml:
            continue
        if not in_experiments:
            if s.startswith("experiments:"):
                in_experiments = True
                # Skip "experiments: []" inline-empty.
                if s.rstrip() == "experiments: []":
                    return []
            continue
        # End of experiments: when we hit another top-level key (zero-indent
        # `^[a-z][a-z_]*:` line).
        if re.match(r"^[a-z][\w]*\s*:", line):
            break
        body.append(line)

    return _parse_experiments_list(body)


def _parse_experiments_list(lines: list[str]) -> list[dict[str, Any]]:
    """Parse a YAML-style list of dict entries indented two spaces under
    'experiments:'. Returns list of dict. Skips comment-only entries.
    """
    entries: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        # New entry: "  - id: ..." or just "  -"
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)
        if stripped.startswith("- "):
            # Push prior entry.
            if cur is not None:
                entries.append(cur)
            cur = {}
            # Parse the first key on the same line as the dash.
            kv_part = stripped[2:]
            _maybe_set_kv(cur, kv_part)
        else:
            if cur is None:
                continue
            _maybe_set_kv(cur, stripped)
    if cur is not None:
        entries.append(cur)
    return entries


_KV = re.compile(r"^([a-zA-Z_][\w]*)\s*:\s*(.*)$")


def _maybe_set_kv(target: dict[str, Any], text: str) -> None:
    m = _KV.match(text)
    if not m:
        return
    key, val = m.group(1), m.group(2).strip()
    if val.startswith("#") or val == "":
        # Either a comment-only value or a nested-object indicator we ignore.
        return
    # Strip inline comment.
    val = re.split(r"\s+#", val, maxsplit=1)[0].strip()
    if val.lower() == "null":
        target[key] = None
    elif val.lower() == "true":
        target[key] = True
    elif val.lower() == "false":
        target[key] = False
    else:
        target[key] = val.strip('"').strip("'")


def _matched_experiment(command: str, experiments: list[dict[str, Any]]) -> dict[str, Any] | None:
    """If the Bash `command` looks like a direct launch of one of the listed
    entrypoints (and that experiment has device/hil target), return the entry.
    Otherwise return None.
    """
    for entry in experiments:
        target = entry.get("execution_target")
        if target not in ("device", "hil"):
            continue
        entry_path = entry.get("entrypoint")
        if not entry_path:
            continue
        # Match if the command mentions the entrypoint path (basename or full
        # path). This is intentionally loose — we want false positives over
        # false negatives, and the skill is the authoritative layer.
        basename = Path(entry_path).name
        if entry_path in command or basename in command:
            return entry
    return None


def _pid_in_self_chain(target_pid: int) -> bool:
    """Walk our own parent-process chain. Return True if target_pid appears.

    This is a best-effort check: on Linux/macOS we read /proc on Linux or
    use psutil-equivalent ppid lookup via `ps`. To avoid an extra dependency,
    we walk via `os.popen('ps -o ppid= -p <pid>')`. The hook MUST not block
    on parse failures — return True conservatively (the skill is the
    authoritative layer that re-checks).
    """
    cur = os.getpid()
    seen: set[int] = set()
    for _ in range(64):  # safety cap; no real process chain is this deep
        if cur == target_pid:
            return True
        if cur in seen or cur <= 1:
            return False
        seen.add(cur)
        try:
            out = os.popen(f"ps -o ppid= -p {cur} 2>/dev/null").read().strip()
            cur = int(out) if out else 0
        except (OSError, ValueError):
            return True  # fail-open
    return False


def _check_lock(lock_path: Path) -> tuple[bool, str | None]:
    """Return (held, reason_if_not_held). Verifies (a) the lock file exists,
    (b) the recorded pid is alive, AND (c) the recorded pid is in this
    process's parent chain (i.e. this session owns it).
    """
    if not lock_path.exists():
        return False, f"ロックファイル {lock_path} が存在しません。`/lock-device` で取得してください。"
    try:
        data = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, f"ロックファイル {lock_path} の JSON parse に失敗しました。"
    pid = data.get("pid")
    if not isinstance(pid, int):
        return False, f"ロックファイル {lock_path} に有効な pid がありません。"
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, OSError):
        return False, f"ロック保持者 pid={pid} は既に終了しています。`/lock-device` で取り直してください。"
    if not _pid_in_self_chain(pid):
        return False, (
            f"ロック {lock_path} は別セッション (pid={pid}) が保持しています。"
            "このセッションでは動作できません。"
        )
    return True, None


def _check_calibration(entry: dict[str, Any]) -> str | None:
    """Return a reason string if calibration is missing/stale; else None.

    The hook reads the most recent run's metadata for this experiment to get
    the last-used calibration_ref. If no prior run exists, the hook skips this
    check (the skill will enforce it).
    """
    exp_id = entry.get("id")
    if not exp_id:
        return None
    results_dir = _project_root() / "data" / "results"
    if not results_dir.is_dir():
        return None
    last_meta: dict[str, Any] | None = None
    last_mtime = 0.0
    for p in results_dir.glob("*/metadata.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("experiment_id") != exp_id:
            continue
        try:
            mt = p.stat().st_mtime
        except OSError:
            continue
        if mt > last_mtime:
            last_mtime = mt
            last_meta = data
    if last_meta is None:
        return None
    device_blk = last_meta.get("device", {})
    cal_ref = device_blk.get("calibration_ref")
    cal_age = device_blk.get("calibration_age_h")
    if not cal_ref:
        return "前回 run の calibration_ref が記録されていません。"
    cal_path = _project_root() / "data" / "calibrations" / cal_ref
    if not cal_path.exists():
        # cal_ref may be a hash; we only check if it looks like a filename.
        if "/" in cal_ref or cal_ref.endswith((".json", ".yaml", ".yml", ".csv", ".npz")):
            return f"参照されている calibration ファイル {cal_path} がありません。"
    if isinstance(cal_age, (int, float)) and cal_age > CALIBRATION_FRESHNESS_DEFAULT_H:
        return f"校正情報が古い: 前回 run 時点で calibration_age_h={cal_age:.1f}h"
    return None


def _check_bench_selfcheck(entry: dict[str, Any]) -> str | None:
    """For HIL: check that a recent bench selfcheck file exists."""
    bench_id = entry.get("bench_id")
    if not bench_id:
        return "HIL 実験ですが bench_id が登録されていません。"
    selfcheck = _project_root() / "data" / "locks" / f"{bench_id}.selfcheck.json"
    if not selfcheck.exists():
        return f"HIL bench selfcheck ({selfcheck}) がありません。`device-operator` の self-check を先に実行してください。"
    try:
        mtime = selfcheck.stat().st_mtime
    except OSError:
        return f"{selfcheck} の stat に失敗しました。"
    age_h = (time.time() - mtime) / 3600.0
    if age_h > BENCH_SELFCHECK_FRESHNESS_H:
        return f"HIL bench selfcheck が古い ({age_h:.1f}h 経過)。直前に再実行してください。"
    return None


def _is_run_experiment_invocation(command: str) -> bool:
    """The skill is allowed through. Direct entrypoint launches with dry-run
    or override flags are NOT — those flags are skill-only per safety-hil.md §2.
    """
    return "/run-experiment" in command or "claude-skill" in command


def main() -> int:
    raw = sys.stdin.read() or "{}"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return 0
    tool = payload.get("tool_name", "")
    if tool != "Bash":
        return 0
    inp = payload.get("tool_input", {}) or {}
    command = inp.get("command", "")
    if not command:
        return 0

    # Don't gate the skill itself; the skill owns the authoritative preflight.
    if _is_run_experiment_invocation(command):
        return 0
    # Don't gate help/listing.
    if re.search(r"\b(ls|stat|cat|less|head|tail|file|find|grep)\b", command.split()[0] if command.split() else ""):
        return 0

    try:
        experiments = _read_zone_b_experiments()
    except Exception:
        # Any parsing failure → fall through. Spurious blocks are worse.
        return 0

    entry = _matched_experiment(command, experiments)
    if entry is None:
        return 0

    # Device lock.
    device_id = entry.get("device_id")
    if not device_id:
        return _block(
            f"experiment {entry.get('id')} は execution_target={entry.get('execution_target')} ですが、"
            "Zone B 登録に device_id がありません。`/init-experiment` で再登録してください。"
        )
    lock_path = _project_root() / "data" / "locks" / f"{device_id}.lock"
    held, why = _check_lock(lock_path)
    if not held:
        return _block(why or f"device lock {lock_path} が未取得です。")

    target = entry.get("execution_target")
    if target == "hil":
        bench_id = entry.get("bench_id")
        if not bench_id:
            return _block(f"HIL 実験ですが bench_id が登録されていません。")
        bench_lock = _project_root() / "data" / "locks" / f"{bench_id}.lock"
        held_b, why_b = _check_lock(bench_lock)
        if not held_b:
            return _block(why_b or f"bench lock {bench_lock} が未取得です。")
        sc = _check_bench_selfcheck(entry)
        if sc:
            return _block(sc)

    cal = _check_calibration(entry)
    if cal:
        return _block(cal + " `/calibrate-device` を実行してください。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
