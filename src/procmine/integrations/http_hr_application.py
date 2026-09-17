"""HTTP adapter: `HRApplication` over a real network connection.

WHAT IT DOES
------------
Translates the five interface calls into HTTP calls against the local HR API server
(`procmine.integrations.local_hr_api`), and translates every transport or protocol
failure into the project's stable error taxonomy. Standard-library `http.client`; no
new dependency.

    navigate(route)         GET  /api/hr/routes, then GET /api/hr/records/{record_id}
    find_note_field()       GET  /api/hr/records/{record_id}      read live, never cached
    set_note_value(id, v)   POST /api/hr/records/{record_id}/notes
    find_confirm_button()   GET  /api/hr/records/{record_id}      read live -- this is what
                                                                  makes confirm-time
                                                                  re-verification real
    click(id)               POST /api/hr/records/{record_id}/confirm
    query_remote_status()   GET  /api/hr/executions/{execution_id}/status   (not in the
                                                                             interface)

WHAT IT DOES NOT DO
-------------------
It holds no policy: no route allowlist, no note validation, no decision about whether a
confirmation may proceed. Those live in `procmine.automation.hr_payroll_automation`, and
a test reads this file to make sure they have not been copied here.

It never retries anything. A confirmation is an irreversible mutation and must never be
re-sent; reads could be retried safely, but one visible failure is easier to reason
about than a hidden retry loop.

THE ONE JUDGEMENT IT MUST MAKE: COULD THE CONFIRMATION HAVE BEEN APPLIED?
------------------------------------------------------------------------
That is a transport fact, not policy, and only this layer can know it:

* the connection was refused       -> nothing was sent      -> KNOWN: not applied
* the server answered 4xx          -> it refused            -> KNOWN: not applied
* a timeout, a dropped connection,
  a 5xx, or an unreadable 2xx
  after the request was sent       -> it may have applied   -> UNKNOWN

An UNKNOWN outcome is settled by asking (`query_remote_status`), keyed by
`execution_id`, which the server treats as the identity of the business action.

**Local only.** The only server this adapter has ever talked to is the local simulator.
A production adapter would also need TLS, a real service identity and a real contract.
"""
from __future__ import annotations

import http.client
import json
import os
import re
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from procmine.automation.audit import AuditEvent, AuditLog, new_request_id

DEFAULT_TIMEOUT_S = float(os.environ.get("HR_API_TIMEOUT_S", "3"))
# Development default for the local simulator; mirrors `local_hr_api.DEV_SERVICE_TOKEN`
# (a test keeps the two equal). It protects nothing and is named as such.
LOCAL_DEV_TOKEN = "local-hr-service-token"

_ID = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
_RECORD_ID = re.compile(r"^[a-z0-9\-]{1,64}$")
_CONFIRMATION_STATES = ("PENDING", "IN_PROGRESS", "CONFIRMED")

# HTTP status -> taxonomy, for responses whose body names nothing more specific.
_BY_STATUS = {
    400: "MALFORMED_REQUEST",
    401: "INTEGRATION_UNAUTHORIZED",
    403: "INTEGRATION_FORBIDDEN",
    404: "TARGET_NOT_FOUND",
    409: "INTEGRATION_CONFLICT",
    429: "RATE_LIMITED",
    504: "INTEGRATION_TIMEOUT",
}
# Server error codes that name a more specific taxonomy member.
_BY_SERVER_CODE = {
    "INVALID_NOTE": "INVALID_NOTE",
    "TARGET_CHANGED": "TARGET_CHANGED",
    "RECORD_NOT_FOUND": "TARGET_NOT_FOUND",
    "EXECUTION_NOT_FOUND": "TARGET_NOT_FOUND",
}


# Why the target says a confirmation was not applied -> taxonomy. No recorded attempt
# at all means the request never got as far as being processed.
_NOT_APPLIED_BECAUSE = {
    None: "INTEGRATION_UNAVAILABLE",
    "TIMEOUT": "INTEGRATION_TIMEOUT",
    "HTTP_500": "INTEGRATION_SERVER_ERROR",
    "INTERRUPTED": "INTEGRATION_UNAVAILABLE",
}


def taxonomy_code(status: int, server_code: str | None) -> str:
    if server_code in _BY_SERVER_CODE:
        return _BY_SERVER_CODE[server_code]
    if status in _BY_STATUS:
        return _BY_STATUS[status]
    return "INTEGRATION_SERVER_ERROR"


