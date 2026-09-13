# HR / Payroll System — Dominant-Path Forensic Analysis

Focused deep-dive on the selected automation candidate, before any
Step-3 prototype work. Dataset-A's locked architecture is untouched
(no file under `src/procmine/segmentation/` was read or modified in
this analysis). No business semantics are invented anywhere below —
every page name, field label, and DOM identifier quoted here is read
directly from the raw event payloads (`payload.url`,
`payload.field.label`, `payload.element.attributes.id`).

Method: Section 3's exact execution pipeline (`system_change_boundaries`
+ `merge_leave_and_return`, threshold 5 events, unchanged) was **rebuilt
directly against the raw dataset** rather than reverse-engineered from
`process_executions_dataset_b.json` by timestamp range — an earlier
draft tried the timestamp-range approach and a cross-check caught it
silently misattributing events for 16 of 94 executions wherever two
events share an exact millisecond at a segment boundary. The rebuild
was verified to reproduce **0 of 645** executions differently from the
already-committed JSON (`rebuild_cross_check_mismatches: 0` in the JSON
artifact) before any of the analysis below was trusted.

New code: `src/procmine/process_discovery/dom_evidence.py` (URL-route
and DOM-element extraction) and `dominant_path_forensics.py`
(variant-group classification, execution-boundary context), with 23
new tests (`test_dom_evidence.py`, `test_dominant_path_forensics.py`)
— one of which (`test_classify_word_only_no_hr_at_all_is_other`) caught
a real edge-case bug in the first version of the classifier before it
shipped.

---

## 1–4. The dominant path, precisely

**94 of 122 HR/Payroll executions (77.0%)** follow the pure single-system
path — no detour into any other application at all
(`variant_signature == ("system:HR人事給与システム",)`).

**Exact ordered event/step sequence**: there is no single fixed byte-
for-byte sequence — event counts per execution range from 1 to 204
(median 23) — but the *structural* backbone is highly consistent and
directly observable from DOM-level evidence:

```
app_switch (entry into the HR system window)
  -> mouse_click (focus into the window / a form field)
  -> [ browser_navigation: route change, e.g. -> #/onboarding ]
  -> browser_click  on #<route>-note   (class "input" — focuses the note textarea)
  -> browser_form_input on #<route>-note, input_method = "paste"   (fills the note)
  -> browser_click  on #btn-<route>-ok (class "btn success" — confirms)
  -> [ mouse_scroll / keystroke / clipboard_change — supporting activity ]
  -> screenshot_smart (trailing, automatic — not a deliberate action; fires as the window loses focus)
```

`<route>` is one of the four confirmed, evenly-paired routes: `pi`
(`#/payroll-items`), `la` (`#/leave-applications`), `ob` (`#/onboarding`),
`si` (`#/social-insurance`) — the id-prefix correspondence is read
directly from the data (each route's note-field id and confirm-button
id share the same two-letter prefix as the route name's initials; not
an invented mapping).

## 5. Start and end conditions

