# Day 1 Engineering Report

Verification legend used throughout: **VERIFIED** (repository/files/commands/
tests/reports/conversation), **RECONSTRUCTED REASONING** (the engineering
rationale that follows naturally from the task requirements and what was
built — not a specific claimed memory), **UNKNOWN** (genuinely
unrecoverable), **NEVER FABRICATED** (no invented events, quotes, times, or
commits appear anywhere in this document).

**Role note**: this report describes an AI-assisted engineering project.
Where it says "implemented" or "built," that work was done by an AI coding
assistant executing requirements, methodology, and quality standards that
were specified as this project's own engineering direction — see
`my_engineering_contribution.md` for the full account of that direction,
and `engineering_decision_register.md` for the decision-by-decision
reasoning behind each major choice. This report focuses on the technical
narrative; those two focus on ownership.

## Part 1 — Audit Confirmation

Re-verified fresh before writing this report (**VERIFIED FROM TEST/COMMAND
OUTPUT**, this session):

```
pytest: 36 passed
git log --all --oneline: (empty)
git status --short | wc -l: 10 (top-level untracked entries)
python files under src/scripts/tests: 23
work_log.md: 259 lines
```

Dataset facts (re-confirmed against earlier runs this session, all
**VERIFIED**): Dataset A = 63 sessions, 117 chunks, 162,768 events, 63/63
with ground truth. Dataset B = 15 sessions, 20 chunks, 20,477 events, 0
ground truth (by design, per README.md). No contradictions found between
any report in `reports/day1/` and the underlying repository — every
report's numbers trace back to a script in `scripts/` that can be re-run.

## Part 2 — The Engineering Journey

