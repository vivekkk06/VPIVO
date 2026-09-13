# Day 2 — Temporal Feature Construction & Gap Distribution (Stage 4)

**MEASUREMENT.** Source: `scripts/build_feature_table.py` run against all
63 Dataset A sessions with ground truth, producing 162,705 labeled
transitions (`feature_table_dataset_a.json`) and the regime summary
(`time_gap_regime_summary_dataset_a.json`). Reused `src/procmine/segmentation/canonical.py`
(Stage 3) for the per-event representation.

**Scope note (DECISION):** this stage builds features and reports
distributional evidence. It does **not** select a threshold τ or run a
precision/recall/F1 sweep — that requires converting a threshold into
actual boundary predictions and scoring them, which is Stage 5's job
("baseline segmentation"). Doing it here would collapse two stages your
spec keeps separate.

## What was built

- `src/procmine/segmentation/features.py` — `extract_transition_features()`
  (GT-agnostic: runs unchanged on Dataset A, B, or a future dataset) and
  `label_transitions()` (GT-only join, Dataset A here).
- `scripts/build_feature_table.py` — produces the shared `(X_i, y_i)`
  table Stage 5/6 will train/score against.
- 10 new tests (`tests/test_segmentation_features.py`), 68/68 passing
  project-wide.

**A design bug was caught and fixed during this stage, before anything
was run**: the first version of `label_transitions` joined a GT boundary
to a transition by *exact* timestamp equality. That's wrong — a GT
boundary timestamp (from the scenario generator) essentially never
exactly equals a raw event's own `timestamp_ms`, so an exact match would
have silently labeled almost nothing. Fixed to a containment join (does
the boundary fall within `[event_i.ts, event_next.ts)`), which is also
how Stage 2 did it. A second bug in the same area — an edge case where a
boundary timestamp past the end of a session's recorded events matched
the last transition anyway — was caught by a test
(`test_label_transitions_boundary_outside_any_interval_labels_nothing`)
before being fixed.

## Gap distribution by regime (MEASUREMENT)

| Regime | n | Median (ms) | Mean (ms) | p10 | p90 |
|---|---|---|---|---|---|
| Interior (mid-execution) | 161,034 | 52 | 537.5 | 1 | 1,173 |
| Normal boundary | 1,509 | 528 | 3,561.8 | 437 | 4,457 |
| Resume boundary | 162 | 513.5 | 1,984.0 | 444 | 4,117 |
| Chunk-file crossing (any) | 56 | 3,969.5 | 45,129.0 | 50 | 56,205 |
| Chunk-file crossing, not also a GT boundary | 55 | 3,982 | 45,939.9 | 50 | 56,205 |

