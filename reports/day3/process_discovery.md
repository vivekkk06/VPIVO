# Process Discovery, Section 2 — Time-Ordered Series and Candidate Execution Boundaries

Continues from `dataset_b_profile.md`. Nothing here retrains, reuses, or
adapts Dataset A's fitted architecture (V1/V2/Design 2/Combined) — those
are classifiers fit against Dataset A's ground truth and have no meaning
without it, and Dataset B has none. Only the generic, dataset-agnostic
`CanonicalEvent`/`TransitionFeatures` representation is reused. New code:
`src/procmine/process_discovery/system_identity.py`,
`src/procmine/process_discovery/boundaries.py`,
`scripts/discover_executions_dataset_b.py`, with
`tests/test_system_identity.py` (13 tests) and `tests/test_boundaries.py`
(10 tests).

## Time-ordered series

Trivial by construction: `load_session_events` + `to_canonical_stream`
already sort by `timestamp_ms` (never raw file order — the profile
confirmed 14.3% of Dataset B's own raw events are out of order before
sorting, so this is required, not optional, here too). Each session's
canonical event list is the ordered work series; no session is merged
with another (per the profile's recorded assumption).

## Candidate boundary methods tested

Per instruction, several methods were tried rather than assuming one:

1. **Gap-threshold** at Dataset B's own p90/p95/p99 inter-event gap
   (1,885 / 2,744 / 5,971ms — recomputed directly from B, not reused from
   the profile report's numbers, so this script is self-contained).
2. **Application change** (`TransitionFeatures.application_changed`,
   already-existing, reused as-is).
3. **System change** — a new, Dataset-B-specific signal
   (`system_identity`): resolves which of the three named business
   systems, or which non-browser application, is active per event.
4. **Debounced system change** — same signal, but a candidate boundary is
   only kept if the new identity persists for at least `min_persist`
   consecutive events (filters transient flicker).

### A real mistake, caught by testing against data, not assumed correct

The first version of `system_identity` used `browser_domain` (host:port)
as the primary signal for which of the three systems was active, because
Dataset A's Stage 5 found port-level granularity mattered there. Running
it against real Dataset B data immediately produced a bad result: **raw
`system_change_boundaries` produced 6,839 segments with a median length of
1 event and 0ms duration** — clearly not usable — and the qualitative spot
check showed the browser tab's `active_browser_tab.url` (and therefore
`browser_domain`) flickering to null constantly even while the visible
window title still clearly named one of the three systems.

Checked directly: of ~4,700 Edge events with no resolved `browser_domain`,
the large majority (over 4,000) still carry one of the three systems'
literal names in `window_title`. **`window_title` is the more reliable
signal for Dataset B; `browser_domain` is not.** This is exactly the
opposite of what mattered most for Dataset A, and it was only found by
running the method against B's real data and looking at what came out —
not assumed to transfer, and not left as a silent bug once the numbers
looked obviously wrong. `system_identity` was corrected to check the three
known system-name substrings (literal strings observed in the data, not
invented) in `window_title` first, falling back to `browser_domain` only
for a real site that isn't one of the three (the dataset's one
`app.slack.com` case), and excluding known browser-chrome noise states
("Restore pages", "Turn off extensions in developer mode", "Untitled...")
as no-evidence rather than a distinct system.

## Method comparison (descriptive — no GT exists to score against)

| Method | Segments | Median length (events) | Median length (ms) |
|---|---:|---:|---:|
| gap p90 (1,885ms) | 2,063 | 7 | 1,161 |
| gap p95 (2,744ms) | 1,039 | 17 | 4,776 |
| gap p99 (5,971ms) | 220 | 67 | 26,283 |
| application_change | 997 | 11 | 4,178 |
| system_change (corrected, no debounce) | 1,018 | 12 | 4,500 |
| system_change, debounce ≥2 | 963 | 13 | 4,760 |
| system_change, debounce ≥3 | 923 | 14 | 5,515 |
| system_change, debounce ≥5 | 770 | 19 | 8,719 |
| system_change, debounce ≥8 | 660 | 22 | 11,079 |
| system_change, debounce ≥12 | 530 | 32 | 14,776 |

(Numbers above reflect a second, small correction: `system_change_boundaries`
originally compared each event's identity only against its immediate
neighbor, so a no-evidence event — a recording-agent window or browser
dialog — sitting between two *different* real systems was invisible to it
(both sides only ever got compared to the `None`, never to each other,
under `system_identity_changed`'s own conservative rule). Measured
directly: 20 of 20,477 events fit this "sandwiched" case. Fixed by forward-
filling each `None` with its nearest preceding real identity
(`system_identity.fill_forward`) before comparing consecutive events —
segment counts above rose slightly (e.g. 969 → 1,018 undebounced) because
those 20 real switches are now correctly detected instead of silently
merged into whichever segment came before them.)

**Gap-threshold methods are confirmed weak, as the profile predicted**: p90/p95
produce thousands of segments a fraction of a second apart (splitting
mid-keystroke), while p99 produces plausible-looking segment sizes only
because it happens to leave nearly everything unsplit (220 segments over
20,477 events is close to one segment per session) — it isn't actually
finding structure, it's just rarely firing. Gap size alone is not a usable
boundary signal for Dataset B, confirming Section 1's prediction with an
actual measurement rather than leaving it as a prediction.

**System-change (corrected) is the usable signal.** The qualitative spot
check (first 15 segments of one session, debounce ≥2) shows genuinely
coherent single-system stretches: a Word document
(`getsujitsu_teigaku_torihikisaki_ichiran`), the Financial Accounting
system, an Excel workbook (`expense_calc`), the HR system for a sustained
74-event/42-second stretch, another Word document
(`kazoku_teate_kitei` — "family allowance regulations"). This is the
first point in the Dataset-B investigation where segment content can be
read directly against real business-system names and makes sense.

## What debounce level to use — left open, not resolved here

Higher debounce values (8, 12) look progressively "cleaner" only because
they suppress more short flickers — but nothing so far actually validates
which level best matches a real business action versus real noise, since
there is no ground truth. **This is a real, honest limit of the current
evidence**, not resolved by choosing a debounce value that merely looks
nicer on paper. The right next step (Section 3) is not "pick the biggest
debounce and call it done" — it's to look at whether *consecutive* short
system-segments belong to one coherent execution (e.g. a brief detour into
Word to check a procedure document and back into the HR system is very
plausibly still one HR-system task, not two), which is a sequence-pattern
question, not a single-transition threshold question. This directly
parallels Dataset A's own finding that a single-transition decision
over-segments and a neighborhood/pattern-aware layer was needed on top of
it — except here it is being designed from scratch for Dataset B's own
evidence, per instruction, not transplanted from Design 2.

## Decision at this checkpoint

`system_change_boundaries` (or a modest debounce, ≥2–3, to remove the
most obvious one-event flicker) is the candidate signal to carry into
Section 3 as the raw segmentation this project's own reconstruction-layer
precedent would then need to be built on top of — combining and pattern-
matching consecutive system-segments into coherent executions, using the
literal system/document names as strong grounding evidence throughout.
Gap-threshold and plain application-change are both rejected as primary
signals, on the evidence above, not by assumption.

**Not yet done**: execution construction (Section 3), process/variant
discovery (Section 4), frequency/time/prioritization analysis (Sections
5–13). This report covers Section 2 only.
