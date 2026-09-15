# Instrumentation Health Analysis (Day 4)

Module: `src/procmine/instrumentation_health.py` (diagnostic-only).
Scripts: `scripts/analyze_instrumentation_health.py`,
`scripts/run_instrumentation_sensitivity_check.py`.
Artifacts: `instrumentation_health_dataset_a.json`,
`instrumentation_health_dataset_b.json`,
`instrumentation_sensitivity_check.json`.

**The locked segmentation architecture was not modified.** Nothing under
`src/procmine/segmentation/` was touched, no threshold was retuned, and
segmentation was not re-run as part of the diagnostic. The locked
baseline was re-run once, unchanged, only to confirm reproducibility.

---

## 1. Problem

The locked Combined pipeline performs far worse on some Dataset-A
sessions than others, and the poor sessions are not randomly distributed
— the seven worst all come from one machine.

| Machine | n | Combined F1 (mean) | under-seg (mean) |
|---|---:|---:|---:|
| **LAPTOP-R36BQBTE** | **7** | **0.14** | **1.28** |
| CHAITANYA0BCF | 12 | 0.37 | 0.06 |
| JAYESH | 2 | 0.39 | 0.11 |
| LAPTOP-0IM1OHQH | 7 | 0.36 | 0.14 |
| Marcos | 10 | 0.40 | 0.09 |
| MSI | 8 | 0.34 | 0.12 |
| SIDDHIGUPTAB00B | 12 | 0.32 | 0.18 |
| yuvraj | 5 | 0.32 | 0.08 |

The risk this creates is not the low number itself. It is that the
pipeline produces ordinary-looking output in this condition and nothing
anywhere indicates the result is less trustworthy.

**Baseline reproducibility (precondition).** Before investigating, the
locked experiment was re-run unchanged. All 30 pooled metrics matched the
Day-2 artifact to 1e-12, with the same selected tempo threshold
(4680.2613) and the same populations (3667/296). Confusion verified
exactly: **TP 1062, FP 3441, FN 609**, precision 0.235843, recall
0.635548, F1 0.3440.

## 2. Evidence

**The degraded machine is missing the strongest boundary signal.**

- 6 of its 7 sessions carry `browser_domain` on **0.00%** of events. The
  7th carries it on 58.77% of events but has only **1 distinct domain**.
- Normal sessions carry 3–4 distinct domains — `127.0.0.1:5122` /
  `:5123` / `:5124`, i.e. different internal business systems separated
  by port.
- **96.6%** of ground-truth boundaries on normally-instrumented sessions
  coincide with a browser-domain change. On LAPTOP-R36BQBTE it is **0%**.
- Day 1 had already measured browser navigation as the strongest single
  signal (lift 13.98) and noted "one session at exactly 0.0 coverage."
  The actual scope is an entire machine — 11% of Dataset A.

**Alternative explanations tested and rejected.**

- *Tempo / pace.* Session median gaps vary only **1.27x** across all 63
  sessions and the degraded machine sits at **1.02x** of the others.
  Structural characteristics (events per execution, duration, app mix,
  top application) are also ordinary. Pace does not explain it.
- *Window-title fallback.* Day 3 solved the same null-domain problem for
  Dataset B by switching to window titles. That does not transfer back:
  on these sessions title-change has median lift **1.10**, firing at
  **3.33%** of boundaries versus **3.55%** of non-boundaries — at or
  below chance. Titles are present (99.6% of events) but do not carry
  business-system identity here.

The conclusion the evidence supports is therefore *"the required
instrumentation is unavailable,"* not *"the algorithm is bad."*

## 3. Hypothesis

A lightweight, ground-truth-free, session-level instrumentation-health
diagnostic based on observed signal coverage can identify sessions where
segmentation evidence is materially degraded. Additive and diagnostic
only; it must not modify the locked segmentation.

## 4. Method

Per session, from the canonical event stream:

- total event count
- `browser_domain`-populated event count
- coverage = populated / total
- distinct non-empty domain count
- `status`: `healthy` | `degraded`, plus warnings naming the failing criterion

It reads `CanonicalEvent.browser_domain`, reusing the existing URL
parsing rather than duplicating it, requires no ground truth, is
deterministic, and writes nothing to raw data. A session is `degraded`
if **either** criterion fails.