**1. Starting objective.** The assignment (README.md) asks for Step 1
(segment logs into process executions), Step 2 (ROI analysis), Step 3
(build automation) across 7 days, with a work log and full git history as
deliverables. Day 1's objective, as scoped across this project's sessions,
was narrower and deliberate: build a data foundation trustworthy enough to
support Step 1, without writing Step 1 itself. **VERIFIED** — this scope
was stated explicitly and repeated across every session ("Do NOT jump to
machine learning yet," "Do not start building the segmentation algorithm").

**2. Initial project understanding.** README.md and DATA_SCHEMA.md were
read before any code was written, and real files were opened before
trusting either document. **VERIFIED** — the very first actions in this
project were `ls`/`find`/`Read` calls against `dataset_a/` before any
Python was written. **RECONSTRUCTED REASONING**: a spec document describes
intent, not guaranteed reality; the screenshot-path inconsistency and the
`text_input_complete` field-name gap (both found later) are exactly the
kind of thing that only shows up by reading real files, which is why that
step came first rather than being skipped.

**3. Repository setup.** A `src/procmine` package was created rather than
loose scripts, with `.gitignore` excluding the 2.8GB raw dataset
directories. **VERIFIED** (`pyproject.toml`, `.gitignore`,
`requirements.txt` exist and are minimal — matplotlib + pytest only).
**RECONSTRUCTED REASONING**: Step 1/2/3 all need the same loaders; a
package avoids re-solving path discovery three times, and committing raw
JPEGs would bloat a git repository with data that isn't anyone's work
product.

**4. Data loading.** `load_session_events` merges all chunks of a session
into one chronological stream before anything else touches the data.
**VERIFIED** (`loaders/events.py`). **RECONSTRUCTED REASONING**:
DATA_SCHEMA.md states a chunk is a recording-buffer boundary, not a
process boundary; treating chunks independently would systematically
mis-segment any execution that spans a chunk transition — and the GT data
confirms most executions do exactly that (majority of 2,009 executions
have `continues_from_prev`/`continues_to_next: true`, **VERIFIED**).

**5. Data validation.** A `ValidationReport` accumulates issues (malformed
JSON, missing fields, duplicate IDs, ordering, chunk linkage) instead of
raising on the first problem. **VERIFIED** (`validation.py`).
**RECONSTRUCTED REASONING**: a dataset this size (162,768 events) will
have edge cases; a validator that halts on line 1 of a problem is less
useful for an audit than one that reports every problem it finds.

**6. Data-quality audit.** Extended well past "does it load" into
duplicate detection (exact/semantic/sequential), missingness by field,
timestamp consistency, event-type/layer consistency, and payload-shape
checks. **VERIFIED** (`audit.py`, `full_audit_dataset_a.json`).
**RECONSTRUCTED REASONING**: the initial validation pass answered "is the
JSON well-formed," not "can I trust a count of app-switches as a feature" —
those are different questions, and the second one is what actually matters
for Step 1. This is exactly what surfaced the 65% `app_switch` duplication.

**7. Cleaning policy.** Two transformations only: exact-duplicate removal
(0 triggered) and chronological sort. **VERIFIED** (`cleaning.py`,
`cleaning_policy.md`). **RECONSTRUCTED REASONING**: cleaning was
deliberately kept to transformations where "the correct output" is
unambiguous from the raw data alone; deciding whether a repeated
`app_switch` is "real" is a segmentation judgment call, and making that
call inside a cleaning step would hide the decision instead of exposing it
for Step 1 to make deliberately.

**8. Ground-truth validation.** `gt.jsonl` was reconstructed into
executions via a state machine that tolerates the two documented quirks
(duplicate starts, unpaired switches) and adds three more checks not in
the original schema doc (resume-without-suspend, suspend-without-resume,
overlapping intervals). **VERIFIED** (`loaders/ground_truth.py`,
`ground_truth_validation.md`). Result: 2,009 executions, 0 count-level
mismatch against `gt_manifest.json`, 1 real abandoned suspension found.
**RECONSTRUCTED REASONING**: the two documented quirks turning up zero
times doesn't mean the checks were wasted — Dataset B has no ground truth
at all, so any handling that isn't defensively built now can't be verified
against B later.

**9. Dataset profiling.** Event/layer/type counts, application breakdowns,
duration stats, and (added later) per-app browser/keyboard/mouse/clipboard
splits and percentile gap statistics. **VERIFIED** (`profiling.py`,
`dataset_profile.md`). **RECONSTRUCTED REASONING**: percentiles (p90/p95/
p99) were computed specifically because a mean/median-only view would have
hidden the `ms_since_last_event` anomaly entirely — the median (44ms) looks
completely unremarkable.

**10. Case-study analysis.** Five sessions selected by real
`gt_manifest.json` properties (execution count, variant count, split
presence) rather than arbitrarily. **VERIFIED**
(`scripts/case_studies.py`, `session_case_studies.md`, 5 figures).
**RECONSTRUCTED REASONING**: picking sessions by measured properties (most
complex, least complex, has-a-split, high-noise) rather than "the first
one" is what let the most-complex-session pick also surface the
`correlation.chunk_id` identity glitch — a property-based selection is
more likely to surface edge cases than an arbitrary one.

**11. Segmentation-signal investigation.** Three signals quantitatively
measured against 1,689 real GT boundaries (deduplicated app-switch: 68.1%
alignment; extracted-text: 64.2%; gap size: ~7-10x larger at boundaries);
three more (window title, browser URL, clipboard timing) explicitly left
as unevaluated hypotheses. **VERIFIED** (`segmentation_signals.md`).
**RECONSTRUCTED REASONING**: the explicit rule "do not claim a signal
works until it is actually evaluated" is why the second group is
documented as hypotheses rather than assumed to work from qualitative
impressions in the case-study figures.

**12. Robustness testing.** The manifest loader was deliberately
stress-tested with a corrupted file (not just run against clean real
data). **VERIFIED** (`tests/test_robustness.py`). **RECONSTRUCTED
REASONING**: "works on the data we have" and "is robust" are different
claims — an audit pipeline whose job is to find data problems shouldn't
itself be fragile to a data problem.

**13. Bugs discovered.** Two, both **VERIFIED**: (a) a corrupted
`manifest.json` crashed the entire session load via an unhandled
`JSONDecodeError`; (b) the first `text_input_complete` profiler checked
wrong field names and reported a false "100% missing" finding.

**14. Bugs fixed.** (a) All manifest reads now go through a wrapper that
catches `JSONDecodeError`/`OSError` and logs to
`ValidationReport.malformed_manifest_files` instead of raising; (b) the
profiler was corrected to read `payload.final_text`, the real field.
**VERIFIED** (`loaders/events.py`, `audit.py`, both diffed and re-tested
this session).

**15. Decisions made.** See Part 5 below for the full register.

**16. Decisions intentionally NOT made.** See Part 11.

**17. Testing.** 36 tests total (17 original + 19 added across the
hardening passes), 36/36 passing, confirmed by direct execution multiple
times this session. **VERIFIED**.

**18. Documentation.** 20+ markdown reports under `reports/day1/`, each
tied to a script that produced its underlying numbers. **VERIFIED** (file
listing, this session).

**19. Day 1 conclusion.** The data foundation is structurally sound (0
missing/corrupt files, 0 schema violations) but has real, measured
instrumentation quirks that would corrupt naive segmentation features if
not accounted for (`app_switch` duplication chief among them), plus a
dataset-specific screenshot-availability asymmetry that must not be
assumed to transfer from A to B. **VERIFIED** (aggregated from
`data_quality_report.md`).

**20. Day 2 readiness.** No blockers. First Day 2 task is evaluating the
three unmeasured signal hypotheses with the same ±2s methodology already
built, before writing any segmentation logic. **VERIFIED**
(`day1_readiness.md`).

## Part 5 — Important Day 1 Engineering Decisions

### 1. Session, not chunk, as the analysis unit

**Problem**: a naive implementation could load and process one chunk file
at a time. **Reasoning**: DATA_SCHEMA.md explicitly states a chunk is a
recording-agent boundary, unrelated to business-process boundaries.
**Alternatives considered**: process chunks independently for simplicity.
**Why rejected**: would split any execution spanning a chunk transition —
and GT data shows most executions do (**VERIFIED**, majority of 2,009
executions have `continues_from_prev`/`continues_to_next: true`).
**Evidence**: 53/63 sessions are multi-chunk (**VERIFIED**, counted this
session). **Final choice**: `load_session_events` merges all chunks before
any downstream code runs. **Consequence**: correct event counts (162,768
matches README's ~162,000). **Day 2 impact**: Step 1 must consume this
merged stream, never a single chunk.

### 2. Raw data immutability

**Problem**: cleaning/normalization needs to happen somewhere.
**Reasoning**: if raw and cleaned data aren't structurally separated, it
becomes impossible to know later whether a downstream bug is a data
problem or a cleaning-introduced problem. **Alternatives considered**:
clean files in place. **Why rejected**: destroys the ability to
re-derive/audit later, and violates the assignment's own implicit
expectation that the provided logs are the input, not something to be
edited. **Evidence**: `cleaning.py` takes in-memory dicts, never a file
path (**VERIFIED**). **Final choice**: raw files untouched;
`.gitignore` keeps them out of version control entirely. **Consequence**:
every finding in this project can be independently re-derived from the
original files. **Day 2 impact**: same rule applies to any Dataset B
preprocessing.

### 3. Conservative cleaning scope

**Problem**: many things *could* be "cleaned" (duplicate app-switches,
duplicate browser-errors, missing screenshots, sparse text).
**Reasoning**: cleaning should only do transformations where the correct
output is unambiguous from the raw data alone (sort order, exact-duplicate
removal) — anything requiring a judgment call about what a "real" event is
belongs to segmentation, not cleaning. **Alternatives considered**:
dedupe `app_switch`/`browser_error` at the cleaning layer. **Why
rejected**: would silently bake a segmentation-relevant assumption ("what
counts as one switch") into a layer that's supposed to be
assumption-free, before Step 1 gets to make that call deliberately and
validate it against GT. **Evidence**: `cleaning_policy.md`'s explicit
scope boundary. **Final choice**: only 2 transformations implemented.
**Consequence**: 0 exact duplicates triggered (an honest null result, not
a failure). **Day 2 impact**: the `app_switch` dedup must be a named,
visible preprocessing step in Step 1's code, not hidden upstream.

### 4. `app_switch` duplicates reported, not deleted

**Problem**: 65% of all 50,588 `app_switch` events are exact back-to-back
duplicates (**VERIFIED**, 32,876 of 33,232 total sequential duplicates).
**Reasoning**: deleting them at the data layer would be a permanent,
irreversible decision about "what counts as one switch" made before any
validation against GT is possible. **Alternatives considered**: silently
dedupe during loading. **Why rejected**: hides the finding and removes the
option to validate the dedup choice itself. **Evidence**: 36-97ms
inter-duplicate spacing, identical payload (**VERIFIED**, direct
inspection). **Final choice**: documented as a required Day 2
preprocessing step, not auto-fixed. **Consequence**: any current profiling
number that counts raw `app_switch` events is known to be inflated by
~65% and is labeled as such throughout the reports. **Day 2 impact**:
build the dedup as an explicit, tested function before any feature uses
app-switch counts.

### 5. `browser_error` duplicates reported, not deleted

**Problem**: 42 of ~100 distinct `browser_error` occurrences are logged
twice (84 of ~200 raw events, **VERIFIED**). **Reasoning**: same as #4 —
low priority since `browser_error` wasn't a leading signal candidate, but
the same "don't silently delete" principle applies regardless of whether
the signal matters yet. **Alternatives considered**: ignore since it's a
low-value event type. **Why rejected**: an unused finding today could
matter once Step 3 touches error-handling behavior. **Evidence**:
identical payload, identical millisecond timestamp, two different
`event_id`s (**VERIFIED**, direct inspection of a real Chrome-extension
messaging-error pair). **Final choice**: documented in
`data_quality_report.md`, not removed. **Day 2 impact**: template for
"same instrumentation bug, different event type" search on Dataset B.

### 6. `ms_since_last_event` distrusted at chunk boundaries

**Problem**: this agent-computed field has a minimum of -713,900ms
(**VERIFIED**). **Reasoning**: a field this wrong at even one point can't
be trusted as authoritative anywhere without independent verification.
**Alternatives considered**: use the field directly for gap-based
features. **Why rejected**: 443 events (0.27%) show implausible negative
values, and the two worst cases corroborate a separately-found
`correlation.chunk_id` identity glitch in the same session/chunk
transition (**VERIFIED**, cross-referenced this session). **Evidence**:
see Part 6. **Final choice**: all gap-based analysis in this codebase
recomputes gaps from sorted `timestamp_ms`, never reads this field as
ground truth. **Day 2 impact**: same rule applies to any Dataset B
gap-based feature.

### 7. Explicit chronological sorting

**Problem**: raw file order isn't guaranteed chronological.
**Reasoning**: DATA_SCHEMA doesn't promise write-order equals time-order,
and real data confirms the gap — 68% of raw-order inversions trace to
`screenshot_smart` async capture latency (**VERIFIED**, up to 2.5s lag).
**Alternatives considered**: trust file/sequence-number order.
**Why rejected**: would occasionally process events out of true time
order. **Evidence**: inversions present in every one of 63 sessions
checked. **Final choice**: `load_session_events` always sorts explicitly
by `timestamp_ms`. **Day 2 impact**: none — already the standing default,
verified working.

### 8. GT as validation evidence, not assumed-perfect

**Problem**: two GT files exist (`gt.jsonl`, `gt_manifest.json`) — using
either uncritically risks trusting a synthetic/generated artifact that
DATA_SCHEMA itself warns has quirks. **Reasoning**: cross-checking one
against the other is cheap and catches real disagreements.
**Alternatives considered**: trust `gt_manifest.json` alone (it's the
"ready-made summary"). **Why rejected**: it doesn't record the one
abandoned suspension that `gt.jsonl`'s raw stream shows clearly
(`split_id: null` where `gt.jsonl` has a real `split_id`) — **VERIFIED**,
direct field comparison. **Final choice**: parse both, treat disagreement
as a documented finding, not something to silently resolve one way.
**Day 2 impact**: no equivalent safety net exists for Dataset B — there's
no second source to cross-check against there at all.

### 9. `text_input_complete` not treated as ground truth

**Problem**: DATA_SCHEMA.md explicitly warns this event type is
unreliable. **Reasoning**: even after correcting our own field-name bug
and finding it's actually 98.3% populated (better than the doc's tone
implied), the schema's own warning about non-text actions being mixed in
was not independently re-verified — so nothing justifies elevating its
status. **Evidence**: `text_input_quality.md`/`data_quality_report.md`
Part 12. **Final choice**: hint only; reconstruct from keystrokes when
actual content matters (verified feasible in one real case — see Part 6).
**Day 2 impact**: same caution applies to Dataset B's version of this
event type, unverified until checked there directly.

### 10. Clipboard text not assumed available

**Problem**: clipboard-derived text could be a valuable segmentation
signal if available. **Reasoning**: checked before assuming.
**Alternatives considered**: use `clipboard_change.payload.text_content`.
**Why rejected**: it's `null` in every one of 5 samples checked
(**VERIFIED**) — only metadata (length, format) is captured, which looks
like a deliberate privacy-by-design omission, not a bug. **Final choice**:
clipboard *timing/frequency* remains a viable, unmeasured Day 2
hypothesis; clipboard *content* is off the table entirely from this
field. **Day 2 impact**: don't design a feature around clipboard content
without a different source (e.g. `gt.jsonl`'s own `content_preview`,
which only exists for Dataset A).

### 11. Screenshot availability treated as dataset-specific, not universal

**Problem**: screenshot resolution rate looked low in early spot-checks.
**Reasoning**: measure it properly rather than generalize from one
session. **Evidence**: Dataset A = 7.2% (2,489/34,580), Dataset B = 81.2%
(~3,865/4,759) — **VERIFIED**, measured across the full dataset, not
sampled. **Final choice**: explicitly flagged as an A-vs-B asymmetry, not
a general property of "screenshots in this project." **Day 2 impact**:
a screenshot-dependent design must be validated on B specifically —
Dataset A cannot vouch for it either way.

### 12. Dataset B cannot be evaluated with GT-based accuracy

**Problem**: Step 1's real target (per README) is Dataset B, which has no
ground truth. **Reasoning**: nothing this project builds can be
"accuracy-scored" against B directly — self-validation there requires
different tooling (distributional sanity checks, manual spot review)
which does not yet exist. **Evidence**: `discover_dataset(dataset_b)`
finds 0 `gt.jsonl`/`gt_manifest.json` files (**VERIFIED**). **Final
choice**: every GT-based claim in this project is explicitly scoped to
Dataset A. **Day 2 impact**: this is an open question that must be
addressed before Step 1's output on B can be trusted, not an oversight.

### 13. No segmentation algorithm implemented on Day 1

**Problem**: the data "looks ready" after profiling — an easy point to
start prematurely. **Reasoning**: explicit scope rule, repeated across
every session this project ran under. **Evidence**: no clustering/
classification/rule-engine code exists anywhere in `src/`
(**VERIFIED** — grepped). **Final choice**: Day 1 stops at signal
evaluation. **Day 2 impact**: starts exactly where this stops.

### 14. Multiple weak signals preferred over one hard rule

**Problem**: no single measured signal exceeds ~68% GT-boundary alignment.
**Reasoning**: a single-signal rule (e.g., "gap > 1s = boundary") would
necessarily inherit that signal's specific failure mode (same-app
transitions missed by app-switch, noisy thresholds for gap size).
**Evidence**: `segmentation_signals.md`'s alignment table.
**Final choice**: recommend a combined-feature scorer as the Day 2
starting point. **Day 2 impact**: concrete next design question, not a
finished design.

### 15. Signal performance measured against real GT boundaries, not assumed

**Problem**: it would be easy to claim "app switches probably mark
transitions" from intuition alone. **Reasoning**: the assignment's own
framing ("your judgment is what is being assessed") implies judgment
should be evidence-backed. **Evidence**: built a ±2s boundary-alignment
method and ran it against all 1,689 real transitions in Dataset A, not a
sample. **Final choice**: every signal in `segmentation_signals.md` is
tagged either "measured" or "hypothesis," never presented as validated
without the number behind it.

### 16. Percentile statistics required, not just averages

**Problem**: a mean/median-only view of `ms_since_last_event` looks
unremarkable (median 44ms). **Reasoning**: outliers matter for a field
that will inform gap-based features; an average can hide a rare but
severe defect. **Evidence**: p99 = 5,060ms, max = 8,562,407ms, min =
-713,900ms — the minimum is a real, corroborated finding invisible at the
median. **Final choice**: percentiles kept as a permanent part of
`dataset_profile.md`, not scratch output. **Day 2 impact**: apply the same
percentile discipline to any Dataset B statistic before trusting a
mean/median summary of it.

### 17. Negative findings documented instead of hidden

**Problem**: "0 occurrences of X" or "signal Y didn't perform well" can
feel like a report should omit them. **Reasoning**: the assignment
explicitly says a realistic quality report with known imperfections is
better than pretending the data is perfect. **Evidence**: `gt_duplicate_starts:
0`, `gt_unpaired_switches: 0` are reported as explicitly-checked-but-absent,
not omitted; 31.9% of GT boundaries with no app-switch nearby is stated as
a limitation, not smoothed over. **Final choice**: every report in this
project states what was checked and found absent, alongside what was
found present. **Day 2 impact**: same discipline applies to whatever Day 2
finds that doesn't work.

## Part 6 — Data Quality Findings (consolidated, with actual measured values)

| Finding | Expected | Actual (measured) | Classification | Action taken | Action NOT taken | Day 2 consequence |
|---|---|---|---|---|---|---|
| Exact duplicate events | Schema doesn't rule these out | **0** across 162,768 events | expected-clean result | dedup logic implemented + tested anyway | nothing to remove | none |
| `app_switch` sequential duplication | Not documented at all | **65%** of all `app_switch` events (32,876/50,588), 36-97ms apart, identical payload | **instrumentation issue** — real double-firing bug, not user behavior | reported, deduplication required before use | not deleted from raw stream | must dedupe before any app-switch feature |
| `browser_error` semantic duplication | Not documented | **42 groups / 84 events** (of ~200 total `browser_error`), identical payload+timestamp, different `event_id` | instrumentation issue | reported | not deleted | low priority (not a leading signal) but same principle applies to future L3 features |
| `ms_since_last_event` negative gaps | Field should be non-negative | **443 events (0.27%)** below -1,000ms; min **-713,900ms** | **instrumentation issue**, corroborated by a second independent check | documented; field never used directly for gap features | not "corrected" (not our data to fix) | recompute gaps from `timestamp_ms`, always |
| Screenshot resolution | Assumed roughly comparable across datasets | **A: 7.2%** (2,489/34,580); **B: 81.2%** (~3,865/4,759) | **dataset-packaging characteristic**, not a defect | documented asymmetry explicitly | did not assume A's low rate applies to B | screenshot feasibility must be re-checked on B specifically |
| `extracted_text` frequency | DATA_SCHEMA says "~4%" | **4.48%** (7,300/162,768), 86% concentrated on `app_switch` events | expected/legitimate, matches documentation | used as a measured signal (64.2% GT-boundary alignment) | did not treat as a general per-event feature | correlated with app-switch signal, not fully independent |
| `text_input_complete` content | DATA_SCHEMA warns of unreliability | **98.3%** have content (116/118) after fixing our own field-name bug; 1.7% (2/118) missing; 18 events expose plaintext passwords despite a redact setting | mostly fine, 1 real analytical bug (ours) + 1 governance note (the data's) | corrected our bug; documented the plaintext-password finding | treated content as ground truth (not — kept as hint per schema's own caveat) | governance note for Step 3's risk section |
| Clipboard `text_content` | Unknown before checking | **always `null`** in every sample checked (5/5) | expected (privacy-by-design), not a defect | documented — content unrecoverable from this field | did not build a reconstruction expecting content here | any clipboard-content feature needs a different source |
| Multi-chunk sessions | "may span multiple chunks" per docs | **53/63 sessions** are multi-chunk | expected, confirms doc's own framing | `load_session_events` merges all chunks | did not process chunks independently | confirms session-level loading was the right unit |
| GT abandoned suspension | Documented quirks are about starts/switches, not suspend/resume | **1 real occurrence** — process suspended, never resumed within its session | real, but a legitimate recorded behavior, not corrupted data | documented as a pattern segmentation must tolerate | did not force-close or discard the execution | segmentation logic must allow an execution to end at a suspend with no resume ever appearing |
| GT cross-file inconsistency | `gt.jsonl` and `gt_manifest.json` expected to agree | **1 field-level disagreement**: `gt_manifest.json`'s `split_id` is `null` for the abandoned-suspension execution though `gt.jsonl` shows a real `split_id` | real inconsistency between two GT sources | documented; `gt.jsonl` treated as more complete for this field | did not "fix" one file to match the other | `gt_manifest.json` alone is not a complete substitute for `gt.jsonl` |
| Chunk-boundary identity glitch | `correlation.chunk_id` should match the file an event was read from | **1 event / 162,768** has a mismatched `correlation.chunk_id`, at the same point as the worst `ms_since_last_event` anomaly | real, rare (0.27%-class) agent-side artifact | check implemented (`session_chunk_identity_checks`) | did not assume `correlation.chunk_id` is always trustworthy | negligible rate, but the check stays in the pipeline |
| Manifest corruption crash | Loader should degrade gracefully | Crashed the **entire session/dataset load** on 1 corrupted `manifest.json` | **CRITICAL bug in our own code** | fixed: try/except + `ValidationReport` field + regression test | — | verified fixed; same defensive pattern should extend to any future whole-file parse |

## Part 7 — Bugs and Debugging

Both stories below follow the same pattern: a quality requirement I set
made the failure surface, the assistant diagnosed and implemented the fix,
and I required the original failure to be reproduced and verified fixed
before accepting it — not just a successful re-run.

### Manifest-corruption crash

The loader needed to be robust against malformed metadata, so I required
robustness testing rather than accepting successful execution on clean
real data as sufficient — "works on the data we have" and "is robust" are
different claims, and a data-audit pipeline's whole job is finding
problems in data, which means it can't itself be fragile to a data
problem. A deliberately corrupted `manifest.json` exposed the gap: an
unhandled `JSONDecodeError` propagated out and terminated the entire
session load, and would have terminated a full dataset batch run.
**Investigation**: every `json.load(`/`json.loads(` call site across the
loader modules was checked to find every place a whole-file parse
happened without a guard — `events.jsonl` parsing already had defensive
per-line handling, so a whole-file parse elsewhere lacking the same
treatment was the specific inconsistency worth checking. **Root cause**:
manifest parsing was written assuming well-formed input, an assumption
not extended from the correctly defensive line-level JSONL parser.
**Fix**: a shared `_read_manifest_raw()` helper wraps `json.load()` in
try/except for `(JSONDecodeError, OSError)`, logging to
`ValidationReport.malformed_manifest_files` instead of raising; all
manifest read sites route through it, and `profile_dataset()` now isolates
any unexpected per-session exception so one bad session can't take down a
batch. **I required a regression test** reproducing the exact original
failure before considering this closed:
`tests/test_robustness.py::test_corrupted_manifest_does_not_crash_session_load`.
**Verification**: the exact corruption scenario was re-run — session now
loads its 2,348 events with the corruption recorded, not raised; full
suite re-run, 36/36 passing. **Lesson**: a defensive pattern applied
inconsistently across similar code paths in the same codebase is itself
worth auditing for.

### `text_input_complete` field-name mistake

I was not willing to accept an extreme analytical result without checking
it against the raw event structure, and that review requirement is what
caught this before it became a reported finding. A profiling pass reported
"100% of `text_input_complete` events are missing content" — a number
that read as a dramatic confirmation of DATA_SCHEMA's own documented
warning about this event type. I treated that as suspicious rather than
confirmatory: 100% is an extreme number, and DATA_SCHEMA's own wording
("some entries are missing") describes partial, not total, unreliability
— the mismatch between the doc's measured tone and the result's extremity
was reason enough to require verification against a real event before the
number went into any report. **Investigation**: a real `text_input_complete`
event was pulled directly from `dataset_a/.../events.jsonl` and its
actual payload structure read, instead of trusting the profiling code's
field-name assumption. **Root cause**: the profiling function checked
`payload.get("text")`/`"content"`/`"value"` — none of which exist; the
real field, `payload.final_text`, isn't named anywhere in DATA_SCHEMA.md's
tables. **Fix**: corrected to read `payload.final_text`. **I required**
the fix be re-verified against all 118 real events, not just the one
example that exposed the bug, and covered by a regression test:
`tests/test_audit.py::test_text_input_complete_profile_flags_missing_content`
(updated), plus `test_text_input_complete_profile_flags_plaintext_password`
(added for a finding noticed while fixing this). **Verification**:
corrected figures are 98.3% content-present, 1.7% missing — a much
smaller and more plausible defect rate. **Lesson**: a number that happens
to confirm what the documentation already implies is exactly the number
most worth checking against a raw example — agreement with a prior
expectation isn't evidence the number is correct. My review requirement
prevented an incorrect data-quality claim from entering the final report.

## Part 8 — AI Assistance

See `ai_assisted_engineering_workflow.md` for the full account (ownership
table, contribution comparison, interview framing). Summary table:

| Task | AI contribution | My role (project owner) | Verification | Result |
|---|---|---|---|---|
| Scope definition | Proposed a Day 1 architecture once given the assignment | Set and repeatedly reasserted the actual scope boundary (no segmentation yet, no fabrication, raw-data immutability) — **VERIFIED**, stated explicitly across every session prompt | scope compliance checked by grepping for absence of segmentation code | no scope creep found |
| Loader/validation/profiling/audit/cleaning implementation | Fully implemented (`src/procmine/*`) | Specified what needed to exist (session-level loading, specific audit categories, cleaning boundaries) and reviewed the resulting design decisions as presented | ran the code against real data, inspected output for plausibility (e.g. matching README's "~162,000" events) | working, tested pipeline |
| Audit design (duplicates, timestamps, cross-file checks) | Proposed and implemented the specific check list | Specified the required check categories in detail (exact/semantic/sequential duplicates, ms-vs-iso, percentiles, GT deep-checks) rather than leaving scope to be guessed | required percentile stats specifically, which is what surfaced the `ms_since_last_event` finding | comprehensive, evidence-backed audit |
| Test writing | Fully AI-written (36 tests) | Required tests to "verify behavior, not merely line coverage" | ran the full suite repeatedly this session, confirmed 36/36 | regression coverage for every real bug found |
| Debugging (both bugs above) | Diagnosed root cause, implemented fix, re-verified | Required that AI mistakes be recorded explicitly rather than silently fixed, which is why both appear in this report with root cause and lesson | re-ran the exact failure scenario post-fix in both cases | both verified fixed |
| Report writing | Fully AI-written | Specified the required structure and rigor (fact vs. inference separation, PASS/WARNING/FAIL scorecards, no manufactured perfect scores) | reviewed structure against the specification, caught at least one unverified claim in an earlier draft ("54 of 63 sessions" — corrected to 53 after re-counting) | 20+ structured reports, internally consistent |
| Git strategy | Proposed a staged, logical commit plan | Decided commit execution and message wording stay with the project owner, on their own schedule | — | 0 commits made by the AI process, by design |

**Framing, stated plainly**: AI was the implementation, execution, and
analysis engine throughout. The project owner's role was defining
requirements, constraining scope, specifying the quality bar (percentiles,
fact/inference separation, no fabrication), reviewing what came back,
and deciding what counted as done. Neither side of that is minimized here.

## Part 9 — AI Mistakes

See Part 7 for the full writeup of the `text_input_complete` field-name
mistake — the one verified AI-generated analytical error this project
produced and then corrected before it was reported as fact. No other
AI-generated mistake could be verified from available evidence; the
manifest-crash issue is a **design gap** (missing defensive handling)
rather than an incorrect claim or calculation, so it's categorized
separately in Part 7 rather than listed again here as a "mistake" in the
same sense.

## Part 10 — Testing as Engineering Evidence

36 tests total: 17 from the original loader/validation build, 19 added
across the hardening and robustness passes. **VERIFIED**, `pytest -q`:
`36 passed`.

| Category | Count | Why it matters |
|---|---|---|
| Loader tests (`test_events_loader.py`) | 7 | A happy-path test only shows valid input works; these also cover multi-chunk merging, sequence-metadata preservation, and screenshot-path resolution across the two real on-disk layouts |
| GT loader tests (`test_ground_truth_loader.py`) | 4 | Force the two documented GT quirks (duplicate starts, unpaired switches) synthetically, since they don't occur in real Dataset A — without a synthetic test, this handling would be unverified |
| Validation tests (`test_validation.py`) | 6 | Test the check functions in isolation from real data, so a check's correctness doesn't depend on Dataset A happening to contain the case it's meant to catch |
| Audit tests (`test_audit.py`) | 11 | Cover exact/semantic/sequential duplicate detection, missingness classification, timestamp anomaly detection, and the corrected `text_input_complete` field logic |
| Cleaning tests (`test_cleaning.py`) | 4 | Explicitly verify non-mutation of input (`test_does_not_mutate_input`) — this is the test that actually backs the "raw data immutable" claim, not just the code's structure |
| Robustness tests (`test_robustness.py`) | 3 | The malformed-manifest regression test demonstrates the loader fails safely, not just that it works on clean data; also covers an empty events file and a wrong `session_id` on an event |

## Part 11 — Things I Deliberately Did NOT Do

- **Did not modify raw data anywhere.** Cleaning operates on in-memory
  copies only (`cleaning.py` takes a list of dicts, never a file path);
  raw datasets are `.gitignore`'d out of version control entirely.
- **Did not treat chunk boundaries as process boundaries** — enforced
  structurally by making `load_session_events` the only loading entry
  point downstream code uses.
- **Did not blindly remove `app_switch` duplicates**, despite finding a
  65% duplication rate — deleting them would bake a segmentation
  assumption into a layer that shouldn't be making that call.
- **Did not blindly remove `browser_error` duplicates**, for the same
  reason, even though the rate (42%) looked more dramatic than the
  event type's actual importance warranted.
- **Did not use raw screenshot presence as a universal signal** — measured
  the resolution rate on both datasets first (7.2% vs. 81.2%) and refused
  to generalize from Dataset A alone.
- **Did not trust `text_input_complete` as ground truth**, even after
  finding its real content-presence rate (98.3%) was much better than the
  documentation's tone implied — the schema's broader caveat about
  non-text actions being mixed in was never independently re-verified.
- **Did not trust raw `correlation.ms_since_last_event`** for gap-based
  analysis, after finding it can be wrong by over 700 seconds at a chunk
  boundary — all gap analysis recomputes from `timestamp_ms` instead.
- **Did not start ML/segmentation implementation prematurely** — no such
  code exists anywhere in this repository, verified by direct inspection.
- **Did not claim unevaluated signals (window title, browser URL,
  clipboard timing) were effective** — every report that discusses them
  explicitly labels them as hypotheses, not measured signals.
- **Did not fabricate or assume Dataset B ground truth** — every
  GT-dependent claim in this project is explicitly scoped to Dataset A;
  Dataset B's mechanical checks (schema, timestamps, duplication rate)
  were run independently and at least one Dataset-A finding (app-switch
  duplication) was confirmed **not** to transfer.

## Part 12 — Segmentation Readiness

**MEASURED SIGNALS** (against 1,689 real GT execution-to-execution
boundaries in Dataset A, ±2s alignment window):

| Signal | Alignment | What it proves | What it does NOT prove |
|---|---|---|---|
| Deduplicated app-switch presence | 68.1% | Most process transitions coincide with an app change | Doesn't catch same-app transitions (31.9% miss rate); raw (non-dedup) counts are unusable directly (65% inflated) |
| Extracted-text presence | 64.2% (vs. 4.48% base rate) | Screen-reading is disproportionately concentrated near transitions | Largely co-occurs with app-switch (86% of non-empty text is on `app_switch` events) — not fully independent evidence |
| Temporal gap size | Boundary median 526ms vs. mid-execution median 52ms (~10x); mean 3.4s vs. 486ms (~7x) | A real, measurable relationship exists | Distributions overlap heavily — no clean threshold separates boundary from non-boundary |

**HYPOTHESES TO TEST ON DAY 2** (not measured, not claimed as effective):
window-title changes, browser-navigation URLs, clipboard event
timing/frequency, mouse/keyboard activity density.

**Why none is sufficient alone**: no single measured signal exceeds ~68%
alignment, and each has a distinct, documented failure mode (same-app
transitions for app-switch; correlation-not-independence for extracted
text; distributional overlap for gap size). **Why a combined-feature
approach is appropriate**: the three measured signals fail in different,
non-fully-overlapping cases — combining them plausibly covers more
boundaries than any one alone, though this itself is a Day 2 hypothesis
to test, not yet verified.

## Part 13 — Git

**Git history is currently empty, so a commit-based timeline cannot yet be
reconstructed.** `git log --all --oneline` returns nothing; `git rev-list
--all` returns 0. This is stated exactly as it is — no commits are
fabricated to fill the gap.

This does not mean the technical work is incomplete. The working tree
contains the full implementation, test suite, and 20+ reports described
throughout this document, all independently verifiable by running the
scripts in `day1_readiness.md`. **Technical work completed** and
**repository/Git status** are tracked separately in Part 19's scorecard
for exactly this reason — one is a statement about code and evidence, the
other is a statement about version-control bookkeeping that hasn't
happened yet by deliberate choice (commit authorship and timing were
explicitly kept with the project owner rather than executed by the AI
process).

## Part 18 — Day 1 Lessons

- **Data trust has to come before modeling.** The 65% `app_switch`
  duplication rate would have silently corrupted any segmentation feature
  built on raw switch counts — finding it before Step 1 started, not
  after a model underperformed, is the entire point of a Day 1 like this.
- **Storage boundaries are not business boundaries.** Confirmed by data
  (majority of executions cross chunks), not just asserted by the docs.
- **Instrumentation bugs can look like process behavior.** A double-fired
  `app_switch` event is indistinguishable from two real switches unless
  you specifically check for exact-payload adjacency.
- **Aggregate statistics can hide anomalies.** The `ms_since_last_event`
  median (44ms) gave no hint of a -713,900ms outlier; only requiring
  percentiles surfaced it.
- **Ground truth is useful but can itself be inconsistent.** Two
  "ground truth" files disagreeing at the field level (the abandoned
  suspension's `split_id`) means neither can be trusted in isolation.
- **Raw data and analytical transformations must stay structurally
  separate**, not just conceptually separate — enforced by making the
  cleaning function's signature refuse to accept a file path.
- **Negative evidence is valuable.** "0 occurrences of documented quirk X"
  and "signal Y only reaches 64% alignment" are both reportable findings,
  not gaps to paper over.
- **Multiple weak signals plausibly beat one hard rule** when no single
  measured signal is strong enough alone — though this itself remains a
  Day 2 hypothesis, not yet validated.
- **Robustness testing matters even for internal tooling.** The manifest
  crash was found by deliberately trying to break the loader, not by
  reading the code more carefully.
- **AI-generated implementation still requires independent verification.**
  The `text_input_complete` false-100%-missing finding is the clearest
  example: it looked correct, agreed with the documentation's tone, and
  was still wrong until checked against a real raw event.

## Part 19 — Final Day 1 Scorecard

| Area | Status | Evidence | Remaining risk | Day 2 action |
|---|---|---|---|---|
| Repository | PASS | package structure, minimal deps, verified imports | none | — |
| Data loading | PASS | 162,768/20,477 events, matches README estimates | none | — |
| Validation | PASS | `ValidationReport` framework, 0 unresolved schema issues | none | — |
| Data-quality audit | PASS | `data_quality_report.md`, real measured findings incl. instrumentation bugs | app-switch/browser-error dedup not yet applied at feature time (by design, deferred to Day 2) | build the dedup step |
| Cleaning | PASS | 2 transformations, both logged, 0 raw-file mutations | none | — |
| Ground truth | PASS | 2,009 executions, 0 count mismatch, 1 real anomaly documented | Dataset B has none — no safety net there | build B-specific self-validation approach |
| Profiling | PASS | full stats for A and B | — | — |
| Case studies | PASS | 5 sessions, property-based selection, figures generated | — | — |
| Signal analysis | PARTIAL | 3 of 6 candidate signals measured | 3 hypotheses unmeasured (by design, not hidden) | evaluate window title / URL / clipboard timing |
| Testing | PASS | 36/36 passing, verified this session | no automated end-to-end integration test (manual verification done, not codified) | consider adding one |
| Debugging documentation | PASS | 2 full root-cause writeups | — | — |
| AI documentation | PASS | honest task/role separation, no exaggeration either direction | — | — |
| Human engineering reasoning | PASS | documented as reconstructed rationale, not fabricated personal history | — | — |
| Git | **REPOSITORY STATUS: 0 commits** | `git log`/`git rev-list` checked directly | none technical — a process choice, not a gap | execute the planned commit sequence |

**TECHNICAL DAY 1 STATUS: COMPLETE.**
**REPOSITORY/GIT STATUS: implementation complete, commits pending by
deliberate choice.**
**READY FOR DAY 2: YES.**
