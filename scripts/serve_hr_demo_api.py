#!/usr/bin/env python3
"""Day 5: a local API exposing the HR/Payroll automation prototype to the dashboard.

WHAT THIS FILE OWNS
-------------------
The request boundary, and nothing else:

    request -> authenticate -> authorise -> orchestrator -> adapter -> target
                                                |
                                                +-> execution state -> repository
                                                +-> audit / observability

It adds no automation logic. Route validation, note validation, element
verification and confirm-time re-verification all happen inside
`procmine.automation.hr_payroll_automation`, unchanged. Execution lifecycle,
state transitions and the lost-response path live in
`procmine.integrations.orchestrator`, not here.

WHY CHECKPOINT STATE STAYS SERVER-SIDE
--------------------------------------
`confirm_submission` re-locates the confirm button at confirm time rather than
clicking a cached reference, precisely because the page may change during the
human review pause. That guarantee only holds if the same adapter and
`ReviewCheckpoint` survive between the two calls, so each prepared checkpoint is
kept in-process and addressed by an opaque single-use token.

Standard library only -- no new dependency was added for this.

Endpoints:
    GET  /api/routes                             -> the four evidenced routes
    GET  /api/integration-modes                  -> selectable LOCAL targets
    POST /api/prepare                            -> {route, note_text,
                                                     integration_mode?,
                                                     failure_mode?, lose_response?}
    POST /api/confirm                            -> {checkpoint_token}
    GET  /api/executions/{execution_id}/status   -> execution status
    GET  /api/metrics                            -> counters
    GET  /api/audit                              -> recent audit events (admin)
    GET  /health                                 -> liveness + version

Status codes:
    200 success
    202 the confirmation outcome is UNKNOWN -- query the status endpoint
    400 malformed request / unknown or consumed token
    401 authentication failed
    403 insufficient permission
    404 unknown endpoint or unknown execution
    422 a SAFE STOP -- the prototype or the integration refused
    503 the selected integration target is unavailable

**LOCAL VALIDATED -- not connected to any real HR system.** Every selectable
target is local: an in-memory mock, a Playwright browser driving the committed
local prototype page, an in-process simulator of an external REST service, or --
in `http` mode -- real HTTP to the separate local HR API server
(`scripts/serve_local_hr_api.py`, SQLite state) at `HR_API_BASE_URL`.

In `http` mode the execution id is issued here, before any call, and is the
idempotency key the HR API honours. An UNKNOWN outcome is settled by asking the HR
API for that id -- which also works after this process restarts, provided
`EXECUTION_DB_PATH` keeps the execution record.

Usage:
    python scripts/serve_hr_demo_api.py            # 127.0.0.1:8000
    python scripts/serve_hr_demo_api.py --port 8123
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import signal
import sys
import threading
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from procmine.automation.hr_payroll_automation import (  # noqa: E402
    AutomationSafetyError,
)
from procmine.automation.mock_hr_app import MockHRApplication  # noqa: E402
from procmine.process_discovery.dom_evidence import KNOWN_ROUTE_PREFIXES  # noqa: E402
from procmine.automation.audit import (  # noqa: E402
    AuditEvent, AuditLog, new_request_id,
)
from procmine.integrations import execution_state as st  # noqa: E402
from procmine.integrations.api_hr_application import ApiHRApplication  # noqa: E402
from procmine.integrations.auth import (  # noqa: E402
    Actor, AuthenticationError, AuthorizationError,
    CONFIRM_AUTOMATION, INSPECT_AUDIT, INSPECT_EXECUTIONS, PREPARE_AUTOMATION,
    ROLE_REVIEWER, authenticate, authorize,
)
from procmine.integrations.hr_api_simulator import (  # noqa: E402
    FAILURE_MODES, SUCCESS, HRApiSimulator,
)
from procmine.integrations.hr_application import (  # noqa: E402
    INTEGRATION_MODES, MODE_API, MODE_BROWSER, MODE_HTTP, MODE_MOCK,
)
from procmine.integrations.http_hr_application import HTTPHRApplication  # noqa: E402
from procmine.integrations.local_hr_api import (  # noqa: E402
    CONNECTION_REFUSED, HTTP_FAILURE_MODES, configured_token, register_fault,
    unreachable_base_url,
)
from procmine.integrations.orchestrator import (  # noqa: E402
    Orchestrator, ReplayRejected, integration_error_code,
)
from procmine.integrations.repositories import (  # noqa: E402
    InMemoryExecutionRepository, SQLiteExecutionRepository,
)

MAX_BODY_BYTES = 64 * 1024
API_VERSION = "1.1.0"

# token -> (PreparedExecution, execution_id). Process-local and deliberately not
# persisted: a checkpoint must not outlive the process that verified it. The
# durable record of the execution lives in the repository; the live adapter does
# not, and cannot.
_CHECKPOINTS: dict[str, tuple] = {}

# Tokens already consumed, so a replay is reported as REPLAYED_REQUEST rather than
# as an indistinguishable "unknown token".
_CONSUMED: set[str] = set()
_LOCK = threading.Lock()

# Audit trail. Set AUTOMATION_AUDIT_LOG to also persist to JSONL.
AUDIT = AuditLog()


def _make_repository():
    """SQLite when a path is configured, in-memory otherwise.

    The default stays in-memory so the demo needs no filesystem and existing
    behaviour is unchanged; setting EXECUTION_DB_PATH proves the abstraction is
    real by surviving a restart.
    """
    path = os.environ.get("EXECUTION_DB_PATH")
    return SQLiteExecutionRepository(path) if path else InMemoryExecutionRepository()


# --- local HTTP integration target ----------------------------------------------
# The separate local HR API server. Loopback only; `scripts/serve_local_hr_api.py`.
HR_API_BASE_URL = os.environ.get("HR_API_BASE_URL", "http://127.0.0.1:8100")
HR_API_TIMEOUT_S = float(os.environ.get("HR_API_TIMEOUT_S", "3"))


def _http_status_resolver(record) -> dict:
    """Durable status source for `http` executions: needs only the persisted id.

    A fresh client per lookup, so it works for an execution this process never held --
    for example one prepared before a restart.
    """
    client = HTTPHRApplication(HR_API_BASE_URL, execution_id=record.execution_id,
                               token=configured_token(), timeout_s=HR_API_TIMEOUT_S,
                               audit=AUDIT)
    return client.query_remote_status()


ORCH = Orchestrator(repo=_make_repository(), audit=AUDIT,
                    resolvers={MODE_HTTP: _http_status_resolver})

# --- authentication boundary ---------------------------------------------
# DEVELOPMENT ONLY. A request carrying an Authorization header is authenticated
# against the development principals in `procmine.integrations.auth`; an invalid
# one is rejected. A request carrying *no* header resolves to a default local
# principal so the demo runs without credential setup -- set API_AUTH_REQUIRED=1
# to fail closed instead, which is what a deployment would do.
#
# The default role is `reviewer` deliberately: it can prepare and confirm, so the
# demo works out of the box, but it cannot read the audit trail -- so the
# permission boundary is observable rather than decorative.
AUTH_REQUIRED = os.environ.get("API_AUTH_REQUIRED", "0") in {"1", "true", "True"}
DEFAULT_DEV_ROLE = os.environ.get("API_DEFAULT_ROLE", ROLE_REVIEWER)
DEFAULT_ACTOR = Actor(user_id="u_local_dev", role=DEFAULT_DEV_ROLE)

# --- CORS -----------------------------------------------------------------
# Local development origins only. The previous `*` was convenient and wrong even
# for a local tool. **This is not a production CORS configuration**: a deployment
# requires an explicit allowlist of the real deployed frontend origins.
_DEFAULT_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")
ALLOWED_ORIGINS = {
    o.strip() for o in
    (os.environ.get("API_ALLOWED_ORIGINS") or ",".join(_DEFAULT_ORIGINS)).split(",")
    if o.strip()
}

_STATUS_PATH = re.compile(r"^/api/executions/([A-Za-z0-9_\-]{1,64})/status$")


class IntegrationUnavailable(RuntimeError):
    """The selected target could not be started (e.g. no browser available)."""


def _log_to_list(action_log) -> list[dict]:
    return [asdict(entry) for entry in action_log]


_TARGET_FIELDS = ("found", "confirmation_state", "state", "in_progress", "commit_count",
                  "audit_ref", "last_error_type", "lookup_error")


def _target_view(target: dict | None) -> dict | None:
    """The target's own record of an execution, reduced to reportable fields."""
    if target is None:
        return None
    return {"source": "local HR API (HTTP)", **{k: target[k] for k in _TARGET_FIELDS
                                                if k in target}}


