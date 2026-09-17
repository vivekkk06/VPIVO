# Module 1 — Continuity-Based Reconstruction (LOCKED BASELINE)

> **Module 1 is the locked baseline used by the canonical downstream analysis.
> Module 2 is an independent experimental approach and does not modify Module 1.**

This document freezes Module 1 so the Day-6 comparison has a fixed reference. Nothing
here is recomputed, re-tuned or re-derived — every number is read from the canonical
artifacts listed in §4.

---

## 1. Purpose

Recover units of work ("executions") from an undifferentiated operator event log, then
use those executions to discover processes, rank automation opportunities, and
prototype an automation for the top-ranked one.

Module 1 is the pipeline that currently answers all three assignment problems. Every
downstream conclusion in this repository rests on it.

## 2. Architecture

```
Raw logs
  ↓  data audit / normalization        (loaders/, cleaning.py, audit.py)
  ↓  canonical event stream            (segmentation/canonical.py)
  ↓  per-transition features           (segmentation/features.py)
  ↓  continuity-based segmentation     (V1 boundary model ∪ V2 continuity model)
  ↓  reconstruction Rules 1-4          (segmentation/reconstruction.py)
  ↓  Strategy_Combined protection      (segmentation/protected_boundary.py)
  ↓  execution reconstruction          (segments.jsonl)
  ↓  process discovery                 (process_discovery/)
  ↓  opportunity analysis              (opportunity_scoring.py, prioritization.py)
  ↓  HR/Payroll automation             (automation/, integrations/)
```

**Two models, unioned, then filtered.** V1 is a boundary-first logistic regression over
9 transition features at threshold **0.9078**. V2 is a continuity model over 8 features
predicting P(same execution), converted to a boundary score `1 - P(S=1)` at threshold
**0.8860**. Their union forms the candidate set; Rules 1-4 demote candidates
(Rule 4 continuity threshold **0.40**); the Strategy_Combined protection layer restores
Rule-4-demoted candidates that both models flagged and that show a post-transition tempo
break.

**Validation:** leave-one-session-out across all 63 Dataset-A sessions. No session's
ground truth ever informs its own prediction.

## 3. Canonical metrics (Dataset A)

| Metric | Value |
|---|---|
| precision | **0.23584277** |
| recall | **0.63554758** |
| F1 | **0.3440233236151604** |
| fragmentation | **79.05251 %** |
| under-segmentation | **0.1412** |
| over-segmentation | **1.6033** |
| TP | **1062** |
| FP | **3441** |
| FN | **609** |

Internally consistent: TP + FP = 1062 + 3441 = 4503 = `n_predicted`;
TP + FN = 1062 + 609 = 1671 = `n_gt_boundaries`.

Scale: 63 sessions, 162,768 events, 162,705 transitions, 1,752 closed GT executions of
which 1,385 are fragmented.

## 4. Canonical implementation and artifacts

| Concern | File |
|---|---|
| Locked run | `scripts/run_protected_boundary_experiment.py` |
| Canonical artifact | `reports/day2/protected_boundary_experiment_dataset_a.json` → `systems.Strategy_Combined.pooled` |
| Evaluator | `src/procmine/segmentation/evaluation.py` |
| V1 features | `src/procmine/segmentation/model.py` (`FEATURE_NAMES`, 9) |
| V2 features | `src/procmine/segmentation/continuity_model.py` (`CONTINUITY_FEATURE_NAMES`, 8) |
| Reconstruction rules | `src/procmine/segmentation/reconstruction.py` |
| Protection layer | `src/procmine/segmentation/protected_boundary.py` |

**Reading the artifact correctly matters.** The canonical block is
`systems.Strategy_Combined.pooled`. Taking the first block containing a `pooled` key
yields `V1` (F1 0.2534) instead — an error that actually occurred during Day 7 and was
caught only by a baseline-drift control. Any comparison script must name the block
explicitly and assert the reproduced F1 matches to within 1e-9.

## 5. Known limitations

- **F1 0.3440 is weak in absolute terms**, and the project reports it as a material
  limitation rather than dressing it up. Precision 0.2358 means roughly three false
  boundaries for every true one.
- **79.05% of GT executions are fragmented.** The pipeline over-segments: 4,503
  predicted boundaries against 1,671 real ones.
- **Class imbalance is severe** (~97:1), handled with `class_weight="balanced"` rather
  than resampling.
- **The "after" window is offline.** Trajectory features look at later events, which is
  valid for reconstructing a finished log and invalid for a real-time segmenter.
- **Thresholds were selected on pooled Dataset-A evidence**, a global model-selection
  step rather than a nested cross-fitted one.
- Day-7 tested four simpler rule-based alternatives; **none passed the promotion gate**,
  which is positive evidence for retaining this design rather than proof it is optimal.

## 6. Why it remains locked

1. **Everything downstream depends on it.** `segments.jsonl`, the Dataset-B execution
   set, process profiles, the Opportunity ranking (HR = 0.4401, rank 1) and the
   automation prototype are all derived from Module 1's output. Changing it silently
   invalidates every published number.
2. **It has survived adversarial testing.** Day-6 ensembles/HMM/clustering and the Day-7
   rule-based challenge all failed to beat it under pre-registered gates.
3. **Comparisons require a fixed reference.** A baseline that moves cannot be compared
   against.

## 7. Relationship to Dataset A

Dataset A has ground truth (63 sessions, `gt_manifest.json` per session). It is the
**only** dataset on which Module 1's supervised metrics are computed. Thresholds,
rules and the protection layer were all selected here under leave-one-session-out.

## 8. Relationship to Dataset B

Dataset B has **no ground truth** (15 sessions). Module 1 is *applied* to it to produce
645 executions, but **no precision/recall/F1 is computed there, and none may be**.
Dataset B supplies operational evidence only: execution counts, durations, variant
distributions, and the HR/Payroll forensic split.

## 9. Downstream dependencies

```
Module 1 segmentation
  └─ segments.jsonl
       └─ Dataset-B execution discovery (645 executions)
            ├─ process profiles  → 21 processes
            ├─ Opportunity ranking → HR/Payroll 0.4401, rank 1
            │     (Impact 0.9236, Feasibility 0.4765)
            └─ HR forensic split → 122 executions = 94 dominant / 24 Word-detour / 4 rare
                 └─ automation prototype (4 evidenced routes, human checkpoint)
```

Any change to Module 1 would require regenerating all of the above. That is precisely
why Module 2 is built as a separate, additive package and why promotion — if it were
ever earned — would be a documented, reviewed decision rather than a silent overwrite.
