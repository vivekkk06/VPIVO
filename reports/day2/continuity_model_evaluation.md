# Stage 6 — Continuity Model Training & Comparison Against V1

**MEASUREMENT.** Logistic regression on Stage 5's recommended 8-feature
set, `class_weight="balanced"`, leave-one-session-out cross-validation
(63 model fits, manual loop so each fold's own model could also be
applied to that session's excluded transitions for full-session
reconstruction). Boundary-quality metrics computed only on the 139,121
labeled transitions; execution-level reconstruction runs on the full
162,705-transition stream, matching how V1 was evaluated. Source:
`scripts/train_continuity_model.py`, `src/procmine/segmentation/continuity_model.py`.
114 tests passing project-wide (111 + 3 for this module... see Tests
section for the exact count).

## Headline comparison

| Metric | V1 (boundary-first) | V2 (continuity-first) | Change |
|---|---|---|---|
| Boundary F1 | 0.254 | **0.270** | +0.016 (better) |
| Precision | 0.157 | 0.167 | better |
| Recall | 0.655 | **0.703** | better |
| Under-segmentation rate | 0.085 | **0.063** | better |
| **Over-segmentation rate** | 2.711 | **3.239** | **worse** |
| **% GT executions fragmented** | **90.8%** | **94.7%** | **worse** |
| Per-session F1 mean | 0.247 | 0.265 | better |
| Per-session F1 worst | 0.040 | **0.102** | better |

## This is not a clean win — reported per instruction not to declare success on one metric

**The continuity-first model is worse on the exact metric Stage 2 used to
motivate this entire pivot**: 94.7% of GT executions fragmented, versus
90.8% for the boundary-first model, and over-segmentation rate rose from
2.711 to 3.239 extra fragments per execution. At the same time, it
genuinely improves boundary F1, recall, under-segmentation, and — notably
— the single worst-performing session (F1 0.102 vs. 0.040, more than
double). **Per the explicit instruction, this is not declared a success.**

## Why this plausibly happened (INFERENCE, not yet directly verified)

Recall rose substantially (0.655 → 0.703) while total predicted positives
rose only slightly (6,966 → 7,044, about +1%) — the model isn't simply
predicting "boundary" much more often overall. **Hypothesis, untested**:
the continuity model's false positives may be more evenly distributed
across *more different* executions (each getting slightly fewer extra
splits on average, but a larger share of executions affected at all),
while V1's false positives may have concentrated more within already-bad
executions. This would explain higher over-segmentation *count* alongside
a similar total FP volume, but has not been directly checked by comparing
the two models' false-positive distributions execution-by-execution —
flagged as the concrete next diagnostic, not asserted as the explanation.

## Feature importance (standardized coefficients, predicting S=1/continuity)

| Feature | Coefficient | Direction (real-world meaning) |
|---|---|---|
| `log1p_delta_t_ms` | −3.597 | larger gap → less likely continuity (i.e. more boundary-like) — dominant, consistent with Stage 5's univariate finding and V1's own coefficient (opposite sign because the target class is flipped, same real-world relationship) |
| `density_after` | −1.282 | denser activity right after → *less* likely continuity — a genuine, non-obvious result worth noting as-is |
| `density_before` | +0.940 | denser activity right before → more likely continuity |
| `browser_domain_changed` | −0.836 | consistent direction and comparable magnitude to V1's own +0.898 (flipped sign, same meaning) |
| `interaction_category_changed` | −0.474 | consistent with V1's finding this feature matters |
| `N10_event_type_jaccard` | +0.464 | higher before/after similarity → more likely continuity — **validates the trajectory hypothesis's direction**, multivariately not just univariately |
| `N10_interaction_category_jaccard` | −0.178 | **sign-flipped from its univariate AUC (0.605, i.e. positive direction)** — likely redundant with `N10_event_type_jaccard` once both are in the model, the same kind of multivariate effect V1's Stage 6 found for `extracted_text_at_transition`, not a real reversal of the underlying relationship |
| `N10_after_window_duration_ms` | **+0.033** | **essentially negligible**, despite being one of Stage 5's strongest univariate signals (AUC 0.686) — almost certainly redundant with `log1p_delta_t_ms`/`density_after` (all three describe related aspects of "how much happened, how fast, around this transition") |

**Two features confirm the established pattern from V1's own Stage 6**:
a feature can look strong alone and contribute little once correlated
features are already in the model (`N10_after_window_duration_ms` here,
`application_changed` there). This is genuine evidence, not a modeling
mistake — flagged rather than hidden.

## What actually improved, and why it matters even given the fragmentation result

- **Worst-case session more than doubled** (0.040 → 0.102) — the
  continuity framing appears to help most exactly where V1 struggled
  most, even though it doesn't help the aggregate fragmentation number.
- **Under-segmentation improved** (0.085 → 0.063) — fewer real executions
  incorrectly merged together.
- **Recall improved substantially** (0.655 → 0.703) — more real
  boundaries are found.

None of this offsets the fragmentation regression on its own — they're
reported as real, separate findings, not as a counterargument to the
headline result.

## Options, not a decision

1. **Investigate the false-positive distribution difference** directly
   (the hypothesis above) before choosing a direction — cheapest next
   step, purely diagnostic, no new modeling.
2. **Re-select the operating threshold** away from the F1-optimal point
   specifically to minimize over-segmentation, accepting a recall cost —
   untested; Stage 7 (calibration/trade-off analysis) was always the
   planned place for this, not skipped, just not reached yet.
3. **Revisit the feature set** — given two of Stage 5's promising
   features turned out redundant multivariately, there may be room to
   swap them for something that specifically targets over-segmentation
   rather than aggregate boundary F1.
4. **Reconsider whether continuity-first, without Stage 8's
   interruption-aware reconstruction layer, was ever going to fix
   fragmentation on its own** — the original hypothesis was that
   continuity-first *plus* proper reconstruction would address this;
   this stage only tested the classification half.

## Tests

3 new (`tests/test_continuity_model.py`): feature-vector shape/content,
and confirming `feature_importance` uses the continuity feature names,
not V1's. 111/111 passing before this addition; full count below.

## Files

- `src/procmine/segmentation/continuity_model.py`
- `tests/test_continuity_model.py`
- `scripts/train_continuity_model.py`
- `reports/day2/continuity_model_dataset_a.json`
- `reports/day2/continuity_model_evaluation.md` — this file