def _build_adapter(mode: str, failure_mode: str, lose_response: bool):
    """Construct the target for one execution.

    This is the only place that knows which concrete adapter exists. Everything
    downstream -- orchestrator, automation service -- sees only `HRApplication`,
    which is the property the architecture is claiming.
    """
    if mode == MODE_MOCK:
        return MockHRApplication()
    if mode == MODE_API:
        simulator = HRApiSimulator(mode=failure_mode,
                                   applied_despite_failure=lose_response)
        return ApiHRApplication(simulator)
    if mode == MODE_HTTP:
        # The execution id is issued before any call: it is the idempotency key.
        execution_id = st.new_execution_id()
        if failure_mode == CONNECTION_REFUSED:
            # Nothing listens there: the first call is refused before a byte is sent.
            base_url = unreachable_base_url()
        else:
            base_url = HR_API_BASE_URL
            if failure_mode != SUCCESS:
                # Arm the selected fault for this execution only, on the HR server's
                # local control plane. The adapter itself knows nothing about faults.
                try:
                    register_fault(base_url, execution_id, failure_mode, stage="confirm",
                                   delay_s=HR_API_TIMEOUT_S + 1.0,
                                   token=configured_token())
                except (OSError, RuntimeError) as exc:
                    raise IntegrationUnavailable(
                        f"local HR API not reachable at {base_url}: "
                        f"{type(exc).__name__}") from exc
        return HTTPHRApplication(base_url, execution_id=execution_id,
                                 token=configured_token(), timeout_s=HR_API_TIMEOUT_S,
                                 audit=AUDIT)
    if mode == MODE_BROWSER:
        # Imported here so the package works without the playwright extra.
        from procmine.automation.browser_adapter import BrowserHRApplication
        app = BrowserHRApplication()
        try:
            app.start()
        except Exception as exc:  # noqa: BLE001 - reported as an integration failure
            raise IntegrationUnavailable(
                f"browser target unavailable: {exc}") from exc
        return app
    raise ValueError(f"unknown integration mode {mode!r}")


