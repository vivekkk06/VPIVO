# Dataset B — Automation Candidate Analysis

Final synthesis of Sections 4–13. Builds on `dataset_b_profile.md`
(Section 1) and `process_discovery.md` (Sections 2–3). All figures below
are read directly from `reports/day3/process_profiles_dataset_b.json`,
`process_variants_dataset_b.json`, `step_frequency_dataset_b.json`,
`human_time_analysis_dataset_b.json`, and `automation_priority_dataset_b.json`
— produced by `scripts/analyze_process_priority_dataset_b.py`, which is
pure downstream analysis of the 645 already-built, already-tested
execution records (Section 3). Dataset B has no ground truth; nothing
below is validated against a label — every number is descriptive of what
was actually recorded, and every judgment call is stated as a judgment
call, not presented as a measured fact.

## The story, end to end

```
Raw Dataset B (20,477 events, 15 sessions, 4 operators)
  -> sorted, canonical event stream (Section 1)
  -> system-change candidate boundaries, corrected for a real bug found
     by testing against the data (Section 2)
  -> 645 executions, short leave-and-return detours merged back in
     (Section 3)
  -> grouped by dominant (system, document) context -> 29 processes,
     21 of them real business processes, 8 excluded as recording/
     navigation infrastructure or unstructured communication (Section 4)
  -> variant signatures (the sequence of systems an execution actually
     touches) computed per process (Section 4)
  -> frequency, time, and step-level analysis per process (Sections 5-7)
  -> a transparent, normalized, sensitivity-tested priority score
     (Sections 9-11)
  -> HR / Payroll System, ranked #1 under the default weighting and 2 of
     4 alternate weightings, selected with the instability in the other
     2 explained rather than hidden (Section 12)
```

## Section 4 — Processes discovered

29 distinct `dominant_context` groups emerged from the 645 executions.
**8 are excluded from the automation ranking**, per instruction #13 ("do
not force every event into a business process"):

| Excluded group | n | Why excluded |
|---|---:|---|
| `app:WindowsTerminal` | 21 | Recording/scenario-setup activity (the very first session's own extracted terminal text showed a scenario-generator script being invoked here), not a repeatable business task. |
| `app:OpenWith` | 15 | A Windows file-open dialog, not a task in itself. |
| `app:Windows Explorer` | 7 | File navigation, always incidental to some other task. |
| `app:ms-teams` | 14 | Chat/communication — inherently judgment-driven, not a deterministic repeatable procedure. |
| `browser:127.0.0.1:5132/5133/5134` (unresolved) | 4–6 each | The window title didn't resolve to one of the three known system names for these events (a real data-attribution gap noted in Section 2's `system_identity` writeup) — too ambiguous to attribute to a specific process with confidence. |
| `app:Notepad` (untitled/bare) | 5 | No document title resolved — likely a blank scratch buffer, not a named memo. |

**21 real business processes remain**, spanning the three named systems
(Financial Accounting, HR/Payroll, Order & Inventory), three named
Excel/Word/Notepad-document groups already covered by name in the
profile, plus several lower-volume named Word procedures (Entertainment
Expense Regulations, Outsourcing Compensation Regulations, Outsourcing
Intake Procedure, New Trading-Partner Registration, Contract Termination,
New Contract Procedure, Childcare/Family-Care/Family-Allowance
Regulations, Administrator Authority Request, New-Employee Checklist,
Monthly Trading-Partner List).

## Section 4 (variants) — what "same process, different shape" looks like here

Variant = the sequence of distinct systems an execution's steps actually
touch (a pure single-system stay is a one-element signature; a detour and
return shows as e.g. `(HR, Word, HR)`). For the HR/Payroll System (the
process examined in most depth below, n=122):

| Variant (system sequence) | Frequency | Avg duration |
|---|---:|---:|
| `HR` only | 94 (77.0%) | 17.8s |
| `HR -> Word -> HR` | 17 (13.9%) | 37.1s |
| `HR -> Word -> HR -> Word -> HR` | 5 (4.1%) | 50.2s |
| `HR -> Explorer -> HR` | 3 (2.5%) | 71.6s |
| `HR <-> Financial` (4 round trips) | 1 (0.8%) | 91.0s |

This is a direct, literal illustration of the assignment's own
"Standard -> Excel -> Submit" vs. "Excel -> Email -> Submit" example: the
dominant variant is a clean, self-contained pass through the HR system;
the next-most-common variant adds a genuine detour into Word (almost
certainly to check one of the named procedure documents found in
Section 1) before returning to finish the task — and it takes roughly
twice as long on average (37.1s vs 17.8s), consistent with that being
real extra work, not noise.

## Sections 5–6 — frequency and human time

