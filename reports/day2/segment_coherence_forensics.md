# Segment-Level Coherence Forensics (Dataset A) — Day 2 closing follow-up

Investigation into whether a segment-scoped (not fixed-N=10) coherence
signal can find further, legitimate demotion opportunities among the
locked **Design 2 + Strategy Combined** architecture's remaining false
boundaries, before Dataset A work is closed and Dataset B is touched.

Script: `scripts/analyze_segment_coherence_forensics.py`. New module:
`src/procmine/segmentation/segment_coherence.py` (diagnostic-only, not
wired into `reconstruction.py` or `protected_boundary.py`). Artifact:
`reports/day2/segment_coherence_forensics_dataset_a.json`.

---

## 1. Question

The locked architecture (Design 2 + Strategy Combined) still leaves
79.05% of GT executions fragmented. Every reconstruction rule built so
far (Rules 1–4, the Tempo/Combined protection layer) decides each
candidate boundary using either a single adjacent event pair or a
*fixed* 10-event window on each side. Before accepting that remaining
fragmentation as a structural limit of this architecture, I wanted to
know: does looking at the *actual*, variable-length segment on each
side of a candidate — the real fragment implied by the current final
boundary set, not a fixed 10-event proxy — find a materially better
signal for telling apart the boundaries that are still wrong from the
ones that are correct?

## 2. Motivation

Independent per-transition classification over-segments; Design 2's
neighborhood rules reduced that but not fully; the protection layer
recovered some of what Rule 4 over-corrected. Each fix operated on a
progressively wider but still fixed window. The next logical question
is whether "wide enough" should mean "as wide as the actual candidate
segment," not a fixed constant — i.e., whether segment-level coherence
(the literal fragment-to-fragment comparison a human reviewing the
session would make) contains information the fixed-window features
already used have not exhausted.

## 3. Hypothesis

A remaining class of false boundaries is detectable by a segment-level
question rather than a transition-level one: "if this candidate
boundary were removed, would the resulting merged segment look like one
coherent execution?" — operationalized as trajectory similarity
(event-type / interaction-category / application / browser-domain
Jaccard) and activity-rate continuity between the real left and right
fragments, plus fragment "thinness" (a very short fragment on either
side is itself weak evidence of a spurious split).

This was explicitly forensic-first: if the evidence didn't support a
useful segment-level signal, the instruction was to stop and keep
Combined, not to force a new rule into existence.

## 4. Current Combined baseline (reproduced, not re-derived)

Re-running the exact locked pipeline (V1 @0.9078, V2 @0.8860, Design 2
Rule 4 @0.40, Combined protection tempo @4680.2613ms — none re-selected)
reproduced the locked numbers exactly:

| Metric | Reproduced | Locked JSON |
|---|---|---|
| Recall | 0.6355 | 0.6355 |
| F1 | 0.3440 | 0.3440 |
| % fragmented | 79.05 | 79.05 |
| Under-segmentation | 0.1412 | 0.1412 |
| Over-segmentation | 1.6033 | 1.6033 |
| TP / FN / FP | 1062 / 609 / 3441 | 1062 / 609 / 3441 |

This confirms the pipeline is reproducible and that this investigation
starts from the actual locked state, not a re-derived approximation.

## 5. Method

Among Combined's 4,503 final `final_boundary=True` transitions, I split
into:

- **Population T** (1,062): correctly kept — a real GT boundary.
- **Population F** (3,441): still kept, but not a real GT boundary —
  the remaining over-segmentation error the hypothesis targets.

For every member of T ∪ F I computed, per `segment_coherence.py`:

- the actual left/right segment bounds implied by the *current*
  `final_boundary` array (`segment_index_bounds`, same cut convention
  as `evaluation.segments_from_boundaries`);
- four segment-scoped Jaccard measures (event type, interaction
  category, application, browser-domain host-only) between those two
  real fragments;
- an activity-rate continuity ratio (`min(rate)/max(rate)` of
  events/second on each side, `None` — not zero — when a fragment has
  zero duration);
