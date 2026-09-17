# Work Log

This log follows the seven work days of the assignment. For each day I recorded what I was
trying to find out, what I tried, what did not work, and what I decided because of it. The
evidence behind every number is in `reports/dayN/`; the final argument is in
`reports/final_report.md`.

**About the dates.** "Day N" is a work phase, not a calendar date. File timestamps on this
machine run from 12 to 18 September 2026, some phases share a calendar day, and a few pieces
of work (the Day-5 integration boundary, Day-6 Module 2, the Day-6 HTTP integration and the
visual review) were finished later than the rest of their day. I filed each of those under
the day whose work it extends and marked it as an extension, rather than inventing extra
days. Where the original entry recorded a test count, I kept it; the counts show how the
suite grew.

**About AI use.** The brief allows generative AI and asks for it to be recorded. I used
Claude Code throughout as an implementation and analysis accelerator: it wrote most of the
code and tests, ran the scripts, and drafted documents. I set the questions, the order of
the investigation, the acceptance and rejection criteria, and the safety boundaries, and I
made the decisions from the evidence. Each day ends with a short note on the split.

**Git.** I handled all Git operations myself. Where a day lists commits, those are my own
records.

---

## Day 1 — Understanding the data before trusting it

*12 September 2026, one continuous session.*

### What I set out to do

Before writing any segmentation, I wanted to know whether the logs could be trusted the way
the task assumes: whether a count, a timestamp or a field really means what it appears to
mean. Step 1 can only be as good as the data under it. So the scope for the day was
discovery, loading, validation, a data-quality audit, ground-truth checks, profiling, and a
first look at candidate boundary signals. No segmentation, no model, and no Dataset-B
output. I kept to that for the whole day.

### What I built

- A `src/procmine` package instead of loose scripts: data models, session and chunk
  discovery, event and ground-truth loaders, a validation framework, an audit module, a
  deliberately minimal cleaning layer, profiling and figures.
- Five command-line scripts that run end to end on the real data (`profile_dataset.py`,
  `parse_ground_truth.py`, `validate_dataset.py`, `audit_dataset.py`, `case_studies.py`).
- 36 tests in 7 files. Each real bug I found got a regression test that reproduces it.
- Five case-study session timelines, picked by properties in `gt_manifest.json` (execution
  count, variants, splits) rather than at random.

### What I found

- **Sizes match the brief.** Dataset A: 63 sessions, 117 chunks, 162,768 events, 2,009
  ground-truth executions. Dataset B: 15 sessions, 20 chunks, 20,477 events, no ground
  truth. The event count matching the brief's "~162,000" was the first real correctness
  check, not just "it ran".
- **Raw order is not chronological.** Every session has events out of timestamp order in
  the raw files, mostly screenshots written late because capture is asynchronous. Sorting by
  `timestamp_ms` is required, and the loader always does it.
- **Sessions span chunks.** 53 of 63 sessions have two or more chunk files, and most
  ground-truth executions cross a chunk edge. Chunk edges are storage, not process
  boundaries.
- **Screenshot folders are inconsistent.** 35 of 117 Dataset-A chunks keep their
  screenshots in a sibling folder with a shorter name, so the resolver checks both places.
- **Duplicates come from the agent, not the user.** 65% of `app_switch` events in Dataset A
  are exact back-to-back repeats 36–97 ms apart; Dataset B has none. 42 groups are the same
  `browser_error` logged twice in the same millisecond.
- **Screenshots depend on the dataset.** 7.2% of Dataset-A screenshot references resolve to
  a file on disk, against 81.2% in Dataset B. A conclusion drawn from A alone would have been
  wrong for B.
- **The agent's own gap field is broken in places.** `ms_since_last_event` reaches −713,900
  ms, and 443 events (0.27%) are below −1,000 ms. The two worst values sit exactly where I
  had separately found an event naming the wrong chunk. Two unrelated checks landing on the
  same point convinced me it is a real agent defect.
- **Ground truth mostly agrees with itself.** The two documented defects (duplicate
  `process_started`, unpaired `process_switched_out`) never occur. My extra checks found one
  execution suspended and never resumed, and one field-level disagreement: the manifest's
  `split_id` is empty for that execution while the raw stream shows a real one.
- **Text needs care.** Keystroke reconstruction matched `final_text` exactly on a real
  example. Clipboard events carry no text at all, only metadata.
- **Password fields were not redacted.** 18 `text_input_complete` events contain the typed
  value of a password field although the capture settings say `redact_password_fields:
  true`. They are synthetic test credentials, so nothing real was exposed, but the redaction
  does not work for this field. I recorded it as a governance risk for Step 3 and never copy
  the values anywhere.

### What went wrong, and how I fixed it

- **One corrupted `manifest.json` crashed a whole session load.** I had tested the loader
  against deliberately corrupted metadata instead of trusting a clean run. Manifest parsing
  assumed well-formed input, while the event parser already handled bad lines. I wrapped it
  so the error is recorded instead of raised, and added a regression test for the exact
  failure.
- **A profiling pass said 100% of `text_input_complete` events had no content.** That
  matched a warning in `DATA_SCHEMA.md` suspiciously well, so I checked it. The profiler was
  looking for fields called `text`, `content` or `value`; the real field is
  `payload.final_text`, which the schema never names. The corrected figure is 2 of 118
  missing, not 118 of 118. It was the clearest lesson of the day: a plausible number still
  needs a raw example checked before it goes into a report.
- **A report draft said "54 of 63 sessions have 2+ chunks"** without the number having
  been counted. I had it re-counted; the true figure is 53.

### Decisions

- `app_switch` counts cannot be used raw. I did not deduplicate them in the cleaning layer,
  because deciding which of two identical switches is "the real one" is a segmentation
  judgement, and I wanted that decision made and tested on Day 2.
- Timing statistics are always reported with percentiles. The median gap (44 ms) looked
  fine; only the tails exposed the −713,900 ms defect.
- Ground truth is evidence to cross-check, not an infallible file.
- Anything measured on Dataset A is re-measured on Dataset B before I rely on it.

