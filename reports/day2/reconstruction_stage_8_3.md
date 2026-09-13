# Stage 8.3 — First Deterministic Reconstruction Experiment (Design 2)

**Implementation of the approved Stage 8.2 architecture, on Dataset A
only.** V1 and V2 are not retrained or retuned (same Stage 6 thresholds,
0.9078 / 0.8860, same LOSO procedure). Reconstruction only ever demotes
a candidate boundary (V1 ∪ V2); it never invents one. Source:
`src/procmine/segmentation/reconstruction.py` (rule engine, unit-tested),
`scripts/run_reconstruction_experiment.py` (orchestration).

**Headline result: the success gate does not pass.** Fragmentation drops
substantially (90.6%/94.7% → 77.6%) and recall stays above the 0.5 floor
(0.520), but under-segmentation increases in **every one of 63
sessions** and roughly **triples in aggregate** (0.063–0.085 → 0.204).
Per the pre-registered gate, this is reported as a failure, not spun as
a partial success.

## 1. Implementation

`reconstruction.py` implements exactly the four ordered rules approved
in Stage 8.2:

- `union_candidates` — C = V1 ∪ V2 predicted boundaries.
- Rule 1 (chunk/noise): reuses `TransitionFeatures.chunk_boundary`
  unchanged, plus `involves_duplicate_app_switch` — Stage 2's *exact*
  duplicate-`app_switch` definition (`deduplicate_consecutive` +
  `app_switch_payload_key`, reused verbatim). **No other noise pattern
  has an existing, reliable, reusable per-transition flag** — Stage 2's
  worst-case example (a browser-error storm) has no such detector, so it
  is *not* covered by Rule 1 here. Documented, not invented.
- Rule 2 (leave-and-return): `return_pattern_evidence_for_transition`
  reuses Stage 8's `detect_return_patterns` unchanged, but **cannot** use
  Stage 8's GT-execution-span scoping (not permitted for a live
  decision). Instead it searches a **±10-event window centered on the
  candidate transition — the same N=10 window Stage 5 already validated**,
  reused rather than inventing a second window-size concept.
  `compute_rule2_demotions` unions both the leave and return edges of
  any detected pattern into one demotion set, so a pair is corrected
  together rather than depending on each side independently
  rediscovering it.
- Rule 3 (cluster protection): `cluster_size_per_transition` — any
  candidate in a run of ≥2 consecutive candidates is **kept**,
  unconditionally, per Stage 8.2's explicit conservative default.
- Rule 4 (continuity fallback): `event_type_jaccard` at N=10
  (`context_features.extract_trajectory_features`, reused, unchanged) —
  chosen as *the* single continuity feature (not a blend) because Stage
  5 ranked it the strongest N=10 trajectory feature (AUC 0.697) and
  Stage 8 found it the cleanest separator (false-internal median 0.500
  vs. true-boundary median 0.286). Using a second feature here would
  have started sliding toward Design 3 (a weighted composite), which
  this stage explicitly defers.

**Design 1 (ablation)**: same candidate set and the same Rule-1 chunk/noise
override (retained so the Design 1 vs. Design 2 comparison isolates
exactly the value of Rules 2+3, not also the value of Rule 1); continuity
threshold applied uniformly to *every* non-chunk/non-noise candidate,
with no return-pattern or cluster distinction at all.

## 2. Threshold selection (Rule 4)

Following Stage 7's exact discipline: pooled out-of-fold evidence across
all 63 sessions, one global threshold, never per-session. The **eligible
population** is deliberately narrow — only candidates that are isolated
(cluster size 1), not chunk/noise, and not part of a detected return
pattern (8,487 of 9,021 total candidates) — since those are the only
transitions Rule 4 actually decides.

`threshold_analysis.build_threshold_grid` (Stage 7, reused unchanged)
was applied directly to the pooled `event_type_jaccard` values of this
population — a legitimate reuse, since the function is orientation- and
domain-agnostic (it only concentrates grid density where the score
distribution has density). Full sweep:

| τ | Precision | Recall | F1 | % fragmented | under-seg |
|---|---|---|---|---|---|
| 0.10 | 0.040 | 0.009 | 0.015 | 4.6% | 8.679 |
| 0.20 | 0.059 | 0.073 | 0.065 | 66.0% | 0.792 |
| 0.30 | 0.238 | 0.483 | 0.319 | 73.9% | 0.266 |
| **0.40** | **0.215** | **0.520** | **0.304** | **77.6%** | **0.204** |
| 0.50 | 0.195 | 0.563 | 0.289 | 84.0% | 0.156 |
| 0.60 | 0.187 | 0.675 | 0.293 | 86.9% | 0.096 |
| 0.70 | 0.154 | 0.691 | 0.252 | 93.2% | 0.072 |
| 1.00 | 0.139 | 0.696 | 0.232 | 94.9% | 0.063 |

