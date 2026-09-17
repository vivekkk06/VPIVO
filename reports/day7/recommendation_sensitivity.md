# Day 7 — Recommendation robustness under segmentation uncertainty

**Artifact:** `reports/day7/recommendation_sensitivity.json`
**Script:** `scripts/run_recommendation_sensitivity.py`
**Result: the composite score is SENSITIVE. The underlying evidence is STABLE.**

---

## 1. Why this experiment was necessary

Dataset-A boundary F1 is 0.3440 and 79.05% of ground-truth executions are
fragmented. Through Day 6 the final report handled this by arguing that the
business recommendation survives anyway, because Step 2 reads *process-level
aggregates* rather than treating individual Dataset-B segments as ground truth.

That was an argument, not a measurement. It was the last load-bearing assumption in
the submission that had never been tested, and it is exactly the objection a
skeptical reviewer would raise: *"you've reasoned that aggregates are robust — show
me."*

## 2. Method

**The one variable:** `max_away_events`, the leave-and-return merge threshold used
when building Dataset-B executions.

**Thresholds, and why these ones.** They are the documented percentiles of the
away-span distribution that the locked baseline was itself drawn from
(`execution_construction.merge_leave_and_return`), not values chosen for their
results:

| Threshold | Justification |
|---:|---|
| 0 | No merging at all — the raw system-change segmentation (conservative lower bound) |
| **5** | **p25 — the locked baseline** |
| 11 | p50, the median away-span |
| 36 | p90 — aggressive merging (upper bound) |

**Held constant:** the boundary signal, scoring weights, the Opportunity formula,
the exclusion policy, and process definitions. Both downstream scripts
(`analyze_process_priority_dataset_b.py`, `audit_problem2_process_mining.py`) were
invoked **unmodified as subprocesses**. If any of those had moved, the experiment
would be uninterpretable.

**Control.** Threshold 5 must reproduce `reports/day3/problem2_audit_results.json`
exactly, or the run aborts rather than reporting differences that are really harness
bugs. **It reproduced the canonical ranking order and HR's Opportunity exactly.**

Canonical artifacts were never overwritten — intermediates were written to a
separate work directory.

## 3. Results

| Threshold | Executions | Top candidate by Opportunity | HR rank | HR Opportunity | Kendall τ vs baseline |
|---:|---:|---|---:|---:|---:|
| 0 | 1,018 | HR / Payroll System | 1 | 0.4000 | 0.7905 |
| **5** | **645** | **HR / Payroll System** | **1** | **0.4401** | **1.0000** |
| 11 | 479 | **Excel: Budget Analysis Workbook** | **5** | 0.2862 | 0.7778 |
| 36 | 262 | HR / Payroll System | 1 | 0.2899 | 0.4559 |

**The recommendation changed at the p50 threshold.** HR fell from rank 1 to rank 5.
This is a real result and it is not being softened.

### What overtook it, and why

At threshold 11 the top slot goes to **Excel: Budget Analysis Workbook**:

| | Excel: Budget Analysis | HR / Payroll |
|---|---:|---:|
| Executions | **7** | 75 |
| Handling time | **0.0200 h** | 0.8684 h |
| Operators | **1** | **4** |
| Impact | 0.3593 | 0.8105 |
| Feasibility | **1.0000** | 0.3531 |
| **Opportunity** | **0.3593** | 0.2862 |

The winner represents **1.2 minutes of work performed by one person**, against HR's
52 minutes across four. It wins because its Feasibility normalises to exactly
**1.0000** — it is the most deterministic process in the population, and min-max
normalisation therefore awards it the maximum.

This is the **same failure mode Day 3 already documented** under a risk-averse
weighting: near-zero-volume processes carry almost no variant complexity or risk, so
a multiplicative Impact×Feasibility score can let them displace real work. Day 7
shows that weighting is not the only thing that can trigger it — changing the merge
threshold does too, because it changes the population the normalisation runs over
(21 ranked processes at baseline, 19 at p50, 17 at p90).

### The non-monotonicity, explained rather than hidden

HR is #1 at thresholds 0, 5 and 36 but not at 11. That is not noise and it is not a
bug — it follows from min-max normalisation over a *changing population*. As merging
absorbs detours, processes merge into others or disappear from the ranked set
entirely, which moves the normalisation denominators for everyone. The composite
score is therefore not monotonic in the threshold, which is itself a finding about
the scoring method.

