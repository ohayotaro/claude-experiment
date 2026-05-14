# Statistical rigor

## When this rule applies

Loaded by default. Activates whenever an experiment, sweep, or report compares
groups, estimates an effect, or draws an inference. The activation flag is
the experiment's `inference_kind` in `docs/research/methodology.md`:

| `inference_kind` | This rule activates? |
|---|---|
| `descriptive` (single measurement, no comparison) | partial: reporting standard for the single value, no p-values needed |
| `comparison` (group A vs B, before/after, controlled vs perturbed) | fully |
| `sweep-inference` (parameter sweep used to infer a relationship or optimum) | fully — plus the multi-comparison correction below |
| `none` (the experiment is a demo / smoke test) | not applicable |

The `data-analyst` agent reads `inference_kind` and refuses to compute
p-values for `descriptive` or `none` experiments. The `script-reviewer` agent
flags `inference_kind: comparison` scripts that do not report effect size or
CI.

The rest of this file uses the strong form (applies fully).

---

## Pre-registration of analysis

- Decide the primary outcome, the statistical test, the significance threshold, and the stopping rule **before** you look at the data. Record these in `docs/research/methodology.md`.
- Any test added after data inspection must be labeled "exploratory" in the analysis section. Do not present exploratory tests as confirmatory.

## Reporting standard

For every reported test:
- Effect size (Cohen's d, odds ratio, R², etc.) — not just p-values.
- 95% confidence interval (or credible interval if Bayesian).
- Sample size (n) — count of independent runs, not measurements.
- Test name and assumptions checked.
- Whether the test was pre-registered or exploratory.

A bare p-value with no effect size and no CI is unacceptable.

## Multiple comparisons

- If running k > 1 tests on the same dataset, apply correction (Holm–Bonferroni, BH-FDR, or report family-wise error rate explicitly).
- Document the family of tests in `methodology.md`.
- Parameter sweeps that test for "best setting" implicitly run many comparisons; treat sweep-inference as multi-comparison by default.

## Forbidden practices

- **p-hacking.** Do not try multiple tests, exclusions, or transformations until p < 0.05 and report only the winning combination.
- **HARKing.** Do not present a hypothesis discovered after seeing the data as if it were pre-specified.
- **Cherry-picking subgroups.** Subgroup analyses are exploratory unless pre-registered.
- **Outlier removal without justification.** If you remove outliers, define the rule before looking at data and report results both with and without removal.
- **Selective re-running.** Re-running a device experiment until the result looks better — without recording the prior runs — is a flavor of p-hacking. See `research-integrity.md`.

## Power and sample size

- Compute and report power for the primary test. Aim for power ≥ 0.8 at the smallest effect size you would consider scientifically meaningful (SESOI).
- For simulation experiments, "sample size" is the number of independent seeds, not the simulation duration.
- If power is below 0.8 due to constraints (cluster time, hardware availability, calibration burden), acknowledge underpowering in the report.

## Bayesian alternative

If you use Bayesian methods, report the prior, posterior, credible interval, and a sensitivity analysis to the prior. Do not silently switch frameworks.
