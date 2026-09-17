# Segmentation Improvement Analysis

**Decision: RETAIN LOCKED SEGMENTATION.** Four candidates were built, tuned with
session-level validation, and measured against the locked baseline. All four failed
the promotion criteria, which were registered before any candidate was scored.

**Artifact:** `reports/day7/segmentation_comparison.json`
**Script:** `scripts/run_segmentation_improvement_experiment.py`
**Module:** `src/procmine/experiments/rule_boundary.py`

---

## 1. Problem

Segmentation sits upstream of everything: executions → process discovery → metrics →
opportunity ranking → the automation proposal → the frontend → the final report. Its
boundary F1 is 0.3440 and 79.05% of ground-truth executions remain fragmented. Before
investing in any further downstream or presentation work, the right question was
whether that upstream weakness can be reduced.

The honest framing is not "make F1 go up". Day 2 already established that a method can
raise recall while producing so many internal boundaries that executions shatter. So
the question is whether a *better operating point* exists — not merely a different one.

There is also a second, quieter motivation. The locked architecture is a union of two
learned models, plus a four-rule reconstruction layer, plus a protection layer. That is
a lot of machinery for F1 0.3440. If a handful of explicit conditions match it, the
machinery is not earning its complexity and should be simplified. That possibility had
never been tested directly.

## 2. Locked baseline

| Metric | Value |
|---|---:|
| Boundary precision | 0.2358 |
| Boundary recall | 0.6355 |
| **Boundary F1** | **0.3440** |
| GT executions fragmented | 79.05% |
| Under-segmentation | 0.1412 |
| Over-segmentation | 1.6033 |
| TP / FP / FN | 1062 / 3441 / 609 |

Per-session F1: mean 0.3316, median 0.3516, min 0.0513, max 0.4330, stdev 0.0865.

The baseline was reproduced from the locked modules at the start of the run and
verified against `reports/day2/protected_boundary_experiment_dataset_a.json`
(`systems.Strategy_Combined`). **Drift: 0.0.** Every comparison below rests on an
exact reproduction.

> A note on that control, because it did its job. The first run reported a drift of
> 0.0906 and aborted. The reproduction was fine — my artifact lookup had grabbed the
> first block containing a `pooled` key, which is `V1` (F1 0.2534), not
> `Strategy_Combined`. Without the control I would have compared four candidates
> against the wrong baseline and drawn confident nonsense.

## 3. Engineering hypotheses

Ordered cheapest-first deliberately. Nothing more complex was attempted until the
simple things had been measured.

| # | Hypothesis | Why it was worth testing |
|---|---|---|
| **C1** | A two-threshold rule: `(context change AND gap > s) OR (gap > l)` | Maximum explainability at minimum implementation cost. If this matches the locked pipeline, the pipeline is over-built. |
| **C2** | C1 plus a demote-only continuity veto on N=10 event-type jaccard | Day-2 forensics found that neighbourhood trajectory evidence disagrees with the misleading single-gap signal in the right direction. This tests it as a primary rule rather than a correction layer. |
| **C3** | C1 where a *familiar* app hop does not count as a context change | Process-aware without being circular: a frequently repeated app transition (HR → Word → HR) is plausibly a motif *inside* a process, not a boundary. |
| **C4** | C1 with separate thresholds where browser-domain coverage is degraded | Day 4 proved some sessions carry almost no context evidence. This tests whether acknowledging that explicitly helps, rather than assuming it does. |

**`window_title_changed` was deliberately excluded** from the context definition. It is
the most tempting available signal, and it has been measured twice and rejected twice:
Day 1 put its boundary lift at 0.048, and Day 4 re-tested it as a fallback at lift 1.10
with alignment at or below chance (3.33% at boundaries vs 3.55% at non-boundaries).

