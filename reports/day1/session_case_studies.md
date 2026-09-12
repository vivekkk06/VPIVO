# Representative Session Case Studies

Five sessions selected by real properties pulled from `gt_manifest.json`
(not arbitrarily) — see `scripts/case_studies.py` for the exact selection
query. Figures: `figures/case_study_<session_id>.png` (top: GT process
intervals per process-code lane; bottom: raw event stream scatter, colored
by layer, same time axis).

## 1. Typical session — `ses_20260630-121953-LAPTOP-R36BQBTE`

25.4 minutes, 2,348 events, 9 processes (A,B,C,E,G,H,J,M,O), 32 executions.
Selected as the "default" example — this is also the very first session
inspected on Day 1.

- Process **A** executes 4 separate times across the session, each ~0.5
  minutes — a clean example of "the same process appears many times a day"
  (README's own framing).
- Process **B** shows a **clean suspend→resume**: a short bar around
  minute 3.5, then a second short bar around minute 5 — this is
  `M1-B-split-1` in `gt.jsonl`, suspended and correctly resumed within the
  same session (contrast with case study #2).
- Visible in the figure: GT process intervals do **not** tile edge-to-edge —
  there are real gaps between them (e.g. between minutes 21 and 25) where no
  process is officially active. Raw event density (bottom panel) stays
  roughly constant through those gaps — meaning **raw activity volume alone
  does not visibly drop during non-process ("noise") time**, which matters
  for signal selection (see `segmentation_signal_analysis.md`).

## 2. Anomaly — abandoned suspension — `ses_20260701-051820-CHAITANYA0BCF`

19-minute session, 2,195 events, 8 processes, 26 executions. Selected
specifically because this is where the dataset-wide GT audit found its one
real `gt_suspend_without_resume` case.

- Process **B**'s second execution (`case_id: PI-101000-002`) is suspended
  (switching out to process E) at 05:33:47 UTC and **never resumes** for the
  rest of the session — the session moves on to E, then J, then ends.
- `gt_manifest.json` records this execution with `split_id: null` (it
  doesn't know it was "supposed to" resume) — only `gt.jsonl`'s raw
  `process_suspended` record carries `split_id: "M1-B-split-1"`. See
  `cross_file_consistency.md`.
- **Segmentation implication**: an execution can legitimately end at a
  suspend point with no resume ever appearing, in-session or otherwise. A
  segmentation approach that assumes every suspend has a matching resume
  (or waits for one before closing a segment) would hang indefinitely or
  mis-attribute later, unrelated activity to the stale open process.

## 3. Most complex + a real identity glitch — `ses_20260701-115141-SIDDHIGUPTAB00B`

Highest process-execution count in Dataset A: 44 executions across many
processes, 3,557 events. Also the one session where the session/chunk
identity check found a real inconsistency: one event's own
`correlation.chunk_id` names the *previous* chunk (`...-1130-...`) while the
event was physically read from the *next* chunk's `events.jsonl`
(`...-1200-...`) — almost certainly a boundary-flush artifact from an event
captured right at the chunk transition. Rate is 1 event in this session
(and 1 in the whole 162,768-event dataset) — noise-level, but the kind of
thing that would silently corrupt a naive "trust `correlation.chunk_id`"
chunk-membership assumption.

## 4. Least complex available — `ses_20260701-075548-CHAITANYA0BCF`

24 executions — the **minimum** across all 63 Dataset A sessions. Worth
stating plainly: **Dataset A has no simple session.** Every single session
is a busy multi-domain mix (the scenario generator's own framing: "HR (5
procs) / Finance (5 procs) / Ops (5 procs)" per the `run_config` banner seen
in the very first event of the very first session). Any segmentation
approach validated on Dataset A is automatically being validated against a
"hard" case by construction — there's no artificially easy session to
overfit to even if we wanted one.

## 5. High noise + near-max complexity — `ses_20260701-070320-JAYESH`

`noise_rate: 0.25` (the highest observed in Dataset A, tied with 4 other
sessions) combined with 42 executions (near the dataset max of 44). Chosen
to see whether high documented noise_rate visibly shows up as extra raw
events between GT intervals in the timeline figure — qualitatively, yes:
more scattered activity in the gaps between colored GT bars than in case
study #1, though this wasn't formally quantified (would require correlating
`noise_rate` against measured inter-process idle-event density across all
63 sessions — flagged as a Day 2 candidate analysis, not done here).

## What these five sessions collectively show

Every documented "what makes this difficult" point from README.md's Step 1
section is visible in real data, not just asserted by the docs: work is
genuinely non-contiguous (case study 1), the same process really does recur
many times (case study 1), suspension is real and can be abandoned (case
study 2), cross-chunk executions are the norm not the exception (all five),
and the dataset provides no easy on-ramp session (case study 4).
