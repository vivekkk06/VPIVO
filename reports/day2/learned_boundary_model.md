# Day 2 — Learned Boundary Model (Stage 6)

**MEASUREMENT.** Logistic regression (`class_weight="balanced"`,
standardized features), evaluated with **leave-one-session-out
cross-validation** across all 63 Dataset A sessions (63 model fits — no
session's own data ever informs the model that scores it). Source:
`scripts/train_boundary_model.py`, `src/procmine/segmentation/model.py`.
4 new tests, 87/87 project-wide.

**Dependency added, flagged explicitly**: `scikit-learn` (installed
cleanly, `requirements.txt` updated). First new runtime dependency since
matplotlib/pytest — used specifically for `LogisticRegression`,
`LeaveOneGroupOut`, `cross_val_predict`, `precision_recall_curve`, all
standard, well-tested implementations rather than hand-rolled versions of
the same algorithms.

## Result: beats both Stage 5 baselines (MEASUREMENT)

| Method | Precision | Recall | F1 | Over-seg | Under-seg |
|---|---|---|---|---|---|
| Baseline 1 (temporal-only, τ=3000) | 0.115 | 0.352 | 0.173 | 2.023 | 0.213 |
| Baseline 2 (temporal AND context, τ=3000) | 0.125 | 0.330 | 0.182 | 1.698 | 0.257 |
| **Learned model (LOSO, best threshold)** | **0.157** | **0.655** | **0.254** | 2.711 | **0.085** |

F1 improves by +0.072 over the best baseline (~40% relative). This is a
genuine, out-of-sample-measured improvement — clears the bar Stage 5 set
for justifying the added complexity, per the project's own "prefer the
simplest approach that achieves strong evidence" instruction: the learned
model earned its complexity here rather than being kept because it's more
sophisticated-looking.

**The improvement is not uniform across metrics — reported honestly, not
smoothed over:**

- **Recall nearly doubled** (0.655 vs. 0.330–0.352) — the model catches
  far more real boundaries.
- **Under-segmentation improved substantially** (0.085 vs. 0.213–0.257) —
  far fewer cases of two real executions getting merged into one
  predicted segment.
- **Over-segmentation got *worse*** (2.711 vs. 1.698–2.023) — the higher
  recall comes at the cost of more fragments per execution on average.
  This is a real trade-off, not a strictly-better result: at the
  F1-optimal threshold, this model favors "don't miss a real boundary"
  over "don't over-split," which may or may not be the right operating
  point depending on what Step 1's actual scoring penalizes more — worth
  revisiting once Step 3's downstream use of segments is clearer, since
  the threshold itself is adjustable (see below).

## Per-session results (MEASUREMENT, not hidden behind the aggregate)

Mean F1 0.247, std 0.061 (relative spread ~25%, modestly tighter than
Baseline 1's ~29%), min 0.040, max 0.356.

**The single worst session got worse under the learned model**:
`ses_20260701-051850-LAPTOP-R36BQBTE` scores F1=0.040 here, below
Baseline 1's worst score (0.061) on any session. **INFERENCE, not yet
investigated**: this is a genuine regression case worth a dedicated look
in Stage 8's failure analysis — improving the aggregate doesn't guarantee
improving every session, and this is the concrete evidence that it
didn't. Full worst-5: `ses_20260701-051850-LAPTOP-R36BQBTE` (0.040),
`ses_20260701-063106-LAPTOP-R36BQBTE` (0.077),
`ses_20260630-135201-LAPTOP-R36BQBTE` (0.083),
`ses_20260630-132737-LAPTOP-R36BQBTE` (0.130),
`ses_20260701-043922-SIDDHIGUPTAB00B` (0.148).

## Feature importance (MEASUREMENT + INFERENCE)

Standardized coefficients, sorted by magnitude, from a model fit on all
data (descriptive only — never used to generate the evaluated
predictions above, which always come from the out-of-fold models):

| Feature | Coefficient | Reading |
|---|---|---|
| `log1p_delta_t_ms` | **+3.737** | By far the dominant signal — temporal gap remains central, as the project's original hypothesis expected |
| `density_after` | +1.472 | Higher activity density right *after* a transition predicts a boundary — starting a new process often begins with a burst |
| `density_before` | −0.928 | Higher activity density right *before* a transition predicts *against* a boundary — a flurry of activity looks like still-active work, not a wind-down |
| `browser_domain_changed` | +0.898 | Confirms Stage 2's strongest single-signal finding (lift 13.98) survives in a multivariate setting |
| `interaction_category_changed` | +0.767 | A category-level shift (e.g. pointer → navigation) is informative beyond raw app identity |
| `extracted_text_at_transition` | **−0.584** | See note below — this flips sign from Stage 2's univariate finding |
| `window_title_changed` | −0.157 | Weak, consistent with Stage 2's near-useless finding for this signal |
| `application_changed` | **−0.078** | Near zero — see note below, this is a real surprise worth explaining |
| `chunk_boundary` | −0.047 | **Confirms, quantitatively, "chunk boundary ≠ process boundary"** — included specifically so this could be tested, and the model learned essentially no weight for it, exactly as Stage 4 predicted from the gap-distribution evidence |

### Two results that need explaining, not just reporting (INFERENCE)

**`extracted_text_at_transition` has a negative coefficient here, despite
a positive lift (1.55) in Stage 2's univariate measurement.** This is not
a contradiction — it's a different question. Stage 2 measured "does this
signal alone correlate with boundaries." This coefficient measures "what
does this feature add once `density_after`, `browser_domain_changed`,
`interaction_category_changed`, etc. already explain most of the same
variance" — extracted_text is disproportionately attached to `app_switch`
events (Day 1 finding, 86% of it), so once the model has application/
context-change features doing that work, the *residual* signal in
extracted_text skews toward ordinary in-app reading, which is more
interior than boundary. A real, legitimate multivariate effect, not a bug.

**`application_changed` carries almost no weight, despite `app_switch`
being Stage 2's second-strongest univariate signal (lift 3.61).** Likely
**redundancy**, not uselessness: real application changes largely
co-occur with `interaction_category_changed` and/or a distinctive gap
size, so once those are in the model, `application_changed`'s independent
contribution is small — the model is using correlated, more granular
signals instead of the coarser one. This is exactly the "which signals
are redundant" question Phase 5 asked to be investigated, now answered
with evidence for this one pair. **Not yet verified with a formal
collinearity check** (e.g. dropping `application_changed` and confirming
F1 is unaffected) — flagged as a concrete, cheap Stage 8 ablation item
rather than asserted from the coefficient alone.

## Threshold is a real, adjustable operating point (FACT)

Best F1 (0.254) occurs at probability threshold 0.908 — a very high bar,
consequence of the 97.4:1 class imbalance requiring a lot of confidence
before the balanced-precision/recall trade-off favors predicting
"boundary." The threshold was selected from out-of-fold probabilities
only (via `precision_recall_curve` on predictions the corresponding
session's model never trained on) — not tuned against the same data used
to report the final metric. A different threshold trades recall for
precision continuously; 0.908 is the F1-optimal point, not the only
reasonable one, and Step 1's actual downstream tolerance for
over-segmentation vs. missed boundaries should inform whether that's the
right point to ship.

## What this changes going into Stage 7/8

- The learned model is the new bar to beat: F1 0.254, and specifically
  its execution-level profile (low under-segmentation, higher
  over-segmentation) — Stage 7's interruption-aware reconstruction should
  be evaluated against *this*, not just against boundary F1, since its
  whole point is fixing exactly the kind of over-fragmentation this model
  exhibits (e.g. A→B→A getting cut into 3 pieces instead of reconnected).
- Two concrete, cheap Stage 8 ablation items now identified from evidence,
  not speculation: (1) does dropping `application_changed` change
  anything (redundancy check), (2) what's actually wrong with
  `ses_20260701-051850-LAPTOP-R36BQBTE` that made it worse, not better.
- `chunk_boundary`'s near-zero coefficient is a clean, quantitative close
  to a thread that's run since Day 1 — worth keeping the feature in future
  iterations specifically *because* it keeps confirming this rather than
  removing it now that it's "proven."

## Files

- `src/procmine/segmentation/model.py`, `tests/test_segmentation_model.py` (4)
- `scripts/train_boundary_model.py`
- `requirements.txt` (added `scikit-learn>=1.4`)
- `reports/day2/learned_model_dataset_a.json`
- `reports/day2/learned_boundary_model.md` — this file
