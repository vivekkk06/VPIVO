# Global Sequence-Optimization Hypothesis (Dataset A) — feasibility study

Research question raised after locking Design 2 + Strategy Combined:
should segmentation be reformulated as a global objective (minimize
total intra-segment incoherence plus a per-boundary complexity penalty)
rather than independent per-transition classification + local
reconstruction rules? Tested as a forensic feasibility study first, per
instruction — no optimizer was to be built unless the evidence
supported it.

Script: `scripts/analyze_global_segmentation.py`. New modules:
`src/procmine/segmentation/global_segmentation_forensics.py`
(diagnostic-only; not wired into `reconstruction.py` or
`protected_boundary.py`). Artifact:
`reports/day2/global_segmentation_hypothesis_dataset_a.json`.

---

### Observation

Independent transition-level classification caused over-segmentation
(V1/V2 alone: 90.6%/94.7% of GT executions fragmented). Local
reconstruction (Design 2 + Combined) improved this but still leaves
79.05% fragmented, and every rule built so far decides one transition
(or a fixed 10-event window around it) at a time.

### Question

Could segmentation instead be formulated as a global sequence
optimization problem — choosing the whole boundary set at once to
minimize a segment-cost objective — rather than deciding each candidate
transition independently?

### Hypothesis

A segmentation should minimize total internal segment incoherence plus
a complexity penalty for introducing each additional boundary:
`L(B) = Σ C(Sj) + λ|B|`. Equivalently, for a candidate boundary
splitting `SL | SR`, compare the cost of keeping the split,
`C(SL) + C(SR) + λ`, against the cost of merging them, `C(SL ∪ SR)`.

## 1. Method (Step 1 — inspect existing evidence)

Reviewed V1/V2 scores, N=10 trajectory features (`context_features.py`),
Design 2 (`reconstruction.py`), Combined protection
(`protected_boundary.py`), and the prior segment-coherence forensics
(`segment_coherence.py`) before building anything new.
`segment_coherence.py` measures **cross-segment** similarity (comparing
two already-adjacent fragments to each other) and, as documented in
`segment_coherence_forensics.md`, that framing was already tested and
rejected. This experiment is a genuinely different question: **intra-
segment** incoherence — how internally consistent is a single candidate
segment on its own — which no existing module measured, so a small new
module (`global_segmentation_forensics.py`) was needed. It reuses
existing per-event/per-transition fields only (`CanonicalEvent
.event_type` / `.interaction_category`,
`TransitionFeatures.application_changed` / `.browser_domain_changed` /
`.log1p_delta_t_ms`), aggregated within a segment rather than across
one transition or one fixed window.

**Segment definition** (deliberately not tied to Combined's output, to
avoid a circular test of the architecture this might replace):
segments are bounded by the candidate set `C' = (V1 ∪ V2)` with Rule
1's already-validated chunk/duplicate-noise override applied (the one
sub-problem this project already solved — reused, not re-litigated).
Every remaining candidate is provisionally treated as a cut point,
reusing `segment_coherence.segment_index_bounds` directly (no
duplicated logic).

Population: **9,021** raw candidates (V1 ∪ V2); **45** filtered out as
Rule-1 noise; **8,976** in `C'`, of which **1,188** are real GT
boundaries (TRUE) and **7,788** are not (FALSE) — this is the
population every component and the composite score is tested against.

## 2. Candidate cost components (Step 2)

Four interpretable, GT-free components, each built from an existing
field, aggregated per-segment:

| Component | Built from | Intuition |
|---|---|---|
| `event_type_entropy_bits` | `CanonicalEvent.event_type` | diverse event types inside one segment = less coherent |
| `interaction_category_entropy_bits` | `CanonicalEvent.interaction_category` | same, at the coarser category level |
| `context_switch_rate` | `application_changed` / `browser_domain_changed` | how often the segment internally jumps app/domain |
| `temporal_irregularity_cv` | `log1p_delta_t_ms` | coefficient of variation of internal gaps — a volatile tempo suggests heterogeneous activity |

No weights were assigned up front. Per the brief's own instruction, the
experiment first tested each component alone (Step 3) and only combined
the ones with real evidence, using an unweighted, data-driven
combination (z-score sum against the pooled Dataset-A scale) rather
than a hand-tuned weight vector — the "mathematically cleaner
formulation" the brief invited if a plain weighted sum wasn't
justified.

