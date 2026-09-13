# Stage 8.4 — Forensic Investigation of Rule 4's 296 Wrongly-Demoted Real Boundaries

**Diagnostic only.** Stage 8.3's reconstruction is not changed, no new
rule is implemented, no classifier is trained, Dataset B is untouched.
V1/V2's exact LOSO procedures (thresholds 0.9078/0.8860, unchanged) and
Design 2's exact rule application (selected threshold τ=0.40, reused, not
re-selected) are re-run solely to reproduce the same two populations
Stage 8.3 already reported. **Cross-check: this run reproduces exactly
3,667 (Population A) and 296 (Population B), matching Stage 8.3's
numbers precisely** — confirming this investigation is looking at the
same decisions, not a re-derivation with different behavior.

Source: `src/procmine/segmentation/rule4_forensics.py` (hostname/port
parsing, candidate-source classification — unit-tested),
`scripts/analyze_rule4_errors.py` (orchestration).

## Definitions (reused, not redefined)

- **Population A** (n=3,667): Rule 4 demoted it, and GT says it is a
  false internal boundary (both endpoints inside one GT execution's
  span — Stage 2/8's exact definition, reused).
- **Population B** (n=296): Rule 4 demoted it, but GT says it is a real
  boundary (`is_boundary=True`, unchanged `label_transitions` label).
- Ratio A:B = 12.39:1 — matches Stage 8.3's reported ~12:1.

## 1. Count and proportion

n_A=3,667, n_B=296. B is 7.47% of all Rule-4 demotions.

## 2. Distribution comparison (selected signals; full table in the JSON)

AUC convention (Stage 5's, reused): B is the positive class. AUC far
from 0.5 in either direction = separating; near 0.5 = uninformative.

| Signal | A median | B median | AUC (B+) | \|AUC−0.5\| |
|---|---|---|---|---|
| `event_type_jaccard` | 0.600 | 0.500 | 0.247 | 0.253 |
| `after_window_duration_ms` | 2,056 | 5,484.5 | **0.712** | **0.212** |
| `density_after` | 19 | 8 | 0.288 | 0.212 |
| `flagged_by_both_models` (rate) | 66.3% | 90.9% | **0.623** | **0.123** |
| `browser_domain_jaccard_with_port` | — | — | 0.610 | 0.110 |
| `delta_t_ms` | 2,590 | 3,790 | 0.593 | 0.093 |
| `v1_score` (raw probability) | 0.951 | 0.944 | 0.484 | 0.016 |
| `v2_boundary_score` | 0.926 | 0.925 | 0.522 | 0.022 |
| `application_changed`, `window_title_changed`, `chunk_boundary`, `duplicate_app_switch`, `hostname_changed`, `port_changed`, `high_event_type_jaccard_but_context_changed` | — | — | 0.42–0.53 | ≤0.08 |

**Raw model confidence does not separate A from B at all** (AUC
0.484/0.522) — Population B is not "low confidence" or "high confidence"
relative to A; this rules out "just trust the raw score more" as an
explanation.

## 3. Candidate-source breakdown — the strongest new finding

| | A | B |
|---|---|---|
| Flagged by both V1 and V2 | 66.3% | **90.9%** |
| V1 only | 19.6% | 4.1% |
| V2 only | 14.2% | 5.1% |

**When both models independently agree a transition is a boundary, it
is far more likely to be a real boundary Rule 4 is wrongly demoting than
a false internal one it's correctly demoting.** AUC 0.623 — moderate,
clearly away from 0.5, and (per §item 11 below) robust across sessions.
Rule 4 currently ignores this entirely — every candidate reaching it is
treated identically regardless of whether one or both models flagged it.

## 4. Leave-and-return involvement

**0/3,667 and 0/296 — mechanically zero for both, not a substantive
finding.** This is expected, not surprising: Rule 2 already removes
every return-pattern-involved candidate from consideration *before* Rule
4 ever sees it, by construction of the rule ordering. A candidate that
still reaches Rule 4 cannot, by definition, have been caught by Rule 2's
own detector. Reported for completeness per the brief, not evidence that
return patterns are irrelevant in general.

## 5. Local positional pattern (±1 immediate event, no GT scoping)

Immediate-neighbor event types differ noticeably: population B's
immediately-following event is `app_switch` far more often than
population A's (full breakdown in the JSON) — consistent with, and a
narrower echo of, the fuller §6 composition finding below.

## 6. N=10 composition (not just the Jaccard scalar)

The after-window's event-type composition differs qualitatively, not
just numerically:

| Event type in after-window | Population A | Population B |
|---|---|---|
| `keystroke` | 81.0% | *(not in top 5)* |
| `shortcut` | 78.0% | *(not in top 5)* |
| `app_switch` | 70.0% | **96.3%** |
| `browser_navigation` | *(not in top 5)* | **69.9%** |
| `browser_click` | *(not in top 5)* | **69.6%** |

**Population A's aftermath looks like ongoing, steady work (keystrokes,
shortcuts). Population B's aftermath looks like orientation/navigation
activity (app-switching, browser navigation, clicking) — the signature
of someone starting a new execution, not continuing one.** This gives a
mechanistic, causally plausible explanation for §2's `after_window_duration_ms`
and `density_after` findings: navigation-heavy activity naturally
proceeds at a different pace than steady keystroke-driven work, so a
window dominated by navigation looks "slower per event" even though it
is not more or less "continuous" in the Jaccard sense.

## 7. Application / browser / window context

| | A | B |
|---|---|---|
| Same application before/after | 92.4% | 99.0% |
| Same browser host | 1.0% (n=2,754) | 0.7% (n=272) |
| Same browser port | 1.0% (n=2,746) | 0.7% (n=272) |
| Same interaction category | 0.5% | 2.7% (n=8 — too small to trust) |
| High event-type jaccard but app/domain/window changed | 69.0% | 70.6% |

**None of these separate A from B.** Same-application is common in both
(92–99%) — consistent with every prior stage's finding that
`application_changed` is a weak signal generally, not specific to this
population. Same-host/same-port are rare in both (~1%) — most
transitions in this already-flagged population involve *some* browser
navigation regardless of GT truth. The "high jaccard but context
changed" combination occurs at essentially the same rate in both
(69.0% vs. 70.6%) — **explicitly rejected as a useful signal**: it does
not add anything beyond what `event_type_jaccard` and the individual
"changed" booleans already show separately.

## 8. Gap regime — inconclusive, and explicitly not assumed

| | median (ms) | p90 |
|---|---|---|
| All GT true boundaries (n=1,671) | 526 | 4,381 |
| Population A (n=3,667) | 2,590 | 15,007 |
| Population B (n=296) | 3,790 | 17,370 |

Pooled, B's gap looks *larger* than both A's and the typical real
boundary's — the opposite of "B has an unusually small gap that fooled
the model." But §11's robustness check (below) found `delta_t_ms`'s
pooled separation **does not hold up session-by-session** (only 41.3%
directional agreement — worse than chance). **Conclusion: no reliable
gap-regime distinction was found for population B; the pooled numbers
are most likely a cross-session aggregation artifact** (Stage 4 already
documented an 11.8x range in session-level gap medians), not a real
population-level effect. Reported honestly as inconclusive, per the
brief's explicit instruction not to assume a larger gap means a true
boundary.

## 9. Session concentration

Population B appears in **all 63 of 63 sessions** (mean 4.7, median 4,
max 10, min 1 per session). **Not concentrated** — no single session
drives more than 3.4% of the 296 cases. This directly supports treating
the top signals found in §11 as general phenomena, not artifacts of one
unusual session.

## 10. Process concentration (post-hoc GT use only)

`prev_process_code` and `next_process_code` for the 296 cases spread
across all ~15 process codes roughly evenly (counts 5–37 per code, no
single process dominating). **Not concentrated in a particular process
family.** Only 8.1% (24/296) are resume boundaries — the large majority
of population B are "genuinely new process starting" moments, not
interrupted-work resumptions, consistent with §6's navigation-heavy
aftermath finding (starting fresh work often begins with orientation
activity). This process/case information was used only here, after
every reconstruction decision had already been made without it.

## 11. Candidate discriminative signals — full verdicts

Applying the brief's six criteria (separates A/B; raw-event-derived;
GT-free; available at reconstruction time; not a duplicate of
`event_type_jaccard`; robust across sessions) to every signal measured,
with the session-robustness check (agreement between each session's own
A-vs-B direction and the pooled direction) as the final filter:

