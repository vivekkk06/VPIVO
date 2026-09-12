# Day 1 Summary — Final Evidence Package

This is the top-level entry point for Day 1. It links to the detailed
reports rather than repeating their evidence; every number below was
produced by a script in this repo and can be reproduced with the commands
in `day1_readiness.md`.

## Engineering Reasoning

I wanted one document that a reader (or a future me) could open first and
get an accurate picture without having to cross every detailed report
myself. My reasoning was that a summary written after the detailed work is
more trustworthy than one written as a plan up front, so this file was
built last, from what the other reports actually found — not the other
way around. The decision to separate "executive summary" from "detailed
evidence" mattered because it let me be honest about severity (calling out
the app-switch duplication and screenshot asymmetry as the two most
consequential findings) without burying that judgment in twenty pages of
supporting detail.

---

## Part 1 — Repository Audit vs. Assignment Requirements

| Area | Status | Note |
|---|---|---|
| Directory structure (`src/`, `scripts/`, `tests/`, `reports/day1/`) | PASS | matches a normal Python project layout |
| Source modules (`models`, `paths`, `loaders/`, `validation`, `profiling`, `viz`, `audit`, `cleaning`) | PASS | each has a single clear responsibility |
| Scripts (`profile_dataset.py`, `parse_ground_truth.py`, `validate_dataset.py`, `audit_dataset.py`, `case_studies.py`) | PASS | all run end-to-end against real data, see `day1_readiness.md` |
| Tests (`tests/`) | PASS | 36/36 passing, see Part 25 |
| Config/dependency files (`pyproject.toml`, `requirements.txt`, `.gitignore`) | PASS | minimal deps (matplotlib, pytest); raw data gitignored |
| Git status | **BLOCKER-turned-note**: nothing committed yet | intentional — commits are being written by the repo owner in their own words, not by this process; see final chat message for the plan |
| Missing expected components | one real gap closed this pass (see below) | a manifest-corruption crash bug existed and has been fixed and tested |

**PASS**: package structure, multi-chunk session merge (verified against
real event counts), screenshot path resolution (handles two real on-disk
layouts), GT reconstruction (0 count-level disagreement with
`gt_manifest.json` across 2,009 executions), test coverage of the loaders.

**PARTIAL (existed but needed hardening, now addressed)**: manifest error
handling (crashed → fixed), missing-value/duplicate/timestamp audits (didn't
exist → built in `audit.py`), cross-file consistency (not checked → now
checked, one real gap found).

**FAIL → now fixed**: `load_session_events`/`load_chunk_manifest`/
`load_gt_manifest` crashed on a single corrupted `manifest.json` instead of
degrading gracefully. See `debugging_log.md` for the full story.

**No open BLOCKER remains** — see `day1_readiness.md` for the full 26-item
gate.

---

## Part 2 — Dataset Structure Verification

| Item | Expected (per README/DATA_SCHEMA) | Actual (measured) | Status |
|---|---|---|---|
| Dataset A sessions | 63 | 63 | PASS |
| Dataset A events | "~162,000" | 162,768 | PASS |
| Dataset A ground truth | provided, all sessions | 63/63 sessions have `gt.jsonl` + `gt_manifest.json` | PASS |
| Dataset B sessions | 15 | 15 | PASS |
| Dataset B events | "~20,000" | 20,477 | PASS |
| Dataset B ground truth | none (by design) | 0 files found | PASS (matches spec) |
| Event/manifest files per chunk | 1 each | 117/117 and 117/117 (A); 20/20 and 20/20 (B) | PASS, 0 missing |
| Screenshot directories | present where captures occurred | 50 found for 117 chunks in A (uneven — see below), 20/20 in B | PASS structurally, see coverage caveat |
| Empty files | 0 expected | 0 found | PASS |

Full detail: `dataset_inventory.md`.

---

## A. Executive Summary

- Dataset A (162,768 events, 63 sessions) and Dataset B (20,477 events, 15
  sessions) are both structurally complete — no missing or empty files.
- **65% of all `app_switch` events in Dataset A are exact, back-to-back
  duplicates** (identical payload, 36-97ms apart) — a real instrumentation
  bug, not user behavior. Confirmed absent in the sampled Dataset B sessions
  checked.
