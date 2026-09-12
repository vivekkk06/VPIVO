# Failure Modes for Step 1 Segmentation

Each entry is grounded in a specific measurement made this pass, not a
generic list of "things that could go wrong."

### 1. Long pauses / non-contiguous work
**Evidence**: gap-size distribution (`timestamp_quality.md`) has a real long
tail beyond 10s-60s even mid-execution; the case-study timelines show clear
white space between GT-labeled intervals.
**Impact**: a pure time-gap segmenter will over-split a single execution
that has one long "thinking" pause in the middle, and under-split when two
different short executions happen back-to-back with minimal gap.
**Mitigation direction**: use gap size as one weighted feature, not a hard
cutoff (see `segmentation_signal_analysis.md`).

### 2. `app_switch` double-firing
**Evidence**: 65% of all 50,588 `app_switch` events in Dataset A are exact
consecutive duplicates, firing 36–97ms apart with identical payload.
**Impact**: any feature counting "number of app switches" or "time since
last app switch" is badly inflated/skewed unless deduplicated first.
**Mitigation**: collapse consecutive identical `app_switch` payloads before
using this signal — a required preprocessing step, not optional cleanup.

### 3. `browser_error` double-logging
**Evidence**: 42 of ~100 distinct `browser_error` occurrences are logged
twice (84 of ~200 raw events), identical payload and millisecond timestamp.
**Impact**: low — `browser_error` wasn't a leading segmentation-signal
candidate — but flagged in case any later feature engineering touches L3
error events, and as a template for what a "same instrumentation bug,
different event type" search should look for in Dataset B.

### 4. Repeated executions of the same process
**Evidence**: process A executes 4 times in one case-study session alone;
dataset-wide, 2,009 executions across 63 sessions average ~32 per session
across ~8-10 distinct process codes.
**Impact**: segmentation must produce *multiple, separate* segments with
the *same* label for one process, not collapse repeats into one, and not
invent spuriously different labels for what's actually the same repeated
process (the README's own evaluation criterion: "whether the same process
consistently receives the same label").

### 5. Process variants
**Evidence**: `gt_manifest.json` shows the same process code (e.g. `B`)
occurring with different `variant` values across executions.
**Impact**: two executions of "the same" process can have different
internal step sequences. A segmentation approach that expects one fixed
event-sequence template per process will fail on the variant executions.

### 6. Sparse / disproportionately-concentrated screen text
**Evidence**: `extracted_text` present on only 4.48% of all events, but 86%
of the non-empty occurrences are attached to `app_switch` events
specifically (concentrated, not evenly spread).
**Impact**: any approach relying on screen text as a general-purpose
feature will have almost nothing to work with mid-execution and comparably
more right at transitions — which is actually favorable for *boundary*
detection (see signal analysis) but means text can't be a general
per-event feature.

### 7. Screenshots mostly absent — in Dataset A specifically
**Evidence**: 7.2% resolution rate in A vs. 81.2% in B.
**Impact**: a Step 1 approach co-developed and validated using screenshots
in Dataset A would be validating against a signal that's nearly absent
there — misleading confidence either way. If screenshots end up mattering
for Step 2/3 (they well might, given B's high availability), that decision
needs its own validation pass on B specifically; A can't vouch for it.

### 8. Duplicate GT `process_started` (documented, unobserved)
**Evidence**: DATA_SCHEMA.md documents this; 0 occurrences found in
Dataset A's 63 sessions.
**Impact**: none observed for A. Real risk for Dataset B: there's no GT to
check against there, so if Dataset B's *own* recording pipeline has quirks
Dataset A didn't happen to exhibit, we'd have no ground truth to catch it.
The handling (dedup consecutive identical starts) stays in the codebase
defensively regardless of A's clean result.

### 9. Cross-chunk executions are the norm
**Evidence**: the large majority of Dataset A's 2,009 executions have
`continues_from_prev`/`continues_to_next: true` in `gt_manifest.json`;
none of the 5 case-study sessions had a chunk-aligned process.
**Impact**: any segmentation implementation that processes chunks
independently (even accidentally, e.g. via naive parallelization) will
silently produce wrong boundaries for most executions. `load_session_events`
already merges chunks before segmentation ever runs — this must remain the
only entry point Step 1 code uses.

### 10. Abandoned suspensions (no resume, ever)
**Evidence**: `ses_20260701-051820-CHAITANYA0BCF`, process B suspended and
never resumed for the rest of the session (case study #2).
**Impact**: a segmentation approach that keeps a "pending resume" state
open indefinitely, or that requires seeing a resume before closing a
segment, will either hang logically or misattribute all subsequent activity
to the wrong open process.

### 11. Ambiguous same-application transitions
**Evidence**: 31.9% of GT boundaries have no `app_switch` within ±2s
(segmentation signal analysis) — meaning the process changed while staying
inside the same application (e.g. two different Excel-based cases back to
back).
**Impact**: app-switch-based segmentation alone will systematically miss
these transitions; needs a same-app discriminator (window title, active
browser tab/URL, or clipboard case-id linkage — all flagged as Day 2
evaluation targets in the signal analysis).

### 12. Session/chunk metadata that lies (rarely)
**Evidence**: 1 event with `correlation.chunk_id` pointing to the wrong
chunk (case study #3).
**Impact**: negligible at this rate (1 in 162,768), but confirms
`correlation.chunk_id` cannot be trusted as ground truth for "which chunk
produced this event" without a corroborating check — relevant if a future
optimization tries to process by declared chunk_id instead of by the
merged, re-sorted session stream.
