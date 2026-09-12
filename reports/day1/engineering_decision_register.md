# Engineering Decision Register

Each decision follows: Decision → What I was trying to protect → Why it
mattered → What I asked the assistant to investigate/build → What evidence
came back → What I questioned → What was verified → My final decision →
Why → Consequence → Day 2 impact.

---

## 1. Session, not chunk, as the analysis unit

**What I was trying to protect**: correct process-execution boundaries.
**Why it mattered**: getting this wrong would corrupt every downstream
count and every GT comparison. **What I asked to be investigated/built**:
session-level loading that merges all chunks, verified against real GT
cross-chunk behavior rather than assumed. **Evidence that came back**:
162,768 events for Dataset A (matching README's ~162,000); majority of
2,009 GT executions span multiple chunks. **What I questioned**: whether
"most sessions are multi-chunk" was actually true or just assumed from the
docs. **What was verified**: counted directly — 53 of 63 sessions are
multi-chunk, 10 are single-chunk. **Final decision**: `load_session_events`
is the only loading entry point downstream code uses; chunk-level loading
stays a secondary, validation-only path. **Why**: the schema's own
framing plus the measured cross-chunk rate made single-chunk processing
indefensible. **Consequence**: correct event/execution counts throughout
the project. **Day 2 impact**: Step 1 must never operate on a single
chunk in isolation.

## 2. Raw data immutability

**What I was trying to protect**: the ability to trust every reported
number back to an unedited source file. **Why it mattered**: if cleaning
and raw data become tangled, no finding can be independently re-verified
later. **What I asked to be built**: a cleaning function that structurally
cannot accept a file path, only in-memory data. **Evidence**: `cleaning.py`
takes `raw_events: list[dict]`, never a `Path`; a test hashes the input
list before/after to confirm no mutation. **What I questioned**: whether
"we don't modify raw data" was actually enforced or just a stated
intention. **What was verified**: `test_does_not_mutate_input` passes;
`.gitignore` excludes the raw dataset directories entirely from version
control. **Final decision**: immutability is structural, not a
convention to remember. **Why**: a convention can be violated by a future
change without anyone noticing; a type signature can't. **Consequence**:
every number in every report traces back to the original files.
**Day 2 impact**: the same structural rule applies to any Dataset B
preprocessing.

## 3. Conservative cleaning scope

**What I was trying to protect**: the ability for Step 1 to make its own
segmentation-relevant judgment calls, unprejudiced by earlier layers.
**Why it mattered**: cleaning that quietly decides "what counts as one
event" is really a segmentation decision wearing a cleaning-layer
disguise. **What I asked to be investigated**: which transformations are
actually unambiguous from raw data alone, versus which require
interpretation. **Evidence**: only two transformations passed that test —
exact-duplicate removal (0 triggered) and chronological sort.
**What I questioned**: whether deduplicating `app_switch` belonged in
this layer, given how clean a fix it would have been. **What was
verified**: `cleaning_policy.md`'s explicit scope boundary holds — no
event-count-altering decision happens in `cleaning.py`. **Final decision**:
keep the transformation list short and justified; defer app-switch/
browser-error dedup to segmentation. **Why**: making that call here would
hide it from the validation Step 1 is supposed to perform against ground
truth. **Consequence**: 0 raw-stream deletions; the dedup decision stays
visible. **Day 2 impact**: Step 1's code must implement and justify the
dedup explicitly.

## 4. `app_switch` duplicates reported, not deleted

**What I was trying to protect**: the reversibility and visibility of a
segmentation-relevant assumption. **Why it mattered**: 65% of all 50,588
`app_switch` events turned out to be exact duplicates — a number large
enough that how it's handled would materially change any app-switch-based
feature. **What I asked to be investigated**: whether this was a real
data-quality problem or an artifact of the analysis itself. **Evidence
that came back**: identical payload, 36-97ms apart, consistently across
sessions. **What I questioned**: 65% seemed too extreme to accept without
a concrete example — I required the type breakdown and a real payload
comparison before treating it as fact. **What was verified**: direct
inspection of two duplicate `app_switch` records confirmed identical
`new_app`/`previous_app` payloads at near-identical timestamps.
**Final decision**: report the finding, do not delete the events from the
raw or cleaned stream; move the deduplication decision to the
segmentation/feature layer. **Why**: preserves reversibility — if a future
analysis needs the raw (undeduplicated) signal for some other purpose, it's
still there; the assumption about what counts as "one switch" is explicit
and testable rather than silently baked in. **Consequence**: any current
profiling number that counts raw `app_switch` events is known and labeled
as inflated by ~65%. **Day 2 impact**: build the dedup as a named, tested
preprocessing function before any feature uses app-switch counts.

## 5. `browser_error` duplicates reported, not deleted

**What I was trying to protect**: the same principle as #4, applied
consistently even to a lower-priority event type. **Why it mattered**:
consistency in how duplication findings are handled matters more than the
specific event type's current importance. **What I asked to be
investigated**: whether the same class of instrumentation bug appeared
elsewhere in the L3 event stream. **Evidence**: 42 of ~100 distinct
`browser_error` occurrences logged twice, identical payload and
millisecond timestamp — confirmed via a real example: a Chrome extension
messaging error captured twice under two different `event_id`s.
**What I questioned**: whether this was worth documenting given
`browser_error` wasn't a leading signal candidate. **What was verified**:
the finding holds regardless of current relevance — a low-value finding
today can matter once Step 3 touches error-handling behavior.
**Final decision**: documented, not removed. **Day 2 impact**: template
for searching Dataset B for the same class of instrumentation defect in
other event types.

## 6. `ms_since_last_event` distrusted at chunk boundaries

**What I was trying to protect**: the correctness of any future gap-based
segmentation feature. **Why it mattered**: this is an agent-computed
field, not something derived independently — if it's wrong, anything
built on it directly inherits the error. **What I asked to be
investigated**: the full percentile distribution, not just central
tendency. **Evidence that came back**: median 44ms (unremarkable), but
p99 = 5,060ms and min = **-713,900ms**. **What I questioned**: whether a
value that extreme was a bug in the analysis script or a real property of
the data. **What was verified**: cross-referenced the two most extreme
negative values against a separately-discovered `correlation.chunk_id`
identity glitch — both point to the exact same session and chunk
transition, which is strong evidence this is a real source-data defect,
not an analysis error. **Final decision**: never read this field directly
for gap-based analysis; always recompute gaps from sorted `timestamp_ms`.
**Why**: one field being wrong at even a low rate (0.27% of events, 443
occurrences) is enough to justify not trusting it as authoritative
anywhere. **Consequence**: existing gap analysis in this codebase already
followed this rule. **Day 2 impact**: same rule applies to any Dataset B
gap-based feature.

## 7. Explicit chronological sorting

**What I was trying to protect**: correct event ordering regardless of
what the raw file happens to contain. **Why it mattered**: DATA_SCHEMA
doesn't promise write-order equals time-order. **What I asked to be
checked**: whether raw file order was actually chronological, not assumed
to be. **Evidence**: inversions present in every one of 63 sessions
checked, 68% traced to `screenshot_smart` async capture latency (up to
2.5s lag). **What was verified**: the loader's explicit sort by
`timestamp_ms` eliminates the issue in the merged output. **Final
decision**: sorting stays mandatory, not conditional on detecting a
problem first. **Day 2 impact**: none — already the standing, verified
default.

## 8. GT treated as evidence to cross-check, not assumed-perfect

**What I was trying to protect**: not building Step 1's validation on a
single, possibly-flawed source of truth. **Why it mattered**: two files
(`gt.jsonl`, `gt_manifest.json`) both claim to represent the same ground
truth — if they can disagree, trusting either alone is risky.
**What I asked to be investigated**: reconstruct executions from both
sources independently and cross-check them, rather than parsing only the
more convenient one. **Evidence that came back**: 0 count-level
disagreements across 2,009 executions — but 1 field-level disagreement:
`gt_manifest.json` records `split_id: null` for an execution that
`gt.jsonl`'s raw stream shows was genuinely suspended. **What I
questioned**: whether this was a bug in the reconstruction logic before
accepting it as a real GT inconsistency. **What was verified**: read both
files' records for the same `case_id` directly, field by field — the
disagreement is real, not a parsing artifact. **Final decision**: document
the disagreement explicitly; treat `gt.jsonl` as more complete for this
specific field rather than "fixing" one file to match the other.
**Day 2 impact**: no equivalent safety net exists for Dataset B — there's
no second source to cross-check against there.

## 9. `text_input_complete` not elevated to ground truth

**What I was trying to protect**: not letting a corrected, better-than-
feared statistic (98.3% populated) create false confidence in this event
type overall. **Why it mattered**: DATA_SCHEMA explicitly warns this
event type is unreliable in ways beyond missing content (non-text actions
mixed in). **What I asked to be investigated**: content-presence rate,
after first catching and fixing a wrong field-name assumption (see the
debugging log for that story). **Evidence**: 116/118 events have content
via the correct field (`payload.final_text`); 18 of those expose plaintext
password content despite a redaction setting. **What I questioned**:
whether the improved number justified trusting this event type more
broadly. **What was verified**: the schema's broader caveat about
non-text actions being mixed in was never independently re-checked this
pass — so nothing justified elevating its status past "hint."
**Final decision**: kept as a hint only; reconstruct from keystrokes when
actual content matters (verified feasible in one real test case).
**Day 2 impact**: the plaintext-password finding carries into Step 3's
risk section as a governance note.

## 10. Clipboard text not assumed available

**What I was trying to protect**: not designing a feature around content
that isn't actually there. **Why it mattered**: clipboard-derived text
could be valuable if available. **What I asked to be checked**: the real
payload structure of `clipboard_change`, not an assumption from the field
names alone. **Evidence**: `payload.text_content` is `null` in every one
of 5 samples checked — only length/format metadata is captured.
**What was verified**: consistent across multiple independent samples, not
a one-off. **Final decision**: clipboard content is off the table as a
feature source from this field entirely; clipboard *timing/frequency*
remains an unmeasured but viable Day 2 hypothesis. **Day 2 impact**: any
clipboard-content feature needs a different source (Dataset A's
`gt.jsonl` has a `content_preview`, but that's ground truth, unavailable
for Dataset B).

## 11. Screenshot availability treated as dataset-specific

**What I was trying to protect**: not generalizing a Dataset-A-only
observation into a project-wide conclusion. **Why it mattered**:
screenshot-based features would be judged entirely differently depending
on whether captures are actually available. **What I asked to be
measured**: resolution rate on both datasets independently, not sampled
from one. **Evidence**: Dataset A = 7.2% (2,489/34,580); Dataset B = 81.2%
(~3,865/4,759). **What I questioned**: whether the low Dataset-A rate
meant screenshots simply aren't a viable signal for this project.
**What was verified**: measuring Dataset B separately showed the opposite
— screenshots are mostly available there. **Final decision**: explicitly
flagged as an A-vs-B asymmetry, not a general property. **Day 2 impact**:
a screenshot-dependent design must be validated on B specifically —
Dataset A cannot vouch for it either way.

## 12. Dataset B cannot be evaluated with GT-based accuracy

**What I was trying to protect**: not overstating confidence in whatever
Step 1 eventually produces for Dataset B. **Why it mattered**: Dataset B
is the actual production target per the assignment, and it has zero
ground truth. **What I asked to be confirmed**: whether any GT-equivalent
existed for B at all. **Evidence**: `discover_dataset(dataset_b)` finds 0
`gt.jsonl`/`gt_manifest.json` files. **Final decision**: every GT-based
claim in this project is explicitly scoped to Dataset A; Dataset B gets
only the mechanical checks (schema, timestamps, duplication rate), run
independently. **Day 2 impact**: self-validation on B requires different
tooling (distributional sanity checks, manual spot review) that doesn't
exist yet — an open problem, stated as such, not hidden.

## 13. No segmentation algorithm on Day 1

**What I was trying to protect**: not designing a segmentation approach
around untested assumptions about which signals actually work.
**Why it mattered**: the data "looking ready" after profiling is exactly
the point where premature modeling happens. **What I enforced**: an
explicit, repeated scope boundary across every phase of this project.
**Evidence**: no clustering/classification/rule-engine code exists
anywhere in `src/` — checked directly. **Final decision**: Day 1 stops at
signal evaluation. **Day 2 impact**: starts exactly where this stops.

## 14. Multiple weak signals preferred over one hard rule

**What I was trying to protect**: not shipping a segmentation design that
inherits one signal's specific failure mode. **Why it mattered**: no
single measured signal exceeds ~68% GT-boundary alignment. **What I
asked to be measured**: each candidate signal's alignment independently,
so their distinct failure modes would be visible rather than averaged
away. **Evidence**: app-switch misses same-app transitions (31.9% of
boundaries); extracted-text correlates with, rather than adds
independently to, app-switch; gap size has heavy distributional overlap.
**Final decision**: recommend a combined-feature scorer as the Day 2
starting point, explicitly labeled as a hypothesis to test, not a
finished design. **Day 2 impact**: concrete next design question.

## 15. Signal performance measured against real GT boundaries

**What I was trying to protect**: not letting intuition ("app switches
probably mark transitions") stand in for evidence. **Why it mattered**:
the assignment frames judgment about approach as something being
assessed — which only means something if the judgment is backed by a
number. **What I required**: a boundary-alignment method run against
every one of Dataset A's 1,689 real transitions, not a sample and not
assumed. **Evidence**: 68.1% / 64.2% / ~7-10x ratio, respectively, for the
three signals actually measured. **Final decision**: every signal in
`segmentation_signals.md` is tagged "measured" or "hypothesis" — never
presented without that distinction. **Day 2 impact**: the same method
applies to the three remaining hypotheses.

## 16. Percentile statistics required, not just averages

**What I was trying to protect**: not missing a rare but severe defect
hidden inside an aggregate summary. **Why it mattered**: a mean or median
alone would not have surfaced the `ms_since_last_event` anomaly at all —
the median (44ms) looks completely normal. **What I required**: the full
percentile spread (p90/p95/p99/max/min) as a standing requirement for any
timing statistic, not an optional extra. **Evidence**: p99 = 5,060ms,
max ≈ 2.4 hours (a real idle period), min = -713,900ms (a real defect).
**Final decision**: percentiles kept as a permanent part of the profiling
report, not scratch output. **Day 2 impact**: the same percentile
discipline applies to any Dataset B summary statistic before it's trusted.

## 17. Negative findings documented instead of hidden

**What I was trying to protect**: the credibility of every other finding
in this project. **Why it mattered**: a report that only lists things it
found wrong invites suspicion that it didn't look hard enough for the
things it says are fine. **What I required**: that "0 occurrences of
documented quirk X" and "signal Y only reaches 64% alignment" both get
stated explicitly as findings, not omitted because they're not dramatic.
**Evidence**: `gt_duplicate_starts: 0`, `gt_unpaired_switches: 0` are
reported as checked-and-absent; the 31.9% app-switch miss rate is stated
as a limitation, not smoothed over. **Final decision**: every report in
this project states what was checked and found absent, alongside what was
found present. **Day 2 impact**: the same discipline applies to whatever
Day 2 finds that doesn't work.