**Not attempted, and why:** no neural sequence model (63 sessions cannot support a
transfer claim — Day 6 already rejected BiLSTM-CRF on that basis), no clustering
pipeline, no LLM in the boundary path. Day 6 measured an HMM at F1 0.0194 and an
HMM/baseline ensemble at ~225 false positives per additional true boundary. Repeating
that class of experiment would have added cost without adding a decision.

## 4. Experimental method

**Leave-one-session-out, with parameters fitted inside the fold.** For each held-out
session, the parameter set is chosen by pooled F1 over the other 62 sessions, then
applied to the held-out session. For C3 the motif set (frequent app pairs) is also
rebuilt from the 62 training sessions only. **No session's ground truth ever informs
its own prediction.**

The sweep is made affordable by precomputing per-session `(tp, fp, fn)` for every
parameter combination once; each fold is then a sum over counts rather than a re-scan
of 162,705 transitions.

Candidates are scored with the **locked evaluator** (`evaluate_boundary_set`), the same
`boundary_metrics` / `execution_metrics` / `segments_from_boundaries` calls the baseline
uses, so the numbers are directly comparable rather than merely similar.

Grid: small gap {250, 500, 1000, 2000, 3000, 5000} ms, large gap {5000, 10000, 20000,
30000, 60000, 120000} ms, veto {0.5, 0.6, 0.7, 0.8}, motif min-count {10, 50, 200},
coverage floor 0.40 (the Day-4 diagnostic threshold, reused not re-selected).

## 5. Promotion criteria — registered before scoring

Gates were derived from the **baseline's own distributions**, which were known before
any candidate existed.

| Gate | Threshold | Justification |
|---|---|---|
| F1 absolute gain | ≥ +0.02 | Per-session F1 has stdev 0.0865. A pooled gain under 0.02 is inside the variation this dataset already shows between sessions. |
| Recall floor | ≥ 0.55 | Day 2 measured that forcing fragmentation down collapses recall to ~0.15–0.21. A floor of 0.55 keeps a detector that still finds more true boundaries than it misses. |
| Fragmentation cap | ≤ 81.05% | Baseline + 2pp. Fragmentation motivated the entire Day-2 pivot; it may not get materially worse. |
| Under-segmentation cap | ≤ 0.2823 | 2× baseline. Beyond this the method is merging genuinely distinct executions — the failure the Day-2 success gate existed to catch. |
| Over-segmentation cap | ≤ 2.0041 | 1.25× baseline. |
| Sessions degraded | ≤ 40% | An aggregate gain that degrades most sessions is not an improvement to the method. |
| Concentration | gain must survive removing the 3 most-improved sessions | A gain carried by three sessions is an improvement to those sessions, not to the method. |

## 6. Results

| Candidate | F1 | ΔF1 | Recall | Frag % | Under-seg | Over-seg | Gates |
|---|---:|---:|---:|---:|---:|---:|:--|
| **baseline (locked)** | **0.3440** | — | **0.6355** | 79.05 | 0.1412 | 1.6033 | — |
| C1 two-threshold rule | 0.2245 | −0.1195 | 0.3160 | 66.50 | 0.3893 | 1.0411 | **fail** |
| C2 rule + continuity veto | 0.2822 | −0.0619 | 0.2980 | **40.87** | 0.6606 | 0.5325 | **fail** |
| C3 rule + motif | 0.2493 | −0.0948 | 0.2998 | 54.45 | 0.4976 | 0.7882 | **fail** |
| C4 instrumentation-aware | 0.2256 | −0.1184 | 0.3148 | 65.58 | 0.3959 | 1.0268 | **fail** |

Every candidate failed the same five gates: F1 gain, recall floor, under-segmentation
cap, degraded-session fraction, and concentration. Every candidate *passed* the
fragmentation and over-segmentation caps — which is precisely the trap, and §8 explains
why.

### The finding that actually matters

Sort the five systems by fragmentation:

| System | Fragmentation % | Under-segmentation |
|---|---:|---:|
| C2 | 40.87 | 0.6606 |
| C3 | 54.45 | 0.4976 |
| C4 | 65.58 | 0.3959 |
| C1 | 66.50 | 0.3893 |
| **baseline** | **79.05** | **0.1412** |

