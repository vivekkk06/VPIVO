"""The local HR API simulator: a real HTTP server with SQLite state.

LOCAL ONLY. It stands in for an HR system so the integration boundary can be exercised
over real sockets. Nothing here is, or talks to, a real HR system.

What must hold:

* idempotency by `execution_id` -- a confirmation is applied at most once, even when
  repeated or raced;
* the note is measured and discarded -- its text never reaches the database;
* credentials never reach the database, the audit trail or the console;
* state survives a restart, and an interrupted confirmation never masquerades as a
  committed one;
* every failure is selected, never random.
"""

from __future__ import annotations

import http.client
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import closing
from pathlib import Path

import pytest

from procmine.integrations import local_hr_api as hr
from procmine.process_discovery.dom_evidence import KNOWN_ROUTE_PREFIXES

ROOT = Path(__file__).resolve().parent.parent
ROUTE = "#/payroll-items"
RECORD = "payroll-items"
NOTE = "Confidential: approved the March adjustment for employee 4471"


@pytest.fixture
def server(tmp_path):
    with hr.running_hr_server(tmp_path / "hr.db") as srv:
        yield srv


def call(srv, method, path, body=None, **kw):
    return hr.http_json(srv.base_url, method, path, body, **kw)


def write_note(srv, eid, text=NOTE, record=RECORD, field="pi-note"):
    return call(srv, "POST", f"/api/hr/records/{record}/notes",
                {"execution_id": eid, "field_id": field, "note_text": text})


def confirm(srv, eid, record=RECORD, button="btn-pi-ok", **kw):
    return call(srv, "POST", f"/api/hr/records/{record}/confirm",
                {"execution_id": eid, "confirm_button_id": button}, **kw)


def status(srv, eid):
    return call(srv, "GET", f"/api/hr/executions/{eid}/status")


def confirms_received(srv, eid) -> int:
    return sum(1 for row in srv.store.audit_trail(eid) if row["operation"] == "confirm")


# --- the contract ------------------------------------------------------------

def test_health_is_open_and_says_only_that_it_is_up(server):
    code, body = call(server, "GET", "/api/hr/health", auth=False)
    assert code == 200
    assert body == {"status": "ok", "service": "local-hr-api"}


@pytest.mark.parametrize("path", ["/api/hr/routes", f"/api/hr/records/{RECORD}",
                                  "/api/hr/executions/exec_x/status"])
def test_every_business_endpoint_requires_the_service_credential(server, path):
    assert call(server, "GET", path, auth=False)[0] == 401
    code, body = call(server, "GET", path, token="not-the-service-credential")
    assert code == 401
    assert body["error_code"] == "UNAUTHORIZED"


def test_mutations_require_the_service_credential_and_write_nothing_without_it(server):
    code, _ = call(server, "POST", f"/api/hr/records/{RECORD}/notes",
                   {"execution_id": "exec_a", "field_id": "pi-note", "note_text": NOTE},
                   auth=False)
    assert code == 401
    assert server.store.execution("exec_a") is None


def test_routes_are_exactly_the_evidenced_routes(server):
    code, body = call(server, "GET", "/api/hr/routes")
    assert code == 200
    assert [r["route"] for r in body["routes"]] == list(KNOWN_ROUTE_PREFIXES)
    assert all(r["record_id"] == r["route"].lstrip("#/") for r in body["routes"])


def test_each_record_carries_the_evidenced_element_ids(server):
    for route, prefix in KNOWN_ROUTE_PREFIXES.items():
        code, body = call(server, "GET", f"/api/hr/records/{hr.record_id_for(route)}")
        assert code == 200
        assert body == {"record_id": hr.record_id_for(route), "route": route,
                        "note_fields": [f"{prefix}-note"],
                        "confirm_buttons": [f"btn-{prefix}-ok"]}


def test_an_unknown_record_is_404(server):
    code, body = call(server, "GET", "/api/hr/records/not-a-record")
    assert code == 404
    assert body["error_code"] == "RECORD_NOT_FOUND"


def test_an_unknown_endpoint_is_404(server):
    assert call(server, "GET", "/api/hr/employees")[0] == 404


# --- notes: measured, never kept ----------------------------------------------

