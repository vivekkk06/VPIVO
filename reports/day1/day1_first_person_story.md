# Day 1 — First-Person Engineering Account

This is written in first person as the project owner directing an
AI-assisted engineering process — reviewing, deciding, and setting the
quality bar — not as a claim of having typed every line by hand. Where
reasoning is reconstructed from what the task required and what the
evidence shows, it's presented as engineering rationale, not a specific
remembered moment.

## Part 3 — Engineering Reasoning, Decision by Decision

**On session vs. chunk as the unit of analysis.** I wanted to make sure I
wasn't building on a wrong assumption before writing a single line of
segmentation logic later. The schema was explicit that a chunk is a
recording-buffer boundary, not a business boundary, so my reasoning was
that treating chunks independently would risk splitting a real execution
in half and producing wrong process counts. I decided the loader had to
merge a session's chunks before anything else touched the data, and I
treated that as non-negotiable rather than an optimization to revisit
later.

**On raw data immutability.** The important thing for me was being able to
trust every number in every report back to an unmodified source file. I
did not want cleaning or normalization to happen in a way where "the data"
and "our interpretation of the data" became tangled together. I decided
cleaning would only ever operate on data already loaded into memory, never
touch a file on disk, and I kept the raw dataset directories out of
version control entirely so there was no way to accidentally commit an
edited copy.

**On why cleaning stayed conservative.** After seeing how much duplication
existed in the raw `app_switch` stream, I was tempted to just fix it at
the loading layer. I decided against that. My reasoning was that deciding
what counts as "one real switch" versus a duplicate is actually a
segmentation judgment call, not a cleaning one — and if I made that call
silently now, I'd lose the ability to evaluate whether it was even the
right call later, against ground truth. I kept that decision out of the
cleaning stage on purpose, and left it as a documented, visible
precondition for whoever builds the segmentation feature.

**On the `app_switch` and `browser_error` duplication findings.** When the
audit came back showing 65% of `app_switch` events were exact duplicates,
my first reaction was that this looked too extreme to be a real number —
so I wanted it broken down by event type and checked against a real
example before I'd accept it. Once I saw the actual payloads (identical,
40-100ms apart) I treated this as a genuine instrumentation defect rather
than user behavior, and the result changed my understanding of what "count
of app switches" even means in this dataset — it's not a behavioral
signal until it's deduplicated.

**On `ms_since_last_event`.** I did not want to trust a field just because
the recording agent computed it. When percentile statistics surfaced a
minimum of -713,900 milliseconds, I treated that as a signal to
investigate rather than an outlier to discard, and cross-referencing it
against a separately-found chunk-identity issue in the same session gave
me enough confidence to call it a real defect in the source data rather
than noise in my own analysis. My decision was to never let gap-based
analysis in this codebase read that field directly — always recompute
from timestamps.

**On ground truth.** I treated `gt.jsonl` and `gt_manifest.json` as two
sources that ought to agree, not one authoritative file. When they
disagreed about whether one particular execution had been suspended, I
did not want to just pick the more "official-looking" one
(`gt_manifest.json`) and move on — I wanted to understand why they
disagreed. What I found was that the manifest simply doesn't record a
suspension that was never resumed. That changed my understanding of what
"ground truth" means here: it's not infallible, and cross-checking it
against itself was worth the effort.

**On `text_input_complete` and clipboard content.** I did not want to
assume either was a usable text source without checking. For keystrokes, I
tested reconstruction directly against a real event and it matched
exactly, which told me that path is genuinely viable if needed later. For
clipboard, checking the raw payload showed the actual text is never
captured — only metadata — so I ruled that out as a text source
completely rather than assuming it might work.

**On screenshots.** The important thing for me here was not letting a
Dataset-A-only observation become a project-wide conclusion. Measuring
the resolution rate separately on both datasets and finding a 7.2% vs.
81.2% split was the kind of result that specifically justified writing
"do not assume this transfers" as an explicit rule rather than a passing
comment.

**On not starting segmentation.** I kept this out of Day 1 on purpose. My
reasoning was that once the data "looks ready" after profiling, it's easy
to start building the actual algorithm prematurely, and the assignment
itself frames judgment about how to spend the available days as part of
what's being evaluated. I decided Day 1's job was to finish evaluating
signals, not to start scoring them into a segmenter.

