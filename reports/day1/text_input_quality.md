# `text_input_complete` Quality

DATA_SCHEMA.md's caveat: *"some entries are missing their content, and some
events that are not actually text input ... are mixed in. If you need text
input, reconstruct it from `keystroke` or `clipboard_change`."*

## First attempt was wrong — worth documenting why

The first pass at profiling this event type guessed the content field was
named `text`, `content`, or `value` in `payload` — none of DATA_SCHEMA.md's
tables actually name it. That guess produced **"100% of events missing
content"**, which looked like a dramatic confirmation of the schema's
warning but was actually just a wrong field name. Reading a real raw event
(`dataset_a/.../events.jsonl`) showed the actual field is
**`payload.final_text`**, alongside `payload.keystroke_count`,
`payload.duration_ms`, `payload.corrections_count`, and
`payload.input_context.is_password_field`. Fixed and re-measured:

## Corrected numbers (Dataset A, 118 `text_input_complete` events total)

| | Count | % |
|---|---|---|
| Has non-empty `final_text` | 116 | 98.3% |
| Missing/empty `final_text` | 2 | 1.7% |

So in this dataset the "missing content" defect is real but rare (2 of 118),
not the dominant failure mode. This event type is still vanishingly small
overall — 118 of 162,768 events (0.07%) — so it was never going to be a
primary signal regardless.

## A separate, more important finding: password fields are not redacted

Of the 116 events with content, **18 have `input_context.is_password_field:
true` and `final_text` populated with the plaintext value typed** (e.g. a
test credential like `pr0cm1ne3@026`). The chunk manifest's
`capture_settings_snapshot.redact_password_fields` field is `true` for these
sessions — the redaction flag is set, but `text_input_complete.final_text`
does not appear to honor it.

This is synthetic/test data (fake `.co.jp` test SSO credentials from a
scripted scenario), so there's no real PII exposure here. But it's a
concrete, evidence-backed **governance risk to carry into the Step 3 report**:
if this same agent/pipeline were pointed at real production logs, password
field content would land in the log in cleartext despite a redaction
setting that claims otherwise. Worth a line in Step 3's risk section
regardless of whether Step 3's chosen automation touches this event type
directly.

## Handling policy for Day 2+

- `text_input_complete` is treated as a **hint, never a source of truth** for
  segmentation or reconstruction — consistent with DATA_SCHEMA.md's guidance.
- Not deleted or filtered out anywhere in the pipeline — both the 2
  content-missing events and the 18 plaintext-password events are preserved
  as-is; this report is the record of the concern, not a code-level redaction
  (redacting after the fact wouldn't undo the exposure and isn't this
  project's data to alter).
- When text content is actually needed by later steps, reconstruct from
  `keystroke` + `clipboard_change` rather than trusting `final_text` alone,
  per the schema's own guidance — `final_text` can be used as a
  cross-check, not a primary source.