def _close_if_browser(app) -> None:
    """Release a browser target. Safe to call on any adapter."""
    closer = getattr(app, "close", None)
    if callable(closer):
        try:
            closer()
        except Exception:  # noqa: BLE001 - teardown must never mask a real error
            pass


class HRDemoHandler(BaseHTTPRequestHandler):
    server_version = "IBYHRDemo/0.2"

    # --- plumbing --------------------------------------------------------

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # Echo only an allowlisted origin. A request with no Origin (curl, the
        # test client) is unaffected; a browser from an unlisted origin gets no
        # CORS header and is blocked by the browser, which is the point.
        origin = self.headers.get("Origin")
        if origin and origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None
        if length <= 0 or length > MAX_BODY_BYTES:
            return None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None

    def log_message(self, fmt: str, *args) -> None:  # quieter console
        sys.stderr.write(f"  api {fmt % args}\n")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send(204, {})

    # --- authentication / authorisation ----------------------------------

    def _resolve_actor(self) -> Actor:
        """Never logs or echoes the header value -- only the resolved user id."""
        header = self.headers.get("Authorization")
        if header:
            return authenticate(header)
        if AUTH_REQUIRED:
            raise AuthenticationError("missing Authorization header")
        return DEFAULT_ACTOR

    def _guard(self, permission: str) -> Actor | None:
        """Authenticate then authorise. Sends the error response itself."""
        try:
            actor = self._resolve_actor()
        except AuthenticationError as exc:
            self._send(401, {"error_type": "AUTHENTICATION_FAILED",
                             "message": str(exc)})
            return None
        try:
            authorize(actor, permission)
        except AuthorizationError as exc:
            self._send(403, {"error_type": "AUTHORIZATION_FAILED",
                             "message": str(exc),
                             "required_permission": exc.permission})
            return None
        return actor

    # --- routes ----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.rstrip("/") or "/"
        status_match = _STATUS_PATH.match(self.path.rstrip("/"))
        if path == "/api/routes":
            self._send(200, {"routes": list(KNOWN_ROUTE_PREFIXES)})
        elif path == "/api/integration-modes":
            self._send(200, {
                "modes": [{"id": k, "label": v} for k, v in INTEGRATION_MODES.items()],
                "default": MODE_MOCK,
                "failure_modes": list(FAILURE_MODES),
                # The local HTTP target has its own, transport-level failure set.
                "http_failure_modes": list(HTTP_FAILURE_MODES),
                "note": ("Every target is local. No real HR system is contacted by "
                         "any of these modes."),
            })
        elif status_match:
            self._execution_status(status_match.group(1))
        elif path == "/api/metrics":
            self._metrics()
        elif path == "/health":
            # Deliberately minimal: liveness plus a version, nothing that would
            # leak configuration or internal state.
            self._send(200, {"status": "ok", "version": API_VERSION})
        elif path == "/api/audit":
            if self._guard(INSPECT_AUDIT) is None:
                return
            self._send(200, {"events": AUDIT.recent(20)})
        else:
            self._send(404, {"message": f"no such endpoint: {self.path}"})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.rstrip("/")
        if path == "/api/prepare":
            self._prepare()
        elif path == "/api/confirm":
            self._confirm()
        else:
            self._send(404, {"message": f"no such endpoint: {self.path}"})

    # --- prepare ---------------------------------------------------------

    def _prepare(self) -> None:
        actor = self._guard(PREPARE_AUTOMATION)
        if actor is None:
            return
        request_id = new_request_id()
        body = self._read_json()
        if body is None:
            AUDIT.record(AuditEvent(request_id=request_id, execution_id=None,
                                    action="prepare", result="rejected",
                                    error_type="MALFORMED_REQUEST"))
            self._send(400, {"request_id": request_id, "error_type": "MALFORMED_REQUEST",
                             "message": "request body must be JSON"})
            return
        route = body.get("route")
        note_text = body.get("note_text")
        if not isinstance(route, str) or not isinstance(note_text, str):
            AUDIT.record(AuditEvent(request_id=request_id, execution_id=None,
                                    action="prepare", result="rejected",
                                    error_type="MALFORMED_REQUEST"))
            self._send(400, {"request_id": request_id, "error_type": "MALFORMED_REQUEST",
                             "message": "both 'route' and 'note_text' are required strings"})
            return

        mode = body.get("integration_mode") or MODE_MOCK
        failure_mode = body.get("failure_mode") or SUCCESS
        lose_response = bool(body.get("lose_response", False))
        if mode not in INTEGRATION_MODES:
            self._send(400, {"request_id": request_id, "error_type": "MALFORMED_REQUEST",
                             "message": f"unknown integration_mode {mode!r}; "
                                        f"expected one of {sorted(INTEGRATION_MODES)}"})
            return
        allowed_failures = HTTP_FAILURE_MODES if mode == MODE_HTTP else FAILURE_MODES
        if failure_mode not in allowed_failures:
            self._send(400, {"request_id": request_id, "error_type": "MALFORMED_REQUEST",
                             "message": f"unknown failure_mode {failure_mode!r} for "
                                        f"integration_mode {mode!r}"})
            return

        try:
            app = _build_adapter(mode, failure_mode, lose_response)
        except IntegrationUnavailable as exc:
            AUDIT.record(AuditEvent(request_id=request_id, execution_id=None,
                                    action="prepare", result="error", route=route,
                                    error_type="INTEGRATION_UNAVAILABLE"))
            self._send(503, {"request_id": request_id,
                             "error_type": "INTEGRATION_UNAVAILABLE",
                             "message": str(exc)})
            return

        try:
            prepared = ORCH.prepare(actor, app, route, note_text,
                                    integration_mode=mode, request_id=request_id)
        except AutomationSafetyError as exc:
            _close_if_browser(app)
            etype = integration_error_code(app, exc)
            self._send(422, {
                "request_id": request_id,
                "execution_id": getattr(exc, "execution_id", None),
                "integration_mode": mode,
                "status": st.FAILED,
                "error_type": etype,
                "exception": type(exc).__name__,
                "message": str(exc),
                "action_log": _log_to_list(exc.action_log),
            })
            return

        checkpoint = prepared.checkpoint
        token = secrets.token_urlsafe(16)
        with _LOCK:
            _CHECKPOINTS[token] = (prepared, prepared.execution_id)

        self._send(200, {
            "request_id": request_id,
            "execution_id": prepared.execution_id,
            "status": prepared.record.status,
            "integration_mode": mode,
            "integration_mode_label": INTEGRATION_MODES[mode],
            "checkpoint_token": token,
            "route": checkpoint.route,
            "note_field_id": checkpoint.note_field_id,
            "note_text": checkpoint.note_text,
            "confirm_button_id": checkpoint.confirm_button_id,
            "confirmed": checkpoint.confirmed,
            "action_log": _log_to_list(checkpoint.action_log),
        })

    # --- confirm ---------------------------------------------------------

    def _confirm(self) -> None:
        actor = self._guard(CONFIRM_AUTOMATION)
        if actor is None:
            return
        request_id = new_request_id()
        body = self._read_json()
        if body is None:
            AUDIT.record(AuditEvent(request_id=request_id, execution_id=None,
                                    action="confirm", result="rejected",
                                    error_type="MALFORMED_REQUEST"))
            self._send(400, {"request_id": request_id, "error_type": "MALFORMED_REQUEST",
                             "message": "request body must be JSON"})
            return
        token = body.get("checkpoint_token")
        if not isinstance(token, str) or not token:
            AUDIT.record(AuditEvent(request_id=request_id, execution_id=None,
                                    action="confirm", result="rejected",
                                    error_type="MALFORMED_REQUEST"))
            self._send(400, {"request_id": request_id, "error_type": "MALFORMED_REQUEST",
                             "message": "'checkpoint_token' is required"})
            return

        with _LOCK:
            entry = _CHECKPOINTS.get(token)
            already_used = token in _CONSUMED
        if entry is None:
            # Idempotency: a token this process already consumed is reported as a
            # replay, distinct from a token it never issued. Confirmation is
            # impossible without a checkpoint this process prepared and verified.
            etype = "REPLAYED_REQUEST" if already_used else "CHECKPOINT_REQUIRED"
            AUDIT.record(AuditEvent(request_id=request_id, execution_id=None,
                                    action="confirm", result="rejected",
                                    error_type=etype))
            self._send(400, {
                "request_id": request_id, "error_type": etype,
                "message": ("this checkpoint has already been confirmed"
                            if already_used else
                            "unknown or expired checkpoint token -- run prepare first"),
            })
            return

        prepared, execution_id = entry
        try:
            record = ORCH.confirm(actor, execution_id, request_id=request_id)
        except ReplayRejected as exc:
            self._send(400, {"request_id": request_id, "execution_id": execution_id,
                             "error_type": "REPLAYED_REQUEST", "message": str(exc)})
            return
        except AuthorizationError as exc:
            self._send(403, {"error_type": "AUTHORIZATION_FAILED", "message": str(exc),
                             "required_permission": exc.permission})
            return
        finally:
            # The token is consumed whatever the outcome, so it can never be
            # replayed. The *execution* remains addressable by id -- that is how a
            # lost response is resolved without re-submitting the mutation.
            with _LOCK:
                _CHECKPOINTS.pop(token, None)
                _CONSUMED.add(token)

        payload = {
            "request_id": request_id,
            "execution_id": execution_id,
            "status": record.status,
            "integration_mode": record.integration_mode,
            "route": record.route,
            "confirmed": record.status == st.CONFIRMED,
            "action_log": _log_to_list(prepared.checkpoint.action_log),
        }

        if record.status == st.CONFIRMED:
            _close_if_browser(prepared.app)
            self._send(200, payload)
        elif record.status == st.UNKNOWN:
            # The mutation is NOT retried. The client is told to ask the status
            # endpoint what actually happened.
            self._send(202, {
                **payload,
                "error_type": record.error_code,
                "status_url": f"/api/executions/{execution_id}/status",
                "message": ("the confirmation outcome is unknown -- query the "
                            "execution status endpoint; the confirmation is "
                            "never retried automatically"),
            })
        else:
            _close_if_browser(prepared.app)
            self._send(422, {
                **payload,
                "error_type": record.error_code,
                "message": "the integration refused or failed; nothing was retried",
            })

    # --- execution status ------------------------------------------------

    def _execution_status(self, execution_id: str) -> None:
        """Authoritative state for one execution.

        For an UNKNOWN execution this asks the target what actually happened. It
        queries; it never re-submits the confirmation.
        """
        actor = self._guard(INSPECT_EXECUTIONS)
        if actor is None:
            return
        record = ORCH.status(actor, execution_id)
        if record is None:
            self._send(404, {"error_type": "TARGET_NOT_FOUND",
                             "message": f"no such execution: {execution_id}"})
            return
        resolved_from_unknown = False
        if record.status == st.UNKNOWN:
            before = record.status
            record = ORCH.resolve_unknown(actor, execution_id) or record
            resolved_from_unknown = record.status != before
        # What the target itself recorded -- for `http` executions only, read-only.
        target = ORCH.target_status(actor, execution_id)
        self._send(200, {
            **record.to_dict(),
            "resolved_from_unknown": resolved_from_unknown,
            "terminal": record.status in st.TERMINAL,
            "target": _target_view(target),
        })

    # --- metrics ---------------------------------------------------------

    def _metrics(self) -> None:
        actor = self._guard(INSPECT_EXECUTIONS)
        if actor is None:
            return
        self._send(200, {
            "metrics": ORCH.metrics.metrics(),
            "recent_events": ORCH.metrics.recent(20),
        })