class HTTPIntegrationError(RuntimeError):
    """A transport or protocol failure, already classified.

    `code` is a member of the project's error taxonomy. `request_sent` says whether any
    part of the request may have reached the server. `submitted_unknown` is set only for
    a confirmation that may have been applied.
    """

    def __init__(self, code: str, status: int | None, message: str, *, operation: str,
                 request_sent: bool, server_code: str | None = None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.operation = operation
        self.request_sent = request_sent
        self.server_code = server_code
        self.submitted_unknown = False


@dataclass
class HttpElement:
    """Mirrors the mock/browser/API element shape so callers cannot tell them apart."""

    element_id: str
    element_type: str
    css_class: str
    value: str | None = None
    clicked: bool = False


def _may_have_applied(exc: HTTPIntegrationError) -> bool:
    if not exc.request_sent:
        return False               # refused or unreachable before a byte was sent
    if exc.status is None:
        return True                # timed out or dropped after the request went out
    if exc.status >= 500 or 200 <= exc.status < 300:
        return True                # a 5xx vouches for nothing; an unreadable 2xx neither
    # Another confirmation of the same execution is still running and may commit.
    return exc.server_code == "CONFIRMATION_IN_PROGRESS"


class HTTPHRApplication:
    """Drives the local HR API over HTTP through the `HRApplication` interface.

    `execution_id` is required and is the idempotency key: the server applies at most
    one confirmation per execution, and the status lookup is addressed by it.
    """

    def __init__(self, base_url: str, *, execution_id: str, token: str | None = None,
                 timeout_s: float | None = None, audit: AuditLog | None = None,
                 request_id: str | None = None):
        parts = urlsplit(base_url)
        if parts.scheme != "http" or not parts.hostname or parts.port is None:
            raise ValueError("base_url must look like http://host:port (local HTTP only)")
        if not isinstance(execution_id, str) or not _ID.match(execution_id):
            raise ValueError("execution_id must be a well-formed identifier")
        self._host = parts.hostname
        self._port = parts.port
        self.base_url = f"http://{self._host}:{self._port}"
        self.execution_id = execution_id
        self._token = token or os.environ.get("LOCAL_HR_API_TOKEN") or LOCAL_DEV_TOKEN
        self.timeout_s = DEFAULT_TIMEOUT_S if timeout_s is None else float(timeout_s)
        self.audit = audit
        self.request_id = request_id or new_request_id()
        self._current_route: str | None = None
        self._record_id: str | None = None
        self._confirm_unknown = False
        self.last_error: HTTPIntegrationError | None = None
        self.calls: list[str] = []     # operation names in order -- what was actually sent

    def __repr__(self) -> str:        # never the credential
        return f"HTTPHRApplication({self.base_url!r}, execution_id={self.execution_id!r})"

    # -- identity ----------------------------------------------------------
    @property
    def idempotency_key(self) -> str:
        return self.execution_id

    def bind_request_id(self, request_id: str) -> None:
        """Carry the caller's request id on every call, for end-to-end correlation."""
        if isinstance(request_id, str) and _ID.match(request_id):
            self.request_id = request_id

    # -- HRApplication -----------------------------------------------------
    @property
    def current_route(self) -> str | None:
        return self._current_route

    def navigate(self, route: str) -> None:
        listing = self._call("GET", "/api/hr/routes", operation="list_routes", route=route)
        routes = listing.get("routes")
        if not isinstance(routes, list):
            raise self._fail("INTEGRATION_SERVER_ERROR", 200, "the route list is not a list",
                             operation="list_routes", request_sent=True, route=route)
        matches = [r for r in routes if isinstance(r, dict) and r.get("route") == route]
        if len(matches) != 1:
            raise self._fail("TARGET_NOT_FOUND", 200,
                             f"the HR API lists {len(matches)} records for {route!r}",
                             operation="list_routes", request_sent=True, route=route)
        record_id = matches[0].get("record_id")
        if not isinstance(record_id, str) or not _RECORD_ID.match(record_id):
            raise self._fail("INTEGRATION_SERVER_ERROR", 200, "malformed record id",
                             operation="list_routes", request_sent=True, route=route)
        record = self._get_record(record_id, route)
        if record.get("route") != route:
            raise self._fail("PAGE_MISMATCH", 200,
                             f"record {record_id!r} belongs to {record.get('route')!r}, "
                             f"not {route!r}", operation="get_record", request_sent=True,
                             route=route)
        self._record_id = record_id
        self._current_route = route

    def find_note_field(self) -> list[HttpElement]:
        if self._record_id is None:
            return []
        record = self._get_record(self._record_id, self._current_route)
        return [HttpElement(fid, "textarea", "input") for fid in record["note_fields"]]

    def find_confirm_button(self) -> list[HttpElement]:
        if self._record_id is None:
            return []
        record = self._get_record(self._record_id, self._current_route)
        return [HttpElement(bid, "button", "btn success") for bid in record["confirm_buttons"]]

    def set_note_value(self, element_id: str, value: str) -> None:
        self._require_navigated()
        length = len(value)
        ack = self._call("POST", f"/api/hr/records/{self._record_id}/notes",
                         operation="set_note", note_length=length,
                         body={"execution_id": self.execution_id, "field_id": element_id,
                               "note_text": value})
        if ack.get("execution_id") != self.execution_id or ack.get("note_length") != length:
            raise self._fail("INTEGRATION_SERVER_ERROR", 200,
                             "the HR API acknowledged a different execution or note length",
                             operation="set_note", request_sent=True)

    def click(self, element_id: str) -> None:
        """The confirmation. Sent once; never retried, whatever happens."""
        self._require_navigated()
        self._confirm_unknown = False
        try:
            ack = self._call("POST", f"/api/hr/records/{self._record_id}/confirm",
                             operation="confirm",
                             body={"execution_id": self.execution_id,
                                   "confirm_button_id": element_id})
        except HTTPIntegrationError as exc:
            self._confirm_unknown = exc.submitted_unknown
            raise
        if (ack.get("execution_id") != self.execution_id
                or ack.get("confirmation_state") != "CONFIRMED"
                or ack.get("committed") is not True):
            # A success status that does not say "confirmed" is neither success nor failure.
            self._confirm_unknown = True
            raise self._fail("INTEGRATION_SERVER_ERROR", 200,
                             "the HR API answered without confirming the execution",
                             operation="confirm", request_sent=True, force_unknown=True)

    # -- outside the interface ---------------------------------------------
    @property
    def outcome_is_unknown(self) -> bool:
        """True when the last confirmation may have been applied without our knowing."""
        return self._confirm_unknown

    def query_remote_status(self) -> dict:
        """What the HR system recorded for this execution. Read-only; never re-submits.

        Raises `HTTPIntegrationError` if the status source itself cannot be read -- the
        caller must then keep the outcome UNKNOWN rather than guess.
        """
        try:
            data = self._call("GET", f"/api/hr/executions/{self.execution_id}/status",
                              operation="get_status")
        except HTTPIntegrationError as exc:
            if exc.status == 404 and exc.server_code == "EXECUTION_NOT_FOUND":
                return {"found": False, "confirmed": False, "in_progress": False,
                        "confirmation_state": None, "error_code": "TARGET_NOT_FOUND"}
            raise
        state = data.get("confirmation_state")
        if data.get("execution_id") != self.execution_id or state not in _CONFIRMATION_STATES:
            raise self._fail("INTEGRATION_SERVER_ERROR", 200, "unreadable execution status",
                             operation="get_status", request_sent=True)
        reason = data.get("last_error_type")
        not_applied = _NOT_APPLIED_BECAUSE.get(reason, "CONFIRMATION_REJECTED")
        return {
            "found": True,
            "confirmed": state == "CONFIRMED",
            "in_progress": state == "IN_PROGRESS",
            "confirmation_state": state,
            "state": data.get("state"),
            "route": data.get("route"),
            "commit_count": data.get("commit_count"),
            "audit_ref": data.get("audit_ref"),
            "last_error_type": reason,
            # The target says it was not applied, and why. Not a guess: its durable record.
            "error_code": None if state in ("CONFIRMED", "IN_PROGRESS") else not_applied,
        }

    # -- transport ---------------------------------------------------------
    def _require_navigated(self) -> None:
        if self._record_id is None:
            raise RuntimeError("not navigated to any route yet")

    def _get_record(self, record_id: str, route: str | None) -> dict:
        record = self._call("GET", f"/api/hr/records/{record_id}", operation="get_record",
                            route=route)
        for key in ("note_fields", "confirm_buttons"):
            value = record.get(key)
            if not (isinstance(value, list) and all(isinstance(v, str) for v in value)):
                raise self._fail("INTEGRATION_SERVER_ERROR", 200,
                                 f"record {record_id!r} has a malformed {key!r}",
                                 operation="get_record", request_sent=True, route=route)
        return record

    def _call(self, method: str, path: str, *, operation: str, body: dict | None = None,
              note_length: int | None = None, route: str | None = None) -> dict:
        self.calls.append(operation)
        route = route or self._current_route
        headers = {"Accept": "application/json",
                   "Authorization": f"Bearer {self._token}",
                   "X-Request-Id": self.request_id,
                   "X-Execution-Id": self.execution_id}
        payload = None
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        started = time.perf_counter()
        conn = http.client.HTTPConnection(self._host, self._port, timeout=self.timeout_s)
        try:
            try:
                conn.connect()
            except OSError as exc:
                # Refused, unreachable, or no answer to the handshake: nothing was sent.
                code = ("INTEGRATION_TIMEOUT" if isinstance(exc, TimeoutError)
                        else "INTEGRATION_UNAVAILABLE")
                raise self._fail(code, None, f"could not connect to the HR API "
                                 f"({type(exc).__name__})", operation=operation,
                                 request_sent=False, route=route, started=started) from exc
            try:
                conn.request(method, path, body=payload, headers=headers)
                response = conn.getresponse()
                raw = response.read()
            except TimeoutError as exc:
                raise self._fail("INTEGRATION_TIMEOUT", None,
                                 "the HR API did not answer in time", operation=operation,
                                 request_sent=True, route=route, started=started) from exc
            except (http.client.HTTPException, OSError) as exc:
                raise self._fail("INTEGRATION_UNAVAILABLE", None,
                                 f"the connection failed after the request was sent "
                                 f"({type(exc).__name__})", operation=operation,
                                 request_sent=True, route=route, started=started) from exc
        finally:
            conn.close()

        status = response.status
        try:
            data = json.loads(raw.decode("utf-8")) if raw else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            data = None
        if not isinstance(data, dict):
            raise self._fail("INTEGRATION_SERVER_ERROR", status,
                             f"the HR API sent an unreadable response (HTTP {status})",
                             operation=operation, request_sent=True, route=route,
                             started=started)
        if not 200 <= status < 300:
            server_code = data.get("error_code") if isinstance(data.get("error_code"), str) else None
            raise self._fail(taxonomy_code(status, server_code), status,
                             f"the HR API refused the request (HTTP {status}"
                             f"{', ' + server_code if server_code else ''})",
                             operation=operation, request_sent=True, route=route,
                             started=started, server_code=server_code)
        # A status client never navigated, so take the route from the answer.
        answered_route = data.get("route") if isinstance(data.get("route"), str) else None
        self._audit(operation, "success", None, status, started,
                    route=route or answered_route, note_length=note_length,
                    confirmation=data.get("confirmation_state"),
                    target_audit_ref=data.get("audit_ref"))
        return data

    def _fail(self, code: str, status: int | None, message: str, *, operation: str,
              request_sent: bool, route: str | None = None, started: float | None = None,
              server_code: str | None = None, force_unknown: bool = False
              ) -> HTTPIntegrationError:
        exc = HTTPIntegrationError(code, status, message, operation=operation,
                                   request_sent=request_sent, server_code=server_code)
        confirmation = None
        if operation == "confirm":
            exc.submitted_unknown = force_unknown or _may_have_applied(exc)
            confirmation = "UNKNOWN" if exc.submitted_unknown else "NOT_APPLIED"
        self.last_error = exc
        self._audit(operation, "unknown" if exc.submitted_unknown else "error", code, status,
                    started, route=route or self._current_route, confirmation=confirmation)
        return exc

    def _audit(self, operation: str, result: str, error_type: str | None,
               http_status: int | None, started: float | None, *, route: str | None,
               note_length: int | None = None, confirmation: str | None = None,
               target_audit_ref: str | None = None) -> None:
        if self.audit is None:
            return
        detail: dict = {"target": "local_hr_api", "http_status": http_status}
        if started is not None:
            detail["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
        if note_length is not None:
            detail["note_length"] = note_length      # the length, never the text
        if isinstance(target_audit_ref, str):
            detail["target_audit_ref"] = target_audit_ref
        self.audit.record(AuditEvent(
            request_id=self.request_id, execution_id=self.execution_id,
            action=f"hr_api.{operation}", result=result, route=route,
            error_type=error_type, confirmation_status=confirmation, detail=detail))
