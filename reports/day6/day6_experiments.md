# Day 6 — Sequence models, ensembles, clustering and LLM labelling

Four experiments, run against the locked Dataset-A baseline. Three were
rejected; one is kept in a narrow role. The locked segmentation pipeline was
**not modified** — `reconstruction.py` and `protected_boundary.py` were
imported and used unchanged, and the Day-2 baseline artifact was never
overwritten.

Scripts: `run_hmm_boundary_experiment.py`,
`run_boundary_ensemble_experiment.py`,
`run_segment_clustering_experiment.py`, `build_llm_labeling_inputs.py`,
`record_llm_labeling_results.py`.
Module: `src/procmine/experiments/hmm_boundary.py`.
Tests: `tests/test_hmm_boundary.py` (17).

---

## 0. The limitation that motivated the day

The locked detector scores each transition largely independently, but a
process boundary is a sequential phenomenon: whether a transition ends a unit
of work depends on the activity mode before and after it. That is a real
structural limitation, and it is the reason to test a sequence model rather
than another threshold.

A neural sequence model (BiLSTM-CRF) was ruled out before implementation:
Dataset A has 63 sessions, which is far too little to learn transferable
boundary semantics for a Dataset B drawn from different departments,
applications and environments. An HMM is the honest middle ground —
sequence-aware, fittable per session, and interpretable.

## 1. Reproduction check (prerequisite)

Before any comparison, the locked Combined predictions were reproduced from
the locked modules and checked against the Day-2 artifact:

```
reproduced pooled F1 = 0.344023
locked     pooled F1 = 0.344023      max abs drift < 1e-9   -> MATCH
```

The ensemble script aborts if this drifts. Every number below sits on a
verified reproduction.

**Locked baseline:** P 0.2358 · R 0.6355 · **F1 0.3440** · over-seg 1.6033 ·
under-seg 0.1412 · 79.05% fragmented · 4,503 predicted boundaries.

## 2. Phase 2–3 — HMM boundary detection

Diagonal-covariance Gaussian HMM, Baum-Welch, Viterbi, fitted **per session,
unsupervised** on the same 9-dimensional per-transition vector the locked V1
model uses. A change of latent state is taken as a candidate boundary. The
state count was **swept, not tuned**; every value is reported.

| K | Precision | Recall | F1 | % transitions flagged | over-seg | under-seg | runtime |
|---:|---:|---:|---:|---:|---:|---:|---:|
| **2** | 0.0101 | 0.2220 | **0.0194** | 22.5% | 14.836 | 0.042 | 49 s |
| 3 | 0.0065 | 0.2142 | 0.0126 | 34.0% | 19.807 | 0.032 | 65 s |
| 4 | 0.0073 | 0.2603 | 0.0141 | 36.8% | 20.602 | 0.029 | 99 s |
| 5 | 0.0054 | 0.2208 | 0.0106 | 41.7% | 22.469 | 0.028 | 95 s |
| 6 | 0.0047 | 0.2047 | 0.0092 | 44.6% | 23.295 | 0.028 | 104 s |
| 8 | 0.0054 | 0.2454 | 0.0105 | 46.9% | 23.087 | 0.026 | 135 s |
| **locked baseline** | **0.2358** | **0.6355** | **0.3440** | 2.8% | 1.6033 | 0.1412 | — |

**Best HMM (K=2) F1 0.0194 versus baseline 0.3440 — roughly 18× worse.**

The mechanism is visible rather than mysterious. Ground-truth boundaries are
about **1.03%** of transitions. The HMM flags **22.5–46.9%**. An unsupervised
sequence model has no way to learn that boundaries are rare — it segments
wherever the observation distribution shifts, and in desktop logs that shifts
constantly. Over-segmentation is 9–15× the baseline's, and 98.3–98.9% of GT
executions end up fragmented.

