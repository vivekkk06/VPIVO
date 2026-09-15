# Day-5 Frontend Implementation

Companion to `data_contract.md` (the data specification) and
`frontend_architecture.md` (the architectural decisions). This document
records what was actually built, how it was verified, and what remains
open.

---

## 1. Hypothesis

> An interactive deterministic replay and process-exploration layer can
> improve observability and explainability of the existing operation-log
> analysis without changing the underlying segmentation,
> instrumentation-health, process-ranking, or automation decisions.

The second half of that claim — "without changing" — is testable and was
tested. The first half — "improves observability and explainability" — is
a claim about a reviewer's experience and is **not** settled by the code
existing. See §15.

## 2. Implementation scope

Built:

- A React + TypeScript + Vite dashboard with five screens, consuming only
  the generated Day-5 data bundle.
- A local Python API exposing the existing HR/Payroll prototype, using the
  standard library only.
- 28 frontend tests and 14 API tests.

Not built, deliberately: any analytical computation in the browser, any
Dataset-A replay, any directly-follows graph for non-HR processes, any
persistence layer, any authentication, any deployment configuration.

## 3. Architecture

```
Days 1-4 artifacts  --(read-only)-->  scripts/build_frontend_data.py
                                              |
                                     frontend/public/data/*.json
                                              |
                                        React dashboard
                                              |
                              HR demo only ---+---> scripts/serve_hr_demo_api.py
                                                        |
                                              procmine.automation (unchanged)
```

Four of the five screens are pure static-data consumers. Only the HR
automation demo talks to a backend, because only it is stateful.

Deliberate dependency restraint: no router (screen state is a `useState`
union), no chart library (the directly-follows graph is a table of the
already-computed edges, the replay timeline is CSS), no UI framework, no
state-management library. Runtime dependencies are `react` and
`react-dom` only. The production bundle is **180 KB raw / 55 KB gzipped**.

## 4. Screens

| # | Screen | Source files | Notes |
|---|---|---|---|
| 1 | Dashboard | all eager files | Dataset-B scope, top opportunity, Dataset-A quality, instrumentation health |
| 2 | Execution Step Replay | `executions-index.json`, lazy `executions/<session_id>.json` | play / pause / restart / 0.5×–4× speed |
| 3 | Process Explorer | `processes.json`, `variants.json`, `hr-payroll.json` | ranked vs excluded; HR forensic split and DFG |
| 4 | Opportunities | `opportunities.json` | canonical ranking, Pareto, sensitivity, filter/sort/detail |
| 5 | HR Automation Demo | live API | prepare → review → confirm |

Every screen carries a collapsible **“Data source / evidence”** panel
naming the Day-1–Day-4 artifact behind its figures, with file sizes read
from `meta.json`.

## 5. Data loading strategy

Eager on startup: `meta`, `sessions`, `executions-index`, `processes`,
`variants`, `opportunities`, `instrumentation`, `hr-payroll`,
`dataset-a-metrics` — **465 KB** total, fetched in parallel.

Lazy: `executions/<session_id>.json` (~300 KB each, 4.4 MB combined),
fetched only when a session is selected and then held in an in-memory
`Map`. A test asserts no per-session file is requested during the eager
load, and another asserts a repeat selection issues no second request.

## 6. Why Session Replay is step-level

The finest granularity in the bundle is `ordered_steps`: `system`,
`interaction_category`, `n_events`, `start_ms`, `end_ms`,
`dominant_event_types`. Individual raw events exist only in the gitignored
~2.8 GB dataset directories and are not part of the frontend contract.

The screen is therefore called **Execution Step Replay**, each step shows
the number of raw events it covers, and the page states in prose that this
is not an individual-event replay. A test asserts that disclaimer is
present. No synthetic event stream is generated to make the timeline look
finer than the data supports.

Playback advances through persisted steps using the real recorded gap
between them, clamped to 2 s so a long idle pause does not stall the demo,
and divided by the selected speed. It is visualisation only — nothing is
executed or re-derived.

## 7. Why Dataset A has no replay

The locked Day-2 pipeline is evaluated but never serialises its predicted
boundaries; only pooled and per-session metrics exist. Rendering a
Dataset-A replay would require adding an export path through the locked
segmentation architecture, which is out of scope for a visualisation
layer.

Dataset A therefore appears as aggregate quality metrics (precision
0.2358, recall 0.6355, F1 0.3440, 79.05 % fragmented, under-segmentation
0.1412, over-segmentation 1.603) and as instrumentation health. A
"Data availability" notice on the replay screen explains the omission
rather than leaving it as a silent gap.

## 8. Provenance approach

A compact `<details>` panel per screen maps each displayed value to its
source artifact path and size, drawn from `meta.json.canonical_sources`.
The Opportunities screen additionally surfaces
`opportunities.json.canonical_note`, which names the superseded artifacts
by filename and says why they are not read.

## 9. HR automation API boundary

Standard library `http.server`; no new Python dependency.

