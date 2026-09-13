# Day 2 — Baseline Segmentation & Threshold Sensitivity (Stage 5)

**MEASUREMENT.** Source: `scripts/run_baseline_segmentation.py`, all 63
Dataset A sessions with ground truth, 162,705 pooled transitions.
Evaluation framework: `src/procmine/segmentation/evaluation.py`
(boundary-level precision/recall/F1 via exact transition matching;
execution-level over/under-segmentation via naive contiguous
reconstruction). Baselines: `src/procmine/segmentation/baselines.py`.
26 new tests across evaluation/baselines, 83/83 project-wide.

## Headline result: naive thresholding performs weakly (FACT, not a bug)

Best F1 across the entire threshold sweep: **0.173** (τ=3000ms,
precision 0.115, recall 0.352). This confirms — with a measurement, not
just the a-priori warning already in the spec — that `if gap > X: boundary`
is inadequate as a real segmentation method, at any threshold.

**Why precision is structurally capped, not just "badly tuned" (INFERENCE,
grounded in a directly measured number):** GT boundaries are 1.03% of all
transitions — a **97.4:1** class imbalance. Even a threshold that
separates the two gap distributions reasonably well in relative terms
still passes a large *absolute* number of interior transitions when there
are 97 interior transitions for every 1 real boundary. This is the same
distributional overlap Stage 4 already found (interior p90 = 1,173ms,
boundary p10 = 437ms — the two ranges overlap substantially) now shown to
translate directly into a hard precision ceiling for any single-threshold
rule, not a tuning failure.

## Full threshold sweep (MEASUREMENT)

| τ (ms) | Precision | Recall | F1 | Over-seg rate | Under-seg rate |
|---|---|---|---|---|---|
| 50 | 0.019 | 1.000 | 0.038 | 17.55 | 0.000 |
| 100 | 0.035 | 0.999 | 0.067 | 16.24 | 0.000 |
| 300 | 0.050 | 0.993 | 0.095 | 14.46 | 0.000 |
| 500 | 0.036 | 0.612 | 0.068 | 12.81 | 0.024 |
| 1000 | 0.036 | 0.399 | 0.066 | 8.37 | 0.056 |
| 2000 | 0.060 | 0.384 | 0.104 | 4.69 | 0.097 |
| **3000** | **0.115** | **0.352** | **0.173** | **2.02** | **0.213** |
| 5000 | 0.067 | 0.083 | 0.074 | 0.74 | 0.769 |
| 10000 | 0.070 | 0.059 | 0.064 | 0.58 | 1.151 |

**Reading the shape (INFERENCE):** there is no sharp optimum and no
stable high-performing plateau — F1 rises slowly from very low
thresholds, peaks modestly around 3,000ms, then falls as recall collapses
faster than precision recovers. Over-segmentation dominates below ~1s
(every execution shredded into many fragments — at τ=50ms, 17.5 extra
fragments per execution on average); under-segmentation dominates above
~5s (executions increasingly merged together — at τ=10000ms, each
predicted segment spans 2.15 GT executions on average). There is no
threshold where both are simultaneously small. **This is direct, measured
evidence for investigating an adaptive or multi-signal approach in Stage
6, not proof one will work — that still has to be measured, not assumed.**

## Baseline comparison at τ=3000ms (MEASUREMENT)

| Baseline | Precision | Recall | F1 | Over-seg | Under-seg |
|---|---|---|---|---|---|
| 1: temporal-only | 0.115 | 0.352 | 0.173 | 2.023 | 0.213 |
| 2: temporal **AND** context change | 0.125 | 0.330 | **0.182** | **1.698** | 0.257 |
| 3: temporal **OR** context change | 0.019 | 0.999 | 0.037 | 12.339 | 0.000 |

**Baseline 2 beats Baseline 1 modestly** (F1 +0.009, over-segmentation
reduced from 2.02 to 1.70 extra fragments per execution) — requiring a
contextual change alongside a time gap filters out some large-but-nothing
-actually-changed false positives. **Baseline 3 is much worse** (F1
0.037) — OR-combining means *any* context change alone triggers a
boundary regardless of gap size, and context changes (per Stage 2/4) are
common even mid-execution, so this floods predictions almost as badly as
a near-zero threshold. **DECISION**: AND-combination is the right
formulation to build on for Stage 6, not OR — confirmed by measurement,
not assumed from the spec's own suggested formulations.

## Per-session stability (MEASUREMENT)

Baseline 1 at τ=3000ms: mean F1 0.173, **std 0.050** (relative std ~29%
of the mean), min 0.061, max 0.305 — a 5x spread between the
worst and best session. Worst 5: `ses_20260701-103521-LAPTOP-0IM1OHQH`
(0.061), `ses_20260701-124550-LAPTOP-0IM1OHQH` (0.086),
`ses_20260701-043922-SIDDHIGUPTAB00B` (0.090),
`ses_20260701-090300-Marcos` (0.093), `ses_20260701-014804-yuvraj` (0.102)
— per the project's own instruction not to hide bad sessions behind an
aggregate. **Checked explicitly**: excluding Stage 4's known-incomplete
session (`ses_20260701-152030-CHAITANYA0BCF`) changes the mean by 0.0006
(0.1732 → 0.1738) — that session is not meaningfully distorting the
aggregate, so no special handling is needed here beyond the disclosure
already in `time_gap_analysis.md`.

## What this changes going into Stage 6

- A hard, measured baseline now exists to beat: **F1 0.173** (temporal-
  only), **F1 0.182** (temporal AND context) at the best fixed threshold
  found. Any learned model needs to clear this bar to justify its
  complexity, per the project's own "prefer the simplest approach that
  achieves strong evidence" instruction — if a learned model can't beat
  0.182, a documented deterministic baseline is the honest answer, not a
  learned model kept because it's more sophisticated-looking.
- The 97.4:1 class imbalance is now a known, measured constraint that
  Stage 6's model selection and evaluation must account for explicitly
  (e.g. class weighting, precision/recall trade-off curves, not accuracy).
- Per-session variance (std ~29% of mean) is now measured evidence, not
  just Stage 4's gap-distribution hypothesis, that a single global
  parameter underperforms unevenly across sessions — worth testing
  whether a learned model's features implicitly compensate for this
  before concluding an explicitly adaptive threshold is needed.
- The naive reconstruction (`segments_from_boundaries` — cut wherever a
  boundary is predicted, no interruption handling) is deliberately not
  yet trying to solve the A→B→A-stays-one-execution problem. Stage 7 owns
  that, and its improvement over this baseline's execution-level numbers
  is exactly how that improvement gets measured, not just claimed.

## Files

- `src/procmine/segmentation/evaluation.py`, `baselines.py`
- `tests/test_segmentation_evaluation.py` (11), `test_segmentation_baselines.py` (4)
- `scripts/run_baseline_segmentation.py`
- `reports/day2/baseline_segmentation_dataset_a.json`
- `reports/day2/segmentation_baseline.md` — this file
