# Work Log

For the detailed evidence behind every finding below, see `reports/day1/`.
For the full account of engineering ownership and AI usage specifically,
see `reports/day1/my_engineering_contribution.md` and
`reports/day1/engineering_decision_register.md`. This log stays
chronological and concise.

## Day 1 — 2026-09-12 — Data understanding & ingestion foundation

All of the following happened in one continuous work session on 2026-09-12.
Exact clock times within the day are not recorded, so I'm not stating any
— where I refer to sequence ("first," "then," "later"), that's order, not
timestamps.

### A. Day 1 goal

Before touching segmentation, I wanted to know whether the operation logs
could actually be trusted the way the task assumes — whether a count, a
timestamp, or a field means what it appears to mean. Step 1 is only as
good as the data underneath it, so Day 1's scope was: discovery, loading,
validation, data-quality audit, ground-truth verification, profiling, and
candidate-signal evaluation. No segmentation algorithm, no ML, no Dataset
B output. I held that boundary for the whole day.

### B. What I built

- A `src/procmine` package rather than loose scripts: data models, path/
  session/chunk discovery, event and ground-truth loaders, a validation
  framework, a deeper data-quality audit module, a conservative cleaning
  layer, profiling, and figure generation.
- Five CLI scripts (`profile_dataset.py`, `parse_ground_truth.py`,
  `validate_dataset.py`, `audit_dataset.py`, `case_studies.py`) that run
  end-to-end against real data, not just synthetic fixtures.
- 36 tests across 7 files — behavior tests, not coverage padding: each
  real bug found got a named regression test reproducing the original
  failure.
- Five case-study session timelines, selected by real `gt_manifest.json`
  properties (execution count, variant count, split presence), not
  arbitrarily.

### C. What I discovered

**Dataset A**: 63 sessions, 117 chunks, 162,768 events, 2,009 reconstructed
GT executions — event count matches the README's stated "~162,000," a
real correctness signal, not just "it ran."

**Dataset B**: 15 sessions, 20 chunks, 20,477 events, no ground truth, by
design.

**Screenshot directory layout is inconsistent on disk.** 35 of 117
Dataset A chunks store screenshots in a sibling directory with a shorter
name than the chunk that references them; the other 82 use the layout
you'd expect. The resolver checks both locations rather than assuming one.

**Raw event order isn't reliably chronological.** Before sorting, every
session has inversions; the majority trace to `screenshot_smart` events
landing slightly out of write-order because screen capture is async
relative to the input-event pipeline. Sorting by `timestamp_ms` explicitly
is required, not optional — this is exactly why the loader always does it.

**Multi-chunk sessions are the norm, not the exception**: 53 of 63
sessions span more than one chunk, and the majority of GT executions cross
a chunk boundary — confirms chunk boundaries are storage artifacts, not
process boundaries, both from the schema and from the data itself.

**The two documented GT defects (duplicate `process_started`, unpaired
`process_switched_out`) don't occur anywhere in Dataset A** — checked
across all 63 sessions, 2,009 executions, zero instances of either. I kept
the handling for both anyway (tested synthetically) since Dataset B has no
GT to verify the same absence against. Deeper checks I added beyond the
documented quirks found two real things the schema doesn't warn about: one
process suspended and never resumed within its session (a genuine
abandoned execution, not a parsing bug), and a field-level disagreement
between `gt.jsonl` and `gt_manifest.json` — the manifest's `split_id` is
`null` for that same execution even though the raw stream shows it was
suspended with a real `split_id`.

**Instrumentation duplication, not user behavior**: 65% of every
`app_switch` event in Dataset A is an exact, back-to-back duplicate
(identical payload, 36–97ms apart). Checked against all 15 Dataset B
sessions — 0% there. Separately, 42 of ~100 distinct `browser_error`
occurrences are logged twice (84 of ~200 raw events), identical payload
and millisecond timestamp.

**Screenshot availability is dataset-specific, not a general property**:
7.2% of Dataset A's `screenshot_smart` events resolve to an actual file on
disk; 81.2% do in Dataset B (measured against all 15 sessions there too).
A conclusion drawn only from A would have been wrong for B.

