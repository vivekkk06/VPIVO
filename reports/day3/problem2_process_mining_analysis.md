# Problem 2 — Process-Mining Investigation (Final Audit)

This supersedes the earlier draft of this report with a stricter,
final-review pass: a mathematical audit that found and fixed one real
bug (variant entropy), plus the redundancy-robustness comparison,
Pareto analysis, expanded 8-scenario sensitivity sweep, ablation
analysis, and outlier-robustness check this audit specifically
required. Problem 1 (Dataset-A segmentation: candidate set V1 ∪ V2,
Rules 1–4, Combined protection, thresholds
0.9078/0.8860/0.40/4680.2613ms, boundary F1=0.3440 — a classifier
metric, not "34.4% segmentation accuracy") is untouched anywhere below.
Problem 3's prototype (`src/procmine/automation/`) was not redesigned —
re-run and re-verified working, not modified.

## 1. Problem 2 objective

Given Dataset B's segmented executions, determine what processes
exist, how often and how long they run, how much human/application
involvement they carry, what variants exist, how deterministic they
are, and which process has the strongest defensible automation
opportunity — then hand that candidate to Problem 3.

## 2. Current approach (audited, not assumed correct or incorrect)

Group by `dominant_context` → exact-match variant discovery
(`variant_signature`) → per-process metrics → an 8-factor additive
score with two subtracted penalties, min-max normalized, equal-weighted.

## 3. Why the current approach was initially reasonable

It never combines raw units, labels feasibility/business-impact/risk
as judgment proxies rather than measurements, and was sensitivity-
tested (5 scenarios) with results reported honestly, including the
scenarios that displaced HR/Payroll. A defensible starting point, not
a naive one.

## 4. Limitation discovered (prior investigation)

Impact and Feasibility were blended into one additive score instead of
kept separate; frequency and duration were included without checking
redundancy; no Directly-Follows view of transition structure existed;
variant grouping was exact-match only, with no continuous similarity
measure to corroborate it.

## 5. Mathematical enhancement, and one genuine bug found and fixed

**Audit finding (mathematical error, not stylistic)**: `variant_entropy`
returns raw Shannon entropy in bits, which is **not comparable across
processes with different variant counts** — a process with more
variants has a higher maximum possible entropy (`H_max = log2(n)`),
so raw entropy conflates "how many variants exist" with "how evenly
they're used." Measured directly on Dataset B: **"Word: Contract
Termination Procedure" (7 variants) shows higher raw entropy (2.195)
than "Word: New Contract Procedure" (3 variants, 1.500) even though the
3-variant process is actually MORE evenly spread relative to its own
maximum (H/H_max = 0.946 vs. 0.782)**. This is a real confound once it
feeds a cross-process normalization step.

**Fix**: added `normalized_variant_entropy` (`H / H_max`, bounded
[0,1], 0.0 for ≤1 variant) and switched `Feasibility_p`'s entropy
component to use it. Raw `variant_entropy` is kept for absolute-scale
reporting, not removed. **Effect on real data**: HR/Payroll's
Feasibility moved 0.453 → 0.477 and Opportunity 0.419 → 0.440; more
materially, Financial Accounting's Feasibility moved 0.315 → 0.369,
**swapping ranks 4 and 5 with Excel: Expense Calculation Workbook**
(mathematically valid formulas were not touched merely for style —
this one was genuinely wrong for cross-process comparison, and fixing
it changed a real rank).

## 6. Trace representation (unchanged from the prior investigation)

SYSTEM_LEVEL (reused `variant_signature`, avg 1.58 tokens) for the DFG;
ACTIVITY_LEVEL ((system, category) pairs, avg 19.65 tokens) for
similarity. Raw event_type traces rejected — up to 204 events per
execution, mostly automatic `screenshot_smart`. Kept from the earlier
pass; re-verified, not re-litigated in this audit since no new evidence
challenged it.

