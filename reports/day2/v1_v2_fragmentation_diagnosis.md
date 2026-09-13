# Option 1 → Option 4: Why V2 Fragments More, and What That Means for Stage 8

**Investigation only.** No thresholds changed, no features changed, no
new model trained beyond re-running both existing LOSO procedures to get
comparable per-transition predictions. Source:
`scripts/compare_v1_v2_fragmentation.py`.

## Option 1 — the false-positive distribution, measured directly

| | Count |
|---|---|
| Neither model fragments | 83 |
| **Only V1 fragments** (V2 fixed it) | 10 |
| **Only V2 fragments** (V2 broke it) | **81** |
| Both fragment | 1,578 |

Net: 71 more executions fragmented under V2 than V1 (81 − 10), closely
matching the raw percentage-point gap (94.7% − 90.8% = 3.9 points ×
1,752 executions ≈ 68 — consistent, small variance from independent LOSO
re-runs).

**My earlier hypothesis in the Stage 6 report — that V2's false positives
might simply be spread more evenly across more executions while V1's
concentrate — is only half right, and the other half is worse than that
hypothesis implied.** For the 1,578 executions *both* models already
fragment, V2 doesn't just match V1's damage — it adds more of it (mean
3.53 extra segments vs. V1's 3.00). **V2 is not redistributing the same
amount of error differently; it is introducing a genuinely higher volume
of erroneous splits**, both in how many distinct executions get touched
(81 new) and in how badly the already-bad ones get hit.

The 81 "only V2" examples span multiple sessions and process codes (B,
C, F, H, J, M — no single process type dominates) and multiple
executions per session in some cases (e.g. three separate `H`-process
cases in one session all newly fragmented) — this looks like a general
shift in the model's behavior, not an isolated bug tied to one process
or session.

## Option 4 — was continuity-first classification alone ever going to fix this?

**No — and this evidence is why.** The original hypothesis (Stage 3/6 of
the continuity-first pivot) was: *continuity-first classification,
combined with a reconstruction layer that reasons about relative
continuity evidence across multiple transitions, together address
fragmentation.* This stage only tested the classification half — same
"compute a score, cut wherever it crosses a fixed threshold" mechanism
V1 used, just with a different score. **That mechanism was never going
to fix over-segmentation on its own, because over-segmentation is
fundamentally a property of thresholding a noisy per-transition score in
isolation — which is exactly what both V1 and V2 still do.** Swapping
which score gets thresholded doesn't remove the thresholding-in-isolation
problem; V2 confirms this empirically rather than leaving it as a
plausible-sounding claim.

**Why a reconstruction layer specifically is a more promising next step
than more classifier tuning**: the 81 "only V2" false splits are, by
construction, **borderline** decisions — the continuity-probability
crossed the threshold, but these are still segments belonging to one
coherent GT execution, meaning the model's own continuity score between
the erroneously-split pieces is plausibly still comparatively high
relative to a genuine boundary, even though it crossed the fixed cutoff.
A reconstruction layer that looks at the **relative** strength of
evidence across a local neighborhood of transitions (rather than a single
global threshold applied independently to each one) is structurally
positioned to catch exactly this pattern — a lone borderline split
between two segments that otherwise look continuous — in a way a fixed
threshold cannot by definition. **This is a reasoned expectation based on
the evidence above, not yet a measured result** — Stage 8 would need to
build this and measure it before it counts as validated, following the
same discipline as everything else in this project.

## What this means for the stated priority order (Option 1 → 4 → 2 → 3)

Options 1 and 4 are now done: the mechanism is understood, and the
reasoning against "just tune the classifier more" is evidence-backed, not
asserted. Before proceeding to Option 2 (re-select the threshold to
target fragmentation specifically) or Option 3 (revisit the feature set),
worth naming the risk plainly: **Option 2 can only trade recall for
fewer false splits along the same fixed-threshold mechanism just shown to
be the structural limitation** — it may narrow the gap to V1 somewhat,
but per this diagnosis, it cannot be expected to fix the class of error
found here, since that error isn't a threshold-calibration problem, it's
a something-other-than-independent-per-transition-thresholding problem.
Option 3 (feature revisit) has the same ceiling for the same reason.
**Neither is expected, based on this evidence, to close the 81-vs-10 gap
found here** — they may still be worth doing for other reasons (Option 2
was always the planned calibration/trade-off stage regardless of this
finding), but the expectation should be set accordingly rather than
assuming either will resolve fragmentation on its own.

## Files

- `scripts/compare_v1_v2_fragmentation.py`
- `reports/day2/v1_v2_fragmentation_comparison_dataset_a.json`
- `reports/day2/v1_v2_fragmentation_diagnosis.md` — this file
