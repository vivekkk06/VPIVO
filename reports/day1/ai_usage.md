# AI Usage Log (Part 23) & Engineering Contribution (Part 24)

**See `ai_assisted_engineering_workflow.md` for the fuller, more accurate
account of the engineering ownership split** — this file's original
framing leans more heavily on "AI implemented, I reviewed" phrasing than
is actually representative; the fuller account leads with the requirements
and methodology that were specified as this project's engineering
direction before the corresponding implementation existed. Both describe
the same underlying facts; kept here for continuity, not because it's the
preferred framing.

Written plainly: this Day 1 work was done through Claude (Claude Code)
acting as the implementing engineer inside an interactive session, with
direction, scope decisions, and review coming from the person running that
session. This log does not claim manual authorship of code that was
AI-generated, and does not inflate the human side of the work beyond what
actually happened in the conversation.

## Engineering Reasoning

The assignment explicitly says AI use is allowed and should be disclosed,
so my reasoning here wasn't "should I admit this" — it was "how do I
describe it accurately without either hiding it or performing false
modesty about my own role." I decided the honest split is: AI did the
implementation and execution; I did the direction, the scope, the quality
bar, and the review. I did not want this document to read as either "the
AI did everything, I typed the prompts" or "I built this myself with AI
help" — both understate or overstate something true, and I'd rather the
description hold up if someone asked a specific follow-up question about
who wrote a particular function.

## Part 23 — AI Assistance Table

| Activity | AI assistance | Review / decision | Outcome |
|---|---|---|---|
| Reading README.md/DATA_SCHEMA.md and forming the initial project design | Summarized the spec, proposed a package layout and design decisions (session-level loading, screenshot-path resolution strategy, no-ML-yet scope) | Design was reviewed and accepted as presented, no changes requested | Adopted as the Day 1 architecture |
| Writing all loader/validation/profiling/audit/cleaning code | Fully AI-written (`models.py`, `paths.py`, `loaders/`, `validation.py`, `profiling.py`, `viz.py`, `audit.py`, `cleaning.py`, all `scripts/`) | Not manually written or line-edited by hand | Working code, verified by running it, not just by inspection |
| Running code against real data and interpreting results | AI executed every script and inspected raw files directly (e.g. pulling real `events.jsonl` lines to check field names) rather than trusting the schema doc alone | Direction to "actually look at the data" and "audit before trusting" was an explicit instruction that shaped this | Caught 2 real bugs (manifest-crash, wrong field name) and several real data findings that doc-reading alone would have missed |
| Duplicate/timestamp/GT/cross-file audit design | AI proposed and implemented the specific checks (exact/semantic/sequential duplicates, ms-vs-iso consistency, split_id scoping, etc.) | Scope for the audit (this exact list of 29 parts) was specified in detail by the requester, not left to AI's own judgement about what to check | Comprehensive, evidence-backed audit rather than an arbitrary subset |
| Writing tests | Fully AI-written (36 tests total) | Requirement that tests "verify behavior, not merely line coverage" was an explicit instruction followed during writing | 36/36 passing, each test tied to a specific real or synthetic scenario |
| Debugging (the 3 issues in `debugging_log.md`) | AI diagnosed root cause, implemented fixes, and re-verified in each case | Requirement to document AI mistakes explicitly, including root cause and lesson, rather than silently fixing and moving on | 1 real crash bug fixed + tested; 1 false finding caught and corrected before being reported; 1 genuine data-source defect identified and documented (not "fixed," since it's not our bug) |
| Interpreting anomalies (app_switch duplication, screenshot asymmetry, GT split_id gap) | AI performed the statistical analysis and drew the initial interpretation | Instruction to distinguish "facts observed" from "conclusions/inferences" was explicit and shaped how these are written up (e.g. "65% duplication, looks like a double-firing bug" is flagged as inference, not asserted as certain) | Findings are presented with their evidence and confidence level stated, not as unconditional truth |
| Report writing (all files under `reports/day1/`) | Fully AI-written | Structure and required sections (the 29-part outline) were specified in detail by the requester | Documents match the requested structure and cite real command output throughout |
| Git strategy | AI proposed a commit sequence broken into logical, reviewable units | Explicit instruction that the requester will write and execute the actual `git commit` messages themselves, in their own words, on their own schedule | Nothing has been committed by this process — staging/commit execution is intentionally left to the requester |

## Part 24 — Engineering Decisions Attributable to Direction, Not the Model

Reported only what's actually supported by the conversation — not
exaggerated, not invented:

- **"Audit before trusting" as a working principle**: the decision to treat
  the morning's own working code as unverified until re-tested, rather than
  accepting it because it existed and had passed its own tests, was an
  explicit instruction, not something the AI decided to do unprompted.
- **Raw data immutability as a hard rule**: stated explicitly and enforced
  structurally (cleaning takes in-memory dicts, never a file path;
  `.gitignore` keeps raw datasets out of version control entirely) because
  it was specified as non-negotiable up front.
- **Scope boundary: no segmentation algorithm yet**: repeated explicitly
  across both work sessions today — this kept Day 1 focused on
  understanding/validation rather than drifting into premature modeling,
  which is an easy trap to fall into once the data "looks ready."
- **Requiring percentile statistics (p90/p95/p99), not just mean/median**:
  this specific requirement is what surfaced the `ms_since_last_event`
  negative-value finding — a mean/median-only summary would have hidden it
  entirely (the median, 44ms, looks completely unremarkable).
- **Requiring explicit UNVERIFIED/fact-vs-inference labeling**: this is why,
  for example, `segmentation_signals.md` separates "observed evidence"
  from "hypotheses for Day 2" instead of presenting untested ideas as
  established signals.
- **Rejecting an AI-generated number without re-derivation**: when this
  report's first draft stated "54 of 63 sessions have 2+ chunks" without
  having actually run that count, it was caught and re-verified against
  the real data before being left in the report (corrected to 53) — an
  example of the "verify, don't assume" principle being applied to this
  very report-writing process, not just to the underlying data pipeline.
- **Deciding not to edit README.md**: treating the assignment brief as
  read-only source-of-truth rather than "the project's README to update,"
  even though a generic instruction said to update it "if necessary" —
  judged not necessary and documented why, rather than complying literally
  in a way that would overwrite the task specification.
- **Deferring commit execution and message wording entirely**: choosing to
  write commit messages in one's own words, on one's own schedule, rather
  than accepting AI-authored commit messages verbatim, was a standing
  decision maintained across the whole engagement.

None of the above claims manual line-by-line code authorship — the honest
account is that direction, scope, required rigor, and final review came
from the requester, and implementation, execution, and analysis were
performed by Claude, checked against real data at every step described in
this report.
