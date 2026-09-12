# Interview Preparation — Day 1

Every number here is real and reproducible (see `day1_readiness.md` for
the exact commands). Answers describe the work accurately: AI implemented,
the project owner directed, reviewed, and decided.

---

### 1. What exactly did you do on Day 1?

**Short answer**: I built and validated a data-loading and data-quality
foundation for a 162,768-event operation log dataset before writing any
segmentation logic — loaders, an audit covering duplicates/timestamps/
missing values/cross-file consistency, ground-truth validation, profiling,
and five representative case studies, all backed by tests.

**Deeper**: The assignment needed logs turned into recovered business
processes eventually, but I didn't trust the raw data enough to start
there. I treated Day 1 as answering one question: can I trust what a count
or a timestamp in this log actually means? That led to building loaders
that merge multi-chunk sessions correctly, a validation layer that reports
issues instead of crashing, and an audit that found real problems —
a 65% duplication rate in `app_switch` events, a screenshot-availability
gap that's completely different between the two datasets, and one actual
crash bug in my own loader that I found by deliberately feeding it
corrupted input.

**Likely follow-ups**: "Why not just start segmenting and fix data issues
as you find them?" / "How long did this actually take?" (**time is NOT
VERIFIABLE from available evidence — no timestamps were recorded**).

---

### 2. Why didn't you start segmentation immediately?

**Short answer**: Because a segmentation feature built on data I hadn't
audited would have been built on top of at least one instrumentation bug I
didn't know about yet — the app-switch duplication would have silently
inflated any feature counting switches.

**Deeper**: The assignment itself says judgment about how to spend the
available days is part of what's evaluated. Jumping to segmentation the
moment the data "looks loadable" is a common trap — clean-looking JSON
doesn't mean trustworthy counts. I found that out directly: validation
passed cleanly (0 schema violations), but the deeper audit found 65% of
`app_switch` events were exact duplicates. If I'd built a segmentation
feature on raw app-switch frequency first, I'd have gotten a plausible but
wrong number and had no idea why.

**Likely follow-ups**: "What would have happened if you'd found nothing in
the audit?" / "How do you know when data-quality work is 'enough'?"

---

### 3. Why is a chunk not a process boundary?

**Short answer**: The schema says so explicitly, and the ground-truth data
confirms it — the majority of the 2,009 recorded process executions in
Dataset A span more than one chunk.

**Deeper**: A chunk is purely a recording-agent artifact — the agent
flushes to a new file periodically regardless of what the user is doing.
Fifty-three of Dataset A's 63 sessions span multiple chunks. If I
processed chunks independently, an execution that starts in one chunk and
finishes in the next would get split into two incomplete, wrong segments.
That's why the loader merges an entire session's chunks into one
chronological stream before anything else runs.

**Likely follow-ups**: "How do you merge chunks correctly — what if
they're out of order?" / "What if an event's own metadata says the wrong
chunk?" (real answer: found exactly one case of that, out of 162,768
events).

---

### 4. What were the biggest data-quality issues?

**Short answer**: 65% of `app_switch` events are exact duplicates; a
screenshot-availability rate of 7.2% in Dataset A versus 81.2% in Dataset
B; and a `ms_since_last_event` field that can be off by over ten minutes
at a chunk boundary.

**Deeper**: Each mattered differently. The app-switch duplication is a
feature-engineering trap — if you don't know about it, you'll build a
wrong feature confidently. The screenshot asymmetry is a dataset-transfer
trap — anything I concluded from Dataset A about screenshots being
unavailable would have been wrong for Dataset B, the dataset that actually
gets used. The `ms_since_last_event` issue is a "don't trust a field just
because the agent computed it" lesson — I found it by requiring percentile
statistics, not just averages; the median (44ms) looked completely normal.

**Likely follow-ups**: "How did you verify the 65% number wasn't a bug in
your own analysis?" / "What did you do about the screenshot gap?"

---

### 5. Why didn't you simply remove duplicate app-switch events?

**Short answer**: Because deciding what counts as "one real switch" is a
segmentation-level judgment call, and making that decision silently inside
a cleaning step would remove my ability to evaluate whether it was even
the right call, against ground truth, later.

**Deeper**: My cleaning layer only does transformations where the correct
output is unambiguous from the raw data alone — exact-duplicate record
removal, chronological sorting. Deduplicating app-switches requires
deciding "these two events represent the same real action," which is
exactly the kind of interpretive decision Step 1 exists to make
deliberately and validate. So I documented the 65% finding as a required
precondition for building an app-switch feature, but left the raw stream
untouched.