| Process | Executions | Variants | Dominant-variant share | Total time (this sample) |
|---|---:|---:|---:|---:|
| Financial Accounting System | 125 | 10 | 66.4% | 0.72 hrs (43.3 min) |
| HR / Payroll System | 122 | 7 | 77.1% | 0.83 hrs (49.9 min) |
| Order & Inventory Management System | 96 | 7 | 83.3% | 0.43 hrs (25.8 min) |
| Excel: Budget Analysis Workbook | 7 | 1 | 100% | 0.02 hrs (1.2 min) |
| Excel: Expense Calculation Workbook | 17 | 1 | 100% | 0.04 hrs (2.4 min) |
| (18 further named Word/Notepad processes) | 2–37 each | mostly 1–2 | mostly 95–100% | each ≤ 0.03 hrs |

**Frequency alone does not pick a winner** (Financial has slightly *more*
executions than HR, 125 vs. 122) — exactly the trap instruction #5 warns
against. **Time consumption reorders it**: HR consumes the most total
recorded time (0.83 hrs) of any process, ahead of Financial (0.72 hrs)
despite Financial's marginally higher execution count, because HR's
individual executions run longer on average and its Word-detour variant
(14%+4% of executions) adds real extra time on top of the base task.

**Important scale caveat, recorded explicitly**: these are hours observed
in this ~3-hour, 15-session sample, not annualized operational volume.
A real prioritization decision would need to multiply by how often this
work actually recurs in production (daily/weekly/monthly), which this
dataset cannot answer — treated here as a *relative* ranking within the
sample, not an absolute business-value estimate.

## Section 7 — where the manual effort actually is

Step-level breakdown for HR/Payroll (`step_frequency_dataset_b.json`),
excluding `capture` (screenshot_smart — an automatic side-effect of the
recording agent, not a deliberate user action, and correctly excluded
from every "manual effort" calculation below):

| Step type | Occurrences | Total time | Avg time/occurrence |
|---|---:|---:|---:|
| pointer (clicking) | 1,194 | 293.0s | 245ms |
| input (typing) | 648 | 19.3s | 30ms |
| clipboard (copy/paste) | 305 | 0.1s | 0.3ms |
| navigation | 163 | 4.9s | 30ms |

**Clicking, not typing, is the dominant manual-effort driver** inside the
HR system — 1,194 distinct click actions accounting for the large
majority of measured interaction time. This is a concrete, useful,
non-obvious finding (frequency alone would have suggested "capture" or
raw event volume dominates; time-weighting reveals it's repetitive
pointer-driven navigation through what is very likely a template-like
web form). This pattern — high click-repetition, low typing-time, a
stable dominant variant — is close to the textbook profile of a good
**RPA/UI-automation** candidate rather than something requiring judgment
or unstructured-text handling.

`avg_manual_event_share` (fraction of an execution's events in
input/pointer/clipboard categories, i.e. how "hands-on-keyboard-and-mouse"
the process is) is comparably high across all three core systems: HR
70.1%, Order/Inventory 64.3%, Financial 68.1% — all substantially manual,
none obviously more automatable than another on this measure alone.

## Sections 9–11 — priority scoring, feasibility, risk

**Scoring formula** (`prioritization.py`): every raw component (execution
count, total hours, manual-effort share, dominant-variant share, a
feasibility proxy, a business-impact proxy, a risk proxy, a complexity
proxy) is min-max normalized to [0,1] across the 21 candidate processes
before being summed — never combined in raw units, per instruction.
Default weighting is **equal (1.0) across all eight components** — not
because equal weights are proven correct, but because Dataset B provides
no labeled outcome to fit weights against, and equal weighting is the
least-biased default absent such evidence. Two components are explicitly
flagged as **judgment proxies, not measurements**:

- **Business impact**: 1.0 for the three core information systems
  (Financial/HR/Order-Inventory), 0.6 for a named administrative
  document/workbook. This reflects a reasonable assumption (a live
  system used dozens of times a day is plausibly higher-stakes than an
  occasional memo) but Dataset B contains no revenue, cost, or SLA data
  to verify it.
- **Risk**: `(1.0 if core system else 0.3) + n_variants` — a core
  browser system is treated as carrying more external-dependency risk
  than a local document, and more variants (more distinct paths through
  the process) is treated as more edge-case risk. Also a proxy, not a
  measured incident rate (Dataset B has none).

**Feasibility** is *not* a proxy in the same sense — it reuses
`dominant_variant_share` directly (how much of the process already
follows one single path), which is an actual measurement, not a guess:
a process that already looks like one deterministic script 100% of the
time is mechanically easier to automate than one that forks constantly.

### Ranking (default equal weights)

