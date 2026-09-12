# Audit of the Existing Day 1 Foundation

Before writing anything new, this is a fresh audit of the scaffolding built
earlier today (`src/procmine/*`, `scripts/*`, `tests/*`, `reports/day1/*`,
`work_log.md`) — not assumed correct just because it exists and passed tests
at the time.

## What already works

- **Package structure** (`src/procmine/{models,paths,validation,profiling,viz}.py`
  + `loaders/`) is sound: clear separation between path discovery, raw
  loading, validation, and derived analysis. Kept as-is.
- **Multi-chunk session merge** (`loaders/events.py::load_session_events`)
  correctly merges, sorts, and preserves original `sequence_number`/`chunk_id`.
  Verified against real data: 162,768 events for dataset_a matches the
  README's stated "~162,000" almost exactly.
- **Screenshot path resolution** (`paths.py::resolve_screenshot`) correctly
  handles the two on-disk layouts observed in the real data (screenshots
  colocated with `events.jsonl`, vs. a separate short-named sibling
  directory). Confirmed by both synthetic tests and a real-data scan.
- **GT execution reconstruction** (`loaders/ground_truth.py`) correctly
  handles the documented quirks (dedup consecutive `process_started`,
  tolerate unpaired `process_switched_out`) and cross-checks against
  `gt_manifest.json`. Cross-check found 0 count mismatches across all 63
  Dataset A sessions — the two GT sources agree at the count level.
- **17 original unit tests** all passed and were run against synthetic
  fixtures (never against the real 2.8GB dataset), which is the right call
  for test speed.

## What was incomplete (and has now been built, see rest of this audit pass)

- No duplicate detection beyond `event_id` uniqueness (no exact/semantic/
  sequential duplicate checks).
- No systematic missing-value audit with missing/null/empty distinguished
  per field.
- No timestamp-quality checks beyond an ordering check (no `timestamp_ms`
  vs. `timestamp_iso` cross-validation, no UTC-format check, no gap-size
  distribution).
- No event_type/layer consistency check against DATA_SCHEMA.md's own
  reference table.
- No payload-shape validation per event type.
- No aggregate screenshot *resolution rate* — the resolver worked, but
  nobody had measured what fraction of `screenshot_smart` events actually
  resolve to a file across the full dataset.
- No `extracted_text` or `text_input_complete` content-quality profiling.
- No session/chunk *identity* cross-checks (does `event.session_id` match
  the directory; does `correlation.chunk_id` match the file it was read
  from).
- No cross-file consistency checks between `manifest.json`, `gt.jsonl`, and
  `gt_manifest.json`.
- No explicit, auditable cleaning/normalization layer — sorting happened
  implicitly inside the loader with no log of what changed.
- No case-study/timeline inspection of real sessions.
- No evidence-based segmentation-signal writeup.

None of this means the original code was wrong — it means Day 1 stopped at
"loaders that work," which was the stated scope at the time. This pass
extends it to "loaders we've actually stress-tested."

## What was incorrect — a real bug found and fixed

**A single corrupted `manifest.json` crashed the entire session/dataset
load.** `load_session_events`, `load_chunk_manifest`, and
`load_gt_manifest` all called `json.load()` on manifest files with no
exception handling, while `_read_jsonl` for `events.jsonl` already handled
malformed lines gracefully. Reproduced directly:

```
CRASHED: JSONDecodeError Expecting property name enclosed in double quotes: line 1 column 2 (char 1)
```

**Fixed**: manifest reads now go through `_read_manifest_raw`, which catches
`JSONDecodeError`/`OSError` and records the failure in
`ValidationReport.malformed_manifest_files` instead of raising. Verified the
same corrupted-manifest scenario no longer crashes (see
`tests/test_robustness.py::test_corrupted_manifest_does_not_crash_session_load`).
`profile_dataset()` was also hardened so one session raising *any* unexpected
exception doesn't kill the whole dataset batch (`n_sessions_failed`/
`session_errors` now reported).

A second, smaller issue: `text_input_complete_profile` initially guessed the
wrong payload field name for input content (`text`/`content`/`value`),
which would have silently reported "100% missing content" — wrong, not a
real finding. Caught by inspecting a real raw event
(`payload.final_text` is the actual field, which DATA_SCHEMA.md doesn't name
explicitly) before trusting the number. Fixed; see
`text_input_quality.md` for the corrected, real figures.

## What should NOT be changed

- The core `Event`/`ChunkManifest`/`GTExecution` dataclasses and their
  `.raw` escape hatch — this is the right level of typing for Day 1.
- The decision not to commit raw data to git.
- `load_session_events` as the primary API surface for downstream (Step 1)
  code — chunk-level loading stays a secondary, validation-only path.

## Test failures / runtime failures encountered during this audit

- 1 real crash reproduced and fixed (corrupted manifest, above).
- 0 test failures in the original 17 tests — they were correct, just
  covering a narrower surface than this pass required. Test count is now
  36 (see `Testing` section of the final report).

## Missing data-quality checks identified

See the rest of `reports/day1/` for full detail; net-new checks added this
pass: exact/semantic/sequential duplicate detection, per-field missingness
with missing/null/empty distinguished, timestamp `ms`-vs-`iso` consistency
and gap-size distribution, event_type/layer consistency against
DATA_SCHEMA.md's table, payload-emptiness-by-type, screenshot resolution
rate (aggregate, not just per-file), extracted_text and
text_input_complete content profiling, session/chunk identity checks,
GT suspend-without-resume / resume-without-suspend / overlapping-interval
checks, and cross-file consistency between all four file types.