Output form:

```json
{ "session_id": "ses_20260701-103853-Marcos",
  "browser_domain_coverage": 0.635913, "n_distinct_browser_domains": 3,
  "status": "healthy", "warnings": [] }
```
```json
{ "session_id": "ses_20260630-121953-LAPTOP-R36BQBTE",
  "browser_domain_coverage": 0.587734, "n_distinct_browser_domains": 1,
  "status": "degraded",
  "warnings": ["browser_domain has 1 distinct value(s), below the 2 required
                for a domain-change signal to be observable at all"] }
```

The second case is the one that justifies having two criteria: 58.77%
coverage looks healthy at a glance, and only the distinct-domain check
catches it.

## 5. Threshold selection

Both thresholds were derived from Dataset A.

**`MIN_DISTINCT_BROWSER_DOMAINS = 2` — structural, not fitted.** With
fewer than two distinct domains a domain *change* is mathematically
unobservable, whatever the coverage. This is a definitional floor rather
than a tuned parameter. Dataset A's distribution:

| distinct domains | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 13 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| sessions | 6 | 1 | **0** | 32 | 20 | 1 | 1 | 1 | 1 |

The **empty bin at exactly 2** means no session sits on the boundary, so
the cut is not knife-edge.

**`MIN_BROWSER_DOMAIN_COVERAGE = 0.40` — from distribution shape.**
Sorted across 63 sessions: six at 0.00%, one at 26.00%, then the main
population spanning 46.42%–69.46% (median 57.56%). The two largest gaps
in the entire distribution are **0.00 → 26.00 (26.0pp)** and
**26.00 → 46.42 (20.4pp)**; the next largest is 3.6pp. 0.40 sits inside
the second gap with a **6.4pp margin** to the nearest healthy session.

**Disclosure.** Dataset B's coverage distribution had already been
observed earlier in the investigation, while identifying the weakness.
The threshold was derived from Dataset A's gap structure alone and was
not adjusted to produce any particular Dataset-B outcome, but the prior
visibility is recorded here rather than implying it was chosen blind.

**Trade-off.** The structural criterion alone flags 7 sessions (all
LAPTOP-R36BQBTE). The coverage criterion adds an 8th,
`ses_20260701-043922-SIDDHIGUPTAB00B` at 26.00%, which independently is
the 6th-worst session in Dataset A (F1 0.165). Each criterion catches
something the other misses, which is why there are exactly two — and why
no weighted health score was built, which would have been complexity
without evidence.

## 6. Dataset-A evaluation

All 63 sessions. Ground truth was used **only** to evaluate the
diagnostic; the diagnostic consumes none, which is what allows the same
code to run unchanged on Dataset B.

Detection against the stated observable "did the locked pipeline do
materially worse on this session," cut at the healthy population's own
5th-percentile F1 (0.2385), derived from the data rather than chosen:

**TP 8, FP 0, FN 2, TN 53 → sensitivity 0.800, specificity 1.000.**

Flagged versus healthy on all four segmentation metrics:

| metric | flagged median | healthy median | flagged range | healthy range |
|---|---:|---:|---:|---:|
| F1 | 0.1579 | 0.3621 | 0.051 – 0.225 | 0.224 – 0.433 |
| under-segmentation | **1.2462** | **0.0921** | **0.622 – 1.833** | **0.017 – 0.277** |
| over-segmentation | 0.4711 | 1.7333 | 0.308 – 0.973 | 0.741 – 2.500 |
| % fragmented | 47.11 | 84.62 | 30.77 – 65.22 | 25.93 – 100.00 |

**The direction is not uniform, and this matters.** Flagged sessions are
worse on F1 and under-segmentation but *better* on over-segmentation and
fragmentation. That is mechanically consistent with the diagnosis rather
than contradicting it: without a domain-change signal, V1/V2 propose far
fewer boundary candidates, so fewer false splits are produced (lower
fragmentation, lower over-segmentation) while most true boundaries are
missed (low recall, high under-segmentation). The characteristic failure
on these sessions is **distinct executions being merged together**, not
executions being split apart.

