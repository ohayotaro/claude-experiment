# Research integrity

These rules are non-negotiable. Any agent or skill that violates them is wrong, regardless of what the user asked for.

## Hard prohibitions

- **No fabrication.** Do not invent data points, results, or measurements. Every number that ends up in `docs/research/` or in a report must come from a script in `src/` whose run is recorded in `data/results/<run_id>/`.
- **No falsification.** Do not modify recorded results to make them look better. If you find a bug in analysis code, write a new run with a new `run_id` and explain the difference in `docs/research/analysis.md`.
- **No selective reporting.** If you ran 5 experiments and 1 supports the hypothesis, you must report all 5. Cherry-picking is fabrication by omission.
- **No silent retries until success.** Re-running a failing device experiment hoping for a different outcome, without recording the failures, is selective reporting. Every launched run produces a `run_id` even if it crashes or is aborted — the `exit_state` field captures the outcome.
- **No p-hacking.** See `statistical-rigor.md`.

## Negative, partial, and aborted runs

- Negative, null, partial, aborted, and inconclusive results are first-class. Report them in `docs/research/analysis.md`. Do not bury them.
- A failed run is data. Do not delete its `run_id` directory.
- `metadata.exit_state` must reflect the actual outcome:
  - `success` — ran to completion, all assertions passed
  - `crash` — process terminated by signal or unhandled exception
  - `aborted` — operator hit abort (typical for device/HIL)
  - `safe-stop` — safety system fired (interlock, e-stop, watchdog)
  - `interrupted` — external signal (SIGTERM, scheduler timeout)
- The `experiment-runner` agent and the `/run-experiment` skill must write metadata even on failure paths. If they cannot (e.g. process killed -9), a partial `metadata.json` with `exit_state: interrupted` is written by the wrapper on next session start.

## Data handling

- `data/raw/` is append-only. Never overwrite or delete a file under `raw/`. If raw data is wrong, document the error and ingest a corrected copy under a new name.
- `data/processed/` may be regenerated, but the script that produces it must be in `src/` and the regeneration must be reproducible from `raw/`.
- `data/results/<run_id>/` is immutable once written. To revise an analysis, create a new `run_id`.
- `data/builds/<build_id>/` is immutable once written. A rebuild with different sources produces a new `build_id`.
- `data/locks/<device_id>.lock` is owned by the session holding the device. Releasing someone else's lock without explicit user confirmation is a violation.

## Authorship and contribution

- Agents are tools, not authors. The human user is the author of any code, dataset, or report produced. Acknowledge AI assistance per the venue's policy when a report is published.
- Code and configuration committed to this repository are the user's responsibility. Generated code that has not been read by the user must be flagged in commit messages.

## When in doubt

Stop and ask the user. Do not guess on integrity questions.