**`ms_since_last_event` (the agent's own field) has a real minimum of
-713,900ms.** 443 events (0.27%) are below -1,000ms. The two most extreme
cases trace to the exact same session and chunk transition as a separate
`correlation.chunk_id` mismatch I found independently — two unrelated
checks landing on the same point in the data is good evidence this is a
real agent-side defect, not noise in my own analysis.

**Keystroke-based text reconstruction is verified, exact-match, in a real
case**: pulled a `text_input_complete` event's linked `related_keystrokes`
and concatenated characters — matched `final_text` exactly.

**Clipboard content is not recoverable from `clipboard_change`**:
`payload.text_content` was `null` in every sample checked; only length/
format metadata is captured.

**A governance/security finding worth carrying into Step 3**: 18
`text_input_complete` events contain plaintext password-field content
(`final_text`) despite `redact_password_fields: true` in the capture
settings. Synthetic test credentials, no real exposure — but the
redaction mechanism itself doesn't appear to work for this field, which
matters if this pipeline ever touched real production logs.

### D. What broke, and how I fixed it

**A corrupted `manifest.json` crashed the entire session load.** I
stress-tested the loader against deliberately corrupted metadata rather
than accepting success on clean real data as sufficient — an audit
pipeline whose whole job is finding data problems shouldn't itself be
fragile to one. It wasn't: one malformed manifest file took down the
whole session (and would have taken down a full dataset batch). Root
cause: manifest parsing assumed well-formed input; the equivalent
line-level event parser already had defensive handling, manifest parsing
didn't. Fixed with a wrapper that catches the parse error and records it
instead of raising, plus a regression test that reproduces the exact
original failure. Re-verified: the same corruption scenario now loads
successfully with the error recorded, not thrown.

**A profiling pass reported "100% of `text_input_complete` events are
missing content."** That number agreed suspiciously well with a warning
already in DATA_SCHEMA.md, which is exactly why I didn't accept it — an
extreme result that confirms what you already expected is worth checking
against raw data before it goes in a report, not after. The profiler had
guessed the content field was named `text`/`content`/`value`; none of
those exist. The real field, `payload.final_text`, isn't named anywhere
in the schema documentation. Corrected and re-run against all 118 real
events: 2 missing (1.7%), not 118 (100%). This stands as the clearest
example from Day 1 of why a plausible-looking result still needs a raw
example checked before it's trusted.

### E. What evidence changed my decisions

- The 65% `app_switch` duplication rate meant "count of app switches"
  could not be treated as a trustworthy raw feature — it changed how I
  scoped the cleaning layer (see F).
- The `ms_since_last_event` percentile spread (not just the median, which
  looked fine at 44ms) is what surfaced the -713,900ms anomaly — I would
  not have found it from an average alone, which is why percentiles are
  now a standing requirement for any timing statistic in this project.
- The `gt.jsonl` vs. `gt_manifest.json` disagreement changed how I treat
  "ground truth" here — it's strong evidence to cross-check, not an
  infallible file to trust in isolation.
- Measuring screenshot resolution on both datasets independently (instead
  of generalizing from Dataset A) is what caught the 7.2%-vs-81.2%
  asymmetry — a single-dataset measurement would have produced a wrong
  conclusion for Dataset B.

### F. What I deliberately did NOT do

- Did not modify raw data anywhere — cleaning operates on in-memory data
  only, raw files are `.gitignore`'d out of the repository entirely.
- Did not treat chunk boundaries as process boundaries.
- Did not delete the `app_switch`/`browser_error` duplicates — decided
  what counts as "one real switch" is a segmentation-time judgment call,
  not a cleaning-time fact, and left it as a documented precondition for
  whoever builds that feature (me, on Day 2).
- Did not trust `text_input_complete` as ground truth, even after the
  corrected number came back better than the documentation implied.
- Did not trust `correlation.ms_since_last_event` directly for any
  gap-based analysis, after finding it wrong by over ten minutes at a
  chunk boundary — gaps get recomputed from sorted `timestamp_ms` instead.
- Did not start segmentation or any ML implementation — no such code
  exists anywhere in this repository as of Day 1's end.
- Did not report a candidate segmentation signal as effective without
  measuring it against real GT boundaries first.
- Did not assume any Dataset A finding transfers to Dataset B without
  checking — the app-switch duplication rate specifically does not (0%
  across all 15 Dataset B sessions vs. 65% in A).

### G. AI assistance and my role

I used Claude Code as a coding and analysis accelerator throughout Day 1.
I directed the investigation and scope: what needed to be built, which
audit categories mattered (exact/semantic/sequential duplicates,
percentile timing stats, cross-file GT consistency), and the hard rules
(raw data immutable, no fabricated results, fact vs. inference separated,
no segmentation yet). I decided which suspicious findings needed to be
checked before being accepted — the 65% app-switch number and the "100%
missing" `text_input_complete` result both got questioned and verified
against raw data before either went into a report. I made the engineering
and scope decisions based on what came back: keeping the app-switch
duplicates out of the cleaning layer, never trusting `ms_since_last_event`
directly, treating GT as evidence rather than an oracle. Claude Code
implemented the loaders, validation, audit tooling, and tests, executed
every script against the real datasets, and performed the initial
diagnosis on both bugs in section D. I'm not claiming I hand-typed that
code — I didn't — but the requirements, the scope, the review, and the
decisions were mine.

### Numerical correction (kept as an example of verification discipline)

An earlier draft of one of the Day 1 reports stated "54 of 63 sessions
have 2+ chunks" without that number having actually been counted. Before
it stayed in a report, I required it be re-verified — the real count is
53. Small, but it's the same discipline applied to writing the reports as
to analyzing the data.

### H. Day 2 starting point

Day 1 ends with a data foundation I understand and have validated enough to start segmentation.
Nothing below is done yet:

- Measure the three segmentation-signal hypotheses left unevaluated on
  Day 1 (window title changes, browser-navigation URLs, clipboard event
  timing) against real GT boundaries, using the same method already built
  for the three signals that are measured (deduplicated app-switch:
  68.1% alignment; extracted-text presence: 64.2%; gap size: ~7-10x larger
  at boundaries).
- Build the `app_switch`/`browser_error` deduplication step as a named,
  tested function — required before any feature can use raw switch counts.
- Design and validate the actual Step 1 segmentation approach against
  Dataset A's ground truth first, per the assignment's own instruction —
  Dataset B has no GT, so A is the only place accuracy can be checked.
- Only after that: figure out how to self-validate whatever the approach
  produces on Dataset B, since there's no ground truth there to score
  against directly, then produce `segments.jsonl`.

Step 2 (process/ROI analysis) and Step 3 (automation prototype) haven't
started and depend on Step 1's output existing first.

### Git

The Day 1 work was organized into a logical sequence of Git commits after
this review pass — by component (scaffolding, data model, loaders,
validation, audit/cleaning, profiling, scripts, tests, evidence artifacts,
analysis reports, engineering documentation) — rather than committed
incrementally as each piece was built during the day itself. This entry
is the last piece to be committed, after being rewritten.

### I. Short structured summary

| Area | Status | Key evidence |
|---|---|---|
| Data loading | Done | 162,768 / 20,477 events, matches README estimates |
| Validation + audit | Done | 0 schema violations; 65% app-switch duplication found and documented |
| Ground truth | Done (Dataset A only) | 2,009 executions, 1 abandoned suspension, 1 cross-file disagreement |
| Cleaning | Done, deliberately minimal | 2 transformations, both logged, 0 raw-file changes |
| Case studies + signals | Done | 5 sessions; 3 of 6 candidate signals measured against GT |
| Tests | 36/36 passing | 7 test files, one regression test per real bug found |
| Segmentation (Step 1) | Not started | No such code exists |
| Dataset B output / Step 2 / Step 3 | Not started | Blocked on Step 1 |
| Git | 14 commits, organized by component | Not committed incrementally through the day |
