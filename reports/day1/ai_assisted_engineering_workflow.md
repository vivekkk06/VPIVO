# AI-Assisted Engineering Workflow

I used an AI coding assistant as an implementation and analysis
accelerator. I remained responsible for defining the requirements,
deciding what to investigate, setting validation criteria, reviewing
outputs, challenging suspicious results, choosing between alternatives,
and determining when the evidence was sufficient to move forward. This
document replaces the earlier, more implementation-centric framing of AI
usage with one that reflects that division of labor accurately — it does
not hide AI's role, and it does not overstate hands-on coding that didn't
happen either.

## Ownership by Area

| Area | My ownership | AI assistance | Verification/decision |
|---|---|---|---|
| Project structure | Defined the required architecture (a reusable package, not loose scripts) and the scope (loaders/validation/profiling/audit/cleaning, no ML) | Implemented the scaffolding, `.gitignore`, dependency list | Verified by repository inspection and a clean `pip install` on the actual environment |
| Data loading | Required session-level loading specifically because chunks are storage boundaries, not process boundaries, per the schema | Implemented `load_session_events`, multi-chunk merge, chronological sort | Verified against a published estimate (162,768 vs. README's ~162,000) and against measured cross-chunk GT behavior (53/63 sessions multi-chunk) |
| Data-quality audit | Defined the required audit categories in detail (exact/semantic/sequential duplicates, missingness classification, timestamp percentiles, event-type/layer consistency, payload shape) | Implemented the checks in `audit.py` and ran them | Verified via direct execution against real Dataset A/B and by inspecting real raw examples for the most surprising results |
| Ground-truth validation | Required cross-checking `gt.jsonl` against `gt_manifest.json` rather than trusting either alone; required the documented quirks be handled without silently "fixing" them | Implemented the reconstruction state machine and the deeper checks (resume/suspend/overlap) | Verified by direct field-by-field comparison of the one disagreement found (the abandoned suspension's `split_id`) |
| Signal analysis | Required that no signal be reported as effective without being measured against real GT boundaries | Implemented the ±2s boundary-alignment method and ran it against all 1,689 transitions | Verified by checking the alignment numbers against the underlying event data directly, not just accepting the aggregate percentage |
| Testing | Required behavior/regression tests specifically — a test for every real bug found, not just coverage for new code | Implemented all 36 tests | Verified by running the full suite repeatedly across every phase of the project |
| Debugging | Required robustness testing rather than accepting success on clean data as sufficient | Diagnosed root cause and implemented both fixes (manifest crash, field-name bug) | Required each fix be verified against the original failure scenario before being accepted, and covered by a named regression test |
| Reports | Defined the required structure, evidence standard (numbers must trace to a script), and the fact/inference/assumption separation | Drafted every report | Verified for internal consistency and re-checked at least one unverified claim before it stayed in a report (an uncounted "54 of 63" corrected to 53 after re-counting) |

## My Contribution vs. AI Contribution

| Responsibility | Me | AI |
|---|---|---|
| Problem definition | Primary | Assist |
| Scope | Primary | Assist |
| Methodology | Primary | Assist |
| Requirements | Primary | Assist |
| Engineering decisions | Primary | Assist |
| Investigation direction | Primary | Assist |
| Code implementation | Assisted / AI-heavy | Primary |
| Test implementation | Defined criteria | Primary implementation |
| Data execution | Reviewed/validated | Primary execution |
| Interpretation | Primary decision owner | Analysis support |
| Documentation | Defined structure/content requirements | Drafting |
| Final acceptance | Primary | None |

No percentages are used here beyond what's directly counted elsewhere in
this project (test counts, event counts, duplication rates) — this table
describes roles, not a weighted split, because a weighted split isn't
something the available evidence actually supports measuring.

## What I Would Say In an Interview

### "How much of this project did you actually do yourself?"

"I used AI heavily as a coding and analysis accelerator, so I don't want
to pretend I manually typed every implementation. My responsibility was
broader than typing code, though. I owned the problem framing, scope,
methodology, validation criteria, and engineering decisions. I decided
what needed to be checked, questioned suspicious results, required
raw-data verification, chose what transformations were safe, and decided
when the evidence was sufficient to move to the next stage. For example, I
didn't accept an early result showing 100% of `text_input_complete` events
were missing content — it read as too extreme given what the
documentation actually said, so the raw event structure had to be checked
before we reported it, and it turned out a field-name assumption was
wrong. Similarly, I chose not to delete the 65% duplicate `app_switch`
events I found, because doing that quietly would have hidden a
segmentation assumption inside a data-cleaning step instead of leaving it
visible for the actual segmentation work to decide on and validate. So AI
accelerated implementation, but I owned the engineering process and the
decisions that came out of it."

### 20-second version

"I used AI as a coding and analysis accelerator, but I owned the
engineering decisions. I defined the scope, methodology, validation
criteria, and what needed to be investigated, then reviewed the evidence
and decided what to accept, reject, or defer. The AI made implementation
faster; it didn't replace the project decisions."

## Where This Replaces the Earlier `ai_usage.md`

The original `ai_usage.md` (kept in place, not deleted) documents the same
underlying facts but leans more heavily on "AI implemented X, I reviewed
it" phrasing throughout. This document is the more complete account —
the requirements and methodology listed above were, in the large majority
of cases, specified in writing before the corresponding implementation
existed, which is a stronger and more accurate claim than "reviewed
afterward." Both documents describe a real AI-assisted engineering
project; this one describes the direction-setting side of it more fully.
