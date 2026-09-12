# Debugging Log (Part 22)

Every meaningful technical problem hit during Day 1, including AI-generated
mistakes, in full. Nothing here is hidden or smoothed over.

## Engineering Reasoning

I required this document to exist because the alternative — quietly fixing
a bug and moving on — throws away exactly the evidence that shows whether
a fix actually addresses the root cause or just the symptom. My rule was:
every bug gets a reproduction, a root cause, a fix, and a re-run of the
original failure scenario, not just "it works now." That standard is why
the `text_input_complete` entry below exists at all — it would have been
easy to just quietly correct the field name and move on, but the false
"100% missing" number had already looked like a legitimate finding for a
few minutes, and documenting how that happened is more useful than hiding
that it happened.

---

## 1. Corrupted `manifest.json` crashed the entire session/dataset load

**Problem**: Fed the loader a session with one deliberately corrupted
`manifest.json` (via a script that copies a real session and overwrites one
manifest with the text `{not valid json`). The load crashed with an
unhandled `JSONDecodeError` instead of degrading gracefully.

**Initial assumption**: None yet formed — this was a deliberate stress test
of code that had only been run against clean real data and synthetic
fixtures, specifically because "assume existing code is correct just
because it exists" was the thing to avoid.

**Diagnosis**: Grepped for every `json.load(` / `json.loads(` call site in
`loaders/events.py` and `loaders/ground_truth.py`. `events.jsonl` parsing
(`read_jsonl`) already wrapped each line in try/except and recorded
failures to `ValidationReport.malformed_json_lines`. Three other call
sites — `load_chunk_manifest`, the manifest read inside
`load_session_events`, and `load_gt_manifest` — called `json.load()`
directly with no exception handling at all.

**Root cause**: An inconsistency introduced when the loaders were first
written — line-level JSONL parsing got defensive handling from the start
(because "one bad line among thousands" was an obvious risk to design for),
but whole-file manifest parsing was written assuming the file is always
well-formed, which is not a safe assumption for either recording defects or
future data.

**Fix**: Added `_read_manifest_raw()` in `loaders/events.py`, wrapping
`json.load()` in try/except for `(json.JSONDecodeError, OSError)`, logging
to a new `ValidationReport.malformed_manifest_files` field, and returning
`None` instead of raising. All three call sites (plus `load_gt_manifest` in
`loaders/ground_truth.py`) route through this pattern now.
`profile_dataset()` was also hardened to catch any unexpected exception per
session so one bad session can't kill a whole dataset batch.

**Verification**: Re-ran the exact same corrupted-manifest scenario —
confirmed the session now loads its 2,348 events successfully with the
corruption recorded in `malformed_manifest_files` instead of crashing.
Added `tests/test_robustness.py::test_corrupted_manifest_does_not_crash_session_load`
so this can't silently regress. Full test suite re-run: 36/36 passing
(count includes 2 other new robustness tests added at the same time —
empty events file, wrong `session_id` on an event).

**Lesson**: "It works on the real data we have" is not the same as "it's
robust." The fix came from actively trying to break the loader with a
plausible real-world failure (a truncated/corrupted write), not from
reading the code more carefully.

---

## 2. Wrong field-name guess produced a false "100% missing" finding

**Problem**: First implementation of `text_input_complete_profile` checked
`payload.get("text") or payload.get("content") or payload.get("value")` for
event content. Running it against real data reported "0 of 118 events have
apparent content — 100% missing," which read as a dramatic (and
plausible-sounding, given DATA_SCHEMA's own warning about this event type)
confirmation of a data-quality defect.

**Initial assumption**: Took the 100%-missing number at face value for a
few minutes as "this confirms the documented unreliability, and it's worse
than the docs implied."

**Diagnosis**: Before writing it down as a finding, pulled a real
`text_input_complete` event directly from `dataset_a/.../events.jsonl` and
read its actual payload structure rather than trusting the profiling code's
assumption.

