# Work-Thread Reconstruction — Research Analysis

**Verdict: RETAIN LOCKED BASELINE.** The work-thread hypothesis was experimentally
evaluated and **rejected at Step 5, before the graph was built**, because the
premise it depends on does not hold in this dataset. No canonical artifact changed.

**Artifacts:** `work_thread_signal_audit.md` · `work_thread_pairwise_experiment.json`
**Scripts:** `scripts/run_work_thread_pairwise_experiment.py`

Evidence labels used throughout: **OBSERVED** (measured), **INFERRED** (reasoned from
measurement), **EXPERIMENTAL** (this experiment's own result), **NOT VALIDATED**.

---

## 1. Motivation

The locked architecture makes an independent boundary decision at every transition.
That framing has a known weakness — 79.05% of ground-truth executions still contain a
spurious internal boundary. The work-thread hypothesis proposes a different shape:
recover hidden *threads* of related work from relationships between events, so
non-contiguous work is reassembled rather than split.

It is a genuinely better idea **if** two things are true: work is actually
non-contiguous, and the telemetry contains evidence that links two events as "same
work". Both were tested.

## 2. Existing baseline (untouched)

| Metric | Value |
|---|---:|
| Precision | 0.23584277 |
| Recall | 0.63554758 |
| **F1** | **0.3440233236151604** |
| Fragmentation | 79.05251% |
| Under-segmentation | 0.1412 |
| Over-segmentation | 1.6033 |
| TP / FP / FN | 1062 / 3441 / 609 |

Not modified at any point in this experiment.

## 3. Hypothesis

> Can execution recovery be improved by reconstructing hidden work threads from
> relationships between events, instead of making an independent boundary decision at
> every transition?

Decomposed into two falsifiable preconditions:

- **P1** — Dataset A contains non-contiguous / interleaved work for threads to recover.
- **P2** — The telemetry contains linking evidence that identifies "same work" across
  a gap, beyond what temporal proximity already provides.

**Both were tested. Both failed.**

## 4. Data availability audit (Step 1) — OBSERVED

Full detail in `work_thread_signal_audit.md`. All 162,768 events streamed.

| Signal the hypothesis needs | Coverage | Usable for linking? |
|---|---:|---|
| Entity identifiers (case / record ID) | **0%** | Not present |
| Clipboard content (copy→paste chains) | **0%** of 5,198 clipboard events | Metadata only; `source_action` populated **4 times** in the whole dataset |
| Extracted / screen text | **0.07%** (116 events) | No text to overlap |
| DOM element identifier | **0%** | Not present |
| `browser_domain` | 52.61% | Effectively **3 values** — 99.6% of domain-bearing events are three localhost ports |
| `tab_id` | 5.74% | **Exists but 37.8× too coarse** — median tab lifetime 1,197 s vs median execution 31.7 s |
| `window_title` | **99.61%** | Highest coverage, and **measured ineffective twice** (Day-1 lift 0.048; Day-4 lift 1.10, at/below chance) |
| Timestamp / application / event type | ~100% | Available — and already the locked model's inputs |

**INFERRED:** every signal capable of linking two events across a gap is absent or too
coarse. What remains is what the locked V1/V2 models already consume. This did not
settle the question — it produced a falsifiable prediction, tested in §7.

## 5. Activity representation (Step 2) — decision

**Raw event, with a bounded temporal neighbourhood.**

A "normalised activity" node was considered and rejected: with no entity, no text and
no usable thread identifier, normalisation could only be over
`(application, event_type, domain)` — all of which are already fields on the raw
event. The abstraction would carry no information the raw event does not, while adding
a second segmentation decision (how to form the activity) *inside* the method meant to
test segmentation. Session, ordering, event type, application, browser and window
context are all preserved.

## 6. Same-work evidence (Step 3)

14 interpretable pairwise features, **no hand-assigned weights** — all weighting is
learned in §7:

`log1p_delta_t_ms`, `index_gap`, `same_application`, `same_window_title`,
`same_browser_domain`, `both_domains_known`, `same_tab_id`, `both_tabs_known`,
`same_event_type`, `same_chunk`, `n_app_switches_between`, `n_distinct_apps_between`,
`any_navigation_between`, `any_clipboard_between`.

Text, clipboard-content and entity features were **not implemented**, because §4 shows
there is no data to compute them from. Implementing them against empty columns would
have manufactured the appearance of a richer experiment.

## 7. Pairwise model (Steps 4–5) — EXPERIMENTAL

**Setup.** 162,768 events → **378,000 pairs** across 63 sessions, gaps sampled
log-spaced over 1…600 events. Labels from GT `case_id`. **GroupKFold(5) grouped by
session.** No GT-derived value is a feature. Seed 0.

> **A parameter error I made and corrected, because it changes the reading.** The first
> run used a dense 20-event window. It produced a positive rate of **0.89** and only
> **33** intervening-work pairs out of 378,000 — a task so easy that the resulting
> ROC-AUC of 0.9749 said nothing about linking ability, only that neighbouring events
> are usually the same work. Re-run log-spaced to 600, the positive rate falls to
> **0.5589** and the task becomes informative. The first run is reported here rather
> than discarded because the correction is the point.

**Overall (random forest):** ROC-AUC **0.9897**, PR-AUC 0.9906, F1 0.9604.
Taken alone this looks like a resounding success. Stratified, it is not.

### Performance collapses exactly where linking would matter

| Index gap | n | Positive rate | ROC-AUC | PR-AUC | F1 |
|---|---:|---:|---:|---:|---:|
| 1–3 (adjacent) | 57,507 | 0.980 | 0.9749 | 0.9990 | **0.9957** |
| 4–20 | 113,620 | 0.909 | 0.9759 | 0.9960 | 0.9831 |
| 21–100 | 104,116 | 0.487 | 0.9502 | 0.9499 | 0.8815 |
| **101–600** | 102,757 | 0.009 | 0.8426 | **0.4250** | **0.4657** |

| Time gap | n | Positive rate | PR-AUC | F1 |
|---|---:|---:|---:|---:|
| <1 s | 76,142 | 0.980 | 0.9997 | 0.9974 |
| 1–5 s | 74,981 | 0.945 | 0.9967 | 0.9878 |
| 5–30 s | 97,487 | 0.597 | 0.9678 | 0.9151 |
| **>30 s** | 129,390 | 0.059 | 0.7145 | **0.6715** |

At short range the model scores ~0.99 — but the positive rate is already 0.98, so
"same work" and "adjacent in time" are nearly the same claim and the model adds almost
nothing. At long range, where a thread model would have to earn its value, F1 falls to
**0.4657**.

### What the model is actually using — the decisive number

| Feature | Importance |
|---|---:|
| `log1p_delta_t_ms` | 0.2991 |
| `n_app_switches_between` | 0.2608 |
| `index_gap` | 0.2303 |
| `any_navigation_between` | 0.1100 |
| `any_clipboard_between` | 0.0388 |
| `same_window_title` | 0.0366 |
| `same_event_type` | 0.0089 |
| `same_browser_domain` | 0.0067 |
| `same_tab_id`, `same_application`, others | ≈0 |

**Temporal / positional features: 90.0% of importance. Linking signals: 5.0%.**

> **Read this alongside §25.3.** Feature importance is a model-specific diagnostic, and
> a later ablation showed this framing **overstates** the case: linking features *alone*
> reach ROC-AUC 0.7651, so they are not negligible — they are largely *redundant* with
> temporal structure. The conclusion survives; the reason is redundancy, not absence.

**INFERRED:** the pairwise model is a temporal-proximity model wearing different
clothes. It re-derives, from a graph-shaped framing, the same evidence the locked
per-transition model already uses — which is precisely why it cannot beat it.
**P2 is rejected.**

## 8. A→B→A analysis (Step 8) — OBSERVED, and the finding that ends the experiment

Interleaving was measured directly on GT spans across all 63 sessions:

```
closed GT executions                                     1752
executions overlapping or nested with a DIFFERENT case      0   (0.00%)
sessions containing any such overlap                        0   of 63
case_id reappearing after a different case intervened       0   across all sessions
```

**Dataset-A ground truth contains no interleaved work at all.** Executions are
strictly sequential and non-overlapping.

This is independently confirmed by the pairwise experiment: of 378,000 pairs, **86,722
have intervening different work, and that stratum is single-class** — every one is
label 0. That is logically necessary given strict sequencing: if different work
intervenes between two events, they cannot belong to the same execution. There is no
A→B→A signature to recover, and therefore **no measurement of A→B→A capability is
possible on this dataset.**

It also confirms Day 2's finding from a different angle. Day 2 looked for a `case_id`
reappearing after an intervening case and found 0 of 63 sessions; this measures span
overlap and nesting and finds 0 of 1,752 executions. Two different tests, same answer.

**P1 is rejected.** No success case was manufactured, and none exists to find.

## 9–12. Graph, thread recovery, fragment merging, confidence — NOT BUILT, deliberately

Step 6 is gated on the pairwise experiment being understood. It is, and it says:

1. The edges such a graph would carry are **90% temporal** (§7).
2. The structure the graph exists to recover — non-contiguous threads — **occurs zero
   times** (§8).

A graph built on temporal edges over strictly sequential work would reproduce temporal
segmentation, which Day 2 already measured (F1 0.173 temporal-only, 0.182 with context)
and Day 7's rule candidates re-measured from another direction. Building it would cost
significant implementation time to confirm a predictable result.

This is the same judgement Day 6 applied when it declined to run an LLM boundary
second opinion after the HMM result, and Day 2 applied when it declined to build the
dynamic-programming optimiser after the feasibility study failed its gate. **Recording
the reasoning is more honest than spending the budget to produce a foregone number.**

**NOT VALIDATED:** no work-thread segmentation exists, so there are no candidate
boundary metrics, no per-session robustness for a candidate, and no ablation over a
working system. §14 states the consequences precisely rather than filling those
sections with material this experiment did not produce.

## 13. Evaluation methodology (Step 10)

Defined in advance, and unused because no candidate reached evaluation:

- **Level 1 — boundary:** precision = TP/(TP+FP), recall = TP/(TP+FN), F1 = harmonic
  mean, over transitions, scored with the locked `boundary_metrics`.
- **Level 2 — execution:** over-segmentation = Σ max(overlaps(e)−1, 0) / |E|;
  under-segmentation = Σ max(overlaps(s)−1, 0) / |S_overlapping|; fragmentation =
  |{e : overlaps(e) > 1}| / |E|, scored with the locked `execution_metrics`.

Reusing the locked evaluator was the plan throughout, so any candidate would have been
directly comparable rather than merely similar.

## 14. Promotion criteria (Step 11) — registered, then not reached

Registered before any candidate was produced:

| Gate | Threshold |
|---|---|
| Boundary F1 | must not materially decrease vs 0.3440 |
| Recall | ≥ 0.55 |
| Fragmentation | must improve materially below 79.05% |
| Under-segmentation | ≤ 2× baseline (0.2823) |
| Over-segmentation | ≤ 1.25× baseline (2.0041) |
| Sessions degraded | ≤ 40% of 63 |
| Concentration | gain must survive removing the 3 most-improved sessions |
| Safety | no merging of unrelated GT executions |

**No candidate was produced, so no gate was evaluated.** The hypothesis was rejected on
its preconditions, which is a stronger rejection than failing the gates would have
been: a candidate that failed the gates would still leave open "maybe a better
candidate exists". P1 and P2 failing closes that door for this dataset.

## 15. Results summary

| Precondition | Test | Result |
|---|---|---|
| **P1** — non-contiguous work exists | GT span overlap / nesting / case reuse, 1,752 executions | **0 occurrences. Rejected.** |
| **P2** — linking evidence exists | Signal audit (162,768 events) + pairwise model (378,000 pairs) | Linking features = **5.0%** of importance; long-range F1 **0.4657**. **Rejected.** |

## 16. Day-7 comparison (Step 12)

| System | F1 | Recall | Fragmentation | Under-seg |
|---|---:|---:|---:|---:|
| **Locked baseline** | **0.3440** | **0.6355** | 79.05% | **0.1412** |
| C1 two-threshold rule | 0.2245 | 0.3160 | 66.50% | 0.3893 |
| C2 rule + continuity veto | 0.2822 | 0.2980 | 40.87% | 0.6606 |
| C3 rule + motif | 0.2493 | 0.2998 | 54.45% | 0.4976 |
| C4 instrumentation-aware | 0.2256 | 0.3148 | 65.58% | 0.3959 |
| **Work-thread** | — | — | — | — (no candidate produced) |

**Does the work-thread approach escape the fragmentation ↓ / under-segmentation ↑
trade-off the rule candidates found? The question cannot be answered empirically,
because no candidate was built — and the reason it was not built is more fundamental
than the trade-off.** The rule candidates at least occupied points on the curve. The
work-thread method never reaches the curve, because the structure it exploits
(non-contiguous work) is absent and the evidence it needs (linking signals) is 5% of
what the model actually uses.

**INFERRED:** had it been built, it would most likely have landed on the same curve,
since its edges are 90% temporal and Day 2 already measured temporal-only segmentation
at F1 0.173–0.182. That is an inference, and it is labelled as one.

## 17. Instrumentation analysis (Step 13)

Thresholds untouched: `MIN_DISTINCT_BROWSER_DOMAINS = 2`,
`MIN_BROWSER_DOMAIN_COVERAGE = 0.40`.

The audit's domain finding explains *why* the diagnostic works and why it cannot help
here. Browser domain is effectively 3-valued, so a session with <2 distinct domains has
no observable domain change — which is exactly what the Day-4 diagnostic detects. But
for **linking**, 3 values across 85,633 events is far too coarse: two events sharing
`127.0.0.1:5122` share an internal system, not a unit of work.

**No healthy-vs-degraded comparison of a candidate was run**, because no candidate
exists. Reporting one would mean inventing it.

## 18. Robustness (Step 14)

Not applicable — no candidate segmentation was produced, so there are no improved /
unchanged / degraded session counts and no worst-session delta. The one robustness
statement this experiment *can* make is about its own model: session-grouped
GroupKFold across all 63 sessions, with no session in both train and test, and the
stratified collapse in §7 is present across the whole pooled set rather than driven by
any subset. **LAPTOP-R36BQBTE did not determine any conclusion here**, because no
conclusion rests on per-session performance.

## 19. Ablation (Step 15)

Not run as a separate sweep — the random-forest feature importance in §7 answers the
same question directly and more cheaply: temporal/positional 90.0%, linking 5.0%. An
ablation that removed the linking features would move overall F1 by a fraction of a
percent, which is a predictable result rather than an informative one.

## 20. Computational cost (Step 16) — OBSERVED

| Stage | Cost |
|---|---:|
| Events processed | 162,768 |
| Pairs constructed | 378,000 |
| Pair construction (all 63 sessions) | **11.9 s** |
| Logistic regression, mean fold fit | 0.93 s |
| Random forest (200 trees), mean fold fit | 11.53 s |
| Neighbourhood | log-spaced, bounded to 600 events, **session-local** |

No all-pairs graph was constructed. Complexity is O(N × G) with G = 24 sampled gaps,
not O(N²) — 378k pairs rather than the ~1.3 × 10¹⁰ an all-pairs construction over
162,768 events would require.

## 21. Dataset B sanity check (Step 17)

**Not performed** — correctly. It is gated on passing the Dataset-A promotion gate,
which was never reached. Dataset B was not read, not tuned on, and not touched.

Downstream remains exactly as it was: HR/Payroll, 122 executions, 94 dominant-path,
77.05%, Opportunity 0.4401.

## 22. Decision

**RETAIN LOCKED BASELINE.**

The work-thread hypothesis was experimentally evaluated but did not satisfy the
pre-registered promotion gate — it did not reach it, because both of its preconditions
were measured and rejected. The locked baseline therefore remains canonical.

**This is not a failure.** It is a scientifically justified rejection, and it is worth
more than a weak improvement claim would have been. The hypothesis was a good one: it
targets the project's real weakness (79.05% fragmentation) with a structurally
different idea. The evidence simply says that in *this* telemetry, the structure it
depends on is not there.

The experiment also produced a finding that outlives it: **Dataset-A ground truth
contains zero interleaved work.** Any future method premised on recovering
non-contiguous threads can be rejected against this dataset without being built.

## 23. Limitations

- **Single dataset.** Zero interleaving is a property of Dataset A as recorded. A
  production log with genuine multitasking could behave completely differently, and
  the hypothesis would deserve re-testing there.
- **GT is a reference, not an oracle.** Day 1 found a cross-file disagreement and an
  abandoned execution. If GT under-records interleaving — for instance by recording a
  resumed execution as a second case — the zero-interleaving result would be an
  artifact of the recording convention rather than of the work. This cannot be
  distinguished from the data available, and it is the single most important caveat on
  this experiment.
- **Neighbourhood bounded at 600 events.** Links beyond that range were not tested.
- **No graph was built**, so the inference in §16 about where it would land is an
  inference, not a measurement.
- **Feature set is what the data supports**, not what the hypothesis wanted.

## 24. Future experiment

Only what the evidence supports:

1. **Re-test on a dataset with recorded interleaving.** This is the only way the
   hypothesis gets a fair trial. The measurement to run first is §8's — if a new
   dataset also shows zero interleaving, stop there.
2. **Ask whether the GT convention hides resumption.** If a resumed execution is
   recorded as a new `case_id`, interleaving would be invisible by construction. This
   is a question for whoever produced the dataset, not an analysis that can be run.
3. **Fix instrumentation before methods** — unchanged from Day 4 and Day 7. Six of the
   seven worst sessions sit at 0.00% browser-domain coverage.
4. **Supervised per-transition classification with explicit class weighting** remains
   the most promising untried direction, and is unaffected by this result.

---

# 25. Final Scientific Closure

A closure audit was run to re-verify the rejection independently rather than let it
rest on one implementation. **Artifact:** `work_thread_closure_audit.json`.
**Script:** `scripts/run_work_thread_closure_audit.py`.

## 25.1 P1 — re-verified by two further methods

The original check compared execution spans pairwise. The audit deliberately avoids
reusing that logic and applies two unrelated techniques:

- **Sweep line** over boundary points. Ends are processed before starts at equal
  timestamps, so two executions that merely touch are counted as adjacent, not
  concurrent. If concurrency ever exceeds 1, two executions were live at once.
- **Run-length analysis** of the per-event case assignment. Consecutive identical
  labels collapse into runs; a `case_id` appearing in more than one run was left and
  returned to — the A→B→A signature. Unlabelled events are dropped rather than treated
  as separators, so an idle pause inside one execution cannot fake a return.

| Measure | Result |
|---|---:|
| Total GT executions analysed | **1,752** |
| Sessions analysed | **63** |
| **Max simultaneous executions anywhere** | **1** |
| Executions with overlap | **0** |
| Executions nested inside another | **0** |
| Sessions affected | **0** |
| **Observable A→B→A cases** | **0** |
| Observable non-contiguous cases | **0** |

**Three independent methods now agree on zero** — pairwise span comparison,
sweep-line concurrency, and run-length return detection.

> **Dataset A, under its recorded execution identity convention, provides no positive
> examples from which to validate interleaved work-thread reconstruction.**

This is a statement about *this dataset as recorded*. It is **not** a claim about real
user behaviour, and §25.6 keeps the alternative explanation open.

## 25.2 The intervening-work stratum — verified, not asserted

| | |
|---|---:|
| Intervening-work pairs | **86,722** |
| …labelled *same execution* | **0** |
| …labelled *different execution* | **86,722** |
| Non-intervening pairs | 291,278 (positive rate 0.7253) |

Perfectly single-class, as predicted. **Why this follows from the convention:** GT
executions are recorded as non-overlapping intervals, so if any event between *i* and
*j* carries a different `case_id`, then *i* and *j* lie in different intervals by
construction. The label is therefore determined by the encoding, not learned from
behaviour — which is exactly why it cannot be used as evidence that users do not
interleave work.

## 25.3 Feature-group ablation — and a correction to §7

Feature importance is a model-specific diagnostic. The stronger test is whether a
model trained on temporal features alone matches the combined model. Same pairs, same
session-grouped validation, threshold fixed at 0.5 (not tuned).

| Group | Features | ROC-AUC | PR-AUC | Precision | Recall | **F1** |
|---|---:|---:|---:|---:|---:|---:|
| **A** temporal / positional only | 6 | 0.9802 | 0.9823 | 0.9324 | 0.9300 | **0.9312** |
| **B** linking / context only | 8 | 0.7651 | 0.7821 | 0.7603 | 0.7395 | **0.7498** |
| **C** combined | 14 | 0.9897 | 0.9906 | 0.9624 | 0.9585 | **0.9604** |

**Combined − temporal: F1 +0.0292, ROC-AUC +0.0095, PR-AUC +0.0083.**

> **This partially corrects §7, and the correction is recorded rather than smoothed
> over.** §7 reported feature importance as "temporal 90.0% / linking 5.0%", which
> reads as though linking evidence is nearly worthless. The ablation says otherwise:
> linking features **alone** reach ROC-AUC **0.7651**, far above chance. Permutation-free
> tree importance measures *marginal* contribution in the presence of strongly
> correlated temporal features, and therefore **understates** how much standalone
> signal a redundant feature group carries.

The accurate statement is not "linking evidence is negligible" but:

- linking evidence carries **real but substantially weaker** signal than temporal
  (0.7651 vs 0.9802 ROC-AUC alone);
- it is **largely redundant** with temporal structure — adding all 8 linking features
  to the 6 temporal ones improves F1 by **+0.029**;
- **temporal/positional structure alone recovers 96.96%** of the combined model's F1
  (0.9312 / 0.9604).

The conclusion is unchanged, and now rests on the stronger test: a graph built on this
evidence would be dominated by temporal structure. But the *reason* is redundancy, not
absence, and the report should say so.

## 25.4 The parameter-error lesson — preserved

| Run | Window | Pairs | Positive rate | Intervening pairs | Overall ROC-AUC |
|---|---|---:|---:|---:|---:|
| **First** | dense, 20 events | 378,000 | **0.89** | **33** | 0.9749 |
| **Corrected** | log-spaced to 600 | 378,000 | **0.5589** | 86,722 | 0.9897 |

The first run is **not deleted**. Its ROC-AUC of 0.9749 looked like a strong positive
result and was rejected because the stratum that mattered — pairs with intervening
different work — contained **33 samples out of 378,000**, far too few to support any
claim about linking across a boundary. A 0.89 positive rate also meant the classifier
was mostly being asked "are these two adjacent events the same work?", to which the
answer is nearly always yes.

This is a useful example of validation catching an attractive but unsupported result:
the headline number improved when the experiment was made *harder*, which is the
opposite of what a result-chasing process would produce.

## 25.5 Why graph construction was stopped — the technical argument

If (a) Dataset-A GT execution identities are **strictly sequential** — max concurrency
1, zero returns across 1,752 executions — and (b) the strongest pairwise evidence is
**temporal/positional**, with temporal-only recovering 96.96% of combined F1 and
linking-only reaching 0.7651, then a graph whose dominant edges are temporal would
**primarily reproduce temporal continuity segmentation** rather than recover hidden
parallel work threads.

There are no hidden parallel threads in this dataset to recover — that is measured,
not assumed. And temporal continuity segmentation is already characterised: Day 2
measured it at F1 0.173 (temporal-only) and 0.182 (temporal AND context change), both
well below the locked 0.3440.

**This is an engineering stop condition, not an implementation failure.** The
experiment reached a point where the next step's outcome was determined by evidence
already in hand, and the correct action was to record that rather than spend the
budget confirming it.

## 25.6 Dataset-convention limitation — the honest alternative

Two statements must be kept apart, and only the first is established:

| Statement | Status |
|---|---|
| "There is no **observed** interleaving in Dataset A." | **OBSERVED** — three independent methods, zero cases |
| "The dataset **encoding may make** interleaving unobservable." | **OPEN** — cannot be excluded |
| "Users never interleave work." | **NOT CLAIMED, and not supported** |

If the recording convention assigns a resumed execution a **new** `case_id`, then a
genuine leave-and-return would appear in the data as two adjacent, separate, strictly
sequential executions — indistinguishable from two unrelated pieces of work. Under that
convention, interleaving is invisible **by construction**, and every zero in §25.1
would be an artifact of the encoding rather than a property of the behaviour.

Day 2 found supporting circumstantial evidence for exactly this concern: the one known
suspend/resume example (`M1-B-split-1`) has `split_id` populated on only the later
phase, with no paired earlier record. That is what a convention which does not preserve
case continuity across a resumption would look like.

This cannot be resolved from the data available. It is a question for whoever produced
the dataset, and it is the single most important caveat on this entire experiment.

## 25.7 Final decision table

| Question | Evidence | Decision |
|---|---|---|
| Does Dataset A contain observable interleaved work? | **0 of 1,752** executions; max concurrency **1**; **0** A→B→A; 3 independent methods | **No validation basis** |
| Do linking signals dominate temporal signals? | Temporal-only F1 **0.9312** vs linking-only **0.7498**; combined **0.9604** (+0.029) | **No** — linking is real but largely redundant |
| Does a graph have validated structure to recover? | No interleaving; edges would be temporal-dominated | **Do not build** |
| Can the work-thread idea transfer to Dataset B? | Dataset B has no ground truth; no validation basis | **Do not test** |
| Should canonical segmentation change? | Promotion gate never reached; preconditions failed | **Retain baseline** |

## 25.8 Conclusion

The work-thread hypothesis was investigated as an alternative abstraction for
execution reconstruction. Dataset A did not contain observable interleaving examples,
and the available linking/context evidence contributed little beyond temporal
structure. Therefore there was insufficient empirical basis to construct and validate
a work graph. The hypothesis is retained as a future research direction for datasets
with genuine interleaving/case continuity evidence, but it is not promoted into the
canonical pipeline.

**Canonical segmentation is unchanged: F1 0.3440233236151604.**
