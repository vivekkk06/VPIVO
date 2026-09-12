# Data Quality Report (Parts 3–18)

All numbers from `scripts/audit_dataset.py`, `scripts/validate_dataset.py`,
and ad-hoc verification scripts run against the real Dataset A this
session. Denominator unless noted: 162,768 events, 63 sessions, 117 chunks.

## Engineering Reasoning

My reasoning going in was that "the JSON parses and required fields are
present" and "I can trust a count of X as a feature" are two different
claims, and only the second one actually matters for Step 1. That's why
this report goes past schema validity into duplicate detection, timestamp
consistency, and payload-shape checks — a validation pass that only
checks structure would have missed the 65% `app_switch` duplication
entirely, since every one of those duplicate events is individually
well-formed JSON. I did not want a clean validation result to be mistaken
for a clean dataset.

## Part 3 — Raw JSONL Validation

| | Count |
|---|---|
| Total lines read across all `events.jsonl` files | 162,768 |
| Malformed JSON lines | 0 |
| Empty lines | 0 (encountered and skipped safely where present; 0 in real data) |
| Records missing a required field (`event_id`, `session_id`, `timestamp_ms`, `timestamp_iso`, `layer`, `event_type`) | 0 |
| Unknown `layer` values | 0 |
| Unknown `event_type` for its `layer` (against DATA_SCHEMA.md's own table) | 0 |

**Severity: none observed.** Dataset A's raw JSONL is schema-clean. This
does not mean the check is unnecessary — `read_jsonl` and
`check_required_fields` still run on every load, and `full_audit_dataset_a.json`
would show any session where this changes.

## Part 4 — Null / Missing Value Audit

Per-field missing/null/empty, computed by `audit.missingness_audit`
(distinguishes "field absent" from "field present but `None`" from "field
present but empty string/dict/list"):

| Field | Missing | Null | Empty |
|---|---|---|---|
| `event_id`, `session_id`, `timestamp_ms`, `timestamp_iso`, `layer`, `event_type` | 0% each | 0% each | 0% each |
| `context` | 0% | 0% | 0% |
| `context.active_app` | present on most events; null on `SYSTEM`-layer events (session_start/end, uploads) — **expected**, there is no foreground app to report at those moments |
| `context.active_browser_tab` | null outside browser activity — **expected**, matches DATA_SCHEMA's description of when this field applies |
| `context.extracted_text` | absent on 95.52% of events — **expected/legitimate**, matches DATA_SCHEMA's own "~4%" claim (measured: 4.48%) |
| `correlation.sequence_number` | 0% missing | — | — |
| `correlation.chunk_id` | 0% missing | — | — |
| `correlation.ms_since_last_event` | null only on the first event of a chunk — **expected** (no prior event to diff against within that chunk) |
| `payload` | 0% missing | some event types have an empty/near-empty payload by nature (see Part 9) | — |

Classification used throughout: **expected/legitimate** (documented sparsity
or structurally impossible fields), **suspicious** (would warrant
investigation — none found at the field level), **invalid** (schema
violation — none found). No field crossed from "expected" into "suspicious"
in Dataset A.

## Part 5 — Duplicate Audit

| Type | Count | Affected | Verdict |
|---|---|---|---|
| Exact duplicate JSON records | 0 | — | remains — nothing to act on |
| Duplicate `event_id` | 0 | — | remains |
| Duplicate timestamps (same `timestamp_ms`, different event) | present, not separately counted — see zero-gap note in Part 6 | multiple | expected — sub-millisecond-resolution UI cascades (a click triggering a browser_click at the same ms) are normal |
| Semantic duplicates (same session+timestamp+type+payload, different `event_id`) | 42 groups / 84 events | 100% `event_type: browser_error` | **data-quality issue** — a real double-logging bug in the L3 browser-error capture path (confirmed via raw payload inspection: identical Chrome extension messaging error, same millisecond, two different `event_id`s). Should be deduplicated before this field is used as a feature, never silently ignored. |
| Sequential duplicates (adjacent, identical payload) | 33,232 events | 98.9% `event_type: app_switch` | **data-quality issue, high impact** — **65% of every `app_switch` event** is an exact back-to-back repeat, 36–97ms apart (not a polling interval — looks like a genuine double-firing bug in the OS hook). Must be deduplicated before any feature uses app-switch counts/timing. |
| GT duplicate `process_started` | 0 occurrences (documented as possible, not observed) | — | handling implemented + tested defensively; Dataset B has no GT to re-check this against |

None of these were deleted from the raw stream — see Part 17 for the
cleaning policy and exactly what *is* safe to normalize vs. what must stay
a reported observation.

## Part 6 — Timestamp and Ordering Audit

- `timestamp_ms` vs. `timestamp_iso`: 0 mismatches (>1s tolerance) across
  all 162,768 events. Both are UTC; 0 non-UTC (non-`Z`-suffixed) timestamps.
- Chronological ordering (raw file order, pre-sort): inversions present in
  every session — see `timestamp_quality.md` (68% trace to `screenshot_smart`
  async capture latency). Our loader always sorts explicitly by
  `timestamp_ms`; this is enforced, not assumed.

**`ms_since_last_event` statistics** (the agent's own recorded field, n =
162,314 non-null values):

| Stat | Value |
|---|---|
| min | **-713,900 ms** |
| median | 44 ms |
| mean | 499.5 ms |
| p90 | 882 ms |
| p95 | 2,188 ms |
| p99 | 5,060 ms |
| max | 8,562,407 ms (~2.4 hours — a genuine long idle gap, not an error) |

**The minimum is a real finding, not noise.** 443 events (0.27%) have
`ms_since_last_event` below -1,000ms. The two most extreme
(-713,900ms and -709,214ms) are **the same event pair** implicated in the
`correlation.chunk_id` identity glitch documented in
`cross_file_consistency.md` (session `ses_20260701-115141-SIDDHIGUPTAB00B`,
chunk transition `1130`→`1200`) — the agent's own gap calculation is
corrupted at exactly the same boundary where the chunk assignment is wrong,
which corroborates that finding independently rather than being a separate
coincidence. A smaller cluster of similar (though less extreme) negative
values appears in at least one other session
(`ses_20260701-131015-SIDDHIGUPTAB00B`, ~-205,000ms), suggesting this class
of chunk-boundary artifact isn't perfectly isolated to one instance, though
its overall rate (0.27% of events) is low.

**Consequence**: never trust `correlation.ms_since_last_event` directly for
gap-based features at chunk boundaries — recompute gaps from sorted
`timestamp_ms` instead, which is what our loader/audit code already does.
Large gaps (per the p99/max figures above) are treated as **candidate**
segmentation signals only, never as automatic process boundaries — see
`segmentation_signals.md`.

## Part 7 — Session / Chunk Consistency

- `event.session_id` matches its containing session directory: verified
  for all events except a check for cross-session leakage was run and
  found none in real data (a synthetic test forces this scenario in
  `tests/test_robustness.py` since it wasn't observed for real).
- `correlation.chunk_id` matches the file the event was physically read
  from: **1 mismatch found** (same event as above).
- Sessions spanning multiple chunks: yes, 53 of 63 sessions have 2+ chunks
  (10 are single-chunk).
- Business processes crossing chunk boundaries: **confirmed** — the large
  majority of the 2,009 GT executions have `continues_from_prev`/
  `continues_to_next: true`. **A chunk is a recording/storage boundary,
  never a business-process boundary** — this is both documented in
  DATA_SCHEMA.md and independently confirmed by our own data.

## Part 8 — Layer and Event-Type Consistency

Event-type frequency (Dataset A, all 162,768 events) — see
`figures/dataset_a_events_by_type.png` for the full chart. Top types:
`app_switch` (50,588 — but see the 65% duplication finding), `keystroke`
(38,717), `screenshot_smart` (34,580 — but see the 7.2% resolution
finding), `shortcut` (13,668), `mouse_click` (6,177). Rarest observed
non-zero types: `mouse_drag_drop` (4), `upload_failed` (5),
`mouse_double_click` (10) — **not discarded**, kept in the profile
regardless of rarity per instruction.

**0 unknown layers, 0 unknown event_type-for-layer combinations** against
DATA_SCHEMA.md's own reference table (`audit.KNOWN_EVENT_TYPES_BY_LAYER`).
The documented taxonomy is complete for what Dataset A actually contains.

## Part 9 — Payload Quality

Checked "does this event type's payload have at least one of its
schema-relevant fields populated" for the types we have a defined field
list for (`app_switch`, `keystroke`, `browser_click`, `clipboard_change`,
`screenshot_smart`) — see `audit.PAYLOAD_FIELDS_BY_TYPE` and
`full_audit_dataset_a.json` → `payload_emptiness_by_type` for exact
per-session rates. No event type showed a majority-empty payload.

Two payload-structure findings from direct inspection (not just aggregate
stats):

- **`text_input_complete.payload.final_text`** is the real content field —
  not named in DATA_SCHEMA.md's tables at all (see Part 12).
- **`clipboard_change.payload.text_content` is always `null`** in every
  sample checked (5 spot-checked directly, consistent with the
  `content_type`/`text_length` metadata being populated while the actual
  text is not) — clipboard events carry *metadata about* a copy/paste
  (length, format, `CF_UNICODETEXT` etc.) but never the copied text itself.
  This is a deliberate-looking omission (privacy-by-design), not a bug —
  but it means clipboard-based text reconstruction (Part 13) is not
  possible from this field, full stop.

## Part 10 — Screenshot Reference Audit

| | Dataset A | Dataset B |
|---|---|---|
| `screenshot_smart` events | 34,580 | 4,759 |
| Resolve to an actual file (via `resolve_screenshot`, checking both the chunk's own dir and sibling short-named dirs) | 2,489 | ~3,865 |
| **Resolution rate** | **7.2%** | **81.2%** |

Missing screenshots are **not** treated as pipeline errors —
`resolve_screenshot` returns `None` and callers treat that as "no capture
available," per DATA_SCHEMA.md's own guidance. The finding here is the
*rate*, not that missing screenshots exist at all, and specifically that
the rate is wildly different between the two datasets (see
`dataset_inventory.md`/`data_quality_scorecard.md` for why this matters for
Step 2/3 planning).

## Part 11 — Extracted Text Audit

- 4.48% of all events have non-empty `context.extracted_text.text` (7,300 /
  162,768) — matches DATA_SCHEMA's documented "~4%" almost exactly.
- Concentrated, not evenly spread: 86% of non-empty occurrences (6,288 of
  7,300) are on `app_switch` events specifically; by application, Chrome
  (5,346) and Notepad (1,390) dominate.
- Length: 1–20,000 characters, mean 1,382.5 — the long tail comes from full
  page-text captures on `app_switch` into a browser.
- 0 events had `extracted_text` present-but-empty (i.e., when the field
  exists, it always has content) — no "suspicious empty" case found.
- OCR is confirmed unnecessary for this text — it's already extracted into
  the log per DATA_SCHEMA.md, and our profiling reads it directly.

## Part 12 — `text_input_complete` Investigation

118 events total (0.07% of all events). Real content field is
`payload.final_text` (see Part 9) — our first attempt guessed wrong field
names and wrongly reported "100% missing"; see `debugging_log.md` for the
full story. Corrected: **98.3% have content (116/118)**, 1.7% missing
(2/118) — consistent with, but much less severe than, DATA_SCHEMA's
warning. Also found: 18 of the 116 populated events are password fields
(`input_context.is_password_field: true`) with the plaintext password in
`final_text`, despite a `redact_password_fields: true` capture setting —
synthetic test credentials, no real PII, but a genuine redaction-mechanism
gap worth carrying into Step 3's risk section. **Conclusion: treated as a
hint, never ground truth**, consistent with DATA_SCHEMA.md's explicit
caveat — not because of the missing-content rate (which is low), but
because of the schema's own documented warning about non-text actions
being mixed in, which we did not independently re-verify this pass.

## Part 13 — Keyboard / Clipboard Reconstruction Investigation

**Keystroke-based reconstruction: verified feasible.** Took a real
`text_input_complete` event (`final_text: "operator2nttd.co.jp"`), pulled
its `payload.related_keystrokes` event-ID list (itself an undocumented but
real linkage field), looked up each linked `keystroke` event's
`payload.character`, concatenated them in order — **exact match** against
`final_text`. This confirms keystroke-level reconstruction is not just
theoretically possible per DATA_SCHEMA's suggestion, but works end-to-end
in at least one real case.

**Clipboard-based reconstruction: not possible from `text_content`.**
Every `clipboard_change` event sampled has `payload.text_content: null` —
only metadata (`text_length`, `content_type`, `formats_available`) is
captured, never the copied text. If clipboard-derived text is ever needed,
it cannot come from this field; `gt.jsonl`'s own `clipboard_copy`/
`clipboard_paste` records do carry a `content_preview` (visible in the raw
GT stream, e.g. company names), but that's ground truth, not something
available in Dataset B.

**Verdict for Day 2**: keystroke-based reconstruction is a real, working
capability if a segmentation or automation approach ever needs actual typed
content. Clipboard content is not recoverable from the operation log at
all — only clipboard *activity* (that a copy/paste happened, and roughly
how much text) is observable.

## Part 14–15 — Ground Truth & Manifest Validation

See `ground_truth_validation.md` for the full writeup (duplicate starts,
unpaired switches, suspend/resume, overlapping intervals, manifest
cross-check).

## Part 16 — Cross-File Consistency

| Issue | File(s) | Count | Severity | Action |
|---|---|---|---|---|
| `machine_id` namespace mismatch (real hostname vs. synthetic scenario code) | `manifest.json` ↔ `gt.jsonl` | all 63 sessions | LOW (expected, but a silent-join hazard) | documented, not fixed — not a defect |
| `split_id` not recorded for an abandoned suspension | `gt.jsonl` ↔ `gt_manifest.json` | 1 confirmed instance | MEDIUM | documented; `gt.jsonl` treated as the more complete source for this field |
| `correlation.chunk_id` names the wrong chunk | `events.jsonl` (metadata) ↔ actual file location | 1 event / 162,768 | LOW (rate), but corroborated by the `ms_since_last_event` anomaly at the same point | documented, check implemented (`session_chunk_identity_checks`) |
| GT execution counts | `gt.jsonl` reconstruction ↔ `gt_manifest.json` | 0 mismatches / 2,009 executions | — | cross-check passes |

Full narrative: `cross_file_consistency.md`.

## Part 17 — Safe Normalization / Cleaning

Two transformations only, both logged, both non-mutating of the raw files:
exact-duplicate record removal (0 triggered) and chronological re-sort
(triggered per Part 6's ordering findings). Full policy and the explicit
list of what is deliberately NOT done at this layer (no fabrication, no
similarity merging, no GT-driven edits): `cleaning_policy.md`.

## Part 18 — Data Quality Scorecard

Full category-by-category table with PASS/WARNING/FAIL/BLOCKER and
evidence: `data_quality_scorecard.md`. No BLOCKER-severity item remains
open — the one that existed (manifest-crash) was fixed this pass.
