# Data Quality Scorecard — Dataset A

Real measured numbers, not a manufactured "everything's fine" summary. Full
detail behind each row lives in the correspondingly-named report in this
directory. Denominators: 63 sessions, 117 chunks, 162,768 events, 2,009 GT
executions, unless noted.

| Category | Status | Count | % | Severity | Action taken | Remaining risk |
|---|---|---|---|---|---|---|
| Schema validity (required fields present) | PASS | 0 missing | 0% | — | none needed | none observed |
| Manifest integrity | FIXED | 1 crash class found, 0 corrupt manifests in real data | — | was CRITICAL | added graceful handling + test | none — but only tested against 1 synthetic corruption case, not a fuzzed set |
| Event ID uniqueness | PASS | 0 duplicate IDs | 0% | — | none needed | none |
| Exact duplicate records | PASS | 0 groups | 0% | — | dedup implemented, unused in practice | none |
| Semantic duplicates (same session+ts+type+payload, different ID) | WARNING | 42 groups (84 events), 100% `browser_error` | 42% of all `browser_error` events | MEDIUM | reported, not auto-removed | if `browser_error` is ever used as a signal, must dedupe first |
| Sequential duplicates (adjacent, identical payload) | WARNING | 33,232 events, 98.9% `app_switch` | **65% of all `app_switch` events** | HIGH for segmentation design | reported, not auto-removed | using raw `app_switch` *count* as a signal without dedup would be badly wrong |
| Timestamp `ms`/`iso` consistency | PASS | 0 mismatches | 0% | — | none needed | none |
| UTC handling | PASS | 0 non-UTC timestamps | 0% | — | none needed | none |
| Raw chronological order (pre-sort) | WARNING | 144+ inversions/session, ~209ms avg, mostly `screenshot_smart` | most sessions affected | LOW (fully mitigated) | explicit sort in loader, tested | none — sort is enforced, not optional |
| Session/chunk identity (`session_id`, `chunk_id` match reality) | WARNING | 1 mismatch found | 1 of 162,768 events | LOW | reported via `session_chunk_identity_checks` | negligible rate, but check must stay in place |
| Layer/event-type consistency | PASS | 0 unknown layers, 0 unknown type-for-layer combos | 0% | — | reference table implemented | none in current data; check will catch future surprises |
| Payload shape (per known event type) | PASS | see `full_audit_dataset_a.json` `payload_emptiness_by_type` | low empty-payload rates observed | — | conditional-by-type validation implemented | none significant |
| Screenshot reference resolution | **CRITICAL for Dataset A, OK for Dataset B** | A: 2,489/34,580 resolved; B: ~3,865/4,759 | **A: 7.2%**, B: 81.2% | HIGH (asymmetry, not just scarcity) | documented; resolver already treats missing as expected, not an error | a screenshot-dependent Step 3 design validated only on A would badly misjudge feasibility |
| `extracted_text` availability | EXPECTED SPARSE | 7,300 / 162,768 | 4.48% | — | matches DATA_SCHEMA's own "~4%" claim | none — matches documented expectation |
| `text_input_complete` content | MOSTLY GOOD (after fixing our own bug) | 116/118 have content | 98.3% | LOW | documented; treated as hint not truth per schema | 18 events expose plaintext password field content — governance note, not a pipeline defect |
| GT duplicate `process_started` | EXPECTED-BUT-UNOBSERVED | 0 occurrences | 0% | — | handling implemented + tested regardless | schema says it *can* happen; Dataset B has no GT to check against, so the handling must stay in place defensively |
| GT unpaired `process_switched_out` | EXPECTED-BUT-UNOBSERVED | 0 occurrences | 0% | — | same as above | same as above |
| GT suspend-without-resume | **REAL, FOUND** | 1 occurrence | 1 of ~30 suspend events | MEDIUM | documented as a genuine "abandoned process" case, not an error | segmentation must allow an execution to end at a suspend with no resume ever appearing |
| GT resume-without-suspend / overlapping intervals | PASS | 0 occurrences each | 0% | — | checks implemented | none observed |
| GT ↔ GT-manifest execution counts | PASS | 0 mismatches / 2,009 executions | 0% | — | cross-check implemented | `split_id` field-level gap still exists — see `cross_file_consistency.md` |
| Cross-file `machine_id` | EXPECTED DIFFERENT NAMESPACES | n/a | n/a | — | documented | would silently break a naive join |

## Overall read

Dataset A is **structurally clean** (no missing files, no schema violations,
no corrupted records) but has **real, measurable instrumentation quirks**
concentrated in exactly two places: `app_switch` double-firing (L2) and
`browser_error` double-logging (L3), plus a screenshot-coverage gap that is
specific to *this* dataset and does not describe Dataset B. None of these
block Step 1 — they change what "count of X" means as a segmentation
feature, which is precisely why this audit needed to happen before writing
any segmentation code.
