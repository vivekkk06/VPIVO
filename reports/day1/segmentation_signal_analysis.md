# Segmentation Signal Analysis

Every claim below was measured against Dataset A's real events + GT
manifest (1,689 real process-to-process boundaries across 63 sessions), not
asserted from intuition. Method for the boundary-alignment numbers: for each
GT execution-to-execution transition, look at the raw event immediately
before/after the boundary timestamp, and whether specific event types occur
within a ±2s window of it.

## Time gaps — MODERATE signal, real but noisy

- **Median raw event-to-event gap at a GT boundary: 526ms.**
  **Median gap strictly inside a GT execution: 52ms** — roughly **10x**
  larger at boundaries.
- Mean gap at boundary: 3.4s vs. 486ms mid-execution (~7x).
- **Weakness**: these are medians of overlapping distributions, not a clean
  separation — a fixed gap threshold will produce both false positives
  (genuine mid-task pauses, e.g. reading a screen before acting) and false
  negatives (some transitions happen with almost no gap, e.g. finishing one
  case and immediately starting the next of the same repeated process).
- **Verdict**: useful as one input feature (e.g. "gap size" as a continuous
  score), not usable alone as a hard threshold rule.

## Application transitions (`app_switch`) — USEFUL BUT MUST BE DEDUPLICATED FIRST

- **68.1% of GT boundaries have an `app_switch` event within ±2s.** Real,
  meaningful correlation — most (not all) process transitions involve
  switching what's on screen.
- **Critical caveat, found during the duplicate-detection pass**: 65% of
  *all* `app_switch` events in Dataset A are exact back-to-back duplicates
  of the same switch (identical payload, 36–97ms apart — see
  `data_quality_scorecard.md`). Any feature built on "count of app switches"
  or "time of nearest app switch" must first collapse consecutive identical
  `app_switch` events, or it will be dominated by this artifact rather than
  real transitions.
- **False negative rate**: 31.9% of boundaries have *no* app switch nearby —
  e.g. two different processes both conducted inside the same application
  (Excel-only workflows switching between different spreadsheets/cases). App
  switching alone will miss these.
- **Verdict**: strong secondary signal after deduplication; must be combined
  with something else to catch same-app transitions.

## Window titles — HYPOTHESIS, NOT YET EVALUATED

`context.active_app.window_title` and `window_title_change` events look
promising qualitatively (case IDs and process names sometimes appear
directly in browser tab titles per the case study screenshots), but this
was not quantitatively measured this pass — flagged as a concrete Day 2
task rather than claimed as validated.

## Browser tabs / navigation (`browser_navigation`, `active_browser_tab.url`) — PROMISING, NOT YET EVALUATED

The portal system runs at `http://127.0.0.1:5122-5123/#/<route>` per
observed URLs (e.g. `#/social-insurance`); the URL fragment plausibly
encodes which business function is active. Not measured against GT boundary
alignment this pass. Strength: if true, this is a much cleaner signal than
timing-based heuristics. Weakness: only present for L3 (browser) activity —
would need a fallback for the Excel/Word/Notepad-only stretches of a
process (per the case-study apps lists, most processes touch
`chrome+excel+notepad` together, so this alone would under-segment
processes that spend time outside the browser).

## Extracted screen text (`context.extracted_text`) — SURPRISINGLY STRONG for its rarity

- Only 4.48% of *all* events carry `extracted_text` (matches DATA_SCHEMA's
  own "~4%" claim almost exactly).
- But **64.2% of GT boundaries have an `extracted_text`-bearing event within
  ±2s** — 14x more concentrated near boundaries than the base rate would
  predict. Consistent with the independent finding that extracted_text is
  disproportionately attached to `app_switch` events (86% of all
  non-empty extracted_text in Dataset A, per `text_input_quality.md`'s
  sibling analysis in `full_audit_dataset_a.json`) — people read the screen
  most when they've just switched to it.
- **Weakness**: still absent on the 35.8% of boundaries it doesn't catch;
  and it's a byproduct of *when* it fires (mostly at app switches), so it's
  correlated with the app-switch signal rather than fully independent of it
  — combining both likely has diminishing returns versus either alone.

## Mouse/keyboard activity density — HYPOTHESIS, NOT YET EVALUATED

Plausible that activity *density* (events/sec) dips briefly around a
transition (a short "what do I do next" pause) even when the absolute gap
isn't large enough to trigger the raw time-gap signal. Not measured this
pass.

## Clipboard events — HYPOTHESIS, NOT YET EVALUATED

`gt.jsonl`'s own `clipboard_copy`/`clipboard_paste` records are tied to
specific `case_id`s, which means real clipboard events in `events.jsonl`
plausibly carry case-boundary information (a copy from a portal followed by
a paste into Excel is very likely one case, one execution). Not
quantitatively linked to GT boundaries this pass — good Day 2 candidate,
since clipboard events are far rarer than app_switch (5,198 vs 50,588
dataset-wide) and thus cheaper to inspect exhaustively.

## Screenshots — LOW VALUE FOR DATASET A, STATUS UNKNOWN FOR DATASET B UNTIL TESTED

7.2% resolution rate in Dataset A (`data_quality_scorecard.md`) makes
screenshots impractical as a primary Dataset-A signal — most referenced
images simply aren't in the distributed data. **This does not transfer to
Dataset B**, where resolution is 81.2%. Any conclusion "screenshots aren't
useful" drawn only from Dataset A would be wrong for the dataset that
actually matters for Step 2/3.

## Summary ranking (Dataset A evidence only)

| Signal | Boundary alignment | Independent of others? | Caveat |
|---|---|---|---|
| Extracted text presence | 64.2% | No — correlated with app_switch | rare overall (4.5%) |
| App switch (deduplicated) | 68.1% | Partially | must dedupe 65% noise first |
| Time gap | ~7-10x larger at boundary (median/mean) | Yes | noisy, not a clean threshold |
| Window title / browser URL | not measured | unknown | promising, Day 2 task |
| Clipboard events | not measured | likely yes (rare, case-linked) | Day 2 task |
| Screenshots | not usable (A), unknown (B) | — | test on B before ruling out |

No single signal reaches high-confidence boundary detection alone; the
data supports a **combined-feature approach** (gap size + deduplicated app
transition + extracted-text presence as a starting feature set), which is
where Day 2 should start, after also evaluating the two "not yet evaluated"
hypotheses above with the same boundary-alignment methodology used here.