### What I deliberately did not do

I did not modify raw data (cleaning works in memory, and the raw folders are not in the
repository), treat chunk edges as boundaries, delete the duplicates, trust
`text_input_complete` or `ms_since_last_event` directly, start any segmentation, or call a
signal useful before measuring it against ground truth.

### AI use

Claude Code implemented the loaders, validation, audit tooling and tests, ran every script
on the real data, and did the first diagnosis of both bugs. I decided what to build, which
audit categories mattered, which suspicious numbers had to be checked before being accepted
(the 65% duplication rate and the "100% missing" text result), and the rules that followed:
raw data is immutable, facts and inferences stay separate, and no segmentation happens yet.

### End of day

Data loading, validation, the audit and ground-truth checks were done; 36/36 tests passed;
three of six candidate signals had been measured. Segmentation had not started. I organised
the day's work into 14 commits by component after the review pass rather than committing
through the day.

---

## Day 2 — Recovering units of work

*13 September 2026.*

### Starting point

The plan was to measure the three signals Day 1 had not evaluated, then design and validate
a segmentation on Dataset A before touching Dataset B at all.

### Signals and simple baselines

- I turned Day 1's ad-hoc alignment check into real code and reproduced its numbers
  exactly before measuring anything new.
- Two of my hypotheses failed: window-title changes (lift 0.048) and clipboard timing (lift
  0.008) are *less* common near boundaries than inside executions. Browser navigation was
  the strongest single signal (lift 13.98), well ahead of app switches (3.61), but uneven
  across sessions, with one session at 0% coverage. That session came back on Day 4.
- Chunk-boundary crossings look nothing like real boundaries (median gap 3,970 ms against
  528 ms), and 55 of 56 never coincide with one.
- I found a new data defect along the way: one session's events end 16 minutes before its
  own ground truth says the session ends. It is the only one of 63, and I added a check for
  it.
- **Baselines.** Splitting on pauses alone peaked at F1 0.173 (gap above 3 s). Requiring a
  context change as well reached 0.182; OR-ing the two collapsed to 0.037. True boundaries
  are 1.03% of transitions, about 97 negatives for every positive, which caps what any
  single threshold can do.

### The boundary-first classifier, and why it failed

A logistic regression over transition features, evaluated leave-one-session-out (63 fits),
reached F1 0.254 (precision 0.157, recall 0.655). The chunk-boundary feature got almost no
weight, which confirmed from a second direction that chunk edges are not process edges.

But when I measured over-segmentation, 90.8% of ground-truth executions contained at least
one false boundary, on average 2.80 of them. The model was not failing to reconnect
interrupted work; it was firing false boundaries inside executions that were never
interrupted.

### Interrupted work: investigated and set aside

The brief says work is not always contiguous, so I checked whether Dataset A contains an
execution that is interrupted and later resumed. No `case_id` reappears after a different
case in any of the 63 sessions, and the one suspend/resume example (`M1-B-split-1`) has its
`split_id` only on the later record. There is nothing to learn or validate a reconnection
step on, so I did not build one. An unvalidated merge heuristic would have been an unearned
claim.

### The pivot: boundary-first to continuity-first

Given the fragmentation, I changed the question from "is this transition a boundary?" to
"does the current execution continue?". The same features became evidence for a learned
continuity probability, and a boundary became a loss of continuity. I kept the baselines and
V1 as references that the new model had to beat.

### Building the continuity model (stages 1–6)

1. **Re-inspection.** The event model, features, baselines and cross-validation code all
   carried over. What was missing was continuity labels, fragmentation metrics and a
   reconstruction layer.
2. **Why V1 over-segments.** I had all 4,903 false internal boundaries analysed against the
   1,671 true ones. The model was *more* confident on its false boundaries (median 0.960)
   than on real ones (0.932), so no threshold could fix it. Pauses inside real work (median
   2,627 ms) were longer than typical real boundaries (526 ms), and the gap feature
   dominated the false positives by four to seven times. Duplicate app switches (0.31%) and
   chunk crossings (0.16%) explained almost none of it.
3. **Labels for unlabelled time.** 14.24% of transitions sit between two unlabelled noise
   regions. I decided to train only on transitions with clear ground-truth evidence and to
   exclude the rest rather than guess a label. While implementing it we found 62 more
   transitions with no reliable pairing; I excluded those too and wrote the case down.
4. **Labels built and reconciled.** All six category counts matched the earlier analysis
   exactly and summed to 162,705.
5. **Context features.** The gap stayed the strongest single feature. Normalising gaps per
   session did nothing. Small windows (3 and 5 events) were weak, but 10-event windows were
   useful (AUC 0.697 and 0.605). Stripping the port from the browser domain, an idea from
   stage 2, made things worse, so I dropped it.
6. **The continuity model (V2).** Better F1 on labelled transitions (0.270 against 0.254),
   better recall and under-segmentation, and a much better worst session. But fragmentation
   got *worse*: 94.7% against 90.8%, the very metric that motivated the pivot. I did not
   call it a success.

### Understanding the result before changing anything

- **Why V2 fragments more.** 10 executions were fragmented only by V1 and 81 only by V2, and
  where both failed, V2 did more damage. My guess that V2 simply spread the same errors more
  thinly was wrong. The real reason is that both models threshold each transition on its
  own, and changing the score does not change that.
- **Thresholds (stage 7).** Before running it I predicted that re-tuning thresholds would
  not close the gap. It did not: bringing fragmentation down to about 73–79% needed recall
  around 0.15–0.21, which misses four in five real boundaries. I fixed the recall floor
  (≥ 0.5) before looking at the sweep so it could not be tuned to look good.
- **What interruptions look like (stage 8).** 1,752 of the 2,009 ground-truth executions
  have a recorded end and are the ones every stage scores. Long gaps and context changes
  are normal inside real work. 95.6% of false boundaries are isolated spikes. The key
  finding: at V1's false boundaries the 10-event neighbourhood looks like ordinary
  continuity (0.500), not like a real boundary (0.286). The neighbourhood agreed with the
  truth where the single gap did not. Half of all executions contain a leave-and-return
  pattern.

