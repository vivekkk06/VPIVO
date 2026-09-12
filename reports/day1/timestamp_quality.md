# Timestamp Quality

All checks via `procmine.audit.timestamp_quality`, run against every session
in Dataset A (162,768 events). Full per-session numbers in
`full_audit_dataset_a.json` under `sessions[].timestamp_quality`.

## `timestamp_ms` vs `timestamp_iso` consistency

Checked that `timestamp_iso` parses as UTC (`Z` suffix) and that converting
it to epoch-ms lands within 1 second of `timestamp_ms`.

- **0 mismatches found** across all 162,768 events. The two fields are
  redundant encodings of the same instant and agree everywhere checked.
- **0 non-UTC timestamps** — every `timestamp_iso` ends in `Z` as
  DATA_SCHEMA.md states. We keep everything in UTC internally
  (`models.py::_parse_iso` normalizes to `timezone.utc`); no local-time
  conversion happens anywhere in the pipeline.

## Chronological ordering (raw, pre-sort)

This is the check that matters most in practice: what does file order look
like *before* our loader re-sorts by `timestamp_ms`?

- **Every single session** (63/63) has at least one negative gap in the raw
  concatenation order.
- 144 negative-gap pairs in just the first session inspected in detail;
  aggregated pattern across all sessions: **68% of these near-simultaneous
  inversions involve a `screenshot_smart` event** landing 20ms–2.5s before or
  after the event that triggered it (mean delta ~209ms). `manifest.json`
  shows `capture_latency_ms` in the 700ms+ range for screenshots, which is
  consistent with an async capture pipeline that doesn't always flush to the
  log in strict wall-clock order relative to the synchronous input-event
  pipeline.
- **Conclusion**: raw file order is not a safe substitute for sorting by
  `timestamp_ms`. Our loader always sorts explicitly — this finding is the
  reason that's not optional.

## Gap-size distribution

Bucketed inter-event gaps (`timestamp_ms[i] - timestamp_ms[i-1]`) across a
session. Full histogram per session in the JSON; the shape is consistent
across sessions: heavily weighted toward `<100ms` and `100ms-1s` (continuous
UI interaction), with a long tail of `10s-60s` and `>60s` gaps corresponding
to genuine pauses between activities. This gap signal is one of the
candidates evaluated in `segmentation_signal_analysis.md`.

## Negative/zero gaps after sorting

By construction, a stable sort by `timestamp_ms` cannot produce negative
gaps in the final output. Zero-gap (identical `timestamp_ms`) events do
occur — e.g. a `browser_click` and the `mouse_click` it triggers, or the
duplicate `browser_error` pairs described in the duplicate-detection
findings, which are frequently logged at the *identical* millisecond.

## Session start/end consistency

`gt.jsonl`'s `session_ended.duration_seconds` was spot-checked against
`(last_event_ts - first_event_ts)` for the same session and matched within
normal event-boundary rounding (session end is logged slightly after the
last operational event, which is expected — the `session_ended` marker
itself is the final line).
