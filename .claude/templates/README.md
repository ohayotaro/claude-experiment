# .claude/templates/

Starter files copied into the project root by `/init-experiment` based on
the resolved `runtime` in Zone B. After the copy, the files belong to the
project; edit them freely.

## Layout

```
python-uv/    — Python helpers + uv project skeleton (always copied;
                analysis runs in Python regardless of experiment runtime)
cpp-cmake/    — CMakeLists.txt stub. Copied additionally when runtime: cpp-cmake.
rust-cargo/   — Cargo.toml workspace stub. Copied additionally when runtime: rust-cargo.
make/         — Makefile stub. Copied additionally when runtime: make.
```

## What `/init-experiment` does

For ANY runtime, the following are copied from `python-uv/`:

| Source | Destination | Purpose |
|---|---|---|
| `python-uv/repro.py` | `src/utils/repro.py` | Reproducibility helpers — six public + three secondary functions per `.claude/rules/reproducibility.md` §9.3. |
| `python-uv/viz.py` | `src/utils/viz.py` | Publication-quality matplotlib styling, Okabe–Ito palette, `save_figure`. Used by `data-analyst`. |
| `python-uv/pyproject.toml` | `pyproject.toml` | uv project skeleton with `package = false`. |
| `python-uv/.gitignore` | `.gitignore` | Excludes `.venv/`, `data/raw/*`, `data/processed/*`, in-tree `build/` and `target/`. |

When `runtime != python-uv`, the runtime-specific stub is copied additionally:

| Runtime | Additional copy |
|---|---|
| `cpp-cmake` | `cpp-cmake/CMakeLists.txt` → repo root |
| `rust-cargo` | `rust-cargo/Cargo.toml` → repo root |
| `make` | `make/Makefile` → repo root |
| `mixed` | None at init; `/design-experiment` handles per-experiment native bootstrap. |

## Adding a new runtime

1. Create `.claude/templates/<runtime-name>/` with the stub files.
2. Update `init-experiment/SKILL.md` step 6 to list the new mapping.
3. Update `.claude/rules/reproducibility.md` §3 (build provenance) if the
   new runtime needs additional toolchain fields in the build manifest.
4. Update `build-engineer.md` to know how to probe the new toolchain.
