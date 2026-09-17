# Production-integration extension: a local HTTP integration boundary

> **LOCAL HTTP INTEGRATION — not a real external HR deployment.**
>
> - **What is new.** Every call in this extension travels over real HTTP, through
>   real sockets, to a separate local process that plays the part of an HR system
>   and keeps its state in SQLite.
> - **What it is not.** That process is a simulator written for this project. No
>   real HR system, no real HR API contract, no real credentials and no real
>   employee data are involved anywhere. Nothing here is production-validated.

The existing prototype is unchanged in behaviour and still in place:

- `MockHRApplication`, `BrowserHRApplication` (Playwright) and the in-process REST
  simulator remain selectable.
- The human review checkpoint, the route allowlist, note validation, confirm-time
  re-verification and replay protection are unchanged.
- No canonical analytical artifact, Module 1, Module 2 result, Opportunity score or
  Day-7 conclusion was touched.

---

## Motivation

Until now, the "integration" targets were either in-process or a browser against a
static page. The in-process REST simulator modelled failures as flags on a Python
object, so the properties that matter most at a real boundary were asserted rather
than exercised:

- a connection that is refused;
- a response that never comes back;
- a server that commits and then fails;
- state that outlives the process.

The README also recorded a real gap. A persisted `UNKNOWN` execution survived a restart
but **could not be resolved after one**, because the status lookup needed the adapter
object that had died with the process.

This extension closes both gaps locally:

- **A real HTTP boundary.** A separate HR API process, reached through a real HTTP
  adapter, with its own SQLite state.
- **Durable status resolution.** A resolver keyed only by `execution_id`, so an
  `UNKNOWN` outcome can be settled after a restart.

It also exposed and fixed a pre-existing safety gap in the automation core (see
*Failure injection*).

## Architecture

```
React frontend  (HR Automation Demo)
      │  /api/prepare · /api/confirm · /api/executions/{id}/status
      ▼
Automation API            scripts/serve_hr_demo_api.py   (stdlib http.server)
      │  development auth: operator / reviewer / admin
      ▼
Policy / safety layer     procmine.automation.hr_payroll_automation
      │  route allowlist · note validation · element checks · human checkpoint ·
      │  confirm-time re-verification
      ▼
Orchestrator              procmine.integrations.orchestrator
      │  execution state machine · replay refusal · audit · status resolution
      ▼
HRApplication interface   procmine.integrations.hr_application
      ├── MockHRApplication          (unchanged)
      ├── BrowserHRApplication       (unchanged; Playwright)
      ├── ApiHRApplication           (unchanged; in-process simulator)
      └── HTTPHRApplication          NEW  procmine.integrations.http_hr_application
              │  http.client, no retries, no policy
              ▼  real HTTP over a socket
          Local HR API server        NEW  procmine.integrations.local_hr_api
              │                           scripts/serve_local_hr_api.py (own process)
              ▼
          SQLite                     hr_records · hr_executions · hr_audit
```

**No new dependency.**

- **FastAPI was not used, because it is not a dependency of this project.** The
  instruction was to use it only if it already existed, and otherwise the smallest
  appropriate option.
- **Both servers use the standard library.** The existing automation API is
  standard-library `http.server`, and the new HR API is standard-library
  `http.server` plus `sqlite3`.
- **The adapter uses `http.client`.**

**The core still depends only on the interface.**

- `hr_payroll_automation.py` imports no transport library, and a test reads the file
  to enforce that.
- The HTTP adapter imports nothing from the core and contains no policy. A second
  test checks that it holds none of the policy markers.

