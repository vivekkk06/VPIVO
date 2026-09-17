# Model Card — Supervised Process Classifier (Dataset A)

**Status: RESEARCH / VALIDATION SIGNAL. Not promoted into the canonical pipeline.**
**Artifact:** `reports/day7/process_classifier_experiment.json`
**Script:** `scripts/run_process_classifier_experiment.py`

---

## 1. Objective

Answer a question Day 6 raised but could not settle without labels:

> Can a supervised model recover business-process identity from **behaviour alone**,
> or does it still need to be told **which system** the user is in?

Day 6's unsupervised clustering found behavioural features agree only weakly with
process identity (ARI 0.264) while adding system identity reaches 0.661, and concluded
that *"process identity lives in system context, not behaviour."* That was measured
without labels. This model tests the same claim with supervision, which is a stronger
instrument.

**Why this matters downstream:** Dataset-B processes are labelled by exact-match
`dominant_context` (system identity). If behaviour alone were sufficient, that choice
would be leaving information unused. If it is not, the Day-3 decision is confirmed by
a second, independent method.

## 2. The task I rejected first, and why

The obvious ML task here is *"predict whether a process is a good automation
candidate."* **It was considered and rejected as circular.** The only available labels
would derive from the Opportunity score the model is supposed to support, so the model
would learn my own scoring function and prove nothing about the world. A classifier
that "validates" its own training signal is worse than no classifier, because it
looks like corroboration.

No independent automation-suitability labels exist in this data, so no supervised
automation-suitability model was built. That is a deliberate omission, not a gap.

## 3. Dataset

| | |
|---|---|
| Source | Dataset A ground truth (`gt_manifest.json`) |
| Executions available | 2,009 |
| **Executions used** | **1,734** (closed executions containing ≥2 events) |
| Classes | **15** process codes (A–O) |
| Class balance | 102–169 per class — well balanced, no minority-class problem |
| Sessions | 63 |

Excluded: open executions (no `end_ts`, so no interval to slice) and executions
spanning fewer than 2 events. Both exclusions are structural, not filtering for
performance.

**Idealised isolation condition — stated explicitly.** For feature extraction, GT
execution boundaries were used to isolate each execution; therefore, this experiment
evaluates process-identity classification given a correctly isolated execution and
does not evaluate end-to-end segmentation. This is **not label leakage** — the labels
are independent GT `process_code` values and the split is session-grouped — but the
classifier is handed perfect execution boundaries, which the real pipeline never has
(§2.1 of the final report puts boundary F1 at 0.3440). An end-to-end system would
have to classify executions recovered by segmentation, and would be correspondingly
harder.

## 4. Label definition

`process_code` from the Dataset-A ground-truth manifest — recorded by whoever
produced the dataset. **Independent of every analytical artifact in this project.** It
is not derived from segmentation, from `dominant_context`, or from the Opportunity
score.

## 5. Features

Two deliberately contrasting sets. The split *is* the experiment, so it is enforced
structurally rather than by convention.

**Behavioural only (32 features)** — duration and log-duration, event count, events
per second, interaction-category fractions (12), event-type fractions (14), distinct
category/type counts, manual-event share, extracted-text share, and **counts** of
distinct applications, app switches and window titles.

**With system identity (52 features)** — the above plus application-share (10) and
browser-domain-share (10) features.

The discipline: `n_distinct_applications` is a **count** (behavioural — how much
switching happens) and lives in both sets; **which** application it is lives only
behind the identity flag.

## 6. Preprocessing

Fractions are computed per execution, so length does not dominate. Logistic regression
is wrapped in a `StandardScaler`; the random forest is unscaled (it does not need it).
Vocabularies for categories, types, applications and domains are taken from the
dataset's most frequent values and recorded in the artifact, so the feature vector is
inspectable rather than implicit.

## 7. Split strategy and leakage controls

**`GroupKFold(n_splits=5)` grouped by session.** No session appears in both train and
test.

This matters more than usual here: executions within one session share an operator, a
machine, a time window and often a task batch. A random split would place
near-duplicate executions on both sides and inflate every number below. Session-level
grouping is the same discipline used for the segmentation work (leave-one-session-out)
and is applied for the same reason.

## 8. Baselines

Two, both evaluated under the identical split: `most_frequent` and `stratified`. With
15 balanced classes, a stratified guess scores macro F1 **0.0646** — that is the
number any model has to beat to be doing anything at all.