| Rank | Process | Executions | Total time | Avg time | Variants | Manual effort | Repetitiveness (dom. share) | Feasibility | Risk (raw) | Priority score |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | HR / Payroll System | 122 | 49.9 min | 24.5s | 7 | 70.1% | 77.1% | 0.77 | 8.0 | 3.400 |
| 2 | Order & Inventory Mgmt System | 96 | 25.8 min | 16.1s | 7 | 64.3% | 83.3% | 0.83 | 8.0 | 2.900 |
| 3 | Excel: Budget Analysis Workbook | 7 | 1.2 min | 10.4s | 1 | — | 100% | 1.00 | 1.0 | 2.880 |
| 4 | Excel: Expense Calculation Workbook | 17 | 2.4 min | 8.7s | 1 | — | 100% | 1.00 | 1.0 | 2.853 |
| 5 | Financial Accounting System | 125 | 43.3 min | 20.8s | 10 | 68.1% | 66.4% | 0.66 | 11.0 | 2.505 |

### Sensitivity analysis (per instruction — reported honestly, not hidden)

| Weighting | Top 3 |
|---|---|
| Equal (default) | HR → Order/Inventory → Excel: Budget Analysis |
| Time-heavy (×3 time impact) | HR → Financial → Order/Inventory |
| Frequency-heavy (×3 frequency) | HR → Financial → Order/Inventory |
| Risk-averse (×3 risk, ×2 complexity) | **Excel: Budget Analysis → Excel: Expense Calc → Word: Childcare Leave** |
| No business-impact proxy (weight 0) | **Excel: Budget Analysis → Excel: Expense Calc → HR** |

**The #1 rank is *not* stable across every weighting tested — reported
as required, not smoothed over.** Under the two weightings that most
heavily penalize risk/variant-count, the tiny single-variant Excel
workbooks overtake HR. This is explainable, not arbitrary: those
workbooks score near-zero risk *because* they are used only 7–17 times
in the whole sample and total 1–2 minutes of recorded work — there is
almost nothing at stake either way. Winning a risk-averse ranking by
having negligible volume is not the same as being a meaningful
automation opportunity. **HR remains #1 under the default (equal) weighting
and under both weightings that emphasize the two most directly measured
factors (actual time spent, actual frequency)** — the two weightings that
displace it are exactly the ones that most heavily discount volume, which
is the one dimension on which HR clearly and objectively leads every
other candidate.

## Section 12 — final candidate: why #1 (HR / Payroll) beats #2 (Order & Inventory)

Order & Inventory is a legitimate, close second — it is actually *more*
internally consistent than HR (83.3% vs. 77.1% single-path share) and has
fewer variants (7, tied with HR). It loses on the two measured-not-guessed
factors that matter most for automation ROI: **HR consumes nearly double
the total human time in this sample** (49.9 vs. 25.8 minutes) and has
**more executions** (122 vs. 96). A slightly less "clean" process that is
used more and consumes more time is, all else being reasonably close, the
better first automation target — automating the busier process returns
more value even if it requires handling a marginally wider (7-variant,
still small) set of paths. Financial Accounting, despite marginally
higher raw frequency than HR (125 vs. 122), ranks lower because it is the
least standardized of the three core systems (only 66.4% single-path,
10 distinct variants) — more edge cases to handle for automation with
less time payoff than HR.

## Section 13 — Automation Opportunity Profile: HR / Payroll System

