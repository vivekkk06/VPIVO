# Day 2 — Signal Evaluation

**MEASUREMENT.** All numbers below are from `scripts/evaluate_signals.py`
run against Dataset A: 63 sessions with ground truth, 1,689 boundaries
(163 resume-type, 1,526 normal — see "Resume tagging" below for how that
split is derived). Window: ±2000ms, matching Day 1's original convention.
Raw output: `signal_evaluation_dataset_a.json`. Nothing here uses Dataset
B, and nothing in the evaluated code is specific to Dataset A's session
IDs, applications, or process labels — see `src/procmine/segmentation/signals.py`.

## Reproduction check (FACT)

Day 1's three signal numbers were computed with ad-hoc terminal commands,
never saved as code — flagged as a gap in the prior completion audit. This
script now reproduces them exactly:

| Signal | Day 1 (ad-hoc) | This script | Match |
|---|---|---|---|
| Deduplicated app-switch coverage | 68.1% | 68.1% | ✓ |
| Extracted-text coverage | 64.2% | 64.2% | ✓ |
| Boundary gap median / mid-execution gap median | 526ms / 52ms | 526ms / 52ms | ✓ |

The method is now reproducible from a checked-in script, closing that gap.

## Full results, all six signals (MEASUREMENT)

| Signal | Coverage | Resume cov. | Normal cov. | Precision | Lift | Distance median (aligned) | Per-session mean±std | Per-session min–max |
|---|---|---|---|---|---|---|---|---|
| App-switch (deduplicated) | 68.1% | 72.4% | 67.6% | 23.2% | 3.61 | 354ms | 0.678 ± 0.121 | 0.231 – 0.913 |
| Extracted-text presence | 64.2% | 69.3% | 63.6% | 17.8% | 1.55 | 390ms | 0.643 ± 0.132 | 0.231 – 0.870 |
| **Browser navigation** | **64.2%** | 55.8% | 65.1% | **66.2%** | **13.98** | 1,570ms | 0.634 ± 0.246 | **0.000** – 0.889 |
| Window-title change | 0.2% | 0.0% | 0.2% | 0.7% | 0.048 | 1,432ms | 0.002 ± 0.007 | 0.000 – 0.040 |
| Clipboard change | 0.4% | 0.0% | 0.4% | 0.1% | 0.008 | 976ms | 0.004 ± 0.030 | 0.000 – 0.240 |

