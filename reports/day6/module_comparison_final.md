# Day 6 — Module 1 vs Module 2

**MODULE 1: canonical / locked.**
**MODULE 2: experimental — segmentation not promoted; automation and decision-view
components retained as experimental additions.**

---

## 1. Why a second module

Module 1 reaches F1 0.3440 with precision 0.2358 and leaves 79.05% of ground-truth
executions fragmented. Day 6 (ensembles, HMM, clustering) and Day 7 (four rule-based
candidates) both failed to beat it. That is evidence the *architecture* holds — not
evidence its *evidence base* is complete.

Two things Module 1 never looks at: whether a pause is unusual **for this operator**,
and whether screen **content changed** rather than merely being present. Testing either
requires adding feature columns, which changes the model — and changing the model in
place would destroy the fixed reference every downstream number depends on. Hence a
separate, additive module.

## 2. Module 1

**Architecture.** Raw logs → audit/normalization → canonical event stream →
per-transition features → V1 boundary model (9 features, threshold 0.9078) ∪ V2
continuity model (8 features, boundary score ≥ 0.8860) → reconstruction Rules 1–4 →
Strategy_Combined protection → executions → process discovery → Opportunity ranking →
HR/Payroll automation.

**Metrics (Dataset A, LOSO, 63 sessions).** precision 0.23584277 · recall 0.63554758 ·
F1 0.3440233236151604 · fragmentation 79.05251% · under-segmentation 0.1412 ·
over-segmentation 1.6033 · TP 1062 · FP 3441 · FN 609. Internally consistent:
1062+3441 = 4503 predicted; 1062+609 = 1671 GT boundaries.

**Known limitations.** Weak absolute precision (~3 false boundaries per true one);
heavy over-segmentation; severe class imbalance (~97:1); offline "after" windows;
thresholds chosen on pooled Dataset-A evidence rather than nested CV.

## 3. Module 2

**Architecture.** Identical to Module 1 except for appended feature columns, plus two
new automation layers and a decision view. It is **not an AI model** — it is a pipeline
of deterministic features, rules and gates reusing Module 1's own classifiers.

**Hypotheses.** H1 operator-normalized timing · H2 content drift · H3 Dataset-B
screenshot review · H4 effort/cost conversion · H5 operator variant concentration ·
H6 Pareto frontier · H7 pre-flight variant routing · H8 post-action audit.

**Mathematics.**

```
z_o(x)    = ( log1p(Δt) − median_o ) / MAD_o          operator-normalized timing
J(A,B)    = |A ∩ B| / |A ∪ B|                          token similarity
D_content = 1 − J(A,B)                                 content drift
TD_p = Σ D_i ;  AD_p = TD_p / F_p ;  TS_p = TD_p / Σ TD   effort
Coverage_p = dominant_executions_p / total_executions_p
A ≽ B iff Impact_A ≥ Impact_B ∧ Feasibility_A ≥ Feasibility_B, one strict
```

MAD-scaling was chosen over a ratio after measuring that operator **medians** barely
differ (52–56 ms, ratio 1.077) while **dispersion** differs more (MAD-log 1.105–1.404).

## 4. Dataset-A segmentation experiment

Fairness control: only the feature matrices vary. Candidate union, Rules 1–4, the
protection layer and the evaluator are the locked Module 1 code, called unmodified. An
`M1_compatible` control runs through the identical harness. Baseline drift: **0.0**.

| Feature set | F1 matched | F1 locked | Frag % (matched) |
|---|---:|---:|---:|
| M1_compatible (control) | 0.3417 | **0.3440** | 78.37 |
| M2A operator timing | 0.3490 | 0.3430 | 77.45 |
| M2B content drift | 0.3465 | 0.3448 | 78.77 |
| **M2C both** | **0.3519** | 0.3457 | **76.94** |

Feature availability: content drift computable on **11.50%** of transitions (the
adjacent-pair formulation was measured first and rejected at **0.03%**). Operator
baselines: all 504 fold-fits used real operator data; the documented fallback never
fired.

## 5. Dataset-B validation — surrogate visual review completed, human review not performed

> Dataset B is used for operational validation, not supervised segmentation evaluation.
> **Vision-model surrogate review — not ground truth.** No Dataset-B segmentation
> quality claim is made from it in either direction.

**The sample.** A deterministic (seed 20260918), **blinded** 40-point sample: 20
predicted boundaries mixed with 20 mid-execution controls, each paired with its nearest
screenshot.

- All 40 are paired, with a median Δt of **385 ms**.
- **14 of 40** referenced screenshot files are missing from the dataset, and none could
  be recovered.
- Every capture chunk that references more than 250 screenshots holds exactly 250
  files. Why is not determinable.

**The surrogate review.** A vision model judged the 26 reviewable points blind, and its
judgments were frozen (SHA-256) before the answer key was read. The result was
**A 7 · B 6 · C 13 · D 14**.

- A visible context change appeared at **3 of 12** judgeable predicted boundaries and at
  **3 of 14** judgeable controls.
