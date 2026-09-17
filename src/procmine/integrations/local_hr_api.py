"""A local HR-system simulator with a real HTTP boundary and SQLite state.

WHAT THIS IS
------------
A separate HTTP server -- its own socket, and its own process when started with
`scripts/serve_local_hr_api.py` -- that plays the part of an HR system for the
`HTTPHRApplication` adapter. It exists so the integration boundary is exercised over a
real network protocol. Refused connections, timeouts, non-2xx responses, malformed
bodies and a dropped response are genuine socket/HTTP events here, not flags on a
Python object.

WHAT THIS IS NOT
----------------
It is **not** a real HR system, not a copy of one, and not a production target. No HR
API contract was ever evidenced in the logs; the endpoints below are this project's own
local contract. There is no employee data: one form record per evidenced route, carrying
the element ids the Dataset-B DOM evidence recorded.

    GET  /api/hr/health
    GET  /api/hr/routes
    GET  /api/hr/records/{record_id}
    POST /api/hr/records/{record_id}/notes
    POST /api/hr/records/{record_id}/confirm
    GET  /api/hr/executions/{execution_id}/status
    POST /api/hr/_simulator/faults          <- local failure injection only

IDEMPOTENCY
-----------
`execution_id` is the identity of one business action. A second confirmation for the
same id returns the stored outcome and writes nothing. The check-and-set runs inside a
`BEGIN IMMEDIATE` transaction, so two concurrent confirmations cannot both commit, and a
commit and its audit row are written in the same transaction.

WHAT IS STORED
--------------
Execution identity and state, the note's *length*, timestamps and an audit trail. **Note
content is accepted over HTTP, measured, and discarded**: this simulator is not a system
of record for note text. Credentials, bearer values and authorization headers are never
stored and never logged.

AUTHENTICATION
--------------
A development bearer value for service-to-service calls (`LOCAL_HR_API_TOKEN`, with a
local default that protects nothing). It is **not** enterprise authentication.
"""
from __future__ import annotations

import contextlib
import hmac
import http.client
import json
import os
import re
import socket
import sqlite3
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from procmine.process_discovery.dom_evidence import KNOWN_ROUTE_PREFIXES

SERVICE_NAME = "local-hr-api"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8100
# A development constant, like the in-process simulator's: it opens a local simulator
# with nothing real behind it. Override with LOCAL_HR_API_TOKEN.
DEV_SERVICE_TOKEN = "local-hr-service-token"
SERVICE_PRINCIPAL = "svc_local_automation"
MAX_BODY_BYTES = 64 * 1024
MAX_NOTE_CHARS = 10_000

# Execution state on the HR side.
NOTE_RECEIVED = "NOTE_RECEIVED"
COMMITTED = "COMMITTED"
# Confirmation state on the HR side. IN_PROGRESS never survives a restart: a commit is
# a single transaction, so an interrupted confirmation provably did not commit.
PENDING = "PENDING"
IN_PROGRESS = "IN_PROGRESS"
CONFIRMED = "CONFIRMED"

# Deterministic failure injection -- selected per execution, never random.
SUCCESS = "SUCCESS"
TIMEOUT = "TIMEOUT"                              # held past the client timeout, then aborted
HTTP_500 = "HTTP_500"                            # 500 before anything is committed
HTTP_500_AFTER_COMMIT = "HTTP_500_AFTER_COMMIT"  # committed, then a 500
MALFORMED_JSON = "MALFORMED_JSON"                # an unparseable body (committed first at confirm)
CONFIRM_RESPONSE_LOST = "CONFIRM_RESPONSE_LOST"  # committed, then the connection is dropped
TARGET_CHANGED = "TARGET_CHANGED"                # a record read shows a different confirm control
CONNECTION_REFUSED = "CONNECTION_REFUSED"        # client side: nothing listens at the address

FAULTS_BY_STAGE: dict[str, set[str]] = {
    "record": {TIMEOUT, HTTP_500, MALFORMED_JSON, TARGET_CHANGED},
    "notes": {TIMEOUT, HTTP_500, MALFORMED_JSON},
    "confirm": {TIMEOUT, HTTP_500, HTTP_500_AFTER_COMMIT, MALFORMED_JSON, CONFIRM_RESPONSE_LOST},
    "status": {TIMEOUT, HTTP_500, MALFORMED_JSON},
}

