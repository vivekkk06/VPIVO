# Module 2 — Dataset-A segmentation experiment (H1, H2)

**Result: MODULE 2 SEGMENTATION IS NOT PROMOTED. Module 1 remains canonical.**

Every candidate improved several metrics. None cleared the pre-registered gate. That
is outcome (B) of the four legitimate outcomes named before the experiment ran.

---

## 1. Observation

Module 1's temporal evidence is absolute (`log1p(delta_t)` against one global
threshold) and its text evidence is a presence bit (`extracted_text_at_transition`).
Neither asks whether *this operator* is unusually slow here, nor whether the screen
*content* changed.

## 2. Method — and the fairness control

Only the classifier feature matrices vary. Candidate union, reconstruction Rules 1–4,
the Strategy_Combined protection layer and the evaluator are **the locked Module 1
code, called unmodified**. An `M1_compatible` control runs through the identical
harness, so any difference is attributable to the added columns and not to a change of
protocol.

**Two threshold protocols are reported**, because either alone invites a fair objection:

| Protocol | Rule | Why |
|---|---|---|
| `matched` | every feature set, control included, selects V1/V2 thresholds by max pooled F1 over LOSO probabilities | Adding columns shifts the probability scale; reusing Module 1's thresholds would handicap Module 2 |
| `locked` | every feature set reuses 0.9078 / 0.8860 | Re-selecting thresholds is itself a degree of freedom, so the un-retuned result is shown too |

**Baseline drift control.** The canonical baseline was reproduced before any candidate
ran, reading `systems.Strategy_Combined.pooled` by name — taking the first block with a
`pooled` key yields V1 (F1 0.2534), an error that actually occurred on Day 7. Measured
drift: **0.0**.

**Validation.** Leave-one-session-out over 63 sessions. Operator baselines are refitted
inside every fold from training sessions only.

## 3. Mathematical definitions

**Operator-normalized timing (H1).** A MAD-scaled robust z-score:

```
z_o(x) = ( log1p(Δt) − median_o ) / MAD_o
```

where `median_o` and `MAD_o` are that operator's log-gap location and dispersion,
fitted on training sessions only. MAD is floored at 1e-6 so a degenerate operator
cannot produce infinity.

*Why MAD-scaled rather than a ratio:* operator **medians** barely differ (52–56 ms,
ratio 1.077), while **dispersion** differs more (MAD of log-gap 1.105–1.404, ≈27%). If
anything distinguishes these operators it is scale, not centre, so the formulation
targets scale. The ratio form suggested in the brief was rejected on this measurement.

**Content drift (H2).**

```
J(A,B)    = |A ∩ B| / |A ∪ B|
D_content = 1 − J(A,B)
```

over token sets from the N=10 event windows either side of the transition — the same
window convention the locked V2 model already uses.

## 4. Feature availability — measured before modelling

| Formulation | Transitions where computable | Verdict |
|---|---:|---|
| Adjacent-event-pair text Jaccard | **48 / 162,705 (0.03%)** | **Rejected on coverage.** This was the first formulation tried |
| N=10 window text Jaccard | **18,715 / 162,705 (11.50%)** | Usable |

Window Jaccard distribution: median 0.0857, mean 0.3265, 16.6% fully disjoint, 1.0%
identical — a real spread, not a degenerate constant.

Where either window has no text, the feature is reported as **unavailable** and paired
with a `content_drift_available` indicator. It is never imputed as 0 (identical) or 1
(disjoint); both would be fabricated evidence.

Operator baselines: across 63 folds × 8 operators, **all 504 were operator-fitted** and
the documented global fallback never fired. The fallback exists for robustness on
future data, not because Dataset A needed it.

## 5. Results

### Matched protocol (the fair comparison)

| Feature set | F1 | ΔF1 vs control | Precision | Recall | Frag % | Under | Over |
|---|---:|---:|---:|---:|---:|---:|---:|
| `M1_compatible` (control) | 0.3417 | — | 0.2359 | 0.6194 | 78.37 | 0.1507 | 1.5605 |
| `M2A` operator timing | 0.3490 | +0.0073 | 0.2409 | 0.6332 | 77.45 | 0.1451 | 1.5508 |
| `M2B` content drift | 0.3465 | +0.0049 | 0.2382 | 0.6355 | 78.77 | 0.1420 | 1.5908 |
| **`M2C` both** | **0.3519** | **+0.0102** | 0.2436 | 0.6338 | **76.94** | 0.1452 | **1.5320** |

### Locked protocol (Module 1's own thresholds)

