---
name: calibrate-device
description: Run an experiment's calibration script under device-operator's supervision, save the resulting calibration artefact + metadata sidecar to data/calibrations/. Required when calibration_age_h exceeds the experiment's tolerance.
when_to_use: Before the first run of a device/HIL experiment, and whenever the most recent calibration is stale (default >24h). Re-runnable.
inputs:
  - <id> — required positional argument; an `experiment_id` whose `execution_target ∈ {device, hil}`. Calibration is meaningful for any such experiment regardless of `safety_class`; the freshness check at `/run-experiment` always reads the calibration sidecar.
  - --device-id <id> (optional override — only when the registry entry shares a device with another experiment and a non-default one is needed)
  - --notes <text> (optional — appended to the calibration metadata sidecar)
outputs:
  - data/calibrations/<calibration_ref>.<ext> — the calibration artefact (format depends on the experiment's calibration script)
  - data/calibrations/<calibration_ref>.meta.json — sidecar with device_id, firmware_rev, ambient, operator, calibration_age_h baseline (0), notes
  - docs/research/incidents.md — appended only if the calibration failed or surfaced anomalies
delegated_agent: device-operator (executes the calibration; this skill is the workflow wrapper)
next_skill: /run-experiment <id>
---

# /calibrate-device

Produces a fresh calibration artefact for one device or HIL bench. The `calibration_ref` becomes the canonical reference recorded in subsequent run metadata under `device.calibration_ref`; `device.calibration_age_h` is computed from the artefact's mtime at each run.

## Steps for the orchestrator

1. **Resolve `<id>`.** Look up `experiments[id == <id>]` in Zone B. Required fields:
   - `execution_target ∈ {device, hil}`
   - `device_id` (resolved either from the registry entry or `--device-id`)
2. **Pre-flight.**
   - Confirm `data/locks/<device_id>.lock` is held by this session (call out to `/lock-device <device_id>` if not, and ask the user before acquiring).
   - For HIL, also confirm `data/locks/<bench_id>.lock`.
   - Resolve the calibration script path: registry's `calibration_script` field if present, else the convention `src/experiments/<id>/device/calibrate.py`. If neither exists, surface a clear remediation: re-run `/design-experiment <id>` or write the calibration script first.
3. **Allocate `calibration_ref`** as `<device_id>-<UTC ISO with hyphens>` (e.g. `mems-01-2026-05-14T12-30-00`). The reference is device-scoped so `/run-experiment` §8.2 can look up the freshest calibration for a given `device_id` without parsing the filename. The originating experiment_id is recorded in the sidecar `experiment_id` field.
4. **Delegate to `device-operator` §B (Calibration)** with the experiment entry, the resolved `device_id`, the calibration script path, and the target output path `data/calibrations/<calibration_ref>.<ext>`. The agent:
   - Brings the device online (vendor-specific init).
   - Executes the calibration sequence per the script.
   - Saves the artefact (raw points, fit coefficients, look-up table, etc. — format determined by the experiment).
   - Returns a structured handoff including any anomalies.
5. **Write the metadata sidecar** at `data/calibrations/<calibration_ref>.meta.json`:
   ```json
   {
     "calibration_ref": "<calibration_ref>",
     "experiment_id": "<id>",
     "device_id": "<device_id>",
     "device_model": "<vendor + model from device-operator>",
     "firmware_rev": "<from device-operator>",
     "ambient": { "temperature_c": ..., "humidity_pct": ..., "supply_voltage_v": ... },
     "operator": "<from lock file>",
     "performed_at": "<ISO-8601 UTC>",
     "calibration_artefact": "<calibration_ref>.<ext>",
     "result_summary": "<one-line from device-operator>",
     "anomalies": [],
     "notes": "<from --notes if any>"
   }
   ```
   The sidecar is the source of truth for `device.calibration_age_h` (computed as `(now - performed_at).total_seconds() / 3600`).
6. **Handle anomalies.** If `device-operator` reports anomalies (out-of-range readings, drift detected, partial completion):
   - Record them in `anomalies[]`.
   - Append a one-line entry to `docs/research/incidents.md` (if `safety_class: destructive`, this is mandatory; otherwise the user is asked).
   - Surface clearly to the user; do NOT mark the calibration as the freshest unless the user explicitly accepts.
7. **Update Zone C**: `last_skill_run: calibrate-device`. No phase change.
8. **Report** (Japanese): calibration_ref, device_id, performed_at, artefact path, anomaly count, the next suggested action (`/run-experiment <id>` or `/run-experiment <id> --dry-run` for first runs of `safety_class: destructive`).

## Idempotence / freshness rules

- Each invocation produces a **new** `calibration_ref` with a new timestamp. Old calibrations are never overwritten — they stay in `data/calibrations/` as the audit trail.
- The "freshest" calibration for a `device_id` is the one with the most recent `performed_at` whose sidecar has zero anomalies (or `anomalies` explicitly accepted by the user).
- `/run-experiment` §8.2 reads the freshest calibration and computes `calibration_age_h`.

## Hard rules

- Refuse to run without the device (and bench, for HIL) lock held by this session.
- Refuse to run when the experiment has `execution_target: sim` — sim experiments have no device to calibrate.
- Never delete or move files under `data/calibrations/`. Stale calibrations are kept; only the "latest healthy" pointer is conceptual.
- Anomalies are reported, not suppressed. Selective reporting of calibrations is a `research-integrity.md` violation.

## Examples

| User input | Effect |
|---|---|
| `/calibrate-device mems-actuator` | Acquire device, run calibration, save artefact + sidecar. |
| `/calibrate-device mems-actuator --notes "before destructive test"` | Same, with notes recorded. |
| `/calibrate-device mems-actuator --device-id mems-02` | Calibrate against a non-default device of the same family. |