The flagging rate is monotonic in K: more states → more state changes → more
flagged transitions (22.5% at K=2 rising to 46.9% at K=8; 36,631 to 76,339
predictions against the baseline's 4,503). Precision itself is *not*
monotonic — 0.0101, 0.0065, 0.0073, 0.0054, 0.0047, 0.0054 — so adding states
is not a clean one-way degradation. But the best result is the *fewest*
states, and even that is not close. There is no state count at which this
becomes competitive, which is exactly why sweeping mattered more than
picking.

**Decision: REJECT.** The decision rule required a meaningful F1 improvement
without unacceptable over-segmentation. It failed both by a wide margin.

## 3. Phase 4 — change-point comparison

Not rebuilt. Day 2 already recorded change-point-style baselines on the same
data and the same metric definitions: a temporal-threshold rule peaked at
**F1 0.173**, and adding a contextual-change requirement reached **F1 0.182**.
Both are well below the locked 0.3440 and well above the HMM's 0.0194.
Building an independent PELT implementation would have added an algorithm
without adding a decision, so it was skipped deliberately.

## 4. Phase 5 — complementarity and ensemble

An ensemble only helps if the components fail differently, so complementarity
was measured before any ensemble was accepted.

Of the 1,671 GT boundaries:

| | count |
|---|---:|
| caught by both | 214 |
| caught by baseline only | 848 |
| **caught by HMM only** | **157** |
| missed by both | 452 |

So the HMM genuinely does carry some complementary signal — 157 boundaries
the locked detector misses. The question is what they cost.

| System | Precision | Recall | F1 | predicted boundaries |
|---|---:|---:|---:|---:|
| Locked Combined (reproduced) | 0.2358 | 0.6355 | **0.3440** | 4,503 |
| HMM only | 0.0101 | 0.2220 | 0.0194 | 36,631 |
| Ensemble — AND (both agree) | 0.1809 | 0.1281 | 0.1500 | 1,183 |
| Ensemble — OR (either flags) | 0.0305 | 0.7295 | 0.0586 | 39,951 |

**OR** does recover those 157 boundaries — recall rises 0.6355 → 0.7295 — but
it costs **35,448 extra predictions to gain 157 true positives — 35,291 of
those additions are false, about 225 false positives per additional boundary
found.** F1 collapses to 0.0586.

**AND** is the more interesting failure. Requiring both detectors to agree
*lowers* precision, 0.2358 → 0.1809. Where the HMM agrees with the baseline,
the baseline is **less** likely to be right than when it acts alone. The
HMM's agreement is not merely weak evidence; it is mildly anti-correlated
with correctness, so it cannot serve as a filter either.

**Decision: REJECT.** Complementarity existed and was still not enough —
which is the outcome worth recording, because "the signals differ" is often
assumed to imply "the ensemble helps".

## 5. Phase 6 — segment-level clustering (HDBSCAN)

Clustering answers the *labelling* question, not the segmentation one, so no
boundary was altered: the 645 validated Dataset-B executions were consumed as
given. `sklearn.cluster.HDBSCAN` was used — no new dependency.

**Avoiding a circular test:** `dominant_context` (the Day-3 process label) is
itself derived from the systems an execution touches. Clustering on system
identity would recover the labels trivially. The primary feature set is
therefore **behavioural only** — duration, event count, step count, number of
distinct systems (a count, never an identity), and interaction-category and
event-type distributions. A second variant includes system identity purely to
make the circularity visible.

| min_cluster_size | clusters | noise | ARI vs Day-3 | NMI vs Day-3 |
|---:|---:|---:|---:|---:|
| **Behavioural only (33 features)** | | | | |
| 5 | 36 | 27.0% | 0.158 | 0.511 |
| 10 | 10 | 36.9% | **0.264** | 0.532 |
| 15 | 7 | 40.5% | 0.258 | 0.521 |
| 20 | 5 | 35.7% | 0.258 | 0.493 |
| **With system identity — circular (46 features)** | | | | |
| 10 | 13 | 32.9% | 0.653 | 0.784 |
| 20 | 8 | 40.6% | **0.661** | 0.792 |

Two findings:

1. **Behaviour alone does not identify the process.** ARI 0.26 is weak
   agreement. How long an execution takes, how many events it contains and
   which interaction categories it uses do **not** tell you which business
   process it is. In this data, process identity comes from *which system you
   are in*, not from *how you behave inside it*. That is a genuinely useful
   thing to know, and it is the strongest argument for the Day-3 approach of
   grouping on system context.
2. **Even the circular variant only reaches ARI 0.661**, while discarding
   31–41% of executions as noise. The Day-3 exact-match grouping assigns
   every execution a process; HDBSCAN drops a third and still agrees only
   moderately with a grouping whose answer it was effectively given.

**Decision: REJECT for the pipeline.** Keep the finding, not the method.

## 6. Phase 7 — LLM semantic labelling

The only experiment that produced value. Compressed per-process summaries
(**no raw event stream, no screenshots**) were built by
`build_llm_labeling_inputs.py`, with the Day-3 `readable_name` **withheld** so
the label could not be read back. Labels came from Claude acting as this
session's assistant; no external API was called. Full input, output,
confidence, evidence and ambiguity are recorded in
`llm_labeling_results.json`.

| Process id (Japanese) | LLM label (name withheld) | Day-3 name | Agree |
|---|---|---|---|
| `system:財務会計システム` | Financial accounting system transaction entry and review | Financial Accounting System | yes |
| `system:HR人事給与システム` | HR/payroll record processing with reviewer comment entry | HR / Payroll System | yes |
| `system:受発注在庫管理システム` | Order and inventory management transaction handling | Order & Inventory Management System | yes |
| `app:…nyusha_checklist_shinsotsu_batch` | New-graduate onboarding checklist preparation in Word | Word: New-Employee Checklist (New-Graduate Batch) | yes |
| `app:…keiyaku_kaijo_tetsuzuki` | Contract termination procedure document handling in Word | Word: Contract Termination Procedure | yes |
| `app:…gyomu_itaku_kyuuyo_kitei` | Outsourcing compensation regulations document reference in Word | Word: Outsourcing Compensation Regulations | yes |

6 of 6 semantically consistent with names the model never saw. More
usefully, it added caveats the names do not carry:

- **HR/Payroll** — from the four Japanese UI placeholders alone it inferred
  four distinct sub-procedures, and flagged that
  「承認コメントまたは差戻し理由」("approval comment or reason for return") is a
  **judgement-bearing approval step**. That independently corroborates the
  Day-3 four-route finding from different evidence.
- **Contract Termination** — flagged as the least standardised of the six
  (7 variants, 44.8% dominant share), so "procedure" is not a fixed script.
- **Outsourcing Compensation Regulations** — flagged that "regulations"
  suggests a document being *consulted* rather than a transaction being
  *executed*, so treating it as a process execution may be a category error.
  Confidence lowered accordingly. This is a caveat worth carrying forward.

**Decision: KEEP, in a narrow role.** Analyst assistance for naming and
interpreting discovered groups — never as ground truth, never in the boundary
path, never on raw logs.

## 7. Benefit / complexity summary

| Method | Benefit | Complexity | Dataset-B transfer | Decision |
|---|---|---|---|---|
| HMM boundaries | strongly negative (F1 0.0194 vs 0.3440) | new model, state sweep, 49–135 s/run | would need refitting; no GT to validate | **REJECT** |
| Ensemble (AND / OR) | negative (0.1500 / 0.0586) | two detectors to maintain | worse | **REJECT** |
| HDBSCAN clustering | weak (ARI 0.264 behavioural) + drops 27–40% as noise | tuning, no dependency added | untested | **REJECT for pipeline; keep the finding** |
| LLM labelling | 6/6 agreement + caveats the names lack | prompt + recorded provenance; cost per call | good — reads Japanese directly | **KEEP as analyst assistance** |

## 8. Final selection

**Outcome D (with a rejection):** segmentation does not improve, so the
locked pipeline stands unchanged; the LLM is kept only for semantic
labelling. Nothing was adopted into the boundary path.

The simplest defensible system remains the Day-2 locked architecture. Three
more sophisticated methods were implemented, evaluated on ground truth, and
rejected on evidence rather than on taste.

## 9. Limitations

- The HMM uses the same 9 features as V1. A different observation
  representation might behave differently; that was not tested.
- Fitting is per session, so no cross-session structure is learned. A pooled
  or hierarchical HMM was not attempted.
- Only Gaussian emissions were tried; several inputs are boolean, and a
  discrete/mixed emission model might fit them better. Given the size of the
  gap (18×), this is unlikely to change the decision, but it is untested.
- HDBSCAN was swept only on `min_cluster_size`; other parameters were left at
  defaults.
- LLM labelling covered the **top 6 processes by execution count**, not all
  29, and agreement was judged by human reading, not an automatic metric.
- Phase 8 (LLM boundary second opinion) was **not run** — the HMM result
  already showed that a detector flagging far more than ~1% of transitions
  cannot compete, and an LLM proposing boundaries from compressed windows
  would face the same structural problem at higher cost.

## 10. For the final report

1. The locked segmentation architecture survived a genuine challenge from a
   sequence model, an ensemble and clustering — it was not merely left
   unexamined.
2. The binding constraint is **class imbalance**, not model sophistication.
   Boundaries are ~1% of transitions; unsupervised methods that segment on
   distribution shift cannot find that needle.
3. **Complementary signal is not sufficient signal** — 157 uniquely-caught
   boundaries still cost about 225 false positives each.
4. In this data, **process identity lives in system context, not in
   behaviour** (ARI 0.264 behavioural vs 0.661 with identity).
5. **LLMs are useful for semantic interpretation, not for boundary
   detection** — 6/6 label agreement from compressed evidence, plus caveats
   a human name does not carry.

## 11. Recommendation for the Day-7 final report

**Ship the locked architecture unchanged.** Day 6 tested it against a
sequence model, two ensembles and a clustering alternative; none of them beat
it, and three lost by a wide margin. That is now a measured result rather than
an untested assumption, and it is the single most defensible thing this day
produced.

The one adopted change is narrow: **keep the LLM as an analyst aid for
semantic labelling**, never in the boundary path. It reads the Japanese
identifiers directly, it agreed with 6 of 6 withheld Day-3 names, and it
surfaced three caveats the names themselves do not carry — most importantly
that the HR/Payroll process contains a **judgement-bearing approval step**
(「承認コメントまたは差戻し理由」), which independently corroborates the
Day-3 four-route finding and directly supports keeping a human review
checkpoint in the prototype.

Two framings worth carrying into the write-up, because they generalise beyond
this dataset:

- **The binding constraint is class imbalance, not model sophistication.**
  Boundaries are ~1% of transitions. Any unsupervised method that segments on
  distribution shift will over-fire by one to two orders of magnitude. This
  explains the HMM result, the OR-ensemble result, and — retrospectively —
  why the Day-2 single-threshold sweep capped out where it did. The way
  forward, if there were more time, is better *evidence* (see below), not a
  bigger model.
- **Complementary signal is not sufficient signal.** The HMM found 157
  boundaries the baseline missed, which is a real complementarity — and
  taking them costs ~225 false positives each. Measuring complementarity
  before building the ensemble is what turned a plausible idea into a
  decided one.

**What I would do next, given more time**, in priority order:

1. **Fix the instrumentation, not the model.** Day 4 showed 6 of the 7 worst
   Dataset-A sessions have 0.00% browser-domain coverage. Restoring that
   field is a configuration change with a larger expected effect than any
   model change tested today.
2. **Revisit supervision.** Every Day-6 method was unsupervised. Dataset A
   *has* labels; a supervised per-transition classifier with explicit class
   weighting is the obvious untried direction, and it addresses the binding
   constraint head-on rather than around it.
3. **Test discrete/mixed HMM emissions.** Several of the nine features are
   boolean and Gaussian emissions fit them poorly. I do not expect this to
   close an 18× gap, but the space is not exhausted and I would rather say so
   than imply it is.

**Honest limitations to state in the report**: the HMM was per-session and
unsupervised (not pooled, not hierarchical); PELT was cited from Day 2 rather
than reimplemented; clustering agreement was measured against a Day-3
grouping rather than ground truth, because **Dataset B has none**; only 6 of
29 processes were LLM-labelled; and semantic agreement was judged by reading,
not by an automatic metric.