**The integration mode is selected per execution.** The API offers `mock`,
`browser`, `api_simulator` and the new `http` ("LOCAL HTTP INTEGRATION — real HTTP
to the local HR API server (SQLite)").

## HTTP integration

**Local HR API** (`GET /api/hr/health` is open; everything else needs the service
credential):

| Endpoint | Purpose |
|---|---|
| `GET /api/hr/routes` | the four evidenced routes and their record ids |
| `GET /api/hr/records/{record_id}` | the form record: its note field(s) and confirm control(s) |
| `POST /api/hr/records/{record_id}/notes` | receive a note for an execution; its **length** is recorded |
| `POST /api/hr/records/{record_id}/confirm` | apply the confirmation, idempotent by `execution_id` |
| `GET /api/hr/executions/{execution_id}/status` | the HR system's own record of an execution |
| `POST /api/hr/_simulator/faults` | local, per-execution failure injection (simulator control only) |

The HR API holds one form record per evidenced route (`payroll-items`,
`leave-applications`, `onboarding`, `social-insurance`), each carrying the element ids
the Dataset-B DOM evidence recorded. It holds no employee records, because the evidence
identifies none, and none were invented.

**Adapter mapping** (`HTTPHRApplication`):

| Interface call | HTTP |
|---|---|
| `navigate(route)` | `GET /routes`, then `GET /records/{id}`; verifies the record belongs to the route |
| `find_note_field()` | `GET /records/{id}` (live every time) |
| `set_note_value()` | `POST /records/{id}/notes`; verifies the acknowledged execution and length |
| `find_confirm_button()` | `GET /records/{id}` (live every time, so confirm-time re-verification is real) |
| `click()` | `POST /records/{id}/confirm` (sent once, never retried) |
| `query_remote_status()` *(outside the interface)* | `GET /executions/{id}/status` |

Every call carries `X-Request-Id` (the automation API's request id) and
`X-Execution-Id`, so one execution can be followed across both processes.

**Error mapping into the existing taxonomy** (no new codes were added):

| Transport / HTTP event | Taxonomy code |
|---|---|
| connection refused / unreachable | `INTEGRATION_UNAVAILABLE` |
| connect or read timeout, HTTP 504 | `INTEGRATION_TIMEOUT` |
| connection dropped after sending | `INTEGRATION_UNAVAILABLE` |
| HTTP 5xx, malformed or unreadable body | `INTEGRATION_SERVER_ERROR` |
| 400 / 401 / 403 / 404 / 409 / 429 | `MALFORMED_REQUEST`, `INTEGRATION_UNAUTHORIZED`, `INTEGRATION_FORBIDDEN`, `TARGET_NOT_FOUND`, `INTEGRATION_CONFLICT`, `RATE_LIMITED` |
| server says `INVALID_NOTE` / `TARGET_CHANGED` | `INVALID_NOTE` / `TARGET_CHANGED` |

**Whether a confirmation could have been applied is decided in the adapter.** This is
the one judgement the adapter makes, and it is transport fact, not business policy:

- **Known not applied:** the connection was refused (nothing was sent), or the server
  answered 4xx.
- **Unknown:** a timeout, a dropped connection, a 5xx, or an unreadable 2xx after the
  request was sent. A 5xx vouches for nothing, and the tests show why: one injected
  500 hides a real commit, and another does not.

## Persistence

**Two SQLite databases, with different owners.**

| Database | Owner | Holds |
|---|---|---|
| HR system state (`LOCAL_HR_DB_PATH`) | local HR API | `hr_executions`: `execution_id`, `request_id`, `record_id`, `route`, `state`, `confirmation_state`, `note_length`, `confirm_request_id`, `commit_count`, `last_error_type`, `created_at`, `updated_at`, `confirmed_at`, `audit_ref` · `hr_audit` (below) · `hr_records` |
| Execution state (`EXECUTION_DB_PATH`, existing) | automation API | the existing execution record and history |

**What the HR store keeps, and what it drops.**

- **Note content.** It is accepted over HTTP, measured, and discarded. The simulator
  is not a system of record for note text; storing it would add risk and prove
  nothing. A real HR system would store the note, because that is its business
  record, so that storage belongs to the system of record and not to this
  integration layer.
- **Credentials.** No credential, bearer value or `Authorization` header is stored.
  Tests read the raw database bytes to check this.
- **Durability.** A `:memory:` database is refused, because this state must outlive
  the process.
- **Restart rule.** A confirmation found `IN_PROGRESS` at start-up is set back to
  `PENDING` with reason `INTERRUPTED`. This is safe because a commit is a single
  transaction, so an interrupted confirmation provably did not commit.

## Idempotency

`execution_id` is the identity of one business action:

1. **Issued before any call.** The automation API issues it before the first HTTP
   call; the orchestrator adopts it, and it becomes the record's `idempotency_key`.
   Supplying two different ids for one execution is refused.
2. **The HR API decides atomically.** It moves `PENDING → IN_PROGRESS` inside a
   `BEGIN IMMEDIATE` transaction. Only one caller can win, and the commit and its
   audit row are written in one transaction.
3. **A repeat returns the stored outcome.** A repeated confirmation of a confirmed
   execution gets `idempotent_replay: true`, and nothing is written: `commit_count`
   stays 1 and `confirmed_at` is unchanged.
4. **A confirmation of an execution still `IN_PROGRESS` is refused.** It gets
   `409 CONFIRMATION_IN_PROGRESS` with no commit claim. The adapter treats this as
   *unknown*, because the other attempt may still commit.
5. **Replays never reach the HR API.** The automation API refuses a replayed
   checkpoint (`REPLAYED_REQUEST`) before any HR call. Tests count the HR API's
   confirm requests to prove it.

Tested:

- **Duplicates:** request → confirmation succeeds → duplicate request → no second
  write.
- **Races:** eight concurrent duplicates → exactly one commit.
- **Lost response:** request → confirmation succeeds → response lost → the same
  execution is queried → status shows committed.

## Lost-response experiment

Run by `scripts/run_http_integration_demo.py`. It uses separate processes: the demo
client, the automation API process and the HR API process. Its deterministic summary,
holding only states, codes and counts, is `reports/day6/http_integration_demo.json`,
and a test re-runs the demo and requires byte-identical output.

**B — the response is dropped after the commit.**

| Step | Observed |
|---|---|
| 1. HR API commits the confirmation | `hr_executions`: `CONFIRMED`, `commit_count` 1 |
| 2. HTTP response intentionally dropped | the HR API closes the socket without answering |
| 3. Client receives no response | adapter: `RemoteDisconnected` after sending → `INTEGRATION_UNAVAILABLE`, unknown |
| 4. Client preserves `execution_id` | `POST /api/confirm` → **202**, same `execution_id`, `status_url` given |
| 5. Client marks the state UNKNOWN | `status: UNKNOWN`, `error_type: CONFIRMATION_UNKNOWN` |
| 6. Client calls the status endpoint | `GET /api/executions/{id}/status` |
| 7. Status resolves the committed execution | **`CONFIRMED`**, `resolved_from_unknown: true` |
| — a second confirm with the same checkpoint | **400 `REPLAYED_REQUEST`** at the automation API |
| — confirm requests the HR API ever received | **1**; `retry_sent: false`; `commit_count` 1 |

**A — the confirmed path.** The flow ran select route → enter note → prepare →
human review checkpoint → confirm, with these results:

- **The HR API** received exactly one confirmation.
- **SQLite** shows `COMMITTED` / `CONFIRMED`, with `commit_count` 1 and
  `note_length` 72.
- **The status lookup** returns `CONFIRMED` with the HR system's own
  `confirmation_state: CONFIRMED`.

The demo's human approval is scripted; in the UI it is the reviewer's click.

**Server restart: the honest result.**

- **C — both processes restarted, with durable state.** A new automation API process
  that never held the adapter, and a new HR API process on the same SQLite file,
  resolve the `UNKNOWN` execution to **`CONFIRMED`**. The resolver needs only the
  persisted `execution_id`.
- **D — the automation API restarted with in-memory state.** The status endpoint
  returns **404**: the automation API has forgotten the execution. The HR system,
  asked directly with the `execution_id` the client kept, still reports
  `CONFIRMED`. **An `UNKNOWN` execution is recoverable through the automation API
  only when its state is durable (`EXECUTION_DB_PATH`).**

**Timeouts are handled conservatively.** The simulated `TIMEOUT` holds the
confirmation past the client's deadline, then aborts it.

- **While it is held,** the HR API reports `IN_PROGRESS`, and resolution deliberately
  leaves the execution `UNKNOWN`. Settling it then could record `FAILED` for a
  confirmation about to commit.
- **Once the HR API aborts,** the lookup settles `FAILED` with
  `INTEGRATION_TIMEOUT`.
- **If the status source itself is unreachable,** the execution stays `UNKNOWN`. The
  failure is audited (`status_lookup / lookup_failed`), and the next lookup settles
  it once the HR API is back.

**What this does not establish:**

- **Not a distributed reconciliation model.** There is one HR node, one status
  source, and no deadline propagation.
- **Resolution trusts the HR API's durable record.** A target that lost its own
  state would mislead it.
- **Execution records do not store the target URL.** A resolver uses the currently
  configured `HR_API_BASE_URL`.
- **Real systems are a different matter.** Whether a real HR system exposes a status
  or reconciliation interface at all is unknown.

## Failure injection

**Faults are selected, never random.** Each one strikes once, for one execution. The
automation API arms it on the HR API's local control endpoint before the first call;
the adapter knows nothing about faults.

| Selected behaviour | Where | At the HR API | Automation result | After status lookup |
|---|---|---|---|---|
| `SUCCESS` | — | commits | 200 `CONFIRMED` | `CONFIRMED` |
| `CONNECTION_REFUSED` | first call | nothing listens | 422 `FAILED` `INTEGRATION_UNAVAILABLE` at prepare | `FAILED` |
| `TIMEOUT` | confirm | held past the client timeout, then aborted | 202 `UNKNOWN` | `UNKNOWN` while held (in progress), then `FAILED` `INTEGRATION_TIMEOUT` |
| `HTTP_500` | confirm | 500 before committing | 202 `UNKNOWN` | `FAILED` `INTEGRATION_SERVER_ERROR` |
| `HTTP_500_AFTER_COMMIT` | confirm | commits, then 500 | 202 `UNKNOWN` | `CONFIRMED` |
| `MALFORMED_JSON` | confirm | commits, then an unparseable 200 | 202 `UNKNOWN` | `CONFIRMED` |
| `CONFIRM_RESPONSE_LOST` | confirm | commits, then drops the connection | 202 `UNKNOWN` | `CONFIRMED` |
| duplicate confirmation | direct HTTP | returns the stored outcome | — | no second write |
| unknown execution ID | status / confirm | 404 `EXECUTION_NOT_FOUND` | `TARGET_NOT_FOUND` | not guessed |

**Failures before the human checkpoint are safe stops.** These are tested:

- a record read that times out, returns 500 or returns garbage;
- a wrong service credential (401);
- a note write that fails;
- **a target that changes during review.** The confirm-time re-verification reads the
  record again, sees a different control, and refuses before any confirmation is
  sent.

**A pre-existing gap was found and fixed.**

- **The gap.** `prepare_note_submission` guarded only `navigate`. An adapter that
  failed while its note field or confirm button was being read, or its note written,
  escaped as a raw exception: no safe stop, no execution record, no audit event, and
  through the API a dropped request. It was reproduced first, with the in-process
  simulator failing at `set_note`.
- **The fix.** The three calls now raise `ElementNotFoundError`, or the new
  `NoteInsertionError` (mapped to `TARGET_CHANGED`), with the partial action log,
  exactly like every other refusal. The happy path and its action log are unchanged;
  a test pins them.

**The system fails closed.** No confirmation is ever retried, and a test counts the HR
API's confirm requests in every uncertain case.

## Audit/security

**Automation-side audit** (the existing `AuditLog`):

- **What is recorded.** The orchestrator's events, plus one event per HTTP call
  (`hr_api.<operation>`).
- **Fields.** `request_id`, `execution_id`, `route`, `action`, `timestamp`, `result`,
  `error_type` and `confirmation_status`, plus `detail`: `http_status`,
  `duration_ms`, `note_length` (note writes only) and `target_audit_ref`.
- **Naming.** The existing schema is kept: *operation* is `action`, and
  *confirmation state* is `confirmation_status`.
- **Resolutions are audited too:** `status_lookup` with `resolved_confirmed`,
  `resolved_not_applied`, `still_in_progress` or `lookup_failed`.

**HR-side audit** (`hr_audit`, SQLite):

- **Fields.** Exactly `request_id`, `execution_id`, `route`, `operation`,
  `timestamp`, `result`, `error_type` and `confirmation_state`, plus `actor`,
  `http_status` and `note_length`.
- **Coverage.** Every request is audited, including rejected credentials (without
  the credential).
- **Cross-reference.** The commit's audit row is written with the commit, and its
  `audit_ref` is returned to the adapter, so the two trails line up.

**Never recorded:**

- **Note content.** Only its length is kept. The orchestrator now records
  `note_length` at the source, so even the in-memory audit buffer no longer holds
  the text.
- **Secrets.** No credentials, bearer values or `Authorization` headers.

Tests read:

- the HR SQLite file, the automation SQLite file and the audit JSONL;
- the server console output;
- the status and audit API payloads;
- error messages.

**Authentication boundary: development only.**

- **Operators.** The automation API keeps its existing development principals
  (`operator` / `reviewer` / `admin`; an operator cannot confirm).
- **The HR API.** It requires a development service bearer (`LOCAL_HR_API_TOKEN`,
  with a local default that protects nothing), compared in constant time.
- **Loopback only.** The server script refuses a non-loopback address.
- **Not enterprise authentication.** A production integration needs:
  - a real identity provider;
  - service-to-service authentication (for example mutual TLS or OAuth client
    credentials);
  - authorization scoped per operation;
  - secret management and token rotation;
  - an auditable caller identity. The HR audit records one fixed local service
    principal.

## Frontend behavior

**The mode selector** offers `LOCAL MOCK`, `LOCAL BROWSER`, `LOCAL API SIMULATOR` and
**`LOCAL HTTP INTEGRATION`**. The last is labelled as a local HTTP integration with a
local simulator; it is never called "production", and no production badge exists.

**In HTTP mode:**

- **Failure list.** The HTTP failure list replaces the simulator's, and switching
  targets resets the selected failure.
- **Staged demo.** *Stage HTTP lost-response demo* selects
  `CONFIRM_RESPONSE_LOST`.
- **Execution panel.** It shows the execution ID, the state, the **confirmation
  state** (the HR system's own record once a status lookup has run, for example
  `CONFIRMED (HR system)`) and the integration mode, plus a status-lookup line
  (`COMMITTED · commits applied 1`).
- **The UNKNOWN path.** `UNKNOWN` → **Check status** → `CONFIRMED`. The execution ID
  stays visible and there is no retry control.
  - *Still in progress:* the page says so and stays `UNKNOWN`.
  - *Status source unreachable:* the page says so and stays `UNKNOWN`.
- **Safety panel.** It previously showed confirm-time re-verification as *refused*
  after a lost response, which was a guess. It now shows *unknown*, then
  *enforced* or *not applied* once settled.

**Checked in a real browser.** A Playwright smoke test ran against the production
build (`vite preview`) with both servers running as processes, at 1440 px and 390 px.

- **Flows.** Both demos completed.
- **Page health.** No page overflow, console errors or failed requests, and no
  production badge.
- **Commits.** The HR SQLite file showed exactly one commit and one confirm request
  per execution.
- **Leaks.** No note text or credential appeared in any log or database.

## What is genuinely integrated

**Validated locally** — tested, and exercised end to end across processes:

- **Local HTTP integration.** A real HTTP adapter talks to a separate local HR API
  process over sockets.
- **Local SQLite persistence** on both sides, surviving restarts.
- **The end-to-end API path:** React → automation API → policy → orchestrator →
  HTTP adapter → HR API → SQLite, and back through the status endpoint.
- **Idempotency by `execution_id`,** including concurrent duplicates.
- **The lost-response simulation,** including resolution after a restart when state
  is durable.
- **Structured, redacted audit** on both sides, cross-referenced.
- **Deterministic failure injection** for refused connections, timeouts, 5xx,
  malformed bodies, dropped responses, duplicates and unknown ids.
- **Existing work survives.** The mock, browser and in-process adapters, the human
  checkpoint, the route allowlist, note validation, confirm-time re-verification and
  replay protection all remain, with no automatic confirmation retry anywhere. The
  existing tests still pass; one assertion was updated (below).

## What remains production work

**Not production-validated:**

- **A real HR target.** No real HR system, HR API contract or employee data was used.
  Whether the real system has an API at all was never evidenced.
- **Enterprise authentication and authorisation,** and a real service identity.
- **Production secrets,** with rotation.
- **Production deployment:** TLS, network policy, packaging and configuration
  management.
- **A distributed or managed database,** with backups.
- **Real reconciliation** against the HR system of record, with deadlines and
  in-flight semantics agreed with its owner.
- **Production observability:** metrics export, alerting, tracing and dashboards.
- **High availability and scaling.** Both servers are single-process and loopback
  only.
- **Business confirmation** that the confirm control really means "submit".

**This is not production readiness.** The recommendation's status remains *ready for
a bounded, supervised pilot*.

---

### Changes to existing files, stated plainly

- **`hr_payroll_automation.py`.** Three adapter calls are now wrapped as safe stops,
  and there is a new `NoteInsertionError`. It is mapped to `TARGET_CHANGED` in
  `audit.py`.
- **`orchestrator.py`** — additive changes:
  - adopts or validates the adapter's `execution_id`;
  - passes the request id to the adapter;
  - accepts per-mode durable `resolvers`;
  - keeps `UNKNOWN` on a lookup failure or an in-progress report;
  - audits resolutions;
  - adds a read-only `target_status`;
  - records `note_length` rather than note text.
- **`hr_application.py` / `observability.py`.** A new mode constant and two trace
  events.
- **`scripts/serve_hr_demo_api.py`:**
  - the `http` mode, with its failure list and per-mode validation;
  - the durable resolver;
  - a `target` block in the status response;
  - a machine-readable `LISTENING` line and SIGTERM handling.
- **`tests/test_hr_demo_api_integration.py`.** The advertised-modes assertion now
  expects four modes, `http` included. It is still an exact-set check.
- **`scripts/build_frontend_data.py`.** The Decision Center's production-boundary
  lists gained one "implemented" and two "requires production" entries.

### Verification

- **Python tests:** 1,119 passed (965 before; 154 new).
- **Frontend tests:** 206 passed (186 before; 20 new).
- **Build:** TypeScript clean; production build successful.
- **Traceability:** report-number traceability passed.
- **Demo:** the multi-process demo is byte-identical across runs.
- **Browser:** the smoke test passed at 1440 and 390 px.
- **Canonical values unchanged:**
  - Opportunity 0.4401;
  - Module 1 F1 0.3440233236151604;
  - M2C F1 0.3519, NOT PROMOTED.

```bash
python scripts/serve_local_hr_api.py                       # local HR API on 127.0.0.1:8100
HR_API_BASE_URL=http://127.0.0.1:8100 EXECUTION_DB_PATH=execution_state.db \
    python scripts/serve_hr_demo_api.py                    # automation API on :8000
cd frontend && npm run dev                                 # choose LOCAL HTTP INTEGRATION
python scripts/run_http_integration_demo.py                # the multi-process demo
pytest tests/test_local_hr_api.py tests/test_http_hr_adapter.py \
       tests/test_http_integration_api.py tests/test_automation_adapter_failures.py
```