- **Entry**: 70/94 (74.5%) executions begin with a `mouse_click`
  (clicking into the window), 15 with `keystroke`, 8 with `shortcut`, 1
  with `screenshot_smart`. The event immediately *before* entry (in the
  full session, outside the execution's own boundary) is
  **`Microsoft Word` 48 times (51%)** and `Microsoft Edge` (already on
  a different tab/route) 27 times — i.e. even the "pure" dominant path
  is very often reached straight from Word, just not close enough in
  time/event-count to be merged into one execution by Section 3's
  detour rule.
- **Exit**: 68/94 (72.3%) executions *end* on a `screenshot_smart` event
  — this is an automatic side-effect of the recording agent firing as
  the window loses focus, **not itself a deliberate action**; the real
  last deliberate action is whatever precedes it. The event immediately
  *after* exit is `Microsoft Word` 49 times (52%), `Microsoft Edge` 31
  times, `Notepad` 12 times.
- **Reading these together**: the dominant HR path is frequently
  sandwiched between Word-document activity in the wider session (entry
  and exit both point to Word roughly half the time) — this is a
  distinct pattern from the Word-*detour* variant (§ comparison below),
  where the Word visit happens *inside* one execution; here it happens
  in the *surrounding* executions instead, close in time but not close
  enough to merge.

## 6. Applications and window titles involved

Exclusively `Microsoft Edge`, window title `HR人事給与システム` (with Edge's
own "and N more pages" tab-count suffix varying — a real, harmless
artifact of how many browser tabs happen to be open, not a different
page). No other application appears *inside* a dominant-path execution
by definition (that's what makes it "dominant" rather than a detour).

## 7. Repeated actions

The single most repeated, most structurally consistent action pair in
the entire dataset: **click a `#<route>-note` textarea, then click
`#btn-<route>-ok`** — occurring 69/69 times for `payroll-items`, 32/32
for `onboarding`, 11/11 for `social-insurance`, and 27/26 for
`leave-applications` (one execution where a note-click wasn't followed
by a matching confirm-click within the observed slice — the one
exception to an otherwise exact 1:1 pattern). Total: 139 note-field
clicks against 138 confirm-button clicks across 94 executions.

## 8. Input actions

**134 `browser_form_input` events, 100% via `input_method: "paste"`** —
not one instance of live typing (`"type"`) was observed inside the
dominant path. This is a strong, direct, non-inferred finding: whatever
text goes into a note field arrives already-composed from the clipboard,
not typed live. Separately, `keystroke` (526) and `shortcut` (218)
events also occur, but these cannot be tied to a specific field the
same way `browser_form_input` can (they are the OS-level individual
keystroke record, not the browser's own occasionally form-aware log).

## 9. Search/navigation actions

**28 `browser_navigation` events**, all `navigation_type: "spa_popstate"`
— hash-route changes within the same single-page application, never a
full page reload. There is no distinct "search" event type in this
schema; the closest available signal is route navigation itself (moving
between `#/payroll-items`, `#/onboarding`, etc.), which is what a user
would do to locate the right record/section. **91% of dominant-path
executions (mean 1.12, median 1.0 distinct routes per execution) touch
exactly one route** — the dominant path is almost always a single-page
task, not a multi-page search.

## 10. Copy/paste or data-transfer actions

**187 `clipboard_change` events** across 94 executions (mean ~2 per
execution) — consistent with the paste-only input method above: content
is copied from somewhere (not observable in this dataset — see
uncertainty section) before being pasted into the note field.

## 11. Output/submission actions

**No event type in this schema is explicitly labeled "submit."** The
closest and best-supported candidate is the `browser_click` on
`#btn-<route>-ok` (class `btn success`) — its near-perfect 1:1 pairing
with the preceding note entry, its `"success"` class name, and its
position immediately after the paste all support reading it as the
confirmation/submission action, but this is a **reasonable inference
from DOM structure, not a directly labeled fact** — recorded here
explicitly as an inference, not asserted as certain.

## 12. Time spent in each meaningful step (dominant path only)

| Step (system, category) | Occurrences | Total time | Avg time |
|---|---:|---:|---:|
| HR / pointer (clicking) | — | — | (see `step_frequency_dataset_b.json`, scoped to all 122 HR executions; the dominant-only breakdown is in the JSON artifact's `dominant_variant_analysis`) |
| HR entry (`app_switch`) | 94 | — | one per execution, by construction |
| `browser_form_input` (paste) | 134 | — | near-instant (paste is a single discrete event, not a duration) |
| `browser_click` note+confirm | 277 | — | — |
| trailing `screenshot_smart` | 829 total in group | 0ms each | automatic, non-deliberate |

Full execution-level duration: **mean 17.8s, median 11.4s, p25 3.1s,
p75 22.1s, max 125.4s** (`hr_payroll_dominant_path_dataset_b.json` →
`dominant_variant_analysis.duration_ms_distribution`). The spread is
wide — this is not a fixed-length script, but the structural steps
within it (one route, one note+confirm cycle) are highly consistent.

## 13. Which actions appear deterministic

- **The note-click → paste → confirm-click triple**, per route. Same
  DOM ids, same class names, same near-1:1 pairing, across 94
  independent executions and (per the session listing) multiple
  different operators. This is the strongest deterministic evidence in
  the entire dataset.
- **Route navigation** — a small, closed, repeatedly-observed set of 6
  hash routes (`payroll-items`, `leave-applications`, `onboarding`,
  `social-insurance`, plus the much rarer `resident-tax` and
  `dashboard`), always via `spa_popstate`, never an external page load.
- **Entry via `app_switch`, exit followed by a trailing
  `screenshot_smart`** — a structural constant of how the recording
  agent itself behaves, not a business action, but deterministic and
  safely ignorable for automation purposes.

## 14. Which actions appear to require human judgment

**None of the events *within* the dominant path itself directly
evidences a human judgment/decision point.** No branching event type,
no conditional-looking pattern, no visible decision moment is present
in the observed 94 executions. The one place judgment plausibly enters
is the *content* of the pasted note — but its content is not observable
(see below), so this cannot be confirmed either way from the logs. The
Word-detour variant (§ comparison) is where an actual
reference-consulting, judgment-adjacent action is directly observed —
the dominant path itself is not.

## 15. Which actions are uncertain because the logs don't expose enough information

- **The pasted note's actual text content** (`payload.value` is `null`
  for every `browser_form_input` event — masked or not captured at the
  source). Whether the note text is a fixed template, a per-case
  variable string, or something requiring judgment to compose cannot be
  determined from this dataset.
- **Where the pasted content comes from** — no `clipboard_change`
  payload in this schema exposes the copied text either (Day 1 already
  established this for Dataset A; confirmed unchanged here).
- **The exact source/target of `keystroke` and `mouse_scroll` events**
  — these are OS-level, not tied to a specific DOM element the way
  `browser_click`/`browser_form_input` are.
- **1 of 27 `leave-applications` note-clicks has no matching confirm
  click** in the observed slice — unclear whether the confirm happened
  just outside the execution's boundary, was skipped, or failed.

## 16. Automation scope — what should and should NOT be automated first

**IN SCOPE for a first prototype** (the deterministic backbone, §13):
navigate to one of the four well-evidenced routes, locate the
`#<route>-note` field, insert a note (content sourced from wherever the
business process currently prepares it — this dataset does not reveal
that source), click the corresponding `#btn-<route>-ok` confirm button.

**OUT OF SCOPE for a first prototype, deliberately**:
- The Word-detour variant (§ comparison, 19.7% of executions) — requires
  either a scripted lookup of the referenced procedure document or a
  human-in-the-loop check; not evidenced as reducible to the same
  deterministic pattern.
- The rare multi-hop edge cases (§ comparison, 3.3%) — only 4 examples
  exist in the entire dataset, too few to generalize a rule from.
- Generating the pasted note's *content* — its source is not observable;
  automating only the mechanical paste-and-confirm action while leaving
  content sourcing to the existing process (or a separately-scoped
  follow-up) is the honest boundary this dataset supports.
- The `resident-tax` and `dashboard` routes (4 and 2 occurrences total)
  — too rare in this sample to confirm the same note/confirm pattern
  applies there.

---

## Comparison: dominant (77%) vs. Word-detour (19.7%) vs. rare edge cases (3.3%)

| | Dominant (n=94) | Word-detour (n=24) | Rare edge (n=4) |
|---|---|---|---|
| Structure | Single HR route, note+confirm | HR → Word (1 or more dips) → HR | HR ↔ Explorer (×3) or HR ↔ Financial ×4 round-trips (×1) |
| Median duration | 11.4s | longer (37–50s for the two shapes seen in `process_discovery.md` §4) | 40.7–131.7s — the longest executions in the whole HR process |
| What happens in the detour | — | A **named procedure document is opened** — `nyusha_checklist_shinsotsu_batch` ("New-Employee Checklist") in 47 of ~129 document-open events, i.e. the most-consulted reference, aligning with `onboarding` also being the most-visited HR route (43 occurrences) | Windows Explorer (file lookup) or a genuine back-and-forth with the Financial system (4 round-trips in the one observed case) |
| Automation read | Deterministic, in scope | Needs either a scripted document lookup or human-in-the-loop; not evidenced as automatable with the same confidence | Too rare (n=4) to generalize; handle manually |

The onboarding-route/New-Employee-Checklist correspondence is a genuine
cross-check the data itself provides, not an assumption: the most-opened
reference document during detours is the one thematically tied to the
most-visited route in the dominant path.

## Variability within the dominant path itself

Despite being "the same variant" by system-sequence, the 94 executions
vary substantially: event count 1–204 (median 23), duration 0–125,430ms
(median 11.4s), 0–3 distinct routes touched (median 1). A handful of
executions are extreme outliers (a single 1-event, 0ms "execution" — a
momentary click into the window that ended immediately, arguably not a
full task at all, reported here rather than silently trimmed). The
*qualitative* structure (route → note → confirm) is highly consistent;
the *quantity* of supporting clicks/scrolls/keystrokes around it is not.

## Leakage / scope confirmation

No file under `src/procmine/segmentation/` (the Dataset-A locked
architecture) was imported, read, or modified by this analysis or its
new code. No automation/prototype code was written — this is analysis
only, per instruction.

---

## Recommendation for Step 3

**RPA / UI automation** is the appropriate implementation form for the
in-scope portion identified above — not a scripted workflow in the
sense of a headless script, not API-based automation, and not
AI-assisted automation, based strictly on what was observed:

- **Not API-based**: nothing in Dataset B evidences that the HR system
  exposes an API; every observed interaction is DOM-level
  (`browser_click`, `browser_form_input` against CSS selectors/element
  ids). A UI-level approach is the evidenced-safe default.
- **Not AI-assisted for the dominant path**: no unstructured text
  reading, visual judgment, or classification step was observed inside
  the dominant path itself — it is a stable, repeated click/paste/click
  sequence against a small, fixed set of DOM elements, which is RPA's
  strongest use case, not a case for an LLM or vision model.
- **AI-assistance (or human-in-the-loop) is appropriate only for the
  Word-detour variant** (19.7% of executions), specifically for reading/
  interpreting the referenced procedure document — genuinely different
  in character from the dominant path and deliberately excluded from
  this first automation scope.
- **A plain scripted workflow (no UI, e.g. calling a backend directly)
  is not supported by the evidence** — there is no sign of a
  non-UI integration point in this dataset.

**Concretely**: build an RPA script that navigates to a given HR route,
inserts a provided note into `#<route>-note`, and clicks
`#btn-<route>-ok` — scoped to the four well-evidenced routes
(`payroll-items`, `leave-applications`, `onboarding`,
`social-insurance`), explicitly excluding the Word-detour and rare
multi-hop cases from v1, and treating note-content sourcing as a
separate, human- or system-provided input rather than something this
dataset justifies generating automatically.