| Signal | AUC | Session agreement | Verdict |
|---|---|---|---|
| `after_window_duration_ms` | 0.712 | **88.9%** (56/63) | **Strong candidate** — passes all 6 criteria |
| `flagged_by_both_models` | 0.623 | **88.9%** (56/63) | **Strong candidate** — passes all 6 criteria, orthogonal to every trajectory feature |
| `density_after` | 0.288 | 87.3% (55/63) | Real and robust, but likely **redundant with `after_window_duration_ms`** — both measure post-transition activity pace via different arithmetic (events-per-fixed-time vs. time-per-fixed-events); treat as one finding, not two |
| `event_type_jaccard` (within the already-demoted population) | 0.247 | 93.6% (59/63) | Confirms B sits closer to the τ=0.40 boundary than A, but this describes *Rule 4's own feature*, not a new, independent signal |
| `browser_domain_jaccard_with_port` | 0.610 | 94.7% (54/57 eligible) | Directionally robust where data exists, but only 57/63 sessions have enough browser context to compute it — **limited generality**, not rejected outright |
| `delta_t_ms` / `log1p_delta_t_ms` | 0.593 | **41.3%** (26/63 — worse than chance) | **Rejected** — pooled separation does not survive the session-robustness check; almost certainly a cross-session scale artifact |
| `application_changed`, `window_title_changed`, `chunk_boundary`, `duplicate_app_switch`, `hostname_changed`, `port_changed`, `high_event_type_jaccard_but_context_changed`, `v1_score`, `v2_boundary_score`, `interaction_category_jaccard`, `application_jaccard`, `window_title_jaccard`, `browser_domain_jaccard_host_only`, `before_window_duration_ms`, `density_before` | 0.42–0.55 | — | **Rejected** — AUC within ~0.08 of 0.5, no meaningful separation |

## What this does and doesn't mean

**Two robust, non-redundant, reconstruction-time-available, GT-free
signals were found**: cross-model agreement (`flagged_by_both_models`)
and post-transition activity pace (`after_window_duration_ms`, with
`density_after` as a redundant restatement of the same underlying
"tempo" concept). Both separate A from B at a moderate level (AUC
0.62–0.71) and hold up in ~89% of sessions individually — not an
artifact of a handful of sessions or a single dominant process.

**This does not mean the 296 errors are fully explained or trivially
fixable.** AUC 0.71 is moderate, not decisive — A's and B's
`after_window_duration_ms` interquartile ranges still overlap
substantially (A: 852–3,131ms; B: 1,695–6,431ms). A rule built on these
signals would likely recover *some*, not all, of the 296 — and would
need its own full evaluation (including a fresh under-segmentation
check) before counting as an improvement, exactly like Stage 8.3's own
experiment. **No such rule is proposed or implemented here.**

## Files

- `src/procmine/segmentation/rule4_forensics.py`
- `tests/test_rule4_forensics.py` (13 tests)
- `scripts/analyze_rule4_errors.py`
- `reports/day2/rule4_error_forensics_dataset_a.json`
- `reports/day2/rule4_error_forensics.md` — this file