- fragment "thinness" (`min_segment_n_events`, `min_segment_duration_ms`,
  and each side's own event count).

Alongside these new signals, I recomputed the existing fixed-N=10
baselines already used by Rule 4/the protection layer
(`event_type_jaccard_n10`, `after_window_duration_ms_n10`,
`flagged_by_both_models`) and Stage 5's original per-transition signals
(`delta_t_ms`, `density_before`, `density_after`) on this same T/F
population, and reused `return_pattern_evidence_for_transition` for
context. All of this is GT-free at computation time — GT enters only to
label a record T or F for the comparison, exactly as it did in Stage
8.4's Population A/B analysis.

## 6. Candidate segment-level signals

New (segment-scoped, this investigation):
`segment_event_type_jaccard`, `segment_interaction_category_jaccard`,
`segment_application_jaccard`, `segment_browser_domain_jaccard_host_only`,
`rate_continuity_ratio`, `min_segment_n_events`,
`min_segment_duration_ms`, `left_n_events`, `right_n_events`.

Existing, included for direct comparison:
`event_type_jaccard_n10`, `after_window_duration_ms_n10`,
`flagged_by_both_models`, `delta_t_ms`, `density_before`,
`density_after`.

## 7. Global distributions (AUC with F as the positive class)

Ranked by discrimination (|AUC − 0.5|), top eight:

| Signal | AUC (F+) | Separation | T median | F median | New / existing |
|---|---|---|---|---|---|
| `right_n_events` | 0.250 | 0.250 | 69 events | 6 events | **new** |
| `after_window_duration_ms_n10` | 0.721 | 0.221 | 444ms | 1,408ms | existing |
| `left_n_events` | 0.706 | 0.206 | 2 events | 31 events | **new** |
| `delta_t_ms` | 0.678 | 0.178 | 515ms | 2,557ms | existing |
| `event_type_jaccard_n10` | 0.323 | 0.178 | 0.286 | 0.200 | existing |
| `flagged_by_both_models` | 0.349 | 0.151 | rate 0.924 | rate 0.621 | existing |
| `min_segment_n_events` | 0.636 | 0.136 | 2 events | 4 events | **new** |
| `rate_continuity_ratio` | 0.607 | 0.107 | 0.159 | 0.316 | **new** |

The four signals that most directly operationalize the *coherence*
hypothesis — the segment-scoped Jaccards and the rate-continuity ratio
— were the **weakest** of the group: `segment_event_type_jaccard`
(sep. 0.045), `segment_interaction_category_jaccard` (sep. 0.025),
`segment_application_jaccard` (sep. 0.060),
`segment_browser_domain_jaccard_host_only` (sep. 0.064). Only
`rate_continuity_ratio` (sep. 0.107) cleared the 0.10 "separates"
bar Stage 8.4 used, and even that trails every fixed-N=10 baseline
already in production.

The strongest signal in the whole population, `right_n_events`, is not
a coherence measurement at all — it is simply "how many events are in
the fragment that follows this boundary before the next kept boundary."
A mechanistic reason this is strong is visible in the data itself: F
(remaining false boundaries) are disproportionately *interior* splits
of one still-fragmented true execution, so the fragment between two
such false splits tends to be short by construction, independent of
any trajectory-similarity property. `left_n_events` shows the same
effect from the other side. This is a real pattern, but it is a
restatement of "these are pieces of a larger execution that's already
fragmented," not new evidence about *why* the split shouldn't exist —
and it carries an obvious risk: a real, short GT execution would look
identical to this signal, so a rule built on fragment length alone
would not obviously distinguish "should merge" from "genuinely a short
execution."

`event_type_jaccard_n10` is also visibly saturated in this remaining
population: 80.4% of T and 83.1% of F fall in the `rule4_continuity`-
kept branch, whose only way to be *kept* by Rule 4 is `jaccard < 0.40`
— so both T and F are compressed below that threshold here (T's
p25–p75 range is `[0.286, 0.286]`, a near-constant value), which is
exactly why this feature, so effective in Stage 8.4, has little
headroom left to discriminate within Combined's specific leftover
population.

## 8. Per-session robustness

Session-direction consistency for the top six signals (63 sessions
eligible in every case):

| Signal | Agreement rate |
|---|---|
| `flagged_by_both_models` | 95.24% |
| `event_type_jaccard_n10` | 92.06% |
| `right_n_events` | 90.48% |
| `after_window_duration_ms_n10` | 88.89% |
| `left_n_events` | 88.89% |
| `delta_t_ms` | 82.54% |

`right_n_events` itself is session-robust (90.5%) — the problem is not
robustness, it is that it isn't a coherence signal and doesn't clear
the "meaningfully better than the existing baseline" bar (§11).

## 9. Counterfactual merge analysis

The segment-scoped Jaccard and rate-continuity signals *are* the
counterfactual-merge evidence: each one directly measures "if the
current split were removed, how similar would the two real
resulting fragments' activity be?" Their weak separation (0.025–0.107)
is itself the answer to Experiment 5's question for this dataset: a
higher-fidelity, segment-scoped coherence measurement does not make the
merge-vs-split call any clearer than the existing fixed-window
features already do. Per the brief's own instruction ("for promising
signals only, perform a counterfactual [KEEP vs REMOVE] analysis"), no
signal here cleared the bar to justify going further with a dedicated
KEEP/REMOVE comparison beyond the AUC test already run.

## 10. Leakage audit

- `segment_coherence.py`'s two public functions
  (`segment_index_bounds`, `compute_segment_coherence_evidence`) take
  only `canonical` (raw `CanonicalEvent` stream) and a `final_boundary`
  array the caller already produced — no `process_code`, `case_id`,
  `process_variant`, GT execution span, continuity label, or boundary
  label parameter exists on either signature.
- In the analysis script, GT (`is_boundary_labels`) is used only to
  assign each already-kept candidate to population T or F for
  comparison, and (had the gate passed) to select Rule 5's threshold
  and evaluate it — the same two uses already established as
  acceptable for every prior threshold in this project (Stage 6/7/8.3/
  8.5), never as a live input to `segment_coherence.py` itself.
- Dataset B was not read, loaded, profiled, or referenced anywhere in
  this script.

## 11. Decision gate

Pre-registered (written into the script before it was run against the
data) conditions, all required for the hypothesis to be SUPPORTED:

| # | Condition | Result |
|---|---|---|
| 1 | Best signal's separation from uninformative (\|AUC−0.5\|) ≥ 0.10 | **PASS** — `right_n_events`, 0.2498 |
| 2 | Session-direction agreement ≥ 75%, with ≥15 sessions eligible | **PASS** — 90.5% over 63 sessions |
| 3 | Signal is a genuinely new family, not one of the existing N=10 baselines | **PASS** (by name) |
| 4 | Best new signal's separation is meaningfully (≥0.03) better than the best existing N=10 baseline's separation | **FAIL** — 0.2498 vs. 0.2210 (existing `after_window_duration_ms_n10`) — margin 0.0288, just under the pre-registered 0.03 bar |

Condition 4 is a near-miss, not a clear failure — but it is a real
failure against the bar I set *before* running the analysis, and the
signal that produced it (`right_n_events`) is not actually the
coherence mechanism the hypothesis was about (§7). Treating a
0.03-short, mechanistically-unrelated signal as sufficient to justify a
new production rule would be exactly the kind of "make the number look
good" decision the assignment explicitly told me to avoid.

## 12. Final decision

**The segment-level coherence hypothesis is REJECTED.** No
trajectory-similarity or activity-rate-continuity signal computed over
the real, variable-length neighboring segments discriminates Combined's
remaining false boundaries from its correctly-kept ones better than the
fixed-N=10 features already in production, and the one signal that
did edge past the discrimination/robustness bars (`right_n_events`) is
a restatement of "these are interior pieces of an already-fragmented
execution," not new evidence about the merge decision, and it missed
the pre-registered non-redundancy margin regardless.

**No ablation (Experiment 7) was performed** — the decision gate did
not pass, so no new rule was designed, thresholded, or evaluated
against Combined.

**FINAL ARCHITECTURE REMAINS: Design 2 + Strategy Combined protection**,
exactly as locked in `reports/day2/segmentation_architecture_final.md`
and `reports/day2/final_architecture_dataset_a.json`. Dataset A work is
closed; Dataset B was not touched at any point in this investigation.
