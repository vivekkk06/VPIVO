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

Not built in the first pass: any analytical computation in the browser, any
Dataset-A replay, any directly-follows graph for non-HR processes, any
persistence layer, any authentication, any deployment configuration.

**Partly superseded.** §16–§22 record the integration upgrade made later the
same day: an execution state machine, persistence, an
authentication/authorisation boundary and a REST adapter were added. The
other exclusions stand — no analytical computation in the browser, no
Dataset-A replay, no non-HR graphs, no deployment configuration.

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
- The API is a local development server. It is not hardened and is not
  intended to be deployed. Since the integration upgrade it has a
  development authentication boundary, a localhost-only CORS allowlist and
  optional SQLite persistence (§16–§22) — none of which makes it production
  ready. §22 states exactly what is still missing.
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

---

# Day-5 integration upgrade

The first pass proved the *automation logic* — route allowlist, note
validation, element verification, human checkpoint, confirm-time
re-verification. What it did not have was a realistic **integration
boundary**: one target (an in-memory mock), no execution identity, no
persistence, no authentication, and one genuinely unsolved production
problem documented but not addressed — a confirmation whose response is
lost.

These sections record the upgrade that closed that gap. **No analytical
result changed**, and the production boundary stays exactly where it was:
**LOCAL VALIDATED — not connected to any real HR system.**

## 16. Integration Architecture

```
React
  ↓
HTTP API            (scripts/serve_hr_demo_api.py)
  ↓
Authentication / Authorization boundary   (integrations/auth.py)
  ↓
Policy / Safety     (automation/hr_payroll_automation.py — unchanged)
  ↓
Automation Orchestrator                   (integrations/orchestrator.py)
  ↓
HRApplication interface                   (integrations/hr_application.py)
  ├── MockHRApplication      (automation/mock_hr_app.py)
  ├── BrowserHRApplication   (automation/browser_adapter.py)
  └── ApiHRApplication       (integrations/api_hr_application.py)
  ↓
Execution State     (integrations/execution_state.py)
  ↓
Persistence         (integrations/repositories.py)
  ↓
Audit / Observability   (automation/audit.py, integrations/observability.py)
```

**One deliberate deviation from the target diagram: the API layer is the
standard library's `http.server`, not FastAPI.** FastAPI would have been a
new runtime dependency for a local prototype that already works, and the
project's standing rule is to prefer the standard library where practical.
The *position* in the architecture is what matters and is unchanged: every
request is authenticated, then authorised, then passed to the orchestrator.
Swapping in FastAPI would touch one file.

What each layer is not allowed to do is as important as what it does:

| Layer | Owns | Must not |
|---|---|---|
| API | transport, status codes, request shape | automation decisions |
| Auth | who the caller is, what they may do | business rules |
| Policy | route allowlist, note validation, element checks | knowing which target is in use |
| Orchestrator | execution lifecycle, state, audit | re-implementing policy |
| Adapter | driving one concrete target | any policy at all |

A test reads each adapter's source and fails if policy markers appear in it,
and a stronger behavioural test asserts that an invalid route is refused
**before the target is contacted at all** (`sim.calls == []`).

## 17. Integration Adapters

The automation service was annotated with the concrete `MockHRApplication`.
It already worked against the browser adapter by duck typing, but the
*declared* dependency pointed at a concrete class. `HRApplication` is now a
`Protocol` that all three targets satisfy, so the dependency is inverted
structurally rather than incidentally. (A fourth, `HTTPHRApplication`, was added in
the Day-6 extension without changing the service.)

| Adapter | Target | Status |
|---|---|---|
| `MockHRApplication` | in-memory deterministic DOM model | LOCAL |
| `BrowserHRApplication` | Playwright → the committed `hr_payroll_mock_app.html` | LOCAL |
| `ApiHRApplication` | in-process simulator of an external REST service | LOCAL |