### Reconstruction and protection (stages 8.2–8.5)

- **Design.** Take V1 and V2's candidates together and only ever remove candidates, using
  an ordered list of rules: noise override, leave-and-return, cluster protection, and a
  10-event continuity fallback (Rule 4). No new boundaries, no fitted weights yet.
- **First experiment.** Fragmentation fell to 77.6% and F1 rose to 0.304, but
  under-segmentation went from 0.063–0.085 to 0.204 in all 63 sessions. The
  pre-registered gate failed, and I reported it as a failure. Rule 4 did 96% of the work and
  removed false boundaries at about 12 to 1, so the idea was sound; it just also removed 296
  real ones.
- **Why Rule 4 removed real boundaries.** Model confidence did not separate the two groups.
  Two signals did, and held across about 89% of sessions: whether *both* models had flagged
  the transition, and how slowly the next ten events unfolded. The raw gap looked useful
  pooled but failed the per-session check (41% agreement), so I rejected it.
- **Protection experiment.** Agreement protection failed three of seven gates (11.28 false
  boundaries protected per true one). Tempo and Combined protection both passed all seven.

### Locking the architecture

Tempo and Combined were close (F1 0.339 against 0.344), so I compared them properly rather
than taking the higher number. Combined was never worse on fragmentation in any of the 63
sessions; 14 executions fragmented only under Tempo and none only under Combined; and
Combined's F1 edge held at all 9 neighbouring threshold values. Tempo had better
under-segmentation in 52 of 63 sessions, which I kept on record as the fallback.

**Locked:** candidates V1∪V2, Rules 1–4, Combined protection, thresholds 0.9078, 0.8860,
0.40 and 4,680.2613. Result on Dataset A: precision 0.2358, recall 0.6355, F1 0.3440, 79.05%
fragmented, under-segmentation 0.1412. It is a partial fix, not a solved problem.

### Two more ideas, tested and rejected before moving on

- **Segment-level coherence.** Would the real segments on each side of a boundary show
  whether they belong together? The coherence signals were the weakest in the comparison
  (separation 0.025–0.107). The strongest signal, fragment length, missed my pre-registered
  bar by 0.001 and is not really a coherence measure. I stopped as I had said I would.
- **Global sequence optimisation.** Could choosing all boundaries at once with a cost
  function do better? I ran a feasibility study before writing an optimiser. The components
  pointed the wrong way because of a segment-length confound, the combined score reached
  only 0.080 separation, and it did not beat Rule 4's own feature. I did not build the
  optimiser.

### AI use

Claude Code implemented the signal, feature, baseline, model, forensic, reconstruction and
protection code and ran every experiment. I set the direction at each step: measuring the
false-boundary rate directly, the pivot to continuity-first, the labelling policy, which
hypotheses to test, the pre-registered gates, the order of the options, and the final
Tempo-versus-Combined decision.

### End of day

The Dataset-A architecture was locked and documented in
`reports/day2/segmentation_architecture_final.md`. 234 tests passed. Dataset B had not been
read.

---

## Day 3 — Dataset B: what work is done, and what to automate

*13–14 September 2026.*

### Profiling first, and a wrong first guess

I did not assume anything from Dataset A would transfer. Profiling Dataset B showed 15
sessions, 4 operators and almost no long pauses, so a gap-based approach would find nothing
there. The Dataset-A classifiers were fitted to Dataset-A ground truth, so I built a separate
boundary signal for Dataset B based on which system is active.

My first version used the browser domain, because it mattered most in Dataset A. It
immediately produced thousands of near-zero-length segments. The domain is often empty in
Dataset B even when the window title clearly names the system, so I rebuilt the signal
around window titles, with short leave-and-return trips (up to 5 events away) merged back.
That was a real wrong guess, caught only by checking the output against the data. The result
was 645 executions across 15 sessions.

### Processes and a first ranking

I grouped executions by their dominant system context into named processes and variants and
ranked them with an equal-weight priority score. HR / Payroll came first under the default
weighting and two of four alternatives. Two tiny Excel workbooks beat it under a risk-averse
weighting; I reported that and explained that they "win" mostly because they have almost no
volume.

### HR forensics, and a reconstruction bug I caught

Before designing any automation I rebuilt HR's dominant path at event level. My first pass
recovered execution boundaries from timestamp ranges, and a cross-check found it
misattributing events in 16 of 94 executions where timestamps collided at the millisecond. I
rebuilt the boundaries from the same index-based pipeline that wrote the data and confirmed
0 mismatches across 645 executions before trusting anything.

The result: 94 of 122 HR executions (77.05%) follow one path — open one of four routes,
paste a note, click OK. Every observed form input was a paste, and note-field clicks pair
with OK clicks almost one-to-one (139 against 138).

### Choosing the form and building the prototype

I chose deterministic UI automation. No API call appears anywhere in the logs, so an API
integration would mean inventing one, and the dominant path contains no judgement or
unstructured step for an AI agent to handle. The Word detour does, so I left it out.

The prototype navigates, checks the note field, inserts the operator's note, checks the OK
button, and then stops at a mandatory human review before a separate confirm call. It runs
against a small in-memory mock HR application with fault injection, because no browser
automation library was installed and adding one only to prove the logic did not seem
justified yet. Going through the safety requirements a second time, I found two gaps: empty
notes were not rejected before touching the UI, and the OK button was clicked from a cached
reference, so a page change during the review would go unnoticed. I fixed both with 8 new
tests.

### Questioning my own scoring

My 8-factor score blended everything into one number and had never been compared with
anything more standard. I built trace abstraction, a directly-follows graph, three
similarity measures, variant entropy, and a different structure that keeps Impact and
Feasibility separate until the end. I ran it over all 21 processes so I could not tune it to
HR.

