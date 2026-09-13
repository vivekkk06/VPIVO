# HR / Payroll Automation Prototype (Day 3, Step 3)

A demonstration of the automation opportunity discovered from Dataset B
— **not** a reproduction of, connection to, or claim about any
production HR/Payroll system. Dataset A's locked segmentation
architecture (`src/procmine/segmentation/`, threshold values
0.9078/0.8860/0.40/4680.2613, boundary F1 0.3440) was neither read nor
modified anywhere in this work, and none of its numbers are used or
reinterpreted here.

## 1. Executive summary

Dataset B's process-discovery analysis (Day 3, Step 2) found a
repeated, structurally consistent, click-driven interaction with a
browser-based HR/Payroll system, occurring in 94 of 122 (77.05%)
HR/Payroll executions. This prototype automates exactly that
interaction — route navigation, note insertion, and a human-reviewed
confirmation click — for the four routes where the pattern is directly
evidenced, using selector-based RPA/UI automation. It deliberately does
not automate the Word-detour variant, rare multi-hop cases, or any
route/behavior the logs don't support.

## 2. Why HR/Payroll was selected

Selected in `reports/day3/automation_candidate_analysis.md` on measured
evidence: highest total observed time (49.9 minutes in the sample)
among the three core systems discovered in Dataset B, second-highest
execution frequency, and a 77% single dominant variant. Ranked #1 under
the default equal weighting and two of four alternate weightings
tested in a sensitivity sweep; the weightings that displaced it did so
only in favor of near-zero-volume processes (2–4 minutes total time),
explained rather than treated as disqualifying in that report.

## 3. Dataset B evidence (observed, not projected)

From `reports/day3/hr_payroll_dominant_path_analysis.md` and
`hr_payroll_dominant_path_dataset_b.json`:

- Dataset B has **no ground-truth execution labels** — treated
  throughout as production-style, unlabeled data, unlike Dataset A.