**The headline claim, now a test:** the same unmodified
`prepare_note_submission` / `confirm_submission` drive the REST adapter end
to end. Adding the third target required **no change to the automation
service**.

**Why a simulator and not a real client.** No real HR API contract, endpoint
or credential exists, and Dataset B never evidenced an API call. Writing a
client against an invented contract would fabricate the one thing this
project has consistently refused to fabricate. The simulator reproduces the
*properties* that matter for integration engineering — authentication,
idempotency, conflict, rate limiting, timeouts — and is labelled a simulator
everywhere it appears, including in the UI.

## 18. Execution State

Every automation attempt now has an `execution_id` and a persisted record.

```
PREPARED ──► AWAITING_CONFIRMATION ──► CONFIRMING ──┬──► CONFIRMED
     │                │                             ├──► FAILED
     └──► FAILED      ├──► FAILED                   └──► UNKNOWN
                      └──► REPLAYED                        │
                                                    ┌──────┴──────┐
                                                    ▼             ▼
                                                CONFIRMED      FAILED
```

`UNKNOWN` is **not terminal** — that is the entire reason it exists. The
machine refuses illegal transitions loudly: `CONFIRMED → CONFIRMING` is the
shape of a double-submission bug against a payroll record, so it raises
rather than being silently permitted. A test asserts `UNKNOWN` is reachable
only from `CONFIRMING`, because an outcome can only be in doubt if a
confirmation was actually attempted.

The record stores note **length**, never note content, and no token or
credential — it is designed to be safe to ship to a log store.

## 19. Idempotency and Lost Responses

**The problem.** The client sends a confirmation. The external system
applies it. The response is lost. The client cannot tell success from
failure. Retrying duplicates a payroll change; assuming failure loses one.
The earlier README named this as a known gap and explicitly said no status
endpoint existed. It now does.

**The solution: ask, never retry.**

```
POST /api/prepare  → execution_id, AWAITING_CONFIRMATION
POST /api/confirm  → 202, status UNKNOWN, CONFIRMATION_UNKNOWN
GET  /api/executions/{execution_id}/status → CONFIRMED
```

Three situations that look alike from outside are kept distinct:

| Situation | Handling |
|---|---|
| the same request repeated safely | the target recognises the `idempotency_key` and returns the **first** outcome |
| a replayed consumed token | refused — `REPLAYED_REQUEST`, and the target is never contacted |
| an outcome genuinely unknown | resolved by querying status; the mutation is **not** re-sent |

A test counts the simulator's calls and asserts that resolving an `UNKNOWN`
execution adds `get_status` and **no second `confirm`**. HTTP **202** is used
for the unknown outcome deliberately: it is neither a success nor a failure,
and collapsing it into either would be the bug.

**Known production edge case — what this local prototype does not prove.** If a
confirmation succeeds but the client loses the response, the current local prototype
cannot prove whether the action committed, for four reasons:

- the status lookup can only settle an outcome against the **local API simulator** —
  the mock and browser targets have no status source, so an `UNKNOWN` there stays
  `UNKNOWN`;
- execution state is **in-memory by default**, and lost on restart unless
  `EXECUTION_DB_PATH` is set;
- even with SQLite, the adapter used for the lookup lives **in process memory**, so a
  persisted `UNKNOWN` survives a restart but cannot be resolved after one;
- there is no real target system to reconcile against.

Production deployment therefore requires durable execution state and an idempotent
status/reconciliation endpoint keyed by `execution_id` that queries the real target by
the persisted idempotency key, through a freshly constructed client rather than an
in-memory one. **Confirmation is intentionally not retried automatically.**

> **Update (Day 6 extension).** The third point above no longer holds for the new
> `http` target.
>
> - **What changed.** A local HTTP integration (a separate local HR API process with
>   SQLite state) is resolved through exactly such a freshly constructed client. A
>   persisted `UNKNOWN` execution is now settled after a restart when
>   `EXECUTION_DB_PATH` is set.
> - **What still holds.** The other three points are unchanged. The target is still
>   a local simulator, not a real system.
>
> See `reports/day6/production_integration_extension.md`.

