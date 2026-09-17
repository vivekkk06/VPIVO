# Module 1 vs Module 2 — evidence-based comparison

No arbitrary score ranks the two modules. Each row below is a measured quantity with
its source, and the decision column says what the evidence supports — nothing more.

---

## 1. Fairness of the comparison

| Held identical | Unavoidably different |
|---|---|
| Dataset A, all 63 sessions | Module 2 adds 1–3 feature columns |
| Leave-one-session-out validation | Module 2 refits operator baselines per fold |
| Session grouping | Module 2 runtime is ~1.5× |
| Metric definitions (the locked evaluator) | — |
| Candidate union, Rules 1–4, protection layer | — |
| Preprocessing and canonical event stream | — |

Module 2 is **not** a raw first prototype compared against a tuned pipeline: it *is*
the tuned pipeline, with columns appended. An `M1_compatible` control runs through the
identical harness so the added columns are the only difference.

Two threshold protocols are reported, because either alone would be objectionable:
`matched` (every feature set re-selects thresholds by the same rule) and `locked`
(everyone reuses Module 1's 0.9078 / 0.8860).

## 2. Segmentation (Dataset A)

| Dimension | Module 1 | Module 2 (best: M2C) | Difference | Note |
|---|---:|---:|---:|---|
| F1 — Module 1's thresholds | **0.3440** (canonical) | 0.3457 | +0.0017 | below gate |
| F1 — thresholds re-selected | 0.3417 (control) | **0.3519** | +0.0102 | **gate requires +0.0200** |
| Precision — re-selected | 0.2359 (control) | 0.2436 | +0.0076 | higher |
| Recall — re-selected | 0.6194 (control) | 0.6338 | +0.0144 | higher |
| Fragmentation % — re-selected | 78.37 (control) | **76.94** | −1.43 pp | lower |
| Under-segmentation — re-selected | 0.1507 (control) | 0.1452 | −0.0055 | lower |
| Over-segmentation — re-selected | 1.5605 (control) | 1.5320 | −0.0285 | lower |
| Sessions with higher / lower F1 | — | 30 / 8 (25 unchanged) | — | broad, not concentrated |
| Survives dropping top-3 sessions | — | yes (0.3282 → 0.3349) | — | robust |
| Survives dropping best operator | — | yes (0.0087 → 0.0073) | — | no machine dominance |
| Computational cost | 87.6 s | 132.0 s | ~1.5× | acceptable |
| GT leakage | none | none (structurally tested) | — | clean |
| **Promotion gate** | reference | **FAILS gate 1** | — | **NOT PROMOTED** |

Every "re-selected" row compares M2C with the Module 1 feature control under the same
threshold rule, so the Module 1 figure on those rows is the control (0.3417), not the
canonical 0.3440. **Module 2 reduced fragmentation in the best experimental
configuration, but the F1 gain (+0.0102) did not meet the pre-registered +0.0200
promotion requirement, so Module 1 remains canonical.** The gate was not moved.

## 3. Dataset-B evidence

| Dimension | Module 1 | Module 2 | Decision |
|---|---|---|---|
| Supervised metrics | none (no GT) | none (no GT) | rule respected by both |
| Dataset-B review | none | blind review framework, 40 points, seed 20260918 | surrogate visual review completed; human review not completed |
| Screenshot pairing | — | all 40 paired, median Δt 385 ms | good pairing |
| Evidence completeness | — | 14 of 40 files missing on disk (0 recovered) | incomplete |
| Review performed | — | **vision-model surrogate only; no human review** | labelled surrogate, not ground truth |
| Surrogate visual labels | — | A 7 · B 6 · C 13 · D 14; visible change at 3 of 12 judgeable boundaries and 3 of 14 judgeable controls | **identifies concerns** — descriptive, not a metric |

## 4. Process analysis

| Dimension | Module 1 | Module 2 | Decision |
|---|---|---|---|
| Ranking | canonical weighted Opportunity (HR 0.4401, rank 1) | unchanged, not recomputed | Module 1 retained |
| Effort view | normalized score | F_p, TD_p, AD_p, TS_p in hours | Module 2 adds interpretability |
| Monetary ROI | not claimed | **not possible** — no cost rate exists | both honest |
| Decision view | single ranking | Pareto frontier (3 of 21) beside it | complementary |
| Sensitivity | 8 scenarios, HR first in 5 | same 8, reused verbatim | unchanged |
| Operator variation | not examined | examined; χ²=1.152 vs 7.815 → noise | **H5 not supported** |

## 5. Automation

| Dimension | Module 1 | Module 2 | Decision |
|---|---:|---:|---|
| Pre-flight variant gate | none | 62/122 eligible (0.5082) | Module 2 adds a control |
| Non-dominant executions admitted | not evaluated | **0 of 28** | gate works |
| Dominant executions refused | — | 32 (no route 14, ambiguous 12, unknown route 6) | conservative by design |
| Post-action evidence | none | 5 structural checks + SHA-256 | Module 2 adds evidence |
| Safety controls | 8 | **same 8, unchanged** + 2 layers | no regression |
| Manual work remaining | note authoring, review | the same **plus 60 routed executions** | Module 2 automates *less* |

## 6. What the comparison does not say

- It does not say Module 2 is better. On segmentation, its best configuration moved
  every reported metric in a favourable direction relative to its control and still
  failed the F1 gate; on automation it is safer and narrower; on process analysis it
  added one supported view (H6), one unsupported one (H5), and one impossible one
  (monetary ROI).
- It does not rank the modules with a composite score. Combining F1, coverage and
  interpretability into one number would be exactly the false precision this project
  has refused elsewhere.
- It does not claim Module 2 would behave the same on real data. Dataset A's
  `dwell_scale` is a constant 1.4 — the generator never varied operator speed — so H1's
  mechanism was largely absent here by construction.