**Likely follow-ups**: "Isn't that just kicking the problem down the
road?" (answer: no — it's making the decision visible and testable instead
of invisible and untested) / "What would the dedup logic actually look
like?"

---

### 6. What did you learn from the ground truth?

**Short answer**: That it's strong evidence, not an infallible oracle —
`gt.jsonl` and `gt_manifest.json` disagreed about one real execution, and
cross-checking one against the other is what caught it.

**Deeper**: I reconstructed 2,009 executions from `gt.jsonl`'s raw event
stream and cross-checked the counts against `gt_manifest.json`'s
ready-made summary — 0 disagreements at the count level, across all 63
sessions. But when I added deeper checks (suspend-without-resume, in
particular), I found one execution that was suspended and never resumed
within its session — a genuinely abandoned process, not a parsing bug —
and `gt_manifest.json`'s own summary doesn't record that it was ever
suspended at all, even though `gt.jsonl`'s raw stream shows it clearly.

**Likely follow-ups**: "How do you know that's a real GT inconsistency and
not a bug in your parser?" (answer: verified by reading both files'
records for the same `case_id` directly, field by field) / "What does this
mean for Dataset B, which has no ground truth at all?"

---

### 7. How did you validate your segmentation signals?

**Short answer**: I measured how often each candidate signal falls within
±2 seconds of a real GT process-transition boundary, across all 1,689
boundaries in Dataset A — not a sample, and not intuition.

**Deeper**: Three signals were actually measured this way: deduplicated
app-switch presence (68.1% alignment), extracted-text presence (64.2%,
against only a 4.48% base rate — a real concentration), and gap size
(boundaries have a ~10x larger median gap than mid-execution). Three more
— window title, browser URL, clipboard timing — looked promising in
case-study inspection but were explicitly left as unmeasured hypotheses,
because "looks promising in a screenshot" and "measured against 1,689 real
boundaries" are different claims, and I didn't want to conflate them.

**Likely follow-ups**: "Why ±2 seconds and not some other window?"
(**reasonable engineering choice, not independently re-derived from a
sensitivity analysis this pass — worth stating honestly if asked**) / "What
would you do if none of the signals reached that alignment rate?"

---

### 8. Why use percentiles instead of just averages?

**Short answer**: Because a mean or median can completely hide a rare but
severe defect — which is exactly what happened here.

**Deeper**: `ms_since_last_event`'s median was 44 milliseconds — totally
unremarkable. Its p99 was 5,060ms, and its actual minimum was -713,900
milliseconds — over eleven minutes negative. None of that shows up if you
only report the mean or median. Requiring the full percentile spread (p90/
p95/p99/max/min) is what surfaced this, and it turned out to corroborate a
separate finding (a chunk-identity metadata glitch) at the exact same
point in the data.

**Likely follow-ups**: "How rare was this, really?" (443 of 162,314 gap
values, 0.27%, below -1,000ms) / "Did you fix the negative values?" (no —
it's a property of the source data, not something to alter; the fix was
never trusting that field directly for gap-based analysis).

---

### 9. What bug did you find?

**Short answer**: A single corrupted `manifest.json` file crashed the
entire session load — and separately, my own first-pass analysis of one
event type used a wrong field name and reported a false "100% missing"
finding.

**Deeper**: The manifest bug was a real code defect — one whole-file JSON
parse had no error handling while the equivalent line-level parser for
events did. The `text_input_complete` issue was an analytical mistake:
checking `payload.text`/`content`/`value` when the real field is
`payload.final_text`, which isn't named in the schema documentation at
all. Both were caught by deliberately testing against a failure case
(corrupted input) or a real raw example (an actual event's payload)
rather than trusting the first version.

**Likely follow-ups**: "Who actually found these — you or the AI?" (honest
answer: the AI process performed the diagnosis within this project's
sessions; my role was requiring the stress-test and the verification step
that surfaced each one, and reviewing/accepting the fix) / "Could there be
more bugs like this you haven't found?" (yes, reasonably — no fuzzing was
done beyond the one manifest-corruption scenario).

---

### 10. How did you test the fix?

**Short answer**: By reproducing the exact original failure and confirming
it no longer crashes, then adding a regression test so it can't silently
come back.

**Deeper**: For the manifest bug, I re-ran the identical
corrupted-manifest scenario post-fix and confirmed the session still loads
its 2,348 events, with the corruption now recorded instead of raised. For
the field-name mistake, I re-ran the profiler against all 118 real
`text_input_complete` events and got the corrected 98.3%/1.7% split. Both
now have a named test in the suite (36 tests total, 36/36 passing) that
specifically encodes the original failure scenario.

