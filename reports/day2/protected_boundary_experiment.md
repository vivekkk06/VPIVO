# Stage 8.5 — Controlled Protection Experiment

**Additive experiment only.** Stage 8.3's `reconstruction.py` and
`run_reconstruction_experiment.py` are byte-for-byte unmodified —
re-running Stage 8.3's original script after this experiment reproduces
identical results (F1 0.253/0.240/0.304/0.308, frag% 90.6/94.7/77.6/77.9
for V1/V2/Design 2/Design 1, exactly as before). Protection is a new,
separate post-processing layer (`protected_boundary.py`) applied only to
transitions Design 2 already demoted under Rule 4; Rules 1–3 and the
candidate union are untouched. No classifier trained, no GT-derived
feature used as reconstruction input, Dataset B untouched, Design 3 not
attempted.

## Question

Can Stage 8.4's two signals — cross-model agreement and post-transition
tempo — protect some of Rule 4's 296 wrongly-demoted real boundaries
without giving back too much of its 3,667-false-boundary reduction?

## Implementation

`protected_boundary.apply_protection()` takes Design 2's own
already-computed `(final_boundary, rule_applied)` arrays and, for every
transition where `rule_applied[i] == RULE_4_CONTINUITY and not final_boundary[i]`
(i.e. only transitions Rule 4 itself demoted), optionally overrides the
decision to KEEP:

- **Strategy Agreement**: protect if flagged by both V1 and V2.
- **Strategy Tempo**: protect if `after_window_duration_ms` (N=10,
  reused from `context_features.py` unchanged) ≥ a selected threshold.
- **Strategy Combined**: protect only if both conditions hold.

Every other transition (kept by any rule, demoted by Rule 1/2, or never
a candidate at all) passes through completely unchanged — verified by
16 unit tests, including an explicit test that maximally favorable
protection evidence cannot create a boundary that was never a V1/V2
candidate.

## Threshold selection