The demo screen handles the purely client-side half: when no response arrives at all,
it keeps the execution id issued at prepare time, shows the outcome as unknown, and
offers **Check status** — never a retry. A lookup that finds the execution still
`AWAITING_CONFIRMATION` reports that nothing was applied.

## 20. Failure Handling

The simulator supports ten deterministic modes — `SUCCESS`, `UNAUTHORIZED`,
`FORBIDDEN`, `NOT_FOUND`, `CONFLICT`, `RATE_LIMITED`, `SERVER_ERROR`,
`TIMEOUT`, `NETWORK_ERROR`, `DUPLICATE_REQUEST`. **Failures are selected,
never random**: a demo that fails randomly cannot be reproduced by a
reviewer.

Two design points worth stating:

- **Failures strike at `confirm` by default.** A mode that also broke
  navigation would make the human review checkpoint unreachable, and the
  lost-response demo impossible to stage. Tests that want an earlier failure
  set `fail_stage` explicitly. *(This was a real bug, caught by the
  end-to-end smoke test: the first implementation failed at `open_route`, so
  `prepare` returned 422 and the demo could never reach confirm.)*
- **Credential failures are the exception** and strike immediately, because
  a rejected service account is rejected from the first request.

Integration errors keep their own codes rather than collapsing into the
generic taxonomy: an `INTEGRATION_TIMEOUT` and a `CONFIRMATION_REJECTED`
demand different operator action.

## 21. Authentication Boundary

**Development authentication only.** Nothing here verifies a signature,
checks an expiry, or contacts an issuer. **Production requires integration
with an enterprise identity provider — Entra ID, Okta, or whatever the
customer environment mandates — issuing verified tokens whose claims map to
these roles.**

| Role | inspect executions | prepare | confirm | inspect audit |
|---|:--:|:--:|:--:|:--:|
| `operator` | ✓ | ✓ | | |
| `reviewer` | ✓ | ✓ | ✓ | |
| `admin` | ✓ | ✓ | ✓ | ✓ |

**An operator can prepare but not confirm.** That is the human-review
checkpoint expressed as an authorisation rule rather than only a UI
convention: the person who stages an action is not automatically the person
who approves it. A refused confirmation leaves the execution
`AWAITING_CONFIRMATION` so a reviewer can still complete it — refusing must
not consume the checkpoint.

A request with no `Authorization` header resolves to a default local
principal so the demo runs without credential setup; `API_AUTH_REQUIRED=1`
fails closed, which is what a deployment would set. The default role is
`reviewer` — it can run the demo but cannot read the audit trail, so the
permission boundary is observable rather than decorative. No real
credentials exist in the repository; a test asserts every development token
is obviously a development token.

**CORS** is now a localhost allowlist (`http://localhost:5173`,
`http://127.0.0.1:5173`) instead of `*`, with the `Origin` echoed only when
allowlisted. **This is not a production CORS configuration**: a deployment
requires an explicit allowlist of the real deployed frontend origins.

## 22. Production Boundary

**LOCAL VALIDATED — not connected to any real HR system.** Nothing in this
upgrade changes that. Every target is local; every credential is a
development stub.

| Currently validated (locally) | Still required for production |
|---|---|
| Mock, browser and REST-simulator targets behind one interface | A real HR API contract, or a real browser target |
| Execution identity, state machine and status lookup | Enterprise identity (Entra ID / Okta / customer IdP) |
| Idempotency keys and replay refusal | Real secrets management |
| Deterministic integration failure modes | Production CORS allowlist for deployed origins |
| Development authentication and role-based authorisation | Deployment, monitoring and alerting |
| In-memory and SQLite execution persistence | Customer authorization model and governance sign-off |
| Structured audit and counters, redacted | Business-owner confirmation that confirm = submit |
| Localhost-only CORS allowlist | Reliability and load testing at real volume |