- 122 total HR/Payroll executions were identified by the Day 3 process-
  discovery pipeline (system-change boundary detection +
  leave-and-return merge — a method built fresh for Dataset B, not
  reused from Dataset A's locked segmentation architecture).
- **100% of the 134 observed `browser_form_input` events used
  `input_method: "paste"`** — never live typing.
- **139 note-field interactions vs. 138 confirmation-button clicks** —
  a near-1:1 pattern, not asserted as exactly 1:1 (one known
  discrepancy in the `#/leave-applications` route).
- The pasted note's actual text content is unobservable — `payload
  .value` is `null` on every recorded `browser_form_input` event.
- No event type in the schema is named "submit" — reading the
  `btn-<route>-ok` click as confirmation is a **DOM-structure
  inference**, repeated as such throughout this document, never
  presented as a directly-labeled fact.
- No judgment-requiring action (branching logic, conditional pattern,
  decision point) was evidenced inside the dominant path itself.

## 4. Dominant-path statistics

| | Count | Share |
|---|---:|---:|
| Dominant path (single-system) | 94 / 122 | 77.05% |
| Word-detour variant | 24 / 122 | 19.7% |
| Rare multi-hop cases | 4 / 122 | 3.3% |

(These are the exact, re-verified figures from
`hr_payroll_dominant_path_dataset_b.json`; the 24/19.7% figure is more
complete than an earlier partial count of 22/17.9% that only summed the
two largest of seven observed variant shapes — corrected once all
variants were enumerated, not silently left inconsistent between
reports.)

## 5. Observed workflow

```
Human/process selects one of four routes
  -> #/payroll-items | #/leave-applications | #/onboarding | #/social-insurance
  -> navigate to the route (SPA hash-route change, "spa_popstate")
  -> click/focus the route's note field: #<route>-note
  -> paste text into it (100% of observed inputs; never typed)
  -> click the route's confirm button: #btn-<route>-ok
```

## 6. DOM-level evidence

Directly observed, not inferred: `payload.element.attributes.id` on
`browser_click` events recurring as `pi-note`/`btn-pi-ok` (69/69
pairs), `ob-note`/`btn-ob-ok` (32/32), `si-note`/`btn-si-ok` (11/11),
`la-note`/`btn-la-ok` (27/26); `payload.field.id`,
`payload.field.label`, and `payload.input_method` on
`browser_form_input` events confirming the paste-only pattern;
`payload.url`/`payload.previous_url` hash fragments on
`browser_navigation` events confirming the four (plus two much rarer,
unconfirmed) routes.

## 7. Why RPA/UI automation was selected

The observed interaction is entirely DOM-level (`browser_click`,
`browser_form_input` against stable CSS/element ids), repeated
identically across 94 independent executions and multiple operators,
with no unstructured content or judgment step inside it. This is
RPA/UI automation's textbook case: deterministic, selector-addressable,
repetitive UI interaction.

## 8. Why API automation was NOT selected

**No API integration point was evidenced anywhere in Dataset B.** Every
recorded interaction with the HR/Payroll system is a browser DOM event;
no event type, payload field, or network-level signal indicates a
backend API being called directly. Building an API integration would
require inventing an endpoint contract the logs do not support —
explicitly disallowed by this task's own instructions ("do not invent
API endpoints or hidden business logic"). If a real API exists behind
this system, discovering it is future work outside this dataset's
evidence, not something to assume here.

## 9. Why an AI agent was NOT selected for the dominant path

No unstructured text interpretation, visual judgment, classification,
or decision-making step was observed inside the 94 dominant-path
executions — the entire path is a fixed sequence against a small,
stable set of named DOM elements. Using an LLM or vision model to drive
this interaction would add non-determinism, cost, and a new failure
surface (hallucinated selectors, inconsistent outputs) to a task the
evidence shows is already fully addressable with plain selector logic.
AI assistance is a plausible *future* option specifically for the
Word-detour variant (reading and interpreting a procedure document,
section 16) — outside this prototype's scope, not because AI is
unsuitable there too, but because that variant was explicitly excluded
from Step 3's automation boundary.

## 10. Prototype architecture

```
src/procmine/automation/
  mock_hr_app.py            -- self-contained mock DOM model, fault
                                injection (missing/duplicate/wrong-id
                                elements, navigation failure), and a
                                static demo HTML page renderer
  hr_payroll_automation.py  -- the RPA/UI automation layer: route +
                                note-text validation, navigation,
                                element verification, note insertion,
                                the mandatory human-review checkpoint,
                                and a separate, re-verifying confirm step

scripts/run_hr_payroll_automation_demo.py  -- end-to-end demo across
                                               all 4 routes plus one
                                               deliberate safe-failure
                                               example; also writes the
                                               static HTML demo page

tests/test_mock_hr_app.py            (18 tests)
tests/test_hr_payroll_automation.py  (29 tests)
```

No new third-party dependency was introduced (checked: `requirements.txt`
already had only `matplotlib`, `pytest`, `scikit-learn`; no browser-
automation or web-framework library is installed in this environment).
Rather than add Selenium/Playwright and their binary browser
dependencies — risky in an environment where their availability isn't
verified, and unnecessary to demonstrate the automation *logic* — the
prototype's automation layer takes a `MockHRApplication` instance as an
explicit, injected parameter exposing five methods (`navigate`,
`find_note_field`, `find_confirm_button`, `set_note_value`, `click`). A
production integration swaps this one object for a thin wrapper around
a real browser driver implementing the same five methods against the
same selectors — `hr_payroll_automation.py` itself would not need to
change (section 20).

A real, standalone static HTML/JS page (`hr_payroll_mock_app.html`,
generated by `render_demo_html()`) reproduces the same four routes and
element ids for visual/manual inspection in an actual browser — clearly
banner-labeled "PROTOTYPE / DEMO ENVIRONMENT," not wired to the Python
automation run (no shared process), and never presented as the real
system.

## 11. Supported routes

Exactly the four confirmed routes, no others:

| Route | Note field id | Confirm button id | Evidence |
|---|---|---|---|
| `#/payroll-items` | `pi-note` | `btn-pi-ok` | 69/69 note↔confirm pairs |
| `#/leave-applications` | `la-note` | `btn-la-ok` | 27/26 pairs |
| `#/onboarding` | `ob-note` | `btn-ob-ok` | 32/32 pairs |
| `#/social-insurance` | `si-note` | `btn-si-ok` | 11/11 pairs |

`#/resident-tax` (4 occurrences) and `#/dashboard` (2 occurrences) were
also observed but **without a confirmed note/confirm pattern** — not
included in the allowlist.

## 12. Selector strategy

Element-id-based only (`#<route>-note`, `#btn-<route>-ok`), matching
exactly what Dataset B's own `css_selector`/`xpath` payload fields
recorded. No screen coordinates, no pixel positions, no image matching
anywhere in this prototype — satisfying the explicit constraint against
fragile, non-deterministic interaction.

## 13. Human-review checkpoint

`prepare_note_submission()` performs route/note validation, navigation,
element verification, and note insertion, returning a `ReviewCheckpoint`
— the confirm button is **never clicked** by this call (directly
tested: `clicked is False` after preparation, for all four routes).
Only a second, deliberate call, `confirm_submission()`, passed that
exact checkpoint, performs the click — and only once (re-entrant calls
raise `RuntimeError`), and only if the confirm button, **re-located at
confirmation time** (not clicked from a stale reference), still matches
exactly what was reviewed.

## 14. Failure handling

| Condition | Exception | Tested |
|---|---|---|
| Route not one of the four evidenced ones | `UnknownRouteError` | ✅ |
| Empty/whitespace/`None` note text | `InvalidNoteError` | ✅ (parametrized over `""`, `"   "`, `"\n\t"`, `None`) |
| Navigation fails | `NavigationError` | ✅ |
| Note field or confirm button missing | `ElementNotFoundError` | ✅ |
| Note/confirm field id doesn't match the evidenced pattern | `ElementNotFoundError` | ✅ |
| Multiple matching note fields or confirm buttons | `DuplicateElementError` | ✅ |
| Confirm button changed/disappeared/duplicated between review and confirmation | `ConfirmationFailedError` | ✅ |

Every one of these stops the pipeline immediately with the partial
action log attached to the exception — never a silent click on a
different element, never a fallback guess.

## 15. What remains manual

- Composing the note's actual content (its source is not observable in
  Dataset B).
