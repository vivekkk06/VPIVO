"""`HTTPHRApplication`: the `HRApplication` interface over real HTTP.

Every test here talks to a real local HR API server over a real socket (a thread in this
process; `test_http_integration_api.py` also uses separate processes). LOCAL ONLY -- no
test contacts a real HR system.

The property defended hardest: **a confirmation is sent once and never retried**, and
when its outcome cannot be known it is reported UNKNOWN and settled by asking -- never
guessed, never re-sent.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from procmine.automation.audit import ERROR_TYPES, AuditLog
from procmine.automation.hr_payroll_automation import (
    ConfirmationFailedError, InvalidNoteError, NavigationError, NoteInsertionError,
    UnknownRouteError, confirm_submission, prepare_note_submission,
)
from procmine.integrations import execution_state as st
from procmine.integrations import local_hr_api as hr
from procmine.integrations import observability as obs
from procmine.integrations.auth import ROLE_REVIEWER, Actor
from procmine.integrations.hr_application import MODE_HTTP, HRApplication
from procmine.integrations.http_hr_application import (
    LOCAL_DEV_TOKEN, HTTPHRApplication, HTTPIntegrationError, taxonomy_code,
)
from procmine.integrations.orchestrator import Orchestrator
from procmine.integrations.repositories import (
    InMemoryExecutionRepository, SQLiteExecutionRepository,
)

ROUTE = "#/payroll-items"
NOTE = "Confidential: approved the March adjustment for employee 4471"
REVIEWER = Actor("u_reviewer", ROLE_REVIEWER)
SRC = Path(__file__).resolve().parent.parent / "src" / "procmine"
PREPARE_CALLS = ["list_routes", "get_record", "get_record", "set_note", "get_record"]


@pytest.fixture
def server(tmp_path):
    with hr.running_hr_server(tmp_path / "hr.db") as srv:
        yield srv


def adapter(url_or_server, *, timeout_s=2.0, **kw) -> HTTPHRApplication:
    url = getattr(url_or_server, "base_url", url_or_server)
    return HTTPHRApplication(url, execution_id=kw.pop("execution_id", st.new_execution_id()),
                             timeout_s=timeout_s, **kw)


def arm(srv, app, mode, stage="confirm", delay=2.0):
    hr.register_fault(srv.base_url, app.execution_id, mode, stage=stage, delay_s=delay)


def hr_row(srv, app) -> dict | None:
    return srv.store.execution(app.execution_id)


def confirms_received(srv, app) -> int:
    return sum(1 for r in srv.store.audit_trail(app.execution_id) if r["operation"] == "confirm")


def wait_until_settled(srv, app, limit=5.0) -> dict:
    deadline = time.monotonic() + limit
    while hr_row(srv, app)["confirmation_state"] == hr.IN_PROGRESS:
        assert time.monotonic() < deadline, "the held confirmation never finished"
        time.sleep(0.05)
    return hr_row(srv, app)


def resolver_for(url):
    return lambda record: HTTPHRApplication(url, execution_id=record.execution_id,
                                            timeout_s=2.0).query_remote_status()


# --- the interface, and where policy lives ---------------------------------------

def test_the_http_adapter_satisfies_the_interface():
    assert isinstance(adapter("http://127.0.0.1:9"), HRApplication)


def test_the_http_adapter_contains_no_copy_of_the_safety_policy():
    text = (SRC / "integrations" / "http_hr_application.py").read_text(encoding="utf-8")
    for marker in ("UnknownRouteError", "InvalidNoteError", "not one of the four",
                   "must be non-empty", "awaiting human review", "KNOWN_ROUTE_PREFIXES",
                   "from procmine.automation.hr_payroll_automation",
                   "import hr_payroll_automation"):
        assert marker not in text, marker


def test_the_automation_core_knows_nothing_about_http():
    text = (SRC / "automation" / "hr_payroll_automation.py").read_text(encoding="utf-8")
    for forbidden in ("http_hr_application", "local_hr_api", "http.client", "urllib",
                      "sqlite3"):
        assert forbidden not in text, forbidden


def test_the_client_and_server_share_the_local_development_credential():
    assert LOCAL_DEV_TOKEN == hr.DEV_SERVICE_TOKEN


@pytest.mark.parametrize("url", ["https://127.0.0.1:8100", "http://127.0.0.1",
                                 "ftp://127.0.0.1:21", "not a url"])
def test_only_a_local_http_address_is_accepted(url):
    with pytest.raises(ValueError):
        HTTPHRApplication(url, execution_id="exec_x")


@pytest.mark.parametrize("bad", ["", "exec x", "exec/../1", "e" * 65, None])
def test_a_malformed_execution_id_is_refused(bad):
    with pytest.raises(ValueError):
        HTTPHRApplication("http://127.0.0.1:9", execution_id=bad)


def test_the_execution_id_is_the_idempotency_key():
    app = adapter("http://127.0.0.1:9", execution_id="exec_0123456789abcdef")
    assert app.idempotency_key == "exec_0123456789abcdef"


def test_the_repr_never_shows_the_credential():
    app = adapter("http://127.0.0.1:9", token="super-secret-service-value")
    assert "super-secret-service-value" not in repr(app)


# --- the unchanged service, driven over HTTP -------------------------------------

def test_the_unchanged_service_drives_the_http_adapter_end_to_end(server):
    app = adapter(server)
    checkpoint = prepare_note_submission(app, ROUTE, NOTE)
    assert checkpoint.confirmed is False
    assert checkpoint.confirm_button_id == "btn-pi-ok"
    assert hr_row(server, app)["confirmation_state"] == hr.PENDING
    result = confirm_submission(app, checkpoint)
    assert result.confirmed is True
    assert app.calls == PREPARE_CALLS + ["get_record", "confirm"]
    row = hr_row(server, app)
    assert (row["state"], row["confirmation_state"], row["commit_count"]) == (
        hr.COMMITTED, hr.CONFIRMED, 1)


def test_prepare_never_sends_a_confirmation(server):
    app = adapter(server)
    prepare_note_submission(app, ROUTE, NOTE)
    assert "confirm" not in app.calls
    assert confirms_received(server, app) == 0


def test_the_note_length_is_what_the_hr_system_recorded(server):
    app = adapter(server)
    prepare_note_submission(app, ROUTE, NOTE)
    assert hr_row(server, app)["note_length"] == len(NOTE)


def test_policy_refuses_an_unevidenced_route_before_any_http_call(server):
    app = adapter(server)
    with pytest.raises(UnknownRouteError):
        prepare_note_submission(app, "#/not-evidenced", NOTE)
    assert app.calls == []


def test_policy_refuses_an_empty_note_before_any_http_call(server):
    app = adapter(server)
    with pytest.raises(InvalidNoteError):
        prepare_note_submission(app, ROUTE, "   ")
    assert app.calls == []


# --- failures before the human checkpoint: known, safe stops ------------------------

def test_a_refused_connection_stops_prepare_before_anything_is_sent():
    app = adapter(hr.unreachable_base_url())
    with pytest.raises(NavigationError):
        prepare_note_submission(app, ROUTE, NOTE)
    assert app.last_error.code == "INTEGRATION_UNAVAILABLE"
    assert app.last_error.request_sent is False
    assert app.outcome_is_unknown is False


def test_a_wrong_service_credential_is_integration_unauthorized(server):
    app = adapter(server, token="not-the-service-credential")
    with pytest.raises(NavigationError):
        prepare_note_submission(app, ROUTE, NOTE)
    assert app.last_error.code == "INTEGRATION_UNAUTHORIZED"
    assert app.last_error.status == 401


def test_a_malformed_record_response_stops_prepare(server):
    app = adapter(server)
    arm(server, app, hr.MALFORMED_JSON, stage="record")
    with pytest.raises(NavigationError):
        prepare_note_submission(app, ROUTE, NOTE)
    assert app.last_error.code == "INTEGRATION_SERVER_ERROR"
    assert hr_row(server, app) is None, "nothing was written"


def test_a_timed_out_record_read_stops_prepare(server):
    app = adapter(server, timeout_s=0.2)
    arm(server, app, hr.TIMEOUT, stage="record", delay=0.5)
    with pytest.raises(NavigationError):
        prepare_note_submission(app, ROUTE, NOTE)
    assert app.last_error.code == "INTEGRATION_TIMEOUT"


def test_a_failed_note_write_is_a_safe_stop_with_the_partial_log(server):
    """Before this extension such a failure escaped the service as a raw exception."""
    app = adapter(server)
    arm(server, app, hr.HTTP_500, stage="notes")
    with pytest.raises(NoteInsertionError) as exc:
        prepare_note_submission(app, ROUTE, NOTE)
    assert [e.step for e in exc.value.action_log][-1] == "insert_note"
    assert "FAILED" in exc.value.action_log[-1].detail
    assert app.last_error.code == "INTEGRATION_SERVER_ERROR"
    assert hr_row(server, app) is None


def test_the_orchestrator_records_a_failed_note_write_as_failed(server):
    orch = Orchestrator()
    app = adapter(server)
    arm(server, app, hr.HTTP_500, stage="notes")
    with pytest.raises(NoteInsertionError) as exc:
        orch.prepare(REVIEWER, app, ROUTE, NOTE, integration_mode=MODE_HTTP)
    record = orch.repo.get(exc.value.execution_id)
    assert record.status == st.FAILED
    assert record.error_code == "INTEGRATION_SERVER_ERROR"


# --- confirm-time re-verification is real over HTTP ------------------------------------

def test_a_target_that_changed_during_review_is_refused_before_any_confirmation(server):
    app = adapter(server)
    checkpoint = prepare_note_submission(app, ROUTE, NOTE)
    arm(server, app, hr.TARGET_CHANGED, stage="record")   # the page changes while a human reads
    with pytest.raises(ConfirmationFailedError):
        confirm_submission(app, checkpoint)
    assert "confirm" not in app.calls
    assert confirms_received(server, app) == 0
    assert hr_row(server, app)["confirmation_state"] == hr.PENDING
    assert app.outcome_is_unknown is False


def test_a_server_gone_at_confirm_time_is_a_known_failure(tmp_path):
    """The re-verification read is refused, so the confirmation is never sent."""
    with hr.running_hr_server(tmp_path / "hr.db") as srv:
        app = adapter(srv)
        checkpoint = prepare_note_submission(app, ROUTE, NOTE)
    with pytest.raises(ConfirmationFailedError):
        confirm_submission(app, checkpoint)
    assert "confirm" not in app.calls
    assert app.outcome_is_unknown is False
    assert app.last_error.code == "INTEGRATION_UNAVAILABLE"
    assert app.last_error.request_sent is False


def test_an_explicit_4xx_refusal_at_confirm_is_known_not_unknown(server):
    app = adapter(server)
    app.navigate(ROUTE)                      # no note was written for this execution
    with pytest.raises(HTTPIntegrationError):
        app.click("btn-pi-ok")
    assert app.last_error.status == 404
    assert app.last_error.code == "TARGET_NOT_FOUND"
    assert app.outcome_is_unknown is False


# --- failures after the human checkpoint: UNKNOWN, settled by asking --------------------

UNKNOWN_CASES = [
    # mode,                 code after confirm,          resolves to confirmed?, reason
    (hr.CONFIRM_RESPONSE_LOST, "INTEGRATION_UNAVAILABLE", True, None),
    (hr.HTTP_500_AFTER_COMMIT, "INTEGRATION_SERVER_ERROR", True, None),
    (hr.MALFORMED_JSON, "INTEGRATION_SERVER_ERROR", True, None),
    (hr.HTTP_500, "INTEGRATION_SERVER_ERROR", False, "INTEGRATION_SERVER_ERROR"),
]


@pytest.mark.parametrize("mode,code,applied,reason", UNKNOWN_CASES)
def test_an_uncertain_confirmation_is_unknown_and_settled_by_asking(
        server, mode, code, applied, reason):
    app = adapter(server)
    checkpoint = prepare_note_submission(app, ROUTE, NOTE)
    arm(server, app, mode)
    with pytest.raises(ConfirmationFailedError):
        confirm_submission(app, checkpoint)
    assert app.outcome_is_unknown is True
    assert app.last_error.code == code
    remote = app.query_remote_status()
    assert remote["confirmed"] is applied
    assert remote["error_code"] == reason
    assert confirms_received(server, app) == 1, "sent exactly once"
    assert app.calls.count("confirm") == 1, "never retried"


def test_a_timeout_is_unknown_in_progress_then_known_not_applied(server):
    app = adapter(server, timeout_s=0.25)
    checkpoint = prepare_note_submission(app, ROUTE, NOTE)
    arm(server, app, hr.TIMEOUT, delay=0.7)
    with pytest.raises(ConfirmationFailedError):
        confirm_submission(app, checkpoint)
    assert app.outcome_is_unknown is True
    assert app.last_error.code == "INTEGRATION_TIMEOUT"
    during = app.query_remote_status()
    assert during["in_progress"] is True and during["error_code"] is None
    wait_until_settled(server, app)
    after = app.query_remote_status()
    assert after["confirmed"] is False
    assert after["error_code"] == "INTEGRATION_TIMEOUT"
    assert confirms_received(server, app) == 1


def test_a_status_lookup_never_sends_a_confirmation(server):
    app = adapter(server)
    checkpoint = prepare_note_submission(app, ROUTE, NOTE)
    arm(server, app, hr.CONFIRM_RESPONSE_LOST)
    with pytest.raises(ConfirmationFailedError):
        confirm_submission(app, checkpoint)
    for _ in range(3):
        app.query_remote_status()
    assert confirms_received(server, app) == 1
    assert hr_row(server, app)["commit_count"] == 1


def test_an_unknown_execution_id_is_not_found_rather_than_guessed(server):
    remote = adapter(server).query_remote_status()
    assert remote == {"found": False, "confirmed": False, "in_progress": False,
                      "confirmation_state": None, "error_code": "TARGET_NOT_FOUND"}


def test_an_unreachable_status_source_raises_rather_than_answering():
    with pytest.raises(HTTPIntegrationError) as exc:
        adapter(hr.unreachable_base_url()).query_remote_status()
    assert exc.value.code == "INTEGRATION_UNAVAILABLE"


def test_a_failed_status_lookup_does_not_clear_the_unknown_outcome(tmp_path):
    with hr.running_hr_server(tmp_path / "hr.db") as srv:
        app = adapter(srv)
        checkpoint = prepare_note_submission(app, ROUTE, NOTE)
        arm(srv, app, hr.CONFIRM_RESPONSE_LOST)
        with pytest.raises(ConfirmationFailedError):
            confirm_submission(app, checkpoint)
    with pytest.raises(HTTPIntegrationError):
        app.query_remote_status()
    assert app.outcome_is_unknown is True


@pytest.mark.parametrize("status,server_code,expected", [
    (400, None, "MALFORMED_REQUEST"), (400, "INVALID_NOTE", "INVALID_NOTE"),
    (401, None, "INTEGRATION_UNAUTHORIZED"), (403, None, "INTEGRATION_FORBIDDEN"),
    (404, "RECORD_NOT_FOUND", "TARGET_NOT_FOUND"), (409, "TARGET_CHANGED", "TARGET_CHANGED"),
    (409, "CONFIRMATION_IN_PROGRESS", "INTEGRATION_CONFLICT"), (429, None, "RATE_LIMITED"),
    (500, "INTERNAL_ERROR", "INTEGRATION_SERVER_ERROR"), (502, None, "INTEGRATION_SERVER_ERROR"),
    (504, "TIMEOUT", "INTEGRATION_TIMEOUT"), (418, None, "INTEGRATION_SERVER_ERROR"),
])
def test_every_http_failure_maps_into_the_stable_taxonomy(status, server_code, expected):
    assert taxonomy_code(status, server_code) == expected
    assert expected in ERROR_TYPES


def test_a_concurrent_confirmation_in_progress_is_treated_as_unknown(server):
    """If another attempt at the same execution is running, it may still commit."""
    slow = adapter(server, timeout_s=0.2)
    prepare_note_submission(slow, ROUTE, NOTE)
    arm(server, slow, hr.TIMEOUT, delay=0.6)
    with pytest.raises(HTTPIntegrationError):
        slow.click("btn-pi-ok")
    second = adapter(server, execution_id=slow.execution_id)
    second.navigate(ROUTE)
    with pytest.raises(HTTPIntegrationError) as exc:
        second.click("btn-pi-ok")
    assert exc.value.server_code == "CONFIRMATION_IN_PROGRESS"
    assert second.outcome_is_unknown is True
    wait_until_settled(server, slow)


# --- the orchestrator over HTTP: lifecycle, restarts, honesty ---------------------------

def lose_confirmation(orch, srv):
    app = adapter(srv)
    prepared = orch.prepare(REVIEWER, app, ROUTE, NOTE, integration_mode=MODE_HTTP)
    arm(srv, app, hr.CONFIRM_RESPONSE_LOST)
    record = orch.confirm(REVIEWER, prepared.execution_id)
    return app, record


def test_the_orchestrator_adopts_the_adapter_execution_id(server):
    orch = Orchestrator()
    app = adapter(server)
    prepared = orch.prepare(REVIEWER, app, ROUTE, NOTE, integration_mode=MODE_HTTP)
    record = orch.repo.get(prepared.execution_id)
    assert record.execution_id == app.execution_id == record.idempotency_key


def test_two_different_ids_for_one_execution_are_refused(server):
    with pytest.raises(ValueError):
        Orchestrator().prepare(REVIEWER, adapter(server), ROUTE, NOTE,
                               integration_mode=MODE_HTTP, execution_id="exec_other")


def test_the_request_id_travels_to_the_hr_system(server):
    orch = Orchestrator()
    app = adapter(server)
    prepared = orch.prepare(REVIEWER, app, ROUTE, NOTE, integration_mode=MODE_HTTP,
                            request_id="req_prepare_0001")
    orch.confirm(REVIEWER, prepared.execution_id, request_id="req_confirm_0001")
    ids = {(r["operation"], r["request_id"]) for r in server.store.audit_trail(app.execution_id)}
    assert ("set_note", "req_prepare_0001") in ids
    assert ("confirm", "req_confirm_0001") in ids


def test_a_lost_response_is_unknown_then_resolved_confirmed(server):
    orch = Orchestrator()
    app, record = lose_confirmation(orch, server)
    assert record.status == st.UNKNOWN
    assert record.error_code == "CONFIRMATION_UNKNOWN"
    resolved = orch.resolve_unknown(REVIEWER, record.execution_id)
    assert resolved.status == st.CONFIRMED
    assert [h["to"] for h in resolved.history] == [
        st.AWAITING_CONFIRMATION, st.CONFIRMING, st.UNKNOWN, st.CONFIRMED]
    assert confirms_received(server, app) == 1


def test_a_target_change_caught_at_confirm_time_is_failed_not_unknown(server):
    orch = Orchestrator()
    app = adapter(server)
    prepared = orch.prepare(REVIEWER, app, ROUTE, NOTE, integration_mode=MODE_HTTP)
    arm(server, app, hr.TARGET_CHANGED, stage="record")
    record = orch.confirm(REVIEWER, prepared.execution_id)
    assert record.status == st.FAILED
    assert record.error_code == "CONFIRMATION_REJECTED"
    assert confirms_received(server, app) == 0


def test_resolution_survives_an_hr_server_restart(tmp_path):
    orch = Orchestrator()
    db = tmp_path / "hr.db"
    with hr.running_hr_server(db) as first:
        app, record = lose_confirmation(orch, first)
        port = first.server_address[1]
    # A new server process-equivalent: same address, same SQLite file, empty memory.
    with hr.running_hr_server(db, port=port):
        resolved = orch.resolve_unknown(REVIEWER, record.execution_id)
    assert resolved.status == st.CONFIRMED


def test_an_unknown_outcome_is_resolved_by_a_new_process_with_durable_state(server, tmp_path):
    """The restarted orchestrator never held the adapter; only the two databases remain."""
    exec_db = tmp_path / "executions.db"
    before = Orchestrator(repo=SQLiteExecutionRepository(exec_db))
    _, record = lose_confirmation(before, server)
    del before                                       # the process is gone

    after = Orchestrator(repo=SQLiteExecutionRepository(exec_db),
                         resolvers={MODE_HTTP: resolver_for(server.base_url)})
    assert after.repo.get(record.execution_id).status == st.UNKNOWN
    resolved = after.resolve_unknown(REVIEWER, record.execution_id)
    assert resolved.status == st.CONFIRMED
    assert SQLiteExecutionRepository(exec_db).get(record.execution_id).status == st.CONFIRMED


def test_without_durable_state_a_restart_forgets_the_unknown_execution(server):
    """The honest limit: in-memory state cannot support recovery."""
    before = Orchestrator(repo=InMemoryExecutionRepository())
    _, record = lose_confirmation(before, server)
    after = Orchestrator(repo=InMemoryExecutionRepository(),
                         resolvers={MODE_HTTP: resolver_for(server.base_url)})
    assert after.resolve_unknown(REVIEWER, record.execution_id) is None
    # Only the HR system still knows -- and only if asked with the id the client kept.
    kept = HTTPHRApplication(server.base_url, execution_id=record.execution_id)
    assert kept.query_remote_status()["confirmed"] is True


def test_without_a_status_source_an_unknown_outcome_stays_unknown(server, tmp_path):
    exec_db = tmp_path / "executions.db"
    _, record = lose_confirmation(Orchestrator(repo=SQLiteExecutionRepository(exec_db)), server)
    after = Orchestrator(repo=SQLiteExecutionRepository(exec_db))     # no resolver registered
    assert after.resolve_unknown(REVIEWER, record.execution_id).status == st.UNKNOWN


def test_an_unreachable_status_source_keeps_the_execution_unknown(tmp_path):
    db = tmp_path / "hr.db"
    orch = Orchestrator()
    with hr.running_hr_server(db) as srv:
        app, record = lose_confirmation(orch, srv)
        port = srv.server_address[1]
    still = orch.resolve_unknown(REVIEWER, record.execution_id)      # the server is down
    assert still.status == st.UNKNOWN
    events = [e["event"] for e in orch.metrics.recent(50, record.execution_id)]
    assert obs.STATUS_LOOKUP_FAILED in events
    lookups = [e for e in orch.audit.recent(50)
               if e["execution_id"] == record.execution_id and e["action"] == "status_lookup"]
    assert lookups[-1]["result"] == "lookup_failed"
    assert lookups[-1]["error_type"] == "INTEGRATION_UNAVAILABLE"
    with hr.running_hr_server(db, port=port):                         # it comes back
        assert orch.resolve_unknown(REVIEWER, record.execution_id).status == st.CONFIRMED


def test_a_confirmation_still_in_progress_is_not_settled_early(server):
    orch = Orchestrator()
    app = adapter(server, timeout_s=0.25)
    prepared = orch.prepare(REVIEWER, app, ROUTE, NOTE, integration_mode=MODE_HTTP)
    arm(server, app, hr.TIMEOUT, delay=0.7)
    assert orch.confirm(REVIEWER, prepared.execution_id).status == st.UNKNOWN
    early = orch.resolve_unknown(REVIEWER, prepared.execution_id)
    assert early.status == st.UNKNOWN, "settling now could contradict a commit in flight"
    assert obs.STILL_IN_PROGRESS in [
        e["event"] for e in orch.metrics.recent(50, prepared.execution_id)]
    wait_until_settled(server, app)
    late = orch.resolve_unknown(REVIEWER, prepared.execution_id)
    assert late.status == st.FAILED
    assert late.error_code == "INTEGRATION_TIMEOUT"
    assert confirms_received(server, app) == 1


def test_the_orchestrator_never_retries_a_confirmation(server):
    orch = Orchestrator()
    app, record = lose_confirmation(orch, server)
    for _ in range(3):
        orch.resolve_unknown(REVIEWER, record.execution_id)
        orch.status(REVIEWER, record.execution_id)
    assert confirms_received(server, app) == 1
    assert app.calls.count("confirm") == 1


def test_the_target_status_is_read_only_and_mode_specific(server):
    orch = Orchestrator(resolvers={MODE_HTTP: resolver_for(server.base_url)})
    app = adapter(server)
    prepared = orch.prepare(REVIEWER, app, ROUTE, NOTE, integration_mode=MODE_HTTP)
    view = orch.target_status(REVIEWER, prepared.execution_id)
    assert view["confirmation_state"] == hr.PENDING
    assert orch.repo.get(prepared.execution_id).status == st.AWAITING_CONFIRMATION
    assert confirms_received(server, app) == 0
    from procmine.automation.mock_hr_app import MockHRApplication
    mock = orch.prepare(REVIEWER, MockHRApplication(), ROUTE, NOTE)
    assert orch.target_status(REVIEWER, mock.execution_id) is None


def test_an_unreadable_target_status_is_reported_not_raised():
    orch = Orchestrator(resolvers={MODE_HTTP: resolver_for(hr.unreachable_base_url())})
    record = st.ExecutionRecord(execution_id="exec_gone", request_id="req", actor="u",
                                process="HR", route=ROUTE, integration_mode=MODE_HTTP)
    orch.repo.save(record)
    assert orch.target_status(REVIEWER, "exec_gone") == {
        "lookup_error": "INTEGRATION_UNAVAILABLE"}


# --- audit and redaction ----------------------------------------------------------

AUDIT_KEYS = {"request_id", "execution_id", "route", "action", "timestamp", "result",
              "error_type", "confirmation_status"}


def test_every_http_call_is_audited_with_the_required_fields(server):
    log = AuditLog()
    app = adapter(server, audit=log)
    confirm_submission(app, prepare_note_submission(app, ROUTE, NOTE))
    events = log.recent(50)
    assert [e["action"] for e in events] == [f"hr_api.{c}" for c in app.calls]
    for e in events:
        assert AUDIT_KEYS <= set(e)
        assert e["execution_id"] == app.execution_id
        assert e["result"] == "success"
    confirm_event = events[-1]
    assert confirm_event["confirmation_status"] == "CONFIRMED"
    assert confirm_event["detail"]["target_audit_ref"] == hr_row(server, app)["audit_ref"]
    note_event = next(e for e in events if e["action"] == "hr_api.set_note")
    assert note_event["detail"]["note_length"] == len(NOTE)


def test_an_unknown_confirmation_is_audited_as_unknown(server):
    log = AuditLog()
    app = adapter(server, audit=log)
    checkpoint = prepare_note_submission(app, ROUTE, NOTE)
    arm(server, app, hr.CONFIRM_RESPONSE_LOST)
    with pytest.raises(ConfirmationFailedError):
        confirm_submission(app, checkpoint)
    last = log.recent(50)[-1]
    assert (last["action"], last["result"], last["confirmation_status"]) == (
        "hr_api.confirm", "unknown", "UNKNOWN")
    assert last["error_type"] == "INTEGRATION_UNAVAILABLE"


def test_no_note_text_or_credential_reaches_the_audit_trail(server, tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    app = adapter(server, audit=log, token=hr.configured_token())
    checkpoint = prepare_note_submission(app, ROUTE, NOTE)
    arm(server, app, hr.HTTP_500_AFTER_COMMIT)
    with pytest.raises(ConfirmationFailedError):
        confirm_submission(app, checkpoint)
    app.query_remote_status()
    blob = path.read_text(encoding="utf-8") + json.dumps(log.recent(100))
    for leak in (NOTE, hr.configured_token(), "Bearer", "Authorization"):
        assert leak not in blob, leak
    assert "note_length" in blob


def test_the_orchestrator_audit_keeps_the_note_length_only(server):
    orch = Orchestrator()
    orch.prepare(REVIEWER, adapter(server), ROUTE, NOTE, integration_mode=MODE_HTTP)
    stored = [e.detail for e in orch.audit.events]
    assert {"note_length": len(NOTE)} in stored
    assert NOTE not in str(stored), "not even the in-memory buffer holds the text"


def test_error_messages_never_carry_the_note_or_the_credential(server):
    app = adapter(server, token="wrong-service-value")
    with pytest.raises(NavigationError) as exc:
        prepare_note_submission(app, ROUTE, NOTE)
    text = str(exc.value) + " ".join(e.detail for e in exc.value.action_log)
    assert "wrong-service-value" not in text
    assert NOTE not in text


def test_every_code_the_adapter_produced_is_in_the_taxonomy(server):
    codes = set()
    for mode, *_ in UNKNOWN_CASES:
        app = adapter(server)
        checkpoint = prepare_note_submission(app, ROUTE, NOTE)
        arm(server, app, mode)
        with pytest.raises(ConfirmationFailedError):
            confirm_submission(app, checkpoint)
        codes.add(app.last_error.code)
    refused = adapter(hr.unreachable_base_url())
    with pytest.raises(NavigationError):
        prepare_note_submission(refused, ROUTE, NOTE)
    codes.add(refused.last_error.code)
    assert codes <= ERROR_TYPES
