# Module 2 — Hypotheses

**Module 2 — Adaptive Evidence-Guided Reconstruction & Automation** is an independent
Day-6 engineering approach. It is **not** an AI model: it is a pipeline built from
deterministic features, rules and gates, using the same logistic-regression classifiers
Module 1 already uses. Where a learned component appears, it is the *existing* one.

> Module 1 is the locked baseline used by the canonical downstream analysis. Module 2
> is an independent experimental approach and does not modify Module 1.

---

## 1. Observation

Module 1 reaches F1 **0.3440** on Dataset A with precision **0.2358** — roughly three
false boundaries for every true one — and leaves **79.05%** of ground-truth executions
fragmented. Day 6 (ensembles, HMM, clustering) and Day 7 (four rule-based candidates)
both failed to beat it, which is evidence the *architecture* is sound but not evidence
that its *evidence base* is complete.

Two things Module 1 never looks at stand out:

1. **Timing is absolute.** `log1p(delta_t)` is compared against one global threshold for
   every operator. If operators work at different speeds, the same pause means
   different things for different people.
2. **Text is a presence bit.** `extracted_text_at_transition` says screen text existed.
   It never asks whether the content *changed*. Two adjacent events can both show text
   and be about entirely different work.

## 2. Why Module 1 was not sufficient to test this

Module 1 cannot answer these questions by re-tuning, because the information is not in
its feature matrix. Testing them requires *adding columns*, which changes the model —
and changing the model in place would destroy the fixed reference every downstream
number depends on. Hence a separate, additive module.

## 3. The hypotheses

Each is stated with the mechanism that would make it true, the condition that would
make it false, and what evidence would settle it.

| # | Hypothesis | Why it might help | When it would hurt / fail |
|---|---|---|---|
| **H1** | Operator-normalized timing reduces false distinctions caused by individual operator speed | A 2-second pause from a fast operator is more anomalous than from a slow one; normalizing recovers that | If operators have near-identical timing distributions, normalization is a no-op that only adds variance |
| **H2** | Observable content drift from `extracted_text` adds evidence beyond temporal/application features | Screen content changing across a transition is direct evidence of a different task | If text coverage is too sparse, the feature is mostly imputed and carries no information |
| **H3** | Dataset-B screenshot sampling gives a useful qualitative sanity check despite no ground truth | A human can see whether a boundary looks defensible | Screenshots may be too far from the boundary in time, or missing |
| **H4** | Converting execution time into transparent effort proxies is more decision-useful than a normalized score alone | Hours are interpretable; a 0–1 score is not | Without an operator cost rate, no monetary figure can be produced at all |
| **H5** | Operator-level variant behaviour reveals rollout/training risk hidden by process-level averages | A single operator driving the detour rate is a training signal, not a process signal | With few operators and small samples, apparent differences may be sampling noise |
| **H6** | A Pareto frontier communicates automation trade-offs more transparently than one weighted ranking | Frontier membership is weight-free, so it cannot be argued away by re-weighting | A frontier returns a set, not a ranking, and cannot break ties |
| **H7** | A pre-flight variant-routing gate can prevent automation attempting executions outside the evidenced dominant path | Variant identity is already established deterministically by the Day-3 forensics | A conservative gate also refuses genuine dominant-path executions, costing coverage |
| **H8** | A post-action visual audit gives additional evidence the intended UI state was reached | Pre-action safety cannot confirm an outcome that has not happened yet | A screenshot proves a screen state, never a business record |

## 4. What would cause Module 2 to be rejected

Registered before any experiment ran:

- **Segmentation:** failure to clear the pre-registered promotion gate (§`module2_segmentation.md`).
  The gate is the Day-7 challenge gate, reused verbatim.
- **H2 specifically:** if the feature is computable on too small a share of transitions,
  it is rejected on coverage rather than on results — and the coverage number is
  reported either way.
- **H5:** if operator differences fall inside sampling noise, the hypothesis is not
  supported, however suggestive the raw percentages look.
- **H7:** if the gate admits any non-dominant execution, it has failed at its only job.

## 5. Leakage rules binding every hypothesis

No ground-truth field is used as a feature anywhere: not `process_code`, `case_id`,
`process_variant`, GT boundaries, GT execution spans, nor `dwell_scale` — which lives
in `gt_manifest.json` and is therefore off limits however tempting a per-session speed
parameter is. Operator baselines are refitted inside every fold on training sessions
only. A structural test parses the feature module and fails if any GT identifier
appears in its code.

## 6. Dataset rules

Dataset A has ground truth and is the only place supervised metrics are computed.
**Dataset B is used for operational validation, not supervised segmentation
evaluation** — no accuracy, precision, recall or F1 appears in any Dataset-B artifact.

## 7. Decision recorded elsewhere

Outcomes per hypothesis are recorded in `module2_final_decision.md`. All four outcomes
named in the brief were treated as legitimate in advance, including outright rejection.
