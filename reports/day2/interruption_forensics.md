# Stage 8 — Forensic Characterization of Interruption/Return Patterns (Dataset A only)

**Forensic characterization only.** No reconstruction algorithm was
implemented (no clustering, DP, HMM, Viterbi, or graph optimization), no
new model was trained, no threshold was tuned, V1/V2's methodology was
not modified, and Dataset B was not touched or inspected. V1's and V2's
existing LOSO procedures and Stage 6-selected thresholds (0.9078, 0.8860)
are re-run **exactly as in Stages 2/6/7** solely to know, per transition,
whether each already-approved model would flag it — that is an input to
this analysis, not something re-derived here. GT (`process_code`,
`case_id`, execution spans) is used throughout for grouping/labeling —
never as a feature of any model. Source: `scripts/analyze_interruption_forensics.py`
(orchestration) and `src/procmine/segmentation/interruption_forensics.py`
(reusable, unit-tested logic: `internal_transition_indices`,
`build_execution_profile`, `collapse_to_runs`, `detect_return_patterns`).

Terminology reused, not redefined, from prior stages: `SAME_EXECUTION`,
`EXIT_TO_DIFFERENT_EXEC`, `EXIT_TO_NOISE_BOUNDARY` (Stage 4's approved
continuity-label categories, `continuity_labels.py`), the false-internal-
boundary definition (Stage 2: model probability over threshold, not a
real GT boundary, both endpoints inside one GT execution's span), and
N=10 trajectory-jaccard (Stage 5's evidence-backed window size,
`context_features.py`, unchanged).

## 0. A count reconciliation, stated plainly rather than silently resolved

The brief states Dataset A has 2,009 GT executions. That number is
correct **and** consistent with every prior stage: `parse_gt_manifest_executions`
returns 2,009 executions total, of which **1,752 have a defined `end_ts`
("closed") and 257 do not ("open/unclosed")**. Every span-based
computation in this project — `extract_boundaries` (Stage 2),
`execution_metrics` (Stages 6/7), and this stage — has consistently used
only closed executions, because an execution without an end has no
defined interval to compute an internal gap, an internal transition, or
a fragmentation count against. This report's "1,752 GT executions" is
therefore the same population every other segmentation report has used,
not an undercount — stated here explicitly so the two numbers in
circulation (2,009 vs. 1,752) don't read as a discrepancy.

## 1. How often do long gaps / context changes occur *within* a GT execution, and in combination?

Measured over all 137,450 `SAME_EXECUTION` transitions (Stage 4's
already-approved category — both endpoints of the transition fall inside
one GT execution). "Long gap" = `delta_t_ms` at or above this
population's own 90th percentile (**1,147ms**, data-driven, not an
arbitrary constant).

| Signal | n firing | rate |
|---|---|---|
| Long gap (≥ p90 = 1,147ms) | 13,746 | 10.0%* |
| App switch | 2,362 | 1.72% |
| Window-title change | 3,731 | 2.71% |
| Browser-domain change | 40,122 | 29.19% |
| Interaction-category change | 72,067 | 52.43% |

*(10.0% is exact by construction — it's the definition of "≥ 90th
percentile" on this same population, included for completeness, not as a
discovery.)*

**Combinations (OBSERVATION):** the strongest pairwise co-occurrence is
`browser_domain_change` + `interaction_category_change` (39,521 co-
occurrences, 54.4% Jaccard of the two signals) — expected, since a domain
change almost always changes what kind of interaction is happening.
`long_gap` + `interaction_category_change` co-occurs on 12,374 transitions
(9.0% of all internal transitions) but only a 16.9% Jaccard — i.e., most
category changes are *not* accompanied by a long gap, and vice versa;
they are only weakly coupled. Distribution of **how many of the 5 signals
fire simultaneously** on one internal transition:

| # signals firing | 0 | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|---|
| n transitions | 63,324 | 28,099 | 36,476 | 7,554 | 1,670 | 327 |
| % | 46.1% | 20.4% | 26.5% | 5.5% | 1.2% | 0.2% |