**Root cause**: The real field is `payload.final_text` — not named
anywhere in DATA_SCHEMA.md's tables. The three guessed field names
(`text`/`content`/`value`) simply don't exist in the real payload, which
also has `keystroke_count`, `duration_ms`, `corrections_count`,
`related_keystrokes`, and `input_context.is_password_field` — none of which
were anticipated from the schema doc alone.

**Fix**: Changed `text_input_complete_profile` in `audit.py` to read
`payload.get("final_text")`. Also added a new
`password_fields_with_plaintext_final_text` counter after noticing, while
fixing this, that some `final_text` values are plaintext passwords for
`is_password_field: true` inputs.

**Verification**: Re-ran against all 118 real events. Corrected numbers:
98.3% have content (116/118), 1.7% missing (2/118) — a much smaller,
more plausible defect rate than the false 100% figure. Updated
`tests/test_audit.py::test_text_input_complete_profile_flags_missing_content`
to use the correct field name, and added
`test_text_input_complete_profile_flags_plaintext_password` for the new
check.

**Lesson**: A number that confirms what you already expected the answer to
be (the schema warns this event type is unreliable) is exactly the number
most worth checking against a raw example before reporting it as fact —
agreement with a prior isn't evidence of correctness.

---

## 3. `ms_since_last_event` contains large negative values at a chunk boundary

**Problem**: Computing percentile statistics for `correlation.ms_since_last_event`
(as requested for Part 6) surfaced a minimum of **-713,900ms** — over 11
minutes negative — which is not a small rounding artifact.

**Initial assumption**: Suspected a bug in the percentile-computation script
(e.g., accidentally including `null` values as 0, or a sign error).

**Diagnosis**: Isolated every event with `ms_since_last_event < -1,000ms`
(443 found) and inspected the most extreme two by `event_id` and session.
Both belonged to `ses_20260701-115141-SIDDHIGUPTAB00B`, at the
`chunk_20260701-1130` → `chunk_20260701-1200` transition — the **same
session and the same chunk transition** already flagged separately by
`session_chunk_identity_checks` for a `correlation.chunk_id` mismatch (an
event's own metadata naming the wrong chunk).

**Root cause**: Not a bug in our analysis code — this is a real defect in
the *source data*, in the recording agent's own internal accounting at a
chunk-transition boundary. The agent's `ms_since_last_event` field appears
to be computed against a reference that doesn't match where the event
actually ended up sequenced, at exactly the same moment its `chunk_id`
metadata is also wrong. Two independently-built checks (one on
`correlation.chunk_id`, one on `correlation.ms_since_last_event`)
corroborating the same anomaly is good evidence this is a real, if rare
(0.27% of events), agent-side artifact rather than two unrelated
coincidences.

**Fix**: No code fix applicable — this is a property of the source data,
not our pipeline. The existing design already avoids trusting this field
directly: gap-based analysis in this codebase recomputes gaps from sorted
`timestamp_ms`, never reads `ms_since_last_event` as authoritative.
Documented the finding and the "never trust this field for gap features"
conclusion explicitly in `data_quality_report.md` Part 6.

**Verification**: Confirmed via direct cross-reference between two
independently written checks (`session_chunk_identity_checks` in
`audit.py`, and the ad-hoc percentile script for this investigation) that
they flag the same event(s), which is what makes this a corroborated
finding rather than a single suspicious number.

**Lesson**: When a metric looks broken, check whether it correlates with a
different, independently-derived anomaly before either dismissing it as
noise or over-investigating it as a code bug — the correlation itself is
often the fastest way to distinguish "our code is wrong" from "the data
really is like this."

---

## Non-issues (checked, found not to be problems)

- **Python 3.14 + matplotlib/pytest compatibility**: this environment runs
  Python 3.14.7, which is new enough that dependency wheels were a real
  risk. `pip install matplotlib pytest` succeeded cleanly with no build
  errors — verified by running the full test suite and generating figures,
  not just by a successful `pip install` exit code.
- **`_read_jsonl` naming**: renamed to public `read_jsonl` when
  `scripts/audit_dataset.py` needed to reuse it — a naming cleanup, not a
  bug, but noted here since it changed a function signature other code
  depended on and needed re-running the test suite to confirm nothing
  broke.