1,671 of 1,689 GT boundaries (Stage 2's count) were successfully matched
to a transition; the other 18 belong to one session with a real
data-completeness gap, explained below — they're correctly absent from
this table, not a bug.

### Chunk boundaries confirmed temporally distinct from process boundaries (INFERENCE, strongly evidenced)

Chunk-file crossings have a median gap **~7.5x larger** than real process
boundaries (3,970ms vs. 528ms) and a mean **~13x larger** — and critically,
**55 of 56 chunk crossings are not GT boundaries at all**. This adds a
temporal-signature confirmation to what Day 1 already established from
`continues_from_prev`/`continues_to_next` flags: chunk boundaries aren't
just conceptually different from process boundaries, they look
completely different in the data (large, one-off gaps consistent with
the recording agent's own buffer-flush behavior, not user activity
patterns) and essentially never coincide with a real transition. If
`chunk_boundary` is included as a model feature in Stage 5/6, this is
the evidence for expecting it to carry near-zero importance — the
feature is included specifically so that expectation gets tested, not
assumed.

### Resume boundaries look different from normal boundaries (INFERENCE)

Resume-boundary median (513.5ms) is close to normal-boundary median
(528ms), but the **mean is much lower** (1,984ms vs. 3,561.8ms) — resumes
have less of a long right tail. Reading: a genuinely new process
sometimes follows a longer idle/thinking gap; returning to interrupted
work tends not to. Consistent with Stage 2's finding that browser
navigation is *weaker* at resumes while app-switch/extracted-text are
*stronger* — two independent pieces of evidence now point the same
direction: resume and normal boundaries are behaviorally distinguishable,
which is exactly the distinction your spec requires the system make
explicit, not collapse.

### Session-to-session variance argues against one fixed global threshold (MEASUREMENT)

Per-session boundary-gap medians: mean of medians 950.1ms, **std 1009.8ms**
— the spread is nearly as large as the mean — min 467ms, max 5,528ms
(an 11.8x range). **HYPOTHESIS, not yet tested**: a single global gap
threshold will systematically over- or under-segment some sessions no
matter where it's set; an adaptive or session-relative threshold is worth
evaluating in Stage 5's sensitivity sweep rather than assumed to be
unnecessary. This is evidence for investigating it, not proof it's
required — Stage 5 needs to actually compare a fixed vs. adaptive
threshold's measured quality before that's a real decision.

## A new finding: one session has a real data-completeness gap (FACT)

While building the feature table, 18 of Dataset A's 1,689 GT boundaries
failed to match any transition — all 18 in a single session,
`ses_20260701-152030-CHAITANYA0BCF`. Investigated rather than dismissed:

- The session's recorded events end at `15:29:59.864`.
- Its own `gt_manifest.json` says the session runs until `15:46:02.467` —
  **16 minutes of ground-truth-described activity has no corresponding
  raw events at all.**
- Checked against all 10 single-chunk Dataset A sessions for comparison:
  9 of them have events extending slightly *past* their GT end (by a few
  seconds to ~84s — normal trailing activity). This session is the only
  one with events stopping dramatically *before* GT end — a
  one-directional, 962.6-second outlier, not noise.
- `manifest.json`'s `is_session_end`/`next_chunk_id` fields were checked
  as a possible detector for this and ruled out: `is_session_end: False`
  appears on **every** non-final-in-some-sense chunk in the dataset
  (117/117 checked), including chunks we know from Day 1 are correctly
  followed by a real next chunk — these fields are not reliably populated
  by this recording agent and can't be used as a completeness signal.

**DECISION**: added a real, generalizable check —
`audit.session_gt_coverage_check(last_event_ms, gt_session_end_ms)` —
comparing a session's last event against its own GT-declared end, with a
2-minute slack for normal trailing activity. Not Dataset-A-specific:
works for any future dataset that has both an event log and a
GT/reference end time. 4 new tests. Run against all 63 Dataset A
sessions: **flags exactly 1**, confirming this is a rare (1.6%), real,
isolated gap — not a systemic problem, and not something the earlier
structural checks (file presence, non-empty files) could have caught,
since the file that exists is genuinely well-formed, just short.

**Consequence for Stage 5/6**: this session's 18 unrecoverable boundaries
are correctly excluded from the feature table (there's no data to label
them from) — the effective Dataset A boundary count for
training/evaluation is 1,671, not 1,689, and that's now a documented,
understood exclusion rather than a silent gap.

## What this changes going into Stage 5

- The feature table (`X_i`, `y_i`) exists and is reusable — Stage 5
  doesn't need to rebuild it.
- `chunk_boundary` is a real feature, included specifically to let the
  "chunk ≠ process boundary" claim be tested against a model rather than
  assumed.
- Session-level gap variance is real evidence that a fixed global
  threshold's performance should be checked *per session*, not just in
  aggregate, when Stage 5 runs its sensitivity sweep.
- One Dataset A session is known to be an unreliable source for any
  segmentation quality metric involving its missing 16 minutes — worth
  excluding or flagging separately in Stage 5/8's per-session evaluation,
  rather than letting it silently drag down an aggregate score for a
  reason that has nothing to do with the segmentation method.

## Files

- `src/procmine/segmentation/features.py`, `tests/test_segmentation_features.py`
- `scripts/build_feature_table.py`
- `src/procmine/audit.py` (added `session_gt_coverage_check`),
  `tests/test_audit.py` (4 new tests)
- `reports/day2/feature_table_dataset_a.json`,
  `reports/day2/time_gap_regime_summary_dataset_a.json`
- `reports/day2/time_gap_analysis.md` — this file