**Selected τ = 0.40** (max F1 subject to recall ≥ 0.5, Stage 7's justified
floor — no other candidate with recall ≥ 0.5 beats its F1). **This sweep
is itself the central finding of this stage, not just a calibration
step: there is no point on this curve where fragmentation improves
substantially without under-segmentation rising by a comparable or
larger factor.** At τ=1.0 (Rule 4 essentially inert) the numbers match
V2's own baseline almost exactly (recall 0.696 vs. V2's 0.703, frag 94.9%
vs. 94.7%, under-seg 0.063 vs. 0.063) — a useful internal consistency
check. Every step toward lower fragmentation costs under-segmentation
monotonically and, at the aggressive end, catastrophically (8.68 at
τ=0.10). Threshold selection was performed entirely on pooled, global,
Dataset-A evidence — no per-session tuning, matching Stage 7's protocol
exactly.

## 3. Leakage audit

Rule-engine inputs, verified by construction: held-out V1/V2 predictions,
`chunk_boundary` (raw-event-derived), duplicate-`app_switch` membership
(raw-event-derived), cluster size (derived only from the candidate array
itself), return-pattern evidence (raw `application`/`browser_domain`
fields only, no execution-span scoping), `event_type_jaccard` (raw
event-type sequence only). **None reference GT `case_id`, `process_code`,
`process_variant`, GT execution spans, GT boundary labels, or continuity
labels.** GT is used in exactly two places: (a) selecting τ from pooled,
global evidence — the same kind of GT use Stage 6 already made to select
V1/V2's own thresholds, not a new leakage category — and (b) scoring the
final, already-fixed decisions afterward. No per-session GT-based tuning
occurred anywhere.

## 4. V1 vs. V2 vs. Design 2 vs. Design 1

| | V1 | V2 | Design 2 | Design 1 (ablation) |
|---|---|---|---|---|
| Precision | 0.157 | 0.167 | 0.215 | ~0.21 |
| Recall | 0.655 | 0.703 | **0.520** | ~0.52 |
| F1 | 0.253 | 0.240* | **0.304** | 0.308 |
| % GT executions fragmented | 90.6% | 94.7% | **77.6%** | 77.9% |
| Under-segmentation rate | 0.085 | 0.063 | **0.204** | ~0.20 |
| Over-segmentation rate | 2.71 | 3.24 | 1.49 | ~1.49 |

*(V2's F1 here, 0.240, differs slightly from the 0.270 reported in Stage
7 — that number used the labeled-only 139,121-transition population;
this table's pooled boundary_metrics runs over the full 162,705-transition
set for a like-for-like comparison with V1 and the reconstruction output,
so the two are not directly comparable without that context. Both are
correct for their own stated population.)*

**Design 1 vs. Design 2**: nearly identical (F1 0.308 vs. 0.304; frag
77.9% vs. 77.6%). Rule 3 (cluster protection) matched 338 candidates and
— by construction — removed none of them (its entire function is to
keep). Rule 2 (return-pattern) matched and removed 151. Rule 4 alone
matched 8,487 and removed 4,774. **Rules 2+3 together touch only ~5.4%
of all candidates (489 of 9,021) — Rule 4's continuity check dominates
the outcome by sheer volume**, which is exactly why Design 2's explicit
case-handling barely moves the aggregate numbers relative to the simpler
Design 1 ablation in this experiment.

## 5. Rule-level breakdown (the most important diagnostic)

| Rule | Matched | Removed | GT-correct boundary removed | False-internal removed | Removed in noise gap |
|---|---|---|---|---|---|
| Rule 1 (chunk/noise) | 45 | 45 | 1 | 34 | 10 |
| Rule 2 (return-pattern) | 151 | 151 | 23 | 95 | 33 |
| Rule 3 (cluster protection) | 338 | 0 | 0 | 0 | 0 |
| Rule 4 (continuity) | 8,487 | 4,774 | 296 | 3,667 | 811 |

**The improvement is not explained by known data-quality exclusions**:
Rule 1 accounts for only 0.9% of all removals (45 of 4,970 total) — the
gain is overwhelmingly coming from Rule 4, i.e., the actual neighborhood-
continuity hypothesis, not from chunk/noise cleanup. That is genuine
support for the underlying hypothesis from Stage 8.