**OBSERVATION**: only 6.9% of internal transitions fire 3+ signals at
once — most "interruption-looking" moments inside real work show only
one or two of these signals, not a clear multi-signal spike. This is
consistent with (not proof of) the reconstruction-layer hypothesis that
no single transition-level signal, or even a small combination, reliably
separates internal activity from a boundary — which is exactly why V1/V2
over-trigger on gap size alone (Stage 2's finding, confirmed again below).

## 2. Per-execution interruption-pattern characterization

Built via `build_execution_profile()` for all 1,752 closed GT executions;
18 have zero internal transitions (single-event executions — no gap to
measure).

| Per-execution metric | mean | median | p90 | p99 | max |
|---|---|---|---|---|---|
| Max internal gap (ms) | 12,500 | 4,598 | 22,062 | 70,647 | 983,945 |
| # gaps ≥ p90 (1,147ms) | 7.8 | 7 | 11 | 16 | 34 |
| # app switches | 1.35 | 2 | 3 | 6 | 9 |
| # browser-domain changes | 22.9 | 25 | 35 | 50 | 99 |
| # window-title changes | 2.13 | 2 | 4 | 8 | 14 |
| # interaction-category changes | 41.1 | 40 | 54 | 76 | 187 |

**OBSERVATION**: a typical GT execution contains **~7-8 internal gaps
already larger than the dataset-wide 90th-percentile same-execution
gap**, and 25 browser-domain changes — i.e., large gaps and domain
changes are the *norm* inside a single coherent execution, not a rare
event. This is the same structural fact Stage 2 diagnosed from the model
side (large gaps dominate false positives); this stage confirms it
directly from the execution side, independent of any model.

**Does activity resume after the interruption? (OBSERVATION, not yet a
causal claim)** At each execution's own largest internal gap (99.0% of
executions have one reaching the ≥p90 bar), N=10 trajectory-jaccard
around that specific gap was compared against the dataset-wide
`SAME_EXECUTION` population's own median (0.500 for `event_type_jaccard`,
0.600 for `interaction_category_jaccard` — both data-driven reference
bars, not arbitrary):

- 76.2% of these "largest-gap" moments have `event_type_jaccard` at or
  above the population median — i.e., context after the pause resembles
  the general same-execution norm more often than not.
- 61.7% show the same for `interaction_category_jaccard`.
- Density right after the gap: median 17 events in the following 5s
  window (mean 17.4) — activity resumes at a normal or above-normal pace
  in the large majority of cases, not trailing off.

**Representative examples (not cherry-picked — median, p90, and the
single most extreme case by max internal gap):**

| | session | case_id | process | duration | max internal gap | # app switches | # domain changes |
|---|---|---|---|---|---|---|---|
| Median case | `ses_20260701-070320-JAYESH` | RT-123250-003 | A | 28.1s | 4.6s | 0 | 29 |
| p90 case | `ses_20260630-135201-LAPTOP-R36BQBTE` | SI-192210-001 | D | 54.4s | 22.1s | 2 | 0 |
| Most extreme | `ses_20260701-081120-SIDDHIGUPTAB00B` | SUP-134051-002 | M | 19.1 min | **16.4 min** | 8 | 27 |

The most extreme case (a 16.4-minute internal gap inside a 19.1-minute
execution) is flagged rather than quietly included: **OBSERVATION**,
not a confirmed data-quality issue — this is a *different* session from
the one Stage 4 found had a genuine 16-minute data-completeness gap
(`ses_20260701-152030-CHAITANYA0BCF`), and this execution's remaining 89
internal transitions and 27 domain changes suggest real recorded
activity on both sides of the gap, not a missing-data artifact — but it
was not specifically re-audited against raw chunk boundaries here, so it
is reported as an observation, not confirmed as "a genuine long human
pause" with certainty.

## 3. Internal (`SAME_EXECUTION`) vs. true-boundary transitions — direct comparison

Reusing Stage 4's category scheme exactly (this is a *different*, narrower
cut than `time_gap_analysis.md`'s "interior vs. boundary-window" framing
— both are valid, not to be conflated). `n_same_execution=137,450`,
`n_true_boundary=1,671` (`EXIT_TO_DIFFERENT_EXEC` + `EXIT_TO_NOISE_BOUNDARY`).

| Feature | same-execution (median) | true-boundary (median) |
|---|---|---|
| `delta_t_ms` | 52 | 526 |
| `density_before` | 16 | 11 |
| `density_after` | 16 | 30 |
| `application_changed` rate | 1.72% | 1.97% |
| `window_title_changed` rate | 2.71% | 2.33% |
| `browser_domain_changed` rate | 29.19% | **86.12%** |
| `interaction_category_changed` rate | 52.43% | **97.49%** |
| `event_type_jaccard` (N=10) | 0.500 | **0.286** |
| `interaction_category_jaccard` (N=10) | 0.600 | **0.500** |