## 9. Models and hyperparameters

| Model | Configuration |
|---|---|
| Logistic regression | `max_iter=2000`, `random_state=0`, standardised inputs |
| Random forest | `n_estimators=300`, `random_state=0`, `n_jobs=-1` |

Started simple, as planned. No gradient boosting or neural model was tried, because
the result below is decisive enough that a stronger learner would not change the
conclusion — it would only change the size of a gap that is already unambiguous.

## 10. Metrics

| Variant | Model | Macro F1 | Accuracy |
|---|---|---:|---:|
| behavioural only | majority baseline | 0.0206 | 0.0675 |
| behavioural only | stratified baseline | 0.0646 | 0.0686 |
| behavioural only | logistic regression | 0.2624 | 0.2843 |
| **behavioural only** | **random forest** | **0.2892** | 0.3028 |
| with system identity | logistic regression | 0.5675 | 0.5761 |
| **with system identity** | **random forest** | **0.5948** | 0.6021 |

**Headline: identity uplift +0.3056 macro F1 — system identity roughly doubles it.**

Macro F1 is the primary metric: classes are balanced, and macro weighting prevents a
few easy classes from masking failures on hard ones. Accuracy is reported alongside,
never alone.

**Feature importances agree.** The three most important features in the
identity variant are all `domain::` features (0.0732, 0.0701, 0.0643); the strongest
behavioural features (duration 0.0798, events-per-second 0.0718) lead in the
behavioural variant but are not enough on their own.

**Per-class spread is wide.** With identity: best class I at F1 0.9469, worst class H
at 0.2822. Behaviour only: best I at 0.8139, worst J and K at 0.0725. Some processes
are behaviourally distinctive; most are not.

**Cost:** ~0.44 s mean fit (behavioural), ~0.54 s (identity), on 1,734 × 32/52.

## 11. Result and interpretation

Two findings, and the second is the one worth carrying:

1. **Behaviour alone is not useless** — 0.2892 is ~4.5× the stratified baseline, so
   duration, pace and interaction mix genuinely carry process signal. Day 6's ARI
   0.264 slightly understated it.
2. **But behaviour alone is not sufficient** — adding system identity roughly doubles
   macro F1. **Day 6's conclusion survives a stronger test, with a sharper number
   attached.**

## 12. Intended use

- **Methodological validation.** Evidence that the Day-3 decision to group Dataset-B
  processes on system context was correct, now confirmed by a supervised method.
- **A supporting signal in the Decision Center**, clearly labelled as such.

## 13. Prohibited use

- **Not** a reason for the HR/Payroll selection. That recommendation comes from the
  analytical framework (handling time, operator coverage, Pareto, sensitivity) and is
  unchanged by this model. Presenting a model output as the reason would be
  retrofitting a justification.
- **Not** for relabelling Dataset B. It is trained on Dataset-A processes and systems;
  Dataset B has different departments, applications and process codes. There is no
  evidence it transfers, and macro F1 0.5948 would not be accurate enough even if it
  did.
- **Not** for automated decisions of any kind. Nothing in the pipeline consumes its
  output.

## 14. Limitations

- **Single dataset, single recording environment.** Transfer is untested and, given
  Dataset B's different process population, probably poor.
- **Macro F1 0.5948 is moderate.** Useful for a comparative claim, not for labelling.
- **1,734 of 2,009 executions used** — open and ultra-short executions are excluded.
- **Ground truth is evidence, not an oracle.** Day 1 found a cross-file disagreement
  and an abandoned execution; those labels are used as given.
- **Fixed vocabularies** (top 10–14 values) drop rare applications and domains.
- **No calibration analysis.** Probabilities are not used anywhere, so they were not
  validated — and an uncalibrated probability shown as "confidence" would mislead.

## 15. Failure cases

- **Classes H, J, K, E** are poorly separated even with identity (F1 0.28–0.34) —
  plausibly processes sharing the same system, where identity cannot discriminate and
  behaviour is too weak.
- **Behaviour-only collapses on J and K** (F1 0.0725) — near-total failure, not
  graceful degradation.
- **Short executions** carry unstable fractions; a 2-event execution's
  "interaction-category distribution" is close to meaningless.

## 16. Reproduction

```bash
python scripts/run_process_classifier_experiment.py --dataset dataset_a --out reports/day7
```

Deterministic (`random_state=0` throughout, fixed fold assignment).