- The final approval decision (by design — the human-review boundary,
  not a gap).
- The two unconfirmed-pattern routes (`resident-tax`, `dashboard`).
- Everything in the Word-detour and rare multi-hop groups (below).

## 16. Word-detour variant

**Deliberately not automated.** 24 of 122 executions (19.7%) involve
opening a named procedure document —
`nyusha_checklist_shinsotsu_batch` ("New-Employee Checklist") in 47 of
~129 document-open events, the most common, plausibly connected to
`onboarding` also being the most-visited route (43 occurrences) — before
returning to the HR system. This requires either a scripted document
lookup or a human judgment call; not evidenced as reducible to the same
deterministic pattern. **AI assistance is a plausible future direction
here specifically** (interpreting a reference document's relevant
section) — explicitly out of this prototype's scope, not attempted.

## 17. Rare multi-hop variants

**Deliberately not automated.** Only 4 examples exist in the entire
dataset (3 Windows-Explorer detours, 1 multi-hop HR↔Financial pattern,
4 round-trips) — too few to generalize any rule from. Not detected or
handled by this prototype; would surface as ordinary manual work today.

## 18. Risks and mitigations

| Risk | Mitigation already built in |
|---|---|
| Confirming an unintended action (OK-button-as-submit is an inference) | Mandatory, separate human-review checkpoint before every confirm click |
| Content-sourcing gap (note text origin unobservable) | Note text is an explicit required input, never invented; empty/whitespace input is rejected |
| DOM drift between review and confirmation | Confirm button is re-located and re-verified immediately before clicking, not cached |
| Ambiguous DOM state (ids duplicated/changed) | Duplicate/mismatched-id detection refuses to guess |
| Silent partial failure | Every action (success or failure) is logged with a timestamp; failures raise a specific, catchable exception |
| Route/system drift over time | Allowlist is explicit and small (4 routes); anything else is rejected outright |