The graph and similarity work confirmed the variant grouping. Execution count and duration
correlated at 0.977, which I had not checked before. The new sensitivity sweep first showed
HR first everywhere, which made me suspicious, so I added an adversarial scenario like the
one that had hurt the old score. The same small workbooks displaced HR again. My impression
that the new method was more stable came from not trying hard enough to break it. Decision:
**augment** the method (keep the clearer Impact/Feasibility structure) rather than replace
it or leave it unexamined.

### The final audit

- **A real bug.** Entropy was used in raw bits, which cannot be compared across processes
  with different numbers of variants: a 7-variant process scored 2.195 against 1.500 for a
  3-variant one that was actually more evenly spread. I switched to entropy normalised by
  its maximum. HR's Feasibility moved from 0.453 to 0.477 and ranks 4 and 5 swapped.
- **Redundancy, tested.** Three of four Impact formulations keep HR first, but dropping
  duration moves HR to rank 3. HR's lead rests on the time signal.
- **Stricter sensitivity.** With the eight one-axis scenarios the task asked for, HR is
  first in 5 of 8 (the earlier, looser sweep said 9 of 12). The three that displace it all
  reduce the weight on time. I reported the stricter number.
- **Ablation.** Only removing frequency (HR to 2) or time (HR to 3) changes HR's rank.
- **Pareto.** Without any weights, only 3 of 21 processes are non-dominated, and HR is one
  of them.
- **Worst case.** HR never fell below rank 3 in anything I tested. I took into Step 3 the
  claim "HR is the strongest evidence-backed candidate here", not "HR is optimal".

### Closing the deliverable gap

Auditing the repository against the brief's deliverables, I found that `segments.jsonl` did
not exist. I added a pure format conversion — no new boundary logic — with labels taken from
the existing process names. 11 single-event executions had equal start and end times, so I
moved their end forward by 1 ms in the output only and logged how many. I then validated the
file independently: 645/645 records, correct schema, all 15 sessions from Dataset B.

### AI use

Claude Code implemented the Dataset-B boundary code, process discovery, the forensic
scripts, the mock application, the automation layer, the process-mining modules and the
tests. I chose what to profile and in what order, formed the hypotheses that turned out to be
wrong and had to be corrected, set the scoring discipline and the automation boundary,
required the adversarial scenario and the Pareto check, and chose HR, deterministic UI
automation and the four routes.

### End of day

453 tests passed. HR / Payroll was the candidate: Opportunity 0.4401, Pareto non-dominated,
worst rank 3. The prototype worked on all four routes and stopped safely on bad input.

---

## Day 4 — Is it the algorithm, or the logs?

*14–15 September 2026.*

### The question

Some Dataset-A sessions were much worse than others. Before changing the algorithm, I wanted
to know whether its input could support it in those sessions. I reproduced the locked
baseline first (all 30 pooled metrics matched to 1e-12), and I did not modify the
segmentation at any point that day.

### What I found

- **All seven of the worst sessions came from one machine**, with a mean F1 around 0.14
  against 0.32–0.40 elsewhere and under-segmentation around 1.28 against 0.06–0.18. A global
  threshold problem would not concentrate on one machine.
- **Pace was my first guess, and it was wrong.** Session pace varied only 1.27× across the
  dataset, and that machine sat at 1.02×. I rejected it and wrote that down.
- **Browser capture was the cause.** Six of the seven sessions had 0.00% browser-domain
  coverage, and the seventh recorded a single domain, so a domain change could never be
  seen. On healthy machines 96.6% of real boundaries coincide with a domain change; on this
  machine, 0%. The rules were not wrong; the evidence they rely on was never captured.
- **Window titles cannot replace it.** Lift about 1.10, with alignment at or below chance
  (3.33% at boundaries against 3.55% elsewhere). Because the fallback failed, a diagnostic
  was the right answer rather than a patch.

### The diagnostic

`src/procmine/instrumentation_health.py` checks browser-domain coverage (minimum 0.40) and
distinct domains (minimum 2) per session. I put it outside the segmentation package on
purpose, so nobody wires it into the locked decision path without a separate justification.
The two-domain minimum is structural: with fewer than two domains a change cannot be
observed.

- **Dataset A:** 8 of 63 flagged — all 7 from that machine and 1 of 12 from another. Against
  "poor session": 8 true positives, 0 false positives, 2 false negatives, 53 true negatives.
  Flagged sessions had median F1 0.158 against 0.362, and median under-segmentation 1.246
  against 0.092. I read the two misses as the scope of the tool: it finds missing capture,
  not every cause of poor segmentation.
- **Dataset B:** 2 of 15 flagged, one at 0.00% and one at 37.20%. The second was new and is
  the weaker flag, because Dataset B's coverage runs lower overall.
- **Does it change the decision?** I re-ran the Day-3 chain without the two flagged sessions
  (645 → 571 executions). HR stayed first (Opportunity 0.4401 → 0.4180, Kendall τ 0.9524 →
  0.9476), but the margin to second place narrowed by about 37%. 0.4401 stays the canonical
  figure; 0.4180 belongs only to this check.

### Decisions and rejected alternatives

I kept the segmentation locked, kept the diagnostic upstream and outside the decision path,
and did not condition segmentation on it. I rejected a pace adjustment, the window-title
fallback, re-tuning the model, and a single weighted health score, which would hide which
check failed. Conditioning segmentation on health is deferred: the signal is real, but it
would be fitted on 8 sessions and would need its own gates.

### Limitations

The diagnostic only covers browser capture, cannot tell why capture failed, repairs nothing,
and was calibrated on Dataset A.

### AI use

AI helped draft the implementation, structure the scripts, write tests and interpret
intermediate output. The decisions were mine: reproduce the baseline first, study the bad
sessions rather than the pooled metric, test and reject pace, pursue browser capture, test
the fallback before settling on a diagnostic, keep it outside the segmentation package, run
the Dataset-B sensitivity check, and leave the segmentation alone.

### Commits

```
af80bea  Add instrumentation health diagnostic
818ca56  Add tests for instrumentation health
e8d6ba6  Add instrumentation health analysis script
f8ae3fc  Add instrumentation sensitivity check
70d60b0  Add instrumentation health results
46b7902  Document instrumentation health analysis
ca7b929  Document Day 4 investigation and decisions
5a34973  Add instrumentation sensitivity results
```

