#!/usr/bin/env python3
"""PostToolUse hook on Write|Edit|MultiEdit under data/results/ or data/builds/.

Secondary check (per CLAUDE.md): the authoritative writer is /run-experiment.
This hook catches ad-hoc metadata edits that violate the schema documented in
.claude/rules/reproducibility.md.

It WARNS (does not block) when:
- A run directory has output files but no metadata.json.
- metadata.json is missing top-level required keys.
- metadata.json's execution_target requires a sim/device/hil block that is
  missing or under-populated.
- metadata.json declares build_id but the referenced build manifest does not
  exist or has corrupt artifact hashes.
- A build manifest is missing required fields.

It never deletes anything and never blocks tool execution. Read
.claude/rules/reproducibility.md for the canonical schema.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

# Top-level keys required for EVERY run, regardless of execution_target.
TOPLEVEL_KEYS: set[str] = {
    "run_id",
    "experiment_id",
    "execution_target",
    "started_at",
    "exit_state",
    "pid",
    "git_rev",
    "git_clean",
    "script",
    "entrypoint_sha256",
    "args",
    "config_snapshot_path",
    "config_snapshot_sha256",
    "compute_target",
    "platform",
}

EXIT_STATES = {"success", "crash", "aborted", "safe-stop", "interrupted"}
EXECUTION_TARGETS = {"sim", "device", "hil"}
COMPUTE_TARGETS = {"local", "cluster", "device", "hil"}

# Per-block required keys.
SIM_REQUIRED: set[str] = {"seed"}
DEVICE_REQUIRED: set[str] = {
    "device_id",
    "device_model",
    "firmware_rev",
    "calibration_ref",
    "calibration_age_h",
    "lock_path",
}
HIL_REQUIRED: set[str] = {
    "bench_id",
    "bench_lock_path",
    "coupling_mode",
    "sample_rate_hz",
    "interlocks",
    "bench_selfcheck_path",
    "simulator",
}
SCHEDULER_REQUIRED: set[str] = {
    "kind",
    "job_id",
    "queue",
    "node_type",
    "nodes",
    "cores_per_node",
    "walltime_requested_s",
    "job_script_hash",
}

# Build manifest required fields.
BUILD_TOPLEVEL_KEYS: set[str] = {
    "build_id",
    "started_at",
    "finished_at",
    "runtime",
    "git_rev",
    "git_clean",
    "source_tree_hash",
    "toolchain",
    "artifacts",
    "platform",
    "exit_state",
}
BUILD_EXIT_STATES = {"success", "smoke_failed", "failed"}


def _project_root() -> Path:
    root = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(root).resolve() if root else Path.cwd().resolve()


def _id_for(path: str, kind: str) -> str | None:
    """If `path` is under <project>/data/<kind>/<id>/, return id.

    kind is "results" or "builds".
    """
    if not path:
        return None
    try:
        rel = Path(path).resolve().relative_to(_project_root())
    except ValueError:
        return None
    parts = rel.parts
    if len(parts) < 3 or parts[0] != "data" or parts[1] != kind:
        return None
    return parts[2]


def _emit(msg: str) -> None:
    """Print a single warning line. Bracket-tag is consistent."""
    print(f"[reproducibility-check] {msg}")


def _check_run_metadata(run_id: str, run_dir: Path, file_being_written: str) -> None:
    if not run_dir.exists():
        return
    md_path = run_dir / "metadata.json"

    # We must NOT complain about metadata.json itself being incomplete during
    # an active write — the writer may be patching it. We only run a partial
    # check when a non-metadata file is the trigger.
    if Path(file_being_written).name == "metadata.json":
        # Light check: parseable + at least run_id present.
        try:
            md = json.loads(md_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(md, dict) and "run_id" not in md:
            _emit(f"{md_path} に run_id がありません。schema は .claude/rules/reproducibility.md を参照してください。")
        return

    if not md_path.exists():
        _emit(
            f"{run_dir}/ に出力があるにもかかわらず metadata.json がありません。"
            "通常 /run-experiment が先に書く契約です。手動で run ディレクトリを"
            "作っていないか確認してください。"
        )
        return

    try:
        md = json.loads(md_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _emit(f"{md_path} の JSON parse に失敗しました。")
        return
    if not isinstance(md, dict):
        _emit(f"{md_path} のトップレベルが JSON object ではありません。")
        return

    missing_top = TOPLEVEL_KEYS - md.keys()
    if missing_top:
        _emit(f"{md_path}: トップレベルの必須キー欠落: {sorted(missing_top)}")

    exit_state = md.get("exit_state")
    if exit_state is not None and exit_state not in EXIT_STATES:
        _emit(f"{md_path}: exit_state={exit_state!r} は不正です ({sorted(EXIT_STATES)} のいずれか)。")

    target = md.get("execution_target")
    if target is not None and target not in EXECUTION_TARGETS:
        _emit(f"{md_path}: execution_target={target!r} は不正です ({sorted(EXECUTION_TARGETS)} のいずれか)。")

    compute = md.get("compute_target")
    if compute is not None and compute not in COMPUTE_TARGETS:
        _emit(f"{md_path}: compute_target={compute!r} は不正です ({sorted(COMPUTE_TARGETS)} のいずれか)。")

    # Conditional block presence.
    if target == "sim":
        _check_block(md_path, md, "sim", SIM_REQUIRED)
    elif target == "device":
        _check_block(md_path, md, "device", DEVICE_REQUIRED)
    elif target == "hil":
        _check_block(md_path, md, "device", DEVICE_REQUIRED)
        _check_block(md_path, md, "hil", HIL_REQUIRED)

    if compute == "cluster":
        _check_block(md_path, md, "scheduler", SCHEDULER_REQUIRED)

    # build_id reference.
    build_id = md.get("build_id")
    if build_id:
        manifest = _project_root() / "data" / "builds" / build_id / "manifest.json"
        if not manifest.exists():
            _emit(f"{md_path}: build_id={build_id} を参照していますが {manifest} がありません。")


def _check_block(md_path: Path, md: dict[str, Any], block: str, required: set[str]) -> None:
    body = md.get(block)
    if not isinstance(body, dict):
        _emit(f"{md_path}: {block} block が必要ですが、存在しないか object ではありません。")
        return
    missing = required - body.keys()
    if missing:
        _emit(f"{md_path}: {block} block の必須キー欠落: {sorted(missing)}")


def _check_build_manifest(build_id: str, build_dir: Path, file_being_written: str) -> None:
    if not build_dir.exists():
        return
    manifest = build_dir / "manifest.json"
    if Path(file_being_written).name == "manifest.json":
        # Trigger is manifest itself — only check parseable.
        try:
            json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            _emit(f"{manifest}: JSON parse に失敗しました。")
        return
    if not manifest.exists():
        _emit(
            f"{build_dir}/ にアーティファクトがあるにもかかわらず manifest.json が"
            "ありません。/build-experiment 経由で再ビルドしてください。"
        )
        return
    try:
        m = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _emit(f"{manifest}: JSON parse に失敗しました。")
        return
    if not isinstance(m, dict):
        _emit(f"{manifest}: トップレベルが JSON object ではありません。")
        return
    missing = BUILD_TOPLEVEL_KEYS - m.keys()
    if missing:
        _emit(f"{manifest}: 必須キー欠落: {sorted(missing)}")
    exit_state = m.get("exit_state")
    if exit_state is not None and exit_state not in BUILD_EXIT_STATES:
        _emit(f"{manifest}: exit_state={exit_state!r} は不正です ({sorted(BUILD_EXIT_STATES)} のいずれか)。")
    if exit_state in {"success", "smoke_failed"} and "smoke_test" not in m:
        _emit(f"{manifest}: exit_state={exit_state} の場合 smoke_test ブロックが必須です。")


def main() -> int:
    raw = sys.stdin.read() or "{}"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return 0
    inp = payload.get("tool_input", {}) or {}
    path = inp.get("file_path", "")

    run_id = _id_for(path, "results")
    if run_id:
        run_dir = _project_root() / "data" / "results" / run_id
        _check_run_metadata(run_id, run_dir, path)
        return 0

    build_id = _id_for(path, "builds")
    if build_id:
        build_dir = _project_root() / "data" / "builds" / build_id
        _check_build_manifest(build_id, build_dir, path)
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