# What the automation API offers for this target. Every server-side failure strikes at
# confirmation -- after a human approved -- which is where the dangerous cases live.
# CONNECTION_REFUSED is the absence of a server, so it fails at the first call.
HTTP_FAILURE_MODES = [SUCCESS, CONFIRM_RESPONSE_LOST, TIMEOUT, HTTP_500,
                      HTTP_500_AFTER_COMMIT, MALFORMED_JSON, CONNECTION_REFUSED]

_ID = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
_RECORD = re.compile(r"^/api/hr/records/([a-z0-9\-]{1,64})$")
_NOTES = re.compile(r"^/api/hr/records/([a-z0-9\-]{1,64})/notes$")
_CONFIRM = re.compile(r"^/api/hr/records/([a-z0-9\-]{1,64})/confirm$")
_STATUS = re.compile(r"^/api/hr/executions/([A-Za-z0-9_\-]{1,64})/status$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_id_for(route: str) -> str:
    """`#/payroll-items` -> `payroll-items`: one form record per evidenced route."""
    return route.lstrip("#/")


# --- persistence --------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS hr_records (
    record_id          TEXT PRIMARY KEY,
    route              TEXT NOT NULL UNIQUE,
    note_field_id      TEXT NOT NULL,
    confirm_button_id  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hr_executions (
    execution_id        TEXT PRIMARY KEY,
    request_id          TEXT,
    record_id           TEXT NOT NULL REFERENCES hr_records(record_id),
    route               TEXT NOT NULL,
    state               TEXT NOT NULL,
    confirmation_state  TEXT NOT NULL,
    note_length         INTEGER NOT NULL,
    confirm_request_id  TEXT,
    commit_count        INTEGER NOT NULL DEFAULT 0,
    last_error_type     TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    confirmed_at        TEXT,
    audit_ref           TEXT
);
CREATE TABLE IF NOT EXISTS hr_audit (
    seq                 INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_ref           TEXT NOT NULL UNIQUE,
    timestamp           TEXT NOT NULL,
    actor               TEXT,
    request_id          TEXT,
    execution_id        TEXT,
    route               TEXT,
    operation           TEXT NOT NULL,
    result              TEXT NOT NULL,
    error_type          TEXT,
    confirmation_state  TEXT,
    http_status         INTEGER,
    note_length         INTEGER
);
CREATE INDEX IF NOT EXISTS ix_hr_audit_execution ON hr_audit(execution_id);
"""

_AUDIT_COLUMNS = ("request_id", "execution_id", "route", "operation", "result",
                  "error_type", "confirmation_state", "http_status", "note_length")

# The execution fields a client may see. Everything the store holds is on this list;
# none of it is note content or a credential.
_PUBLIC = ("execution_id", "record_id", "route", "state", "confirmation_state",
           "note_length", "commit_count", "last_error_type", "created_at", "updated_at",
           "confirmed_at", "audit_ref")


def _public(row: dict) -> dict:
    return {k: row[k] for k in _PUBLIC}


class HRSystemStore:
    """SQLite state of the simulated HR system. No ORM: three tables, stdlib only."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path in ("", ":memory:"):
            raise ValueError("the HR store needs a file: its state must outlive the process")
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            conn.executemany(
                "INSERT OR IGNORE INTO hr_records VALUES (?, ?, ?, ?)",
                [(record_id_for(route), route, f"{prefix}-note", f"btn-{prefix}-ok")
                 for route, prefix in KNOWN_ROUTE_PREFIXES.items()])

    @contextlib.contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    @contextlib.contextmanager
    def _transaction(self):
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")

    @staticmethod
    def _audit_row(conn: sqlite3.Connection, fields: dict) -> str:
        audit_ref = f"hraud_{uuid.uuid4().hex[:16]}"
        values = {k: fields.get(k) for k in _AUDIT_COLUMNS}
        conn.execute(
            "INSERT INTO hr_audit (audit_ref, timestamp, actor, request_id, execution_id, "
            "route, operation, result, error_type, confirmation_state, http_status, "
            "note_length) VALUES (:audit_ref, :timestamp, :actor, :request_id, "
            ":execution_id, :route, :operation, :result, :error_type, "
            ":confirmation_state, :http_status, :note_length)",
            {**values, "audit_ref": audit_ref, "timestamp": _now(),
             "actor": fields.get("actor")})
        return audit_ref

    @staticmethod
    def _execution(conn: sqlite3.Connection, execution_id: str) -> dict | None:
        row = conn.execute("SELECT * FROM hr_executions WHERE execution_id = ?",
                           (execution_id,)).fetchone()
        return dict(row) if row else None

    # -- reads ---------------------------------------------------------------
    def routes(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT route, record_id FROM hr_records ORDER BY rowid").fetchall()
        return [dict(r) for r in rows]

    def record(self, record_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM hr_records WHERE record_id = ?",
                               (record_id,)).fetchone()
        if row is None:
            return None
        return {"record_id": row["record_id"], "route": row["route"],
                "note_fields": [row["note_field_id"]],
                "confirm_buttons": [row["confirm_button_id"]]}

    def execution(self, execution_id: str) -> dict | None:
        with self._connect() as conn:
            return self._execution(conn, execution_id)

    def audit_trail(self, execution_id: str | None = None) -> list[dict]:
        with self._connect() as conn:
            if execution_id is None:
                rows = conn.execute("SELECT * FROM hr_audit ORDER BY seq").fetchall()
            else:
                rows = conn.execute("SELECT * FROM hr_audit WHERE execution_id = ? ORDER BY seq",
                                    (execution_id,)).fetchall()
        return [dict(r) for r in rows]

    # -- writes --------------------------------------------------------------
    def audit(self, **fields) -> str:
        with self._transaction() as conn:
            return self._audit_row(conn, fields)

    def write_note(self, execution_id: str, request_id: str | None, record: dict,
                   note_length: int, audit: dict) -> tuple[str, dict | None]:
        """Create or update the execution. Only the note's length is kept."""
        with self._transaction() as conn:
            row = self._execution(conn, execution_id)
            now = _now()
            if row is not None and row["record_id"] != record["record_id"]:
                return "record_mismatch", row
            if row is not None and row["confirmation_state"] != PENDING:
                return "not_editable", row
            audit_ref = self._audit_row(conn, {**audit, "result": "success",
                                               "confirmation_state": PENDING,
                                               "note_length": note_length})
            if row is None:
                conn.execute(
                    "INSERT INTO hr_executions (execution_id, request_id, record_id, route, "
                    "state, confirmation_state, note_length, created_at, updated_at, audit_ref) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (execution_id, request_id, record["record_id"], record["route"],
                     NOTE_RECEIVED, PENDING, note_length, now, now, audit_ref))
                outcome = "created"
            else:
                conn.execute(
                    "UPDATE hr_executions SET note_length = ?, request_id = ?, updated_at = ?, "
                    "audit_ref = ? WHERE execution_id = ?",
                    (note_length, request_id, now, audit_ref, execution_id))
                outcome = "updated"
            return outcome, self._execution(conn, execution_id)

    def begin_confirm(self, execution_id: str, request_id: str | None,
                      record_id: str) -> tuple[str, dict | None]:
        """The idempotency gate. Atomic: only one caller can move PENDING -> IN_PROGRESS."""
        with self._transaction() as conn:
            row = self._execution(conn, execution_id)
            if row is None:
                return "not_found", None
            if row["record_id"] != record_id:
                return "record_mismatch", row
            if row["confirmation_state"] == CONFIRMED:
                return "already_confirmed", row
            if row["confirmation_state"] == IN_PROGRESS:
                return "in_progress", row
            conn.execute(
                "UPDATE hr_executions SET confirmation_state = ?, confirm_request_id = ?, "
                "updated_at = ? WHERE execution_id = ? AND confirmation_state = ?",
                (IN_PROGRESS, request_id, _now(), execution_id, PENDING))
            return "started", self._execution(conn, execution_id)

    def commit(self, execution_id: str, audit: dict) -> dict:
        """Apply the confirmation. The commit and its audit row are one transaction."""
        with self._transaction() as conn:
            now = _now()
            audit_ref = self._audit_row(conn, {**audit, "confirmation_state": CONFIRMED})
            cur = conn.execute(
                "UPDATE hr_executions SET state = ?, confirmation_state = ?, "
                "commit_count = commit_count + 1, confirmed_at = ?, updated_at = ?, "
                "last_error_type = NULL, audit_ref = ? "
                "WHERE execution_id = ? AND confirmation_state = ?",
                (COMMITTED, CONFIRMED, now, now, audit_ref, execution_id, IN_PROGRESS))
            if cur.rowcount != 1:
                raise RuntimeError("commit without a started confirmation")
            return self._execution(conn, execution_id)

    def abort(self, execution_id: str, error_type: str, audit: dict) -> dict:
        """A confirmation that did not commit goes back to PENDING, with its reason."""
        with self._transaction() as conn:
            audit_ref = self._audit_row(conn, {**audit, "error_type": error_type,
                                               "confirmation_state": PENDING})
            conn.execute(
                "UPDATE hr_executions SET confirmation_state = ?, last_error_type = ?, "
                "updated_at = ?, audit_ref = ? WHERE execution_id = ? AND confirmation_state = ?",
                (PENDING, error_type, _now(), audit_ref, execution_id, IN_PROGRESS))
            return self._execution(conn, execution_id)

    def recover_interrupted(self) -> int:
        """At start-up, any IN_PROGRESS confirmation was interrupted before it committed."""
        with self._transaction() as conn:
            rows = conn.execute("SELECT execution_id, route FROM hr_executions "
                                "WHERE confirmation_state = ?", (IN_PROGRESS,)).fetchall()
            for row in rows:
                audit_ref = self._audit_row(conn, {
                    "execution_id": row["execution_id"], "route": row["route"],
                    "operation": "recover", "result": "aborted_by_restart",
                    "error_type": "INTERRUPTED", "confirmation_state": PENDING,
                    "actor": SERVICE_NAME})
                conn.execute(
                    "UPDATE hr_executions SET confirmation_state = ?, last_error_type = ?, "
                    "updated_at = ?, audit_ref = ? WHERE execution_id = ?",
                    (PENDING, "INTERRUPTED", _now(), audit_ref, row["execution_id"]))
            return len(rows)


# --- failure injection --------------------------------------------------------

@dataclass(frozen=True)
class Fault:
    mode: str
    stage: str
    delay_s: float = 2.0


class FaultPlan:
    """One-shot faults keyed by (execution_id, stage). Selected, never random."""

    def __init__(self) -> None:
        self._faults: dict[tuple[str, str], Fault] = {}
        self._lock = threading.Lock()

    def add(self, execution_id: str, fault: Fault) -> None:
        with self._lock:
            self._faults[(execution_id, fault.stage)] = fault

    def take(self, execution_id: str | None, stage: str) -> Fault | None:
        if not execution_id:
            return None
        with self._lock:
            return self._faults.pop((execution_id, stage), None)


# --- the HTTP server ----------------------------------------------------------

class LocalHRServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, store: HRSystemStore, *, token: str, quiet: bool = True):
        self.store = store
        self.token = token
        self.quiet = quiet
        self.faults = FaultPlan()
        super().__init__(address, LocalHRAPIHandler)

    def handle_error(self, request, client_address) -> None:
        # The default prints a full traceback. Keep it to one line: no request body,
        # no headers, no local variables can reach the console.
        exc = sys.exc_info()[1]
        sys.stderr.write(f"  {SERVICE_NAME}: unhandled {type(exc).__name__}\n")

    @property
    def base_url(self) -> str:
        host, port = self.server_address[:2]
        return f"http://{host}:{port}"