### End of day

465 tests passed. No segmentation file, locked metric or canonical ranking changed.

---

## Day 5 — Making the evidence inspectable

*14–15 September 2026; the integration extension was finished later.*

### The goal and the main risk

All the evidence was JSON and markdown in `reports/`. I wanted a reviewer to be able to
inspect it and to see the automation run. The obvious way — load the artifacts into React and
compute what each screen needs — would have created a second copy of the analysis that could
quietly drift from the real one. So the rule was: the frontend displays validated results and
never computes them.

### The data contract

`scripts/build_frontend_data.py` only reads, selects, reshapes and writes. Every value is
copied from an artifact or is a clearly marked count or look-up, listed in
`reports/day5/data_contract.md`. The most important choice was the ranking source: three
files in `reports/day3/` hold different values, and only `problem2_audit_results.json` has
the post-fix 0.4401. The superseded pre-fix value (0.4186) must never appear. The HR variant
split (94 / 24 / 4) is carried explicitly rather than re-derived in JavaScript. The contract
also lists what is *not* available — raw event streams, Dataset-A predicted boundaries,
graphs for the other 20 processes — so the UI cannot pretend otherwise.

### Frontend

React, TypeScript and Vite, with only `react` and `react-dom` at runtime: no router, no chart
library, no UI kit. Everything loads eagerly except the per-session execution files (about
4.4 MB), which load when a session is opened. Five screens: Dashboard, Opportunities,
Process Explorer, Session Replay and the HR Automation Demo. The F1 is always labelled as a
transition-level metric. Degraded sessions carry a badge and the same wording everywhere:
missing instrumentation means missing evidence, not proven failure.

### The HR demo and its API

`scripts/serve_hr_demo_api.py` is a small standard-library server with three endpoints
(`/api/routes`, `/api/prepare`, `/api/confirm`). HTTP 422 means the prototype refused on its
own safety rules. The checkpoint is held on the server, keyed by a single-use token, because
confirm re-locates the OK button at confirm time; rebuilding objects per request would defeat
that. The browser cannot create a checkpoint, and the confirm button does not exist until the
server issues one. The note must come from the operator.

### Tests

The data-builder tests run on the real artifacts: all 645 executions survive, per-session
files partition them exactly, the HR row equals the audit file, the superseded 0.4186 appears nowhere, and
two builds are byte-identical apart from a timestamp. API tests cover the safety properties,
including that a checkpoint cannot be confirmed twice. The Python suite went from 490 to 504
tests; the build was about 180 KB of JavaScript.

### Rejected

Analytics in the frontend, recomputing scores in JavaScript, loading 4.7 MB eagerly,
requiring the raw datasets, pretending event-level data exists, acting on instrumentation
health in the UI, and production-grade automation.

### Extension (finished later): integration boundary, execution state, lost responses

The prototype proved the automation logic but had no realistic integration boundary: one
in-memory target, no execution identity, no persistence, and an open problem I had written
down myself — if a confirmation succeeds and the response is lost, the client cannot tell
what happened. That is the gap where being wrong means a duplicated payroll change.

I added an explicit `HRApplication` interface with three adapters (mock, browser, and a REST
adapter over a local simulator; I did not write a client for a real HR API because none is
evidenced), an execution state machine with `UNKNOWN` as a non-terminal state,
`GET /api/executions/{id}/status` so the client asks instead of retrying, idempotency keys,
development roles in which an operator can prepare but not confirm, in-memory and SQLite
repositories, ten deterministic failure modes, and trace events keyed by request and
execution id.

My own tests caught two bugs: the simulator applied its failure at every stage, so the
lost-response demo could never reach the checkpoint (an end-to-end smoke test found this),
and the repository protocol was not runtime-checkable. One frontend test stub counted every
non-prepare call as a confirmation; I made it count `/confirm` explicitly without changing
its assertion.

This is the largest piece of pure architecture in the project, built against a target with
no real API. I think the never-retry rule and review-as-authorisation earn their place; if
someone disagreed, I would drop the SQLite backend first. The status stayed **LOCAL
VALIDATED — not connected to any real HR system**. After this work: 830 Python and 137
frontend tests.

### AI use

The components, adapter, API and tests were AI-implemented. I decided that the frontend is an
evidence layer and not a second analytics engine, the single ranking source, the explicit HR
split, the labelling of missing evidence, lazy loading, the server-side checkpoint, and the
bounded scope of the demo, and I reviewed the behaviour before accepting it.

### Commits

```
28f6b60  Set up frontend project
03acd68  Add frontend data builder
a57cb1b  Add frontend data bundle
ae1ba93  Build frontend foundation
fd13841  Add process analysis screens
899db16  Add session replay
b02633a  Add automation demo
6aa95c6  Add HR demo API
d84ae43  Add frontend tests
384af4a  Add API tests
b4cf539  Document frontend implementation
```

### End of day

A reviewable five-screen frontend over the validated artifacts and a working demo with its
safety model intact. No analytical result changed.

---

## Day 6 — The decision layer, and attacks on my own architecture

*15 September 2026; Module 2, the visual review and the HTTP integration were finished later
and are filed here as extensions.*

### Part 1 — Automation Decision Center

The dashboard could say which process to automate, but not whether we were ready, why we
believed it, or how robust it was. I added three things:

- **Readiness as explicit gates, not another score.** Six yes/no checks, each naming the
  artifact it reads: ranked first, Pareto non-dominated, one path covering most executions,
  a bounded set of routes, one deterministic input method, and a working prototype. HR
  passes all six, so the screen says READY FOR BOUNDED PILOT and explains that this means a
  supervised trial. The "most executions" rule (over 50%) is labelled as a display rule.
- **Evidence traceability.** The claim sits at the top, and each piece of evidence expands
  into what was observed, why it matters, and the source file and field, with links into
  Process Explorer, the demo and a real recorded execution. The two weak spots are visible
  on purpose: the 139/138 click mismatch (on `#/leave-applications`, 27 against 26) and the
  fact that OK-as-confirmation is inferred from the DOM.
