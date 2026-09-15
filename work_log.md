# Work Log

For the detailed evidence behind every finding below, see `reports/day1/`.
For the full account of engineering ownership and AI usage specifically,
see `reports/day1/my_engineering_contribution.md` and
`reports/day1/engineering_decision_register.md`. This log stays
chronological and concise.

## Day 1 — 2026-09-12 — Data understanding & ingestion foundation

All of the following happened in one continuous work session on 2026-09-12.
Exact clock times within the day are not recorded, so I'm not stating any
— where I refer to sequence ("first," "then," "later"), that's order, not
timestamps.

### A. Day 1 goal

Before touching segmentation, I wanted to know whether the operation logs
could actually be trusted the way the task assumes — whether a count, a
timestamp, or a field means what it appears to mean. Step 1 is only as
good as the data underneath it, so Day 1's scope was: discovery, loading,
validation, data-quality audit, ground-truth verification, profiling, and
candidate-signal evaluation. No segmentation algorithm, no ML, no Dataset
B output. I held that boundary for the whole day.

### B. What I built

- A `src/procmine` package rather than loose scripts: data models, path/
  session/chunk discovery, event and ground-truth loaders, a validation
  framework, a deeper data-quality audit module, a conservative cleaning
  layer, profiling, and figure generation.
- Five CLI scripts (`profile_dataset.py`, `parse_ground_truth.py`,
  `validate_dataset.py`, `audit_dataset.py`, `case_studies.py`) that run
  end-to-end against real data, not just synthetic fixtures.
- 36 tests across 7 files — behavior tests, not coverage padding: each
  real bug found got a named regression test reproducing the original
  failure.
- Five case-study session timelines, selected by real `gt_manifest.json`
  properties (execution count, variant count, split presence), not
  arbitrarily.

### C. What I discovered

**Dataset A**: 63 sessions, 117 chunks, 162,768 events, 2,009 reconstructed
GT executions — event count matches the README's stated "~162,000," a
real correctness signal, not just "it ran."

**Dataset B**: 15 sessions, 20 chunks, 20,477 events, no ground truth, by
design.

**Screenshot directory layout is inconsistent on disk.** 35 of 117
Dataset A chunks store screenshots in a sibling directory with a shorter
name than the chunk that references them; the other 82 use the layout
you'd expect. The resolver checks both locations rather than assuming one.

**Raw event order isn't reliably chronological.** Before sorting, every
session has inversions; the majority trace to `screenshot_smart` events
landing slightly out of write-order because screen capture is async
relative to the input-event pipeline. Sorting by `timestamp_ms` explicitly
is required, not optional — this is exactly why the loader always does it.

**Multi-chunk sessions are the norm, not the exception**: 53 of 63
sessions span more than one chunk, and the majority of GT executions cross
a chunk boundary — confirms chunk boundaries are storage artifacts, not
process boundaries, both from the schema and from the data itself.

**The two documented GT defects (duplicate `process_started`, unpaired
`process_switched_out`) don't occur anywhere in Dataset A** — checked
across all 63 sessions, 2,009 executions, zero instances of either. I kept
the handling for both anyway (tested synthetically) since Dataset B has no
GT to verify the same absence against. Deeper checks I added beyond the
documented quirks found two real things the schema doesn't warn about: one
process suspended and never resumed within its session (a genuine
abandoned execution, not a parsing bug), and a field-level disagreement
between `gt.jsonl` and `gt_manifest.json` — the manifest's `split_id` is
`null` for that same execution even though the raw stream shows it was
suspended with a real `split_id`.

**Instrumentation duplication, not user behavior**: 65% of every
`app_switch` event in Dataset A is an exact, back-to-back duplicate
(identical payload, 36–97ms apart). Checked against all 15 Dataset B
sessions — 0% there. Separately, 42 of ~100 distinct `browser_error`
occurrences are logged twice (84 of ~200 raw events), identical payload
and millisecond timestamp.

**Screenshot availability is dataset-specific, not a general property**:
7.2% of Dataset A's `screenshot_smart` events resolve to an actual file on
disk; 81.2% do in Dataset B (measured against all 15 sessions there too).
A conclusion drawn only from A would have been wrong for B.