class LocalHRAPIHandler(BaseHTTPRequestHandler):
    server: LocalHRServer
    server_version = "LocalHRAPI/1.0"
    protocol_version = "HTTP/1.0"      # one request per connection

    # -- plumbing ------------------------------------------------------------
    def log_message(self, fmt: str, *args) -> None:
        # The request line only -- never headers, never bodies.
        if not self.server.quiet:
            sys.stderr.write(f"  {SERVICE_NAME} {fmt % args}\n")

    def _send_raw(self, status: int, body: bytes) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass                 # the client already gave up (e.g. it timed out)

    def _send(self, status: int, payload: dict) -> None:
        self._send_raw(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def _drop_connection(self) -> None:
        """Close the socket without a response -- the lost-response case."""
        self.close_connection = True
        with contextlib.suppress(OSError):
            self.connection.shutdown(socket.SHUT_RDWR)

    def _read_json(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None
        if length <= 0 or length > MAX_BODY_BYTES:
            return None
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def _ids(self) -> tuple[str | None, str | None]:
        """Correlation ids from headers, kept only if well formed."""
        rid = self.headers.get("X-Request-Id")
        eid = self.headers.get("X-Execution-Id")
        return (rid if rid and _ID.match(rid) else None,
                eid if eid and _ID.match(eid) else None)

    def _audit(self, **fields) -> str:
        return self.server.store.audit(actor=SERVICE_PRINCIPAL, **fields)

    def _authenticated(self) -> bool:
        scheme, _, value = (self.headers.get("Authorization") or "").partition(" ")
        value = value.strip()
        return (scheme.lower() == "bearer" and bool(value)
                and hmac.compare_digest(value.encode(), self.server.token.encode()))

    def _require_auth(self, operation: str) -> bool:
        if self._authenticated():
            return True
        rid, eid = self._ids()
        # Recorded without the header value -- an audit trail must not become a
        # credential store.
        self.server.store.audit(actor=None, request_id=rid, execution_id=eid,
                                operation=operation, result="rejected",
                                error_type="UNAUTHORIZED", http_status=401)
        self._send(401, {"error_code": "UNAUTHORIZED",
                         "message": "missing or invalid service credential",
                         "committed": False})
        return False

    def _serve_fault(self, fault: Fault | None, *, operation: str, rid, eid, route,
                     committed: bool = False) -> bool:
        """Serve a fault that replaces a normal response. True if it did."""
        if fault is None or fault.mode == TARGET_CHANGED:
            return False
        if fault.mode == TIMEOUT:
            time.sleep(fault.delay_s)
            self._audit(request_id=rid, execution_id=eid, route=route, operation=operation,
                        result="timed_out", error_type=TIMEOUT, http_status=504)
            self._send(504, {"error_code": TIMEOUT, "message": "simulated upstream timeout",
                             "committed": committed})
            return True
        if fault.mode == HTTP_500:
            self._audit(request_id=rid, execution_id=eid, route=route, operation=operation,
                        result="error", error_type=HTTP_500, http_status=500)
            # A 5xx vouches for nothing, so the body makes no claim about a commit.
            self._send(500, {"error_code": "INTERNAL_ERROR",
                             "message": "simulated internal error"})
            return True
        if fault.mode == MALFORMED_JSON:
            self._audit(request_id=rid, execution_id=eid, route=route, operation=operation,
                        result="malformed_response", error_type=MALFORMED_JSON, http_status=200)
            self._send_raw(200, b'{"execution_id": "')
            return True
        return False

    # -- dispatch ------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0].rstrip("/")
        if path == "/api/hr/health":
            self._send(200, {"status": "ok", "service": SERVICE_NAME})
            return
        if path == "/api/hr/routes":
            if self._require_auth("list_routes"):
                self._list_routes()
            return
        match = _RECORD.match(path)
        if match:
            if self._require_auth("get_record"):
                self._get_record(match.group(1))
            return
        match = _STATUS.match(path)
        if match:
            if self._require_auth("get_status"):
                self._get_status(match.group(1))
            return
        self._send(404, {"error_code": "NOT_FOUND", "message": "no such endpoint"})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0].rstrip("/")
        match = _NOTES.match(path)
        if match:
            if self._require_auth("set_note"):
                self._post_note(match.group(1))
            return
        match = _CONFIRM.match(path)
        if match:
            if self._require_auth("confirm"):
                self._post_confirm(match.group(1))
            return
        if path == "/api/hr/_simulator/faults":
            if self._require_auth("register_fault"):
                self._post_fault()
            return
        self._send(404, {"error_code": "NOT_FOUND", "message": "no such endpoint"})

    # -- reads ---------------------------------------------------------------
    def _list_routes(self) -> None:
        rid, eid = self._ids()
        self._audit(request_id=rid, execution_id=eid, operation="list_routes",
                    result="success", http_status=200)
        self._send(200, {"routes": self.server.store.routes()})

    def _get_record(self, record_id: str) -> None:
        rid, eid = self._ids()
        record = self.server.store.record(record_id)
        if record is None:
            self._audit(request_id=rid, execution_id=eid, operation="get_record",
                        result="rejected", error_type="RECORD_NOT_FOUND", http_status=404)
            self._send(404, {"error_code": "RECORD_NOT_FOUND",
                             "message": f"no record {record_id!r}"})
            return
        fault = self.server.faults.take(eid, "record")
        if self._serve_fault(fault, operation="get_record", rid=rid, eid=eid,
                             route=record["route"]):
            return
        result = "success"
        if fault is not None and fault.mode == TARGET_CHANGED:
            # The form changed while the human was reviewing: its confirm control
            # is no longer the one that was verified.
            record["confirm_buttons"] = [f"{b}-v2" for b in record["confirm_buttons"]]
            result = "served_changed_target"
        self._audit(request_id=rid, execution_id=eid, route=record["route"],
                    operation="get_record", result=result, http_status=200)
        self._send(200, record)

    def _get_status(self, execution_id: str) -> None:
        rid, _ = self._ids()
        fault = self.server.faults.take(execution_id, "status")
        if self._serve_fault(fault, operation="get_status", rid=rid, eid=execution_id,
                             route=None):
            return
        row = self.server.store.execution(execution_id)
        if row is None:
            self._audit(request_id=rid, execution_id=execution_id, operation="get_status",
                        result="not_found", error_type="EXECUTION_NOT_FOUND", http_status=404)
            self._send(404, {"found": False, "execution_id": execution_id,
                             "error_code": "EXECUTION_NOT_FOUND",
                             "message": "this HR system has no record of that execution"})
            return
        self._audit(request_id=rid, execution_id=execution_id, route=row["route"],
                    operation="get_status", result="success",
                    confirmation_state=row["confirmation_state"], http_status=200)
        self._send(200, {"found": True, **_public(row)})

    # -- writes --------------------------------------------------------------
    def _body_or_reject(self, operation: str, rid, eid) -> dict | None:
        body = self._read_json()
        execution_id = body.get("execution_id") if body else None
        if (body is None or not isinstance(execution_id, str) or not _ID.match(execution_id)
                or (eid is not None and eid != execution_id)):
            self._audit(request_id=rid, execution_id=eid, operation=operation,
                        result="rejected", error_type="MALFORMED_REQUEST", http_status=400)
            self._send(400, {"error_code": "MALFORMED_REQUEST",
                             "message": "a JSON body with a well-formed execution_id "
                                        "(matching X-Execution-Id) is required",
                             "committed": False})
            return None
        return body

    def _post_note(self, record_id: str) -> None:
        rid, eid = self._ids()
        body = self._body_or_reject("set_note", rid, eid)
        if body is None:
            return
        execution_id = body["execution_id"]
        note = body.pop("note_text", None)   # nothing else keeps a reference to it
        if not isinstance(note, str) or not note.strip() or len(note) > MAX_NOTE_CHARS:
            # The HR system's own input validation. Nothing is written.
            self._audit(request_id=rid, execution_id=execution_id, operation="set_note",
                        result="rejected", error_type="INVALID_NOTE", http_status=400)
            self._send(400, {"error_code": "INVALID_NOTE",
                             "message": "note_text must be a non-empty string of at most "
                                        f"{MAX_NOTE_CHARS} characters",
                             "committed": False})
            return
        note_length = len(note)
        del note                     # measured and discarded: never stored, never logged
        record = self.server.store.record(record_id)
        if record is None:
            self._audit(request_id=rid, execution_id=execution_id, operation="set_note",
                        result="rejected", error_type="RECORD_NOT_FOUND", http_status=404)
            self._send(404, {"error_code": "RECORD_NOT_FOUND",
                             "message": f"no record {record_id!r}", "committed": False})
            return
        if body.get("field_id") not in record["note_fields"]:
            self._audit(request_id=rid, execution_id=execution_id, route=record["route"],
                        operation="set_note", result="rejected",
                        error_type="TARGET_CHANGED", http_status=409)
            self._send(409, {"error_code": "TARGET_CHANGED",
                             "message": "that note field is not on this record",
                             "committed": False})
            return
        fault = self.server.faults.take(execution_id, "notes")
        if self._serve_fault(fault, operation="set_note", rid=rid, eid=execution_id,
                             route=record["route"]):
            return
        audit = {"actor": SERVICE_PRINCIPAL, "request_id": rid, "execution_id": execution_id,
                 "route": record["route"], "operation": "set_note", "http_status": 200}
        outcome, row = self.server.store.write_note(execution_id, rid, record,
                                                    note_length, audit)
        if outcome in ("record_mismatch", "not_editable"):
            error = "RECORD_MISMATCH" if outcome == "record_mismatch" else "NOT_EDITABLE"
            self._audit(request_id=rid, execution_id=execution_id, route=record["route"],
                        operation="set_note", result="rejected", error_type=error,
                        confirmation_state=row["confirmation_state"], http_status=409)
            self._send(409, {"error_code": error,
                             "message": "the execution cannot take a note in its current state",
                             "committed": row["confirmation_state"] == CONFIRMED,
                             "confirmation_state": row["confirmation_state"]})
            return
        self._send(200, {**_public(row), "note_written": True})

    def _post_confirm(self, record_id: str) -> None:
        rid, eid = self._ids()
        body = self._body_or_reject("confirm", rid, eid)
        if body is None:
            return
        execution_id = body["execution_id"]
        store = self.server.store
        record = store.record(record_id)
        if record is None:
            self._audit(request_id=rid, execution_id=execution_id, operation="confirm",
                        result="rejected", error_type="RECORD_NOT_FOUND", http_status=404)
            self._send(404, {"error_code": "RECORD_NOT_FOUND",
                             "message": f"no record {record_id!r}", "committed": False})
            return
        route = record["route"]
        if body.get("confirm_button_id") not in record["confirm_buttons"]:
            self._audit(request_id=rid, execution_id=execution_id, route=route,
                        operation="confirm", result="rejected",
                        error_type="TARGET_CHANGED", http_status=409)
            self._send(409, {"error_code": "TARGET_CHANGED",
                             "message": "that confirm control is not on this record",
                             "committed": False})
            return

        outcome, row = store.begin_confirm(execution_id, rid, record_id)
        if outcome == "not_found":
            self._audit(request_id=rid, execution_id=execution_id, route=route,
                        operation="confirm", result="rejected",
                        error_type="EXECUTION_NOT_FOUND", http_status=404)
            self._send(404, {"error_code": "EXECUTION_NOT_FOUND",
                             "message": "no note was ever written for this execution",
                             "committed": False})
            return
        if outcome == "record_mismatch":
            self._audit(request_id=rid, execution_id=execution_id, route=route,
                        operation="confirm", result="rejected",
                        error_type="RECORD_MISMATCH", http_status=409)
            self._send(409, {"error_code": "RECORD_MISMATCH",
                             "message": "this execution belongs to a different record",
                             "committed": row["confirmation_state"] == CONFIRMED})
            return
        if outcome == "already_confirmed":
            # IDEMPOTENCY: the same business action again. Report what was stored;
            # write nothing to the execution.
            self._audit(request_id=rid, execution_id=execution_id, route=route,
                        operation="confirm", result="idempotent_replay",
                        confirmation_state=CONFIRMED, http_status=200)
            self._send(200, {**_public(row), "committed": True, "idempotent_replay": True})
            return
        if outcome == "in_progress":
            self._audit(request_id=rid, execution_id=execution_id, route=route,
                        operation="confirm", result="rejected",
                        error_type="CONFIRMATION_IN_PROGRESS",
                        confirmation_state=IN_PROGRESS, http_status=409)
            # Deliberately no `committed` claim: the other attempt may still commit.
            self._send(409, {"error_code": "CONFIRMATION_IN_PROGRESS",
                             "message": "another confirmation of this execution is running"})
            return

        fault = self.server.faults.take(execution_id, "confirm")
        mode = fault.mode if fault is not None else SUCCESS
        audit = {"actor": SERVICE_PRINCIPAL, "request_id": rid, "execution_id": execution_id,
                 "route": route, "operation": "confirm"}
        if mode == TIMEOUT:
            time.sleep(fault.delay_s)
            store.abort(execution_id, TIMEOUT,
                        {**audit, "result": "aborted_timeout", "http_status": 504})
            self._send(504, {"error_code": TIMEOUT, "message": "simulated upstream timeout; "
                             "the confirmation was not applied", "committed": False})
            return
        if mode == HTTP_500:
            store.abort(execution_id, HTTP_500,
                        {**audit, "result": "aborted_error", "http_status": 500})
            self._send(500, {"error_code": "INTERNAL_ERROR",
                             "message": "simulated internal error"})
            return

        results = {SUCCESS: ("committed", 200),
                   CONFIRM_RESPONSE_LOST: ("committed_response_dropped", None),
                   HTTP_500_AFTER_COMMIT: ("committed_then_error", 500),
                   MALFORMED_JSON: ("committed_malformed_response", 200)}
        result, http_status = results[mode]
        row = store.commit(execution_id, {**audit, "result": result,
                                          "http_status": http_status})
        if mode == CONFIRM_RESPONSE_LOST:
            self._drop_connection()
        elif mode == HTTP_500_AFTER_COMMIT:
            self._send(500, {"error_code": "INTERNAL_ERROR",
                             "message": "simulated internal error"})
        elif mode == MALFORMED_JSON:
            self._send_raw(200, b'{"execution_id": "')
        else:
            self._send(200, {**_public(row), "committed": True, "idempotent_replay": False})

    def _post_fault(self) -> None:
        rid, _ = self._ids()
        body = self._read_json() or {}
        execution_id = body.get("execution_id")
        mode = body.get("mode")
        stage = body.get("stage", "confirm")
        delay = body.get("delay_s", 2.0)
        valid = (isinstance(execution_id, str) and bool(_ID.match(execution_id))
                 and stage in FAULTS_BY_STAGE and mode in FAULTS_BY_STAGE[stage]
                 and isinstance(delay, (int, float)) and 0 <= delay <= 30)
        if not valid:
            self._audit(request_id=rid, execution_id=None, operation="register_fault",
                        result="rejected", error_type="MALFORMED_REQUEST", http_status=400)
            self._send(400, {"error_code": "MALFORMED_REQUEST",
                             "message": "execution_id, a known stage, a mode valid for that "
                                        "stage, and 0 <= delay_s <= 30 are required"})
            return
        self.server.faults.add(execution_id, Fault(mode, stage, float(delay)))
        self._audit(request_id=rid, execution_id=execution_id, operation="register_fault",
                    result=f"{stage}:{mode}", http_status=201)
        self._send(201, {"execution_id": execution_id, "stage": stage, "mode": mode,
                         "delay_s": float(delay)})


# --- construction and small clients ----------------------------------------------

def configured_token() -> str:
    return os.environ.get("LOCAL_HR_API_TOKEN") or DEV_SERVICE_TOKEN


def build_hr_server(db_path: str | Path, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                    *, token: str | None = None, quiet: bool = True) -> LocalHRServer:
    store = HRSystemStore(db_path)
    store.recover_interrupted()
    return LocalHRServer((host, port), store, token=token or configured_token(), quiet=quiet)


@contextlib.contextmanager
def running_hr_server(db_path: str | Path, **kwargs):
    """Start a server on an ephemeral port in a daemon thread. Real sockets, real HTTP."""
    kwargs.setdefault("port", 0)
    server = build_hr_server(db_path, **kwargs)
    # A short poll interval so shutdown (and so a simulated restart) is prompt.
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                              daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def http_json(base_url: str, method: str, path: str, body: dict | None = None, *,
              token: str | None = None, auth: bool = True, timeout_s: float = 3.0,
              headers: dict | None = None) -> tuple[int, dict | None]:
    """A minimal JSON call for tests, the demo and the fault control plane."""
    parts = urlsplit(base_url)
    conn = http.client.HTTPConnection(parts.hostname, parts.port, timeout=timeout_s)
    try:
        sent = {"Accept": "application/json"}
        if auth:
            sent["Authorization"] = f"Bearer {token or configured_token()}"
        payload = None
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            sent["Content-Type"] = "application/json"
        sent.update(headers or {})
        conn.request(method, path, body=payload, headers=sent)
        resp = conn.getresponse()
        raw = resp.read()
        try:
            data = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            data = None
        return resp.status, data if isinstance(data, dict) else None
    finally:
        conn.close()


def register_fault(base_url: str, execution_id: str, mode: str, *, stage: str = "confirm",
                   delay_s: float = 2.0, token: str | None = None,
                   timeout_s: float = 3.0) -> dict:
    """Arm one deterministic fault for one execution on a running local HR server."""
    status, data = http_json(base_url, "POST", "/api/hr/_simulator/faults",
                             {"execution_id": execution_id, "mode": mode, "stage": stage,
                              "delay_s": delay_s},
                             token=token, timeout_s=timeout_s)
    if status != 201 or data is None:
        raise RuntimeError(f"the local HR API refused the fault registration (HTTP {status})")
    return data


def unreachable_base_url(host: str = DEFAULT_HOST) -> str:
    """A local address with nothing listening on it: connecting is refused."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        port = sock.getsockname()[1]
    return f"http://{host}:{port}"