**Coverage** = fraction of GT boundaries with the signal firing within
±2s (Day 1's "alignment"). **Precision** = fraction of the signal's own
firings that land within ±2s of *any* boundary. **Lift** = (rate of this
signal among events near a boundary) ÷ (rate of this signal among events
in the interior of an execution) — this is new relative to Day 1, and
it's the metric that actually answers "is this signal boundary-specific,
or just common" rather than "does it look correlated."

## Resume tagging (DECISION, documented)

A transition is tagged `is_resume` when the next execution carries a
`split_id` (continuing a suspended split) or shares the previous
execution's `case_id` (the same case resuming) — see
`extract_boundaries()`. This directly operationalizes the "true
transition vs. interruption/resumption" distinction your spec requires be
handled explicitly, rather than left implicit. 163 of 1,689 boundaries
(9.7%) are resume-type in Dataset A.

## Findings, by signal

### Window-title change — HYPOTHESIS REJECTED

**INFERENCE**: this signal is not useful for boundary detection as
defined here. Lift 0.048 means it's actually **less** common near
boundaries than mid-execution — the opposite of what the hypothesis
predicted. 0% coverage at resume boundaries specifically. This is a
legitimate negative result, not a measurement failure: `window_title_change`
only fires 451 times total across 63 sessions (vs. 50,588 `app_switch`
events), so it's both rare and, per this measurement, not concentrated
where it would need to be to matter. **DECISION**: drop from the feature
set unless a different formulation (e.g. title *similarity* rather than
title-change-event presence) is tested later — that's a different,
unevaluated hypothesis, not the same one restated.

### Clipboard timing — HYPOTHESIS REJECTED (for boundary presence)

**INFERENCE**: same conclusion as window-title, lift 0.008 — clipboard
activity is heavily concentrated *inside* executions (consistent with
copy/paste being a mid-task action), not at their edges. **DECISION**:
drop as a boundary-presence signal. Note this doesn't rule out clipboard
*content* (case-ID linkage via `gt.jsonl`'s `content_preview`) as useful
for a *different* purpose — process identity/fingerprinting (Phase 16),
not boundary detection. That's a separate hypothesis for a later stage.

### Browser navigation — STRONGEST SIGNAL MEASURED SO FAR (MEASUREMENT + INFERENCE)

**FACT**: 64.2% coverage, 66.2% precision, lift 13.98 — an order of
magnitude more boundary-concentrated than app-switch (3.61) or
extracted-text (1.55). This was not asserted from Day 1's case-study
screenshots; it's measured against all 1,689 boundaries.

Two caveats, both real, both worth weighing before treating this as a
primary signal:

1. **Asymmetric at resume boundaries** (55.8% vs. 65.1% at normal
   boundaries) — the opposite pattern from app-switch/extracted-text,
   which are both *stronger* at resumes. **INFERENCE**: a genuinely new
   process is more likely to involve fresh navigation than work resuming
   in an already-open context. This is evidence, not proof — it's one
   dataset's worth of resume cases (163).
2. **High per-session variance** (std 0.246, one session at exactly
   0.000 coverage). **INFERENCE**: this signal's strength depends on how
   browser-centric a session's work is — a session with little browser
   activity will have this signal contribute nothing, which is a real
   generalization risk given the project's own requirement not to assume
   Dataset A's application mix transfers to a future dataset. This needs
   checking against Dataset B's browser-activity profile before being
   trusted there (exploratory only, per Phase 18 — not used to tune
   anything).
3. **Looser timing**: median distance-when-aligned is 1,570ms, vs. 354ms
   for app-switch — when browser navigation does align with a boundary,
   it's less precisely timed. Combined with high precision/lift, this
   reads as "a reliable presence signal, not a precise timing signal."

### App-switch and extracted-text — CONFIRMED, WITH NEW DETAIL

Both reproduce Day 1's headline numbers and add: both are **stronger at
resume boundaries than normal ones** (app-switch 72.4% vs 67.6%;
extracted-text 69.3% vs 63.6%) — the opposite pattern from browser
navigation. **INFERENCE**: resuming interrupted work still involves
switching back into an application/reading the screen, even when it
doesn't involve fresh navigation. Both have tight aligned-distance medians
(354ms/390ms) — precise timing signals, unlike browser navigation.

### A redundancy question raised, not yet answered

Browser-navigation's coverage (64.2%) exactly matches extracted-text's
(64.2%) to one decimal place. **UNKNOWN whether this is coincidence or
overlap** — e.g. extracted_text may be disproportionately attached to
browser_navigation events the same way Day 1 found it's disproportionately
attached to app_switch events. Not resolved here; flagged for the
ablation stage (Phase 9), where signal redundancy is explicitly in scope.

## Gap-size analysis (MEASUREMENT, unchanged from Day 1, now reproducible)

Boundary gap median 526ms vs. mid-execution gap median 52ms (~10x);
mean 3,409ms vs. 486ms (~7x), computed the same way as Day 1: the gap
straddling a boundary timestamp vs. gaps strictly inside a closed
execution's own interval. 1,671 boundary gaps, 137,450 mid-execution gaps
measured.

## What this changes going into Phase 3 (temporal model) and Phase 6 (boundary scoring)

- Six signals now have real numbers, not five measured + one assumed.
  Two of the three new hypotheses failed; that's a usable result, not a
  wasted measurement.
- Browser navigation is a candidate for the strongest single feature in
  the eventual boundary score — but its generalization risk (session
  variance, resume-asymmetry) means it shouldn't be weighted as heavily
  as its raw lift number alone would suggest without more evidence.
- The resume/normal split, built here for evaluation, is reusable
  machinery for Phase 7 (execution reconstruction) — it's exactly the
  distinction that layer needs to make.

## Remaining uncertainty

- Whether window-title *similarity* (not just change-event presence) or
  clipboard *content linkage* are viable under a different formulation —
  not tested, not ruled out.
- Whether browser-navigation's strength holds on Dataset B given its
  different application mix — unmeasured, and per your Phase 18
  instruction, must not be used to tune anything even when it is checked.
- The apparent extracted-text/browser-navigation overlap — unresolved.

## Files

- `src/procmine/segmentation/signals.py` — new, reusable, tested (12 new
  tests, `tests/test_segmentation_signals.py`)
- `scripts/evaluate_signals.py` — new CLI
- `reports/day2/signal_evaluation_dataset_a.json` — raw output
- `reports/day2/signal_evaluation.md` — this file