- **Sensitivity by scenario.** Rendering the eight scenarios caught an error of mine: I
  remembered HR falling to rank 6 under an adversarial weighting. The canonical artifact
  says the worst rank is 3; the "6" came from an earlier exploratory run. I wrote the screen
  against the artifact and added a test that "rank 6" never appears.

For any process other than HR the screen shows "Not proposed" and nothing HR-specific; I
tested that, because leaking HR's evidence onto another process would be the easiest way for
this screen to mislead.

### Part 2 — HMM, ensembles, clustering and LLM labelling

The locked detector judges transitions largely one at a time, and a boundary is really a
property of a sequence. I wanted to know whether a sequence model would show a measurable
advantage or whether that was "more sophisticated, so probably better" thinking.

- **Scope choices.** I ruled out a BiLSTM-CRF before writing code: 63 sessions cannot
  support a model that must transfer to different departments. I did not rebuild
  change-point baselines, which Day 2 had already measured (F1 0.173 and 0.182). Clustering
  answers a different question and belongs after segmentation.
- **Reproduction first.** The experiment code sits in a separate package, and a test checks
  it imports nothing from the locked segmentation. Before any comparison, the script
  reproduced the locked predictions with drift 0.0.
- **HMM.** Unsupervised and fitted per session, with the state count swept (2–8) rather than
  set to the number of processes. The best was 2 states at F1 0.0194, about 18× worse than
  0.3440. It flagged 22.5–46.9% of transitions against a true rate near 1%.
- **Ensemble.** There was real complementary signal: the HMM alone caught 157 of the 1,671
  true boundaries. But either-flags recovered them at about 225 false positives each (F1
  0.0586), and both-must-agree *lowered* precision to 0.1809.
- **Clustering.** To avoid a circular test I clustered on behaviour only, without system
  identity: ARI 0.264. With system identity added back, 0.661. Behaviour alone does not tell
  you which process you are in, which supports grouping on system context.
- **LLM labelling.** Compressed summaries only, with the process names withheld: 6 of 6
  labels matched in meaning. It also pointed out that one HR route asks for "approval comment
  or reason for return", a judgement step.
- **Conclusion.** The binding constraint is class imbalance, not model sophistication. I
  changed nothing in the pipeline and kept the LLM only for labelling. I skipped the planned
  LLM boundary second opinion, because after the HMM result its failure was predictable.
  Limitations: Gaussian emissions on partly boolean features, and only 6 processes labelled.

### Part 3 — Auditing my own submission

Reading the repository as a sceptical reviewer, I found that the final report did not exist
and the README was still the brief with my name on top. I wrote the report and rebuilt the
README, keeping the brief intact. The audit changed two things in the argument:

- **77% of executions is not 77% of time.** The dominant path covers 55.89% of HR handling
  time (27.9 of 49.9 minutes), because detours take two to six times longer. Quoting "77%
  automated" as a time saving would have overstated the benefit by about 21 points.
- **Operator coverage.** HR is done by all 4 operators; the workbooks that displace it under
  some weightings are used by 1 and 3. The strongest objection has a plain factual answer.

I also caught myself calling class imbalance "the reason the number looks low". That is an
excuse. Imbalance explains why F1 is the right metric; it does not make 0.3440 good, and the
report now says so. I built `scripts/verify_report_numbers.py`, which recomputes every
headline number from its artifact and checks it appears in the report, and made it a test.

### Extension — Module 2: new evidence, not a new arrangement

Every challenger so far had rearranged the same evidence. Two gaps stood out: timing is
judged against one global threshold for everyone, and the model only knows that screen text
existed, not whether it changed. Testing that meant adding columns, which would change Module
1 in place, so I froze Module 1 and built Module 2 as a separate package with eight written
hypotheses.

- **The data corrected both designs before any modelling.** Word-overlap between adjacent
  events was computable on only 0.03% of transitions, so I moved to 10-event windows (11.50%)
  and marked the rest as unavailable instead of imputing a value. Operator speed barely
  varies (median gaps 52–56 ms), so I normalised by spread rather than by centre.
- **Fair comparison.** Only the feature matrices vary; the candidate union, rules,
  protection and evaluator are the locked code, and a control runs through the same harness.
- **Result.** The combined set (M2C) reached F1 0.3519 against the control's 0.3417: a gain
  of **+0.0102**, where the pre-registered gate required **+0.0200**. It improved every
  segmentation metric together, across 30 of 63 sessions (8 worse), and passed the other
  seven gates. This was the tempting moment: lowering the gate to 0.01 would have promoted
  it. That would have been fitting the gate to the result, so I did not. Module 2 was
  **not promoted**.
- **Routing gate.** Word appears in 24 of 24 detours and 0 of 94 dominant executions, so no
  classifier was needed. The gate admits 62 of 122 executions and refuses all 28
  non-dominant ones, but also 32 that the forensics call dominant (no route visited, several
  routes, or a route outside the four). I kept the refusals: "dominant variant" is a weaker
  claim than "safe to automate". That gives two different numbers, 0.7705 and 0.5082, and I
  report both.
- **Post-action audit.** Structural checks after the flow; it catches injected route drift.
  I did not invent a pixel threshold, and the audit never claims a record was written.

### Extension — Dataset-B visual review

For Dataset B I prepared a blind review sheet: a fixed seed (20260918) drew 20 predicted
boundaries and 20 mid-execution controls, shuffled together, each with its nearest
screenshot (median gap 385 ms). 14 of the 40 screenshot files were missing from disk. I left
the human sheet blank rather than fill it with model labels.

Later I ran a separate blind review with a vision model. The reviewer saw no answer-bearing
field, missing images were marked unavailable by rule, and the judgments were hashed before
I opened the answer key. A byte-exact search recovered none of the 14 missing files. Before
the freeze I re-read every rationale and adjusted three judgments, all logged.

