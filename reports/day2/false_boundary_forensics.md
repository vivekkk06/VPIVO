# Stage 2 — False-Boundary Forensic Analysis

**Investigation only.** No retraining, no new threshold, no feature
changes, no Dataset B, no merge/continuity logic. Reuses the exact V1
model configuration and Stage 6's threshold (0.9078) throughout. Source:
`scripts/forensic_false_boundaries.py`, re-running the identical
leave-one-session-out procedure manually (not via `cross_val_predict`)
specifically to keep each fold's fitted pipeline — feature-contribution
decomposition below always uses the model that never saw the session
being explained, never a leakage-tainted one.

## 1. False-boundary definition (exact matching logic)

A transition is a **false internal boundary** when: the model predicts a
boundary (`probability ≥ 0.9078`), it is **not** a real GT boundary, **and**
both its endpoints (`event_i.timestamp_ms`, `event_next.timestamp_ms`)
fall strictly within one GT execution's `[start_ts, end_ts]` span. A
predicted-but-wrong boundary whose endpoints fall in an unlabeled
"noise" gap between executions is **excluded** from this analysis
(counted separately as `false_noise`) — there is no GT claim about that
time, so it isn't evidence of fragmenting a *coherent execution*, which
is specifically what this investigation is about.

## 2–3. Counts and false vs. true boundary comparison (MEASUREMENT)

| | Count |
|---|---|
| True positives (TP) | 1,094 |
| False negatives (FN) | 577 |
| True negatives (TN) | 155,164 |
| **False internal boundaries** | **4,903** |
| False-in-noise-gap (excluded) | 967 |

Recall = 1,094 / 1,671 = 65.5% — matches Stage 6 (small ±2 count
difference from re-running LOSO manually vs. `cross_val_predict`;
immaterial). **4,903 false internal boundaries against only 1,671 real
boundaries** — the model produces roughly 3 false internal splits for
every real boundary it's trying to find.

## 4. Model probability: can it tell true from false internal apart? (FACT)

| | n | mean | median | p25 | p75 | p90 | p95 |
|---|---|---|---|---|---|---|---|
| True boundaries | 1,671 | 0.877 | **0.932** | 0.844 | 0.958 | 0.975 | 0.989 |
| False internal | 4,903 | 0.958 | **0.960** | 0.936 | 0.980 | 0.993 | 0.998 |

**The model is more confident on its false internal predictions than on
real boundaries.** Median probability for false internals (0.960) exceeds
median probability for true boundaries (0.932). This is not a threshold
problem — no threshold placed anywhere on this probability scale would
cleanly separate the two populations, because the wrong population is, if
anything, shifted *higher*. This is the single most important number in
this investigation: it rules out "just raise the threshold" as a fix.

## 5. Feature distribution comparison (MEASUREMENT)

| Feature | True boundaries (median) | False internal (median) |
|---|---|---|
| `delta_t_ms` | 526 | **2,627** |
| `log1p_delta_t_ms` | 6.27 | 7.87 |
| `density_before` | 11 | 13 |
| `density_after` | 30 | 20 |
| `application_changed` (rate) | 2.0% | 4.6% |
| `window_title_changed` (rate) | 2.3% | 5.8% |
| `browser_domain_changed` (rate) | 86.1% | 78.9% |
| `interaction_category_changed` (rate) | 97.5% | 97.7% |
| `extracted_text_at_transition` (rate) | 9.8% | 21.1% |
| `chunk_boundary` (rate) | 0.06% | 0.16% |

**The false internal transitions have *larger* gaps than real boundaries**
(median 2,627ms vs. 526ms) — over 5x larger. This is the core mechanism:
Dataset A contains natural mid-execution pauses (thinking, reading,
waiting for a page) that are **larger than a typical real boundary gap**,
and the model has learned gap size as such a strong signal that these
pauses get misread as boundaries.

**`interaction_category_changed` is near-ubiquitous in both classes**
(97.5% vs. 97.7%) — it fires on almost every transition regardless of
class, consistent with Stage 6's finding that it contributes to the model
but isn't independently discriminating as a simple rate.

**A specific limitation found in `browser_domain_changed`, not previously
identified**: this feature parses `urlparse(url).netloc`, which includes
the port number. The portal system in this data runs multiple
micro-services on different local ports (`127.0.0.1:5122`,
`:5123`, `:5124` — confirmed directly in Day 1). Navigating between
different pages of what is functionally **one coherent multi-step
process** can register as a "domain change" purely because the ports
differ — plausibly explaining why this feature fires at a high rate
(78.9%) even on transitions *inside* a single execution. **HYPOTHESIS,
not yet tested**: comparing hostname-only (ignoring port) might sharpen
this feature; flagged for a later experiment, not changed now.

## 6. Feature contribution analysis (MEASUREMENT — real decomposition, not estimated)

Mean per-transition logit contribution (`standardized_value × coefficient`)
among the 4,903 false internal cases, using each session's own held-out
fold model:

| Feature | Mean contribution | % of cases pushing toward "boundary" |
|---|---|---|
| **`log1p_delta_t_ms`** | **+6.645** | 96.7% |
| `density_after` | +1.160 | 71.9% |
| `browser_domain_changed` | +0.969 | 78.9% |
| `interaction_category_changed` | +0.683 | 97.7% |
| `density_before` | +0.336 | 67.3% |
| `extracted_text_at_transition` | −0.249 | 78.9%* |
| `window_title_changed` | −0.024 | 94.2% |
| `chunk_boundary` | −0.003 | 99.8% |
| `application_changed` | −0.014 | 93.7% |