def build_server(host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), HRDemoHandler)


def _stop(signum, frame) -> None:
    raise KeyboardInterrupt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    httpd = build_server(args.host, args.port)
    host, port = httpd.server_address[:2]
    # First stdout line is machine-readable (useful with --port 0); the rest is stderr.
    print(f"LISTENING http://{host}:{port}", flush=True)
    signal.signal(signal.SIGTERM, _stop)
    print(f"HR automation demo API on http://{host}:{port}", file=sys.stderr)
    print("  GET  /api/routes", file=sys.stderr)
    print("  GET  /api/integration-modes", file=sys.stderr)
    print("  POST /api/prepare   {route, note_text, integration_mode?, failure_mode?}",
          file=sys.stderr)
    print("  POST /api/confirm   {checkpoint_token}", file=sys.stderr)
    print("  GET  /api/executions/{execution_id}/status", file=sys.stderr)
    print("  GET  /api/metrics", file=sys.stderr)
    print(f"  CORS origins: {sorted(ALLOWED_ORIGINS)}", file=sys.stderr)
    print(f"  auth required: {AUTH_REQUIRED} (default role: {DEFAULT_DEV_ROLE})",
          file=sys.stderr)
    print(f"  local HTTP integration target (mode 'http'): {HR_API_BASE_URL}",
          file=sys.stderr)
    print("Automation logic is owned by procmine.automation -- this is transport only.",
          file=sys.stderr)
    print("LOCAL VALIDATED -- not connected to any real HR system.", file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped", file=sys.stderr)
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