def test_a_note_creates_a_pending_execution_with_its_length(server):
    code, body = write_note(server, "exec_note1")
    assert code == 200
    assert body["confirmation_state"] == hr.PENDING
    assert body["state"] == hr.NOTE_RECEIVED
    assert body["note_length"] == len(NOTE)
    assert body["commit_count"] == 0


def test_the_note_text_never_reaches_the_database(server, tmp_path):
    write_note(server, "exec_note2")
    confirm(server, "exec_note2")
    raw = (tmp_path / "hr.db").read_bytes()
    assert NOTE.encode() not in raw
    assert b"exec_note2" in raw, "sanity: the execution really was written"


def test_the_schema_has_no_column_for_note_text_or_credentials():
    lowered = hr._SCHEMA.lower()
    for forbidden in ("note_text", "note_content", "token", "password", "secret",
                      "credential", "authorization", "bearer"):
        assert forbidden not in lowered, forbidden


def test_the_response_to_a_note_does_not_echo_it(server):
    _, body = write_note(server, "exec_note3")
    assert NOTE not in str(body)


@pytest.mark.parametrize("text", ["", "   ", "x" * (hr.MAX_NOTE_CHARS + 1)])
def test_the_hr_system_refuses_an_invalid_note_and_writes_nothing(server, text):
    code, body = write_note(server, "exec_bad", text=text)
    assert code == 400
    assert body["error_code"] == "INVALID_NOTE"
    assert server.store.execution("exec_bad") is None


def test_a_note_for_a_field_that_is_not_on_the_record_is_refused(server):
    code, body = write_note(server, "exec_field", field="la-note")
    assert code == 409
    assert body["error_code"] == "TARGET_CHANGED"


def test_a_mismatched_execution_header_is_refused(server):
    code, body = call(server, "POST", f"/api/hr/records/{RECORD}/notes",
                      {"execution_id": "exec_body", "field_id": "pi-note", "note_text": NOTE},
                      headers={"X-Execution-Id": "exec_header"})
    assert code == 400
    assert body["error_code"] == "MALFORMED_REQUEST"
    assert server.store.execution("exec_body") is None


def test_a_malformed_body_is_refused(server):
    code, body = call(server, "POST", f"/api/hr/records/{RECORD}/notes", {"field_id": "pi-note"})
    assert code == 400
    assert body["committed"] is False


def test_a_committed_execution_takes_no_further_note(server):
    write_note(server, "exec_done")
    confirm(server, "exec_done")
    code, body = write_note(server, "exec_done", text="a different note")
    assert code == 409
    assert body["error_code"] == "NOT_EDITABLE"
    assert server.store.execution("exec_done")["note_length"] == len(NOTE)


# --- confirmation and idempotency -----------------------------------------------

def test_a_confirmation_commits_once(server):
    write_note(server, "exec_c1")
    code, body = confirm(server, "exec_c1")
    assert code == 200
    assert body["committed"] is True
    assert body["idempotent_replay"] is False
    assert body["confirmation_state"] == hr.CONFIRMED
    assert body["state"] == hr.COMMITTED
    assert body["commit_count"] == 1


def test_a_duplicate_confirmation_returns_the_stored_outcome_and_writes_nothing(server):
    write_note(server, "exec_dup")
    _, first = confirm(server, "exec_dup")
    code, second = confirm(server, "exec_dup")
    assert code == 200
    assert second["idempotent_replay"] is True
    assert second["commit_count"] == 1, "no second write"
    assert second["confirmed_at"] == first["confirmed_at"]
    assert server.store.execution("exec_dup")["commit_count"] == 1


def test_concurrent_duplicate_confirmations_commit_exactly_once(server):
    write_note(server, "exec_race")
    results: list[tuple[int, dict]] = []
    lock = threading.Lock()

    def attempt():
        outcome = confirm(server, "exec_race")
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert server.store.execution("exec_race")["commit_count"] == 1
    fresh = [b for code, b in results if code == 200 and b["idempotent_replay"] is False]
    assert len(fresh) == 1
    assert all(code in (200, 409) for code, _ in results)


def test_confirming_an_execution_that_never_wrote_a_note_is_404(server):
    code, body = confirm(server, "exec_never")
    assert code == 404
    assert body["error_code"] == "EXECUTION_NOT_FOUND"
    assert body["committed"] is False