The ordering is **perfectly monotonic**. Every candidate that reduces fragmentation
increases under-segmentation by a corresponding amount. **The candidates did not find
a better operating point — they found different points on the same trade-off curve,
and the baseline's point has the best F1 on it.**

This independently reproduces, from a completely different direction, what Day 2's
threshold sweep found: fragmentation can be bought down, but only with recall, and the
price is merging distinct executions. Two unrelated experiments landing on the same
constraint is much stronger evidence than either alone.

## 7. Per-session robustness

| Candidate | Improved | Unchanged | Degraded | Mean session F1 | Worst session Δ |
|---|---:|---:|---:|---:|---:|
| baseline | — | — | — | 0.3316 | — |
| C1 | 6 | 2 | **55** | 0.2143 | −0.3227 |
| C2 | 11 | 4 | **48** | 0.2657 | −0.3144 |
| C3 | 5 | 2 | **56** | 0.2336 | — |
| C4 | 6 | 2 | **55** | 0.2140 | — |

Not one candidate degrades fewer than 48 of 63 sessions.

**Concentration check.** For C1 and C2 the (negative) pooled delta gets *worse* after
removing the three most-improved sessions — mean session F1 excluding the top 3 is
0.3354 → 0.2093 for C1 and 0.3326 → 0.2549 for C2. The few gains that exist are
concentrated, and the losses are not.

**Parameter stability was excellent, which matters.** LOSO selected
`small_gap_ms = 3000` in **63 of 63 folds** for every candidate, and
`large_gap_ms = 30000` in 60 of 63 for C1. These rules are *not* failing because they
overfit or because the search was unstable — they are stable, reproducible, and simply
worse. That is a cleaner negative result than a noisy one would have been.

**Machine and instrumentation concentration.** The improvements are not explained by
instrumentation health. Of the 8 sessions the Day-4 diagnostic flags as degraded, none
appears among the most-improved for C1 or C2; one degraded session
(`ses_20260630-125757-LAPTOP-R36BQBTE`) is among C2's five worst. Gains are spread
across MSI, yuvraj and SIDDHIGUPTAB00B sessions with no single machine dominating.

## 8. Failure mode analysis

**A. Over-segmentation** — every candidate *improves* it (1.6033 → 0.53–1.04). They
predict far fewer boundaries, so they split less.

**B. Under-segmentation** — every candidate badly worsens it (0.1412 → 0.39–0.66, i.e.
2.8× to 4.7×). This is the direct cost of the same under-prediction. **This is the gate
they all fail hardest**, and it is the failure that actually damages downstream
analysis: merged executions corrupt process counts and handling-time attribution in a
way that internal splits do not.

**C. Fragmentation** — every candidate improves it, C2 dramatically (79.05% → 40.87%).
Taken alone this looks like a major win. It is not: it is bought entirely by predicting
half as many boundaries.

**D. Merging** — the mirror of B, and the reason C2 must be rejected despite the
attractive fragmentation number. Recall falls 0.6355 → 0.2980, so more than two thirds
of real boundaries are missed and the executions on either side are joined.

**The single mechanism behind all four rows:** recall collapses from 0.6355 to roughly
0.30 in every candidate. A rule that fires on "context changed and the person paused"
simply does not fire at most real boundaries, because Day-2's forensics established
that genuine mid-task pauses (median 2,627 ms) are *longer* than typical real
boundaries (median 526 ms). The gap signal is not merely weak here — it is inverted on
the hard cases, and no threshold placement fixes an inverted signal.

## 9. Decision

**RETAIN LOCKED SEGMENTATION.** No candidate passed the promotion criteria. The locked
Combined strategy remains the canonical segmentation.

## 10. Why

1. **No candidate came close on F1.** The best was C2 at 0.2822 against 0.3440 — a
   deficit of 0.0619, three times the size of the +0.02 gate in the wrong direction.