**OBSERVATION**: true boundaries are cleanly distinguishable from
same-execution transitions on `browser_domain_changed` (86% vs 29%),
`interaction_category_changed` (97% vs 52%), and both trajectory-jaccard
measures (clearly lower for true boundaries — context really does change).
`delta_t_ms` alone is directionally right (526 vs 52) but, per Stage 2,
overlaps heavily with the tail of same-execution gaps (p90 of
same-execution gaps is 1,147ms, already above the boundary median).

## 4. Are V1/V2's false internal boundaries isolated spikes, clustered, gap-associated, context-associated, or "return"-associated?

Both models' false-internal-boundary sets were re-derived by their own
established procedure and threshold (V1: 4,903 of 137,450 SAME_EXECUTION
transitions, 3.57%; V2: 5,870, 4.27% — consistent with V2's higher
overall fragmentation rate found in Stage 6/7).

**a. Isolated vs. clustered (OBSERVATION):**

| | V1 | V2 |
|---|---|---|
| Isolated (cluster size 1) | 4,691 (95.7%) | 5,614 (95.6%) |
| In a cluster of 2+ | 60 (1.2%, up to 60 executions affected) | 77 (1.3%) |

**The overwhelming majority of false internal boundaries are isolated,
single-transition spikes, not consecutive runs**, for both models. This
matters for reconstruction design: a simple "smooth over short runs of
predicted boundaries" heuristic would only ever address ~1.2-1.3% of the
false-positive volume — the fix has to work at the level of a single
mis-classified transition, evaluated against its neighborhood, not at
the level of merging adjacent flagged transitions.

**b. Gap association (OBSERVATION, confirms Stage 2 independently):**
flagged median `delta_t_ms` = 2,627 (V1) / 2,579 (V2) vs. 51/50 for
ordinary same-execution transitions — roughly **52x larger**. Consistent
with, and independently reproducing, Stage 2's finding.

**c. Context-change association (OBSERVATION):** `browser_domain_changed`
rate is 78.9% (V1) / 71.2% (V2) among flagged transitions vs. 27.4%/27.6%
among ordinary same-execution ones — nearly 3x enrichment. `interaction_category_changed`:
97.7% (V1) flagged vs. 50.8% ordinary.

**d. "Followed by return to previous trajectory/context" (OBSERVATION —
the central finding of this stage):** comparing N=10 trajectory-jaccard,
flagged vs. ordinary same-execution vs. true-boundary:

| | true boundary | V1 flagged | V1 ordinary | V2 flagged |
|---|---|---|---|---|
| `event_type_jaccard` median | **0.286** | 0.500 | 0.500 | 0.400 |
| `interaction_category_jaccard` median | **0.500** | 0.600 | 0.600 | 0.500 |
| `delta_t_ms` median (for contrast) | 526 | **2,627** | 51 | 2,579 |

**This is the quantitative answer to item 6's question.** On the single-
transition feature that actually drives the classifiers (gap size), V1's
false positives (median 2,627ms) look *more* boundary-like than real
boundaries (526ms) — consistent with Stage 2's "the model's confidence is
inverted" finding. But on the N=10 neighborhood evidence, V1's false
positives are statistically indistinguishable from ordinary same-execution
continuity (0.500 vs. 0.500) and clearly *unlike* genuine boundaries
(0.286) — V2's false positives sit slightly closer to boundary-like
(0.400) but still far above the true-boundary level. **The individual
transition and its neighborhood disagree about whether this is a
boundary; the neighborhood is the more reliable of the two by this
measure**, since it's the neighborhood value, not the single-transition
gap, that lines up with what genuine same-execution continuity actually
looks like.

**e. "Surrounded by otherwise continuous activity" (OBSERVATION, partial
support only):** density-before at the flagged transition, as a ratio to
that execution's own mean internal density-before: median ratio 0.78
(V1) / 0.71 (V2) — somewhat quieter than the execution's own average,
but **not dramatically so**, and the 75th percentile ratio is 1.14 (V1) —
meaning a full quarter of flagged transitions sit in an at-or-above-
average-density stretch. **This signal is real but weaker and less
uniform than the trajectory-jaccard finding above** — density alone is
not a reliable discriminator here.

## 5. Interruption-return patterns (A → B → A and general trajectories)

Detected via `detect_return_patterns()` on the `application` and
`browser_domain` fields, within each execution's own span.

| | count | % of 1,752 GT executions |
|---|---|---|
| Executions with ≥1 return-pattern instance | **884** | **50.5%** |
| Total return-pattern instances | 1,175 | — |

**Session-aware (OBSERVATION):** present in **every one of 63 sessions**
(0 sessions with zero) — per-session rate of executions containing a
return pattern: mean 50.4%, std 11.1%, range 16.2%–68.2%. Widespread, not
concentrated in a few sessions.