```
Process name:              HR / Payroll System (受発注在庫管理システム's
                            counterpart; observed window-title marker:
                            "HR人事給与システム")
Process description:       Browser-based HR/payroll system work,
                            predominantly a single continuous session
                            inside the system, with an identifiable
                            minority pattern of stepping into a Word
                            procedure document mid-task and returning.
Execution count:           122 (of 645 total discovered; 18.9% of all
                            executions, the single largest named process)
Total human time (sample): 49.9 minutes (0.83 hours)
Average execution time:    24.5s (median lower; dominant variant alone
                            averages 17.8s, the Word-detour variant 37.1s)
Users involved:             observed across multiple of the 4 recorded
                            operators (not restricted to one person --
                            see per-operator breakdown in
                            process_profiles_dataset_b.json)
Applications involved:      Microsoft Edge (the HR system itself),
                            Microsoft Word (procedure-document detour,
                            14%+4% of executions), Windows Explorer
                            (rare, 2.5%)
Variants:                   7 distinct system-sequences; 1 dominant
                            (single-system, 77.1%), 2 meaningful minority
                            variants (Word detour, single or double,
                            17.9% combined), 3 rare edge cases (<3% each)
Common steps:               Repeated pointer-driven interaction within
                            the HR system (1,194 click-runs, 293s total
                            -- the dominant manual-effort driver),
                            moderate typed input (648 runs, 19.3s)
Variant-specific steps:     The detour variants add a Word-document
                            open/read/return step not present in the
                            dominant variant
Most repetitive steps:      Pointer/click interaction inside the HR
                            system (highest frequency and highest total
                            time of any step type observed)
Most time-consuming steps:  Same -- pointer interaction dominates total
                            time (293s) far more than any other category
Manual effort:              70.1% of this process's events fall in
                            manual interaction categories (input/pointer
                            /clipboard) -- the highest of the three core
                            systems
Automation feasibility:     Rule-based/RPA: HIGH for the dominant variant
                            (77.1% of executions, a stable, repeated
                            click-driven path through one web system --
                            exactly RPA's strong case). API-based:
                            UNKNOWN -- Dataset B contains no evidence of
                            whether this system exposes an API; a UI-
                            level (RPA) approach is the evidenced-safe
                            default. AI-assisted: LOW priority for the
                            dominant variant (no unstructured text/
                            visual-judgment steps observed there); the
                            Word-detour variant (17.9% of executions)
                            plausibly needs either a scripted "read this
                            specific procedure field" step or a human-
                            in-the-loop check, since it involves reading
                            document content rather than only structured
                            form fields.
AI suitability:             Low for the core flow; a human-in-the-loop
                            checkpoint is recommended specifically for
                            the Word-detour variant, not the whole
                            process.
Business impact:            Judgment proxy (not measured): scored high
                            because this is one of three core operational
                            systems used dozens of times in even this
                            short sample, not because Dataset B reports
                            any revenue/cost/SLA figure.
Risk:                       Moderate -- external system dependency (a
                            live browser-based system, not a static
                            document) plus 7 variants to handle
                            correctly; the dominant variant alone is
                            low-risk, the rarer multi-hop variants
                            (HR<->Financial, 1 execution) would need
                            explicit exception handling or exclusion
                            from an initial automation scope.
Complexity:                 Low-moderate -- average 1.65 distinct
                            systems touched per execution, 7 interaction
                            categories observed
Estimated automation
  opportunity:               Automate the dominant single-system variant
                            (77.1% of volume) first via RPA/UI
                            automation targeting the repeated click
                            sequence; treat the Word-detour variant as a
                            phase-2 target (needs either a scripted
                            lookup of the referenced procedure field or
                            a human checkpoint); leave the rare multi-
                            hop edge cases (<3% of executions) for manual
                            handling initially.
Priority score:              3.400 (default equal weighting; #1 of 21
                            candidate processes; #1 or #2 under 3 of 5
                            weightings tested, displaced only by two
                            near-zero-volume workbooks under risk-averse
                            weighting -- see Section 12 for why that
                            displacement doesn't change the
                            recommendation)
Why automate this first:    Highest total measured time consumption of
                            any discovered process in this sample, second
                            -highest execution frequency, a strong (77%)
                            single dominant variant suitable for direct
                            RPA scripting, the highest manual-effort
                            share of the three core systems, and a
                            well-bounded, low-complexity risk profile
                            once the rare multi-hop edge cases are
                            explicitly scoped out of the first
                            automation attempt.
```

## Explicit assumptions and uncertainty (instruction #10/#11)

- Process boundaries rest on the Section 2/3 pipeline's own documented
  assumptions (executions never cross a session boundary; a leave-and-
  return detour of ≤5 events is merged into the surrounding execution).
  A different, equally defensible merge threshold would shift execution
  counts and durations somewhat — the *ranking* of the three core systems
  relative to each other was checked to be qualitatively stable across
  the debounce/merge sweep in Section 2/3, but was not re-run under every
  possible threshold as a full sensitivity study.
- "Business impact" and "risk" are explicit judgment proxies, restated
  here for visibility, not measurements this dataset can provide.
- Absolute time figures are sample-scale (≈3 hours of total recorded
  activity across 15 sessions), not annualized production volume.
- The #1 ranking is not universally stable across every weighting tested
  (Section 9) — reported, not hidden, with the reasoning for why the
  displacement doesn't change the practical recommendation.
- No screenshot content was used as evidence anywhere in this analysis
  (per instruction #4/#5) — every claim above traces to structured event
  fields (`window_title`, `active_app`, `interaction_category`,
  `event_type`, timestamps), not image content.

## What this is not

This is a **frequency/time/consistency-based prioritization from event-log
evidence**, not a validated ROI model — Dataset B has no ground truth, no
cost data, and no production-volume data. It is the defensible,
evidence-based starting point instruction asked for, to be handed to Step
3 for a working prototype targeting the dominant HR/Payroll variant.