| Feature set | F1 | ΔF1 vs control | Recall | Frag % |
|---|---:|---:|---:|---:|
| `M1_compatible` | **0.3440** (= canonical exactly) | — | 0.6355 | 79.05 |
| `M2A` | 0.3430 | −0.0010 | 0.6260 | 77.97 |
| `M2B` | 0.3448 | +0.0008 | 0.6284 | 78.77 |
| `M2C` | 0.3457 | +0.0017 | 0.6212 | 77.45 |

M2C versus the **canonical shipped number** (0.3440233…): **+0.0079** matched,
**+0.0017** locked.

## 6. The pre-registered gate

Registered before any candidate was scored, and **not adjusted afterwards**. It is the
Day-7 segmentation-challenge gate reused verbatim, so Module 2 is held to exactly the
standard the previous challenge faced.

| Gate | Threshold | M2C (matched) | Pass |
|---|---|---|:--:|
| 1 · F1 absolute gain | ≥ 0.02 | +0.0102 | ❌ |
| 2 · Recall | ≥ 0.55 | 0.6338 | ✅ |
| 3 · Fragmentation | ≤ 81.05% | 76.94% | ✅ |
| 4 · Under-segmentation | ≤ 0.2823 | 0.1452 | ✅ |
| 5 · Over-segmentation | ≤ 2.0041 | 1.5320 | ✅ |
| 6 · Sessions degraded | ≤ 40% | 8/63 = 12.7% | ✅ |
| 7 · Gain survives dropping top-3 sessions | required | 0.3282 → 0.3349 | ✅ |
| 8 · Gain survives dropping most-improved operator | required | 0.0087 → 0.0073 | ✅ |

**M2C fails on gate 1 alone.** Under the locked protocol it additionally fails gates 7
and 8. Every candidate fails gate 1 under both protocols.

### Robustness (M2C, matched)

30 sessions improved, 8 degraded, 25 unchanged. Per-session ΔF1: mean 0.0087, median
0.0055, min −0.040, max +0.0563, sd 0.021. Gain by operator ranges 0.0003
(CHAITANYA0BCF) to 0.0252 (yuvraj) and survives removing the most-improved operator.

So the improvement is **real and broad** — it is simply **too small**.

## 7. Interpretation

**H1 — weakly supported, mechanism mostly absent.** The premise barely holds in this
data: operator median gaps span 52–56 ms (ratio 1.077), median log-gap spread is 0.073,
and only 40% of session-median variance is between-operator. `dwell_scale` is 1.4 for
every session — the generator never varied operator speed. Normalizing against
near-identical baselines cannot do much, and it did not. The +0.0073 it contributes is
consistent with the small dispersion difference that does exist, not with the effect
the hypothesis imagined.

**H2 — supported in direction, limited by coverage.** Content drift improves recall
(0.6194 → 0.6355) and under-segmentation at essentially unchanged fragmentation. But it
is computable on 11.50% of transitions; on the other 88.50% the model sees an imputed
zero and an indicator. A feature that abstains on seven transitions in eight cannot
move a pooled metric far, and did not.

**Together they are complementary rather than redundant.** M2C (+0.0102) exceeds
M2A (+0.0073) and M2B (+0.0049) and beats their sum on fragmentation (−1.43pp, the
largest of the three), which is what one would expect from features carrying different
information. That is the most interesting positive finding here — and it is still
inside the noise band the gate was set to exclude.

## 8. Limitations

- Threshold re-selection in the `matched` protocol is a global model-selection step on
  pooled out-of-fold evidence, mirroring Module 1's own method — not nested CV.
- Dataset A is synthetic; a constant `dwell_scale` of 1.4 is a property of the
  generator. **H1 could behave very differently on real operators**, and this
  experiment cannot say whether it would.
- Text coverage is a property of this capture configuration. A capture with richer OCR
  would give H2 far more to work with.
- Module 2 features were added to **both** V1 and V2 matrices; adding to only one was
  not explored.
- Runtime roughly doubles (87.6s → 132.0s per LOSO sweep) for the added columns.

## 9. Decision

**MODULE 2 SEGMENTATION IS NOT PROMOTED.** No canonical artifact is regenerated, no
threshold is changed, and `segments.jsonl` is untouched. Module 1 remains the canonical
segmentation for every downstream conclusion.

The gate was not moved to let the best candidate through, and the result is reported
with its improvements intact rather than minimised: M2C is genuinely better on five of
six reported metrics, and still not better enough to justify invalidating every
downstream number.