The labels: clear continuity 7, clear boundary 6, ambiguous 13, unavailable 14. After the
reveal, a visible context change appeared at 3 of 12 judgeable boundaries and 3 of 14
judgeable controls. **Decision: identifies concerns.** It is a surrogate review, not ground
truth and not a metric. Two things surprised me: the three boundaries that look continuous
all follow a short Word lookup that the 5-event merge limit turned into its own execution,
and every capture chunk above 250 screenshots holds exactly 250 files.

### Extension — a local HTTP integration

The in-process simulator modelled a lost response as a flag on a Python object, and a
persisted `UNKNOWN` execution could not be settled after a restart. I built a separate local
HR API server (standard library, SQLite state), an HTTP adapter behind the same interface
with no retries, durable status resolvers in the orchestrator, and a fourth demo mode. I did
not add FastAPI; both servers use only the standard library.

Before relying on it I reproduced a gap the HTTP target would hit: the automation guarded
only navigation, so a target failing while the note was being written escaped as a raw
error. The three unguarded calls now raise safe stops. With real sockets, a lost response
becomes `UNKNOWN` and is settled to `CONFIRMED` by a status lookup, with exactly one
confirmation received — also after both processes restart, when state is durable. Two
details I had not expected: a 500 on a confirmation proves nothing (it may come before or
after the commit), so both become `UNKNOWN`; and a timed-out confirmation that is still in
progress must not be settled early. I also changed the orchestrator to record the note's
length at the source instead of keeping the text in memory.

### AI use

The Decision Center, adapter additions, HMM module, experiment scripts, Module 2 code,
review tooling, HTTP server and adapter, and their tests were AI-implemented, and the
Phase-7 labels and the visual judgments were genuinely model output, recorded as such. I
chose the features to build, rejected a weighted readiness score, required the weak spots to
be visible, took the artifact over my memory of "rank 6", chose which models to test and
which to rule out, required the reproduction checks, designed the clustering against
circularity, wrote the Module 2 hypotheses and kept the gate unchanged, kept the surrogate
review out of the human sheet, and made every accept or reject decision.

### End of day

Day 6 itself ended with 533 Python and 88 frontend tests and 30/30 traced report numbers.
After the extensions: 1,119 Python tests, 206 frontend tests and 75/75 traced numbers.
Module 1 remained canonical throughout.

---

## Day 7 — Testing what the recommendation rests on, and finishing

*15–18 September 2026.*

### Robustness under segmentation uncertainty

The report argued that the recommendation survives weak segmentation because Step 2 reads
aggregates. That was reasoning, not evidence, and the last untested assumption in the
submission. I stated the hypothesis so it could fail: reasonable merge-threshold changes
materially alter the recommendation.

I varied only the leave-and-return merge threshold, at the documented percentiles of its own
distribution (0, 5, 11, 36), and re-ran the whole Step-2 chain into a separate folder. A
control required threshold 5 to reproduce the canonical ranking exactly, and it did.

The result was not the comfortable one. At the median threshold, HR fell to rank 5 and a
workbook with 7 executions, 0.02 hours and one operator took first place, because its
Feasibility normalised to 1.0. The composite score is fragile. The evidence underneath held:
HR had the most handling time (0.7635, 0.8309, 0.8684 and 0.9796 h) and all four operators at
every threshold. So the recommendation stands, but the score became corroboration rather than
foundation, and the 77.05% share is now described as depending on the threshold (100%,
77.05%, 53.33%, 33.33%). I decided not to redesign the score on the last day after seeing
the result.

### Figures

The submission was all text, so I drew five figures, each answering one reviewer question,
with one convention throughout: solid borders for stages measured against ground truth,
dashed where none exists. They are generated as SVG by a standard-library script and
rasterised with ImageMagick, with no new dependency. Looking at every rendered PNG caught four
layout defects that file sizes would never have shown. Figure 5 contains only mechanisms I
re-read in the source that day. While writing the demo steps I also found stale counts in the
report (30/30 and 86) and corrected them. The demo steps went into `demo/DEMO_SCRIPT.md`,
which is not in the current tree; the README now carries the demo walkthrough.

### Can something simpler do as well?

The locked pipeline is a lot of machinery for F1 0.3440. If a few explicit rules matched it, I
should simplify rather than defend it. I tested four rules cheapest-first (C1 two thresholds;
C2 plus a continuity veto; C3 with frequent app hops treated as part of a process; C4 with a
separate threshold for poorly instrumented sessions), fitted leave-one-session-out, scored by
the locked evaluator, against gates registered before scoring. I left window titles out,
since they had been rejected twice.

The control caught a bug in my harness: the first run reported drift 0.0906 because my lookup
had picked V1 instead of the Combined system. After fixing it, drift was 0.0.

All four failed the same gates. Sorted by fragmentation they trace one curve: C2 (40.87%,
under-segmentation 0.6606), C3 (54.45%, 0.4976), C4 (65.58%, 0.3959), C1 (66.50%, 0.3893),
and the baseline (79.05%, 0.1412). They found other points on the same trade-off, not a
better one. C4 got a fair fit (a different threshold for degraded sessions in all 63 folds)
and was still marginally worse than C1, which agrees with Day 4: the fix belongs in the
capture setup. The experiment also measured, for the first time, that the full stack is worth
a 53% relative improvement over a well-tuned two-threshold rule. **Decision: retain the locked
baseline.** Nothing downstream changed.

### Submission polish

The Day-7 challenge was missing from the report, and the README had grown by accretion. I
added the trade-off table and the retain decision to the report and restructured the README.
Extending the traceability script immediately failed: the words "RETAIN LOCKED" were nowhere
in the report, although the decision was everywhere else. A machine check found what a
re-read would not.

### Learned component, real browser, production boundary

- **A learned model, chosen to avoid circularity.** The obvious model — "is this process a
  good automation candidate?" — would learn my own Opportunity score and hand it back as
  corroboration, so I did not build it. Instead I used labels that exist independently:
  Dataset A's 15 process codes. Can behaviour alone recover the process? Macro F1 0.2892 from
  behaviour, 0.5948 with system identity, against a 0.0646 baseline, with session-grouped
  folds. It confirms from another direction that process identity lives in system context. It
  is a validation signal only and feeds nothing.