By field:

| | n instances | immediate A→B→A | general (A→B→C→A, …) | median "away" duration |
|---|---|---|---|---|
| `application` | 928 | 784 (84.5%) | 144 (15.5%) | 18.6s |
| `browser_domain` | 247 | 194 (78.5%) | 53 (21.5%) | 5.2s |

**Do V1/V2 falsely split at the leave or return moment of these patterns?
(OBSERVATION):**

| | V1 flags "leave" | V1 flags "return" | V2 flags "leave" | V2 flags "return" |
|---|---|---|---|---|
| `application` patterns | 16.3% | 5.6% | 39.4% | 10.8% |
| `browser_domain` patterns | 0.8% | 11.3% | 1.2% | 7.7% |

**OBSERVATION**: for application-based returns, both models are far more
likely to falsely flag the *leave* transition than the *return* — V2
especially (39.4% vs 10.8%). For browser-domain-based returns, the pattern
flips — the *return* is flagged more than the *leave* (domain changes are
too common on their own, per item 1's 29% base rate, to trigger a
boundary by themselves; something about re-entering a domain after time
away is more likely to co-occur with whatever else pushes the score over
threshold). **Representative example** (session
`ses_20260630-121953-LAPTOP-R36BQBTE`, case `LA-175009-004`): the user
leaves "Google Chrome" for 32.4 seconds and returns — **both V1 and V2
falsely split at the leave moment**, exactly the kind of error a
neighborhood-aware layer that recognizes the eventual return could
correct, since the return itself is *not* flagged by either model in
this example (the "back to A" moment looks unremarkable to both).

## 6. Local-neighborhood evidence vs. single-transition evidence — quantified

Directly established in §4d above and restated here as the stage's core
answer: **yes, a local N=10 neighborhood contains evidence the individual
transition's own features do not.** The clearest single number: V1's
false-internal-boundaries have a median single-transition gap (2,627ms)
*larger* than true boundaries' median gap (526ms) — the transition-level
evidence is actively misleading — while their median neighborhood
`event_type_jaccard` (0.500) exactly matches ordinary same-execution
continuity (0.500) and is far from true boundaries' (0.286). The
neighborhood evidence and the single-transition evidence point in
different directions for these specific transitions; only one of them
(the neighborhood) agrees with the GT-known answer.

## Files

- `src/procmine/segmentation/interruption_forensics.py`,
  `tests/test_interruption_forensics.py` (15 tests)
- `scripts/analyze_interruption_forensics.py`
- `reports/day2/interruption_forensics_dataset_a.json` (all aggregate
  findings above)
- `reports/day2/interruption_forensics_execution_profiles_dataset_a.json`
  (all 1,752 per-execution profiles)
- `reports/day2/interruption_forensics_return_patterns_dataset_a.json`
  (all 1,175 return-pattern instances)
- `reports/day2/interruption_forensics.md` — this file

## Recommendation for the reconstruction layer (concise, evidence-based)

1. **Use neighborhood trajectory-jaccard (N=10, `event_type` and
   `interaction_category`) as a correction signal, not just a
   classification feature.** §4d/§6 show it disagrees with the gap-driven
   single-transition prediction in exactly the direction needed to fix
   false internal boundaries, on the same population where V1/V2 err.
2. **Design for isolated single-transition corrections, not run-smoothing.**
   95.6-95.7% of false internal boundaries are isolated (§4a) — a
   reconstruction step that only merges *adjacent* flagged boundaries
   would leave the large majority of the problem untouched.
3. **Explicitly model "leave-and-return" as a first-class pattern.** Half
   of all GT executions (50.5%) contain at least one such pattern (§5),
   present in every session; both models mis-flag the *leave* transition
   of an application-based return far more than the *return* itself —
   a mechanism that looks forward for a plausible return before
   committing to a split at a "leave"-shaped transition is directly
   motivated by this asymmetry.
4. **Don't rely on density alone.** §4e shows the "surrounded by
   continuous activity" signal is real but weak and inconsistent — not a
   safe sole basis for a correction rule.
5. **Treat `browser_domain_changed` with caution as a standalone signal**
   inside a reconstruction rule: it fires on 29% of *all* ordinary
   same-execution transitions (§1) — common enough that using it alone
   would re-introduce a high false-positive rate, echoing Stage 2's
   original finding about the current classifiers.

This is a recommendation for Stage 9's design discussion, not a decision
made here — no reconstruction algorithm has been chosen or implemented.