2. **Recall collapsed in every candidate** (0.6355 → ~0.30), far below the 0.55 floor.
3. **Under-segmentation exploded in every candidate** (2.8×–4.7× baseline), which is
   the failure mode that most damages downstream process analysis.
4. **48–56 of 63 sessions degraded** in every candidate.
5. **The fragmentation improvements are not real improvements.** They move along a
   trade-off curve rather than beating it.

**And the result answers the second question too.** The locked architecture's extra
machinery *is* earning its complexity. A stable, well-tuned two-threshold rule reaches
F1 0.2245; the union-plus-reconstruction-plus-protection stack reaches 0.3440. That is
a 53% relative improvement attributable to the machinery, measured rather than assumed.
Before today that was an untested assumption about my own design.

**On hypothesis 4 specifically:** instrumentation-aware thresholds are rejected on
evidence. C4 selected a genuinely different threshold for degraded sessions
(`degraded_small_gap = 5000` vs `3000` healthy) in 63/63 folds, so the idea was given a
fair fitting — and it produced mean session F1 0.2140 against C1's 0.2143, i.e.
marginally *worse*. This is consistent with Day 4's own conclusion, reached
independently: the diagnostic identifies a data-capture problem, and the fix belongs
upstream in the capture configuration, not in the segmentation rules.

## 11. Downstream impact

**None. Nothing downstream was regenerated, and nothing should be.**

Segmentation did not change, so every downstream artifact remains valid and internally
consistent on the locked baseline:

- `reports/day3/process_executions_dataset_b.json` (645 executions) — unchanged
- `segments.jsonl` — unchanged
- process profiles, variants, DFG, step frequency — unchanged
- `reports/day3/problem2_audit_results.json` (HR Opportunity 0.4401) — unchanged
- HR dominant-path forensics and the automation prototype — unchanged
- `frontend/public/data/*` — unchanged
- Day-6 Decision Center evidence — still truthful, still pointing at the current
  execution population
- `reports/final_report.md` — its segmentation numbers remain correct

No canonical artifact was written by this experiment. Output is confined to
`reports/day7/`.

## 12. Limitations

- **Four rule families, not an exhaustive search.** A different rule shape could behave
  differently; this tests the cheap and obvious ones, not every possible one.
- **The grid is discrete.** Thresholds between grid points were not explored, though
  the 63/63 stability of the selected values suggests the optimum is not being missed
  by a narrow margin.
- **C3's motif definition is one of several possible.** App-pair frequency is the
  cheapest non-circular process signal; n-gram or DFG-edge motifs were not tested.
- **The candidates were tested standalone, not as additions to the locked pipeline.**
  It remains possible that the motif signal adds value *inside* the reconstruction
  layer rather than replacing it. That would be a different experiment with its own
  gates, and Day-2's Stage 8.4/8.5 work is the precedent for how to run it.
- **Ground truth remains evidence, not an oracle.** No candidate improved, so no
  apparent improvement needed to be checked against a GT artifact — the caveat did not
  become load-bearing this time.

## 13. Future work

Only what the evidence actually supports:

1. **Fix the instrumentation** (highest expected value, and unchanged from Day 4).
   Six of the seven worst sessions sit at 0.00% browser-domain coverage. C4 confirms
   that compensating for this *in the algorithm* does not work — which strengthens
   rather than weakens the case for fixing it at the source.
2. **Supervised per-transition classification with explicit class weighting.** Every
   method tested on Day 6 and Day 7 was either unsupervised or a fixed rule. Dataset A
   *has* labels, and boundaries being ~1.03% of transitions is a class-imbalance
   problem that a weighted supervised model addresses head-on. This remains the most
   promising untried direction.
3. **Motif evidence as a reconstruction-layer input** rather than a replacement rule,
   evaluated under the Stage-8.5 protection-experiment protocol.

Explicitly *not* recommended: a larger sequence model, an LLM in the boundary path, or
further threshold tuning. All three have now been measured and rejected.