def test_confirming_a_control_that_is_not_on_the_record_is_refused(server):
    write_note(server, "exec_btn")
    code, body = confirm(server, "exec_btn", button="btn-pi-cancel")
    assert code == 409
    assert body["error_code"] == "TARGET_CHANGED"
    assert server.store.execution("exec_btn")["confirmation_state"] == hr.PENDING


def test_confirming_through_a_different_record_is_refused(server):
    write_note(server, "exec_rec")
    code, body = confirm(server, "exec_rec", record="onboarding", button="btn-ob-ok")
    assert code == 409
    assert body["error_code"] == "RECORD_MISMATCH"
    assert server.store.execution("exec_rec")["commit_count"] == 0


# --- status ------------------------------------------------------------------------

def test_status_reports_the_stored_state(server):
    write_note(server, "exec_s1")
    assert status(server, "exec_s1")[1]["confirmation_state"] == hr.PENDING
    confirm(server, "exec_s1")
    code, body = status(server, "exec_s1")
    assert code == 200
    assert body["found"] is True
    assert body["confirmation_state"] == hr.CONFIRMED


def test_an_unknown_execution_id_is_reported_as_not_found(server):
    code, body = status(server, "exec_unknown_id")
    assert code == 404
    assert body == {"found": False, "execution_id": "exec_unknown_id",
                    "error_code": "EXECUTION_NOT_FOUND",
                    "message": "this HR system has no record of that execution"}


def test_status_never_changes_anything(server):
    write_note(server, "exec_ro")
    before = server.store.execution("exec_ro")
    for _ in range(3):
        status(server, "exec_ro")
    assert server.store.execution("exec_ro") == before


# --- failure injection: selected per execution, one-shot ------------------------------

def arm(srv, eid, mode, stage="confirm", delay=2.0):
    return hr.register_fault(srv.base_url, eid, mode, stage=stage, delay_s=delay)


def raw_confirm(srv, eid, timeout=5.0):
    """A plain http.client call, so a dropped connection surfaces as it would to a client."""
    conn = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=timeout)
    try:
        conn.request("POST", f"/api/hr/records/{RECORD}/confirm",
                     body=f'{{"execution_id": "{eid}", "confirm_button_id": "btn-pi-ok"}}',
                     headers={"Authorization": f"Bearer {hr.configured_token()}",
                              "Content-Type": "application/json"})
        response = conn.getresponse()
        return response.status, response.read()
    finally:
        conn.close()


def test_a_fault_must_name_a_mode_valid_for_its_stage(server):
    with pytest.raises(RuntimeError):
        arm(server, "exec_f", hr.CONFIRM_RESPONSE_LOST, stage="record")
    with pytest.raises(RuntimeError):
        arm(server, "exec_f", "EXPLODE")
    with pytest.raises(RuntimeError):
        arm(server, "exec_f", hr.TIMEOUT, delay=99)


def test_the_fault_control_plane_requires_the_service_credential(server):
    code, _ = call(server, "POST", "/api/hr/_simulator/faults",
                   {"execution_id": "exec_f", "mode": hr.HTTP_500}, auth=False)
    assert code == 401


def test_a_dropped_response_still_commits(server):
    write_note(server, "exec_lost")
    arm(server, "exec_lost", hr.CONFIRM_RESPONSE_LOST)
    with pytest.raises(http.client.RemoteDisconnected):
        raw_confirm(server, "exec_lost")
    body = status(server, "exec_lost")[1]
    assert body["confirmation_state"] == hr.CONFIRMED
    assert body["commit_count"] == 1


def test_a_500_before_commit_applies_nothing(server):
    write_note(server, "exec_500")
    arm(server, "exec_500", hr.HTTP_500)
    code, body = confirm(server, "exec_500")
    assert code == 500
    assert "committed" not in body, "a 5xx vouches for nothing"
    row = server.store.execution("exec_500")
    assert (row["confirmation_state"], row["commit_count"], row["last_error_type"]) == (
        hr.PENDING, 0, hr.HTTP_500)


def test_a_500_after_commit_hides_a_real_commit(server):
    write_note(server, "exec_500c")
    arm(server, "exec_500c", hr.HTTP_500_AFTER_COMMIT)
    assert confirm(server, "exec_500c")[0] == 500
    assert server.store.execution("exec_500c")["confirmation_state"] == hr.CONFIRMED