What has **not** been demonstrated: a real HR system, real customer
credentials, enterprise SSO, production deployment, production-scale load,
or a real customer authorization model. The architecture is shaped so those
are substitutions rather than rewrites — but a substitution that has never
been performed is not evidence, and is not claimed as any.

## 23. Integration upgrade — testing

| Suite | Before | After |
|---|---:|---:|
| Python (`pytest tests/ -q`) | 647 | **830** (+183) |
| Frontend (`npx vitest run`) | 108 | **137** (+29) |

Seven new Python test files cover the adapters and interface, the execution
state machine, persistence (including a real restart), authentication and
authorisation, security redaction, orchestrator idempotency, and the new API
endpoints. One frontend file covers the integration UI.

**No existing test was weakened.** One existing frontend test needed a stub
correction: it counted *every* non-`prepare` call as a confirmation, and the
screen now also asks the API which targets it offers. The stub was made to
count `/confirm` explicitly; its `confirms === 1` assertion is unchanged and
now measures exactly what it claims to.

Browser QA against the **production build** at 1440 / 1024 / 390 px: six
screens, zero horizontal overflow, zero uncaught errors, zero failed
requests, zero unexpected console errors — and the full lost-response
journey exercised in a real browser, resolving `UNKNOWN → CONFIRMED` without
re-submitting the confirmation.

---

# Day-6 addition — Automation Decision Center

A sixth screen, hash-routed at `#decision`, added to answer *"are we ready
to automate this, why do we believe it, and how robust is that decision?"*
rather than only *"what should we automate?"*. It is a presentation layer:
no analytical value is computed in React.

## Process awareness

The screen defaults to the **canonical rank-1 process read from
`opportunities.json`**, not to a hardcoded HR id. A selector switches
process. For any process that is not the one the Day-3 HR forensics
identified, the screen shows that process's own profile and ranking but:
no RPA recommendation ("Not proposed"), no bounded-pilot status, no
forensic variant split, no DFG, no automation boundary, and no scenario
table. Leaking HR evidence onto another process is the main failure mode
this screen could have, and it is tested against.

## A · Automation Readiness

Six explicit boolean gates, each rendering the artifact path it reads:

| Gate | Source |
|---|---|
| Ranked first by canonical Opportunity | `opportunities.json → ranking` |
| Pareto non-dominated | `opportunities.json → ranking[].pareto_status` |
| A single path covers most executions | `processes.json → dominant_variant_share` |
| Automation surface bounded to evidenced routes | `hr-payroll.json → route_id_prefix_correspondence` |
| Form input observed as one deterministic method | `hr-payroll.json → …form_input_method_distribution` |
| A working prototype exists | `procmine.automation` |

States are **PASS / WARN / UNAVAILABLE**; UNAVAILABLE means the supporting
artifact does not exist for that process. HR/Payroll passes all six →
**READY FOR BOUNDED PILOT**, with the screen stating that pilot readiness
means a bounded trial under human review. No production-readiness claim and
no monetary figure appears anywhere.

Deliberately **not** a weighted score. The one numeric judgement — "covers
most executions" at 50% — is labelled in the UI as a display rule for this
screen, not an analytical threshold.

## B · Evidence → Claim Traceability

Claim → Evidence → Source artifact → Source field → Execution → Decision.
Eight evidence items, each expandable into observed evidence, why it
matters, source artifact and source field, with navigation into Process
Explorer, the prototype, or a **real execution deep-linked into Replay**.

Two weak-evidence caveats are surfaced here rather than left in the Day-3
reports:

- **139 note-field clicks vs 138 confirm-button clicks** — named as
  unexplained and localised to `#/leave-applications` (27 vs 26), computed
  from the artifact's own click counts. Wording is always "near-1:1"; the
  UI never asserts exactly 1:1.