- Three predicted boundaries sit inside visibly continuous work, right after an 8-event
  Word procedure lookup.
- **Decision: identifies concerns.** This is descriptive, not a metric, and not a basis
  for promoting anything.

**The human sheet.** **No human review was performed**, and the sheet's judgments still
ship empty by design. Full results: `module2/dataset_b_screenshot_review_results.md`.

## 6. Process analysis

21 ranked processes, 2.5581 observed hours. **Direct monetary ROI cannot be estimated
because operator cost/headcount cost is unavailable** — no rate exists in either
dataset. Financial Accounting has more executions than HR (125 vs 122) but less total
time (0.7213 h vs 0.8309 h), a distinction an hours column shows and a normalized score
hides. Dataset-B timing may reflect the test environment, not production.

## 7. Operator analysis

| Operator | n | dominant share | 95% CI |
|---|---:|---:|---|
| NEELA9BAF | 44 | 0.7727 | [0.630, 0.872] |
| LAPTOP-76QMG9DE | 35 | 0.7143 | [0.549, 0.837] |
| SIDDHIGUPTAB00B | 25 | 0.8000 | [0.609, 0.911] |
| CHAITANYA0BCF | 18 | 0.8333 | [0.608, 0.942] |

χ² = 1.152 against a 7.815 critical value (dof 3); every CI contains the pooled 0.7705.
**H5 is not supported** — the 12-point spread is what four small samples from a single
0.7705 process would produce. The canonical 94/24/4 split was joined, not reinterpreted
(122/122 matched, 0 unmatched).

## 8. Pareto analysis

Recomputed independently and **matches the canonical frontier exactly**: 3 of 21 (HR,
Order & Inventory, Excel Budget Analysis). Excel Budget sits on the frontier on 7
executions and 0.78% of time — feasibility alone. Financial Accounting is dominated by
HR despite the most executions. Frontier membership is weight-free and therefore
invariant across all 8 canonical scenarios, by construction rather than by evidence.

## 9. Automation routing

| Quantity | Value |
|---|---:|
| Canonical dominant share | 0.7705 (94/122) |
| Routing-eligible coverage | **0.5082 (62/122)** |
| Non-dominant executions admitted | **0 of 28** |
| Dominant executions refused | 32 (no route 14 · ambiguous 12 · unknown route 6) |

The gate is deliberately stricter than the forensic label: 6 dominant executions touched
`#/resident-tax` or `#/dashboard`, outside the four evidenced routes, and 14 visited no
route at all. **Neither number is automation accuracy.**

## 10. Post-action audit

Five structural checks plus a SHA-256 screenshot hash. Expected end state passes;
injected route drift is detected. No pixel-perfect assertion; the pixel-difference ratio
is defined but never asserted on; `UNAVAILABLE` never counts as a pass; a screenshot is
evidence the UI reached a state, **not proof a payroll record was written**.

## 11. Module comparison

Relative to its Module 1 feature control, M2C scores higher on precision, recall and F1
and lower on fragmentation, under- and over-segmentation, with 30 of 63 sessions higher
and 8 lower. It survives both robustness checks. **Module 2 reduced fragmentation in the
best experimental configuration, but the F1 gain did not meet the pre-registered
promotion gate, so Module 1 remains canonical.** It automates **less** than Module 1
(62 of 122 executions admitted rather than ungated) and produces more evidence. Full
row-by-row table: `module2/module2_comparison.md`.

## 12. Promotion decision

The gate was registered before any candidate ran, reused verbatim from the Day-7
challenge, and **not adjusted afterwards**.

- Gate 1 — F1 gain ≥ 0.02: **+0.0102 → FAIL**
- Gates 2–8: **all PASS**

**MODULE 2 SEGMENTATION IS NOT PROMOTED.** Loosening gate 1 to 0.01 would have promoted
M2C; that would have been fitting the gate to the result. Even at face value, +0.0079
over canonical would require regenerating every downstream artifact — including the
94/24/4 split the automation depends on — for a gain inside the between-session noise
band.

## 13. Limitations

Dataset A is synthetic and `dwell_scale` is a constant 1.4, so H1's mechanism was
largely absent by construction. Text coverage (11.50%) is a property of this capture
configuration. Four operators cannot separate a real adherence difference from noise.
14 of 40 review screenshots are missing, and the Dataset-B review has one surrogate
(vision-model) reviewer and no human rater. Module 2 features were added to both V1 and V2
matrices; adding to one only was not explored. Runtime rises ~1.5×.

## 14. What remains canonical

Unchanged and byte-identical: `segments.jsonl`, the 645 Dataset-B executions, the 21
process profiles, the Opportunity ranking (HR **0.4401**, rank 1, Impact 0.9236,
Feasibility 0.4765), the HR forensic split **94/24/4**, and the Day-5 automation
prototype. `reports/day2`, `day3`, `day4` and all of `day7` were not modified.

> Module 1 is the locked baseline used by the canonical downstream analysis. Module 2
> is an independent experimental approach and does not modify Module 1.