**Only under-segmentation separates completely**: every flagged session
≥ 0.622, every healthy session ≤ 0.277, zero overlap. F1 ranges overlap
by 0.001; over-segmentation and fragmentation overlap substantially.

By machine: LAPTOP-R36BQBTE 7/7 flagged, SIDDHIGUPTAB00B 1/12, the other
six machines 0.

**Wording, deliberately.** These figures describe *observed segmentation
behaviour on flagged versus healthy sessions*. They do not establish that
the diagnostic predicts segmentation quality; it was not evaluated as a
predictor and makes no such claim.

**Both misses are reported.**

- `ses_20260701-030836-yuvraj` — F1 0.2243, coverage 68.85%, 4 domains.
  Genuinely poor and genuinely well-instrumented, so its problem lies
  elsewhere and the diagnostic correctly does not claim it.
- `ses_20260701-035622-SIDDHIGUPTAB00B` — F1 0.238532, coverage 47.64%,
  3 domains. A boundary artifact: the percentile cut is literally its own
  F1 value, so it counts as "poor" by construction.

Sensitivity 0.800 is the honest figure and the correct scope. The
diagnostic detects missing instrumentation, not every cause of poor
segmentation.

## 7. Dataset-B evaluation

Identical diagnostic, identical thresholds, no retuning. Dataset B has no
ground truth, so nothing here is a segmentation-accuracy claim.

**2 of 15 sessions flagged:**

| session | coverage | domains | executions | of total | HR/Payroll execs |
|---|---:|---:|---:|---:|---:|
| `ses_20260701-192455-NEELA9BAF` | 0.00% | 0 | 39 | 6.0% | 12 (9.8% of HR) |
| `ses_20260701-164424-CHAITANYA0BCF` | 37.20% | 3 | 35 | 5.4% | 2 (1.6% of HR) |
| **combined** | | | **74** | **11.5%** | **14 (11.5% of HR)** |

The previously-identified 0%-coverage session was correctly flagged. The
second was **not previously identified** and was investigated rather than
assumed to be a diagnostic error.

**Caveat.** Dataset B's coverage distribution sits systematically lower
than Dataset A's (median 50.44% vs 57.56%), so a Dataset-A-derived
threshold is somewhat stricter when applied to B. The 0.00% session is
unambiguous; the 37.20% session sits only **2.8pp** below the threshold
and should be read as marginal, not as an equivalent failure. This is the
same "do not assume Dataset-A patterns transfer" condition this project
has hit before, and it is reported rather than smoothed over.

## 8. HR/Payroll sensitivity analysis

The Problem-2 chain was re-run end to end, twice, invoking the existing
Day-3 scripts (`analyze_process_priority_dataset_b.py` →
`audit_problem2_process_mining.py`) unmodified as subprocesses. Profiles
and variants are **recomputed** from each execution population, because
the opportunity score reads `execution_count`, `total_duration_ms`,
`avg_manual_event_share`, `dominant_variant_share` and `n_variants` from
the profiles — filtering executions while keeping full-population
aggregates would have silently mixed the two. No scoring weight, formula,
or threshold was altered; the only difference is which executions are in
the input.

Case A reproduces the Day-3 artifact **exactly** (Impact 0.9236,
Feasibility 0.4765, Opportunity 0.4401), confirming the harness is
faithful.

| | Case A (all 645) | Case B (571, degraded excluded) |
|---|---:|---:|
| **HR/Payroll rank** | **1** | **1** |
| HR Impact | 0.9236 | 0.9249 |
| HR Feasibility | 0.4765 | 0.4519 |
| HR Opportunity | 0.4401 | 0.4180 |
| HR Pareto-non-dominated | yes | yes |
| HR #1 in sensitivity scenarios | 5 of 8 | 5 of 8 |
| mean Kendall τ vs default | 0.9524 | 0.9476 |
| processes ranked | 21 | 21 |

The top five keep their exact order. Eleven processes change rank; every
change is ±1 and all are below rank 5.

**The recommendation is robust.** Removing 11.5% of executions —
including 11.5% of the HR/Payroll evidence — does not change the top
candidate, its Pareto status, or its sensitivity profile.