- **No `submit` event exists in the schema** — treating `btn-<route>-ok` as
  confirmation is stated as a **DOM-structure inference**, tied directly to
  why a human checkpoint precedes every confirm.

Unavailable evidence (the note text itself) renders as *"Evidence available
in analytical report, not currently exposed in frontend bundle"* rather
than being dropped or invented.

## C · Decision Sensitivity

All eight canonical scenarios by their real names with real HR ranks:
`balanced`, `feasibility_feasibility_heavy`, `feasibility_risk_averse`,
`frequency_heavy`, `time_heavy` → **#1**; `manual_effort_heavy`,
`volume_deemphasized`, `correlation_aware` → **#3**.

**The worst HR rank is 3, not 6.** An earlier exploratory run mentioned in
the Day-3 log produced a rank-6 figure; the canonical audit artifact does
not, and `final_ranking_robustness_table[0].worst_rank` independently
records 3. The UI renders the artifact, and a test asserts "rank 6" never
appears.

Interpretation is worded **"strong but assumption-sensitive"** — explicitly
not statistical confidence, since no confidence interval exists anywhere in
this project.

Beside it, the Day-4 instrumentation sensitivity: all Dataset B → rank 1 at
**0.4401**; excluding the two degraded sessions (645 → 571 executions) →
rank 1 at **0.4180**. The screen repeats that instrumentation health affects
evidence availability and does not by itself prove segmentation failure.

## D · Automation boundary

Automate (navigate, select an evidenced route, locate the note field,
insert the operator's note, confirm only after the human checkpoint) versus
keep-human (review and authoring of note content, the 24 Word-detour and 4
rare multi-hop executions, any judgment-dependent decision), with a
"why not automate everything?" answer grounded in the variant split.

## Tests and cost

86 frontend tests (54 pre-Day-6 + 32 added), 508 Python tests, typecheck
clean, build 217 KB JS / 65 KB gzipped. **No dependency was added** — still
React + React DOM, CSS and inline SVG only.

---

## Update — final presentation pass

The frontend was reorganised around the investigation rather than around screens, without
changing any analytical value.

- **Navigation** is grouped by stage (Overview, Investigation, Decision, Evidence,
  Automation). Day 1–4 are now first-class pages (`Day1DataAudit.tsx`,
  `Day2Reconstruction.tsx`, `Day3ProcessMining.tsx`, `Day4EvidenceHealth.tsx`) reading the
  new `investigation.json` (see the data contract).
- **Shell.** Sidebar branding and dataset status, a page top bar with stage, dataset and
  evidence chips, a skip link, focus moved to the page title on navigation, a mobile menu,
  and short transitions that are switched off under `prefers-reduced-motion`.
- **Shared components.** `evidence.tsx` (the CANONICAL / OBSERVED / INFERRED /
  EXPERIMENTAL / NOT PROMOTED / PROTOTYPE / LIMITATION badges, the expandable "View
  evidence" trace, and experiment status tags), `charts.tsx` (a dependency-free scatter
  chart, bar list and coverage strip that only plot bundle values), and
  `InvestigationProgress.tsx`.
- **Existing screens.** The dashboard puts the decision and the limitations side by side;
  the Decision Center opens with a decision record; Opportunities adds executions, time
  share and rank range plus a Pareto view; Approach Comparison adds a validation summary and
  an experiment and rejection log; Replay shows execution metadata and evidence labels;
  the HR demo is organised as five steps with REVIEW REQUIRED and SAFE STOP states.
- **Tests and QA.** 262 frontend tests (206 + 56), typecheck clean, build 352.67 kB JS
  (99.57 kB gzip). Browser QA at 1440, 1024 and 390 px on every page found no overflow and
  no console or network errors; the demo, safe stops and replay were driven against the
  local API.
