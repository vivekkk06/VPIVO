# Day 2 — Final Segmentation Architecture (Dataset A, locked)

This report closes the Day 2 segmentation investigation for Dataset A
and defines the exact pipeline that will later be applied, unchanged, to
Dataset B. It synthesizes every prior Day-2 stage rather than replacing
any of them — all prior reports and artifacts under `reports/day2/`
remain valid and are cited, not superseded.

## 1. Problem statement

The assignment asks for business-process executions to be reconstructed
from raw desktop/browser operation logs — a segmentation problem:
partition each session's event stream into contiguous spans, each
corresponding to one GT execution. Dataset A provides 2,009 GT
executions (1,752 "closed," i.e. with a defined end time — used
consistently across every segmentation stage since Stage 2, for the same
reason: only a closed execution has a defined interval to score against)
across 63 sessions to develop and validate the method; Dataset B (15
sessions, no ground truth) is reserved to test whether the method
generalizes, and was not inspected, loaded, or referenced computationally
at any point in this investigation.

## 2. Why naive app-switch/time-gap segmentation failed

Day 1's ad-hoc signal analysis (persisted in Stage 1 as `signals.py`)
established that no single raw signal — application switch, browser
navigation, extracted text, or a fixed time gap — cleanly separates real
process boundaries from ordinary mid-execution activity. The clearest,
most quantified restatement of this came later, from the execution side
rather than the model side (Stage 8, interruption forensics): a typical
GT execution already contains ~7–8 internal gaps larger than the
dataset-wide 90th-percentile same-execution gap, and ~25 browser-domain
changes. Large gaps and context changes are the *norm* inside real work,
not a rare event — so no naive single-signal rule can use them as a
boundary indicator without producing severe over-segmentation.

## 3. Boundary-first findings (V1)

V1 (`src/procmine/segmentation/{features,model}.py`) frames the task as
"is this transition a boundary?", trained with `class_weight="balanced"`
against the 97.4:1 non-boundary:boundary imbalance. At its Stage 6
threshold (0.9078): F1 0.253, 90.6% of GT executions fragmented.
Stage 2's forensic analysis found the mechanism: false internal
boundaries have a *larger* median gap (2,627ms) than real boundaries
(526ms) — the model is not just imprecise, its confidence is inverted
for exactly the population that matters. No threshold placement fixes an
inverted-confidence population.

## 4. Continuity-first findings (V2)

The continuity-first reframing (Stage 4's `continuity_labels.py`: predict
`S=1` same-execution vs. `S=0` boundary, on the 139,121 transitions with
an unambiguous GT-derived label) was tested as a structurally different
hypothesis, not a retuning of V1. At its own selected threshold (0.8860):
F1 0.240 (measured identically to V1, over the full 162,705-transition
population — see the note in `reconstruction_stage_8_3.md` §4 on why
this differs from the 0.270 figure reported against the labeled-only
subset in Stage 7), 94.7% fragmented — **worse** than V1's own 90.6%.
Stage 8's Option-1 diagnosis (`v1_v2_fragmentation_diagnosis.md`) found
why: V2 doesn't merely redistribute the same errors, it introduces a
genuinely higher volume of erroneous splits (81 executions newly broken
vs. only 10 fixed, relative to V1).

## 5. Why independent thresholding was insufficient

Stage 7's threshold/operating-point analysis swept both V1's and V2's
full threshold ranges on pooled, honest out-of-fold scores. Finding,
stated in that report's own words: raising the threshold reduces
fragmentation only by sacrificing boundary recall, and the trade-off is
**monotonic with no favorable operating point** — every reduction in
fragmentation costs a comparable or larger amount of recall, all the way
to the point of missing 4 in 5 true boundaries. This is the central
structural conclusion driving everything that follows: **the problem is
not which threshold each model uses — it's that both models make an
independent, per-transition decision with no access to the surrounding
context**, and no amount of threshold tuning changes that.

## 6. Reconstruction hypothesis

