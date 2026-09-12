# Day 1 — Data Foundation & Reconnaissance

This report synthesizes the detailed findings in this directory. Each
section links to the report that has the full evidence — this document is
the summary, not a duplicate.

## Engineering Reasoning

This report exists because a pile of individually-correct findings isn't
the same thing as a coherent picture of whether the foundation is ready
for Step 1. I structured it around the 22 sections that mirror how the
work actually proceeded (inventory → validation → quality → GT → profiling
→ signals → limitations → recommendations) rather than an arbitrary order,
because I wanted a reader to be able to follow the same reasoning path
that produced the findings, not just see a list of them. Section 20
("Limitations") mattered enough to me to keep as its own section rather
than fold into a footnote — I didn't want the strength of the measured
findings to imply more confidence in the unmeasured ones than was earned.

## 1. Objective

Build a trustworthy data-foundation layer (discovery → loading → validation
→ quality audit → cleaning policy → GT parsing → profiling → exploratory
analysis) for the operation logs described in `README.md`/`DATA_SCHEMA.md`,
**before** writing any segmentation logic. Two passes today: an initial
build (loaders, profiling, GT parsing, tests), then a hardening/audit pass
that stress-tested it against real data and fixed what broke.

## 2. Dataset Inventory

63 sessions / 117 chunks / 162,768 events (Dataset A, has ground truth);
15 sessions / 20 chunks / 20,477 events (Dataset B, no ground truth,
different departments/apps per README). No missing or empty files in either
dataset. Full detail: `dataset_inventory.md`.

## 3. Data Schema Understanding

Confirmed against real files, not just the docs: chunk ≠ process boundary
(explicit in DATA_SCHEMA.md, confirmed by the majority of GT executions
spanning chunks); `text_input_complete`'s actual content field is
`payload.final_text`, which DATA_SCHEMA.md doesn't name; screenshot folder
layout is inconsistent on disk (two different real layouts observed).

## 4. Data Quality Audit

See `data_quality_scorecard.md` for the full category-by-category table.
Headline: structurally clean (no missing files, no schema violations), but
real instrumentation-level duplication in `app_switch` (65%) and
`browser_error` (42% of occurrences), plus a severe, dataset-specific
screenshot coverage gap (7.2% in A vs. 81.2% in B).

## 5. Missing Values

Distinguished missing/null/empty per field (`full_audit_dataset_a.json` →
`missingness`). `extracted_text` at 4.48% matches DATA_SCHEMA's documented
"~4%" — an expected sparsity, not a defect. No suspicious missingness found
on required fields (0% missing across `event_id`, `session_id`,
`timestamp_ms`, `timestamp_iso`, `layer`, `event_type`).

## 6. Duplicate Analysis

Exact duplicates: 0. Semantic duplicates (same session+timestamp+type+
payload, different `event_id`): 42 groups, 100% `browser_error`. Sequential
(adjacent, identical payload) duplicates: 33,232, of which 32,876 (98.9%)
are `app_switch` — **65% of every `app_switch` event in Dataset A is an
exact back-to-back repeat**, firing 36–97ms apart. GT-specific: the
documented duplicate-`process_started` and unpaired-`process_switched_out`
quirks were checked and found 0 times in Dataset A (handling is
implemented and tested regardless, since it's an explicit "can happen"
warning in the schema and Dataset B has no GT to verify against). Full
detail: `data_quality_scorecard.md`.

## 7. Timestamp Validation

`timestamp_ms`/`timestamp_iso` agree everywhere (0 mismatches); all UTC as
documented. Raw (pre-sort) file order has real inversions in every session
— 68% of them traced specifically to `screenshot_smart` events lagging
their trigger by up to 2.5s (async capture latency). Confirms explicit
sorting is required, not optional. Full detail: `timestamp_quality.md`.

## 8. Session/Chunk Validation