- **A real browser.** `BrowserHRApplication` implements the same interface with Playwright,
  and the automation logic runs unchanged against a live Chromium page. The adapter holds no
  safety logic of its own, and a test checks that. 19 browser tests cover the routes, invalid
  input, missing and duplicate elements, a page change during review and double
  confirmation. It is labelled LOCAL VALIDATED, because it drives the local prototype page.
- **Service boundary.** Request and execution ids, a structured audit log that stores the
  note's length but never its text, credentials or tokens, a health endpoint, an error
  taxonomy and environment configuration. I changed `error_type` to a stable taxonomy and
  updated the three tests that asserted the old contract.

### Work-thread reconstruction, and auditing my own rejection

Every earlier attempt kept the per-transition framing. I tested a different idea: rebuild
hidden work threads from links between events. I split it into two preconditions that could
each kill it: interleaved work must exist (P1), and the logs must contain linking evidence
beyond timing (P2).

- **Signals.** No entity or element ids, screen text on 0.07% of events, content-free
  clipboard events, and a browser domain with effectively three values. Browser tab ids
  exist, but a tab lives across about 38 executions, so it identifies a container, not a unit
  of work.
- **A pairwise model.** My first 20-event window made the task trivially easy (89% positive,
  only 33 useful pairs). With gaps up to 600 events, the model looked excellent overall (AUC
  0.9897) but fell to F1 0.4657 at long range, and it relied mostly on timing. P2 rejected.
- **The decisive finding.** Ground-truth executions never overlap or nest (0 of 1,752), and
  no case returns after another intervenes. P1 rejected, so I did not build the graph.
- **Auditing the rejection.** I re-checked P1 with two unrelated methods, each first tested on
  synthetic interleaved data; all agreed on zero. An ablation corrected my own wording:
  linking features alone reach AUC 0.7651, so they are redundant with timing rather than
  absent. The conclusion held, but the reason changed. The open caveat: if a resumed
  execution is given a new case id, interleaving would be invisible by construction. I cannot
  tell from the data, so the report keeps "not observed" separate from "does not happen".

### Final presentation and documentation pass

In the last session I reworked how the finished project is presented. No analytical result
changed.

- **Frontend.** Grouped navigation by investigation stage; first-class Day 1–4 pages (data
  audit, reconstruction record with a trade-off chart, process mining, evidence health); a
  page top bar with dataset and evidence status; an investigation progress strip; a
  dashboard that puts the decision and the limitations side by side; the Decision Center as
  an engineering decision record; opportunity columns with a Pareto view; an experiment and
  rejection log with a validation summary; clearer replay metadata; and a five-step HR demo
  with visible REVIEW REQUIRED and SAFE STOP states. The new pages read an
  `investigation.json` produced by the data builder from existing artifacts; figures that
  exist only in a written report are checked against that report at build time. Machine host
  names are replaced by letters on the Day-4 page. I added 56 frontend and 11 Python tests
  and checked every page in a real browser at 1440, 1024 and 390 px.
- **Documents.** I rewrote the final report to a shorter evaluator structure, rewrote the
  README, moved the original brief to `docs/assignment_brief.md` unchanged, and restructured
  this log by day.
- **A sensitive-value fix.** `reports/day1/text_input_quality.md` quoted one synthetic test
  credential as an example. I removed the value; the finding is unchanged.

### AI use

AI implemented the sensitivity harness, the figure generator, the rule candidates, the
classifier experiment, the browser adapter, the audit log, the work-thread scripts, the
presentation-pass code and their tests, and drafted the reports. I stated the hypotheses so
they could fail, chose the thresholds as percentiles and not by outcome, kept the score
unchanged after seeing its fragility, ordered the rule candidates cheapest-first, excluded
window titles on prior evidence, rejected the circular model, kept safety logic out of the
browser adapter, split the work-thread idea into two falsifiable preconditions, re-checked my
own rejection, and decided what the presentation should and should not claim.

### End of day

Module 1 is canonical (F1 0.3440). HR / Payroll is the recommendation (Opportunity 0.4401,
94/122 = 77.05% on the dominant path, 55.89% of HR handling time). Module 2 is not promoted.
The prototype is validated on local targets only. Final counts: 1,130 Python tests (including
the 19 browser tests), 262 frontend tests, and 75/75 report numbers traced to artifacts.

---

## What did not work

| Day | Idea | What happened |
|---|---|---|
| 1 | Trusting `text_input_complete` counts | The profiler read the wrong field (100% missing → really 1.7%) |
| 2 | Window-title and clipboard signals | Lift 0.048 and 0.008 |
| 2 | Boundary-first classifier | 90.8% of executions fragmented |
| 2 | Continuity-first classifier alone | Fragmentation rose to 94.7% |
| 2 | Threshold re-tuning | Needs recall of about 0.15–0.21 |
| 2 | Reconnecting interrupted work | Nothing in the data to validate it |
| 2 | Design 2 without protection | Under-segmentation rose to 0.204 (2.4–3.3× the classifiers), in all 63 sessions |
| 2 | Agreement protection | Failed 3 of 7 gates |
| 2 | Segment coherence; global optimisation | Below their pre-registered bars |
| 3 | Browser domain as the Dataset-B signal | Thousands of near-empty segments |
| 3 | Timestamp-based execution rebuild | 16 of 94 executions misattributed |
| 3 | Raw-bit entropy | A real scoring bug; fixed |
| 4 | Pace explanation; window-title fallback | 1.02× against 1.27×; lift 1.10 |
| 6 | HMM; ensembles; behavioural clustering | F1 0.0194; ~225 false positives per extra boundary; ARI 0.264 |
| 6 | Module 2 | +0.0102 against +0.0200 required |
| 7 | Stable Opportunity ranking | Top candidate flips at the median merge threshold |
| 7 | Four simpler rules | All failed the registered gates |
| 7 | Work-thread reconstruction | No interleaving in the ground truth |
