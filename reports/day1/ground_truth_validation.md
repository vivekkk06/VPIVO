# Ground Truth Validation (Parts 14–15)

All checks via `procmine.loaders.ground_truth.parse_gt_executions` +
`cross_check_against_manifest`, run against all 63 Dataset A sessions
(the only dataset with ground truth — Dataset B has none, by design).

## Engineering Reasoning

I treated `gt.jsonl` and `gt_manifest.json` as two sources that ought to
agree with each other, not as one authoritative file plus a redundant
copy. That's why this validation cross-checks them instead of just parsing
whichever looked more convenient (`gt_manifest.json`'s ready-made
`executions[]` list would have been the easier path). The cross-check is
what caught the one real disagreement — an abandoned suspension that
`gt_manifest.json` doesn't record at all. If I'd trusted the manifest
alone, that finding would not exist in this report.

## What was checked

`process_started`, `process_switched_out`, `process_suspended`,
`process_resumed`, `task_started`, `clipboard_copy`/`clipboard_paste`,
`session_ended`, plus `current_process`/`process_variant` carried on every
line, `case_id`, and start/end timestamps.

## Results

| Check | Result | Classification |
|---|---|---|
| Duplicate consecutive `process_started` (documented quirk) | 0 occurrences / 2,009 executions | documented behavior, not observed — handling implemented and tested anyway |
| `process_switched_out` without a matching open process (documented quirk) | 0 occurrences | documented behavior, not observed |
| `process_resumed` without a prior `process_suspended` (same `split_id`) | 0 occurrences | not observed |
| `process_suspended` never followed by a `process_resumed` (same `split_id`, same session) | **1 occurrence** | **real, actual inconsistency** — see below |
| Overlapping process intervals (one execution starts before the previous closes) | 0 occurrences | not observed |
| Invalid/unparseable timestamps in `gt.jsonl` | 0 | — |
| Missing process labels (`process_code`/`process_name` absent on a start) | 0 | — |
| Inconsistent variants (same process, wildly inconsistent variant labeling) | none found — variants are drawn from a small consistent set per process code | — |

**Total: 2,009 executions reconstructed across 63 sessions.**

## The one real inconsistency — abandoned suspension

Session `ses_20260701-051820-CHAITANYA0BCF`: process **B**'s second
execution (`case_id: PI-101000-002`) is suspended via
`process_suspended {from: B, to: E, split_id: "M1-B-split-1"}` at
`05:33:47.067677Z`, and the session ends 3.5 minutes later (after moving to
E, then J) with no `process_resumed` for B anywhere in the remaining 133
lines of `gt.jsonl`.

**Classification: real, but not a data-integrity defect — an actually
abandoned process.** This is the recorded behavior of the simulated
operator (they never returned to B before the session ended), not a
parsing bug or a corrupted record. Confirmed by manually reading the full
tail of the session's `gt.jsonl` (reproduced in
`session_case_studies.md`, case study #2).

**Not silently "fixed."** Our `parse_gt_executions` correctly leaves this
execution's `end_ts` set to the suspend time and marks `suspended=True` —
it does not wait for or assume a resume, and does not merge it with any
later execution.

## Ground-truth manifest cross-check (`gt_manifest.json`)

`cross_check_against_manifest` compares, per process code, the number of
executions reconstructed from `gt.jsonl` against `gt_manifest.json`'s own
`executions[]` list, for every session.

**Result: 0 mismatches across all 63 sessions, 2,009 executions.** The two
GT sources agree at the count level everywhere.

**However — a field-level disagreement was found for the abandoned-suspension
case above**: `gt_manifest.json`'s corresponding execution entry
(`case_id: PI-101000-002`) records `split_id: null` and
`continues_to_next: false` — it does not surface that this execution was
suspended at all. Only `gt.jsonl`'s raw event stream shows the
`process_suspended` record with its `split_id`. **Classification: real
inconsistency between the two GT files, not ambiguous** — verified by
directly reading both files for the same execution (`case_id`) and
comparing field-by-field, reproduced in `cross_file_consistency.md`.

**Practical implication**: `gt_manifest.json` alone is not a complete
substitute for `gt.jsonl` — an execution that was suspended and never
resumed is invisible in the manifest's `split_id`/`continues_to_next`
fields. Our loaders parse both and prefer `gt_manifest.json` as the
canonical execution list (it has `apps` info the raw stream lacks) while
keeping the `gt.jsonl` reconstruction as the cross-check that actually
caught this case.

## Also verified: `split_id` values are per-scenario template labels, not global keys

`grep -rl "M1-B-split-1" dataset_a/*/gt.jsonl` returns **25 different
sessions** — the same literal `split_id` string is reused every time that
scenario template runs. This is not a bug, but it means `split_id` matching
must be scoped to a single session; treating it as a globally unique
cross-session identifier would incorrectly link unrelated suspend/resume
pairs from different sessions. Verified directly via `grep`, not assumed.

## Cross-chunk executions

The large majority of the 2,009 executions have
`continues_from_prev`/`continues_to_next: true` in `gt_manifest.json` —
cross-chunk execution is the norm, not an edge case, in Dataset A.