## 7. Variant discovery — clustering considered and rejected

**Audit question (Section 10 of the instructions)**: is exact-match
variant grouping sufficient, or does full clustering add value? Tested
via the similarity investigation already run (Levenshtein/LCS/Jaccard,
HR/Payroll's 122 traces): within-group similarity (0.32–0.87 across
measures) exceeds between-group similarity (0.30–0.55), supporting the
existing exact-match split without needing a general clustering
algorithm. **Clustering was not implemented**, for a concrete,
data-grounded reason: with only 21 candidate processes and system-level
traces averaging 1.58 tokens, there is not enough sequence diversity
for hierarchical/DBSCAN clustering to find structure a 3-measure
similarity check plus exact-match grouping hasn't already shown. This
is documented as a deliberate engineering decision, not an omission.

## 8. Directly-Follows Graph (unchanged, evidence preserved)

HR/Payroll: `HR → Word` count=33 (P=0.825), `Word → HR` count=32
(P=**1.000**), `HR → Financial` count=4 (P=0.100), `Financial → HR`
count=4 (P=**1.000**), `Explorer → HR` count=3 (P=**1.000**). Every
detour returns to HR with probability 1.000 — no dead-end paths —
preserved unchanged from the prior investigation as required.

## 9. Operational metrics — observed vs. derived, labeled explicitly