**But Rule 4 removes 296 real (GT-correct) boundaries alongside 3,667
false-internal ones** — a roughly 12:1 ratio, better than doing nothing,
but the 296 lost real boundaries are exactly what drives recall down to
0.520 and under-segmentation up to 0.204. Rule 2 shows the same pattern
at smaller scale (23 real boundaries removed alongside 95 false-internal
— a less favorable ~4:1 ratio, worth noting as weaker evidence quality
for Rule 2 specifically than for Rule 4). The one GT-correct boundary
removed by Rule 1 is consistent with Stage 4's own finding that
chunk-boundary/real-boundary overlap is rare but not literally zero (1
known exception).

## 6. Session-level stability

54 of 63 sessions improved on fragmentation relative to the better of
V1/V2; 8 got worse (mean change: **+12.3 percentage points**, std 10.6 —
broad, not concentrated in a handful of sessions on this metric).

**But on under-segmentation, all 63 of 63 sessions got worse** — this is
universal, not an artifact of a few extreme sessions. This is the
clearest, most decisive piece of evidence behind the gate failure: it is
not noise, not session-specific, and not fixable by excluding a handful
of outlier sessions.

## 7. Success gate (pre-registered, evaluated honestly)

| Condition | Result |
|---|---|
| 1. Fragmentation materially lower than both V1 and V2 | **PASS** (77.6% vs. 90.6%/94.7%) |
| 2. Recall ≥ 0.5 floor | **PASS** (0.520) |
| 3. Under-segmentation not materially worse | **FAIL** — 0.204 vs. 0.063–0.085 baseline (2.4–3.3x; universal across 63/63 sessions, not a borderline call under any reasonable definition of "material") |
| 4. Improvement not concentrated in a few sessions | **PASS** (54/63 improved, broad) |
| 5. Gain not explained solely by chunk/noise | **PASS** (0.9% of removals from Rule 1) |

**Overall: the success gate does NOT pass.** Condition 3 is a hard,
independent gate per the pre-registered protocol, and it fails cleanly —
not marginally, not on a technicality, and not only at the selected
threshold (the full sweep in §2 shows no threshold avoids this trade-off).

## 8. Limitations, stated plainly

- Rule 2's window-based return-pattern search (±10 events) will miss
  leave-and-return patterns whose away-period exceeds that window —
  Stage 8 measured the away-duration tail reaching 49–62s at p90, likely
  exceeding 10 events in busier stretches. This is a known, documented
  gap in this implementation, not a claim that Rule 2 is complete.
- Rule 1 covers only the one instrumentation-noise pattern with an
  existing, reliable, reusable detector (duplicate `app_switch`).
  Browser-error storms (Stage 2's worst-case example) have no such flag
  and are not covered.
- `event_type_jaccard` alone, at the population level, does not cleanly
  separate "safe to demote" from "must keep" among candidates — the
  monotonic trade-off in the full sweep (§2) is direct evidence of this,
  consistent with (not contradicting) Stage 8's own finding that false-
  internal and ordinary-same-execution jaccard distributions were nearly
  indistinguishable in the pooled population.

## 9. Is Design 3 justified?

**Not on this evidence, and not yet.** The brief's instruction — do not
add complexity when the gate fails — is followed here. But it's worth
stating precisely *why* Design 3 (a weighted composite of 2–3 features)
is not obviously the right next move even setting that instruction aside:
the sweep in §2 shows the failure is not a threshold-placement problem
(no τ on this curve avoids the trade-off), which is the same shape of
result Stage 7 already found for V1/V2's own thresholds. Blending in a
second feature (e.g. `interaction_category_jaccard`) might sharpen the
margin somewhat, but Stage 8 already documented substantial population-
level overlap between false-internal and ordinary-same-execution
transitions on both jaccard measures — there is no evidence yet that a
linear combination would resolve an overlap this large rather than
merely relabeling where the same trade-off curve sits. Before trying
Design 3, the more informative next step (a decision for the project
owner, not made here) would be understanding *why* Rule 4 misclassifies
the 296 real boundaries it removes — e.g., whether they share some other
already-available characteristic — rather than assuming a weighted score
fixes an unexplained error population.

## Files

- `src/procmine/segmentation/reconstruction.py`
- `tests/test_reconstruction.py` (29 tests)
- `scripts/run_reconstruction_experiment.py`
- `reports/day2/reconstruction_experiment_dataset_a.json`
- `reports/day2/reconstruction_stage_8_3.md` — this file
