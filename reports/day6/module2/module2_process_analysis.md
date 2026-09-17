# Module 2 — Process analysis: effort, operators, Pareto, sensitivity (H4, H5, H6)

> Dataset B is used for operational validation, not supervised segmentation
> evaluation. No accuracy, precision, recall or F1 appears in this report.

**The canonical Opportunity score is not recomputed, replaced or re-weighted.** HR
remains 0.4401 at rank 1. Module 2 adds a second view beside it.

---

## 2A · Time / effort / cost conversion (H4)

### Definitions

```
F_p  = execution frequency
TD_p = Σ duration_i            (total observed time)
AD_p = TD_p / F_p              (average duration)
TS_p = TD_p / Σ_p TD_p         (time share)
ObservedEffort_p = TD_p in hours
```

### Results — top processes by observed time (21 ranked)

| Process | F_p | TD_p (h) | AD_p (ms) | TS_p | Cost input? | Est. cost |
|---|---:|---:|---:|---:|:--:|---|
| HR / Payroll System | 122 | 0.8309 | 24,518 | 0.3248 | **No** | — |
| Financial Accounting System | 125 | 0.7213 | 20,774 | 0.2820 | **No** | — |
| Order & Inventory Management | 96 | 0.4292 | 16,095 | 0.1678 | **No** | — |
| Word: Contract Termination | 29 | 0.1361 | 16,901 | 0.0532 | **No** | — |
| Word: Outsourcing Compensation | 23 | 0.0827 | 12,949 | 0.0323 | **No** | — |

Total observed time across all 21 ranked processes: **2.5581 hours**.

Missing inputs for every row, identically: operator hourly cost rate, headcount,
fully-loaded employment cost.

### Interpretation

> **Direct monetary ROI cannot be estimated from the provided telemetry because
> operator cost/headcount cost is unavailable.**

No salary, rate or headcount figure exists anywhere in Dataset A or Dataset B. Any
currency amount would be invented rather than measured, so the cost column stays empty.

The effort view does add something the score alone does not. **Financial Accounting has
*more* executions than HR (125 vs 122) but less total time (0.7213 h vs 0.8309 h).** A
frequency-only reading would rank it first; a time-aware one does not. That is exactly
the kind of distinction an hours column makes visible and a normalized 0–1 score hides.

**Environment caveat.** Dataset-B timing may reflect the assignment/test environment
rather than production reality. These are observed recording durations, not validated
production cycle times, and must not be presented as the latter. 2.5581 hours total is
a recording-scale number, not a business-scale one.

**H4: supported, with the monetary half explicitly unavailable.**

---

## 2B · Operator-level variant analysis (H5)

The canonical 94 / 24 / 4 split is **used, never reinterpreted**. Execution ids were
read from the canonical forensic artifact and joined to their operator: all 122 joined,
**zero unmatched**, pooled dominant share reproduced at **0.7705**.

| Operator | n | dominant | detour | rare | Dominant share | 95% CI | CI covers pooled? |
|---|---:|---:|---:|---:|---:|---|:--:|
| NEELA9BAF | 44 | 34 | 9 | 1 | 0.7727 | [0.630, 0.872] | ✅ |
| LAPTOP-76QMG9DE | 35 | 25 | 8 | 2 | 0.7143 | [0.549, 0.837] | ✅ |
| SIDDHIGUPTAB00B | 25 | 20 | 4 | 1 | 0.8000 | [0.609, 0.911] | ✅ |
| CHAITANYA0BCF | 18 | 15 | 3 | 0 | 0.8333 | [0.608, 0.942] | ✅ |

Spread 0.1190, sd 0.0436. **χ² = 1.152, dof = 3, 0.05 critical value 7.815.**

### Interpretation

**H5 is not supported on this data.** The raw spread looks suggestive — 0.7143 to
0.8333 — and a less careful reading would report "operator adherence varies by 12
points" as a training finding. It does not survive contact with the sample size: every
operator's confidence interval contains the pooled share, and χ² is roughly one seventh
of its critical value. **The observed variation is what four samples of 18–44 draws from
a single 0.7705 process would be expected to produce.**

Neutral wording, as required: *variant concentration differs across operators and may
indicate a training/process-adherence consideration* — but on this evidence it is more
parsimoniously explained by sampling noise, and no operator is characterised as
performing badly.

### Limitations

- Only 4 operators, 18–44 HR executions each.
- Operator identity is a machine/account label, not a verified person.
- A difference in variant mix would not establish a difference in competence, workload
  or case difficulty — none of which is observable here.
- Dataset B has no ground truth; these are operational statistics.

---

## 2C · Pareto frontier (H6)

### Dominance

```
A dominates B  iff  Impact_A ≥ Impact_B  AND  Feasibility_A ≥ Feasibility_B
                    with at least one strict inequality
```

Recomputed independently from the canonical ranking and **matches the canonical
frontier exactly**: 3 of 21 processes.

| Rank | Process | Impact | Feasibility | Opportunity | Frontier | Executions | Time share |
|---:|---|---:|---:|---:|:--:|---:|---:|
| 1 | HR / Payroll System | 0.9236 | 0.4765 | 0.4401 | ✅ | 122 | 0.3248 |
| 2 | Order & Inventory Management | 0.6699 | 0.5267 | 0.3529 | ✅ | 96 | 0.1678 |
| 3 | Excel: Budget Analysis Workbook | 0.3542 | 0.9544 | 0.3380 | ✅ | 7 | 0.0078 |
| 4 | Financial Accounting System | 0.8802 | 0.3695 | 0.3252 | ❌ | 125 | 0.2820 |
| 5 | Excel: Expense Calculation | 0.3452 | 0.9221 | 0.3183 | ❌ | 17 | 0.0147 |

Annotation dimensions (executions, time share, dominant-variant share, evidenced
routes) are **annotations, not score components**. No weighted score is added.

### Interpretation

The frontier exposes a trade-off the single score compresses away. **Excel: Budget
Analysis sits on the frontier on 7 executions and 0.78% of observed time** — it is
there purely on feasibility (0.9544), not because it matters much. Meanwhile
**Financial Accounting is dominated by HR** (0.9236 ≥ 0.8802 and 0.4765 ≥ 0.3695)
despite having the most executions of any process. Both facts are visible instantly on
the frontier and invisible in "rank 3 vs rank 4".

**H6: supported as a communication device.** It is not a better decision rule — it
returns a set of 3 and cannot break ties. Neither view is universally superior.

---

## 2D · Sensitivity

The canonical 8 scenarios are reused verbatim; no new weights were invented.

| HR rank 1 | HR rank 3 |
|---|---|
| balanced · feasibility_heavy · risk_averse · frequency_heavy · time_heavy | manual_effort_heavy · volume_deemphasized · correlation_aware |

**HR is first in 5 of 8** scenarios; worst rank 3; mean Kendall τ vs default 0.9524.

The Pareto view is **invariant across all 8** — not as an empirical finding but as a
structural property: frontier membership uses no weights, so re-weighting cannot move
it. That is precisely the transparency H6 claimed, and also precisely its limit: an
invariant answer is not a more *correct* answer.

Both views are shown side by side in the frontend. Neither is presented as superior.