**One qualifier belongs in the final report.** HR's Opportunity falls
5.0% while Order & Inventory rises, so the **margin to second place
narrows from 0.0872 to 0.0546, a 37.4% reduction**. HR still leads
clearly, but the lead is smaller on clean evidence than the headline
number implies.

## 9. Limitations

- The diagnostic detects **missing instrumentation only**. Sensitivity
  0.800 against "poor session" is the correct scope, not a number to
  improve by widening the claim.
- It is a descriptive agreement check, **not a validated predictor** of
  segmentation quality.
- It cannot measure segmentation correctness on Dataset B — no ground
  truth exists there. On Dataset B it reports only that evidence is thin.
- The coverage threshold is derived from Dataset A and appears slightly
  strict when applied to Dataset B.
- It says nothing about **why** capture failed (extension absent, not
  connected, permissions, or a genuinely single-system session).
  Separating those needs agent-side telemetry this dataset does not
  contain.
- It **repairs nothing**. Flagged sessions still produce segments that
  still flow downstream; they are only labelled.
- `browser_domain` is the only signal assessed. Other instrumentation
  gaps would go undetected.

## 10. Final decision

**RETAIN**, strictly as an upstream quality layer.

It separates the degraded population cleanly on the metric that matches
the mechanism (under-segmentation, complete separation), costs two
interpretable parameters justified structurally and distributionally
rather than fitted to their own outcome, transfers to Dataset B unchanged
and surfaced a session not previously identified, and converts a silent
failure into a stated one.

```
Raw operation logs
    -> Instrumentation health check   (healthy / degraded)
    -> Locked segmentation            (UNCHANGED)
    -> Segmented executions
    -> Problem-2 process analysis
    -> Automation opportunity
    -> Problem-3 prototype
```

No Dataset-A segmentation metric changed, because nothing in the decision
path changed. That is the intended outcome: this improves operational
honesty, not benchmark numbers.

### The three things this separates, kept separate

**A. Algorithm quality.** The locked Combined pipeline is unchanged and
its measured quality is unchanged: F1 0.3440, recall 0.6355,
fragmentation 79.05%, under-segmentation 0.1412, over-segmentation 1.603.
Day 4 produced no evidence that the algorithm is worse than previously
measured, and none that it is better.

**B. Instrumentation quality.** Separately measurable and previously
unmeasured. 8 of 63 Dataset-A sessions (12.7%) and 2 of 15 Dataset-B
sessions (13.3%) lack the browser-domain evidence the pipeline's
strongest boundary signal depends on. On Dataset A those sessions show
markedly higher under-segmentation.

**C. Business-analysis confidence.** The Dataset-B automation ranking
rests on 645 executions, of which 74 (11.5%) come from
instrumentation-degraded sessions. Excluding them leaves HR/Payroll #1,
Pareto-non-dominated, with an unchanged sensitivity profile — but with a
37.4% narrower margin to second place. Confidence in "HR/Payroll is the
right first automation target" is therefore **high**; confidence in the
precise Opportunity value (0.4401) is **lower**, and it should be
reported as a figure that moves by ~5% depending on which evidence is
admitted.

These are three different claims and are not collapsed into one number.

## Potential follow-up hypothesis — recorded, NOT implemented

**Observation.** Under-segmentation separates the flagged and healthy
populations perfectly (flagged ≥ 0.622, healthy ≤ 0.277, zero overlap),
and the mechanism is understood: without a domain-change signal, far
fewer boundary candidates are proposed, so executions merge.

**Why it is interesting.** It suggests the pipeline could in principle
condition on instrumentation availability — for example by relaxing the
Rule-4 continuity demotion, or by weighting the remaining signals
differently, when the domain signal is known to be absent. That would
target the specific failure mode rather than the aggregate.

**What would need to be tested.** A pre-registered success gate on
Dataset A comparing a degraded-session-specific path against the locked
Combined baseline on all four metrics plus per-session robustness; it
would need to improve under-segmentation on the 8 flagged sessions
without worsening any metric on the 55 healthy ones, and it would need to
work with only 8 sessions of evidence — a small population that makes
overfitting a genuine risk.

**Why it was not included in Day 4.** It would modify the locked
architecture, which was explicitly out of scope for this experiment, and
it requires its own hypothesis, success criterion and engineering
decision rather than being folded into a diagnostic-only change.