**Likely follow-ups**: "What's your test coverage like overall?" / "What
would a code reviewer push back on in this test suite?" (fair answer: no
automated end-to-end integration test runs the full CLI pipeline against a
real dataset — that was done manually and repeatedly, not codified).

---

### 11. What role did AI play?

**Short answer**: AI implemented essentially all of the code, ran every
script, and performed the initial diagnosis on every bug and finding. I
defined the scope, set the quality rules, reviewed what came back, and
made the decisions.

**Deeper**: I'm not going to pretend I hand-wrote the loaders or the audit
functions — I didn't. What I did was specify what needed to exist (session-
level loading because of the chunk/process distinction; specific audit
categories; a conservative cleaning boundary), require rigor (percentiles
not just averages, fact/inference separation, explicit documentation of
AI mistakes rather than silent fixes), and decide what counted as done.
The assignment explicitly allows and expects AI use to be disclosed — this
is that disclosure, stated plainly rather than minimized.

**Likely follow-ups**: "So what did you actually contribute?" (see next
question) / "Are you worried this looks like you didn't do the work?"
(the work that's mine is the direction, the standards, and the judgment
calls — which is a real and different skill from typing code, and I'd
rather be honest about which one this was).

---

### 12. What did YOU personally contribute?

**Short answer**: Scope definition, the specific quality bar (percentiles,
no fabrication, fact/inference separation, raw-data immutability), review
of every result, and the judgment calls about what mattered and what
didn't.

**Deeper**: Concretely: I set the rule that segmentation couldn't start
until signals were measured, not assumed. I required the deeper GT checks
that found the abandoned-suspension case. I required percentile stats
specifically, which is what found the `ms_since_last_event` anomaly. I
required that AI-generated mistakes be documented with root cause rather
than quietly patched. And when an earlier draft of one of my own reports
stated an uncounted number ("54 of 63 sessions"), I required it be
re-verified before it stayed in the report — it was wrong (53).

**Likely follow-ups**: "Isn't that just prompt engineering?" (it's project
direction and quality control applied to an AI-assisted pipeline — which
is an increasingly real skill, and I'd rather describe it accurately than
oversell the hands-on-coding version of it).

---

### 13. What would you do next on Day 2?

**Short answer**: Measure the three unevaluated signal hypotheses (window
title, browser URL, clipboard timing) with the same ±2-second boundary
method already built, before writing any segmentation logic.

**Deeper**: I don't want to design a segmentation algorithm around
assumptions I haven't tested — the same discipline that found the
app-switch duplication and the screenshot asymmetry applies here. Once
those three are measured, the actual Step 1 design work starts: likely a
combined-feature scorer rather than a single hard rule, since no single
measured signal exceeds ~68% alignment alone.

**Likely follow-ups**: "How would you combine the signals?" (open design
question — not yet decided, honestly) / "How would you validate the
result against Dataset B, which has no ground truth?" (open problem,
explicitly flagged as unresolved in Day 1's own reports).

---

### 14. What are the biggest risks in Dataset B?

**Short answer**: No ground truth to validate against, and at least one
Dataset-A finding (the app-switch duplication rate) already confirmed not
to transfer — all 15 Dataset B sessions showed 0% of that duplication
pattern.

**Deeper**: Every accuracy-style claim in this project is Dataset-A-only
by necessity. Dataset B's mechanical checks (schema validity, timestamp
consistency) were run independently and came back clean, but that doesn't
mean Dataset A's behavioral quirks transfer — and the one I explicitly
checked, didn't. Screenshot availability is the opposite risk: Dataset A
underrepresents it (7.2%) while Dataset B has it mostly available (81.2%),
so a design that ignores screenshots based on Dataset A alone would be
leaving a real signal on the table for B.

**Likely follow-ups**: "How would you self-validate a segmentation
approach with zero labels?" (open problem for Day 2 — distributional
sanity checks and manual spot review are the plausible directions, neither
built yet).

---

### 15. What would make an automation candidate attractive?

**Short answer**: That's a Step 2/3 question I haven't reached yet — Day 1
was scoped to data understanding, not automation prioritization.

**Deeper**: I can say what Day 1's findings imply for that later
decision: a process needs to be reliably segmentable (high signal
alignment, low variant ambiguity) before it's a safe automation target,
because you can't automate what you can't first reliably identify. The
GT data shows real variation in "difficulty" per process (variant counts,
suspend/resume frequency), which will matter once Step 2 starts ranking
candidates — but I haven't done that ranking yet, and I'm not going to
claim I have.

**Likely follow-ups**: "So what's blocking that analysis right now?"
(Step 1's segmentation output on Dataset B, which doesn't exist yet — Day
1 explicitly stopped short of building it).