*(rate reflects how often the feature is present, not the direction of
its pull — its contribution is negative on average, i.e. it dampens
these false positives rather than causing them.)*

**`log1p_delta_t_ms`'s contribution (+6.645) is 4–7x larger than any
other feature's.** This directly and quantitatively answers the
investigation's central question: **temporal gap dominates the false
positives, by a wide margin.** No other single feature comes close.
`chunk_boundary` and `application_changed` contribute almost nothing
either way — consistent with Day 1/Stage 6's findings about both.

## 7. Execution-level examples (not cherry-picked — worst, moderate, and the honest absence of a clean case)

**No session in Dataset A has zero false internal boundaries** — checked
directly, 0 of 63. There is no "minimally fragmented" example to show
that isn't itself still fragmented; the closest is
`ses_20260701-054901-LAPTOP-R36BQBTE` at 26.9% of executions fragmented
(still roughly 1 in 4).

**Worst case (62 false splits in one execution)** —
`ses_20260701-054930-CHAITANYA0BCF`, execution `SHP-111912-003`, 42
seconds long, 262 events. Breakdown: **170 of 262 events (65%) are
`browser_error`**, plus 43 `app_switch` events in that same 42-second
window. This is an error-storm execution — consistent with Day 1's
finding that `browser_error` events are frequently double-logged — not
representative human behavior. **This specific worst case has an
identifiable, different root cause (instrumentation noise) from the
general problem.**

**Moderate/representative case (16 false splits)** —
`ses_20260701-124033-SIDDHIGUPTAB00B`, execution `SHP-181002-002`, 88
seconds, 181 events, dominated by `keystroke` (78) — ordinary data-entry
work. Largest internal gaps: 28,158ms, 9,608ms, 4,516ms, 4,460ms. **No
error storm, no unusual event mix — just a person pausing mid-task for up
to 28 seconds**, which comfortably exceeds real-boundary gaps (median
526ms, p90 4,381ms) and gets read as multiple boundaries. **This is the
representative, pervasive case — not an edge case.**

## 8. Duplicate/noise relationship (MEASUREMENT — a clear negative result)

| | Rate among false internal boundaries |
|---|---|
| Involves a duplicated `app_switch` event | **0.31%** (15 of 4,903) |
| Occurs at a chunk-file boundary | **0.16%** (8 of 4,903) |

**Neither known instrumentation-noise pattern explains the false
positives.** This rules out "just deduplicate app_switch better" or
"handle chunk transitions better" as the fix — those account for well
under 1% of the problem combined. The worst-case example above (the
browser-error storm) is itself real evidence that *a* noise pattern can
cause severe local fragmentation, but it's rare (this appears to be the
single most extreme instance found) and not the general driver.

## 9. Session-level fragmentation (MEASUREMENT — widespread, not concentrated)

Every one of 63 sessions has false internal boundaries. Range: 25.0%–100%
of a session's GT executions fragmented; false-splits-per-execution from
0.35 to 3.58. **This is a widespread property of the model applied across
the whole dataset, not a few problem sessions** — there is no small
subset of "bad sessions" whose removal would fix the aggregate.

## 10–11. Main observed causes, ranked by evidence

1. **Temporal gap dominance (primary, ~5–7x stronger than any other
   feature)**: the model over-weights gap size, and legitimate
   mid-execution pauses in real work are frequently as large as, or
   larger than, typical inter-execution gaps. This is the cause of the
   *large majority* of the 4,903 false internal boundaries.
2. **The model's confidence is inverted, not just imprecise**: false
   internal predictions have *higher* median probability than true
   boundaries. A threshold adjustment cannot fix this — the ordering
   itself is wrong, not just the cutoff point.
3. **Rare, severe instrumentation-noise events (browser-error storms)**
   can locally produce extreme fragmentation (62 splits in one 42-second
   execution) — real, but not the general driver (noise involvement is
   <1% dataset-wide).
4. **`browser_domain_changed`'s port-sensitivity** is a plausible
   contributing factor for the feature's high false-internal rate, not
   yet confirmed by a controlled test.
5. Not a cause: duplicate `app_switch` events, chunk-boundary crossings —
   both measured at <1% involvement.

## 12. Evidence-backed recommendation

**Findings that support the continuity-first pivot**: the dominant
problem is exactly what continuity-first is meant to address — the
current formulation treats "big gap" as boundary evidence in isolation
strongly enough that it can't tell a real transition from a long pause
inside real work. A model that has to justify *sustained* discontinuity
across more of the transition's context, rather than reacting to gap size
so heavily, is a reasonable hypothesis for reducing this — but this
investigation does not prove continuity-first will fix it; that has to be
measured once built (Stage 5/6 of the continuity-first protocol), not
assumed here.

**Findings that complicate it / must carry forward**: the
temporal-gap-vs-pause overlap problem is a property of the *data*
(genuine human pauses are long and variable), not purely of the boundary-
first framing — a continuity-first model built on the same underlying
temporal feature could inherit the same confusion unless it weighs
temporal evidence differently or leans more on the features that
*didn't* show this inversion (the contribution table above is the
concrete starting point for that). The browser-error-storm case is a data
-quality issue no reformulation will fix on its own — it may need
explicit handling regardless of segmentation approach.

## Files

- `scripts/forensic_false_boundaries.py`
- `reports/day2/false_boundary_records_dataset_a.json` (4,903 detailed records)
- `reports/day2/false_boundary_session_summary_dataset_a.json` (per-session fragmentation)
- `reports/day2/false_boundary_forensics_dataset_a.json` (aggregate comparisons)
- `reports/day2/false_boundary_forensics.md` — this file