def test_a_malformed_success_body_follows_a_real_commit(server):
    write_note(server, "exec_bad_json")
    arm(server, "exec_bad_json", hr.MALFORMED_JSON)
    code, _ = raw_confirm(server, "exec_bad_json")
    assert code == 200
    assert call(server, "POST", f"/api/hr/records/{RECORD}/confirm",
                {"execution_id": "exec_bad_json", "confirm_button_id": "btn-pi-ok"}
                )[1]["idempotent_replay"] is True
    assert server.store.execution("exec_bad_json")["commit_count"] == 1


def test_a_timeout_is_in_progress_while_held_then_aborted_uncommitted(server):
    write_note(server, "exec_slow")
    arm(server, "exec_slow", hr.TIMEOUT, delay=0.6)
    with pytest.raises(TimeoutError):
        raw_confirm(server, "exec_slow", timeout=0.2)
    assert status(server, "exec_slow")[1]["confirmation_state"] == hr.IN_PROGRESS
    # A second confirmation while the first is held is refused, not applied.
    code, body = confirm(server, "exec_slow")
    assert code == 409
    assert body["error_code"] == "CONFIRMATION_IN_PROGRESS"
    assert "committed" not in body
    deadline = time.monotonic() + 5
    while status(server, "exec_slow")[1]["confirmation_state"] == hr.IN_PROGRESS:
        assert time.monotonic() < deadline
        time.sleep(0.05)
    row = server.store.execution("exec_slow")
    assert (row["confirmation_state"], row["commit_count"], row["last_error_type"]) == (
        hr.PENDING, 0, hr.TIMEOUT)


def test_faults_are_one_shot_and_scoped_to_one_execution(server):
    write_note(server, "exec_one")
    write_note(server, "exec_two")
    arm(server, "exec_one", hr.HTTP_500)
    assert confirm(server, "exec_two")[0] == 200, "another execution is unaffected"
    assert confirm(server, "exec_one")[0] == 500
    assert confirm(server, "exec_one")[0] == 200, "the fault struck once"


def test_a_changed_target_is_served_once_on_the_next_record_read(server):
    arm(server, "exec_tc", hr.TARGET_CHANGED, stage="record")
    headers = {"X-Execution-Id": "exec_tc"}
    _, changed = call(server, "GET", f"/api/hr/records/{RECORD}", headers=headers)
    _, normal = call(server, "GET", f"/api/hr/records/{RECORD}", headers=headers)
    assert changed["confirm_buttons"] == ["btn-pi-ok-v2"]
    assert normal["confirm_buttons"] == ["btn-pi-ok"]


@pytest.mark.parametrize("stage,path", [("record", f"/api/hr/records/{RECORD}"),
                                        ("status", "/api/hr/executions/exec_rf/status")])
def test_read_stages_can_fail_with_a_500(server, stage, path):
    arm(server, "exec_rf", hr.HTTP_500, stage=stage)
    code, _ = call(server, "GET", path, headers={"X-Execution-Id": "exec_rf"})
    assert code == 500


def test_nothing_about_a_fault_is_random():
    import inspect

    source = inspect.getsource(hr)
    assert "import random" not in source and "from random" not in source


# --- durability ---------------------------------------------------------------

def test_a_commit_survives_a_server_restart(tmp_path):
    db = tmp_path / "hr.db"
    with hr.running_hr_server(db) as first:
        write_note(first, "exec_durable")
        confirm(first, "exec_durable")
    with hr.running_hr_server(db) as second:
        code, body = status(second, "exec_durable")
        assert code == 200
        assert body["confirmation_state"] == hr.CONFIRMED
        # and idempotency holds across the restart
        assert confirm(second, "exec_durable")[1]["idempotent_replay"] is True
        assert second.store.execution("exec_durable")["commit_count"] == 1


def test_an_interrupted_confirmation_is_not_left_in_progress_after_a_restart(tmp_path):
    db = tmp_path / "hr.db"
    store = hr.HRSystemStore(db)
    record = store.record(RECORD)
    store.write_note("exec_cut", "req_1", record, 12,
                     {"operation": "set_note", "route": ROUTE, "execution_id": "exec_cut"})
    assert store.begin_confirm("exec_cut", "req_2", RECORD)[0] == "started"
    # The process dies here, before the commit. A restart must not report it as
    # in progress forever -- and certainly not as committed.
    with hr.running_hr_server(db) as srv:
        body = status(srv, "exec_cut")[1]
    assert body["confirmation_state"] == hr.PENDING
    assert body["last_error_type"] == "INTERRUPTED"
    assert body["commit_count"] == 0


