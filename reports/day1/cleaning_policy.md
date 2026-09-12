# Cleaning / Normalization Policy

**Rule zero: raw files on disk are never modified.** Everything below
operates on dicts already read into memory and returns a new list plus an
explicit transformation log (`procmine.cleaning.clean_session_events`) —
never a silent mutation. This is enforced structurally: the cleaning
function takes `raw_events`, never a file path, and is covered by a test
that hashes the input list's identity/order before and after to confirm no
in-place mutation (`tests/test_cleaning.py::test_does_not_mutate_input`).

## Engineering Reasoning

The line I kept coming back to while deciding what belongs in this file
was: does the correct output follow unambiguously from the raw data
alone, or does it require a judgment call about what a "real" event is?
Sorting by timestamp and removing byte-identical duplicate records pass
that test — there's only one right answer either way. Deduplicating
`app_switch` events does not pass that test, even though the case for
doing it is strong (65% duplication measured) — deciding which of two
near-identical switches is "the real one" is a segmentation interpretation,
not a data-cleaning fact. I kept that decision out of this file on purpose
so it stays visible and testable in Step 1's code instead of disappearing
into a preprocessing step nobody would think to question.

## What we DO clean, and why each one is safe

| Transformation | Justification | Real impact measured |
|---|---|---|
| Drop exact full-record duplicates | Identity is unambiguous — a byte-identical JSON record occurring twice carries zero additional information the second time. | **0 found in Dataset A.** Implemented and tested anyway, since a future dataset (or Dataset B) could have them, and "0 found" is itself a useful, reportable number rather than an assumption. |
| Sort chronologically by `timestamp_ms` | Raw file/chunk order is not reliably chronological — see `timestamp_quality.md` (68% of raw-order inversions trace to async screenshot capture latency). | Reorders a measurable fraction of events per session; original `correlation.sequence_number`/`chunk_id` are left untouched, so which chunk/position an event came from is never lost. |

Both transformations are logged with `affected_events` count and an
explicit `information_lost: False` flag every time they run — see
`cleaning_log` in `full_audit_dataset_a.json`.

## What we explicitly do NOT do, and why

- **Do not fabricate missing values.** A `None` or absent field stays that
  way through the pipeline. Downstream code must handle "not captured,"
  never receive a synthesized substitute.
- **Do not delete suspicious records without hard evidence.** The 42
  `browser_error` semantic-duplicate pairs and the 33,232 sequential
  duplicates (mostly `app_switch`, see `full_audit_dataset_a.json`) are
  **reported, not dropped**, from the raw stream. Deduplicating a
  double-logged UI event is a defensible *segmentation-time* decision for
  Step 1 (e.g. collapse consecutive identical `app_switch` before counting
  transitions) — it is not something Day 1's cleaning layer should decide
  unilaterally, because it changes what "one operation" means and that's
  exactly the judgment call Step 1 exists to make deliberately, with
  evaluation against ground truth.
- **Do not merge events because they look similar.** Similarity-based
  merging is a segmentation-algorithm decision, not a cleaning one — merging
  at the cleaning layer would silently bake in an assumption before Step 1
  has a chance to validate it against Dataset A's ground truth.
- **Do not treat chunk boundaries as process boundaries**, ever, anywhere in
  this codebase — see `dataset_inventory.md`.
- **Do not infer process labels during cleaning.** That's the entire point
  of Step 1; doing any of it here would make Day 1 quietly prejudge Step 2's
  work.
- **Do not use ground truth to modify raw events.** `gt.jsonl`/
  `gt_manifest.json` are read-only references for *validating* a
  segmentation approach (Dataset A only) — never inputs that alter the
  event stream itself. This also keeps the Dataset A pipeline honestly
  representative of Dataset B, where no such ground truth exists at all.
- **Do not silently normalize the GT duplicate-`process_started` quirk out
  of existence.** `parse_gt_executions` skips creating a second
  `GTExecution` for a duplicate consecutive start (see
  `loaders/ground_truth.py`), but the skip is logged to
  `ValidationReport.gt_duplicate_starts` every time — 0 occurrences found in
  Dataset A, but the mechanism is real and tested
  (`test_deduplicates_consecutive_duplicate_process_started`).

## Where the line actually is

Cleaning = transformations where the *correct* output is unambiguous given
only the raw data itself (sort order, exact-duplicate removal). Anything
where "what's the right answer" depends on business-process judgment,
statistical modeling, or ground truth is Step 1/2 work and stays out of this
layer, full stop.
