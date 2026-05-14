"""Reproducibility helpers for the claude-experiment template.

Public stable API (do not rename in agents/skills/hooks; see
.claude/rules/reproducibility.md §9.3):

- make_run_id()
- set_seed(seed, frameworks=None)
- hash_file(path)
- write_initial_metadata(run_id, *, experiment_entry, resolved, args,
                         config_snapshot_path, build_id)
- patch_metadata(run_id, **fields)
- finalize_metadata(run_id, exit_state)

Secondary helpers (used by native launchers and /run-experiment step 5):

- read_build_manifest(build_id)
- verify_binary_hash(manifest, artifact_path)
- compute_source_tree_hash()

The metadata schema is the one defined in .claude/rules/reproducibility.md §2.
Field ownership is the table in §9. Any divergence in this file from those
two sections is a bug in this file; do not paraphrase the schema elsewhere.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import random
import secrets
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# --- paths --------------------------------------------------------------

def _project_root() -> Path:
    """Resolve the project root.

    Priority: CLAUDE_PROJECT_DIR env var (set by Claude Code), else walk up
    from the importing module's __file__ looking for CLAUDE.md.
    """
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env).resolve()
    # Fallback: walk up from this file.
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / "CLAUDE.md").exists():
            return parent
    return Path.cwd().resolve()


def _run_dir(run_id: str) -> Path:
    return _project_root() / "data" / "results" / run_id


def _metadata_path(run_id: str) -> Path:
    return _run_dir(run_id) / "metadata.json"


# --- run_id allocation --------------------------------------------------

def make_run_id() -> str:
    """Allocate a `<UTC ISO-8601 with hyphens>_<8-char hash>` run id.

    The hyphenated form (`2026-05-14T12-34-56`) is filesystem-safe across
    platforms (the colons in raw ISO-8601 are not). The 8-char suffix is a
    fresh random hex token, NOT a content hash — uniqueness across rapid
    sequential calls is what matters here.
    """
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%dT%H-%M-%S")
    suffix = secrets.token_hex(4)  # 8 lowercase hex chars
    return f"{stamp}_{suffix}"


# --- seeding ------------------------------------------------------------

def set_seed(seed: int, frameworks: list[str] | None = None) -> dict[str, int]:
    """Set seeds for the frameworks listed (defaults: random, numpy).

    Returns a dict {framework: seed_used} suitable for `sim.seeds_per_framework`.
    Frameworks not currently importable are skipped silently — the caller
    should record the resolved dict, not the requested list.
    """
    out: dict[str, int] = {}
    random.seed(seed)
    out["python_random"] = seed
    requested = frameworks if frameworks is not None else ["numpy"]

    if "numpy" in requested:
        try:
            import numpy as np  # type: ignore[import-not-found]
            np.random.seed(seed)
            out["numpy"] = seed
        except ImportError:
            pass
    if "torch" in requested:
        try:
            import torch  # type: ignore[import-not-found]
            torch.manual_seed(seed)
            if torch.cuda.is_available():
                torch.cuda.manual_seed_all(seed)
            out["torch"] = seed
        except ImportError:
            pass
    if "jax" in requested:
        # JAX seeds are per-call keys, so we just store the master seed; the
        # driver derives subkeys from jax.random.PRNGKey(seed).
        try:
            import jax  # type: ignore[import-not-found]
            del jax  # imported only to verify availability
            out["jax"] = seed
        except ImportError:
            pass
    if "tensorflow" in requested or "tf" in requested:
        try:
            import tensorflow as tf  # type: ignore[import-not-found]
            tf.random.set_seed(seed)
            out["tensorflow"] = seed
        except ImportError:
            pass
    return out


# --- hashing ------------------------------------------------------------

def hash_file(path: str | os.PathLike[str]) -> str:
    """SHA-256 of a single file's contents, returned as lowercase hex."""
    h = hashlib.sha256()
    p = Path(path)
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_source_tree_hash() -> str:
    """SHA-256 over the sorted list of tracked source paths + their file hashes.

    Independent of `git rev-parse HEAD`: a dirty working tree yields a
    different hash even at the same commit. Used for `build_id` cache lookup.

    Falls back to an empty-hash if `git` is unavailable; the caller MUST
    treat this as "no cache hit possible".
    """
    root = _project_root()
    try:
        out = subprocess.run(
            ["git", "ls-files"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""
    h = hashlib.sha256()
    for rel in sorted(out.stdout.splitlines()):
        p = root / rel
        if not p.is_file():
            continue
        try:
            file_hash = hash_file(p)
        except OSError:
            continue
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(file_hash.encode("ascii"))
        h.update(b"\n")
    return h.hexdigest()


# --- git rev ------------------------------------------------------------

def _git_rev() -> tuple[str, bool]:
    """Return (rev, clean). `rev` has `-dirty` suffix when working tree is dirty."""
    root = _project_root()
    try:
        rev = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ("no-git", True)
    try:
        diff = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return (rev, True)
    clean = diff == ""
    if not clean:
        rev = f"{rev}-dirty"
    return (rev, clean)


# --- env capture --------------------------------------------------------

def _python_version() -> str:
    return ".".join(map(str, sys.version_info[:3]))


def _package_versions() -> dict[str, str]:
    """Return a sorted dict of installed package -> version.

    Uses importlib.metadata which respects the active environment (uv run
    point to the right interpreter automatically).
    """
    out: dict[str, str] = {}
    for dist in importlib.metadata.distributions():
        name = (dist.metadata["Name"] or "").lower()
        if not name:
            continue
        out[name] = dist.version or ""
    return dict(sorted(out.items()))


def _platform_string() -> str:
    return f"{platform.system().lower()}-{platform.machine().lower()}"


# --- atomic JSON write --------------------------------------------------

def _atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON atomically (tmp + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=False)
        f.write("\n")
    os.replace(tmp, path)


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


# --- scheduler env ------------------------------------------------------

_SCHEDULER_ENV_MAP = {
    "slurm": {
        "job_id": "SLURM_JOB_ID",
        "queue": "SLURM_JOB_PARTITION",
        "node_type": "SLURM_JOB_PARTITION",  # placeholder; many sites use SLURM_JOB_CONSTRAINT
        "nodes": "SLURM_JOB_NUM_NODES",
        "cores_per_node": "SLURM_CPUS_ON_NODE",
        "gpus_per_node": "SLURM_GPUS_ON_NODE",
    },
    "pbs": {
        "job_id": "PBS_JOBID",
        "queue": "PBS_QUEUE",
    },
    "lsf": {
        "job_id": "LSB_JOBID",
        "queue": "LSB_QUEUE",
    },
    "sge": {
        "job_id": "JOB_ID",
        "queue": "QUEUE",
    },
    "kubernetes": {
        "job_id": "JOB_NAME",
    },
}


def _scheduler_block(kind: str) -> dict[str, Any]:
    """Best-effort capture of scheduler fields from env vars."""
    if kind == "none":
        return {}
    out: dict[str, Any] = {"kind": kind}
    for field, env_var in _SCHEDULER_ENV_MAP.get(kind, {}).items():
        v = os.environ.get(env_var)
        if v is None:
            continue
        if field in {"nodes", "cores_per_node", "gpus_per_node"}:
            try:
                out[field] = int(v)
            except ValueError:
                out[field] = v
        else:
            out[field] = v
    # Submitted job script hash and walltime are passed through env by the skill.
    js = os.environ.get("EXPERIMENT_JOB_SCRIPT_SHA256")
    if js:
        out["job_script_hash"] = js
    wt = os.environ.get("EXPERIMENT_WALLTIME_REQUESTED_S")
    if wt:
        try:
            out["walltime_requested_s"] = int(wt)
        except ValueError:
            pass
    return out


# --- target blocks ------------------------------------------------------

def _sim_block(seed: int | None) -> dict[str, Any]:
    blk: dict[str, Any] = {}
    if seed is not None:
        blk["seed"] = seed
    blk["python_version"] = _python_version()
    blk["package_versions"] = _package_versions()
    return blk


def _device_block(experiment_entry: dict[str, Any]) -> dict[str, Any]:
    """Initial device block. Only the orchestrator-knowable subset is filled
    here; device-operator fills the rest later via patch_metadata.
    """
    device_id = experiment_entry.get("device_id")
    if not device_id:
        return {}
    return {
        "device_id": device_id,
        "lock_path": f"data/locks/{device_id}.lock",
    }


def _hil_block(
    experiment_entry: dict[str, Any], config_snapshot: dict[str, Any] | None
) -> dict[str, Any]:
    """Initial HIL block. Reads hil.coupling_mode, hil.sample_rate_hz,
    hil.simulator from the resolved config snapshot if present. The bench
    self-check and interlocks are added later by device-operator.
    """
    bench_id = experiment_entry.get("bench_id")
    if not bench_id:
        return {}
    blk: dict[str, Any] = {
        "bench_id": bench_id,
        "bench_lock_path": f"data/locks/{bench_id}.lock",
    }
    if config_snapshot:
        hil_cfg = config_snapshot.get("hil", {})
        for key in ("coupling_mode", "sample_rate_hz", "simulator"):
            if key in hil_cfg:
                blk[key] = hil_cfg[key]
    return blk


# --- public: write_initial_metadata -------------------------------------

def write_initial_metadata(
    run_id: str,
    *,
    experiment_entry: dict[str, Any],
    resolved: dict[str, Any],
    args: dict[str, Any],
    config_snapshot_path: str | os.PathLike[str],
    build_id: str | None,
) -> Path:
    """Write the schema-complete initial `metadata.json`.

    `experiment_entry` is the Zone B entry. `resolved` is the dict
    {runtime, execution_target, compute_target} from CLAUDE.md §Resolution.
    `args` is the full CLI args dict the driver received. `build_id` is
    None for `runtime: python-uv`.
    """
    run_dir = _run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    # Resolve the snapshot path. Accept either:
    #   (a) absolute path
    #   (b) path relative to project root (CWD when invoked normally)
    #   (c) path relative to run_dir (just the basename, e.g. "config.snapshot.yaml")
    raw = Path(config_snapshot_path)
    if raw.is_absolute():
        snap_path = raw
    elif raw.exists():
        snap_path = raw.resolve()
    elif (run_dir / raw).exists():
        snap_path = (run_dir / raw).resolve()
    else:
        raise FileNotFoundError(
            f"config snapshot not found at any of: {raw} (cwd), {run_dir / raw}"
        )
    config_snapshot_sha256 = hash_file(snap_path)

    # Also read the snapshot to source HIL config fields.
    config_snapshot: dict[str, Any] | None = None
    try:
        text = snap_path.read_text(encoding="utf-8")
        # Try JSON first, then yaml.safe_load if available.
        try:
            config_snapshot = json.loads(text)
        except json.JSONDecodeError:
            try:
                import yaml  # type: ignore[import-not-found]
                config_snapshot = yaml.safe_load(text)
            except ImportError:
                config_snapshot = None
    except OSError:
        config_snapshot = None

    script_path = experiment_entry["entrypoint"]
    entrypoint_abs = _project_root() / script_path
    entrypoint_sha256 = hash_file(entrypoint_abs)
    git_rev, git_clean = _git_rev()
    execution_target = resolved["execution_target"]
    compute_target = resolved["compute_target"]

    md: dict[str, Any] = {
        "run_id": run_id,
        "experiment_id": experiment_entry["id"],
        "experiment_family": experiment_entry.get("family"),
        "sweep_id": args.get("sweep_id"),
        "execution_target": execution_target,
        "started_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "finished_at": None,
        "exit_state": None,  # filled by finalize_metadata
        "pid": os.getpid(),
        "git_rev": git_rev,
        "git_clean": git_clean,
        "script": script_path,
        "entrypoint_sha256": entrypoint_sha256,
        "args": args,
        "config_snapshot_path": snap_path.relative_to(run_dir).as_posix() if snap_path.is_relative_to(run_dir) else str(snap_path),
        "config_snapshot_sha256": config_snapshot_sha256,
        "build_id": build_id,
        "compute_target": compute_target,
        "platform": _platform_string(),
    }

    if execution_target == "sim":
        md["sim"] = _sim_block(seed=args.get("seed"))
    elif execution_target == "device":
        md["device"] = _device_block(experiment_entry)
    elif execution_target == "hil":
        md["device"] = _device_block(experiment_entry)
        md["hil"] = _hil_block(experiment_entry, config_snapshot)

    if compute_target == "cluster":
        scheduler_kind = os.environ.get("EXPERIMENT_SCHEDULER_KIND", "none")
        if scheduler_kind != "none":
            md["scheduler"] = _scheduler_block(scheduler_kind)

    _atomic_write_json(_metadata_path(run_id), md)
    return _metadata_path(run_id)


# --- public: patch_metadata ---------------------------------------------

def _deep_merge(dst: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    """Shallow merge per top-level key. For known nested blocks
    (sim/device/hil/scheduler), do a one-level merge of inner keys."""
    NESTED = {"sim", "device", "hil", "scheduler"}
    for k, v in src.items():
        if k in NESTED and isinstance(v, dict) and isinstance(dst.get(k), dict):
            inner = dict(dst[k])
            inner.update(v)
            dst[k] = inner
        else:
            dst[k] = v
    return dst


def patch_metadata(run_id: str, **fields: Any) -> None:
    """Read-modify-write the run's metadata.json with the given fields.

    For nested target blocks pass them as nested dicts:
        patch_metadata(run_id, device={"firmware_rev": "1.2.3"})

    This is atomic at the file level (write to tmp + os.replace). Concurrent
    writers race-lose-write — for the small handful of cooperative writers in
    this template (driver + device-operator + skill preflight) this is
    sufficient. If a project needs true cross-process locking, wrap calls in
    fcntl/portalocker.
    """
    path = _metadata_path(run_id)
    if not path.exists():
        raise FileNotFoundError(
            f"metadata.json not found for run {run_id}; call write_initial_metadata first"
        )
    data = _read_json(path)
    _deep_merge(data, fields)
    _atomic_write_json(path, data)


# --- public: finalize_metadata ------------------------------------------

def finalize_metadata(run_id: str, exit_state: str) -> None:
    """Write `finished_at` and `exit_state`. Idempotent.

    For cluster runs with EXPERIMENT_STARTED_AT in env, also set
    `scheduler.walltime_used_s`.
    """
    VALID = {"success", "crash", "aborted", "safe-stop", "interrupted"}
    if exit_state not in VALID:
        raise ValueError(
            f"exit_state must be one of {sorted(VALID)}, got {exit_state!r}"
        )
    path = _metadata_path(run_id)
    if not path.exists():
        # Nothing to finalize; the caller is past the point of writing.
        return
    data = _read_json(path)
    # Idempotence: don't overwrite an already-terminal state from a later
    # cleanup pass; only refresh finished_at if missing.
    cur = data.get("exit_state")
    if cur in VALID:
        if not data.get("finished_at"):
            data["finished_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            _atomic_write_json(path, data)
        return
    data["exit_state"] = exit_state
    data["finished_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if data.get("compute_target") == "cluster" and "scheduler" in data:
        started_env = os.environ.get("EXPERIMENT_STARTED_AT_EPOCH")
        if started_env:
            try:
                used = int(time.time() - float(started_env))
                if used >= 0:
                    sched = dict(data["scheduler"])
                    sched["walltime_used_s"] = used
                    data["scheduler"] = sched
            except ValueError:
                pass
    _atomic_write_json(path, data)


# --- secondary: build manifest helpers ----------------------------------

def read_build_manifest(build_id: str) -> dict[str, Any]:
    """Load `data/builds/<build_id>/manifest.json` as a dict."""
    path = _project_root() / "data" / "builds" / build_id / "manifest.json"
    return _read_json(path)


def verify_binary_hash(
    manifest: dict[str, Any], artifact_path: str | os.PathLike[str]
) -> None:
    """Verify the binary's SHA-256 matches the manifest entry. Raises on mismatch."""
    artifact_p = Path(artifact_path).resolve()
    expected: str | None = None
    for art in manifest.get("artifacts", []):
        if Path(art["path"]).resolve() == artifact_p or art["path"] == str(artifact_path):
            expected = art["sha256"]
            break
    if expected is None:
        raise ValueError(
            f"artifact {artifact_path} not listed in manifest {manifest.get('build_id')}"
        )
    actual = hash_file(artifact_p)
    if actual != expected:
        raise ValueError(
            f"binary hash mismatch for {artifact_path}: "
            f"manifest says {expected}, on-disk is {actual}"
        )


# --- exports ------------------------------------------------------------

__all__ = [
    "make_run_id",
    "set_seed",
    "hash_file",
    "write_initial_metadata",
    "patch_metadata",
    "finalize_metadata",
    "read_build_manifest",
    "verify_binary_hash",
    "compute_source_tree_hash",
]