## 19. Prototype limitations

- Automates against an **in-memory Python model** of the observed DOM
  structure, not a real browser or the real HR system — a
  demonstration, not a production integration.
- The near-1:1 note/confirm pattern (139 vs. 138) has one known,
  unexplained exception in the source evidence; this prototype does not
  attempt to explain or reproduce it.
- No handling for the two rare, unconfirmed routes.
- The static demo HTML page is a separate, visual-only artifact — not
  wired to the Python automation layer (no shared browser process).

## 20. Productionization path

1. Implement the same five-method interface
   (`navigate`/`find_note_field`/`find_confirm_button`/`set_note_value`
   /`click`) against a real browser driver (Selenium/Playwright), using
   the **identical `id`-based selectors** already validated here —
   `hr_payroll_automation.py` itself needs no change.
2. Add a real, explicit note-content source as an input to
   `prepare_note_submission` — never inferred or hard-coded.
3. Confirm with the actual business/system owner whether the OK-button
   click really represents "submit" before ever removing the
   human-review checkpoint for any route.
4. Pilot on `#/payroll-items` alone (the largest single confirmed
   pattern, 69/69) before extending to the other three.
5. Revisit the Word-detour variant as its own, separately-scoped
   follow-up (possibly AI-assisted document lookup, possibly a narrower
   human-in-the-loop step) — not a rewrite of this automation.

## 21. Expected impact / ROI framing — observed vs. projected

**Observed (Dataset B, this sample only)**: 94/122 (77.05%) dominant-
path executions, 24/122 (19.7%) Word-detour, 4/122 (3.3%) rare edge
cases, across a ~3-hour, 15-session recorded sample with no
ground-truth labels and no production-volume data.

**What this prototype demonstrates**: that the navigate→note→confirm
sequence for the four confirmed routes is mechanically automatable with
a small, deterministic, selector-based RPA layer, with mandatory human
review preserved.

**What is explicitly NOT claimed**: any specific number of hours,
dollars, or percentage of "automation savings." Dataset B does not
contain production execution frequency, labor cost, or annualized
volume — projecting a concrete saving from a 3-hour sample would be
fabrication.

**The formula a real estimate would require**, stated so the
measurement gap is explicit rather than papered over:

```
Potential labor hours saved (per period)
  = automatable executions (per period)
  × average manual handling time per execution
  × automation coverage (share of executions the automation actually
    completes without human escalation)
```

Where, from this analysis:
- `average manual handling time per execution` ≈ 11.4s (median) /
  17.8s (mean) for the dominant path **in this sample only** — not
  validated as representative of steady-state production timing.
- `automation coverage` ≈ 77.05% is an upper bound *if* production
  behavior matches this sample's variant mix — itself unverified beyond
  Dataset B's own recording window.
- `automatable executions (per period)` is **unknown** — Dataset B has
  no timestamp-to-calendar-period mapping that would support
  extrapolating a daily/weekly/monthly production volume.

**What would be needed to turn this into a real ROI estimate**:
production execution-frequency data over a representative period (not
a 3-hour synthetic-looking sample), a validated measure of true
human handling time (this sample's durations include non-deliberate
trailing events, e.g. an automatic `screenshot_smart` firing after the
last real action — see the dominant-path analysis report), and a
measured post-deployment automation success/escalation rate rather
than an assumed one.
