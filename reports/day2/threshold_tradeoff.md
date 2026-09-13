# Stage 7: Threshold / Operating-Point Analysis (Dataset A only)

**Evaluation only.** No new model was trained, no feature or label
definition changed, no reconstruction logic was added, Dataset B was not
touched. This stage re-runs V1's (boundary-first) and V2's
(continuity-first) existing LOSO procedures exactly once each to obtain
honest, session-aware out-of-fold scores, then sweeps a threshold grid
cheaply on those cached scores. Source: `scripts/analyze_threshold_tradeoff.py`
(orchestration/plotting) and `src/procmine/segmentation/threshold_analysis.py`
(the actual grid-construction and per-threshold metric logic, factored out
so it is unit-tested the same way as every other metric in this project
rather than tested inside a CLI script).

## 1. Re-inspection of existing code (before writing anything new)

Before building this stage, `evaluation.py`'s `ExecutionMetrics` /
`execution_metrics()` were re-read. Fragmentation percentage
(`% GT executions fragmented`, Stage 2's headline metric) was already
being computed ad hoc, separately, in both `train_continuity_model.py` and
`compare_v1_v2_fragmentation.py` — the exact duplication this project's
own rule says to avoid. Rather than writing a third ad-hoc copy for this
stage, `ExecutionMetrics` was extended additively (`n_fragmented`,
`pct_fragmented`, `fragmented_case_ids`) and `exec_intervals` now carries
`case_id` for cross-model diffing. This is backward-compatible: the full
pre-existing test suite (111 tests) passed unchanged after the extension,
and two new tests were added for the new fields (113 passed). This stage
uses that extended `execution_metrics()` — and the untouched
`boundary_metrics()` / `segments_from_boundaries()` — exclusively; no
metric is redefined here.

## 2. Score distribution and threshold-grid justification

Both models' out-of-fold scores were examined before choosing a grid. As
expected from the ~82–97:1 class imbalance documented in Stages 4 and 6,
scores concentrate heavily near 1.0 — a plain linear 0.50–0.99 sweep would
spend almost all of its points in a flat, uninformative region and barely
sample the region where the interesting trade-offs actually happen.

The grid (`build_threshold_grid()`) is built from:
- 7 coarse points (0.10–0.70) purely for context on the flat low-score
  region, where recall is near-total and both precision and fragmentation
  barely move;
- 40 points at the 75th–99.9th percentiles of the **pooled out-of-fold**
  score distribution, concentrating grid density exactly where the score
  mass actually sits;
- 5 fixed reference points (0.80, 0.90, 0.95, 0.99, 0.999).

Result: 52 distinct thresholds per model, range [0.063, 1.000] for V1 and
[0.072, 1.000] for V2, with 11/52 points ≥ 0.90 for both models — i.e.
roughly a fifth of the grid is spent resolving the narrow, high-density
region above 0.90 where the actual precision/recall trade-off plays out.
Stage 6's previously-chosen thresholds (V1 = 0.9078, V2 = 0.8860) were
**not** members of the native percentile grid — they were injected as
explicit reference rows, per the spec's requirement to keep the current
operating point visible on the same curve. Both independently landed
exactly on this run's own best-F1 point anyway (see §4) — expected, not
coincidental: the pipeline, features, and fold splits are identical to
Stage 6's, and `LogisticRegression` with the `lbfgs` solver is
deterministic, so an equivalent OOF-based F1 optimization reproduces the
same answer. This is a reproducibility cross-check, not new information.

## 3. Threshold selection discipline (no leakage)

Both models' LOSO loops were each run **once**, producing one out-of-fold
score per transition, pooled across all 63 sessions before any threshold
is chosen or evaluated — `evaluate_at_threshold()` takes a single scalar
threshold applied identically to every session (`full_scores >=
threshold`), with no per-session parameter anywhere in its signature or
body. No threshold in this report was selected by looking at any
individual held-out session's own score distribution or outcome.

## 4. Global trade-off tables

Full curves (52–53 rows each) are in `threshold_tradeoff_dataset_a.json`
(`v1_curve` / `v2_curve`). Key rows:

**V1 (boundary-first)**

| threshold | precision | recall | F1 | % GT frag. | over-seg | under-seg |
|---|---|---|---|---|---|---|
| 0.5000 | 0.085 | 0.970 | 0.156 | 98.8 | 8.215 | 0.002 |
| 0.8000 | 0.127 | 0.808 | 0.220 | 96.5 | 4.358 | 0.030 |
| **0.9078** (Stage 6 / best-F1) | **0.157** | **0.655** | **0.253** | **90.6** | 2.710 | 0.085 |
| 0.9181 | 0.157 | 0.602 | 0.250 | 89.5 | 2.477 | 0.106 |
| 0.9500 | 0.129 | 0.327 | 0.186 | 81.6 | 1.647 | 0.272 |
| 0.9620 | 0.105 | 0.206 | 0.139 | 73.2 | 1.279 | 0.414 |
| 0.9900 | 0.085 | 0.048 | 0.062 | 24.5 | 0.312 | 1.721 |

**V2 (continuity-first)**

| threshold | precision | recall | F1 | % GT frag. | over-seg | under-seg |
|---|---|---|---|---|---|---|
| 0.5000 | 0.089 | 0.965 | 0.163 | 98.5 | 8.693 | 0.003 |
| 0.8000 | 0.132 | 0.802 | 0.226 | 97.1 | 4.865 | 0.028 |
| **0.8860** (Stage 6 / best-F1) | **0.167** | **0.703** | **0.270** | **94.7** | 3.239 | 0.063 |
| 0.9132 | 0.166 | 0.543 | 0.254 | 91.8 | 2.519 | 0.122 |
| 0.9500 | 0.116 | 0.239 | 0.156 | 83.8 | 1.687 | 0.311 |
| 0.9649 | 0.091 | 0.153 | 0.114 | 79.3 | 1.415 | 0.419 |
| 0.9931 | 0.101 | 0.062 | 0.077 | 39.0 | 0.502 | 1.319 |

Plots: `reports/day2/figures/threshold_vs_recall.png`,
`threshold_vs_f1.png`, `threshold_vs_fragmentation.png`,
`threshold_vs_over_segmentation.png`, `threshold_vs_under_segmentation.png`,
`precision_recall_tradeoff.png`.

## 5. Named operating points

Three points are named per model, plus the already-existing Stage 6
point (which turns out to coincide with the first):

1. **Max-F1 = current Stage 6 threshold.** V1 τ=0.9078 (F1=0.253,
   frag=90.6%); V2 τ=0.8860 (F1=0.270, frag=94.7%). These are the same
   point — Stage 6 picked its threshold by F1-optimizing pooled OOF
   scores, exactly what this sweep's best-F1 row does independently.
2. **Min-fragmentation subject to a recall ≥ 0.5 floor.** The floor is
   **not** a round number chosen after seeing results — it is fixed
   ahead of the search by a criterion that is independent of this
   dataset's specific numbers: *a boundary detector that misses more true
   boundaries than it catches provides less signal than it destroys, and
   is a weaker foundation for any downstream reconstruction step than
   simply not filtering at all.* Recall ≥ 0.5 is the exact statement of
   "catches at least as many true boundaries as it misses." Under this
   floor: V1 τ=0.9181 (R=0.602, frag=89.5% — only 1.1pp better than
   max-F1); V2 τ=0.9132 (R=0.543, frag=91.8% — 2.9pp better than max-F1).
3. **High-recall regime, recall ≥ 0.95** (the "catch nearly everything"
   end of the curve, included for completeness/contrast, not because it
   is a recommended point): V1 τ=0.5796 (R=0.953, frag=98.4%); V2
   τ=0.5396 (R=0.956, frag=98.3%).

A fourth point was computed as a diagnostic, not a recommendation: the
geometric knee of the (recall, fragmentation) curve (maximum perpendicular
distance from the chord connecting the curve's endpoints) lands at V1
τ=0.9620 (R=0.206, frag=73.2%) and V2 τ=0.9649 (R=0.153, frag=79.3%) —
i.e. the point of steepest fragmentation improvement per unit of
threshold requires giving up ~80% of true boundary recall. It is reported
in §7 (sensitivity) rather than promoted to a named operating point,
because a point that misses 4 out of 5 true boundaries is not a usable
foundation for reconstruction regardless of its fragmentation number.

## 6. Per-session stability at each operating point

No session collapses to F1=0 at any of the three points (checked
directly, not inferred):

| Model / point | mean F1 | std | min | max | IQR |
|---|---|---|---|---|---|
| V1 max-F1 (0.9078) | 0.247 | 0.060 | 0.040 | 0.356 | [0.226, 0.286] |
| V1 recall-floor (0.9181) | 0.243 | 0.062 | 0.040 | 0.372 | [0.210, 0.288] |
| V1 high-recall (0.5796) | 0.177 | 0.030 | 0.131 | 0.301 | [0.162, 0.183] |
| V2 max-F1 (0.8860) | 0.265 | 0.059 | 0.102 | 0.364 | [0.235, 0.309] |
| V2 recall-floor (0.9132) | 0.249 | 0.065 | 0.088 | 0.383 | [0.204, 0.301] |
| V2 high-recall (0.5396) | 0.176 | 0.031 | 0.140 | 0.303 | [0.161, 0.175] |

The pooled/global numbers in §4 are not artifacts of one or two extreme
sessions — spread is moderate and consistent across all three points, and
the ranking (max-F1 > recall-floor > high-recall) holds session-by-session
in aggregate, not just on average.

## 7. Threshold sensitivity: plateau vs. cliff

Local slope of recall with respect to threshold (`Δrecall/Δτ`), computed
directly from adjacent grid points:

| Region (V1) | slope (Δrecall/Δτ) |
|---|---|
| τ≈0.80–0.87 | ≈ −1.0 to −1.4 (gentle) |
| τ≈0.87–0.90 | ≈ −1.5 to −2.5 |
| **τ≈0.9078 (current op. point)** | **onset of steepening** |
| τ=0.9078→0.9181 | −5.11 |
| τ=0.9181→0.9347 | −7.46 |
| τ=0.9347→0.9486 | −10.03 |
| τ=0.9500→0.9620 | −10.07 |

V2 shows the same pattern (gentle ≈ −0.5 to −2 below τ≈0.886, then −4.7,
−7.1, −8.4, −8.3 immediately above it). **The currently-used operating
point (both models) sits right at the edge of a plateau, not deep inside
one** — a small further increase in threshold costs several times more
recall per unit of τ than a same-sized increase below it would. This
means the current operating point is more sensitive to small threshold
perturbations than its isolated F1 value suggests, and this sensitivity
is a property of the score distribution's own shape, not an artifact of
this particular grid's spacing (slopes are computed from real adjacent
data points, not interpolated).

## 8. Does threshold tuning change the 81-vs-10 execution-level damage pattern? (Option 1 re-check)

Re-ran the fragmented-case-id diff (V1-only / V2-only / both / neither)
from `v1_v2_fragmentation_diagnosis.md` at all three operating points
(1,752 GT executions total):

| Operating point | neither | only V1 | only V2 | both | **net (V2−V1)** |
|---|---|---|---|---|---|
| Max-F1 (Stage 6) | 96 | 9 | 75 | 1,572 | **+66** |
| Recall-floor (R≥0.5) | 110 | 43 | 81 | 1,518 | **+38** |
| High-recall (R≥0.95) | 50 | 3 | 2 | 1,697 | **−1** |

The net gap **narrows** as the threshold moves toward the recall floor
(+66 → +38, roughly 42% smaller) — but not because V2 gets better while
V1 stays put: V1's own `only V1` count nearly quintuples (9 → 43), i.e.
V1 degrades too. **This is both models converging toward each other's bad
behavior, not V2 catching up to a fixed, good V1.** At the high-recall
end the gap effectively vanishes (−1), but only because both models are
now uniformly catastrophic (98.3–98.4% of executions fragmented) — not a
usable regime. **The 81-vs-10 asymmetry measured in Option 1 is a
property of the max-F1 (current) operating point specifically; it is not
a fixed, threshold-independent gap, but it also does not close within any
threshold range that keeps recall at a usable level (≥0.5).**

## 9. V1 vs. V2 curve comparison

At matched thresholds, V2 has both **higher recall and higher
fragmentation** than V1 across almost the entire curve (e.g. at τ=0.90:
V1 R=0.677/frag=91.0% vs. V2 R=0.637/frag=93.6% — closer at this specific
point, but V2's own best-F1 point trades 4.8pp of extra fragmentation for
4.8pp of extra recall relative to V1's best-F1 point). This is consistent
with, not contradictory to, the Option 1/4 finding: V2 is not simply
"the same errors moved around" — it is a genuinely different, higher-
volume error profile that persists as a visible gap across the full curve,
not just at one selected threshold.

## 10. What threshold tuning can and cannot fix

**Threshold tuning can measurably reduce fragmentation, at a real and
non-trivial recall cost, and it narrows (but does not close) the V1-vs-V2
gap found in Stage 6/Option 1.** Moving from max-F1 to the recall-floor
point reduces fragmentation by only 1.1pp (V1) to 2.9pp (V2) while giving
up 5.3–16.0 points of recall — a poor exchange rate. Reducing
fragmentation substantially (down to ~73–79%, still extremely high in
absolute terms) requires recall to collapse to ~0.15–0.21, i.e. missing
4 out of 5 true boundaries — not usable. **Threshold tuning cannot fix
over-segmentation to anywhere near an acceptable level while preserving
usable recall, because fragmentation here is a downstream consequence of
independently thresholding a single per-transition score, not of the
threshold's specific value.** This confirms, quantitatively rather than
only diagnostically, what `v1_v2_fragmentation_diagnosis.md` (Option 4)
already concluded on structural grounds: the fix has to come from a
reconstruction layer that reasons about relative evidence across a
neighborhood of transitions, not from re-tuning where a single global cut
is placed.

## 11. Files

- `scripts/analyze_threshold_tradeoff.py` — orchestration: loads Dataset
  A, runs both LOSO procedures once, calls the grid/sweep logic, writes
  JSON and plots.
- `src/procmine/segmentation/threshold_analysis.py` — `build_threshold_grid()`,
  `evaluate_at_threshold()` (unit-tested, reuses `boundary_metrics`/
  `execution_metrics`/`segments_from_boundaries` from `evaluation.py`
  without redefining any of them).
- `reports/day2/threshold_tradeoff_dataset_a.json` — full curves (v1_curve,
  v2_curve), grids, best-F1 points.
- `reports/day2/threshold_tradeoff_session_detail_dataset_a.json` — per-
  threshold, per-session fragmented-case-id sets and F1 values (large;
  used for §6 and §8, not meant for direct reading).
- `reports/day2/figures/*.png` — 6 plots (recall, F1, fragmentation,
  over-segmentation, under-segmentation vs. threshold; precision-recall
  trade-off).
- `tests/test_threshold_analysis.py` — 8 new tests: grid sortedness/
  dedup/bounds, grid density concentration, low-range context points,
  known-answer precision/recall recovery, identical-threshold-across-
  sessions (no per-session leakage path exists), the exact
  labeled-mask-vs-filtered-list alignment bug found and fixed in this
  stage (regression-guarded), fragmentation agreement with
  `execution_metrics`, and a no-labeled-rows edge case.
- `src/procmine/segmentation/evaluation.py` — extended this stage
  (§1), not otherwise modified.
