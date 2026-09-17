# Module 2 — Final decision

**MODULE 1: canonical / locked.**
**MODULE 2: experimental — segmentation NOT PROMOTED; automation and decision-view
components retained as experimental additions.**

No canonical artifact was regenerated. `segments.jsonl`, the Dataset-B execution set,
the process profiles, the Opportunity ranking (HR 0.4401, rank 1) and the Day-5
automation prototype are all byte-identical to before Module 2 existed.

---

## 1. Verdict per hypothesis

| # | Hypothesis | Verdict | Decisive evidence |
|---|---|---|---|
| **H1** | Operator-normalized timing | **Weakly supported, mechanism largely absent** | Operator median gaps 52–56 ms (ratio 1.077); `dwell_scale` constant at 1.4. +0.0073 F1 alone |
| **H2** | Content drift | **Supported in direction, limited by coverage** | Computable on 11.50% of transitions; adjacent-pair form rejected at 0.03%. +0.0049 F1 alone |
| **H1+H2** | Combined (M2C) | **Complementary, still below gate** | +0.0102 vs control, +0.0079 vs canonical; gate required +0.02 |
| **H3** | Dataset-B screenshot review | **Assessed by surrogate review only — identifies concerns; human review not performed** | Blind vision-model review (not ground truth), judgments frozen before the reveal. 26 of 40 points reviewable (14 image files missing, 0 recovered). Visible context change at 3 of 12 judgeable boundaries vs 3 of 14 judgeable controls; 13 ambiguous. Not a segmentation metric (`dataset_b_screenshot_review_results.md`) |
| **H4** | Effort/cost conversion | **Supported; monetary half impossible** | Hours computed for 21 processes; no cost rate exists in the telemetry |
| **H5** | Operator variant concentration | **NOT supported** | χ² = 1.152 vs 7.815 critical (dof 3); every operator CI contains the pooled 0.7705 |
| **H6** | Pareto frontier | **Supported as communication, not as a decision rule** | Frontier 3/21 reproduced exactly; invariant across all 8 scenarios by construction |
| **H7** | Pre-flight variant routing | **Supported as a safety mechanism, at a coverage cost** | 0 of 28 non-dominant executions admitted; coverage 0.5082 vs canonical share 0.7705 |
| **H8** | Post-action audit | **Supported, with its ceiling stated** | Expected state passes; injected route drift detected; never proof of a business record |

## 2. The segmentation gate

Registered before any candidate ran, reused verbatim from the Day-7 challenge, and
**not adjusted afterwards**. Best candidate M2C, matched protocol:

- Gate 1 (F1 gain ≥ 0.02): **+0.0102 — FAIL**
- Gates 2–8 (recall, fragmentation, under-, over-segmentation, degraded sessions,
  session concentration, machine dominance): **all PASS**

Failing one decisive gate while passing seven is the honest description. The
temptation here was real: M2C improves precision, recall, fragmentation,
under-segmentation and over-segmentation simultaneously, broadly across 30 of 63
sessions, and survives both robustness checks. Loosening gate 1 to 0.01 would have
"promoted" it. **That would have been fitting the gate to the result**, and the gate
exists precisely to stop that.

## 3. Why not promote anyway

Even taken at face value, +0.0079 F1 over the canonical number would require
regenerating `segments.jsonl`, re-deriving all 645 Dataset-B executions, all 21 process
profiles, the entire Opportunity ranking, the HR forensic split and the automation
evidence base — invalidating every published number in the repository, including the
94/24/4 split the automation depends on. A gain inside the between-session noise band
does not justify that.

Per Rule 23, promotion would in any case have **stopped before** replacing canonical
artifacts and required a documented review. It never reached that point.

## 4. What is retained

| Component | Status | Rationale |
|---|---|---|
| Module 2 segmentation features | **Experimental, not canonical** | Failed the gate |
| Pre-flight variant routing | **Retained as an experimental control** | Refuses 100% of non-dominant variants; costs coverage, adds no risk |
| Post-action evidence audit | **Retained as an experimental control** | Detects end-state drift the existing controls structurally cannot |
| Effort/hours view | **Retained as a presentation layer** | Adds interpretability; changes no score |
| Pareto decision view | **Retained beside the canonical ranking** | Reproduces the canonical frontier exactly |
| Operator variant analysis | **Retained as a negative result** | Documents that the apparent difference is sampling noise |
| Dataset-B blind review sheet | **Retained; human review not performed** | Infrastructure delivered; limitation reported |
| Dataset-B surrogate visual review | **Completed; identifies concerns** | Vision-model surrogate, not ground truth; descriptive counts only, never a metric; not a basis for promotion |

## 5. What would change this decision

- **Real operator data with genuinely different work speeds.** Dataset A's constant
  `dwell_scale` removed H1's mechanism by construction; this experiment cannot say how
  it behaves when operators actually differ.
- **Richer text capture.** At 11.50% availability, content drift abstains on seven
  transitions in eight. At 50% it would be a different experiment.
- **A completed human review** of the Dataset-B sample — starting from the concerns the
  surrogate review raised — with the 14 missing screenshots obtained from the data
  provider. (None of this bears on promotion, which was decided on Dataset A.)
- **A larger operator sample** for H5 — 4 operators cannot separate a real 12-point
  adherence difference from noise.

None of these is available now, and none is assumed.

## 6. Statement of record

> Module 1 is the locked baseline used by the canonical downstream analysis. Module 2
> is an independent experimental approach and does not modify Module 1.

Module 2 was not built to produce a better number, and it did not produce one that
cleared the pre-registered gate. It produced
a defensible comparison, two automation controls that are genuinely additive, one
supported presentation view, one clearly negative result, and one hypothesis rejected
on data availability before it could be tested properly. All of those are reported.
