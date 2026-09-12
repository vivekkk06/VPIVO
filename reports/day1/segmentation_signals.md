# Candidate Segmentation Signals (Part 21)

No segmentation algorithm is implemented here — this is signal evaluation
only, per instruction. Method for every "Evidence" cell marked *measured*:
for each of Dataset A's 1,689 real GT execution-to-execution boundaries,
checked whether a given event type/feature occurs within ±2s of the
boundary timestamp, and compared against the base rate / mid-execution
rate. Full method and additional signals: `segmentation_signal_analysis.md`
(this file restates it in the requested table format and adds the explicit
observed/hypothesis split).

## Engineering Reasoning

The assignment frames judgment about the approach as part of what's being
assessed, which I took to mean judgment should be backed by a number, not
intuition — even when the intuition is plausible. That's why every signal
here is explicitly labeled "measured" or "hypothesis" rather than
presented as one uniform list. Window titles looked genuinely promising
in the case-study screenshots, and it would have been easy to write that
up as a working signal. I decided not to, because "looks promising in one
inspected example" and "aligns with 1,689 real boundaries" are different
strength claims, and conflating them would have overstated what Day 1
actually established.

## Observed evidence (quantitatively measured against real GT boundaries)

| Signal | Why useful | Evidence | Limitation |
|---|---|---|---|
| Deduplicated application switches | A new process often means a new active application | **Measured**: 68.1% of 1,689 GT boundaries have an `app_switch` within ±2s | **Must deduplicate first** — 65% of raw `app_switch` events are exact back-to-back duplicates (see `data_quality_report.md` Part 5). 31.9% of boundaries have no app switch nearby (same-app transitions). |
| Extracted screen text presence | Reading the screen correlates with acting on new information, often right after a transition | **Measured**: 64.2% of boundaries have an `extracted_text`-bearing event within ±2s, vs. only 4.48% base rate — 14x concentration | Only 4.48% of events have it at all; largely co-occurs with `app_switch` (86% of non-empty text is on `app_switch` events), so it's not fully independent evidence from the app-switch signal |
| Temporal gap size | A pause plausibly marks "finished one thing, about to start another" | **Measured**: median gap at a boundary is 526ms vs. 52ms mid-execution (~10x); mean 3.4s vs. 486ms (~7x) | Distributions overlap heavily — no gap threshold cleanly separates boundary from non-boundary. Best used as a continuous weighted feature, not a hard rule. |
| GT process-transition structure itself (repeats, variants, cross-chunk) | Defines what "correct" looks like for validating any candidate approach | **Measured**: 2,009 executions, ~32/session, cross-chunk the norm (see `ground_truth_validation.md`) | Only available for Dataset A — Dataset B has no equivalent to validate against directly |

## Hypotheses for Day 2 (plausible from data inspection, NOT yet quantitatively evaluated)

| Signal | Why it might be useful | Evidence so far | Limitation / open question |
|---|---|---|---|
| Window title changes | Case IDs / process names sometimes visible in titles in case-study screenshots (qualitative only) | Not measured against GT boundary alignment this pass | Needs the same ±2s methodology applied before it can be trusted |
| Browser navigation / active tab URL | Portal URLs encode route fragments (e.g. `#/social-insurance`) that plausibly map to business function | Observed directly in raw events (qualitative) | Only covers L3 (browser) activity — most processes also spend time in Excel/Notepad, so URL alone would under-segment |
| Clipboard event *timing* (not content) | `gt.jsonl`'s own `clipboard_copy`/`clipboard_paste` are tied to specific `case_id`s | Clipboard events are far rarer than app_switch (5,198 vs. 50,588 total) — cheap to inspect exhaustively | `clipboard_change.payload.text_content` is **always null** (verified, Part 13) — timing/frequency only, never content, from this event type |
| Mouse/keyboard activity density dip | A brief "what next" pause might show as a density dip even below the raw gap threshold | Not measured | Would require windowed density computation not yet built |
| Case-boundary text via keystroke reconstruction | Verified exact-match reconstruction of typed content from linked keystrokes (Part 13) | One verified real case, not a systematic evaluation | Reconstruction works technically; whether the *content* itself is a useful segmentation feature (vs. just activity presence) is untested |

## Explicitly ruled out / low priority

| Signal | Reason |
|---|---|
| Raw (non-deduplicated) `app_switch` count | 65% inflated by exact-duplicate logging — unusable without the dedup step above |
| Screenshot presence/absence as a Dataset-A feature | 7.2% resolution rate — too sparse to be a primary Dataset-A signal (status unknown/untested for Dataset B's 81.2% until evaluated there specifically) |
| `text_input_complete` as ground truth for typed content | Schema explicitly warns it's unreliable; our own measurement found 98.3% content-present (better than feared) but still explicitly a hint per the documented caveat, not a primary source |
| `correlation.ms_since_last_event` (the field itself) as a gap feature | Found to be wrong (large negative values) at at least one real chunk boundary — recompute gaps from sorted `timestamp_ms` instead |

## Bottom line

No single measured signal exceeds ~68% boundary alignment alone. The
evidence supports a **combined-feature approach** for Day 2 (deduplicated
app-switch + extracted-text presence + gap size as a starting feature set),
with the three hypothesis-stage signals evaluated with the same rigor
before being added or dismissed.