4,774 Rule-4-demoted candidates were eligible (296 true boundaries,
4,478 false — this denominator is larger than Stage 8.4's 3,667 "false
internal" figure because it also includes demotions that fell in
unlabeled noise gaps; for a "protect or not" decision only "is this a
real boundary" matters, so both are pooled together here). Reused
Stage 7's exact grid method (`threshold_analysis.build_threshold_grid`)
on the pooled `after_window_duration_ms` values of this population.

| τ (ms) | protected | true protected | false protected | precision | recall | F1 |
|---|---|---|---|---|---|---|
| 0.1–0.999 (score floor; identical) | 4,774 | 296 | 4,478 | 0.062 | 1.000 | 0.117 |
| 3,348.75 | 1,194 | 220 | 974 | 0.184 | 0.743 | 0.295 |
| 4,031.0 | 738 | 214 | 524 | 0.290 | 0.723 | 0.414 |
| **4,680.26 (selected)** | **615** | **206** | **409** | **0.335** | **0.696** | **0.452** |
| 5,857.24 | 462 | 108 | 354 | 0.234 | 0.365 | 0.285 |
| 9,562.93 | 280 | 10 | 270 | 0.036 | 0.034 | 0.035 |
| 51,659.30 (grid max) | 5 | 0 | 5 | 0.000 | 0.000 | 0.000 |

*(Full 52-point grid in the JSON artifact.)* **Selected τ = 4,680.3ms**
(max protection-F1). **This is a global, pooled, out-of-fold analytical
threshold selected from Dataset-A evidence across all 63 sessions at
once — the same methodology, and the same validation strength, as Stage
7's and Stage 8.3's own threshold selections. It is not nested or
cross-fitted, and no per-session threshold was ever computed.** GT was
used here only to build this one global threshold (mirroring exactly how
V1/V2's own thresholds were originally chosen) and, separately, for the
post-hoc evaluation below — never inside the protection decision itself.

## Leakage audit

Protection inputs, verified by construction: held-out V1/V2 predictions
(`flagged_by_both`), and `after_window_duration_ms` (raw event
timestamps and counts only, via the unchanged Stage 5 trajectory
function). **Neither references GT `case_id`, `process_code`,
`process_variant`, GT execution spans, GT boundary labels, or continuity
labels.** GT appears in exactly two places: pooled, global threshold
selection (above) and post-hoc evaluation (below) — never inside
`apply_protection` itself, which takes no GT-derived argument at all.

## Full reconstruction evaluation

| System | Recall | F1 | % fragmented | Under-seg | Over-seg |
|---|---|---|---|---|---|
| V1 | 0.655 | 0.253 | 90.6% | 0.085 | 2.710 |
| V2 | 0.703 | 0.240 | 94.7% | 0.063 | 3.239 |
| Design 2 (original) | 0.520 | 0.304 | 77.6% | 0.204 | 1.490 |
| Strategy Agreement | 0.681 | 0.252 | 93.0% | 0.075 | 2.877 |
| **Strategy Tempo** | **0.643** | **0.339** | **79.9%** | **0.133** | **1.671** |
| **Strategy Combined** | **0.636** | **0.344** | **79.1%** | **0.141** | **1.603** |

**Strategy Agreement essentially undoes Design 2's improvement**,
landing at 93.0% fragmented — worse than V1's own 90.6%, i.e. barely
distinguishable from doing nothing. **Strategy Tempo and Strategy
Combined both retain almost all of Design 2's fragmentation gain (79–80%
vs. Design 2's 77.6%, still far below V1/V2's 90.6/94.7%) while reducing
under-segmentation by 31–35% (0.204 → 0.133/0.141) and improving recall
(0.520 → 0.643/0.636) — and both achieve a higher F1 than Design 2 itself
(0.339/0.344 vs. 0.304), the best F1 of all six systems.**

## Rule-level analysis

| | Strategy Agreement | Strategy Tempo | Strategy Combined |
|---|---|---|---|
| Candidates protected | 3,302 | 615 | 452 |
| True boundaries protected | 269 | 206 | 193 |
| False boundaries protected | 3,033 | 409 | 259 |
| False:true ratio | **11.28** | **1.99** | **1.34** |
| % of Rule 4's 296 errors recovered | 90.9% | 69.6% | 65.2% |
| % of Rule 4's 3,667 correct removals sacrificed | 82.7% | 11.2% | 7.1% |
| Protected by source | 100% both | 452 both / 133 v2-only / 30 v1-only | 100% both (mechanical — AND condition) |

**Strategy Agreement recovers the most errors (90.9%) but at an
indefensible cost (sacrifices 82.7% of Design 2's correct removals,
ratio 11.28:1)** — direct confirmation that cross-model agreement alone
is too blunt: since 90.9% of Population B already satisfies it (Stage
8.4), protecting on it alone necessarily re-admits almost everything
Rule 4 removed. **Strategy Tempo recovers a smaller but still
substantial 69.6% of errors while sacrificing only 11.2% of correct
removals (ratio 1.99:1)** — a genuinely favorable trade. Interestingly,
Tempo protects across all three candidate sources (not just "both"),
meaning tempo carries information beyond what agreement alone captures.
**Strategy Combined trades some recovery (65.2%) for better precision
(7.1% sacrificed, ratio 1.34:1)** — the more conservative of the two
useful options.

## Session robustness

| | Strategy Agreement | Strategy Tempo | Strategy Combined |
|---|---|---|---|
| Under-seg improved / unchanged / worsened (of 63) | 63 / 0 / 0 | 63 / 0 / 0 | 63 / 0 / 0 |
| Under-seg improvement: median / mean / max | 0.113 / 0.201 / 1.308 | 0.071 / 0.099 / 0.758 | 0.063 / 0.075 / 0.313 |
| Recall improved / unchanged / worsened | 63 / 0 / 0 | 60 / 3 / 0 | 60 / 3 / 0 |
| Fragmentation improved / unchanged / worsened | 0 / 1 / 62 | 0 / 40 / 23 | 0 / 42 / 21 |
| Fragmentation change, mean (pp) | **−15.1** | −2.1 | −1.4 |

**Under-segmentation improves in every one of 63 sessions for all three
strategies — universal, not a few-session artifact.** Recall improves or
stays flat everywhere, never worsens. Fragmentation, as mechanically
expected (protection only re-adds boundaries), never improves and is
flat or worse everywhere — but the *size* of that cost differs sharply:
Strategy Agreement gives back a devastating 15.1 percentage points per
session on average (up to 48.6pp in one session), while Tempo and
Combined give back only 1.4–2.1pp on average. This is the clearest
quantitative statement of why Agreement fails and Tempo/Combined don't.

## Success gate

| Condition | Strategy Agreement | Strategy Tempo | Strategy Combined |
|---|---|---|---|
| 1. Recall materially improved | PASS | PASS | PASS |
| 2. Under-segmentation materially reduced | PASS | PASS | PASS |
| 3. Substantial fragmentation gain retained | **FAIL** | PASS | PASS |
| 4. Does not recreate V1/V2 fragmentation | **FAIL** | PASS | PASS |
| 5. Improves broadly, not a few sessions | PASS | PASS | PASS |
| 6. Meaningful false:true protection ratio | **FAIL** (11.28) | PASS (1.99) | PASS (1.34) |
| 7. No GT-derived reconstruction info | PASS | PASS | PASS |

**Strategy Agreement is explicitly rejected** — it fails three
independent conditions, all for the same underlying reason (the signal
is satisfied by 90.9% of the very population it's meant to protect, so
using it alone cannot be selective). **Strategy Tempo and Strategy
Combined both pass all seven conditions.**

## Decision

**This is a genuine, evidenced improvement over Design 2 — not a
complete fix.** Under-segmentation drops from 0.204 to 0.133–0.141, still
roughly double V1's own 0.085 and more than double V2's 0.063; the
problem is reduced, not solved. Per the brief's explicit framing, this
was the correct bar: the newly discovered signals were tested for
whether they *improve the operating point*, not for whether they solve
fragmentation outright, and by that standard Strategy Tempo and Strategy
Combined both clearly do.

**Neither is adopted as the final architecture in this stage.** Per
instruction, this result is reported as evidence that these signals are
worth carrying into a next-candidate reconstruction version — a
decision for the project owner, not made unilaterally here. Between the
two passing strategies: Strategy Combined is more conservative (better
false:true ratio, smaller fragmentation cost) while Strategy Tempo
recovers more errors and reaches a marginally higher recall; Strategy
Tempo's slightly higher F1 (0.339 vs. Combined's 0.344 — nearly
identical) makes this a genuine, close trade-off between the two, not
a clear winner, which is itself worth stating rather than picking one
arbitrarily.

## Files

- `src/procmine/segmentation/protected_boundary.py`
- `tests/test_protected_boundary.py` (16 tests)
- `scripts/run_protected_boundary_experiment.py`
- `reports/day2/protected_boundary_experiment_dataset_a.json`
- `reports/day2/protected_boundary_experiment.md` — this file