| Endpoint | Purpose |
|---|---|
| `GET /api/routes` | the four evidenced routes, read from `KNOWN_ROUTE_PREFIXES` |
| `POST /api/prepare` | `{route, note_text}` → checkpoint payload + opaque token |
| `POST /api/confirm` | `{checkpoint_token}` → `AutomationResult` |

Status codes carry meaning: **200** success, **400** malformed request or
unknown/consumed token, **422** the prototype refused on its own safety
rules (a *safe stop*, returned with `error_type` and the partial action
log).

The wrapper adds no automation logic. Route validation, note validation,
element verification and confirm-time re-verification all execute inside
`procmine.automation.hr_payroll_automation`, unmodified.

## 10. Safety / checkpoint model

`MockHRApplication` and `ReviewCheckpoint` are held **server-side**, keyed
by an opaque token, for the life of one process. This is not incidental:
`confirm_submission` re-locates the confirm button at confirm time rather
than clicking a cached reference, precisely because the page may change
during the human review pause. That guarantee only holds if the same
objects survive between the two calls, so a stateless design that rebuilt
them per request would silently defeat it.

Consequences the UI enforces:

- The browser holds no automation state and cannot construct a checkpoint.
- The "Approve and confirm" control **does not exist** until a
  server-issued checkpoint is in hand; the screen says so explicitly.
- A fresh `MockHRApplication` is created per checkpoint, so concurrent
  demos cannot interfere.
- A consumed token is discarded, so a checkpoint cannot be replayed.
- The note text must be supplied by the user. No default is offered and
  none is invented.

## 11. Testing

| Suite | Before | After |
|---|---:|---:|
| Python (`pytest tests/ -q`) | 490 | **504** (+14 API tests) |
| Frontend (`npx vitest run`) | — | **28** |

No existing test was modified or weakened. Frontend tests run against the
**real generated bundle** on disk rather than fixtures, so a superseded
value in the artifacts would fail the tests rather than pass silently.

Notable guards:

- HR opportunity renders **0.4401**, and **0.4186 appears nowhere**.
- Rank 4 is Financial Accounting and rank 5 is Expense Calculation, each
  asserted within its own table row.
- HR variant split renders 94 / 24 / 4, each scoped to its own row because
  the same integers also appear in the generic variant table.
- No per-session execution file is fetched during the eager load; a repeat
  selection issues no second request.
- Confirmation is impossible without a checkpoint; safe stops render
  distinctly from API errors; a missing bundle file renders a data error
  naming the file instead of crashing.
- A checkpoint cannot be confirmed twice.

## 12. Performance

Production build: 180.17 KB JS (55.39 KB gzipped), 5.51 KB CSS. Eager data
465 KB. Worst case for a session selection is one ~300 KB fetch, cached
thereafter. `executions-index.json` (284 KB) backs every list and table
without touching the lazy files.

No virtualisation was added: the largest rendered table is 645 rows and
the largest step list is bounded by one execution. Adding it now would be
premature.

## 13. Limitations

- Directly-follows graphs and trace-similarity evidence exist for
  HR/Payroll only; the Day-3 script did not persist them for the other 20
  processes. The UI says so where relevant rather than showing an empty
  panel.
- No Dataset-A replay (§7).
- No raw event view (§6).
- The DFG is rendered as an edge table, not a node-link diagram. A graph
  layout would need a charting dependency and answers no question the
  table does not.
- The API is a local development server: single process, in-memory
  checkpoints, permissive CORS, no authentication. It is not hardened and
  is not intended to be deployed.
- `npm audit` reports 5 advisories (3 moderate, 1 high, 1 critical) in the
  dev-dependency tree. They were **not** auto-fixed, because `npm audit
  fix --force` would introduce breaking major-version changes to the build
  tooling. Flagged for the engineer rather than acted on unilaterally.

## 14. Intentionally not implemented

Dataset-A predicted-boundary visualisation; raw-event replay; non-HR
directly-follows graphs; any recomputation of scores, thresholds, entropy
or boundaries in the browser; a routing library; a charting library; a
component framework; authentication; deployment configuration; any change
to Days 1–4; any work-log entry (left to the engineer).

## 15. Is the hypothesis supported?

**The "without changing" half is supported.** Verified: no file under
`src/procmine/segmentation/`, `src/procmine/process_discovery/`,
`src/procmine/automation/`, `src/procmine/instrumentation_health.py`, or
`reports/day1..day4/` was modified; the existing 490 tests still pass
unchanged; the dashboard recomputes nothing.

**The "improves observability and explainability" half remains to be
evaluated.** A working prototype is evidence that the exploration layer
*can exist* and that every figure it shows is traceable to a source
artifact. Whether it actually makes the analysis easier for a reviewer to
understand is a judgement only a reviewer can make. Nothing measured here
establishes it, and it should not be reported as established.

**Verification method, stated honestly:** correctness was verified
programmatically — 28 jsdom-rendered component tests against the real
bundle, 14 API tests, and live HTTP checks against a running dev server
(canonical values served, lazy file served, prepare → confirm flow, and
all four safety refusals). The rendered interface was **not** visually
inspected in a browser; no screenshots were taken and none are claimed.