## 3. Component-level forensics (Step 3)

For each component, tested whether the **merged** segment's own cost
(what `SL ∪ SR` would look like) discriminates real boundaries (TRUE)
from non-boundaries (FALSE) — AUC with TRUE as the positive class:

| Component | AUC | Separation | Session agreement | Validated? |
|---|---|---|---|---|
| `event_type_entropy_bits` | 0.339 | 0.161 | 90.5% (63 sessions) | yes |
| `interaction_category_entropy_bits` | 0.355 | 0.145 | 92.1% (63 sessions) | yes |
| `context_switch_rate` | 0.563 | 0.063 | 74.6% (63 sessions) | no (below 0.10 separation) |
| `temporal_irregularity_cv` | 0.257 | 0.243 | 92.1% (63 sessions) | yes |

Three of four components are discriminative (≥0.10 separation) and
session-robust (≥75% agreement, all 63 sessions eligible) — but the
**direction is the opposite of the hypothesis**: TRUE boundaries have
**lower** merged-segment entropy/CV than FALSE candidates, not higher.
A merge across a real process boundary was expected to look *more*
chaotic than a merge across a spurious one; the data shows the reverse.

**Secondary check — does own-segment cost track actual coherence?**
For every candidate-implied segment, split by whether it's "pure" (no
missed/undetected GT boundary inside) or "impure" (silently merges two
real executions because both V1 and V2 missed that boundary):

| Component | AUC (impure positive) | Separation |
|---|---|---|
| `interaction_category_entropy_bits` | 0.701 | 0.201 |
| `event_type_entropy_bits` | 0.670 | 0.170 |
| `context_switch_rate` | 0.282 | 0.218 |
| `temporal_irregularity_cv` | 0.356 | 0.144 |

Here entropy behaves as expected (impure segments genuinely score
higher — the "lower cost = more coherent" premise holds when comparing
whole segments of very different, size-independent character). The
mechanistic explanation for the earlier reversal: raw (non-length-
normalized) entropy and CV both tend to increase simply with more
events, independent of whether those events represent one task or two
— and FALSE candidates in `C'` sit disproportionately inside longer,
still-fragmented stretches (the same "interior split of a bigger
execution" pattern the prior segment-coherence experiment already
found via `right_n_events`/`left_n_events`). The purity check isn't
confounded the same way because "impure" segments are large by
construction on both sides of the comparison; the merged-vs-candidate-
label test is, because `SL`/`SR`/merged sizes vary systematically with
the TRUE/FALSE label itself. This is a genuine, useful finding about
*why* a naive entropy-based segment cost doesn't transfer cleanly to a
per-candidate decision, not an artifact of a coding mistake.

## 4. Split-vs-merge counterfactual (Step 4)

**Sign convention, defined explicitly** (the brief invited this,
noting its own worked example shouldn't be assumed correct without
checking): since `C` is an incoherence cost (higher = worse),
`gap(i) = z(C(SL ∪ SR)) − [z(C(SL)) + z(C(SR))]`. A positive gap means
merging concentrates *more* standardized incoherence than the two
fragments already had separately — evidence *for* keeping the split.
This is the opposite sign from the brief's own literal `Δᵢ` formula,
which read as internally inconsistent once "cost" is fixed to mean
"higher = worse" — resolved here by being precise rather than guessing.

Built from the three validated components only (`event_type_entropy`,
`interaction_category_entropy`, `temporal_irregularity_cv`):

- AUC (TRUE positive) = **0.580**, separation **0.080** — below the
  0.10 bar.
- Session-direction agreement: 85.7% (54/63) — robust, but the
  underlying signal itself is too weak for that robustness to matter.
- FALSE gap distribution: mean 1.30, median 1.54. TRUE gap
  distribution: mean 1.71, median 1.78 — directionally consistent with
  the hypothesis (TRUE slightly higher) but heavily overlapping (FALSE
  p75 = 2.74 vs TRUE p75 = 1.91).