**`ms_since_last_event` (the agent's own field) has a real minimum of
-713,900ms.** 443 events (0.27%) are below -1,000ms. The two most extreme
cases trace to the exact same session and chunk transition as a separate
`correlation.chunk_id` mismatch I found independently — two unrelated
checks landing on the same point in the data is good evidence this is a
real agent-side defect, not noise in my own analysis.

**Keystroke-based text reconstruction is verified, exact-match, in a real
case**: pulled a `text_input_complete` event's linked `related_keystrokes`
and concatenated characters — matched `final_text` exactly.

**Clipboard content is not recoverable from `clipboard_change`**:
`payload.text_content` was `null` in every sample checked; only length/
format metadata is captured.

**A governance/security finding worth carrying into Step 3**: 18
`text_input_complete` events contain plaintext password-field content
(`final_text`) despite `redact_password_fields: true` in the capture
settings. Synthetic test credentials, no real exposure — but the
redaction mechanism itself doesn't appear to work for this field, which
matters if this pipeline ever touched real production logs.

### D. What broke, and how I fixed it

**A corrupted `manifest.json` crashed the entire session load.** I
stress-tested the loader against deliberately corrupted metadata rather
than accepting success on clean real data as sufficient — an audit
pipeline whose whole job is finding data problems shouldn't itself be
fragile to one. It wasn't: one malformed manifest file took down the
whole session (and would have taken down a full dataset batch). Root
cause: manifest parsing assumed well-formed input; the equivalent
line-level event parser already had defensive handling, manifest parsing
didn't. Fixed with a wrapper that catches the parse error and records it
instead of raising, plus a regression test that reproduces the exact
original failure. Re-verified: the same corruption scenario now loads
successfully with the error recorded, not thrown.

**A profiling pass reported "100% of `text_input_complete` events are
missing content."** That number agreed suspiciously well with a warning
already in DATA_SCHEMA.md, which is exactly why I didn't accept it — an
extreme result that confirms what you already expected is worth checking
against raw data before it goes in a report, not after. The profiler had
guessed the content field was named `text`/`content`/`value`; none of
those exist. The real field, `payload.final_text`, isn't named anywhere
in the schema documentation. Corrected and re-run against all 118 real
events: 2 missing (1.7%), not 118 (100%). This stands as the clearest
example from Day 1 of why a plausible-looking result still needs a raw
example checked before it's trusted.

### E. What evidence changed my decisions

- The 65% `app_switch` duplication rate meant "count of app switches"
  could not be treated as a trustworthy raw feature — it changed how I
  scoped the cleaning layer (see F).
- The `ms_since_last_event` percentile spread (not just the median, which
  looked fine at 44ms) is what surfaced the -713,900ms anomaly — I would
  not have found it from an average alone, which is why percentiles are
  now a standing requirement for any timing statistic in this project.
- The `gt.jsonl` vs. `gt_manifest.json` disagreement changed how I treat
  "ground truth" here — it's strong evidence to cross-check, not an
  infallible file to trust in isolation.
- Measuring screenshot resolution on both datasets independently (instead
  of generalizing from Dataset A) is what caught the 7.2%-vs-81.2%
  asymmetry — a single-dataset measurement would have produced a wrong
  conclusion for Dataset B.

### F. What I deliberately did NOT do

- Did not modify raw data anywhere — cleaning operates on in-memory data
  only, raw files are `.gitignore`'d out of the repository entirely.
- Did not treat chunk boundaries as process boundaries.
- Did not delete the `app_switch`/`browser_error` duplicates — decided
  what counts as "one real switch" is a segmentation-time judgment call,
  not a cleaning-time fact, and left it as a documented precondition for
  whoever builds that feature (me, on Day 2).
- Did not trust `text_input_complete` as ground truth, even after the
  corrected number came back better than the documentation implied.
- Did not trust `correlation.ms_since_last_event` directly for any
  gap-based analysis, after finding it wrong by over ten minutes at a
  chunk boundary — gaps get recomputed from sorted `timestamp_ms` instead.
- Did not start segmentation or any ML implementation — no such code
  exists anywhere in this repository as of Day 1's end.
- Did not report a candidate segmentation signal as effective without
  measuring it against real GT boundaries first.
- Did not assume any Dataset A finding transfers to Dataset B without
  checking — the app-switch duplication rate specifically does not (0%
  across all 15 Dataset B sessions vs. 65% in A).

### G. AI assistance and my role

I used Claude Code as a coding and analysis accelerator throughout Day 1.
I directed the investigation and scope: what needed to be built, which
audit categories mattered (exact/semantic/sequential duplicates,
percentile timing stats, cross-file GT consistency), and the hard rules
(raw data immutable, no fabricated results, fact vs. inference separated,
no segmentation yet). I decided which suspicious findings needed to be
checked before being accepted — the 65% app-switch number and the "100%
missing" `text_input_complete` result both got questioned and verified
against raw data before either went into a report. I made the engineering
and scope decisions based on what came back: keeping the app-switch
duplicates out of the cleaning layer, never trusting `ms_since_last_event`
directly, treating GT as evidence rather than an oracle. Claude Code
implemented the loaders, validation, audit tooling, and tests, executed
every script against the real datasets, and performed the initial
diagnosis on both bugs in section D. I'm not claiming I hand-typed that
code — I didn't — but the requirements, the scope, the review, and the
decisions were mine.

### Numerical correction (kept as an example of verification discipline)

An earlier draft of one of the Day 1 reports stated "54 of 63 sessions
have 2+ chunks" without that number having actually been counted. Before
it stayed in a report, I required it be re-verified — the real count is
53. Small, but it's the same discipline applied to writing the reports as
to analyzing the data.

### H. Day 2 starting point

Day 1 ends with a data foundation I understand and have validated enough to start segmentation.
Nothing below is done yet:

- Measure the three segmentation-signal hypotheses left unevaluated on
  Day 1 (window title changes, browser-navigation URLs, clipboard event
  timing) against real GT boundaries, using the same method already built
  for the three signals that are measured (deduplicated app-switch:
  68.1% alignment; extracted-text presence: 64.2%; gap size: ~7-10x larger
  at boundaries).
- Build the `app_switch`/`browser_error` deduplication step as a named,
  tested function — required before any feature can use raw switch counts.
- Design and validate the actual Step 1 segmentation approach against
  Dataset A's ground truth first, per the assignment's own instruction —
  Dataset B has no GT, so A is the only place accuracy can be checked.
- Only after that: figure out how to self-validate whatever the approach
  produces on Dataset B, since there's no ground truth there to score
  against directly, then produce `segments.jsonl`.

Step 2 (process/ROI analysis) and Step 3 (automation prototype) haven't
started and depend on Step 1's output existing first.

### Git

The Day 1 work was organized into a logical sequence of Git commits after
this review pass — by component (scaffolding, data model, loaders,
validation, audit/cleaning, profiling, scripts, tests, evidence artifacts,
analysis reports, engineering documentation) — rather than committed
incrementally as each piece was built during the day itself. This entry
is the last piece to be committed, after being rewritten.

### I. Short structured summary

| Area | Status | Key evidence |
|---|---|---|
| Data loading | Done | 162,768 / 20,477 events, matches README estimates |
| Validation + audit | Done | 0 schema violations; 65% app-switch duplication found and documented |
| Ground truth | Done (Dataset A only) | 2,009 executions, 1 abandoned suspension, 1 cross-file disagreement |
| Cleaning | Done, deliberately minimal | 2 transformations, both logged, 0 raw-file changes |
| Case studies + signals | Done | 5 sessions; 3 of 6 candidate signals measured against GT |
| Tests | 36/36 passing | 7 test files, one regression test per real bug found |
| Segmentation (Step 1) | Not started | No such code exists |
| Dataset B output / Step 2 / Step 3 | Not started | Blocked on Step 1 |
| Git | 14 commits, organized by component | Not committed incrementally through the day |

---

## Day 2 — 2026-09-13 (date approximate — see note) — Segmentation: boundary-first attempt, evidence-driven pivot to continuity-first

Note on dating: Day 1's entries are dated 2026-09-12 based on this
project's own commit timestamps. Day 2's work happened in a later working
session; I don't have an independently verified calendar date for it
beyond "after Day 1," so I'm using the date this entry was written rather
than asserting a specific day-count against the assignment's 7-day
window, which I have no way to verify from evidence.

### Goal

Evaluate the remaining Day 1 signal hypotheses, then design and validate
a Step 1 segmentation approach against Dataset A's ground truth before
touching Dataset B — continuing exactly where Day 1 stopped.

### What was built and measured, stages 1–6 (summary — full detail in `reports/day2/`)

- **Signal evaluation** (`segmentation_signal_analysis` extended):
  persisted Day 1's ad-hoc boundary-alignment method as real code
  (`src/procmine/segmentation/signals.py`), reproduced its three original
  numbers exactly (68.1%/64.2%/526ms-52ms), then measured the three
  signals Day 1 left unevaluated. Two hypotheses rejected on evidence:
  window-title change (lift 0.048) and clipboard timing (lift 0.008) are
  *less* common near boundaries than mid-execution — the opposite of what
  was predicted. One hypothesis strongly confirmed: browser navigation
  (lift 13.98) is the strongest single signal measured, beating app-switch
  (3.61) by a wide margin — though with a real caveat, session-to-session
  std of 0.246 and one session at exactly 0.0 coverage, meaning it likely
  won't generalize evenly.
- **Temporal feature construction**: built `features.py` (per-transition
  features, GT-agnostic) and measured gap distributions across regimes.
  Found chunk-boundary crossings are temporally distinct from real
  boundaries (median 3,970ms vs. 528ms) and essentially never coincide
  with one (55 of 56). **A genuinely new data defect was found in the
  process**: one session (`ses_20260701-152030-CHAITANYA0BCF`) has events
  ending 16 minutes before its own ground truth says the session ends —
  isolated to exactly 1 of 63 sessions after checking systematically, and
  a reusable check (`audit.session_gt_coverage_check`) was added for it.
- **Baseline segmentation** (deterministic, kept as an explicit baseline
  per the architecture decision below, not deleted): threshold sweep for
  a temporal-only rule found a ceiling of **F1 0.173** (best at τ=3,000ms);
  adding a contextual-change requirement (AND) raised this modestly to
  **F1 0.182**; combining with OR was much worse (F1 0.037). Root cause of
  the low ceiling: GT boundaries are 1.03% of all transitions — a
  **97.4:1 class imbalance** that structurally caps precision for any
  single-threshold rule.
- **Learned boundary model**: logistic regression, `class_weight="balanced"`,
  evaluated with **leave-one-session-out cross-validation** (63 model
  fits — no session's own data ever informs its own prediction). Beat both
  baselines: **F1 0.254** (P=0.157, R=0.655). `chunk_boundary` got
  essentially zero learned weight (−0.047) — a clean quantitative
  confirmation of "chunk boundary ≠ process boundary." Added
  `scikit-learn` as a dependency for this — first new dependency since
  matplotlib/pytest, flagged explicitly rather than added silently.

### Failed/limited approach: boundary-first segmentation

**Observed**: while measuring the learned boundary model's over-
segmentation, found that **90.8% of GT executions contain at least one
spurious predicted boundary inside their own execution span**, with a
mean of **2.80 false internal splits per execution** (one outlier
execution had 62). This is a real, measured result from the actual model,
not a hypothetical.

**Conclusion**: the dominant failure mode of boundary-first segmentation
is not "failing to reconnect interrupted work" — it's the model firing
false-positive boundaries *inside* otherwise-coherent single executions.
Boundary-first prediction, as implemented and measured, is too sensitive
under the current feature/model configuration to be the final approach.

**Decision**: investigate a continuity-first formulation instead (see
below), rather than trying to patch boundary-first with a post-hoc
reconnection layer — which the next finding shows can't be validated
anyway.

### Interruption/resumption finding — investigated and rejected as unvalidatable

**Question I raised**: does Dataset A contain examples of a single
business execution being interrupted by unrelated work and later resumed
(the README's own "non-contiguous work" description), and if so, can a
reconnection/merge capability be learned and validated against it?

**Investigation**: checked directly whether any GT `case_id` reappears
later in a session after a *different* case's execution intervenes.
**Result: 0 of 63 sessions.** Then inspected the one known suspend/resume
example (`M1-B-split-1`) directly in the raw `gt_manifest.json`: `split_id`
is populated on only the later ("phase 2") execution record; there is no
paired "phase 1" record carrying the same identifier. `case_id` is never
reused across an interruption anywhere in the dataset.

**Conclusion**: Dataset A does not provide sufficient ground-truth
evidence to learn or validate interrupted-execution reconnection.

**Decision**: no reconnection/merge capability is included in the
validated pipeline. No `merge_if_similar`-style heuristic is implemented.
The architecture stays extensible for a future dataset that does contain
validated interruption/resumption pairs, but nothing here claims to solve
that problem now, because it cannot currently be checked against evidence.

### Architecture change: boundary-first → continuity-first

**Initial hypothesis** (Day 1 through Stage 6): boundary detection —
"is this transition a boundary?" — is the primary segmentation problem.

**Evidence against it**: the two findings directly above, together.
Excessive false boundaries occur *inside* otherwise coherent GT
executions (90.8% / 2.80 mean), and there is no way to validate a
reconnection layer that would patch the symptom after the fact.

**New formulation, decided**:

```
Events
  → Learn same-execution continuity
  → Estimate whether adjacent activity belongs together
  → Construct coherent executions
  → Boundary = loss of continuity
```

This is not a manually authored rule system — the same feature types
already built (temporal, application, UI/window, browser, behavioral,
text) become evidence for a learned `P(S_i = 1 | X_i)`, where `S_i = 1`
means the activity after transition `i` is likely part of the same
execution as the activity before it. Boundary is derived from *loss* of
continuity, not defined as its own independent target — and the
relationship `P(B_i) = 1 - P(S_i)` is not assumed automatically; whether
that equivalence actually holds is something the implementation has to
justify once built, not something declared true in advance.

**No hardcoded rules, restated for this architecture**: time gap, app
switch, window change, and behavior change remain *evidence* fed to a
learned model — none of them is automatically a boundary on its own. The
existing deterministic baselines and the boundary-first learned model are
**kept, not deleted** — they become `V0`/`V1` experimental references the
continuity-first model (`V2`) has to actually beat, per the same
"simplest approach that achieves strong evidence" discipline this project
has used throughout.

### Decision ledger

**QUESTION**: Should interrupted-execution reconnection be implemented?
**EVIDENCE**: 0 of 63 sessions show a reusable case-level interruption
pair; the one known split_id example is unpaired in the GT data itself.
**OPTIONS**: (1) implement an unvalidated merge heuristic anyway, (2)
exclude reconnection from the validated capability set, (3) use Dataset B
to manufacture assumptions.
**DECISION**: Option 2.
**WHY**: only Dataset A has ground truth to validate against; Dataset B
must stay unseen during methodology selection, and an unvalidated
heuristic would be exactly the kind of unearned claim this project has
avoided everywhere else.
**VALIDATION PLAN**: revisit if a future dataset provides paired
interruption/resumption ground truth.

**QUESTION**: Should the primary formulation stay boundary-first?
**EVIDENCE**: measured 90.8% of GT executions fragmented by the boundary
model, mean 2.80 false internal splits/execution.
**OPTIONS**: (1) keep boundary-first and try to suppress false positives
post-hoc, (2) add an unvalidated reconnection layer on top, (3) reframe
the primary question as continuity rather than boundaries.
**DECISION**: Option 3.
**WHY**: reframing addresses the measured failure mode directly (the
model over-triggers "different" rather than under-triggering "same"),
and doesn't require the unvalidatable capability from the decision above.
**VALIDATION PLAN**: Stage 5/6 must show the continuity-first model
actually reduces the 90.8%/2.80 fragmentation numbers while retaining
useful boundary recall, measured the same way as the boundary-first model
was — success is not assumed, it has to clear that bar.

### Engineering ownership

I raised the investigation direction at each step (whether the
interruption pattern was real and validatable; whether over-segmentation
came from missed reconnection or from something else), required the
false-internal-boundary rate be measured directly rather than assumed,
and made the call to pivot the architecture once that evidence came back
— including rejecting my own project's original hypothesis when the
data didn't support it. Claude Code implemented the signal/feature/
baseline/model code, ran every experiment above, and surfaced the
architecture fork explicitly rather than resolving it unilaterally, per
my own standing instruction not to make silent architectural decisions.

### Status

Stages 1–6 (boundary-first track) complete and measured, as summarized
above. The continuity-first pivot is **decided, not yet implemented** —
no continuity-label construction, continuity model, or reconstruction
code exists yet.

### Stage 1 (continuity-first protocol) — repository re-inspection

Re-inspected the six existing segmentation modules against the new
formulation rather than assuming what would carry over. Result: the
canonical event model, feature extractor, both baselines, and the
LOSO-CV model-training machinery are all directly reusable — none of
that work is discarded by the pivot. What's genuinely missing: continuity
-specific label construction (a different question than `is_boundary`),
fragmentation-specific evaluation metrics, calibration analysis, and the
reconstruction layer itself. Raised one open design question before
building labels: how a transition where *both* sides fall in an
unlabeled "noise" gap should be labeled, since treating that as
continuity risks the model conflating quiet unlabeled time with genuine
same-execution continuity.

### Stage 2 — false-boundary forensic analysis

**QUESTION** (I directed this investigation): why is the existing
boundary model over-segmenting coherent GT executions — specifically, is
it a reconnection failure, a noise/duplicate-event problem, or something
about how the model uses its features?

**EVIDENCE**: built a full forensic dataset of all 4,903 false internal
boundaries (predicted, wrong, and strictly inside one GT execution's
span — 967 further predicted-but-wrong cases that fell in unlabeled noise
gaps were explicitly excluded from this count, per the precise definition
required). Compared against the 1,671 true boundaries on every feature,
on model probability, and on a genuine per-transition feature-
contribution decomposition (re-ran the identical LOSO procedure manually,
specifically to keep each fold's own model rather than reuse a
leakage-tainted one for this analysis).

**ANALYSIS — what the evidence actually showed**:
- The model is **more confident on its false internal predictions
  (median probability 0.960) than on real boundaries (median 0.932)**.
  This rules out a threshold fix outright — the ordering itself is wrong.
- False internal transitions have **larger temporal gaps than real
  boundaries** (median 2,627ms vs. 526ms) — genuine mid-execution pauses
  in real work are frequently longer than a typical real boundary gap.
- Feature-contribution decomposition confirms this quantitatively:
  `log1p_delta_t_ms`'s mean contribution to these false predictions
  (+6.645) is 4–7x larger than any other feature's — temporal gap
  dominates the false positives by a wide margin.
- Checked and **ruled out** the two most obvious noise explanations:
  duplicate `app_switch` events (0.31% involvement) and chunk-boundary
  crossings (0.16% involvement) — neither explains the problem.
- Found one real exception with a different cause: the single worst
  execution (62 false splits in 42 seconds) is a `browser_error` storm
  (170 of 262 events) — a genuine data-quality anomaly, not the general
  pattern. The representative/typical case (16 splits) had no such
  anomaly, just an ordinary 28-second human pause during keystroke-heavy
  work — confirming the dominant cause is pervasive, not a few bad
  sessions (checked directly: 0 of 63 sessions have zero false internal
  boundaries).
- Found one previously-unidentified feature limitation:
  `browser_domain_changed` compares `urlparse().netloc`, which includes
  port number — this portal runs multiple services on different local
  ports, so navigating within one coherent process can register as a
  "domain change." Flagged as a hypothesis for a later experiment, not
  acted on now.

**DECISION**: do not change the model, threshold, or features until this
was understood — investigation completed before any implementation
change, per my own instruction. The continuity-first pivot from the prior
entry is reinforced, not undermined, by this evidence: the core problem
(gap size treated as strong evidence in isolation) is exactly what a
formulation requiring sustained, multi-signal discontinuity is meant to
address — though this investigation does not prove continuity-first will
fix it; that remains to be measured once built, not assumed.

**NEXT HYPOTHESIS**: a continuity-first model needs to weigh temporal
evidence less in isolation than V1 did, or it risks inheriting the same
gap-vs-pause confusion, since that confusion is a property of the data
(genuine pauses are long and variable) as much as of the boundary-first
framing.

Claude Code implemented the forensic script and ran the analysis; I
specified the exact false-boundary definition to use, directed which
comparisons mattered (probability distributions, feature contributions,
noise involvement), and made the call to stop before touching the model
once the causes were understood, rather than proceeding to fix anything
in the same pass.

### Status

Continuity-first Stages 1–2 complete.

### Stage 3 (pre-training) — why continuity should be modeled from context, and the noise-gap labeling question

**QUESTION**: why should continuity be modeled from context rather than
treating individual event transitions as direct boundaries?

**EVIDENCE** (Stage 2): false internal boundaries have *higher* median
model probability (0.960) than real boundaries (0.932) — the model isn't
just imprecise, its confidence ordering is backwards. The dominant driver
is temporal gap alone (`log1p_delta_t_ms` mean contribution +6.645, 4–7x
any other feature), and false internal transitions have larger gaps
(median 2,627ms) than real boundaries (median 526ms) — genuine human
pauses in real work routinely exceed typical boundary gaps.

**NEW HYPOTHESIS** (mine — the architecture direction is my call, Claude
Code is implementing and measuring it): local contextual/trajectory
continuity — does activity before and after a gap belong to the same
behavioral trajectory, not just "how long was the gap" — may distinguish
genuine human pauses from actual execution changes better than a single
event-to-event transition dominated by temporal gap can.

**RISK, explicitly acknowledged before building anything**: the same
temporal signal could remain dominant in a context-window model unless
its interaction with contextual/behavioral evidence is controlled and
measured, not just assumed to improve by adding more features.

**VALIDATION PLAN**: session-aware (leave-one-session-out) Dataset A
experiments, same discipline as Stages 5–6, comparing boundary quality
*and* execution coherence (false-splits/execution, % fragmented) — not
boundary F1 alone, since a model can score well on one and still fragment
executions badly, which is exactly what happened with V1.

**Noise-gap labeling — investigated, options presented, NOT decided.**
Quantified the structure directly rather than assuming it:
`SAME_EXECUTION` 84.48%, `NOISE_TO_NOISE` **14.24%** (23,171
transitions — present in every session, 6.7%–29.7% per session),
`EXIT_TO_DIFFERENT_EXEC` 0.85%, `EXIT_TO_NOISE` 0.22%, `ENTRY_FROM_NOISE`
0.22%. Found that the current `is_boundary=False` label is applied
identically to genuine same-execution transitions *and* to all 23,171
noise-to-noise transitions, which have no GT claim about them at all —
and that all 351 `ENTRY_FROM_NOISE` transitions (a new execution actually
starting after idle time) are currently indistinguishable from ordinary
continuity. Three labeling options written up with trade-offs
(`reports/day2/noise_gap_labeling_analysis.md`) — excluding
ambiguous/unlabeled transitions from training, labeling noise-to-noise as
same-execution, or labeling it as different-execution. A recommendation
(exclude the ambiguous 14.68%, don't guess a label the GT doesn't
support) is offered in that report, but **the final decision is explicitly
left open, per instruction, until reviewed and approved** — no continuity
labels have been constructed and no model has been trained on this
question yet.

Claude Code implemented the classification script and ran it against real
Dataset A; I set the architecture direction (continuity-first, context
windows, trajectory continuity) and the explicit rule that this labeling
question must be resolved with evidence before any training happens, and
I remain the one approving which option gets used.

### Status

Stage 3 pre-training investigation complete. Continuity-label
construction, feature/context-window design, model training, calibration,
and reconstruction all remain **Planned**, pending the noise-gap labeling
decision.

### Stage 4 — continuity label policy approved and implemented

**QUESTION**: how should continuity labels be defined when GT does not
cover the transition?

**EVIDENCE**: Stage 3's measured category counts — SAME_EXECUTION
137,450 (84.48%), NOISE_TO_NOISE 23,171 (14.24%), EXIT_TO_DIFFERENT_EXEC
1,383 (0.85%), EXIT_TO_NOISE 350 (0.22%), ENTRY_FROM_NOISE 351 (0.22%).

**DECISION** (mine — approved after reviewing the Stage 3 options):
Option A. Train only on transitions with unambiguous GT evidence; exclude
`NOISE_TO_NOISE` and `ENTRY_FROM_NOISE` entirely, assign neither S=0 nor
S=1 to them.

**RATIONALE**: do not manufacture supervision from unlabeled regions —
consistent with this project's standing discipline since Day 1.

**RISK, accepted**: the model will not directly learn from unlabeled/
idle-region behavior. Accepted because a guessed label there would
introduce systematic supervision noise, which is a worse failure mode
than simply not covering that case yet.

**Implementation note surfaced during the build, not decided silently**:
the approved policy's 5 named categories didn't fully specify one small
sub-case found while implementing full coverage of `EXIT_TO_NOISE` —
62 of its 350 transitions (0.04% of the dataset) have no paired boundary
label at all (they're a session's last recorded execution, with nothing
following to pair a boundary against). Applied the same governing
principle used for the rest of the policy (don't manufacture supervision
without reliable evidence) and excluded these too, as a new category
`EXIT_TO_NOISE_UNRELIABLE_EXCLUDED` — flagged here for review rather than
silently folded into an existing category.

**VALIDATION**: ran the label construction against all 63 Dataset A
sessions and reconciled every count against Stage 3's independently-
computed numbers. **Exact match, including the total** (all six category
counts sum to 162,705, the full transition count, with no discrepancy).
Positive:negative ratio is 82.26:1 (137,450 positive vs. 1,671 negative)
— the negative count is, not coincidentally, identical to the
boundary-first model's 1,671 true GT boundaries, since the two negative
categories here (`EXIT_TO_DIFFERENT_EXEC` + `EXIT_TO_NOISE_BOUNDARY` =
1,383 + 288) are exactly the same underlying transitions the old
`is_boundary=True` label already identified. No session has only one
label class present, and no session shows an extreme (>500:1) local
ratio — the imbalance is consistent across the dataset, not concentrated.

**OWNERSHIP**: I made the labeling-policy decision (Option A) and
reviewed/approved the additional sub-case handling once it was found;
Claude Code implemented the label-construction module, the 9 invariant
tests, the reconciliation script, and ran it against real Dataset A.

### Status

Continuity labels are built, tested, and fully reconciled.

### Stage 5 — context/trajectory feature design and measurement

**QUESTION**: can local context and before/after trajectory evidence
distinguish same-execution continuity from genuine execution boundaries
better than adjacent-transition features alone?

**EVIDENCE** (Stage 2): temporal-gap dominance and widespread
fragmentation in the boundary-first model.

**HYPOTHESIS** (mine — I set this direction): a transition should be
evaluated using surrounding activity trajectory rather than isolated gap
magnitude.

**RISK, acknowledged before measuring**: context features could introduce
noise or dimensionality without adding real information; after-context is
valid for this offline task but would not be for a real-time system —
documented explicitly in the new module rather than left implicit.

**WHAT THE MEASUREMENT ACTUALLY SHOWED** (I required univariate AUC
evidence before allowing any feature into consideration for training):

- Temporal gap remains **by far the strongest single feature** (AUC 0.110,
  i.e. 0.39 from uninformative — over 2x the next strongest family),
  and stable per-session (std 0.019 across 63 sessions). This doesn't
  contradict Stage 2's finding about its dominance being a problem — that
  was about a specific hard subset; pooled across the whole dataset, most
  same-execution transitions have short gaps, so the feature stays
  informative on average despite failing on the documented minority
  pattern.
- The session-relative temporal normalization I asked to be tested (gap ÷
  session median gap) showed **no measurable improvement** over the
  existing plain log transform (0.1097 vs. 0.1098, essentially identical)
  — a real negative result, not a null one to bury.
- Small trajectory windows (N=3, N=5) were **mostly weak**, contrary to
  the original hypothesis at that scale — but N=10 event-type and
  interaction-category similarity showed real, moderate discrimination
  (AUC 0.697 and 0.605). The trajectory idea isn't rejected, but it needs
  a wider window than initially proposed.
- **The browser-domain-port hypothesis I asked to be tested was
  rejected**: stripping the port from `browser_domain` did not improve
  discrimination at any window size, and was measurably *worse* in the
  windowed comparison. Recommendation: keep the existing representation
  unchanged — Stage 2's concern was reasonable to raise given the
  evidence at the time, but the controlled experiment doesn't support
  acting on it.
- A feature family not in the original plan emerged from the measurement
  itself: the wall-clock **duration** spanned by the N events after a
  transition (not just whether one occurred) is a moderately strong,
  previously unmeasured signal (AUC up to 0.686).

**VALIDATION**: all measurement pooled across 63 sessions (139,121
labeled transitions) plus per-session AUC stability checks for the
strongest features; no random splitting of adjacent transitions; Dataset
B untouched.

**DECISION**: no feature set is finalized yet — a recommended candidate
list is written up for Stage 6 to actually test in a trained model, since
univariate strength and multivariate contribution are known (from the
boundary-first track's own Stage 6) to sometimes diverge.

Claude Code implemented the context/trajectory feature module, the 12
new tests, and the measurement script, and ran it against real Dataset A;
I set which hypotheses needed testing (window size, session-relative
temporal normalization, the port experiment) and required the evidence be
measured before any of them could be accepted or rejected.

### Status

Feature families measured and documented.

### Stage 6 — continuity model trained and compared against V1: a mixed result, not declared a success

**QUESTION**: does training an actual continuity model on Stage 5's
recommended features reduce the fragmentation problem Stage 2 found, or
just move the numbers around?

**METHOD**: logistic regression, `class_weight="balanced"`, leave-one-
session-out cross-validation (63 fits) — same rigor as the V1 model.
Boundary quality evaluated only on the 139,121 labeled transitions;
execution-level reconstruction run on the full transition stream,
matching how V1 was evaluated, with excluded-transition predictions
explicitly marked as unvalidated (no GT label exists for them).

**RESULT — genuinely mixed, reported as such rather than rounded up to a
win**:

| Metric | V1 | V2 (continuity) |
|---|---|---|
| Boundary F1 | 0.254 | 0.270 (better) |
| Recall | 0.655 | 0.703 (better) |
| Under-segmentation | 0.085 | 0.063 (better) |
| Worst-session F1 | 0.040 | 0.102 (much better) |
| **Over-segmentation** | 2.711 | **3.239 (worse)** |
| **% GT executions fragmented** | **90.8%** | **94.7% (worse)** |

**The continuity-first model is worse on the exact metric (fragmentation)
that motivated the entire architecture pivot in Stage 2**, while
genuinely improving F1, recall, under-segmentation, and — notably — the
single worst session. I am not accepting this as a validated improvement
just because some numbers went up; per my own standing instruction, one
improved metric does not constitute success.

**Feature importance also produced a concrete, useful negative result**:
`N10_after_window_duration_ms`, one of Stage 5's strongest univariate
signals (AUC 0.686), contributed almost nothing in the trained model
(coefficient +0.033) — likely redundant with the temporal/density
features once combined, the same class of effect V1's own Stage 6 found
for `application_changed`. Confirms, again, that univariate strength does
not guarantee multivariate contribution — worth remembering before
trusting any single-feature measurement as a final answer.

**DECISION**: do not declare the continuity-first pivot validated. Four
options written up (investigate the false-positive distribution
difference directly; re-select the threshold to target fragmentation
specifically, which was always Stage 7's planned job; revisit the feature
set given two features turned out redundant; or conclude continuity-first
classification alone was never going to fix fragmentation without Stage
8's reconstruction layer) — **no option chosen yet, this is presented as
a genuine fork for review**, not resolved unilaterally.

**VALIDATION**: same leave-one-session-out discipline throughout; no
Dataset B; no threshold re-tuning performed to make the headline number
look better.

Claude Code implemented the continuity model, the training script, and
ran the full comparison; I required the exact Stage-2 comparison metric
(% fragmented) be computed directly rather than approximated, which is
what surfaced the regression clearly instead of leaving it implicit in a
less specific "over-segmentation rate" number.

### Status

Continuity model trained and evaluated; result is mixed, not a validated
improvement.

### Option 1 → Option 4 (my chosen order, given after reviewing the four options)

**QUESTION**: why does V2 fragment more GT executions than V1, and does
that change whether Option 2 (threshold re-selection) or Option 3
(feature revisit) is even likely to help?

**METHOD**: re-ran both models' exact LOSO procedures to get comparable
per-transition predictions, then cross-tabulated which specific GT
executions each one fragments.

**EVIDENCE**: 83 executions clean under both; **10 fragmented only by
V1** (V2 fixed these); **81 fragmented only by V2** (V2 broke these,
V1 had them right); 1,578 fragmented by both — and among those shared
cases, V2 adds *more* damage on average (3.53 vs. 3.00 extra segments),
not the same amount redistributed. Net: 71 more executions harmed than
helped, closely matching the raw 90.8%→94.7% gap.

**This refuted my own stated hypothesis from the Stage 6 report** (that
V2's false positives might just be spread more evenly with less damage
each) — the evidence shows V2 is simply more prone to erroneous splits,
both in how many distinct executions it touches and in how badly it hits
the ones both models already get wrong.

**ANALYSIS (Option 4)**: continuity-first classification alone was never
going to fix over-segmentation, because both V1 and V2 still threshold a
per-transition score independently — swapping which score gets
thresholded doesn't remove the thresholding-in-isolation mechanism that
causes fragmentation in the first place. The 81 newly-broken executions
are, by construction, borderline decisions — exactly the pattern a
reconstruction layer that weighs relative evidence across a local
neighborhood of transitions (rather than one fixed global cutoff applied
independently) is structurally positioned to catch. **This is reasoned
from the evidence, not yet measured** — Stage 8 would have to be built
and tested before it counts as validated.

**DECISION**: proceeding to Option 2 next, but with the expectation set
by this diagnosis stated plainly — threshold re-selection can trade
recall for fewer false splits along the same mechanism just shown to be
the structural limitation, so it is not expected to close the 81-vs-10
gap on its own. Still worth doing (it was always the planned calibration
stage), but not oversold as the fix.

Claude Code implemented the comparison script and ran both LOSO
procedures; I set the investigation order (1 before 4 before 2/3) and
the requirement that the "spread more evenly" hypothesis from the
previous stage be checked directly rather than left as an unverified
guess — which is what surfaced that it was wrong.

### Status

Fragmentation mechanism understood and documented. Proceeding to Option
2 (threshold/calibration analysis) next; Option 3 (feature revisit) and
Stage 8 (reconstruction) remain **Planned**.

### Stage 7 — Threshold / Operating-Point Analysis (Option 2)

**QUESTION**: can re-selecting the decision threshold (rather than
changing features, labels, or model) meaningfully close the 81-vs-10
fragmentation gap between V1 and V2 found in Option 1, without destroying
recall?

**HYPOTHESIS** (stated before running anything, per Option 4's own
reasoning): no — fragmentation was diagnosed as a consequence of
thresholding a per-transition score in isolation, a mechanism both models
share regardless of where the cutoff is placed. Threshold tuning should
be able to trade recall for some fragmentation reduction, but should not
close the gap while recall stays usable.

**EXPERIMENT**: re-ran V1's and V2's exact LOSO procedures once each
(same pipelines, same features, same folds as Stages 6/Option 1 — nothing
retrained differently) to get pooled out-of-fold scores across all 63
Dataset-A sessions, built a threshold grid concentrated at the 75th–99.9th
percentiles of each model's own score distribution (justified by the
class-imbalance-driven concentration near 1.0 — a linear grid would waste
points on the flat region), and swept `boundary_metrics()` /
`execution_metrics()` (both reused unchanged from `evaluation.py`, the
latter extended additively this stage with `n_fragmented`/
`pct_fragmented`/`fragmented_case_ids` to stop duplicating that
computation ad hoc across scripts) at every grid point. All threshold
selection used pooled OOF scores only — no per-session tuning.

**EVIDENCE**:
- At the current Stage 6 operating points (which independently re-emerge
  as this run's own best-F1 points — a reproducibility cross-check, since
  the pipeline is deterministic and unchanged), the V2-vs-V1 fragmentation
  gap is +66 executions (close to Option 1's +71; small variance is an
  independent-refit artifact).
- Moving to the min-fragmentation point subject to a recall ≥ 0.5 floor
  (justified as "must catch at least as many true boundaries as it
  misses," fixed before looking at results) narrows the gap to +38 — but
  by both models getting worse (V1's own `only-V1` count rises from 9 to
  43), not by V2 improving toward a fixed V1.
- At recall ≥ 0.5, fragmentation drops only 1.1pp (V1) to 2.9pp (V2) from
  the max-F1 point. Reducing fragmentation substantially (to ~73–79%,
  still very high) requires recall to collapse to ~0.15–0.21 — missing 4
  of 5 true boundaries, not usable.
- Local slope analysis shows both models' operating points sit right at
  the edge of a plateau, not inside one: recall-vs-threshold slope
  roughly doubles to quintuples immediately above τ=0.9078 (V1) /
  τ=0.8860 (V2), i.e. the current point is more threshold-sensitive than
  its isolated F1 number suggests.
- No per-session collapse (F1=0) at any of the three checked operating
  points; moderate, consistent spread (std ≈ 0.03–0.065).

**RESULT**: hypothesis confirmed. Threshold tuning gives a small, real
improvement (gap narrows ~42% at a usable recall floor) but does not
close the fragmentation gap or bring absolute fragmentation to an
acceptable level at any threshold that preserves usable recall.

**DECISION**: do not treat threshold re-selection as a fix for
over-segmentation. Option 3 (feature revisit) is not expected, on this
same structural reasoning, to do materially better — it faces the same
independent-per-transition-thresholding ceiling. Stage 8
(interruption-aware reconstruction, reasoning about relative evidence
across a neighborhood of transitions rather than one global cutoff)
remains the next step expected to actually address fragmentation, per
Option 4's original reasoning — now with quantitative, not just
diagnostic, support.

**REJECTED ALTERNATIVES**: a plain linear threshold grid (rejected —
would have wasted most points in the flat, uninformative low-score
region given the class imbalance); using the geometric knee of the
recall/fragmentation curve as the recall floor (computed as a diagnostic,
but rejected as the named "recall-floor" operating point because it lands
at R≈0.15–0.21, i.e. missing most true boundaries — not a usable floor);
picking round-number recall floors after seeing results (rejected in
favor of fixing the ≥0.5 "catches more than it misses" criterion before
running the sweep, so the floor isn't quietly tuned to produce a
favorable number).

Claude Code implemented `scripts/analyze_threshold_tradeoff.py` and
`src/procmine/segmentation/threshold_analysis.py`, ran both LOSO sweeps,
computed the operating points, stability analysis, and the re-check of
Option 1's damage pattern across thresholds, and wrote
`reports/day2/threshold_tradeoff.md`. I set the investigation's governing
hypothesis in advance (from Option 4's reasoning), required the
recall-floor to be justified independently of the resulting numbers
rather than picked to look good, and set the standard that a narrowed gap
must be reported as narrowed-not-closed rather than rounded up to a
success.

### Status

Threshold/operating-point analysis complete. Confirms, quantitatively,
that threshold tuning alone cannot fix fragmentation while recall stays
usable. Option 3 (feature revisit) and Stage 8 (reconstruction layer)
remain **Planned**; Stage 8 is now the priority given this result.

### Stage 8 — Forensic Characterization of Interruption/Return Patterns

**QUESTION**: before designing a neighborhood-aware reconstruction layer
(motivated by Stage 7's conclusion that independent per-transition
thresholding is structurally insufficient), what does the actual
interruption/return structure inside GT executions look like, and is
there measurable evidence a reconstruction layer could exploit that a
single transition's own features cannot see?

**METHOD**: forensic characterization only — no reconstruction algorithm,
no new model, no new threshold, no Dataset B. Re-ran V1's and V2's exact
LOSO procedures and Stage 6 thresholds (0.9078, 0.8860) once each, purely
to know which transitions each already-approved model flags. Reused
Stage 4's `SAME_EXECUTION`/`EXIT_TO_DIFFERENT_EXEC`/`EXIT_TO_NOISE_BOUNDARY`
categories and Stage 5's N=10 trajectory-jaccard unchanged. Added two
small reusable building blocks no prior stage needed
(`internal_transition_indices`/`build_execution_profile` for per-execution
gap/context-change profiles; `collapse_to_runs`/`detect_return_patterns`
for the brief's named A→B→A pattern, generalized to A→B→C→A) — 15 new
tests. GT used only for grouping/labeling, never as a model feature.

**EVIDENCE**:
- Count reconciliation: Dataset A has 2,009 GT executions total; 1,752 are
  "closed" (defined `end_ts`) and used here, matching every prior stage's
  convention — 257 open executions have no interval to compute gaps
  against, not a new exclusion invented for this stage.
- Large gaps and context changes are the *norm*, not the exception,
  inside a real execution: a typical execution contains ~7-8 internal
  gaps already above the dataset-wide 90th-percentile same-execution gap,
  and ~25 browser-domain changes.
- 95.6-95.7% of both V1's and V2's false-internal-boundaries are isolated
  single-transition spikes, not consecutive clusters — a
  smooth-adjacent-flags heuristic would only ever touch ~1.2% of the
  problem.
- **Central finding**: V1's false-internal-boundaries have a median
  single-transition gap (2,627ms) *larger* than real boundaries' own
  median (526ms) — the single-transition evidence is actively
  misleading, reproducing Stage 2's "inverted confidence" finding
  independently. But their median N=10 neighborhood trajectory-jaccard
  (0.500) is statistically indistinguishable from ordinary same-execution
  continuity (0.500) and clearly unlike real boundaries' (0.286). The
  neighborhood evidence and the single-transition evidence disagree, and
  the neighborhood is the one that agrees with the GT-known answer.
- 50.5% of all 1,752 GT executions contain at least one detected
  leave-and-return pattern (A→B→A or a longer detour), present in every
  one of 63 sessions (16.2%-68.2% per-session rate). For application-based
  returns, both models are far more likely to falsely split at the
  *leave* moment (V1 16.3%, V2 39.4%) than at the *return* moment (V1
  5.6%, V2 10.8%) — for browser-domain-based returns this reverses.
- "Surrounded by continuous activity" (density) is real but weak and
  inconsistent (median density ratio ~0.7-0.8 of the execution's own
  mean, but 25% of flagged transitions sit at or above it) — not a safe
  sole basis for a correction rule.

**RESULT**: the neighborhood-aware reconstruction hypothesis has direct,
quantified support, not just the structural argument Option 4 made
before. The specific, actionable evidence: neighborhood trajectory-
jaccard disagrees with the misleading single-transition gap signal in
exactly the needed direction; false positives are isolated (not
clustered); half of all executions contain a detectable leave-and-return
structure that a forward-looking check could exploit; density alone is
not reliable enough to lean on.

**DECISION**: proceed to designing the reconstruction layer next (not yet
built), guided by this evidence: (1) use neighborhood trajectory-jaccard
as a correction signal, not merely a classification feature; (2) design
for correcting isolated single-transition mistakes, not for smoothing
adjacent runs; (3) treat leave-and-return as a first-class pattern,
particularly asymmetric leave-vs-return flagging; (4) don't lean on
density alone; (5) treat `browser_domain_changed` with caution as a
standalone rule input (29% base rate among ordinary same-execution
transitions).

**REJECTED ALTERNATIVES**: defining "large gap" as an arbitrary fixed
millisecond constant (rejected — used the dataset's own SAME_EXECUTION
p90/p95/p99 instead, consistent with this project's standing practice);
treating the geometric knee or a hand-picked density-ratio cutoff as the
final word on "surrounded by continuous activity" (rejected — reported
the full distribution instead, since the signal turned out weaker/less
uniform than trajectory-jaccard and a single threshold would have
overstated it).

Claude Code implemented `interruption_forensics.py`,
`analyze_interruption_forensics.py`, the 15 new tests, and ran the full
Dataset A analysis. I set the investigation's scope (forensic
characterization only, explicitly no reconstruction algorithm this
stage), required GT/case_id to be usable for forensic grouping but never
as a feature, and required every major finding to carry a count,
percentage, distribution statistic, and an explicit observation-vs-
hypothesis label rather than prose claims alone.

### Status

Forensic characterization complete. Concrete, quantified evidence now
exists for what a reconstruction layer should exploit (neighborhood
trajectory-jaccard, isolated-mistake correction, leave-and-return
awareness). No reconstruction algorithm implemented yet — that is Stage
9's task, pending review of this evidence.

### Stage 8.2 — Reconstruction Architecture Decision (no code)

**QUESTION**: given Stage 8's forensic evidence, what should the
reconstruction layer's mechanism, decision unit, and first concrete
design be?

**DECISION**: reconstruction re-scores/demotes V1∪V2's existing
predicted boundaries only (never adds new ones); decision unit is the
individual candidate boundary, evaluated using local neighborhood
evidence. First design: an ordered, deterministic rule list ("Design
2") — chunk/noise override → leave-and-return check → cluster-size
conservative gate → N=10 continuity fallback. Design 1 (single-feature
threshold) approved as an ablation only, not a competing first choice.
Design 3 (fitted composite score) explicitly deferred pending evidence
Design 2's hard rules cost something material. No numeric thresholds
chosen at this stage — deferred to pooled-OOF selection, Stage 7's
discipline, when implemented.

**OWNERSHIP**: architecture decisions made by the user; Claude Code
drafted the design options and evidence linkage. No code written —
architecture-decision-only stage, approved as specified.

### Stage 8.3 — First Deterministic Reconstruction Experiment (Design 2)

**QUESTION**: does the approved Design 2 rule list, implemented exactly
and evaluated honestly, pass the pre-registered success gate — lower
fragmentation than V1/V2, recall ≥ 0.5, under-segmentation not
materially worse, improvement not concentrated in a few sessions, gain
not explained solely by chunk/noise?

**METHOD**: implemented `reconstruction.py` (union_candidates,
cluster_size_per_transition, involves_duplicate_app_switch reusing
Stage 2's exact duplicate-app_switch definition, return_pattern_evidence_for_transition
reusing Stage 8's detect_return_patterns but window-scoped at ±10 events
— GT execution spans cannot be used for a live decision — instead of
Stage 8's GT-scoped search, apply_design2_rules, apply_design1_rule) —
29 new tests. V1/V2 LOSO re-run unchanged (same thresholds 0.9078/0.8860,
never retuned) to get the candidate set C = V1 ∪ V2. Rule 4's continuity
threshold selected from pooled OOF evidence across all 63 sessions,
reusing Stage 7's `build_threshold_grid` directly, choosing max-F1
subject to the same recall ≥ 0.5 floor Stage 7 already justified.

**EVIDENCE**:
- Selected threshold τ=0.40 on `event_type_jaccard` (N=10). Full sweep
  shows a **monotonic** fragmentation-vs-under-segmentation trade-off
  with no favorable point anywhere on the curve — at τ=1.0 (Rule 4
  inert) metrics match V2's own baseline almost exactly (internal
  consistency check), and every step toward lower fragmentation costs
  under-segmentation proportionally or worse (catastrophically so at
  aggressive τ, e.g. 8.68 at τ=0.10 vs. 0.063 baseline).
- At the selected point: fragmentation 90.6%/94.7% (V1/V2) → **77.6%**
  (reconstruction) — a real, substantial improvement. Recall 0.520,
  clears the floor. But under-segmentation **0.063–0.085 → 0.204**
  (2.4–3.3x), and this increase is **universal — 63 of 63 sessions**,
  not concentrated or noisy.
- Rule-level breakdown: Rule 4 (continuity) does 96% of the work by
  volume (8,487 of 9,021 candidates matched) and removes false-internal
  boundaries at a ~12:1 ratio over real ones (3,667 vs. 296) — genuine
  support for the underlying neighborhood-evidence hypothesis, NOT
  explained by chunk/noise (Rule 1 = 0.9% of all removals). Rule 2
  (return-pattern) shows a weaker ~4:1 ratio (95 vs. 23). Rule 3 (cluster
  protection) matched 338 candidates and, by design, removed none.
- Design 1 (ablation) is nearly identical to Design 2 (F1 0.308 vs.
  0.304, frag 77.9% vs. 77.6%) — Rules 2+3 together touch only ~5.4% of
  candidates, too small a share to move the aggregate much either way in
  this experiment.

**RESULT**: **success gate does NOT pass.** Condition 3 (under-
segmentation) fails cleanly and universally; conditions 1, 2, 4, 5 pass.
Per the pre-registered protocol, this is reported as a failure, not a
partial success — the fragmentation improvement is real, but it is not
free, and the cost (merging genuinely distinct executions) is exactly
the failure mode the objective was designed to catch.

**DECISION**: do not add complexity. Do not implement Design 3 at this
time — the sweep shows this is not a threshold-placement problem (no τ
avoids the trade-off), and Stage 8 already documented substantial
population-level overlap between false-internal and ordinary-same-
execution trajectory-jaccard, so there's no evidence a weighted
composite would resolve the overlap rather than just relocating the same
curve. Before any Design 3 attempt, understanding *why* Rule 4's 296
misclassified real boundaries look the way they do is the more
informative next step — a decision for the project owner, not made here.

**REJECTED ALTERNATIVES**: relaxing the under-segmentation gate to call
this a qualified success (rejected — condition 3 was pre-registered as a
hard gate, and the universality of the failure across all 63 sessions
rules out treating it as noise); picking a more conservative τ to
rescue condition 3 (checked directly via the full sweep — no τ satisfies
both fragmentation improvement and acceptable under-segentation
simultaneously, so this isn't a calibration fix); adding a second
neighborhood feature ad hoc to patch Rule 4 (rejected as a Design-3-style
escalation not authorized by this stage).

Claude Code implemented `reconstruction.py`, the 29 tests,
`run_reconstruction_experiment.py`, ran the full Dataset A experiment,
performed the leakage audit, and reported the honest result including
the gate failure. I approved Design 2's exact architecture in Stage 8.2,
required the success gate to be pre-registered and evaluated without
exception, and required the rule-level and session-level breakdowns
needed to tell a genuine neighborhood-evidence effect apart from a
data-quality-exclusion artifact.

### Status

Stage 8.3 complete. Design 2 does not pass the pre-registered success
gate (under-segmentation fails, universally across sessions). Design 3
is not justified by this evidence and was not attempted, per instruction.
Next decision (understanding Rule 4's misclassified real-boundary
population, or another direction entirely) is **Planned**, pending the
project owner's review.

### Stage 8.4 — Forensic Investigation of Rule 4's 296 Wrongly-Demoted Real Boundaries

**QUESTION**: why do the 296 real GT boundaries Rule 4 wrongly demoted
look continuous to the N=10 neighborhood metric — is there another
raw-event-derived, GT-free signal that explains it?

**HYPOTHESIS**: none stated in advance beyond the brief's own framing —
this was an open forensic search, not a test of one pre-committed idea.

**METHOD**: re-ran V1/V2's exact LOSO (unchanged thresholds) and Stage
8.3's exact Design 2 rule application (reused selected threshold τ=0.40,
not re-selected) to reproduce the same two populations. Cross-check:
reproduced exactly 3,667 (Population A, correctly-demoted false internal
boundaries) and 296 (Population B, wrongly-demoted real boundaries),
matching Stage 8.3 exactly. Compared ~24 signals (existing
TransitionFeatures/TrajectoryFeatures fields, candidate source, return-
pattern involvement, raw V1/V2 scores, hostname/port-level browser
context) between A and B using AUC (Stage 5's established convention,
reused) as the separation measure, then added a session-by-session
directional-consistency check for the top candidates specifically to
catch a signal that looks strong pooled but is actually a cross-session
aggregation artifact or driven by a tiny subset.

**EVIDENCE**:
- Raw model confidence (V1/V2's own scores) does NOT separate A from B
  (AUC 0.48/0.52) — ruling out "just trust the score more."
- **Cross-model agreement is the strongest new finding**: 90.9% of
  Population B was flagged by BOTH V1 and V2 independently, vs. 66.3% of
  Population A (AUC 0.623, 88.9% session-directional agreement — robust).
  Rule 4 currently ignores this entirely.
- **Post-transition activity pace** (`after_window_duration_ms`, AUC
  0.712, 88.9% session-robust; `density_after`, AUC 0.288, 87.3%
  session-robust — the same underlying "tempo" concept measured two
  ways, not two independent signals) separates the populations: A's
  aftermath is steady work (keystrokes/shortcuts dominate, 78-81%); B's
  aftermath is navigation/orientation activity (app_switch 96.3%,
  browser_navigation/click ~70%) — the signature of starting fresh work,
  not continuing it.
- `event_type_jaccard` itself, within the already-demoted population, is
  LOWER for B (0.500) than A (0.600) (AUC 0.247, 93.6% session-robust) —
  B sits closer to the τ=0.40 decision boundary, not further from it;
  this describes Rule 4's own feature more precisely, not a new signal.
- `delta_t_ms`/`log1p_delta_t_ms` showed a modest pooled AUC (0.593) that
  **collapsed under the session-robustness check (41.3% agreement, worse
  than chance)** — rejected as a likely cross-session scale artifact
  (Stage 4 already documented an 11.8x range in session-level gap
  medians), a concrete example of exactly the kind of false lead the
  robustness check was built to catch.
- Application/browser/window "same context" signals (host, port,
  interaction category, "high jaccard but context changed") all showed
  no meaningful separation (AUC 0.42-0.55) or were too sparse to trust.
- Population B spreads across all 63 sessions (max 10, i.e. 3.4%, in any
  one session) and all ~15 GT process codes roughly evenly — not
  concentrated in a session or a process family. Only 8.1% are resume
  boundaries — most are genuinely-new-process starts.
- Leave-and-return involvement is mechanically zero for both populations
  (Rule 2 already removes any such candidate before Rule 4 ever sees
  it) — expected, not a substantive finding.

**FINDINGS**: two robust, non-redundant, GT-free, reconstruction-time-
available signals were found — cross-model agreement and post-transition
tempo — each moderately separating (AUC 0.62-0.71) and consistent across
~89% of sessions individually. Several plausible-looking signals
(gap size, browser/app "same context") were explicitly tested and
rejected for lack of robustness or lack of separation, not merely
unreported.

**CANDIDATE SIGNALS**: `flagged_by_both_models` (strong), `after_window_duration_ms`
/ `density_after` (strong, treated as one finding). `browser_domain_jaccard_with_port`
is directionally robust but only computable in 57/63 sessions — limited
generality, not rejected outright. Everything else tested is rejected.

**DECISION**: report the findings; do not implement any new rule; do not
modify Stage 8.3's reconstruction behavior; do not proceed to Design 3
or Dataset B. The 296 errors are not fundamentally, unfixably ambiguous
(real, robust structure exists — this is not a null result) but are not
trivially separable either (AUC 0.71 leaves substantial overlap between
A's and B's `after_window_duration_ms` interquartile ranges) — any future
rule built on these signals would need its own full success-gate
evaluation, including under-segmentation, exactly like Stage 8.3's.

**REJECTED ALTERNATIVES**: treating `delta_t_ms`'s pooled AUC as
meaningful without the session-robustness check (rejected once the
41.3% agreement rate surfaced — this is the check's intended catch);
treating `density_after` as an independent second signal alongside
`after_window_duration_ms` (rejected — both measure the same
post-transition-pace concept via different arithmetic, and reporting
them as independent would overstate the evidence).

Claude Code implemented `rule4_forensics.py`, the 13 tests,
`analyze_rule4_errors.py`, ran the full Dataset A investigation including
the session-robustness addendum, and reported every signal honestly
(including the ones rejected). I required the exact same threshold and
rule application be reused (not re-derived), required a session-level
robustness check specifically to prevent a pooled-only false positive,
and required rejected signals to be reported alongside accepted ones
rather than only the favorable findings.

### Status

Stage 8.4 complete. Two candidate signals (cross-model agreement,
post-transition tempo) identified with genuine, robust, non-redundant
separation — real evidence, not a null result, but not decisive on
their own. No rule implemented, no Stage 8.3 behavior changed. Next
step (whether/how to test these signals in a future, fully-gated
experiment) is **Planned**, pending the project owner's decision.

### Stage 8.5 — Controlled Protection Experiment

**QUESTION**: can Stage 8.4's two signals (cross-model agreement,
post-transition tempo) protect some of Rule 4's 296 wrongly-demoted real
boundaries without giving back too much of its 3,667-false-boundary
reduction?

**HYPOTHESIS**: given Stage 8.4's finding that agreement is satisfied by
90.9% of the very population it would need to selectively protect,
agreement alone was expected to be too blunt an instrument; tempo, being
more continuously distributed, was expected to allow a more selective
trade-off.

**EXPERIMENTAL DESIGNS**: Strategy Agreement (protect if flagged by both
V1 and V2), Strategy Tempo (protect if `after_window_duration_ms` ≥ a
selected threshold), Strategy Combined (both conditions). Implemented as
a strictly additive post-processing layer (`protected_boundary.py`) over
Stage 8.3's own, unmodified `apply_design2_rules` output — eligible only
for transitions Rule 4 itself demoted; Rules 1–3 and the candidate union
untouched. Confirmed by re-running Stage 8.3's original script afterward:
identical results (F1 0.253/0.240/0.304/0.308, frag% 90.6/94.7/77.6/77.9)
— Stage 8.3 behavior is unmodified and still reproducible.

**THRESHOLD-SELECTION METHOD**: reused Stage 7's exact grid method
(`build_threshold_grid`) on pooled `after_window_duration_ms` values
across all 4,774 Rule-4-demoted candidates (296 true, 4,478 false),
selecting via max protection-F1. This is a **global, pooled, out-of-fold
analytical threshold** using all-session Dataset-A evidence at once —
the same validation strength as Stage 6/7/8.3's own threshold choices,
explicitly NOT nested/cross-fitted and NOT selected per session. Selected
τ = 4,680.3ms (protection P=0.335, R=0.696, F1=0.452).

**EVIDENCE**:
- Strategy Agreement protects 3,302 candidates (269 true, 3,033 false;
  ratio 11.28:1) — recovers 90.9% of Rule 4's errors but sacrifices 82.7%
  of its correct removals. Pooled fragmentation lands at 93.0% — worse
  than V1's own 90.6%, i.e. essentially reverting Design 2's gain.
  Fragmentation worsens in 62/63 sessions (mean −15.1pp, max −48.6pp).
- Strategy Tempo protects 615 candidates (206 true, 409 false; ratio
  1.99:1) — recovers 69.6% of errors, sacrifices only 11.2%. Pooled:
  recall 0.520→0.643, under-segmentation 0.204→0.133 (−35%), fragmentation
  77.6%→79.9% (still far below V1/V2's 90.6/94.7%), F1 0.304→0.339 (best
  of all six systems). Under-segmentation improves in 63/63 sessions;
  fragmentation cost averages only −2.1pp/session.
- Strategy Combined protects 452 candidates (193 true, 259 false; ratio
  1.34:1) — recovers 65.2%, sacrifices 7.1%. Pooled: recall 0.636, F1
  0.344 (highest of all six), fragmentation 79.1%, under-segmentation
  0.141 (−31%). Fragmentation cost averages −1.4pp/session.
- All three strategies improve under-segmentation and recall in every
  session that changes at all (0 sessions worsened on either metric) —
  the difference between Agreement and the other two is entirely in how
  much fragmentation they give back, not in whether the improvement is
  broad.

**SUCCESS GATE**: Strategy Agreement **fails** 3 of 7 conditions
(fragmentation-gain retention, not-recreating-V1/V2, false:true ratio) —
explicitly rejected. **Strategy Tempo and Strategy Combined both pass
all 7 conditions.**

**DECISION**: report this as a genuine, evidenced improvement over
Design 2 — not a complete fix (under-segmentation 0.133–0.141 remains
roughly double V1's own 0.085). Neither strategy is adopted as the final
architecture in this stage; per instruction, this is reported as
evidence that these signals are worth carrying into a next-candidate
reconstruction version, a decision left to the project owner. Tempo and
Combined are a close, genuine trade-off (Combined: better false:true
ratio and smaller fragmentation cost; Tempo: more errors recovered,
marginally higher recall) — not a case where one clearly dominates,
stated as such rather than picking one arbitrarily.

**REJECTED ALTERNATIVES**: assuming Strategy Combined would automatically
outperform the single-signal strategies (checked directly — Combined and
Tempo are nearly tied, and Combined is not uniformly better); using
`density_after` alongside `after_window_duration_ms` in the tempo
condition (rejected — Stage 8.4 already found these measure the same
underlying "tempo" concept via different arithmetic; adding both would
not add independent evidence and risks edging toward a weighted
composite, i.e. Design 3, which remains out of scope).

Claude Code implemented `protected_boundary.py`, the 16 tests,
`run_protected_boundary_experiment.py`, ran the full Dataset A
experiment including the mandatory session-robustness breakdown, and
verified Stage 8.3 remains byte-identical and reproducible. I approved
the three strategies to test, required the threshold to be selected the
same way Stage 7 selected its own, required the success gate to include
a session-breadth condition (not just pooled numbers), and required an
explicit statement of which strategy is closer to "best" rather than a
premature architectural commitment.

### Status

Stage 8.5 complete. Strategy Tempo and Strategy Combined both pass the
full success gate — a real, evidenced, partial improvement over Design 2
(recall and F1 up, under-segmentation down ~31-35%, most of the
fragmentation gain retained). Strategy Agreement is rejected. No
architecture change made; Stage 8.3 remains the implemented baseline.
Next decision (whether to adopt Tempo or Combined as the next
reconstruction candidate, refine further, or pursue a different
direction) is **Planned**, pending the project owner's review.

## Day 2 closing — Architecture lock (Tempo vs. Combined, final decision)

**QUESTION**: Stage 8.5 left Tempo and Combined both passing the success
gate without picking one. Before closing Dataset-A work and moving to
Dataset B, I needed one controlled, apples-to-apples comparison between
them, plus a check that the decision doesn't hinge on one fragile
threshold value.

**WHY THIS MATTERS**: I'm about to freeze this pipeline and apply it
unchanged to Dataset B, which has no ground truth to fall back on if the
choice turns out to be wrong. I wanted the decision to survive an
interview question like "why this one and not the other," not just "it
had a slightly higher F1."

**HYPOTHESIS**: going in, I expected this to be close — both strategies
passed the same 7-condition gate in Stage 8.5 with similar pooled
numbers (F1 0.339 vs 0.344). I did not assume Combined would win just
because it uses two signals instead of one; a conjunction of two
moderately-reliable signals (AUC 0.62–0.71 each, per Stage 8.4) isn't
automatically better than either alone.

**EXPERIMENT**: I reused the exact same held-out V1/V2 LOSO pipeline and
the exact same Design 2 + protection code from Stages 8.3–8.5 (no new
classifier, no new feature, no Design 3, no per-session tuning) and ran
both strategies at the already-selected threshold (τ=4,680.3ms) with an
extended metric set: global precision/recall/F1/fragmentation/
under-segmentation/over-segmentation, per-session mean/std/min/max/IQR,
a session-by-session Tempo-vs-Combined comparison, and a GT-execution-
level comparison (does a given execution fragment under one strategy but
not the other?). Then I ran a sensitivity sweep over the 9 threshold-grid
points nearest the selected value (the same grid Stage 8.5 already
built — not a new search) to check whether the ordering between the two
strategies holds up or flips near the selected threshold.

**EVIDENCE**:
- Pooled: Tempo R=0.6433 F1=0.3393 frag=79.85% under=0.1332; Combined
  R=0.6355 F1=0.3440 frag=79.05% under=0.1412. Close, as expected.
- Session-level: on fragmentation, Combined is strictly better or equal
  in **all 63 sessions** — 0 sessions where Tempo fragments less than
  Combined. On under-segmentation, Tempo is better in 52/63 sessions.
- GT-execution level (1,752 executions): 1,385 fragment under both, 353
  fine under both, **14 fragment only under Tempo, 0 fragment only under
  Combined** — a one-directional result, not noise.
- Sensitivity: across the 9 nearest grid points to the selected
  threshold (τ from 4,031 to 5,652ms), **Combined's F1 was ≥ Tempo's F1
  at every single point (9/9)** — the ordering isn't an artifact of the
  one selected value.

**DECISION**: I selected **Strategy Combined** as the locked Rule-4
protection strategy. This was not "pick the higher F1" — the F1 gap is
small (0.344 vs 0.339) and I checked it for robustness rather than
trusting it at face value. What decided it was the one-directional
dominance on fragmentation (Combined is never worse, in any session or
execution) plus the better false:true protection ratio (1.34:1 vs
1.99:1 from Stage 8.5) plus the stable F1 edge across the sensitivity
neighborhood. I'm keeping Tempo as the documented alternative, not
discarding it — if a future priority weighs under-segmentation reduction
above fragmentation, Tempo is the evidence-backed fallback, since it
does have a real, consistent edge there (52/63 sessions).

**ARCHITECTURE LOCKED**: candidate set = V1 ∪ V2 (union, demote-only);
Rules 1–4 exactly as Stage 8.3 defined them, unmodified; Rule 4's
protection layer = Strategy Combined (flagged by both models AND
`after_window_duration_ms` (N=10) ≥ 4,680.2613ms). All four thresholds
(0.9078, 0.8860, 0.40, 4,680.2613) are global, pooled, out-of-fold
analytical selections over Dataset A — none nested/cross-fitted, none
per-session. This is the exact pipeline documented in
`reports/day2/segmentation_architecture_final.md` and
`reports/day2/final_architecture_dataset_a.json`, to be applied
unchanged to Dataset B.

**REJECTED ALTERNATIVES**: picking Tempo by default for simplicity
(rejected — Combined's dominance on the primary fragmentation objective
and better protection ratio outweighed the small complexity difference
of a two-condition rule); treating the close F1 gap as decisive on its
own without the session/execution/sensitivity breakdown (rejected —
that would have been exactly the kind of numerically-driven, unverified
call I wanted to avoid before locking a pipeline I can't re-tune against
Dataset B).

I set the comparison's scope (no Design 3, no new classifier, no new
feature, reuse the existing LOSO pipeline exactly) and made the final
Tempo-vs-Combined call myself from the evidence above. AI was used to
accelerate implementation of the comparison script, the sensitivity
sweep, the regression tests, and the consolidated final report —
architectural direction and acceptance criteria were mine throughout Day
2, including this final decision.

**KNOWN LIMITATION, STATED HONESTLY**: Combined does not fully solve
fragmentation — under-segmentation (0.141) remains roughly double V1's
own rate (0.085). This is a real, partial improvement over Design 2, not
a finished architecture. Recorded as such, not oversold.

### Status — Day 2 closed for Dataset A

Final Dataset-A segmentation architecture locked: Design 2 + Strategy
Combined protection, exact thresholds and rules documented in
`segmentation_architecture_final.md`. 206 tests passing (194 prior + 12
new architecture-lock tests). Dataset B confirmed untouched throughout
(no file read, loaded, profiled, or referenced computationally). Next:
Day 3 — apply the locked pipeline's contract to Dataset B (first
authorized Dataset B use), then Step 2/3 of the assignment (automation
opportunity analysis, prototype). No commits or pushes made — the
engineer handles all Git operations.

## Day 2 closing — Segment-level coherence forensics (hypothesis test, before Dataset B)

Before actually moving to Dataset B, I wanted to check one more thing:
Combined still leaves 79.05% of GT executions fragmented, and every
rule I'd built so far (Rules 1–4, the Tempo/Combined protection layer)
makes its decision using either a single adjacent event pair or a
*fixed* 10-event window. I tested whether looking at the real,
variable-length segment on each side of a candidate — not a fixed-N
proxy — would find a materially better signal for telling the
remaining false boundaries apart from the correct ones.

**HYPOTHESIS**: a remaining class of false boundaries is detectable by
asking a segment-level question ("if this boundary were removed, would
the merged segment look like one coherent execution?") rather than only
a transition-level one — via trajectory-similarity Jaccards
(event-type, interaction-category, application, browser-domain) and
activity-rate continuity computed over the *actual* left/right
fragments implied by the current final-boundary set.

**EXPERIMENT**: I did not retune V1, V2, Rule 4, or the tempo
threshold — I re-ran the exact locked pipeline and confirmed it
reproduced the locked numbers exactly (R=0.6355, F1=0.3440, frag%=79.05,
TP=1062/FN=609/FP=3441) before doing anything new. I split Combined's
4,503 kept boundaries into Population T (1,062 correct) and Population F
(3,441 still-wrong, the target of this hypothesis), built a new
diagnostic-only module (`segment_coherence.py`) to compute the real
segment bounds and the coherence signals over them, and ran the same
AUC + per-session-direction-consistency discrimination test Stage 8.4
used, against both the new segment-scoped signals and the existing
fixed-N=10 baselines already in production, on this same population.
I pre-registered the decision gate (discrimination ≥0.10 separation,
session agreement ≥75% over ≥15 sessions, a genuinely new signal
family, and ≥0.03 better separation than the best existing baseline)
in the script before running it against the data.

**EVIDENCE**: the signals that actually operationalize the coherence
hypothesis were the *weakest* in the whole comparison —
`segment_event_type_jaccard` (separation 0.045), interaction-category
(0.025), application (0.060), browser-domain (0.064); only
`rate_continuity_ratio` (0.107) even cleared the 0.10 bar, and it still
trailed every existing fixed-N=10 feature. The strongest signal
overall, `right_n_events` (fragment length after the boundary,
separation 0.250), isn't a coherence measurement — it's a restatement
of "this false boundary sits inside an already-fragmented execution, so
the piece after it tends to be short," which doesn't reliably
distinguish "should merge" from "genuinely a short execution." It also
missed my own pre-registered non-redundancy bar against the best
existing baseline (0.250 vs. 0.221, needed +0.03, got +0.029) — a
near-miss, not a clear failure, but a failure against the bar I set
before I saw the numbers. I also confirmed mechanistically why
`event_type_jaccard_n10` (Stage 8.4's own strong signal) has lost most
of its power here: 80%+ of this remaining population sits in Rule 4's
"isolated candidate, kept" branch, which by construction only contains
jaccard values below 0.40 — the feature is saturated in exactly the
population where I was hoping it still had headroom.

**DECISION**: I rejected the segment-level coherence hypothesis and did
not implement Experiment 7's ablation — the pre-registered gate did not
pass, so no new rule was designed, thresholded, or evaluated. This is
not a null result I'm hiding — the near-miss on `right_n_events` is
reported in full in `segment_coherence_forensics.md` — but a
0.03-short, mechanistically-unrelated signal is not sufficient
justification for a new production rule, and I said before running this
experiment that I would stop rather than keep searching if the evidence
didn't clearly support one.

**ARCHITECTURE UNCHANGED**: Design 2 + Strategy Combined protection
remains the final Dataset-A architecture, exactly as locked. AI was
used to accelerate implementation of `segment_coherence.py`, the
analysis script, the regression tests, and this write-up; I set the
hypothesis, the pre-registered decision gate, and made the final
reject/accept call myself from the evidence above.

### Status — Day 2 permanently closed for Dataset A

220 tests passing (206 prior + 14 new `test_segment_coherence.py`
tests). Dataset B confirmed untouched throughout this investigation
too. No further Dataset-A architecture experiments are planned — the
locked pipeline (Design 2 + Strategy Combined) is what will be applied,
unchanged, to Dataset B on Day 3. No commits or pushes made.

## Day 2 — Global sequence-optimization hypothesis (research detour before Dataset B)

**Observation:**
I noticed that every rule I'd built so far — V1/V2's per-transition
classification, Design 2's Rules 1-4, the Tempo/Combined protection
layer — decides one transition (or a fixed 10-event window around it)
at a time. Combined still leaves 79.05% of executions fragmented, and
the segment-coherence experiment I ran right before this one had
already ruled out one specific fix (cross-segment trajectory
similarity). That made me want to step back and question something more
basic about the formulation itself, not just add another local rule.

**Reasoning:**
The previous experiments suggested that independent, transition-local
decisions are fundamentally where the over-segmentation comes from — a
business-process execution is a coherent sequence, not something
defined by any single transition. Design 2's neighborhood rules and the
protection layer both widened the decision window, but always to a
fixed size. I wanted to know if the right fix wasn't a wider window but
a different kind of objective entirely.

**Question:**
I asked whether segmentation should be formulated as a global sequence-
optimization problem — choosing the entire boundary set at once to
minimize a total-incoherence-plus-complexity-penalty objective — rather
than as independent per-transition classification.

**Hypothesis:**
I hypothesized that a segmentation should minimize
`Σ C(segment) + λ|boundaries|`, where `C(S)` is an interpretable,
GT-free measure of a segment's internal incoherence, and that for a
candidate boundary, comparing `C(SL) + C(SR) + λ` (keep split) against
`C(SL ∪ SR)` (merge) would identify real boundaries better than a
per-transition score.

**Method:**
I ran this as a forensic feasibility study before writing any
optimizer, exactly as I'd planned. I built four intra-segment
incoherence components from fields already in production (event-type
and interaction-category entropy, an internal context-switch rate, and
gap-time coefficient of variation) — deliberately not new feature
families, just existing fields aggregated within a segment instead of
across one transition. I tested each component alone first (on the
8,976-candidate union set, after excluding the already-solved chunk/
noise artifacts) before ever combining them, defined the split-vs-merge
sign convention explicitly myself rather than trust the algebra I'd
first sketched (it turned out to be internally inconsistent once I
pinned down what "cost" meant), combined only the components that
actually cleared a discrimination/robustness bar using an unweighted,
data-driven z-score sum (not hand-tuned weights), and selected λ via
the same pooled-grid, max-F1-subject-to-recall-floor method I've used
for every threshold since Stage 7. I pre-registered the go/no-go gate
for building the dynamic-programming prototype before running the
script against the data.

**Evidence:**
Three of four components discriminated real boundaries from false
candidates and held up across all 63 sessions — but in the opposite
direction from what I expected: real boundaries had *lower* merged-
segment entropy than false ones, not higher. Digging into why (a
separate purity check: segments that silently merge two real executions
do show higher entropy, as expected), I found the reversal traces to a
segment-length confound — raw entropy and gap-CV both grow with segment
size regardless of whether the content is one task or two, and false
candidates happen to sit inside longer, already-fragmented stretches.
Combining the three components largely canceled this out rather than
reinforcing it: the composite split-vs-merge score reached only 0.080
separation (below my 0.10 bar) and its best-F1 classifier (0.331) did
not beat Rule 4's own existing feature evaluated on the identical
population (0.365).

**Decision:**
Therefore I rejected the global-optimization hypothesis and did not
build the dynamic-programming prototype — two of my four pre-registered
gate conditions failed, and building the optimizer anyway just to see
would have been exactly the kind of "keep adding complexity until it
works" behavior I'd already ruled out for myself. I'm keeping the
segment-length confound finding on record since it's a real, useful
piece of engineering knowledge if this direction ever comes up again,
but it doesn't change today's decision. Design 2 + Strategy Combined
remains the final Dataset-A architecture, unmodified.

**AI contribution:**
AI was used to accelerate implementation, experiment execution,
analysis, and testing; the engineering hypothesis, evaluation criteria,
and final decision were reviewed and owned by me.

### Status — Day 2 remains closed for Dataset A

234 tests passing (220 prior + 14 new
`test_global_segmentation_forensics.py` tests). Dataset B confirmed
untouched. `reconstruction.py` and `protected_boundary.py` were not
modified — the DP/Combined-comparison code path that would have
imported them was never reached. Next: Day 3, apply the locked
Design 2 + Strategy Combined pipeline to Dataset B unchanged. No
commits or pushes made.

## Day 3 — Dataset B process discovery, HR/Payroll selection, and the automation prototype

**Question:** with Dataset A's segmentation architecture locked, what
does Dataset B actually contain, and which real, repeated piece of work
in it is the strongest, most evidence-backed candidate to automate
first?

**Reasoning:** I explicitly did not assume Dataset A's segmentation
approach — or any of its findings — would transfer to Dataset B.
Dataset B has no ground-truth execution labels at all, so I treated it
as production-style, unlabeled data throughout and required every claim
about it to trace to something directly observed in the raw events, not
inferred from Dataset A's patterns.

**Profiling first:** I profiled Dataset B before building anything —
15 sessions, 4 operators, and (this mattered a lot for what came next)
essentially no large time gaps anywhere in the data, unlike Dataset A.
That single finding told me a gap-threshold segmentation approach
(which Dataset A's whole investigation was built around originally)
would not find structure in Dataset B, so I didn't start there.

**Building the boundary/execution logic fresh:** I built a
`system_identity`-based boundary signal for Dataset B from scratch,
grounded in window titles and DOM evidence rather than time gaps. My
first version used `browser_domain` as the primary signal (it had
mattered most for Dataset A), and running it against real data
immediately produced obviously broken output — thousands of near-zero-
length segments. I dug into why and found `browser_domain` is often
null in Dataset B even when the window title clearly names the active
system; I rebuilt the signal around window titles instead, and it
produced sensible, readable segments. I'm recording this here
deliberately: the first design was a real, wrong guess, caught only by
checking it against the data rather than trusting it because it worked
for the other dataset.

**Process/priority discovery:** I grouped the resulting executions into
named processes and variants, then ranked them with a transparent,
normalized priority score (equal-weighted by default, since Dataset B
gives me no labeled outcome to fit weights against) and ran a
sensitivity sweep across several alternate weightings. HR/Payroll came
out #1 under the default weighting and two of the four alternates; I
reported honestly that it isn't #1 under every weighting tested (two
near-zero-volume Excel workbooks edge it out under a risk-averse
weighting) and explained why that doesn't change my recommendation —
those workbooks "win" mainly because they have almost no volume to
carry any risk.

**Forensic deep-dive on the winner:** before designing any automation,
I did a focused, event-level reconstruction of HR/Payroll's dominant
path specifically. First pass reverse-engineered execution boundaries
from timestamp ranges in the already-written JSON, and a cross-check I
ran specifically to catch this kind of error found it silently
misattributing events for 16 of 94 executions at exact-millisecond
boundary collisions. I fixed this by rebuilding execution boundaries
from the same index-based pipeline that produced the JSON in the first
place, rather than reverse-engineering from timestamps, and verified a
0/645 mismatch before trusting anything downstream. The forensic
result: 94/122 (77.05%) of HR/Payroll executions follow one dominant,
DOM-evidenced pattern (navigate to one of four routes, paste a note,
click confirm), with real structured evidence for it — 100% of observed
form inputs were paste operations, and the note-field/confirm-button
click pairing is nearly exactly 1:1 (139 vs. 138) across 94 independent
executions.

**Choosing the automation form:** RPA/UI automation, not an API
integration and not an AI agent, decided directly from what the logs do
and don't show — no API call was ever evidenced (inventing one would be
fabricating business logic I have no evidence for), and no
judgment-requiring or unstructured-content step appears inside the
dominant path itself (that's the Word-detour variant, which I scoped
out of this prototype entirely, not partially automated).

**Building the prototype:** I scoped the automation to exactly the
evidenced boundary — navigate, verify the note field, insert the note,
verify the confirm button, then a mandatory human-review checkpoint
before a separate, deliberate confirmation call. I built a small,
dependency-free mock HR application (no new third-party dependency —
checked what's installed first, nothing for browser automation was
available, and I judged that adding one just to prove the automation
*logic* works wasn't justified) with deliberate fault injection so
every required failure mode could be tested without a real, unpredictable
target. Going back through the safety requirements a second time, I
found two gaps in my first version: it didn't reject an empty/whitespace
note before touching the UI at all, and it clicked the confirm button
from a cached reference instead of re-verifying it was still there right
before clicking — meaning a DOM change during the human-review pause
would have gone undetected. I fixed both (new `InvalidNoteError` and
`ConfirmationFailedError`, tested with 8 new test cases) before calling
the safety model complete.

**What I did not do:** I did not invent an API endpoint anywhere in this
prototype. I did not claim the mock application is the real HR system —
it's banner-labeled as a prototype/demo everywhere, including in the
generated HTML page. I did not project any specific hours-saved or
dollar figure — Dataset B has no production-volume or cost data to
support that, so the ROI section states the formula a real estimate
would need and what measurements are missing, rather than making one up.
I did not touch Dataset A's locked segmentation architecture anywhere in
this work.

**AI contribution:** implementation was AI-assisted using Claude Code —
the segmentation-signal code, the process-discovery pipeline, the
forensic scripts, the mock application, the automation layer, and the
test suites were all AI-implemented. I directed the investigation
(what to profile, in what order), formed the hypotheses that turned out
wrong and needed correcting (the browser_domain signal, the timestamp-
range reconstruction), set the evaluation criteria (the priority-score
weighting discipline, the automation boundary), and made the final
scope and architecture decisions (HR/Payroll as the candidate, RPA over
API/AI-agent, exactly which four routes and which failure modes are in
scope). Claude Code is not being credited with deciding what mattered;
it accelerated building and testing what I decided mattered.

### Status — Day 3 prototype complete

369 tests passing (361 prior + 8 new for empty-note validation and
confirmation-time re-verification). Dataset A's locked architecture
(`src/procmine/segmentation/`) was not read or modified. Dataset B was
read-only throughout. Deliverables:
`reports/day3/dataset_b_profile.md`, `process_discovery.md`,
`hr_payroll_dominant_path_analysis.md` (+ its JSON artifact),
`automation_candidate_analysis.md`, and
`hr_payroll_automation_prototype.md` (+ the generated demo HTML page).
Git commits for Day 3 are being handled by me directly, not by Claude
Code, per my own instruction partway through this stage.

## Day 3 (continued) — questioning my own Problem-2 scoring before finalizing it

**Why I did this:** the 8-factor priority score I'd built for Problem 2
(frequency, time, manual effort, repetitiveness, feasibility, business
impact, risk, complexity, all blended additively with two subtracted
penalties) worked, and it did pick HR/Payroll — but it was a scoring
scheme I designed myself, ad hoc, without checking it against anything
more standard. Before treating "HR/Payroll is #1" as settled going into
Problem 3, I wanted to know whether a more conventional process-mining
treatment — the kind of thing an actual process-mining tool would do
(trace abstraction, a directly-follows graph, variant similarity,
entropy, impact kept separate from feasibility instead of blended) —
would agree with my own scoring, or expose that I'd built something
that only looked reasonable because I hadn't compared it to anything.
I did not go into this assuming the fancier approach would win; I went
in specifically to try to break my own earlier conclusion.

**What I tested:** I built a trace abstraction at two granularities
(system-level, which turned out to just be the variant-signature I
already had, and a finer system+interaction-category level), a
directly-follows graph, three different sequence-similarity measures
(normalized edit distance, LCS, Jaccard), variant entropy, and a
genuinely different scoring structure — Impact and Feasibility computed
as two separate, named quantities and only multiplied together at the
end, instead of my old approach's one blended additive sum. I ran the
whole thing over the real Dataset B process population (21 candidate
processes), not just HR/Payroll, specifically so I couldn't be accused
of tuning the method to reproduce the answer I already wanted.

**What the comparison actually showed:** the DFG and the similarity
investigation mostly *confirmed* what the exact-match variant grouping
had already found — they didn't overturn anything, they gave me a
second, more standard way to see the same structure (e.g. the DFG shows
every detour from HR returns to HR with probability 1.000, which lines
up with what I already knew about the Word-detour always closing the
loop). The one number that gave me pause was a very high correlation
(0.977) between execution count and total duration across processes —
a real sign that frequency and time aren't as independent as I'd been
treating them, in both my old scoring and the new one. And when I first
ran the new sensitivity sweep, HR/Payroll looked #1 in every scenario I
threw at it — which made me suspicious rather than pleased, because my
*old* scoring's own sensitivity sweep had let two tiny Excel workbooks
overtake HR/Payroll under a risk-averse weighting. I went back and
built an equivalently adversarial scenario for the new scoring instead
of accepting a result that just happened to look better than my
earlier one. Once I did, the same displacement happened again — a
volume-de-emphasizing weighting lets those same small, simple workbooks
win under the new method too (HR dropped to rank 4, then 6). That told
me the earlier "new method is more stable" impression was really just
me not having tried hard enough to break it, not a real property of the
new formula.

**What I decided:** AUGMENT, not replace, and not just keep the old
approach unexamined either. The new methodology earned its place — the
Impact/Feasibility separation is genuinely more explainable than my old
8-factor blend (I can now say exactly *why* a process ranks where it
does, not just that it does), and the correlation check is a real,
useful caveat I hadn't checked for before. But it didn't produce a
different top candidate, and once I tested it fairly (not just under
scenarios convenient to it), it didn't show categorically better
ranking stability than what I already had either. Replacing a working,
already-validated pipeline on a result that only looked better because
I hadn't stress-tested it the same way would have been the wrong call.
HR/Payroll remains the Problem-3 candidate, on stronger and more
carefully-checked grounds than before, not because I forced the numbers
to agree with my earlier work.

**AI contribution:** implementation was AI-assisted using Claude Code —
the trace/similarity/DFG/scoring modules, the analysis script, and the
test suites were AI-implemented. I directed which methods to test
(edit distance, LCS, and Jaccard specifically, not a larger menu),
required the correlation/double-counting check the assignment's own
instructions called for, caught myself accepting a too-convenient
"new method is more stable" result and required an equivalently
adversarial sensitivity scenario before trusting it, and made the
final AUGMENT decision myself from the comparison.

### Status — Problem 2 investigation complete, Problem 3 unchanged

421 tests passing (369 prior + 52 new for the process-mining modules).
Decision: **AUGMENT current approach** — HR/Payroll remains the
Problem-3 candidate, ranked #1 by both the original and the new
methodology, under the default weighting and 9 of 12 sensitivity
scenarios tested (vs. 3 of 5 for the original approach — a real but
modest difference, not claimed as decisive). Problem 1 (Dataset A's
locked segmentation architecture) was not touched. The HR/Payroll
automation prototype is unchanged and remains consistent with this
conclusion. New report: `reports/day3/problem2_process_mining_analysis.md`
+ `problem2_process_metrics.json`. Git commits for Day 3 remain mine to
create, not Claude Code's, per my standing instruction.

---

# DAY 3 — PROBLEM 2: PROCESS ANALYSIS AND AUTOMATION PRIORITIZATION (final audit)

## 1. Starting point

After Problem 1 (Dataset-A segmentation) was locked, I moved to
Dataset B and asked the actual Problem-2 question: given the recovered
executions, where does automation look most impactful? I didn't start
with a scoring formula — I started the way the earlier entries in this
log already show: group executions, look for repeated patterns, measure
frequency/time/manual work by hand, and dig into whatever candidate
looked promising. That direct approach is what found HR/Payroll in the
first place.

## 2. Initial finding (recap — full detail in the entries above)

94/122 executions (77.05%) followed one dominant, DOM-evidenced path
(HR system → route → note → paste → confirmation); 24/122 (19.7%) were
a Word-detour variant; ~4/122 (3.3%) were rare multi-hop cases. High
concentration, but I was clear with myself even then that concentration
alone doesn't prove it's the *best* automation target, just a real,
repeatable one.

## 3. My Problem-2 question, restated for this final pass

Before treating any of this as settled going into Problem 3, I wanted
one more, stricter pass: not "does my scoring agree with itself," but
"if I actually try to break my own ranking — check the math for real
errors, test redundancy properly, check whether HR is genuinely
undominated rather than just highest-scoring, and see how far a
reasonably adversarial weighting can push it — does HR/Payroll still
hold up, and do I actually know *why*?"

## 4. Mathematical audit — one real bug found

I re-checked every formula in `opportunity_scoring.py` rather than
assuming last turn's code was correct because it had already run once.
Most of it held up: normalization direction was right everywhere
(risk, complexity, and entropy are all correctly inverted before being
added as feasibility contributions), constant-column handling was
already correct (maps to 0.5, not 0, when nothing in the set differs).
But `variant_entropy` itself had a real problem: it returns raw
Shannon-entropy bits, and raw bits aren't comparable across processes
with *different numbers of variants* — a process with 7 variants has a
higher ceiling (log2(7)) than one with 3 (log2(3)), so a moderately
skewed 7-variant process can show *higher* raw entropy than a genuinely
more evenly-used 3-variant one. I checked this wasn't theoretical by
computing it on the real data: "Word: Contract Termination Procedure"
(7 variants) showed raw entropy 2.195, higher than "Word: New Contract
Procedure" (3 variants) at 1.500 — even though the 3-variant process is
actually more evenly spread relative to its own maximum (94.6% of its
ceiling vs. 78.2%). That's a genuine mathematical error feeding into a
cross-process comparison, not a style preference, so I fixed it: added
normalized entropy (H / H_max, bounded 0–1 regardless of variant count)
and switched Feasibility to use it. It moved real numbers — HR's own
Feasibility went from 0.453 to 0.477, and Financial Accounting swapped
ranks 4 and 5 with an Excel workbook as a direct consequence.

## 5. Separating impact from feasibility — kept, re-verified sound

I didn't change the Impact/Feasibility separation itself this pass —
it was already the right idea (a process can consume a lot of time
while being poorly suited to automation, or vice versa) and nothing in
this audit gave me a reason to collapse it back into one blended score.
What I did check, freshly, is whether Feasibility was quietly becoming
a "how much I like this process" score in disguise — it isn't:
HR/Payroll is my Impact leader (0.924) but explicitly *not* my
Feasibility leader (0.477, versus 0.92–0.95 for the two Excel
workbooks) — the model keeps saying that out loud instead of hiding it
behind one number, which is exactly what I wanted from separating them
in the first place.

## 6. The redundancy question, tested properly this time

Last pass I noted the 0.977 correlation between execution count and
total duration and reasoned informally that it "probably doesn't
matter much." This time I actually tested that claim instead of
asserting it: I built four different Impact formulations (frequency +
total duration; frequency + average duration; total duration + average
duration; and frequency + manual-effort only, with duration dropped
entirely). Three of the four keep HR at #1 with high rank agreement
(Spearman ≥ 0.977) — genuinely reassuring, since it means the exact
pairing of volume/duration signals doesn't matter much. But the fourth
one — dropping duration entirely — knocks HR down to rank 3. That told
me something I hadn't actually confirmed before: HR's advantage is
substantially carried by the *time* signal specifically, not by raw
frequency or manual-effort rate on their own. I recorded that plainly
rather than treating three-out-of-four agreeing as enough to call the
question closed.

## 7. Sensitivity analysis, done stricter this time

The prior sensitivity sweep used a looser scenario grid and reported
HR at #1 in 9 of 12 combinations. For this audit I built the eight
scenarios the task actually asked for, one axis varied at a time
(balanced, frequency-heavy, time-heavy, manual-effort-heavy,
feasibility-heavy, risk-averse, volume-deemphasized, and a
"correlation-aware" scenario that explicitly down-weights frequency and
time together instead of double-counting them). Under this tighter set,
HR is #1 in only 5 of 8 — and the three that displace it
(manual-effort-heavy, volume-deemphasized, correlation-aware) all share
the same mechanism: each one reduces how much weight the model puts on
the time/volume signal HR wins on, which lines up exactly with what the
redundancy test in the previous section already showed. I want to be
honest about why the two numbers (9/12 vs. 5/8) differ: it isn't that
the new run is more pessimistic for no reason, it's that this run is a
more targeted test, including two scenarios (manual-effort-heavy,
correlation-aware) the earlier sweep never tried. A stricter test found
a real vulnerability the looser one missed, and reporting only the
looser number would have been misleading even though it wasn't wrong
at the time I ran it.

## 8. Ablation — which components actually carry HR's ranking

I removed one scoring component at a time from the full model to see
which ones were doing real work versus just adding complexity. Only two
removals change HR's own rank: taking out frequency (HR falls to 2) or
taking out time (HR falls to 3) — matching sections 6 and 7 from a
third, independent angle. Every Feasibility-side component
(determinism, entropy, automation surface, risk) leaves HR at #1 when
removed individually, even though removing manual-effort causes the
single biggest disturbance to the *overall* ranking of all 21
processes (rank correlation 0.896 vs. the full model, the lowest of any
single removal). That told me manual effort matters a lot for the
population as a whole, just not specifically for whether HR stays on
top — a distinction I wouldn't have seen without doing the ablation
one component at a time instead of just eyeballing the formula.

## 9. Pareto analysis — the one result that doesn't depend on weighting

Everything in sections 6–8 depends on how the score is weighted. I
wanted at least one piece of evidence that didn't. A Pareto frontier
over (Impact, Feasibility) doesn't need weights at all — a process is
either dominated by another (equal-or-better on both axes, strictly
better on at least one) or it isn't. Only 3 of 21 processes are
non-dominated: HR/Payroll, Order & Inventory, and Excel: Budget
Analysis. HR/Payroll is one of them — genuinely, not because I put it
there. That's the strongest single piece of evidence in this whole
audit, because it's the one claim that survives regardless of which
sensitivity scenario or redundancy formulation someone prefers.

## 10. Old vs. new decision, and why it's still AUGMENT

The enhanced methodology did not produce a different top candidate that
survives scrutiny — Excel: Budget Analysis only wins under scenarios
and formulations that deliberately discount the time signal, and it has
no equivalent to the independent DOM-forensic validation HR/Payroll
already has from the Problem-3 prototype work. So I kept AUGMENT, not
REPLACE. But I also won't pretend this audit made HR's case *stronger*
than I'd previously reported — the honest result is that the more
rigorous test found HR's ranking is *more contested* than the looser
9/12 sweep suggested (5/8 here), while also finding one thing that
isn't contested at all (Pareto non-domination). Both of those are real,
and I'm reporting both rather than picking the one that sounds better.

## 11. Final HR/Payroll status

HR/Payroll never fell below rank 3 in anything I tested — not the
redundancy formulations, not the 8 sensitivity scenarios, not the
per-component ablation, not even winsorized (outlier-capped)
normalization, which also displaces it to rank 2. It's Pareto-
non-dominated, it's #1 under the plain unweighted default, and it still
has the DOM-forensic grounding from Problem 3 that no other candidate
in this population has. That's the case I'm taking into Problem 3 — not
"HR is mathematically optimal," which the evidence doesn't support
unconditionally, but "HR is the strongest evidence-backed candidate in
this Dataset-B population, and I know exactly which assumptions that
conclusion leans on."

## 12. Transition to Problem 3, and Problem-3 status

Problem 2 answers "what should be automated." The DOM forensic work
(already done, unchanged by this audit) answers "which part of that
process is technically bounded and deterministic enough to attempt."
Problem 3 demonstrates "can that bounded part actually be automated." I
re-ran the existing HR/Payroll RPA prototype after this audit
specifically to confirm I hadn't broken anything relevant — all four
routes still complete end to end, the safe-failure case still stops
correctly, and I did not touch `src/procmine/automation/` at all this
pass, per my own rule not to redesign a working prototype without a
real bug driving it.

## 13. AI contribution

Claude Code was used as an implementation and analysis accelerator for
this audit too — the entropy fix, the Pareto/rank-correlation module,
the redundancy/sensitivity/ablation script, and the test suites were
AI-implemented. I directed which formulas to re-check and why, required
the entropy issue to be verified against real data before calling it a
bug rather than a style complaint, specified the exact 8 sensitivity
scenarios and the 4 redundancy formulations to test, required the
Pareto analysis specifically because I wanted at least one
weighting-independent check, and made the final AUGMENT call and the
"HR is the strongest evidence-backed candidate, not the mathematically
optimal one" framing myself, from the comparison.

## 14. Final Day-3 reflection

The main improvement from this whole Day-3 arc wasn't a more
complicated algorithm. It was turning Problem 2 from "which process did
I happen to notice first" into a decision I could actually defend on a
whiteboard — including the parts where the defense is "here's exactly
where this conclusion gets shakier, and here's the one piece of
evidence that doesn't." Because the enhanced approach added real
explanatory and validation value (a genuine bug fix, a clearer picture
of what HR's ranking actually depends on, and a weighting-independent
Pareto check) without producing a decisively better candidate, I
augmented the original methodology instead of replacing it. That's the
final engineering judgment for Day 3.

### Status — Problem 2 final audit complete

448 tests passing (421 prior + 5 for normalized entropy + 22 for the
new Pareto/rank-correlation/winsorization module). One real
mathematical bug found and fixed (unnormalized cross-process entropy).
Decision unchanged: **AUGMENT**. HR/Payroll status: #1 by default,
Pareto-non-dominated, never worse than rank 3 under any tested
perturbation, displaced from #1 under 3/8 stricter sensitivity
scenarios and 1/4 redundancy formulations — reported in full, not
smoothed over. Problem 1 untouched. Problem 3 prototype re-verified
working, not redesigned. New/updated:
`reports/day3/problem2_process_mining_analysis.md`,
`problem2_audit_results.json`. Git remains mine to commit, not Claude
Code's.

## Day 3 — closing the one real gap: `segments.jsonl`

I ran a full audit of the repository against the assignment brief's
own Deliverables section before calling Day 3 done, and it caught a
real, concrete gap: the brief names `segments.jsonl` (Dataset B, one
line per execution, `session_id`/`start`/`end`/`label`) as the actual
Step-1 submission artifact, and it didn't exist anywhere in the repo.
Everything upstream of it did — `process_executions_dataset_b.json`
already has the segmented Dataset B executions from Section 3's
system-change-boundary + leave-and-return pipeline — it just had never
been converted into the exact schema the brief asks for.

I deliberately treated this as a format conversion, not new
segmentation work: no boundary logic runs in the conversion script,
nothing is merged, split, invented, or dropped. `label` reuses the
already-computed `dominant_context` -> `readable_name` mapping from
`process_profiles_dataset_b.json`, so "same process gets the same
label" holds by construction, not by a new rule I had to justify.

One real edge case turned up during validation, not before: 11 of 645
executions are genuine single-event executions where `start_ms ==
end_ms` at millisecond resolution — a real property of the data, not a
bug. The schema requires `start < end`, so I nudged `end` forward by
1ms *in the output timestamp only* for those 11 records, and logged
exactly how many that affected rather than silently rounding the
problem away. I validated the result independently after generating
it (not just trusted the generator's own printout): 645/645 records,
valid JSON, correct schema, all 15 session_ids actually belong to
Dataset B, all timestamps parse and satisfy start < end, no empty
labels, and an exact 1:1 count match against the source executions
file.

### Status — Day 3 complete

453 tests passing (448 + 5 for the new conversion function). New file:
`scripts/build_segments_jsonl.py`, `tests/test_build_segments_jsonl.py`,
and the deliverable itself, `segments.jsonl` (repo root, 645 records).
No segmentation algorithm was touched to produce it. Final submission
report, README rewrite, and Day 4/5 work remain explicitly out of
scope for today, per my own instruction. Git remains mine to handle,
not Claude Code's — no git command was run this session.

---

## Day 4 — Instrumentation Health Review

### Starting Point

Days 1–3 left the Dataset-A segmentation architecture locked (V1 ∪ V2 →
Rules 1–4 → Combined protection, thresholds 0.9078 / 0.8860 / 0.40 /
4680.2613), Dataset B segmented into 645 executions across 21 processes,
HR/Payroll selected as the automation candidate on Impact 0.9236 /
Feasibility 0.4765 / Opportunity 0.4401, and a working RPA prototype for
its four evidenced routes. Day 2 had already tested and rejected a long
list of alternatives — temporal baselines, contextual AND/OR rules,
boundary-first logistic regression, continuity-first V2, threshold
re-selection, reconnection/merge, Design 3, segment-level coherence, and
global sequence optimization — so Day 4 deliberately did not open with a
search for another algorithm.

The day started by re-running the locked protected-boundary experiment
unchanged, to establish that anything measured later could be trusted
against a reproducible reference. It reproduced exactly: all 30 pooled
metrics matching the Day-2 artifact to 1e-12, same selected tempo
threshold, same populations (3667/296), and confusion verified at
TP 1062 / FP 3441 / FN 609, precision 0.235843, recall 0.635548,
F1 0.3440.

### Observation

Looking at the per-session spread rather than the pooled numbers, the
seven worst sessions in Dataset A all come from the same machine,
LAPTOP-R36BQBTE. Mean Combined F1 there is 0.14 against 0.32–0.40 for
every other machine, and mean under-segmentation is 1.28 against
0.06–0.18 — roughly ten times worse, concentrated in one operator's
hardware rather than scattered across the dataset.

### Investigation

Measuring the instrumentation actually available in those sessions
produced a categorical difference, not a marginal one. Six of the seven
carry `browser_domain` on 0.00% of events. The seventh carries it on
58.77% of events but has only one distinct domain, so a domain *change*
can never be observed there either. Normal sessions carry three or four
distinct domains, and those domains are localhost ports — 127.0.0.1:5122,
:5123, :5124 — i.e. different internal business systems distinguished by
port number.

The decisive measurement: on normally-instrumented sessions 96.6% of
ground-truth boundaries coincide with a browser-domain change. On
LAPTOP-R36BQBTE that figure is 0%.

Day 1 had already measured browser navigation as the strongest single
boundary signal (lift 13.98) and noted "one session at exactly 0.0
coverage" as a caveat. The actual scope turns out to be an entire
machine — 11% of Dataset A.

### Alternative Explanations

Two competing explanations were tested before accepting the
instrumentation reading.

*Tempo / pace.* If sessions on that machine simply ran at a different
speed, a globally-fixed threshold could mis-fit them. Measured: session
median gaps vary only 1.27x across all 63 sessions, and the degraded
machine sits at 1.02x of the others. Structural characteristics — events
per execution, session duration, application mix, top application — are
also ordinary. Rejected.

*Window-title fallback.* Day 3 had solved the same null-domain problem
for Dataset B by rebuilding the boundary signal around window titles, so
the obvious question was whether that fallback transfers back. It does
not: on these sessions window-title change has a median lift of 1.10,
firing at 3.33% of boundaries versus 3.55% of non-boundaries — at or
below chance. Titles are present on 99.6% of events; they simply do not
carry business-system identity in Dataset A. Rejected.

Testing this second one mattered, because if a fallback signal had
worked then the correct response would have been to use it, not to build
a diagnostic. There is no signal left to recover on these sessions.

### Engineering Question

Can sessions whose required instrumentation is materially degraded be
detected before segmentation, so the system does not silently present
low-confidence output as normal output?

This was treated as a data-quality and observability question, not as a
request to change segmentation.

### Hypothesis

A lightweight, ground-truth-free, session-level instrumentation-health
diagnostic based on observed signal coverage can identify sessions where
segmentation evidence is materially degraded.

### Proposed Change

A new module, `src/procmine/instrumentation_health.py`, deliberately
placed outside `src/procmine/segmentation/`. Per session it computes
event count, `browser_domain`-populated count, coverage, distinct-domain
count, and a `healthy`/`degraded` status with warnings naming the
failing criterion. It reads `CanonicalEvent.browser_domain`, reusing the
URL parsing that already exists rather than duplicating it, consumes no
ground truth, is deterministic, and writes nothing to raw data.

It was kept diagnostic-only on purpose. The evidence supported the claim
"the required instrumentation is unavailable"; it did not support any
claim about how segmentation should behave differently in that
condition, and conflating the two would have meant changing a locked
architecture on the strength of an observation that was never tested as
an intervention.

### Threshold Reasoning

Two criteria, both derived from Dataset A, and a session is degraded if
either fails.

The distinct-domain minimum of 2 is structural rather than fitted: below
two distinct domains a domain-change is mathematically unobservable
regardless of coverage. Dataset A's distinct-domain distribution runs
0→6 sessions, 1→1, 2→**0**, 3→32, 4→20, then singletons at 5, 6, 7 and
13. The empty bin at exactly 2 means no session sits on the boundary.

The coverage threshold of 0.40 comes from the shape of the distribution:
six sessions at 0.00%, one at 26.00%, then the main population from
46.42% to 69.46% with a median of 57.56%. The two largest gaps in the
entire distribution are 0.00→26.00 (26.0pp) and 26.00→46.42 (20.4pp);
the next largest is 3.6pp. The threshold sits inside that second gap with
a 6.4pp margin to the nearest healthy session.

Recorded for honesty: Dataset B's coverage distribution had already been
seen earlier in the day while identifying the weakness. The threshold was
still derived from Dataset A's gap structure alone and was not moved to
produce any particular Dataset-B result, but it was not chosen blind and
the entry should say so.

The trade-off is worth keeping. The structural criterion alone catches
seven sessions, all on the bad machine. The coverage criterion adds an
eighth, `ses_20260701-043922-SIDDHIGUPTAB00B` at 26.00%, which
independently is the sixth-worst session in Dataset A. Each criterion
catches something the other misses, which is why there are two and not
one — and why no weighted health score was built, since that would have
added complexity the evidence did not call for.

### Dataset-A Results

Eight of 63 sessions flagged. Against the stated observable "did the
locked pipeline do materially worse on this session," cut at the healthy
population's own 5th-percentile F1 (0.2385): TP 8, FP 0, FN 2, TN 53 —
sensitivity 0.800, specificity 1.000.

| metric | flagged median | healthy median | flagged range | healthy range |
|---|---:|---:|---:|---:|
| F1 | 0.1579 | 0.3621 | 0.051 – 0.225 | 0.224 – 0.433 |
| under-segmentation | 1.2462 | 0.0921 | 0.622 – 1.833 | 0.017 – 0.277 |
| over-segmentation | 0.4711 | 1.7333 | 0.308 – 0.973 | 0.741 – 2.500 |
| % fragmented | 47.11 | 84.62 | 30.77 – 65.22 | 25.93 – 100.00 |

The direction is not uniform, and that turned out to be the most
informative part of the result. Flagged sessions are worse on F1 and
under-segmentation but *better* on over-segmentation and fragmentation.
That is mechanically consistent with the diagnosis rather than a
contradiction of it: without a domain-change signal V1/V2 propose far
fewer boundary candidates, so fewer false splits are produced while most
true boundaries are missed. The characteristic failure on these sessions
is distinct executions being merged together, not executions being split
apart — which is a more precise statement of the problem than "these
sessions score badly."

Only under-segmentation separates completely: every flagged session at or
above 0.622, every healthy one at or below 0.277, with no overlap. F1
ranges overlap by 0.001; over-segmentation and fragmentation overlap
substantially. By machine, LAPTOP-R36BQBTE is 7/7 flagged,
SIDDHIGUPTAB00B is 1/12, the other six machines 0.

Wording kept deliberate: these figures describe observed segmentation
behaviour on flagged versus healthy sessions. They do not establish that
the diagnostic predicts segmentation quality, and it was not evaluated as
a predictor.

Both misses are recorded rather than tuned away.
`ses_20260701-030836-yuvraj` has F1 0.2243 with 68.85% coverage and 4
domains — genuinely poor and genuinely well-instrumented, so its problem
lies elsewhere and the diagnostic correctly declines to claim it.
`ses_20260701-035622-SIDDHIGUPTAB00B` is a boundary artifact: the
percentile cut is literally its own F1 value, so it counts as poor by
construction. Sensitivity 0.800 is the honest figure and the correct
scope — this detects missing instrumentation, not every cause of bad
segmentation.

### Dataset-B Results

Same diagnostic, same thresholds, no retuning. Two of fifteen sessions
flagged. `ses_20260701-192455-NEELA9BAF` at 0.00% coverage — the one
already known, correctly caught. And `ses_20260701-164424-CHAITANYA0BCF`
at 37.20%, which had not been identified before and was investigated
rather than dismissed as a diagnostic error.

Together they contribute 74 of 645 executions (11.5%) and 14 of the 122
HR/Payroll executions (11.5% of the evidence base behind the
recommendation).

The caveat belongs on record: Dataset B's coverage distribution sits
systematically lower than Dataset A's (median 50.44% vs 57.56%), so a
threshold derived from A is somewhat stricter when applied to B. The
0.00% session is unambiguous; the 37.20% one is only 2.8pp under the line
and should be read as marginal. The honest reading is one clear flag plus
one borderline flag, not two equivalent failures.

### Business Sensitivity

Since 11.5% of the HR/Payroll evidence comes from sessions now considered
degraded, the recommendation itself had to be re-tested rather than
assumed.

The Problem-2 chain was re-run end to end, twice, invoking the existing
Day-3 scripts unmodified as subprocesses, with the only difference being
which executions are in the input. Profiles and variants are recomputed
from each population — filtering executions while keeping full-population
aggregates would have quietly mixed the two, since the opportunity score
reads execution_count, total_duration_ms, avg_manual_event_share,
dominant_variant_share and n_variants from the profiles. Case A
reproduced the Day-3 artifact exactly (0.9236 / 0.4765 / 0.4401),
confirming the harness was faithful before Case B was read.

With both degraded sessions removed (645 → 571 executions), HR/Payroll
stays rank 1. Impact 0.9236 → 0.9249, Feasibility 0.4765 → 0.4519,
Opportunity 0.4401 → 0.4180. Still Pareto-non-dominated. Still #1 in 5 of
8 sensitivity scenarios, identically. The top five keep their exact
order; eleven processes move, every move is ±1, and all are below rank 5.

The recommendation survives, but not untouched. HR's Opportunity falls
5.0% while Order & Inventory rises, so the margin to second place narrows
from 0.0872 to 0.0546 — a 37.4% reduction. HR still leads clearly; the
lead is simply smaller on clean evidence than the headline number
implies, and that belongs in the final report rather than only the
favourable half.

### Decision

**RETAIN**, strictly as an upstream quality layer.

The diagnostic separates the degraded population cleanly on the metric
that matches the mechanism, costs two interpretable parameters justified
structurally and distributionally rather than fitted to their own
outcome, transfers to Dataset B unchanged and surfaced a session that had
not been identified, and converts a silent failure into a stated one.

No Dataset-A segmentation metric changed, because nothing in the decision
path changed. That was the intended outcome — the goal was operational
honesty, not a better benchmark number.

The architecture is now conceptually: raw logs → instrumentation health
check → locked segmentation (unchanged) → executions → Problem-2 →
opportunity → prototype.

Three separate conclusions, kept separate rather than collapsed into one
figure. *Algorithm quality*: unchanged and unchallenged — F1 0.3440,
recall 0.6355, fragmentation 79.05%, under-segmentation 0.1412,
over-segmentation 1.603. *Instrumentation quality*: newly measured — 8 of
63 Dataset-A sessions and 2 of 15 Dataset-B sessions lack the evidence
the strongest boundary signal depends on. *Business-analysis confidence*:
high for "HR/Payroll is the right first target," lower for the precise
Opportunity value, which moves ~5% depending on which evidence is
admitted.

### Remaining Question

Under-segmentation separates the flagged and healthy populations
perfectly (flagged ≥ 0.622, healthy ≤ 0.277, zero overlap) and the
mechanism is understood, which suggests the pipeline could in principle
condition on instrumentation availability — relaxing the Rule-4
continuity demotion, or weighting the remaining signals differently, when
the domain signal is known absent.

This was deliberately not investigated. It would modify the locked
architecture, it needs its own pre-registered success gate on all four
metrics plus per-session robustness, and it would be fitted on only 8
flagged sessions, which makes overfitting a real risk. Recorded as a
potential Day-5 hypothesis pending an explicit decision, not folded into
a diagnostic-only change.

### AI Contribution

AI was used to accelerate implementation, experiment execution, testing,
and analysis: the diagnostic module, the two analysis scripts, and the
twelve tests were AI-implemented. The engineering direction was mine —
starting from baseline reproduction rather than algorithm search,
requiring the tempo and window-title explanations be measured and ruled
out before accepting the instrumentation reading, setting the constraint
that the locked architecture stays untouched, requiring thresholds be
justified structurally and from distribution shape rather than fitted to
the outcome, requiring the HR/Payroll sensitivity check because the
recommendation is mine to defend, and making the RETAIN call and the
scoping decision not to condition segmentation on the flag.

### Status — Day 4 complete

465 tests passing (453 prior + 12 for the diagnostic). Locked
segmentation architecture untouched and re-verified bit-identical. New:
`src/procmine/instrumentation_health.py`,
`scripts/analyze_instrumentation_health.py`,
`scripts/run_instrumentation_sensitivity_check.py`,
`tests/test_instrumentation_health.py`, and `reports/day4/`. Dataset A
and Dataset B raw data unmodified; no Day-1/2/3 report was altered. Git
remains mine to handle — no git command was run this session.
