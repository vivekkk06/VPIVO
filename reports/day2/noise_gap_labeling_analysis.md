# Stage 3 (pre-training) — Noise-Gap Structure & Continuity-Label Options

**No model trained. No labels finalized. No Dataset B use.** This is
exactly the investigation the stop condition asked for: quantify the
structure, present options, wait for a decision.

## Method

For every transition in Dataset A (162,705 total, 63 sessions), classify
both endpoints (`event_i`, `event_next`) by which GT execution's
`[start_ts, end_ts]` span contains each — reusing exactly the same
containment logic already validated in Stages 2/4, no new matching
convention introduced. Source: `scripts/analyze_noise_gap_structure.py`.

## Category breakdown (MEASUREMENT)

| Category | Count | % of all transitions | Current `is_boundary` label |
|---|---|---|---|
| **SAME_EXECUTION** (both endpoints in the same execution) | 137,450 | 84.48% | always `False` |
| **NOISE_TO_NOISE** (neither endpoint in any execution) | **23,171** | **14.24%** | always `False` |
| **EXIT_TO_DIFFERENT_EXEC** (endpoints in two adjacent executions, no gap) | 1,383 | 0.85% | always `True` |
| **EXIT_TO_NOISE** (exits an execution into unlabeled time) | 350 | 0.22% | `True` in 288 cases, `False` in 62 |
| **ENTRY_FROM_NOISE** (enters an execution from unlabeled time) | 351 | 0.22% | always `False` |

Per-session `NOISE_TO_NOISE` rate: min 6.7%, max 29.7%, mean 14.5% —
present in every session, not concentrated in a few.

## What this reveals — a real gap in the current label scheme, not just an edge case

**14.24% of the entire dataset (23,171 transitions) currently gets the
exact same label (`is_boundary=False`) as genuine same-execution
continuity (137,450 transitions), despite having no GT claim about them
at all.** Under the old boundary-first framing this was harmless (the
model was only ever asked "is this the boundary," and `False` was the
correct answer either way). Under continuity-first, `is_boundary=False`
would naively become `S=1` ("same execution") by default — which would
actively teach the model that unlabeled idle/off-task time is
same-execution continuity. This is precisely the risk the task
description warned about, now measured rather than hypothesized: it's
not a rare corner case, it's **1 in 7 transitions in the entire dataset**.

**A second, smaller but conceptually important gap**: `ENTRY_FROM_NOISE`
(351 transitions — the moment a new execution actually *begins* after
idle time) is currently labeled `is_boundary=False` in 100% of cases. The
existing scheme only ever marks the *exit* from a closing execution as a
boundary (`extract_boundaries` pairs consecutive executions and records
the boundary at the closing one's `end_ts`) — it never separately marks
the *entry* into the next one when a gap separates them. So a real "new
execution starting" moment is currently indistinguishable, label-wise,
from ordinary continuity. Small in count (0.22%), but if left as `S=1`
by default it would be teaching the model the opposite of what's true at
exactly the moments that matter for detecting a genuinely new execution.

`EXIT_TO_DIFFERENT_EXEC` (0.85%) needs no decision — it's the clean,
already-unambiguous case (`S=0`, no gap, adjacent executions). The 62
`EXIT_TO_NOISE` cases labeled `is_boundary=False` are explained
structurally, not an inconsistency: they're the final execution of a
session (no following execution exists to pair a boundary with) — there
is genuinely nothing to compare against, not a labeling ambiguity.

## Labeling options (presented, not decided)

**Option A — Exclude everything without an unambiguous GT answer.**
Train only on `SAME_EXECUTION` (S=1) and `EXIT_TO_DIFFERENT_EXEC` ∪
`EXIT_TO_NOISE-with-is_boundary=True` (S=0) — 139,121 of 162,705
transitions (85.5%). `NOISE_TO_NOISE` and `ENTRY_FROM_NOISE` (14.46%
combined) are dropped from training entirely, not labeled either way.
*Trade-off*: cleanest, zero risk of teaching a false association; but the
model never sees idle-region behavior at all, so nothing is known about
how it would behave if Dataset B contains a lot of it (untested, not
assumed either way).

**Option B — Label `NOISE_TO_NOISE` as S=0.** Reasoning: neither side
belongs to a labeled execution, so "same execution" is technically false
regardless of activity similarity. *Trade-off*: gives the model exposure
to idle-time patterns as negative examples, but risks teaching it that
ordinary low-activity behavior (not just true execution changes) predicts
"different" — could inflate false positives on genuinely quiet stretches
inside a real execution, which is close to the exact failure mode Stage 2
already found the current model has (over-triggering on gaps).

**Option C — Label `NOISE_TO_NOISE` as S=1.** Explicitly the option the
task description already flags as the wrong default, and Stage 2's own
evidence supports that concern: a large fraction of noise time likely
contains long pauses, and teaching "long pause = continuity" indiscriminately
here could reinforce exactly the temporal-dominance problem this whole
pivot exists to fix.

**`ENTRY_FROM_NOISE` (351 cases) needs its own, separate decision**
regardless of which option above is chosen for `NOISE_TO_NOISE`: exclude
it (consistent with Option A's caution), or label it `S=0` (treat "a new
execution starting after idle time" as boundary-like evidence, which
matches what it actually represents).

## Recommendation (offered, not applied)

**Option A, plus excluding `ENTRY_FROM_NOISE`**, i.e. train only on the
85.3% of transitions with an unambiguous GT answer. Reasoning: this
project's own standing discipline all through Day 1 and Day 2 has been
"don't manufacture a label the evidence doesn't support" — Options B and
C both require deciding what `NOISE_TO_NOISE` *means* for continuity
without GT actually saying so, and Stage 2 already showed the cost of the
model learning a spurious relationship with temporal/activity patterns.
Excluding is reversible (nothing stops revisiting B or C later with a
targeted experiment once a baseline exists), while including on a
guess is not something a later experiment can cleanly undo. This is a
recommendation, not a decision — proceeding to build labels around it
only on your approval.

## Files

- `scripts/analyze_noise_gap_structure.py`
- `reports/day2/noise_gap_structure_dataset_a.json`
- `reports/day2/noise_gap_labeling_analysis.md` — this file