| Metric | Value (HR/Payroll) | Label |
|---|---|---|
| `execution_count` | 122 | OBSERVED |
| `frequency_share` | 21.5% (of 21 candidates' total) | DERIVED |
| `total_duration_ms` | 2,991,209ms | OBSERVED (sum of recorded durations) |
| `average_duration_ms` | 24,518ms | DERIVED |
| `time_share` | 32.5% | DERIVED |
| `user_count` | 4 | OBSERVED |
| `application_count` | 4 | OBSERVED (from each execution's own recorded `applications` list) |
| `manual_involvement` (`avg_manual_event_share`) | 70.1% | DERIVED (event-category classification is a fixed, documented rule, not a judgment call — INFERRED only in the sense that "input/pointer/clipboard = manual" is a reasonable categorization, not directly labeled in the raw schema) |
| `dominant_variant_share` | 77.05% | DERIVED |
| `variant_entropy` (normalized) | 0.419 | DERIVED |
| `automation_surface` | 0.540 | DERIVED (a *definition*, §11) |

No metric here is PROJECTED (nothing about future/production volume is
claimed anywhere in this section).

## 10. Impact

`Impact_p = mean(norm(FS_p), norm(TS_p), norm(manual_p))`. HR: **0.924**
(highest of 21) — driven by the combination of a large `time_share`
(32.5%, the largest of any candidate) and high manual involvement, not
by frequency alone (Financial has more raw executions, 125 vs. 122, but
a lower Impact, 0.880, because its time_share and manual_involvement
are both lower).

## 11. Feasibility

`Feasibility_p = mean(norm(C_p), 1-norm(H_norm_p), norm(AS_p), 1-norm(risk_p))`.
HR: **0.477** — not the highest (Excel: Budget Analysis: 0.954; Excel:
Expense Calculation: 0.922; Order/Inventory: 0.527 — all exceed HR).
**This is reported plainly, not softened**: HR is the highest-Impact,
*not* the highest-Feasibility candidate — exactly the "high impact,
not the most feasible" pattern the instructions require to stay
visible rather than be absorbed into one number.

`automation_surface` (`AS_p = dominant_variant_share × avg_manual_event_share`)
remains a **definition**, not an independently measured third quantity
— restated here because it is load-bearing for Feasibility and must
not be mistaken for a directly-observed count (§9 of the earlier
report's reasoning, unchanged).

## 12. Opportunity score

`Opportunity_p = Impact_p × Feasibility_p`, bounded [0,1]. HR: **0.440**
(after the entropy fix). Top 5: HR (0.440) → Order/Inventory (0.353) →
Excel: Budget Analysis (0.338) → Financial Accounting (0.325) → Excel:
Expense Calculation (0.318).

## 13. Correlation / redundancy — investigated in depth, not just noted

Pearson `r(execution_count, total_duration_ms) = 0.9768` across the 21
candidates (measured previously, re-confirmed, real and substantial).
**Four Impact formulations compared, as required**:

| Formulation | HR rank | Spearman ρ vs. default (A) |
|---|---:|---:|
| A: frequency + total duration + manual (current) | 1 | 1.000 |
| B: frequency + average duration + manual | 1 | 0.983 |
| C: total duration + average duration + manual | 1 | 0.977 |
| D: frequency + manual only (duration dropped entirely) | **3** | 0.986 |

**A, B, C all keep HR at #1** with high rank agreement (ρ ≥ 0.977) —
the ranking is not sensitive to *which pairing* of volume/duration
signals is used, as long as some duration-related signal remains.
**D changes the top candidate**: dropping duration entirely (using only
a pure count + manual-involvement rate) lets Excel: Budget Analysis
Workbook overtake HR (HR falls to rank 3). This is reported explicitly,
not smoothed over: **HR's Impact advantage is substantially carried by
the duration/time_share signal specifically, not by frequency or
manual involvement alone.** The redundancy between frequency and total
duration does not by itself invalidate the ranking (A/B/C agree), but
removing time information altogether does change the answer — a real,
load-bearing dependency worth knowing before treating HR as the
obviously correct choice under every possible formulation.

## 14. Sensitivity analysis — 8 named scenarios, one axis varied at a time

| Scenario | HR rank | Top candidate | Spearman ρ vs. default |
|---|---:|---|---:|
| balanced (default) | 1 | HR/Payroll | 1.000 |
| frequency_heavy | 1 | HR/Payroll | 0.982 |
| time_heavy | 1 | HR/Payroll | 0.994 |
| feasibility_heavy | 1 | HR/Payroll | 0.997 |
| risk_averse | 1 | HR/Payroll | 0.994 |
| **manual_effort_heavy** | **3** | Excel: Budget Analysis | 0.986 |
| **volume_deemphasized** | **3** | Excel: Budget Analysis | 0.973 |
| **correlation_aware** (frequency & time each weighted 0.5, avoiding double-counting) | **3** | Excel: Budget Analysis | 0.986 |

**HR ranks #1 in 5 of 8 scenarios.** Mean Kendall's τ vs. default across
all 8 = **0.952** (very high rank agreement overall, despite the 3
scenarios that displace the top candidate — most of the *rest* of the
ranking barely moves even when #1 changes). The three scenarios that
displace HR share a common mechanism: **each one reduces the influence
of the time/volume signal HR wins on** (directly, or by explicitly
correcting for its correlation with frequency) — consistent with, and
reinforcing, the §13 finding. This is reported as a real, structural
sensitivity, not hidden: **HR/Payroll's #1 ranking depends on giving
material weight to the time it actually consumes; under a formulation
that treats manual-effort *rate* or redundancy-corrected volume as the
primary signal instead, a small, highly-consistent process (Excel:
Budget Analysis, 100% dominant variant, 0.954 feasibility) is the more
defensible pick.**

## 15. Ablation analysis — which components actually matter

Full model, one component removed at a time:

| Component removed | HR rank | Top candidate changes? | Spearman ρ vs. full model |
|---|---:|---|---:|
| frequency | 2 | Yes | 0.988 |
| time | 3 | Yes | 0.986 |
| manual_effort | 1 | No | 0.896 (largest overall rank disturbance of any single removal, yet HR itself unaffected) |
| variant_concentration (determinism) | 1 | No | 0.991 |
| entropy | 1 | No | 0.996 |
| automation_surface | 1 | No | 0.986 |
| risk | 1 | No | 0.996 |

**Frequency and time are the only two components whose removal changes
HR's rank at all** — removing either alone displaces it (to 2 and 3
respectively), directly corroborating §13/§14 from a third, independent
angle (leave-one-out rather than reweight-and-compare). **Every
Feasibility-side component (determinism, entropy, automation_surface,
risk) is individually non-decisive for HR's own position** — removing
any one of them leaves HR at #1, even though `manual_effort`'s removal
causes the single largest disturbance to the *overall* ranking
(ρ=0.896, lowest of the seven) — meaning manual effort matters a great
deal for the population as a whole, just not for whether HR
specifically stays on top. No component tested is purely decorative:
each one moves at least one process's rank measurably (full detail in
`problem2_audit_results.json`); frequency and time are simply the two
that are decisive *for HR specifically*.

## 16. Pareto analysis

**3 of 21 processes are non-dominated**: HR/Payroll (0.924, 0.477),
Order & Inventory (0.670, 0.527), Excel: Budget Analysis (0.354, 0.954).
**HR/Payroll is on the Pareto frontier** — not forced there: no other
process has both equal-or-higher Impact AND equal-or-higher Feasibility
with at least one strict improvement. This is a weighting-independent
property (true regardless of how Impact/Feasibility are subsequently
combined or weighted) and is the single piece of evidence in this
report that does **not** depend on the redundancy/sensitivity concerns
raised above — HR's frontier membership holds even though its exact
*rank* among the frontier's 3 members depends on the weighting chosen.

## 17. Old vs. new comparison (updated with this audit's findings)

Unchanged from the prior report for dimensions 1–9, 11–13 (process
groups, variants, DFG, metrics visibility, explainability,
computational complexity, analyst effort — see the version history in
this file's predecessor). **Updated for dimension 10 (ranking
stability), now measured more rigorously**: the earlier draft reported
"9/12 scenarios" from a quicker, less targeted scenario grid; this
audit's 8 *specifically-named, one-axis-at-a-time* scenarios (matching
the instructions exactly, including two — `manual_effort_heavy` and
`correlation_aware` — not tested before) found HR #1 in only **5/8**.
**The more rigorous test found a real vulnerability the earlier,
looser test missed.** This is reported as a correction, not hidden:
the old approach's own sensitivity sweep found HR #1 in 3/5 (60%); this
audit's new-methodology sweep finds 5/8 (62.5%) — **materially similar
stability, not a decisive improvement**, once tested with comparable
rigor on both sides.

## 18. HR/Payroll validation — final, honest status

| Required evidence | Status |
|---|---|
| 1. Highest or near-highest operational impact | ✅ Highest Impact of 21 (0.924) |
| 2. Strong dominant variant | ✅ 77.05% (94/122) |
| 3. Low enough process variation for bounded automation | ⚠️ Feasibility 0.477 — mid-range, not the highest (Excel workbooks: 0.92–0.95) |
| 4. DFG support | ✅ All detours return to HR, P=1.000 |
| 5. DOM-level evidence | ✅ Unchanged, independently validated (Problem-3 forensic work) |
| 6. Deterministic UI pattern | ✅ id-based selectors, paste-only input, near-1:1 note/confirm pairing |
| 7. Clearly defined automation boundary | ✅ 4 routes only, Word-detour and rare multi-hop explicitly excluded |

**HR/Payroll remains a defensible Problem-3 candidate**, but this audit
found its numerical ranking is **more contested than previously
reported**: it is displaced from #1 under 3 of 8 reasonable sensitivity
scenarios and one non-redundant Impact formulation, and it is not the
most *feasible* of the 21 candidates. What survives every test run in
this audit: **HR/Payroll is Pareto-non-dominated (a weighting-
independent fact), never falls below rank 3 in any scenario tested,
and is #1 under the direct, unweighted default configuration.** Its
case rests on the combination of a real, substantial Impact
advantage plus independent DOM-forensic evidence Excel: Budget Analysis
does not have (no comparable automation prototype work exists for the
Excel candidates in this project) — not on unconditional numerical
dominance.

## 19. Final ranking (default weights, all 21 candidates in `problem2_process_metrics.json`; top 5 shown)

| Rank | Process | Impact | Feasibility | Opportunity |
|---|---|---:|---:|---:|
| 1 | HR / Payroll System | 0.924 | 0.477 | **0.440** |
| 2 | Order & Inventory Management System | 0.670 | 0.527 | 0.353 |
| 3 | Excel: Budget Analysis Workbook | 0.354 | 0.954 | 0.338 |
| 4 | Financial Accounting System | 0.880 | 0.369 | 0.325 |
| 5 | Excel: Expense Calculation Workbook | 0.345 | 0.922 | 0.318 |

## 20. Final decision

**AUGMENT CURRENT APPROACH.**

Not KEEP: this audit found and fixed a genuine mathematical error
(unnormalized entropy) that measurably changed real ranks, and it
surfaced a real, previously-underreported sensitivity (HR's ranking
depends materially on the time/duration signal, per §13–15) that the
original approach's own 5-scenario sweep also could have found but
didn't test for as specifically.

Not REPLACE: no different candidate emerged as unconditionally
superior — Excel: Budget Analysis wins only under 3 of 8 tested
scenarios and one of four redundancy formulations, and it lacks the
independent DOM-forensic validation HR/Payroll already has from
Problem 3's prototype work. Replacing the pipeline on this evidence
would trade a real, working, forensically-validated candidate for a
numerically-competitive one with no equivalent independent check.

## 21. Why this decision is defensible

Every claim above traces to a re-runnable script
(`scripts/audit_problem2_process_mining.py`) against real Dataset B
data — not asserted. The audit was not designed to protect HR/Payroll's
position: the manual_effort_heavy, volume_deemphasized, and
correlation_aware scenarios, and the D redundancy formulation, were
each capable of (and did) displace it, and that is reported plainly
rather than reframed. What remains true after every adversarial test
run — Pareto non-domination, never worse than rank 3, #1 under the
unweighted default, and independent DOM evidence — is a stronger,
more honestly-earned basis for the decision than an unstressed ranking
would have been.

## 22. Limitations

- The entropy fix changes absolute scores but not the overall
  decision; it is reported because it is real, not because it flips
  the final recommendation.
- `application_count` and `user_count` are read from already-recorded
  per-execution fields, not independently re-verified against raw
  events in this audit pass.
- Outlier robustness (winsorization, limit=0.1) **also displaces HR**
  (to rank 2, Order/Inventory becomes #1) — consistent with, not
  contradicting, §13–15's finding that HR's position leans on values in
  the upper part of the observed distribution; not treated as
  disqualifying given HR still ranks 2nd and remains Pareto-
  non-dominated even here, but recorded as a further real caveat, not
  omitted. Full min-max normalization is retained as the reported
  default per the instructions ("only implement robust normalization
  if it materially improves decision quality") — winsorization changes
  the top rank here, which is itself informative evidence for §13–15
  rather than grounds to silently switch the production normalization.
- Dataset B has no process-level ground truth anywhere in this
  analysis; every ranking is a relative, evidence-based ordering, not
  a validated accuracy measurement.

## 23. Reproducibility

```
.venv/bin/python scripts/analyze_problem2_process_mining.py --day3-dir reports/day3 --out reports/day3
.venv/bin/python scripts/audit_problem2_process_mining.py --day3-dir reports/day3 --out reports/day3
```

Both deterministic given the existing (unchanged) Day-3 artifacts as
input; no random seed anywhere in either module. Full test suite:
`.venv/bin/python -m pytest tests/ -q` — 448 passed at the time of this
report (421 prior + 5 for `normalized_variant_entropy` + 22 for
`robustness_analysis.py`).