All sessions/chunks discoverable; multi-chunk merge verified correct
(matches README's ~162,000-event estimate exactly at 162,768). One
`correlation.chunk_id` inconsistency found (1 event out of 162,768) —
likely a chunk-transition flush artifact. Full detail:
`cross_file_consistency.md`, case study #3 in `session_case_studies.md`.

## 9. Event/Layers Validation

0 unknown layers, 0 unknown event_type-for-layer combinations against
DATA_SCHEMA.md's own reference table — the schema's documented event
taxonomy is complete for what's actually in Dataset A.

## 10. Screenshot Validation

**The single most consequential finding this pass.** 7.2% of Dataset A's
34,580 `screenshot_smart` events resolve to an actual JPEG on disk; Dataset
B is at 81.2% (4,759 events, ~3,865 resolved). A screenshot-dependent
design validated only on A would wrongly conclude the signal is
unavailable — it's actually mostly available in B, the dataset that's
actually scored. Missing files are treated as expected/acceptable per
DATA_SCHEMA.md's own guidance, never as pipeline errors. Full detail:
`dataset_inventory.md`, `data_quality_scorecard.md`.

## 11. Text/Input Quality

`extracted_text`: 4.48% overall, but 64.2% of GT process boundaries have an
extracted-text-bearing event within ±2s — far more concentrated near
transitions than the base rate suggests (`segmentation_signal_analysis.md`).
`text_input_complete`: our first profiling attempt used the wrong field
name and wrongly concluded "100% missing" — corrected after inspecting a
real event; actual content field is `payload.final_text`, actual missing
rate is 1.7% (2/118). Separately found: 18 of those events expose plaintext
password-field content despite a `redact_password_fields: true` capture
setting — a governance note for later, not a pipeline defect (synthetic
test credentials, not real PII). Full detail: `text_input_quality.md`.

## 12. Ground Truth Validation

2,009 executions reconstructed from `gt.jsonl` across 63 sessions; 0
count-level disagreements against `gt_manifest.json`'s own summary. Deeper
checks added this pass (resume-without-suspend, suspend-without-resume,
overlapping intervals) found exactly one real case: a process suspended and
never resumed within its session (`ses_20260701-051820-CHAITANYA0BCF`) —
documented as a genuine "abandoned process" pattern Step 1 must tolerate.
Full detail: `session_case_studies.md` (case study #2),
`data_quality_scorecard.md`.

## 13. Cross-file Consistency

`manifest.json.machine_id` (real hostname) and `gt.jsonl`'s `machine_id`
(synthetic scenario code) are intentionally different namespaces — would
silently break a naive join. More significantly: `gt_manifest.json`'s
`split_id` field is `null` for the one abandoned-suspension execution even
though `gt.jsonl`'s raw stream shows it was suspended with a real
`split_id` — the ready-made summary under-reports splits that never got a
matching resume. Also confirmed `split_id` values (e.g. `M1-B-split-1`) are
reused *template labels* across 25+ different sessions, not globally unique
keys — must scope matching to within one session. Full detail:
`cross_file_consistency.md`.

## 14. Cleaning and Normalization Policy

Two safe, logged, non-mutating transformations: exact-duplicate removal (0
triggered in real data) and chronological re-sort (triggered per the
timestamp-order findings above). Explicitly does NOT dedupe the
instrumentation-level `app_switch`/`browser_error` duplicates, delete
suspicious records, merge similar events, or use GT to alter raw events —
those are segmentation-time decisions, not cleaning-time ones. Full
rationale: `cleaning_policy.md`.

## 15. Dataset Profiling

`profile_dataset_a.json` / `profile_dataset_b.json` (event/layer/type
counts, top applications, session durations) plus `full_audit_dataset_a.json`
/ `full_audit_dataset_b.json` (everything from this hardening pass, per
session). Runtime: dataset-wide audit processes 162,768 events in ~24s
(~6,750 events/sec) without loading any screenshot binaries into memory.

## 16. Exploratory Findings

See `data_quality_scorecard.md` for the consolidated view; the two standout,
non-obvious findings are the `app_switch` 65% duplication rate and the
7.2%-vs-81.2% screenshot resolution asymmetry between datasets — both
directly shape what Step 1/Step 3 can safely assume.

## 17. Representative Session Timelines

Five sessions, chosen by real `gt_manifest.json` properties (not
arbitrary): a typical session with a clean suspend/resume, the one
abandoned-suspension anomaly, the most complex session (which also has the
one real chunk-id identity glitch), the least complex session in the entire
dataset (24 executions — there is no "simple" session in Dataset A), and
the highest-noise session. Full writeup + figures:
`session_case_studies.md`, `figures/case_study_*.png`.

## 18. Potential Segmentation Signals

Ranked by measured (not assumed) boundary alignment against 1,689 real GT
transitions: extracted-text presence (64.2% alignment, but correlated with
app-switch), deduplicated app-switch (68.1% alignment, 31.9% miss rate on
same-app transitions), time-gap size (~7-10x larger at boundaries, but
noisy/no clean threshold). Window titles, browser URLs, and clipboard
events are promising but not yet quantitatively evaluated — explicit Day 2
tasks. Full detail: `segmentation_signal_analysis.md`.

## 19. Failure Modes

Twelve concrete, evidence-backed failure modes covering duplication
artifacts, repeated/variant processes, abandoned suspensions, same-app
transitions, and the screenshot asymmetry. Full detail: `failure_modes.md`.

## 20. Limitations

- Window title, browser URL/DOM, clipboard, and activity-density signals
  are hypothesized but **not yet quantitatively evaluated** against GT
  boundaries — flagged, not silently assumed to work.
- The "noisy session" qualitative observation (case study #5) was not
  formally quantified against `noise_rate` across all 63 sessions.
- Screenshot content itself (actually opening the 2,489 available JPEGs)
  was not inspected — only reference-resolution was checked, not image
  content/quality.
- The manifest-crash fix was verified against one synthetic corruption
  case, not a fuzzed range of corruption types.
- Dataset B has zero ground truth, so nothing in this report about "what's
  true" transfers to B — only the mechanical checks (schema validity,
  timestamp quality, duplication) were run against B directly; the GT-based
  findings are Dataset-A-only by necessity.

## 21. Day 2 Recommendations

1. Quantitatively evaluate window title, browser URL, and clipboard-event
   alignment against GT boundaries using the same ±2s methodology already
   built for app-switch/extracted-text (reuse
   `segmentation_signal_analysis.md`'s method).
2. Design the Step 1 segmentation approach as a combined-feature scorer
   (gap size + deduplicated app-switch + extracted-text presence as the
   starting set), not a single-signal rule.
3. Build the `app_switch` deduplication step as a named, reusable
   preprocessing function before any feature built on it — this is not
   optional given the 65% duplication rate.
4. Validate whatever approach is built against Dataset A's GT, then run it
   unchanged against Dataset B and sanity-check the output distribution
   (process count, execution frequency) rather than assuming transfer.
5. Re-run the audit script's dataset-level checks (`audit_dataset.py`)
   against Dataset B specifically before trusting any Dataset-A-derived
   assumption there — the app-switch duplication rate, for one, does
   **not** transfer (0% in the Dataset B sample checked vs. 65% in A).

## 22. Completion Checklist

See `day1_completion_checklist.md`.