## 4. The evidence layer tells a different story

Measured separately from the composite score:

| Threshold | HR handling time | HR rank **by handling time** | HR operators |
|---:|---:|---:|---:|
| 0 | 0.7635 h | **1** | 4 |
| 5 | 0.8309 h | **1** | 4 |
| 11 | 0.8684 h | **1** | 4 |
| 36 | 0.9796 h | **1** | 4 |

**HR/Payroll is the single largest consumer of recorded handling time at every
threshold tested, and is performed by all four operators at every threshold.** Its
measured handling time does not merely hold — it *increases* monotonically with the
merge threshold (0.7635 → 0.9796 h), because merging correctly reattributes detour
time back to the work it belongs to.

Financial Accounting is second at every threshold (0.6032 → 0.8182 h). The ordering
of the three core systems by handling time never changes.

So the instability is **in the scoring layer, not in the process evidence**.

## 5. One scope figure that is genuinely threshold-dependent

The dominant-path share — the basis of the automation scope — moves substantially:

| Threshold | HR dominant-variant share |
|---:|---:|
| 0 | 100.00% |
| **5** | **77.05%** |
| 11 | 53.33% |
| 36 | 33.33% |

This must be stated plainly: **"77.05% of executions" is a threshold-dependent
figure, not an absolute property of the work.** Heavier merging absorbs the Word
detours *into* HR executions, so the pure single-system path becomes a smaller share
of a smaller number of longer executions.

What does *not* change is the underlying activity. The same navigate → note →
confirm interactions occur in the log regardless of how executions are bracketed;
only the denominator moves. The automation still automates the same real work — but
any claim of the form "covers 77% of executions" is a statement about one
segmentation choice, and should be read that way.

## 6. The exclusion policy was not driving anything either

The exclusion policy was held constant throughout. The Day-6 conclusion holds at
every threshold: excluded contexts remain a negligible fraction of the work relative
to HR, so neither segmentation variation nor exclusion policy is silently carrying
the recommendation.

## 7. Interpretation

Three different kinds of confidence, which this project had been running together:

| | Question | Answer |
|---|---|---|
| **Boundary confidence** | How accurately were individual boundaries recovered? | **Low.** F1 0.3440, 79.05% fragmented. Unchanged by this experiment. |
| **Process-analysis confidence** | How stable are aggregate process observations? | **High.** HR is the top process by handling time and has 4/4 operator coverage at every threshold. |
| **Decision confidence** | Is the recommendation stable under segmentation uncertainty? | **Conditional.** Stable on the evidence; *not* stable on the composite score, which flips at p50. |

**Classification: C. SENSITIVE** for the composite Opportunity score;
**A. STABLE** for the process evidence underneath it.

### What this changes

The recommendation stands, but its *justification* must change, and this is the main
intellectual outcome of Day 7:

- **Before:** "HR ranks #1 on the Opportunity score, corroborated by evidence."
- **After:** "HR is the largest consumer of handling time and the only high-volume
  process touched by all four operators, at every segmentation setting tested. The
  Opportunity score agrees at the baseline threshold but is fragile, and should be
  read as corroboration rather than as the foundation."

The composite score should not be the load-bearing element of a business
recommendation when a 7-execution workbook can take the top slot from it.

### What would resolve the remaining uncertainty

Production execution volume. Every threshold where a near-zero-volume workbook wins
depends on that workbook's tiny volume carrying no risk. Real frequency data would
settle it immediately — and it is the same measurement the pilot in the final report
§6.5 is designed to collect.

## 8. Honest limitations of this experiment

- Four thresholds, not a continuous sweep. A finer grid could reveal other flips.
- Only the **merge threshold** was varied. The underlying `system_change_boundaries`
  signal was held constant; a different boundary signal was not tested.
- **Dataset B still has no ground truth.** No threshold's segmentation is claimed to
  be more correct than another's. This measures *decision stability*, not accuracy.
- The result at threshold 36 has the weakest rank correlation (τ 0.4559) and only 17
  comparable processes, so HR's rank-1 position there sits on a substantially
  different population than the baseline's.