def test_an_in_memory_store_is_refused():
    with pytest.raises(ValueError):
        hr.HRSystemStore(":memory:")


# --- the audit trail -------------------------------------------------------------

AUDIT_FIELDS = {"request_id", "execution_id", "route", "operation", "timestamp", "result",
                "error_type", "confirmation_state"}


def test_every_request_leaves_an_audit_row_with_the_required_fields(server):
    headers = {"X-Request-Id": "req_audit_1"}
    call(server, "GET", f"/api/hr/records/{RECORD}", headers=headers)
    write_note(server, "exec_aud")
    confirm(server, "exec_aud")
    status(server, "exec_aud")
    rows = server.store.audit_trail()
    assert [r["operation"] for r in rows] == ["get_record", "set_note", "confirm", "get_status"]
    for row in rows:
        assert AUDIT_FIELDS <= set(row)
        assert row["timestamp"]
    assert rows[0]["request_id"] == "req_audit_1"
    assert rows[1]["note_length"] == len(NOTE)
    assert rows[2]["result"] == "committed"
    assert rows[2]["confirmation_state"] == hr.CONFIRMED


def test_a_commit_and_its_audit_row_share_a_reference(server):
    write_note(server, "exec_ref")
    _, body = confirm(server, "exec_ref")
    commit_rows = [r for r in server.store.audit_trail("exec_ref") if r["result"] == "committed"]
    assert len(commit_rows) == 1
    assert body["audit_ref"] == commit_rows[0]["audit_ref"]


def test_a_rejected_credential_is_audited_without_the_credential(server, tmp_path):
    call(server, "GET", "/api/hr/routes", token="Bearer-looking-secret-value")
    rows = server.store.audit_trail()
    assert rows[-1]["result"] == "rejected"
    assert rows[-1]["error_type"] == "UNAUTHORIZED"
    raw = (tmp_path / "hr.db").read_bytes()
    assert b"Bearer-looking-secret-value" not in raw
    assert hr.configured_token().encode() not in raw


def test_the_audit_trail_never_holds_note_text(server):
    write_note(server, "exec_an")
    confirm(server, "exec_an")
    assert NOTE not in str(server.store.audit_trail())


def test_the_console_log_carries_the_request_line_but_no_credential(tmp_path, capfd):
    with hr.running_hr_server(tmp_path / "hr.db", quiet=False) as srv:
        write_note(srv, "exec_log")
    err = capfd.readouterr().err
    assert "/api/hr/records/payroll-items/notes" in err
    assert hr.configured_token() not in err
    assert NOTE not in err
    assert "Bearer" not in err


# --- helpers and the process entry point ----------------------------------------------

def test_the_unreachable_address_really_refuses():
    url = hr.unreachable_base_url()
    port = int(url.rsplit(":", 1)[1])
    with pytest.raises(ConnectionRefusedError):
        socket.create_connection(("127.0.0.1", port), timeout=1).close()


def test_the_server_script_refuses_a_non_loopback_address(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "serve_local_hr_api.py"),
         "--host", "0.0.0.0", "--port", "0", "--db", str(tmp_path / "hr.db")],
        capture_output=True, text=True, timeout=30)
    assert proc.returncode == 2
    assert "refusing" in proc.stderr


def test_the_server_script_serves_real_http_from_its_own_process(tmp_path):
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "serve_local_hr_api.py"),
         "--port", "0", "--db", str(tmp_path / "hr.db")],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        line = proc.stdout.readline().strip()
        assert line.startswith("LISTENING http://127.0.0.1:")
        url = line.split(" ", 1)[1]
        assert hr.http_json(url, "GET", "/api/hr/health", auth=False)[0] == 200
        assert hr.http_json(url, "GET", "/api/hr/routes")[0] == 200
    finally:
        proc.terminate()
        assert proc.wait(timeout=15) == 0, "SIGTERM should stop it cleanly"
        proc.stdout.close()
    with closing(sqlite3.connect(tmp_path / "hr.db")) as conn:
        assert conn.execute("SELECT COUNT(*) FROM hr_records").fetchone()[0] == 4