**On when Day 1 was "done."** I decided completion meant: every planned
check had actually been run against real data (not assumed to pass),
every finding had a number behind it, every AI-introduced mistake was
documented rather than quietly fixed, and nothing outstanding was a
hidden blocker. The one item I left explicitly incomplete —
committing the work to git — I left incomplete by choice, not because the
technical work wasn't finished.

## Part 4 — Think → Build → Test → Learn

| Stage | My Goal | My Initial Reasoning | What I Asked/Required | AI Assistance | What We Built | What I Checked | What We Found | My Decision | Result/Learning |
|---|---|---|---|---|---|---|---|---|---|
| Project setup | A structure Step 2/3 could reuse without copy-pasting path logic three times | Solving session/chunk discovery once, in a package, beats re-solving it per script across a multi-day project | Required a proper package layout, not loose scripts, and a minimal dependency footprint | Implemented the layout, `.gitignore`, dependency list | `pyproject.toml`, `.gitignore`, `requirements.txt`, `src/procmine` | Confirmed the install actually worked cleanly on this environment's Python (3.14.7), not just that requirements.txt looked reasonable | Clean install, no dependency conflicts | Adopt as-is | A minimal dependency set (matplotlib + pytest) avoided a whole class of version-compatibility risk on a very new Python |
| Session/chunk loading | Correct process-execution counts, not split by recording artifacts | The schema says chunks are time buckets, not process boundaries — treating each chunk independently could split a single execution and produce incorrect process counts | Required session-level loading as the only entry point downstream code uses, and required this be checked against real GT data, not just asserted from the schema doc | Implemented `load_session_events` with multi-chunk merge + chronological sort | `loaders/events.py` | Whether GT executions actually crossed chunk boundaries in practice, and whether the resulting event count matched a published estimate | 162,768 events (vs. README's ~162,000); 53/63 sessions multi-chunk; majority of 2,009 executions cross chunks | Make session-level loading non-negotiable, not an optimization to revisit | A count matching a published estimate is a real correctness signal, not just "it ran without error" |
| Validation | Know when raw data is untrustworthy without crashing on the first bad record | A validator that halts on line 1 of a problem is less useful for a 162,768-event audit than one that accumulates every issue found | Required non-fatal, accumulating validation with severity left to the caller | Implemented `ValidationReport` + check functions | `validation.py` | Whether "0 violations" reflected real cleanliness or a validator that wasn't looking hard enough | 0 schema violations in Dataset A | Push further into a deeper quality audit rather than accept a clean validation pass as the whole story | The absence of a violation is itself worth recording, not proof nothing else is wrong |
| Manifest robustness | Confirm the loader degrades gracefully on corrupted metadata, not just clean input | An audit pipeline whose entire job is finding data problems shouldn't itself be fragile to a data problem | Required a deliberate stress test against corrupted input, not just continued testing against clean real data | Diagnosed the resulting crash; implemented the fix | `_read_manifest_raw()` wrapper in `loaders/events.py` | Re-ran the exact corruption scenario before and after the fix | Confirmed crash pre-fix; confirmed graceful degradation post-fix | Wrap every manifest read the same way; require a regression test before calling it closed | Defensive handling applied inconsistently across similar code paths in the same codebase is itself worth auditing for |
| Duplicate investigation | Know whether raw event counts can be trusted as behavioral signals | If a "count of X" is going to inform a segmentation feature later, I needed to know whether it counts real occurrences or an instrumentation artifact | Required duplicate detection at four distinct levels (exact/semantic/sequential/GT), not one generic check | Implemented all four categories; ran against real data | `audit.py`, `full_audit_dataset_a.json` | Broke the aggregate 33,232-duplicate number down by event type before accepting it meant anything; checked real payloads directly | 65% `app_switch` duplication, 42 `browser_error` semantic-duplicate groups, 0 exact duplicates | Report all three, delete none — dedup is a segmentation-time decision | A single aggregate duplicate count needed a type breakdown before it was actionable |
| Cleaning | Normalize only what's unambiguous, leave judgment calls to segmentation | Cleaning that requires a judgment call about "what counts as one event" is a segmentation decision wearing a cleaning-layer disguise | Required the cleaning scope stay conservative even after seeing a strong case (65% duplication) for going further | Implemented `clean_session_events` (exact-dup removal + sort) | `cleaning.py` | Whether "0 exact duplicates triggered" meant the check was pointless or just an honest null result on this dataset | 0 exact duplicates triggered on real data | Keep the transformation list short and explicitly justified rather than expand it opportunistically | An honest "0 triggered" result is still a useful, reportable outcome |
| Ground-truth validation | Know whether the two GT files can be trusted individually or only in combination | Two "ground truth" sources that could silently disagree needed a cross-check, not blind trust in either | Required both `gt.jsonl` and `gt_manifest.json` be parsed and cross-checked, and required documented GT quirks be handled, not silently "fixed" | Implemented GT reconstruction + cross-check; added deeper checks (resume/suspend/overlap) | `loaders/ground_truth.py` | Verified the one disagreement found by reading both files' records for the same `case_id` directly, field by field | 2,009 executions, 0 count mismatch, 1 real abandoned suspension, 1 field-level GT disagreement | Document the disagreement; don't "fix" one file to match the other | Ground truth can itself be internally inconsistent — it's evidence, not an oracle |
| Dataset profiling | Surface anomalies that a mean/median summary would hide | An aggregate mean can mask a rare but severe defect | Required the full percentile spread (p90/p95/p99/max/min) as a standing requirement, not an optional extra | Computed event/layer/type/app breakdowns and percentile gap stats | `profiling.py`, `dataset_profile.md` | Whether the unremarkable-looking median (44ms) told the whole story | `ms_since_last_event` p99=5,060ms, min=-713,900ms — a real anomaly invisible at the median | Keep percentiles permanent in the profile, not scratch output; investigate the outlier instead of discarding it | The requirement itself, not just the execution, is what surfaced the finding |
| Case studies | Learn what real process boundaries look like, using genuinely representative examples | Picking sessions by measured properties is more likely to surface real edge cases than picking arbitrarily | Required session selection be justified by real `gt_manifest.json` properties (execution count, variant count, split presence), not chosen arbitrarily | Queried those properties to select 5 sessions; generated timeline figures | `scripts/case_studies.py`, 5 figures | Whether the most-complex-session pick would surface anything beyond what it was picked for | It also contained the chunk-identity glitch found independently — a coincidence worth keeping as a cross-reference | Evidence-based selection stays the standard for any future case-study work | Property-based selection surfaces things arbitrary selection wouldn't |
| Segmentation signal analysis | Avoid claiming a signal works without a number behind it | Judgment about approach only means something if it's evidence-backed, not intuition-backed | Required every candidate signal be measured against real GT boundaries before being called effective | Built a ±2s GT-boundary alignment method; ran it against all 1,689 real transitions | ad-hoc analysis scripts this session | Measured app-switch, extracted-text, and gap-size alignment; explicitly did NOT let window-title/URL/clipboard be reported as effective without the same measurement | 68.1% / 64.2% / ~7-10x gap ratio for the three measured; three left as unmeasured hypotheses | Rank only what was measured; label the rest as hypotheses, not findings | A signal looking promising in a screenshot is not the same claim as a measured signal |
| Testing | Prove behavior, not just achieve coverage | A passing happy-path test only shows valid input works | Required a named regression test for every real bug found, reproducing the original failure specifically | Implemented all 36 tests | `tests/*.py` | Ran the full suite repeatedly across every phase, not once at the end | 36/36 passing | Treat "fixed" as verifiable only once a reproducing test exists and passes | Each bug found got a test that makes "fixed" a checkable claim, not an assertion |

## Part 16 — Final First-Person Day 1 Story

### 1. I framed the problem

I started Day 1 by deliberately not jumping into segmentation. The
assignment's real question — can raw operation logs be turned into
recovered business processes worth automating — only makes sense to
answer if the underlying log data means what it appears to mean. So I
framed Day 1 around a narrower question first: can I trust a count, a
timestamp, or a field in this log enough to build a segmentation feature
on top of it? Everything else followed from that framing.

### 2. I set the Day 1 scope

I decided, and held to, a hard boundary: no segmentation or ML
implementation on Day 1. It would have been easy to start once the data
"looked ready" after an initial profiling pass — that's exactly the trap I
wanted to avoid, because the assignment treats judgment about how I spend
the available days as part of what's being assessed. I kept this boundary
in place through every phase of the work; there is no clustering,
classification, or rule-engine code anywhere in this project as a result.

### 3. I defined the quality bar

I set specific, checkable standards rather than a general "make it good"
intention: raw data stays immutable, no result gets reported without a
number behind it, every AI-introduced mistake gets documented with root
cause rather than quietly patched, and nothing counts as "done" until it's
actually been run against real data. I also required a level of statistical
rigor beyond the obvious — full percentile spreads (p90/p95/p99), not just
mean and median, specifically because an average can hide a rare but
severe defect.

### 4. I directed the data audit

I required the audit go well past "does the JSON parse" — schema validity
and duplication are different claims, and only checking the first would
have missed the second entirely. I specified the audit categories in
detail: exact duplicates, semantic duplicates, sequential duplicates,
missingness by field with missing/null/empty distinguished, timestamp
consistency, event-type/layer consistency, and cross-file consistency
between all four file types in the dataset. That specificity is what
produced the finding that mattered most: 65% of every `app_switch` event
in Dataset A is an exact, back-to-back duplicate.

### 5. I reviewed suspicious findings

I did not accept extreme-looking results at face value. When 65% of
`app_switch` events came back as duplicates, that felt too large to trust
without a concrete example, so I required the number broken down by event
type and checked against real payloads before accepting it as a genuine
instrumentation defect rather than an artifact of the analysis itself.
When an early profiling pass reported "100% of `text_input_complete`
events are missing content" — a number that agreed suspiciously well with
a warning already in the documentation — I required that be checked
against a real raw event before it went into any report. It turned out to
be wrong: the actual content field (`payload.final_text`) wasn't even
named in the schema documentation, and the real figure was 98.3%
content-present, not 0%. Agreement with what I expected to find was
exactly why that result got scrutinized, not accepted.

### 6. I made design decisions

Every one of these went through a real trade-off, not a default: session-
level loading over chunk-level (because chunks are storage boundaries, not
process boundaries, and GT data confirms most executions cross them);
keeping the `app_switch`/`browser_error` duplicates in the raw and cleaned
stream rather than deleting them (because deciding what counts as "one
real switch" is a segmentation-time judgment call, not a cleaning fact,
and I didn't want that decision buried where it couldn't be evaluated
against ground truth); never trusting `correlation.ms_since_last_event`
directly for gap analysis once it showed a minimum of -713,900 milliseconds
at a chunk boundary; and treating `gt.jsonl` and `gt_manifest.json` as two
sources to cross-check rather than one authoritative file, which is what
caught a real disagreement — an abandoned process suspension that the
manifest simply doesn't record.

### 7. I validated the evidence

I didn't treat a single number as sufficient proof of anything. The
`ms_since_last_event` anomaly was corroborated against a separately-found
`correlation.chunk_id` identity glitch in the same session before I
treated it as a real source-data defect rather than noise. The screenshot
resolution rate was measured independently on both datasets (7.2% in A,
81.2% in B) specifically so a Dataset-A-only observation wouldn't get
generalized into a project-wide conclusion. The three segmentation signals
I did claim as measured (deduplicated app-switch, extracted-text presence,
gap size) were each checked against all 1,689 real GT boundaries in
Dataset A, not a sample.

### 8. I used AI to accelerate implementation

I want to be direct about this rather than understate it in either
direction: an AI coding assistant implemented the loaders, the validation
framework, the audit tooling, the tests, and the report drafts, and it
executed every script and diagnosis I've described above. What I did was
define what needed to exist and why, specify the methodology and quality
bar in detail, direct which results needed deeper investigation, and
decide what the evidence meant once it came back. That division — I own
the engineering process and decisions, AI accelerates the implementation
and execution — is what actually happened, and it's also exactly what the
assignment says is fine as long as it's disclosed honestly.

### 9. I documented failures honestly

Two real bugs happened this project, and both are written up in full: the
manifest-crash bug (found because I required robustness testing against
corrupted input, not just continued success on clean data) and the
`text_input_complete` field-name mistake (found because I required
suspicious results be re-checked against raw data before being reported).
Neither got quietly fixed and forgotten — both have a documented root
cause, a fix, and a regression test that reproduces the original failure,
because I wanted "fixed" to be a verifiable claim, not an assertion.

### 10. I decided Day 1 was ready for Day 2

I set the completion bar as: every planned check actually run against real
data, every finding backed by a number, every AI-introduced mistake
documented, and nothing outstanding as a hidden blocker. By that bar, Day
1 is done — with one item left explicitly, deliberately incomplete:
committing the work to git, which I chose to do myself, in my own words,
rather than have it done for me. Day 2 starts exactly where Day 1 stops:
measuring the three segmentation-signal hypotheses I left unmeasured
(window title, browser URL, clipboard timing), using the same
evidence-first standard that already found two real bugs and one real
data inconsistency this time around.