Stage 8's forensic characterization (`interruption_forensics.md`,
`rule4_error_forensics.md`) produced the direct, quantified motivation
for a neighborhood-aware correction layer: **95.6–95.7% of both models'
false internal boundaries are isolated single-transition spikes**, and
for exactly these transitions, the individual transition's own evidence
(gap size) looks *more* boundary-like than real boundaries do, while a
10-event neighborhood-continuity measure (`event_type_jaccard`) looks
statistically indistinguishable from ordinary same-execution continuity
(median 0.500 vs. 0.500) and clearly unlike real boundaries (0.286). The
individual transition and its neighborhood disagree, and the
neighborhood is the one that agrees with the GT-known answer. This is
the evidence basis for Stage 8.2's architecture decision: reconstruct by
**demoting** existing candidate boundaries using neighborhood evidence —
never inventing new ones (no evidence supports under-segmentation as a
problem; every threshold sweep in Stage 7 found it near zero at
reasonable operating points).

## 7. Stage 8.3 — Design 2 (implemented, unmodified since)

Candidate set **C = V1 ∪ V2** predicted boundaries (union, not
intersection — preserves the best achievable recall of either model,
since reconstruction can only remove). An ordered, deterministic rule
list, applied once per candidate:

1. **Chunk/noise override** — demote if `chunk_boundary` (existing
   feature) or `duplicate_app_switch` (Stage 2's exact detector).
2. **Leave-and-return** — demote both edges of a detected
   leave-and-return pattern (`detect_return_patterns`, window-scoped
   ±10 events around the candidate — GT execution spans cannot be used
   for a live decision, so this differs deliberately from Stage 8's
   GT-scoped forensic search).
3. **Cluster protection** — keep, unconditionally, any candidate in a
   run of ≥2 consecutive candidates (a deliberately conservative default
   — Stage 8 never established clusters are false).
4. **N=10 continuity fallback** — for isolated, non-chunk/noise,
   non-return candidates: demote if `event_type_jaccard` (N=10) ≥ 0.40
   (selected via Stage 7's exact pooled-OOF grid method), else keep.

Result: **F1 0.304, 77.6% fragmented (down from V1's 90.6%/V2's 94.7%),
recall 0.520 (above Stage 7's justified 0.5 floor)** — but
**under-segmentation rose from 0.063–0.085 to 0.204, universally across
all 63 sessions** — the pre-registered success gate failed on this one
condition. Reported as a genuine partial result, not spun as a clean
win: fragmentation genuinely improved, but the cost (merging distinct
executions) was real and dataset-wide.

## 8. Stage 8.4 — Rule-4 error forensics

Investigated *why* Rule 4 wrongly demotes 296 real boundaries (vs.
3,667 correctly-demoted false internals). Of ~24 signals tested with
AUC (Stage 5's convention) plus a session-level directional-robustness
check (added specifically to catch pooled-only artifacts): raw model
confidence separated nothing (AUC 0.48–0.52); `delta_t_ms` had a modest
pooled AUC (0.593) that **collapsed under the robustness check** (41.3%
session agreement — worse than chance, rejected as a cross-session scale
artifact). Two signals passed every criterion: **cross-model agreement**
(90.9% of wrongly-demoted real boundaries vs. 66.3% of correctly-demoted
false ones flagged by both V1 and V2; AUC 0.623, 88.9% session-robust)
and **post-transition tempo** (`after_window_duration_ms`; AUC 0.712,
88.9% session-robust — mechanistically explained by composition: correct
removals' aftermath is steady work — keystrokes/shortcuts dominate 78–81%
of after-windows — while wrong removals' aftermath is navigation/
orientation activity — `app_switch` in 96.3%, `browser_navigation`/
`browser_click` in ~70%).

## 9. Stage 8.5 — protection experiment

Tested whether these two signals could protect some of the 296 without
giving back too much of the 3,667. Three strategies, evaluated against a
pre-registered 7-condition success gate:

| | Recall | F1 | % fragmented | Under-seg | Gate |
|---|---|---|---|---|---|
| Design 2 (baseline) | 0.520 | 0.304 | 77.6% | 0.204 | (reference) |
| Agreement | 0.681 | 0.252 | 93.0% | 0.075 | **FAIL** (3/7) |
| Tempo | 0.643 | 0.339 | 79.9% | 0.133 | PASS (7/7) |
| Combined | 0.636 | 0.344 | 79.1% | 0.141 | PASS (7/7) |

Agreement was rejected: it protects 3,302 candidates (only 269 correctly
— an 11.28:1 false:true ratio) because 90.9% of the very population it
should selectively protect already satisfies it, so it cannot be
selective. Tempo (false:true ratio 1.99:1) and Combined (1.34:1) both
passed all seven conditions, improving under-segmentation by 31–35% in
every one of 63 sessions while retaining most of Design 2's fragmentation
gain.

## 10. Tempo vs. Combined — final controlled comparison

Neither strategy was adopted in Stage 8.5 pending exactly this
comparison. Both were re-evaluated with an extended metric set on the
identical pipeline (`scripts/compare_tempo_vs_combined.py`):

| | Tempo | Combined |
|---|---|---|
| Precision | 0.2304 | 0.2358 |
| Recall | 0.6433 | 0.6355 |
| F1 | 0.3393 | 0.3440 |
| % fragmented | 79.85% | 79.05% |
| Under-segmentation | 0.1332 | 0.1412 |
| Over-seg (extra fragments/execution) | 1.6712 | 1.6033 |
| True boundaries kept / demoted | 1,075 / 596 | 1,062 / 609 |
| False boundaries still present (FP) | 3,591 | 3,441 |

**Session-level** (63 sessions): on `% fragmented`, Combined is
**strictly better or equal in every session — 0 sessions where Tempo
fragments less than Combined** (9 Combined-better, 54 equal). On
under-segmentation, Tempo is better in 52/63 sessions (0 worse, 11
equal). On recall, Tempo is better in 12/63, equal in the remaining 51.

**GT-execution-level** (1,752 executions): 1,385 fragmented under both,
353 fine under both, **14 fragmented only under Tempo, 0 fragmented only
under Combined**. There is not one GT execution where Combined performs
worse than Tempo on fragmentation — a one-directional dominance, not
noise.

**Neither gain is concentrated**: the session and execution counts above
already show broad, dataset-wide effects, not a handful of sessions
driving the numbers.

## 11. Sensitivity analysis (not re-tuning)

Evaluated the 9 grid points nearest the selected τ=4,680.3ms on the same
52-point grid Stage 8.5 already built (no new threshold search
performed): τ ∈ {4031.0, 4093.3, 4172.0, 4287.8, **4680.3**, 4964.1,
5257.0, 5466.2, 5652.1}.

**Combined's F1 ≥ Tempo's F1 at all 9 neighboring points (9/9)** — the
ordering found at the selected threshold is not an artifact of that one
value. Both curves move smoothly (recall 0.597→0.648 for Tempo,
0.590→0.640 for Combined across this range; fragmentation 79.8→80.1% /
79.1→79.2%) — no cliff, no sign of a fragile decision boundary. **The
conclusion does not depend on one extremely fragile threshold value.**

## 12. Final architecture decision

| Criterion | Tempo | Combined | Weight given |
|---|---|---|---|
| Fragmentation | 79.85% | **79.05%, never worse in any session** | High — the primary objective since Stage 6 |
| Recall | **0.6433** | 0.6355 | Medium — both clear the 0.5 floor comfortably |
| F1 | 0.3393 | **0.3440, holds across all 9 sensitivity points** | Medium |
| Under-segmentation | **0.1332, better in 52/63 sessions** | 0.1412 | High — the specific failure Stage 8.3 needed fixed |
| Session robustness | broad, 63/63 | broad, 63/63 | Equal |
| False:true protection ratio | 1.99:1 | **1.34:1** | Medium-high — a purer signal of correct protection |
| Threshold sensitivity | stable | stable, and F1-dominant across the neighborhood | Equal |
| Interpretability | single condition | conjunction of two conditions — still a one-line rule | Slight edge to Tempo |
| Implementation complexity | lower | marginally higher (two evidence inputs) | Slight edge to Tempo |
| Risk of reintroducing V1/V2 behavior | low | **lower** (never worse on fragmentation than Tempo in any session) | High |

**Decision: Combined is selected as the locked Rule-4 protection
strategy.** This is not a "pick the highest F1" default — F1 is close
(0.344 vs. 0.339) and was checked for robustness rather than trusted at
face value. The deciding evidence is the **one-directional dominance on
fragmentation** (§10: Combined is never worse in any of 63 sessions or
1,752 executions) combined with the **better false:true protection
ratio** (1.34:1 vs. 1.99:1 — fewer false boundaries reinstated per real
boundary recovered) and the **stable F1 advantage across the full
sensitivity neighborhood** (§11). Tempo's real advantages — better
under-segmentation in the majority of sessions, marginally higher recall
— are acknowledged, not dismissed: Combined does not fully dominate
Tempo, and if a future engineering priority weighs under-segmentation
reduction above all else, Tempo remains the documented, evidence-backed
alternative, not a rejected option. This is a close, evidence-based
call, not a case of forcing a decision where none was warranted — the
evidence does lean one direction, consistently, across every check
performed.

## 13. Exact final algorithm

```
Input: one session's chronologically-ordered raw event stream (Dataset A or B)

1. Canonicalize:           to_canonical_stream(events)                    [canonical.py, unchanged]
2. Transition features:    extract_transition_features(canonical)          [features.py, unchanged]
3. V1 inference:           held-out-equivalent LogisticRegression pipeline,
                           feature_vector(f), threshold >= 0.9078          [model.py, unchanged]
4. V2 inference:           continuity_feature_vector(canonical, i, f),
                           boundary_score = 1 - P(S=1), threshold >= 0.8860 [continuity_model.py, unchanged]
5. Candidate union:        C[i] = V1_predicted[i] OR V2_predicted[i]        [reconstruction.union_candidates]
6. Reconstruction evidence (raw-event/held-out-prediction only):
     - chunk_boundary[i]                          [features.py, unchanged]
     - duplicate_app_switch[i]                    [signals.deduplicate_consecutive + app_switch_payload_key]
     - cluster_size[i]                            [reconstruction.cluster_size_per_transition, over C]
     - return_pattern evidence, +/-10 event window [reconstruction.return_pattern_evidence_for_transition]
     - event_type_jaccard[i], N=10                [context_features.extract_trajectory_features]
     - flagged_by_both[i] = V1_predicted[i] AND V2_predicted[i]
     - after_window_duration_ms[i], N=10          [context_features.extract_trajectory_features]
7. Design 2 rules (ordered, first match wins), for every i where C[i]:
     Rule 1: chunk_boundary[i] or duplicate_app_switch[i]        -> DEMOTE
     Rule 2: i is a leave-or-return edge of a detected pattern   -> DEMOTE (both edges)
     Rule 3: cluster_size[i] >= 2                                -> KEEP
     Rule 4: event_type_jaccard[i] >= 0.40                       -> DEMOTE, else KEEP
8. Protection (Strategy Combined) -- applies ONLY to transitions Rule 4 demoted:
     if flagged_by_both[i] AND after_window_duration_ms[i] >= 4680.2613:
         override to KEEP
9. Final boundary sequence:  the surviving KEEP decisions (candidates never in C stay non-boundary)
10. Segments:                segments_from_boundaries(session_id, timestamps, final_boundary)  [evaluation.py, unchanged]
```

Every threshold (`0.9078`, `0.8860`, `0.40`, `4680.2613`) is a Stage 6/7/8.5
pooled, global, out-of-fold analytical selection over Dataset A — none
is nested/cross-fitted, none is per-session, and this is stated plainly
rather than overclaimed as a stronger validation than was actually
performed.

## 14. Leakage audit (final, consolidated)

**Training-time information** (Dataset A only, used to fit V1/V2 and to
select every threshold above): GT boundary labels (`is_boundary`), GT
continuity labels (`S`), GT execution spans (only for label
construction, per Stage 4's documented policy) — never as a feature.

**Reconstruction-time information** (must be available identically on
Dataset B): raw event fields, V1/V2's own held-out predictions/scores,
`chunk_boundary`, duplicate-`app_switch` membership, cluster size (over
the candidate set), return-pattern evidence, N=10 trajectory jaccard,
N=10 window duration, cross-model agreement. **No GT field of any kind**
— structurally verified (not just claimed) by `tests/test_architecture_lock.py`'s
signature-inspection tests, which fail if any of
`apply_design2_rules`/`apply_design1_rule`/`apply_protection`/
`union_candidates`/`cluster_size_per_transition` ever gains a
GT-derived parameter.

**GT-only evaluation information**: `is_boundary` labels and GT
execution spans, used only inside `boundary_metrics`/`execution_metrics`
after every reconstruction decision is already fixed — confirmed by
inspection in Step 1 of this stage and unchanged from every prior stage.

## 15. Dataset-B application contract

**Input**: Dataset B's raw event stream per session (15 sessions,
20,477 events, no ground truth) — read through the exact same
`discover_dataset` / `load_session_events` loaders already used for
Dataset A, untouched by this investigation.

**Output**: `segments.jsonl`, one record per reconstructed segment, using
only fields already meaningful in this project's existing schema
(`session_id`, `start_ms`, `end_ms`, plus whatever timestamp/event-id
provenance `PredictedSegment` already carries) — no new fields invented
for this contract.

**Session/chunk handling**: sessions are processed independently (no
cross-session evidence, matching every LOSO run's own boundary); chunk
crossings are handled exactly as `chunk_boundary` already defines them
(Stage 4's finding: chunk boundaries are temporally distinct from process
boundaries and essentially never coincide with one — Rule 1 continues to
demote them regardless of any other evidence).

**Noise handling**: unlabeled/idle time is not specially reconstructed —
Design 2 has never attempted to assign meaning to time outside a
detected segment; it only decides whether a *candidate* boundary
(already flagged by V1 or V2) should survive.

**Candidate generation on Dataset B**: identical to Dataset A —
V1 and V2 run inference (not retrained; the exact fitted pipelines/
feature functions apply directly, since neither model's feature set
references anything Dataset-A-specific) at their existing thresholds
(0.9078 / 0.8860), and the union becomes the candidate set.

**Reconstruction on Dataset B**: the exact ordered rule list in §13,
with the exact same four numeric thresholds (0.40, 4680.2613) — **no
threshold is re-selected on Dataset B**, since Dataset B has no GT to
select one from, and re-selecting per-dataset would violate the
already-established discipline of global, evidence-based, non-nested
threshold selection.

**Emission**: `segments_from_boundaries` applied to the final boundary
sequence, unchanged.

**This stage does not execute any of the above on Dataset B** — it is
documented as a precise contract for a future, explicitly authorized
step.

## 16. Known limitations (stated plainly)

- Under-segmentation, even after protection, remains roughly double
  V1's own rate (0.141 vs. 0.085) — a real, unresolved cost, not
  something this stage claims to have fully solved.
- Rule 2's return-pattern search (±10 events) will miss leave-and-return
  patterns whose away-period exceeds that window (Stage 8's own
  away-duration data reaches 49–62s at p90, plausibly exceeding 10
  events in busy stretches).
- Rule 1 covers only the one instrumentation-noise pattern with an
  existing, reliable, reusable detector (duplicate `app_switch`);
  browser-error storms (Stage 2's worst-case example) are not covered.
- All four thresholds are global analytical selections from pooled
  Dataset-A evidence, not from a held-out validation split distinct from
  the data used to characterize the signals — this is consistent with
  (not weaker than) how V1/V2's own thresholds were originally selected,
  but is not a claim of a stronger, independent validation protocol.
- Generalization to Dataset B is unverified by construction (Dataset B
  has no GT to check against) — the contract in §15 is the honest limit
  of what can be claimed before Dataset B is actually processed and,
  eventually, spot-checked qualitatively.

## 17. What remains for Day 3

- Execute the §15 contract against Dataset B and produce `segments.jsonl`
  (first authorized use of Dataset B in this investigation).
- Qualitative/spot-check review of Dataset B's reconstructed segments
  (no GT exists for a quantitative check).
- Step 2/3 of the original assignment: automation-opportunity analysis
  and prototype, once segmentation output exists for both datasets.
- Optional, lower-priority, explicitly-gated follow-ups only if directed:
  Option 3 (feature revisit, Stage 6's deferred item), a deeper
  investigation of the remaining under-segmentation cost, or Design 3 —
  none authorized in this stage.

## AI contribution

AI was used to accelerate implementation, experiment execution, analysis,
and test generation across every stage referenced in this report;
architectural direction, methodology approval, and acceptance criteria
were set and reviewed by the engineer at each stage, including the final
Tempo-vs-Combined decision in §12.

## Files

- This report consolidates, without replacing, every prior Day-2 report:
  `signal_evaluation.md`, `time_gap_analysis.md`, `segmentation_baseline.md`,
  `learned_boundary_model.md`, `false_boundary_forensics.md`,
  `noise_gap_labeling_analysis.md`, `continuity_feature_design.md`,
  `continuity_model_evaluation.md`, `v1_v2_fragmentation_diagnosis.md`,
  `threshold_tradeoff.md`, `interruption_forensics.md`,
  `reconstruction_stage_8_3.md`, `rule4_error_forensics.md`,
  `protected_boundary_experiment.md`.
- New this stage: `scripts/compare_tempo_vs_combined.py`,
  `tests/test_architecture_lock.py` (12 tests),
  `reports/day2/tempo_vs_combined_comparison_dataset_a.json`,
  `reports/day2/final_architecture_dataset_a.json`,
  `reports/day2/segmentation_architecture_final.md` — this file.
