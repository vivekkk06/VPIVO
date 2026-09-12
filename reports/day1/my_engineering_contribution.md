# My Engineering Contribution

This is the central account of what I owned on Day 1. Engineering
contribution is not measured only by lines of code — a person can own
system design, requirements, methodology, test strategy, validation
criteria, data-quality strategy, interpretation, risk assessment, and
scope management while using AI to accelerate implementation. That's the
model this document uses throughout: I owned the problem, the methodology,
and the decisions; the AI coding assistant executed them faster than I
could have alone.

Verification note: every claim below that I "required" or "specified"
something traces to an explicit instruction in this project's own working
sessions — most of the methodology listed in section 3 was written out in
full, in advance, as a working requirement, before the corresponding code
existed. That's checkable, not asserted. Where a claim can't be traced
that specifically, it's marked as such rather than stated as fact.

---

## 1. Problem Framing

The assignment (README.md) is explicit that technical accuracy isn't the
objective by itself — judgment about how to spend the available time is
what's being assessed, and Step 1's segmentation output is only as good as
whether the underlying log data can be trusted to mean what it appears to
mean. I framed Day 1 around that constraint specifically: before any
segmentation logic gets written, the question that has to be answered
first is whether a count, a timestamp, or a field in this log can be
trusted as a feature. That framing is why Day 1 became a full data-trust
audit rather than a quick pass through the loaders — a decision that
directly produced the 65% `app_switch` duplication finding, which would
have silently broken a naive segmentation feature if it had gone
unnoticed.

## 2. Scope Control