- **Screenshot coverage is dataset-specific, not a general property**: 7.2%
  resolution in Dataset A vs. 81.2% in Dataset B. A conclusion drawn only
  from A would be wrong for B.
- **One real GT cross-file inconsistency**: `gt_manifest.json`'s `split_id`
  field doesn't record a suspension that `gt.jsonl`'s raw stream shows
  clearly — the ready-made summary under-reports abandoned suspensions.
- **One real chunk-boundary data-integrity glitch**: an event's own
  `correlation.chunk_id` and `ms_since_last_event` are both wrong at the
  same chunk transition in the same session — two independent checks
  corroborating the same underlying defect.
- **Text reconstruction from keystrokes is verified exact-match** in a real
  test case; clipboard content (`text_content`) is **always null** in every
  sample checked — clipboard-based reconstruction is not possible from that
  field.
- A real crash bug (corrupted `manifest.json` takes down the whole session
  load) was found, fixed, and tested during this pass.
- A real bug in our own first-pass analysis (`text_input_complete` profiled
  against a made-up field name, "final_text" is the actual field) was
  self-caught and corrected before being reported as fact.
- No blockers remain; Day 2 can start.

## B. Dataset Facts (verified only)

See Part 2 table above and `dataset_inventory.md` / `dataset_profile.md` for
the full breakdown (event types, layers, applications, durations).

## C. Data Quality Findings

See `data_quality_report.md` for the complete PART 3-18 audit. Headline
issues: `app_switch` duplication (65%), `browser_error` double-logging (42%
of occurrences), screenshot coverage asymmetry, 443 events (0.27%) with an
implausible negative `ms_since_last_event`.

## D. Ground Truth Findings

See `ground_truth_validation.md`. 2,009 executions reconstructed, 0
count-level mismatch against `gt_manifest.json`; one real abandoned
suspension (process suspended, never resumed in-session); one real
`split_id` field disagreement between `gt.jsonl` and `gt_manifest.json`.

## E. Important Observations

Chunk boundaries are confirmed (not just documented) to not align with
process boundaries — the large majority of GT executions span chunks.
Dataset A has no "simple" session — minimum 24 GT executions in any single
session. See `session_case_studies.md` for five sessions inspected in
detail with timeline figures.

## F. Candidate Segmentation Signals

See `segmentation_signals.md`. Three signals quantitatively evaluated
against 1,689 real GT boundaries (deduplicated app-switch: 68.1% alignment;
extracted-text presence: 64.2%; time-gap size: ~7-10x larger at boundaries
but noisy); three flagged as hypotheses for Day 2, not claimed as validated
(window title, browser URL, clipboard-linked case IDs).

## G. Problems Encountered

See `debugging_log.md` for the full Problem/Diagnosis/Root
cause/Fix/Verification/Lesson writeups: the manifest-crash bug, the
`text_input_complete` field-name mistake, and the `ms_since_last_event`
negative-value discovery.

## H. AI Assistance

See `ai_usage.md`.

## I. My Engineering Decisions

See Part 24 in `ai_usage.md` (kept together with the AI-usage table so the
two are easy to compare side by side).

## J. Remaining Risks

- Window title / browser URL / clipboard-linked signals are unevaluated —
  Day 2's first task, not a hidden gap.
- The manifest-crash fix was verified against one synthetic corruption
  case, not a fuzzed range.
- No automated end-to-end integration test runs the CLI scripts against a
  real dataset (done manually and verified this session, not codified).
- Dataset B has zero ground truth — every GT-based finding in this package
  is Dataset-A-only by necessity; only the mechanical checks (schema,
  timestamps, duplication) were run against B directly, and at least one of
  them (app-switch duplication) does **not** transfer.

## K. Day 2 Recommendations

1. Quantify window-title/browser-URL/clipboard-case-id alignment against GT
   boundaries using the same ±2s method already built.
2. Build the `app_switch` deduplication step as a named preprocessing
   function before any feature uses raw app-switch counts.
3. Design Step 1 as a combined-feature scorer, not a single-signal rule.
4. Re-run `audit_dataset.py`'s mechanical checks against Dataset B before
   trusting any Dataset-A-derived assumption there.

## L. Day 1 Readiness

**PASS** — see `day1_readiness.md` for the full 26-item gate.
**READY FOR DAY 2: YES.**
