# Stage 5 — Continuity Representation: Local Context + Trajectory

**No model trained. No feature set finalized. No Dataset B use.**
Everything below is univariate measurement against the Stage 4 approved
labels (S=1 SAME_EXECUTION, S=0 EXIT_TO_DIFFERENT_EXEC ∪
EXIT_TO_NOISE_BOUNDARY), pooled across 63 sessions, 139,121 labeled
transitions, plus per-session stability checks. AUC convention used
throughout: **AUC > 0.5 means higher feature values predict S=1 (same
execution); AUC < 0.5 means higher values predict S=0 (boundary)** — both
directions are informative; only closeness to 0.5 means "uninformative."

## QUESTION

Can local context and before/after trajectory evidence distinguish
same-execution continuity from genuine execution boundaries better than
adjacent-transition features alone?

## HYPOTHESIS

A single long pause should not automatically imply a boundary if the
activity before and after the pause forms a consistent trajectory.

## Feature families created

- **F0 (existing V1)**: the 9 transition-level features already built
  (`log1p_delta_t_ms`, `density_before/after`, 4 "changed" booleans,
  `extracted_text_at_transition`, `chunk_boundary`) — unmodified, reused
  as the baseline comparison point.
- **T2 (new)**: `delta_t_over_session_median` — gap normalized by that
  session's own median gap across all transitions, testing whether a
  session-relative temporal representation beats the plain log transform.
- **N3/N5/N10 trajectory features (new)**: for each window size, Jaccard
  similarity of applications, event types, interaction categories,
  browser domains (both port-inclusive and host-only), and window-title
  tokens between the N-event window before and after the transition —
  plus the wall-clock **duration** each window spans (a new signal family
  not previously measured).
- **V2 (new)**: `browser_domain_changed_host_only` — the controlled
  comparison against the existing port-inclusive `browser_domain_changed`.

`src/procmine/segmentation/context_features.py` (12 new tests),
`scripts/measure_continuity_features.py`.

## Context-window experiment results

| Window size | Best trajectory feature | AUC |
|---|---|---|
| N=3 | interaction_category_jaccard | 0.369 (weak) |
| N=5 | interaction_category_jaccard | 0.533 (weak) |
| **N=10** | **event_type_jaccard** | **0.697 (moderate)** |

**Small windows (N=3, N=5) show weak discrimination across almost every
trajectory feature** — most cluster between 0.36 and 0.53, close to
uninformative. **N=10 is qualitatively different**: `event_type_jaccard`
(0.697), `interaction_category_jaccard` (0.605), and both
`before/after_window_duration_ms` (0.317 / 0.686) show real, moderate
discrimination. **The trajectory hypothesis is not rejected outright, but
it requires a wider context window than the 3–5 events initially
proposed** — a genuinely useful, evidence-backed refinement, not the
original guess.

## Trajectory results — application/domain/title similarity mostly weak

`application_jaccard` peaks at only 0.480 (N=3) and gets *weaker*, not
stronger, at larger windows (0.466 at N=5, 0.436 at N=10) — the opposite
trend from event-type/interaction-category. `window_title_jaccard` stays
weak at all sizes (0.39–0.46). **Not every trajectory signal benefits
from a wider window — this has to be checked per feature, not assumed
uniform**, which is exactly why each was measured separately rather than
combined into one "trajectory similarity" score up front.

## A new finding not anticipated in the original feature list: window duration

`N10_after_window_duration_ms` (0.686) and `N5_after_window_duration_ms`
(0.661) are among the strongest non-temporal features found. **INFERENCE**:
the wall-clock time the *following* N events span — not just whether a
gap occurred — carries real information; a same-execution continuation
appears to proceed at a different local pace than the start of a new
execution. This wasn't in the original candidate list; it emerged from
measuring "local activity context" broadly rather than only the
similarity comparisons initially proposed. Not yet explained causally —
flagged as a strong candidate for Stage 6, not a settled mechanism.

## Temporal representation results (T1 vs. T2)

| | AUC | Distance from 0.5 |
|---|---|---|
| T1: `log1p(delta_t)` (existing) | 0.1098 | 0.390 |
| T2: `delta_t / session_median_gap` (new) | 0.1097 | 0.390 |

**Virtually identical** — session-relative normalization provides no
measurable univariate improvement over the plain log transform. This is
itself a real result, not a null outcome to hide: the specific T2
representation tested here doesn't help; a different normalization might,
but this one doesn't, so it's not carried forward as-is.