Combining the three components nets out much of each one's individual
(confounded) signal rather than reinforcing it — consistent with the
component-level finding above: each raw component's "TRUE lower than
FALSE" pattern on the *merged* side works against, not for, a
composite score meant to read "TRUE ⇒ splitting reduces cost."

## 5. λ / complexity-penalty sweep (Step 5)

Reused `threshold_analysis.build_threshold_grid` (Stage 7's exact
method, not a fresh arbitrary grid) over the composite gap's pooled
out-of-fold distribution; selected λ by max F1 subject to recall ≥ 0.5,
the same floor used for every prior threshold in this project:

| Classifier | Selected value | Precision | Recall | F1 |
|---|---|---|---|---|
| Gap-based (this experiment) | λ = 0.999 | 0.201 | 0.942 | **0.331** |
| `event_type_jaccard_n10` (existing, Rule 4's own feature) | τ = 0.30 | 0.249 | 0.683 | **0.365** |

Both classifiers were evaluated on the exact same `C'` population, so
this is a fair, same-data comparison. The new gap-based score does not
beat the existing feature already in production.

## 6. Decision gate (Steps 3-5 evidence, pre-registered before Step 6)

| Condition | Result |
|---|---|
| A. At least one component validated | **PASS** (3 of 4) |
| B. Composite gap discriminative (≥0.10 separation) | **FAIL** (0.080) |
| C. Composite gap session-robust (≥75%, ≥15 sessions) | PASS (85.7%, 63 sessions) — moot, given B |
| D. Gap classifier competitive with existing baseline (F1 ≥ baseline) | **FAIL** (0.331 vs 0.365) |

Two of four gate conditions failed. **Step 6 (dynamic-programming
global optimizer) and Step 7 (comparison against locked Combined) were
never executed** — per the brief's own instruction, DP is only built
if the cost formulation already shows promise, and it doesn't here.

### Evidence

Three of four intra-segment incoherence components discriminate real
boundaries from candidates reasonably well and hold up across all 63
sessions — but in the *opposite* direction the hypothesis predicted,
traced to a segment-length confound in raw entropy/CV. The purity check
confirms the underlying "lower cost ⇒ more coherent" premise is sound
in principle (AUC 0.67–0.70) but that soundness doesn't survive being
turned into a per-candidate split-vs-merge decision using this
population's actual size dynamics. The resulting composite gap score
is directionally correct but too weak (separation 0.080, just under
the 0.10 bar) and, decisively, is not competitive with a feature
already in production on the identical population (F1 0.331 vs 0.365).

### Decision

**B. The mathematical formulation does not provide sufficient robust
evidence, so I rejected the additional complexity and retained
Combined.** No dynamic-programming prototype was built; no comparison
against Combined's full pipeline metrics was run, because the
feasibility gate that was supposed to justify that work did not pass.
This is treated as an acceptable, informative engineering outcome, not
a failure to fix: it identifies a real confound (segment-size-driven
entropy) worth remembering if this direction is revisited later, rather
than quietly forcing a length-normalized version into existence to
rescue the hypothesis after seeing the numbers.

## 7. Leakage audit

- `global_segmentation_forensics.compute_segment_cost` and
  `internal_feature_slice` take only a `CanonicalEvent` slice and a
  `TransitionFeatures` slice — no `process_code`, `case_id`,
  `process_variant`, GT execution span, continuity label, or boundary
  label parameter exists on either signature.
- In the analysis script, GT (`is_boundary_labels`) is used only to (a)
  label each `C'` candidate TRUE/FALSE for the forensic comparison, (b)
  the purity check's pure/impure split, and (c) selecting λ from
  pooled, global, out-of-fold evidence — the same two permitted uses as
  every prior threshold in this project (Stage 6/7/8.3/8.5), never as a
  live input to the cost computation itself.
- Dataset B was not read, loaded, profiled, or referenced anywhere in
  this script.

## 8. Final architecture status

**FINAL ARCHITECTURE UNCHANGED: Design 2 + Strategy Combined
protection**, exactly as locked in
`reports/day2/segmentation_architecture_final.md` and
`reports/day2/final_architecture_dataset_a.json`. `reconstruction.py`
and `protected_boundary.py` were never imported by the DP-comparison
code path (which was never reached) and were not modified. Dataset B
was not touched at any point in this investigation.