I enforced, repeatedly and explicitly, that no segmentation or ML
implementation would happen on Day 1 — this appears as a standing
instruction across every session of this work ("Do NOT jump to machine
learning yet," "Do NOT start building the segmentation algorithm," "Do not
start segmentation implementation in this task"). I treated this as a
scope boundary, not a suggestion: it's verifiable that no clustering,
classification, or rule-engine code exists anywhere in `src/` — the scope
boundary held for the entire duration of Day 1, not just at the start.

## 3. Methodology Definition

The following methodological requirements were specified as explicit
working requirements, in writing, ahead of the implementation that
satisfies them:

- **Raw data immutability** — the raw dataset must never be modified;
  cleaning must produce a derived representation, never edit the source.
- **Session-level analysis, chunk ≠ process boundary** — chunks are a
  recording/storage artifact, and this had to be explicitly confirmed
  against real data, not just asserted from the schema doc.
- **Percentile statistics, not just averages** — required specifically for
  `ms_since_last_event` (min/median/mean/p90/p95/p99/max), on the grounds
  that a mean or median can hide a rare but severe timing anomaly.
- **Multi-level duplicate analysis** — exact record duplicates, duplicate
  event IDs, duplicate-timestamp-and-type-and-payload combinations,
  sequential (consecutive) duplicates, and GT-specific duplicate starts —
  specified as five distinct categories to check, not one generic
  "check for duplicates."
- **Timestamp and ordering validation** — `timestamp_ms` vs. `timestamp_iso`
  consistency, negative gaps, unusually large gaps, with an explicit
  instruction that a large gap is a *candidate* signal only, never an
  automatic process boundary.
- **Ground-truth cross-validation** — `gt.jsonl` and `gt_manifest.json`
  had to be checked against each other, with an explicit instruction not
  to silently "fix" any documented GT quirk found.
- **Evidence-based signal evaluation** — an explicit rule that no
  candidate segmentation signal could be reported as effective without
  being measured against real GT boundaries first.
- **Fact vs. inference separation** — every report in this project
  distinguishes verified fact from reconstructed reasoning from
  assumption, because that distinction was set as a hard requirement, not
  a stylistic preference.
- **No fabricated results** — explicit, repeated, and treated as
  non-negotiable across every phase of this work.
- **Behavior-focused tests** — tests were required to "verify behavior,
  not merely line coverage," which is why each real bug found has a named
  regression test reproducing the original failure, not just a coverage
  bump.
- **Dataset A vs. Dataset B separation** — an explicit requirement that
  Dataset A's ground-truth-backed findings never be assumed to transfer to
  Dataset B, which has none.

## 4. Investigation Direction

Specific instances where deeper investigation, verification against raw
data, or hypothesis-testing (rather than assumption) was required as a
matter of standing methodology:

- Profiling `text_input_complete` for missing/invalid examples was an
  explicit requirement ("Profile text_input_complete quality. Identify
  missing/invalid examples") — the investigation that surfaced the wrong
  field-name bug was executing that requirement, not a spontaneous side
  quest.
- The instruction that "extracted_text is present on roughly 4% of
  events... DO NOT assume screen text exists for every event" is what
  shaped the extracted-text profiling into a distribution analysis rather
  than a simple presence check.
- "Do not assume existing code is correct just because it exists" was
  stated explicitly before the hardening pass that found the manifest
  crash bug — the stress test that exposed the crash was a direct
  response to that standing instruction to distrust prior work by default.
- "Do NOT claim a signal works until it is actually evaluated" is the
  exact rule that produced the measured-vs-hypothesis split in the
  segmentation signal analysis, rather than a single undifferentiated
  list of "signals that might work."
- Cross-checking Dataset A against Dataset B specifically (rather than
  treating Dataset A's findings as universal) was required explicitly —
  the app-switch duplication rate was checked against all 15 Dataset B
  sessions specifically because of this requirement, and found not to
  transfer (0% there vs. 65% in A).

## 5. Engineering Judgment

Decisions where one approach was chosen over an available alternative, on
stated reasoning:

- Chose cross-checking `gt.jsonl` against `gt_manifest.json` over trusting
  either file alone — the disagreement over the abandoned suspension's
  `split_id` would not have surfaced otherwise.
- Chose deferring `app_switch`/`browser_error` deduplication to the
  segmentation/feature layer over deduplicating during cleaning — on the
  reasoning that "what counts as one real switch" is an interpretive
  decision that needs to stay visible and testable, not buried in a
  preprocessing step.
- Chose recomputing gaps from sorted `timestamp_ms` over trusting the
  agent's own `ms_since_last_event` field directly, once that field was
  shown to be unreliable at a chunk boundary.
- Chose not to generalize Dataset A's screenshot-scarcity finding (7.2%)
  to Dataset B — measuring both independently is what caught the 81.2%
  figure in B, which contradicts the naive generalization.

## 6. Quality Ownership

The standard for "Day 1 is done" was set explicitly, not left implicit:
every planned check had to actually run against real data (not be assumed
to pass), every finding needed a number behind it, every AI-introduced
mistake had to be documented with root cause rather than quietly patched,
and nothing outstanding could be a hidden blocker. That standard is why
this project has a `debugging_log.md` at all, and why the completion gate
in `day1_readiness.md` marks git status as a separate, honestly-labeled
PARTIAL rather than folding it into an overall PASS.

## 7. Review and Verification Loop

The pattern that recurs throughout this project: **requirement stated →
AI implements/executes → output produced → output questioned when it
looks suspicious → verified against raw data or a second independent
check → corrected if wrong → accepted only after verification.** The
clearest example: an early `text_input_complete` profiling pass reported
100% missing content, which was not accepted at face value because it read
as more extreme than the documentation's own "some entries are missing"
framing — the field assumption was checked against a real raw event before
the number was allowed into a report. That review step is what caught a
wrong analytical result before it became a false finding.

## 8. Iteration

This project went through multiple deliberate rounds, not one pass treated
as final: an initial build (loaders, profiling, GT parsing, 17 tests), a
hardening pass that specifically distrusted the first pass and found a
real crash bug, a formalization pass that re-derived and cross-checked
numbers rather than restating them (catching an uncounted claim — "54 of
63 sessions" — before it went into a report, correcting it to 53), and
this reconstruction pass. Treating the first version of anything as a
draft to be stress-tested, rather than a finished result, is a deliberate
choice that runs through the whole project, not an accident of how the
work happened to unfold.

---

## My Ideas / Requirements Table

| My input/requirement | Why it mattered | What AI did | What happened | My decision | Result |
|---|---|---|---|---|---|
| Treat raw data as immutable | Prevents ever losing the ability to distinguish "what the data says" from "what we did to it" | Implemented `cleaning.py` to take in-memory dicts only, never a file path | Structurally enforced, verified by a non-mutation test | Kept as a hard rule throughout | 0 raw files modified anywhere in the project |
| Session, not chunk, as the process-execution unit | Chunk is a storage boundary per the schema; treating it as a process boundary would split executions | Implemented `load_session_events` with multi-chunk merge | Checked against GT: majority of 2,009 executions cross chunks | Made session-level loading the only entry point | 53/63 sessions confirmed multi-chunk, validating the design |
| Percentile statistics (p90/p95/p99), not just mean/median | An average can hide a rare, severe anomaly | Computed the full percentile spread for `ms_since_last_event` | Median looked normal (44ms); min was -713,900ms | Investigated the extreme value instead of dismissing it as noise | Found and documented a real chunk-boundary data defect |
| Multi-level duplicate analysis (exact/semantic/sequential/GT) | A single "duplicate count" metric hides which category actually matters | Implemented all four categories separately | 0 exact, 42 semantic (browser_error), 33,232 sequential (mostly app_switch) | Required a type breakdown before accepting the aggregate number as meaningful | Found the 65% app_switch duplication specifically, not just "some duplicates exist" |
| Don't assume a time gap means a process boundary | Prevents a naive, overconfident segmentation heuristic | Measured actual gap-size distribution at real GT boundaries vs. mid-execution | ~10x median difference, but heavily overlapping distributions | Treated gap size as one weighted feature, not a hard rule | Segmentation signal report explicitly avoids claiming a gap threshold works |
| GT should be treated as evidence, not assumed perfect | Two "ground truth" files could silently disagree | Cross-checked `gt.jsonl` reconstruction against `gt_manifest.json` | Found 1 field-level disagreement (an abandoned suspension's `split_id`) | Documented the disagreement rather than picking one file as automatically correct | `gt_manifest.json` alone confirmed not to be a complete substitute for `gt.jsonl` |
| Verify a suspicious extreme result against raw data before reporting it | An implausibly extreme number (100% missing) deserved scrutiny before being written down as fact | Re-checked a real `text_input_complete` event's raw payload | Found the real field name (`payload.final_text`), corrected the analysis | Required the fix be verified against all 118 real events before accepting the new number | Corrected finding: 98.3% populated, not 0% |
| Don't claim a signal works until it's actually evaluated | Prevents overstating what Day 1 established | Built a ±2s GT-boundary alignment method; measured 3 signals | 3 signals measured (68.1%/64.2%/gap ratio), 3 explicitly left unmeasured | Labeled every signal "measured" or "hypothesis," never blended | `segmentation_signals.md` makes no unearned claims |
| Compare Dataset A and Dataset B independently, don't assume transfer | Dataset A findings could be an A-specific artifact | Ran the mechanical audit checks against Dataset B directly | App-switch duplication: 0% across all 15 Dataset B sessions vs. 65% in A; screenshots: 81.2% in B vs. 7.2% in A | Rejected the assumption that A's findings generalize | Two major A-specific findings identified and explicitly flagged as non-transferable |
| Record AI mistakes rather than hiding them | Silently fixing a bug destroys the evidence of whether the fix addresses the real root cause | Diagnosed and fixed both the manifest crash and the field-name bug, then documented root cause for each | Two full root-cause writeups exist in `debugging_log.md` | Required a regression test for each, not just a patch | Both bugs verifiably fixed and covered by tests |
| Don't destroy the raw `app_switch`/`browser_error` duplicate events | Deduplication is a segmentation-time interpretive decision, not a data fact | Implemented duplicate detection without deletion | 65%/42% duplication rates reported, 0 events removed | Deferred the dedup decision to the segmentation/feature layer explicitly | The assumption stays visible and testable instead of hidden upstream |
| Behavior-focused tests, not coverage-focused tests | A passing happy-path test doesn't prove a failure mode is actually handled | Wrote 36 tests, including named regression tests for each real bug | 36/36 passing | Required each bug to have a test reproducing the original failure | Test suite functions as verifiable proof of fixes, not just a coverage number |