**Important interpretive note, to avoid a false contradiction with Stage
2**: temporal gap is, by a wide margin, **the single strongest univariate
feature measured** (0.39 from uninformative — over 2x the next strongest
family). This does not contradict Stage 2's finding that false internal
boundaries have *larger* gaps than true boundaries — that finding was
about a specific hard subset (long pauses inside real executions);
pooled across the *whole* dataset, most same-execution transitions have
very short gaps (median 52ms, Day 1/Stage 4), so temporal gap remains
highly informative on average even though it specifically fails on the
harder, evidence-documented minority pattern. **Per-session stability
confirms this is a real, robust signal, not a pooled artifact**: mean AUC
0.110, std 0.019 across all 63 sessions, min 0.057, max 0.155 — never
close to uninformative in any single session.

## Browser domain hostname-vs-port experiment — hypothesis REJECTED

| Representation | Simple "changed" AUC | N=3 Jaccard AUC | N=5 Jaccard AUC | N=10 Jaccard AUC |
|---|---|---|---|---|
| With port (existing) | 0.2154 | 0.4607 | 0.4270 | **0.3626** |
| Host-only (V2) | 0.2174 | 0.4790 | 0.4596 | **0.4248** |

For the simple transition-level "changed" flag, the two are essentially
identical (0.2154 vs. 0.2174 — a 0.002 difference, not meaningful). **For
the windowed Jaccard comparison, host-only is consistently *weaker*
(closer to 0.5) than the port-inclusive version at every window size** —
the opposite of what Stage 2's hypothesis predicted. **Per the instructed
protocol: measured, not improved, therefore rejected.** Recommendation:
**keep the existing port-inclusive `browser_domain` representation
unchanged.** Stage 2's concern was a reasonable thing to test given the
evidence available at the time (multiple localhost ports observed), but
the controlled comparison doesn't support the fix.

## Duplicate/chunk effect — confirmed not central (unchanged conclusion)

`V1_chunk_boundary` AUC = **0.4999** — indistinguishable from
uninformative. Consistent with every prior stage's finding; not made a
central feature, per instruction.

## Leakage analysis

- `test_trajectory_features_expose_no_gt_metadata` (new) asserts
  `process_code`/`case_id`/`process_variant`/`is_boundary`/
  `continuity_label` are absent from every `TrajectoryFeatures.to_dict()`
  key.
- `test_no_gt_metadata_in_model_feature_names` (Stage 4, still passing)
  covers the existing V1 feature names the same way.
- All "after" context features are explicitly documented (module
  docstring) as **offline-only evidence** — valid for this assignment's
  actual task (reconstructing completed logs), invalid for a hypothetical
  real-time segmenter, which is stated plainly rather than silently
  assumed.
- `executions` (GT) is passed into `label_continuity` only to determine
  span membership for labeling — never into any feature-producing
  function. Feature extraction (`extract_transition_features`,
  `extract_trajectory_features`) takes only `CanonicalEvent` sequences.

## Session-aware analysis

All measurements pooled across sessions, but the top 6 features were also
checked per-session (63 sessions each) — reported above for the temporal
features; the full table is in
`continuity_feature_measurement_dataset_a.json`. No random splitting of
neighboring transitions was used anywhere; Dataset B was not inspected or
used at any point in this stage.

## Complexity trade-off assessment

Everything measured here is a named, interpretable statistic (a gap, a
set-overlap ratio, a duration) — no embeddings, no opaque transforms, no
deep learning. The window-size experiment itself is evidence *against*
defaulting to more complexity: N=3 and N=5 mostly underperform N=10 for
the features that work at all, and `application_jaccard` actively gets
*worse* at N=10 — bigger is not uniformly better, and this project's own
measurement is what shows that, not an assumption either way.

## Recommendation (for Stage 6 to test, not a final selection)

Carry forward as candidates: `log1p_delta_t_ms` (dominant, keep), the
existing `density_before`/`density_after`, `interaction_category_changed`,
`browser_domain_changed` (port-inclusive, unchanged), plus the new
`N10_event_type_jaccard`, `N10_interaction_category_jaccard`,
`N10_after_window_duration_ms`, and `N5_after_window_duration_ms`. Drop
from further consideration (weak/uninformative alone):
`application_changed`, `window_title_changed`, `chunk_boundary` (kept
only as a diagnostic, per the standing decision not to discard it),
`application_jaccard` at any window size, `window_title_jaccard`, and the
host-only browser-domain variant. **This is a recommendation for what
Stage 6's model comparison should test, not a claim about what the
trained model will actually use** — Stage 6 of the boundary-first track
already showed univariate strength and multivariate contribution can
diverge (e.g. `application_changed` there had near-zero coefficient
despite non-trivial univariate signal elsewhere).

## Tests

12 new (`tests/test_context_features.py`) covering window boundaries,
stream-start/end truncation, short streams, missing browser/window/text
context, duplicate-event set semantics, and the no-leakage guarantee.
108/108 passing project-wide.

## Files

- `src/procmine/segmentation/context_features.py`
- `tests/test_context_features.py`
- `scripts/measure_continuity_features.py`
- `reports/day2/continuity_feature_measurement_dataset_a.json`
- `reports/day2/continuity_feature_design.md` — this file
