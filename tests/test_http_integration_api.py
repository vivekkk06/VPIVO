"""The automation API in `http` mode, end to end.

    client -> automation API (scripts/serve_hr_demo_api.py) -> policy -> orchestrator
           -> HTTPHRApplication -> local HR API (real HTTP) -> SQLite

Both servers are real HTTP servers on ephemeral ports; the last test also runs them as
separate processes through the committed demo. LOCAL ONLY: the `http` mode is a local
HTTP integration with a simulator, never a real HR system, and is labelled that way.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from procmine.integrations import local_hr_api as hr
from procmine.integrations.hr_application import MODE_HTTP
from procmine.integrations.orchestrator import Orchestrator
from procmine.integrations.repositories import (
    InMemoryExecutionRepository, SQLiteExecutionRepository,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "serve_hr_demo_api.py"
_spec = importlib.util.spec_from_file_location("serve_hr_demo_api_http", _SCRIPT)
_module = importlib.util.module_from_spec(_spec)
sys.modules["serve_hr_demo_api_http"] = _module
_spec.loader.exec_module(_module)

ROUTE = "#/payroll-items"
NOTE = "Reviewed per standard process."
SECRET_NOTE = "Confidential: approved the March adjustment for employee 4471"


def _client(base: str):
    def call(method: str, path: str, body: dict | None = None, *, token: str | None = None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(base + path, method=method, headers=headers,
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            return exc.code, (json.loads(raw) if raw else {})
    return call


@pytest.fixture(scope="module")
def hr_server(tmp_path_factory):
    with hr.running_hr_server(tmp_path_factory.mktemp("hr") / "hr.db") as srv:
        yield srv


@pytest.fixture(scope="module")
def api(hr_server):
    saved = (_module.HR_API_BASE_URL, _module.HR_API_TIMEOUT_S)
    _module.HR_API_BASE_URL = hr_server.base_url
    _module.HR_API_TIMEOUT_S = 0.4
    server = _module.build_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever,
                              kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    yield _client(f"http://127.0.0.1:{server.server_address[1]}")
    server.shutdown()
    server.server_close()
    _module.HR_API_BASE_URL, _module.HR_API_TIMEOUT_S = saved


def prepare(api, failure_mode="SUCCESS", note=NOTE, route=ROUTE, **kw):
    return api("POST", "/api/prepare", {"route": route, "note_text": note,
                                        "integration_mode": MODE_HTTP,
                                        "failure_mode": failure_mode}, **kw)


def confirm(api, checkpoint, **kw):
    return api("POST", "/api/confirm", {"checkpoint_token": checkpoint["checkpoint_token"]}, **kw)


def status(api, execution_id, **kw):
    return api("GET", f"/api/executions/{execution_id}/status", **kw)


def confirms_received(srv, execution_id) -> int:
    return sum(1 for r in srv.store.audit_trail(execution_id) if r["operation"] == "confirm")


def wait_until_settled(srv, execution_id, limit=5.0):
    deadline = time.monotonic() + limit
    while srv.store.execution(execution_id)["confirmation_state"] == hr.IN_PROGRESS:
        assert time.monotonic() < deadline
        time.sleep(0.05)


# --- the mode is offered, and offered honestly ----------------------------------

def test_the_local_http_target_is_advertised_and_labelled_local(api):
    _, payload = api("GET", "/api/integration-modes")
    modes = {m["id"]: m["label"] for m in payload["modes"]}
    assert modes[MODE_HTTP].startswith("LOCAL HTTP INTEGRATION")
    assert "production" not in modes[MODE_HTTP].lower()
    assert payload["http_failure_modes"] == hr.HTTP_FAILURE_MODES
    assert "CONFIRM_RESPONSE_LOST" not in payload["failure_modes"], (
        "the in-process simulator keeps its own failure list")


def test_a_simulator_only_failure_mode_is_refused_for_http(api):
    code, payload = prepare(api, failure_mode="CONFLICT")
    assert code == 400
    assert payload["error_type"] == "MALFORMED_REQUEST"


def test_an_http_only_failure_mode_is_refused_for_the_simulator(api):
    code, _ = api("POST", "/api/prepare", {"route": ROUTE, "note_text": NOTE,
                                           "integration_mode": "api_simulator",
                                           "failure_mode": "CONFIRM_RESPONSE_LOST"})
    assert code == 400


# --- the confirmed path -------------------------------------------------------

def test_a_confirmed_execution_end_to_end(api, hr_server):
    code, checkpoint = prepare(api)
    assert code == 200
    assert checkpoint["integration_mode"] == MODE_HTTP
    assert checkpoint["status"] == "AWAITING_CONFIRMATION"
    assert checkpoint["confirmed"] is False
    eid = checkpoint["execution_id"]
    row = hr_server.store.execution(eid)
    assert row["confirmation_state"] == hr.PENDING, "the HR system holds the prepared note"
    assert row["request_id"] == checkpoint["request_id"]

    code, result = confirm(api, checkpoint)
    assert code == 200
    assert (result["status"], result["confirmed"]) == ("CONFIRMED", True)

    code, view = status(api, eid)
    assert code == 200
    assert view["status"] == "CONFIRMED"
    assert view["target"]["source"] == "local HR API (HTTP)"
    assert view["target"]["confirmation_state"] == hr.CONFIRMED
    assert view["target"]["commit_count"] == 1
    assert hr_server.store.execution(eid)["state"] == hr.COMMITTED


def test_other_modes_report_no_target_view(api):
    _, checkpoint = api("POST", "/api/prepare", {"route": ROUTE, "note_text": NOTE})
    _, view = status(api, checkpoint["execution_id"])
    assert view["target"] is None


# --- the lost response -----------------------------------------------------------

def test_a_lost_response_is_unknown_then_resolved_by_status_lookup(api, hr_server):
    _, checkpoint = prepare(api, "CONFIRM_RESPONSE_LOST")
    eid = checkpoint["execution_id"]
    code, result = confirm(api, checkpoint)
    assert code == 202
    assert result["status"] == "UNKNOWN"
    assert result["error_type"] == "CONFIRMATION_UNKNOWN"
    assert result["execution_id"] == eid
    assert result["status_url"] == f"/api/executions/{eid}/status"
    assert hr_server.store.execution(eid)["confirmation_state"] == hr.CONFIRMED, (
        "the HR system committed although the client never heard")

    _, first = status(api, eid)
    assert (first["status"], first["resolved_from_unknown"]) == ("CONFIRMED", True)
    _, second = status(api, eid)
    assert (second["status"], second["resolved_from_unknown"]) == ("CONFIRMED", False)


def test_a_lost_response_is_never_retried(api, hr_server):
    _, checkpoint = prepare(api, "CONFIRM_RESPONSE_LOST")
    eid = checkpoint["execution_id"]
    confirm(api, checkpoint)
    for _ in range(3):
        status(api, eid)
    code, again = confirm(api, checkpoint)
    assert code == 400
    assert again["error_type"] == "REPLAYED_REQUEST"
    assert confirms_received(hr_server, eid) == 1
    assert hr_server.store.execution(eid)["commit_count"] == 1


def test_a_held_confirmation_stays_unknown_until_the_hr_system_finishes(api, hr_server):
    _, checkpoint = prepare(api, "TIMEOUT")
    eid = checkpoint["execution_id"]
    code, result = confirm(api, checkpoint)
    assert (code, result["status"]) == (202, "UNKNOWN")
    _, early = status(api, eid)
    assert early["status"] == "UNKNOWN"
    assert early["resolved_from_unknown"] is False
    assert early["target"]["in_progress"] is True
    wait_until_settled(hr_server, eid)
    _, late = status(api, eid)
    assert (late["status"], late["error_code"], late["resolved_from_unknown"]) == (
        "FAILED", "INTEGRATION_TIMEOUT", True)
    assert hr_server.store.execution(eid)["commit_count"] == 0
    assert confirms_received(hr_server, eid) == 1


@pytest.mark.parametrize("mode,settled,error_code", [
    ("HTTP_500", "FAILED", "INTEGRATION_SERVER_ERROR"),
    ("HTTP_500_AFTER_COMMIT", "CONFIRMED", "CONFIRMATION_UNKNOWN"),
    ("MALFORMED_JSON", "CONFIRMED", "CONFIRMATION_UNKNOWN"),
])
def test_an_uncertain_answer_is_unknown_until_the_hr_system_is_asked(
        api, hr_server, mode, settled, error_code):
    _, checkpoint = prepare(api, mode)
    code, result = confirm(api, checkpoint)
    assert (code, result["status"]) == (202, "UNKNOWN")
    _, view = status(api, checkpoint["execution_id"])
    assert view["status"] == settled
    # A settled CONFIRMED keeps the code that explains how it got there.
    assert view["error_code"] == error_code
    assert confirms_received(hr_server, checkpoint["execution_id"]) == 1


# --- failures that stop before the human checkpoint --------------------------------

def test_a_refused_connection_stops_at_prepare(api, hr_server):
    code, stop = prepare(api, "CONNECTION_REFUSED")
    assert code == 422
    assert (stop["status"], stop["error_type"]) == ("FAILED", "INTEGRATION_UNAVAILABLE")
    assert stop["execution_id"].startswith("exec_")
    assert hr_server.store.execution(stop["execution_id"]) is None
    _, view = status(api, stop["execution_id"])
    assert view["status"] == "FAILED"


def test_an_unreachable_hr_api_is_a_safe_stop_not_a_crash(api, monkeypatch):
    monkeypatch.setattr(_module, "HR_API_BASE_URL", hr.unreachable_base_url())
    code, stop = prepare(api)
    assert (code, stop["error_type"]) == (422, "INTEGRATION_UNAVAILABLE")
    # With a fault requested, the fault cannot even be armed: the target is unavailable.
    code, payload = prepare(api, "HTTP_500")
    assert (code, payload["error_type"]) == (503, "INTEGRATION_UNAVAILABLE")


@pytest.mark.parametrize("route,note,error_type", [
    ("#/not-evidenced", NOTE, "INVALID_ROUTE"),
    (ROUTE, "   ", "INVALID_NOTE"),
])
def test_policy_refuses_before_the_hr_system_is_contacted(api, hr_server, route, note,
                                                          error_type):
    code, stop = prepare(api, route=route, note=note)
    assert (code, stop["error_type"]) == (422, error_type)
    assert hr_server.store.audit_trail(stop["execution_id"]) == [], (
        "the HR API must not have seen this execution at all")


def test_an_operator_cannot_confirm_an_http_execution(api, hr_server):
    _, checkpoint = prepare(api, token="dev-operator-token")
    code, payload = confirm(api, checkpoint, token="dev-operator-token")
    assert (code, payload["error_type"]) == (403, "AUTHORIZATION_FAILED")
    assert confirms_received(hr_server, checkpoint["execution_id"]) == 0
    code, result = confirm(api, checkpoint, token="dev-reviewer-token")
    assert (code, result["status"]) == (200, "CONFIRMED")


# --- the status source itself failing ------------------------------------------

def test_status_lookup_with_the_hr_api_down_stays_unknown(api, tmp_path, monkeypatch):
    db = tmp_path / "hr.db"
    with hr.running_hr_server(db) as own:
        monkeypatch.setattr(_module, "HR_API_BASE_URL", own.base_url)
        port = own.server_address[1]
        _, checkpoint = prepare(api, "CONFIRM_RESPONSE_LOST")
        confirm(api, checkpoint)
    eid = checkpoint["execution_id"]
    code, view = status(api, eid)                       # the HR API is down
    assert code == 200
    assert (view["status"], view["resolved_from_unknown"]) == ("UNKNOWN", False)
    assert view["target"]["lookup_error"] == "INTEGRATION_UNAVAILABLE"
    with hr.running_hr_server(db, port=port) as back:  # it comes back, same file
        _, view = status(api, eid)
        assert (view["status"], view["resolved_from_unknown"]) == ("CONFIRMED", True)
        assert confirms_received(back, eid) == 1


# --- restarts of the automation API ------------------------------------------

def test_a_restarted_automation_api_resolves_from_durable_state(api, hr_server, tmp_path,
                                                                 monkeypatch):
    exec_db = tmp_path / "executions.db"

    def fresh_process():
        return Orchestrator(repo=SQLiteExecutionRepository(exec_db), audit=_module.AUDIT,
                            resolvers={MODE_HTTP: _module._http_status_resolver})

    monkeypatch.setattr(_module, "ORCH", fresh_process())
    _, checkpoint = prepare(api, "CONFIRM_RESPONSE_LOST")
    code, _ = confirm(api, checkpoint)
    assert code == 202
    # Restart: a new orchestrator with no live adapter and no checkpoints -- only files.
    monkeypatch.setattr(_module, "ORCH", fresh_process())
    monkeypatch.setattr(_module, "_CHECKPOINTS", {})
    code, view = status(api, checkpoint["execution_id"])
    assert code == 200
    assert (view["status"], view["resolved_from_unknown"]) == ("CONFIRMED", True)


def test_an_in_memory_automation_api_forgets_the_execution_after_a_restart(api, hr_server,
                                                                            monkeypatch):
    def fresh_process():
        return Orchestrator(repo=InMemoryExecutionRepository(), audit=_module.AUDIT,
                            resolvers={MODE_HTTP: _module._http_status_resolver})

    monkeypatch.setattr(_module, "ORCH", fresh_process())
    _, checkpoint = prepare(api, "CONFIRM_RESPONSE_LOST")
    confirm(api, checkpoint)
    monkeypatch.setattr(_module, "ORCH", fresh_process())
    code, payload = status(api, checkpoint["execution_id"])
    assert (code, payload["error_type"]) == (404, "TARGET_NOT_FOUND")
    # The HR system still knows -- but only if asked directly with the kept id.
    code, direct = hr.http_json(hr_server.base_url, "GET",
                                f"/api/hr/executions/{checkpoint['execution_id']}/status")
    assert (code, direct["confirmation_state"]) == (200, hr.CONFIRMED)


# --- audit and redaction ----------------------------------------------------------

def test_the_audit_trail_covers_the_whole_http_execution(api):
    _, checkpoint = prepare(api)
    confirm(api, checkpoint)
    status(api, checkpoint["execution_id"])
    _, payload = api("GET", "/api/audit", token="dev-admin-token")
    events = [e for e in payload["events"] if e["execution_id"] == checkpoint["execution_id"]]
    assert [e["action"] for e in events] == [
        "hr_api.list_routes", "hr_api.get_record", "hr_api.get_record", "hr_api.set_note",
        "hr_api.get_record", "prepare", "hr_api.get_record", "hr_api.confirm", "confirm",
        "hr_api.get_status"]
    for e in events:
        assert e["request_id"] and e["timestamp"] and e["result"] == "success"
        assert e["route"] == ROUTE


def test_no_note_text_or_credential_reaches_a_status_or_audit_payload(api, hr_server):
    _, checkpoint = prepare(api, note=SECRET_NOTE)
    confirm(api, checkpoint)
    _, view = status(api, checkpoint["execution_id"])
    _, audit = api("GET", "/api/audit", token="dev-admin-token")
    blob = json.dumps(view) + json.dumps(audit)
    for leak in (SECRET_NOTE, hr.configured_token(), "dev-admin-token", "Bearer"):
        assert leak not in blob, leak
    assert view["note_length"] == len(SECRET_NOTE)
    assert SECRET_NOTE.encode() not in Path(hr_server.store.path).read_bytes()


# --- separate processes: the committed demo --------------------------------------

def test_the_multi_process_demo_reproduces_its_committed_artifact(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "run_http_integration_demo", _REPO_ROOT / "scripts" / "run_http_integration_demo.py")
    demo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(demo)
    assert demo.main(["--out", str(tmp_path)]) == 0
    produced = (tmp_path / "http_integration_demo.json").read_text(encoding="utf-8")
    committed = (_REPO_ROOT / "reports" / "day6" / "http_integration_demo.json").read_text(
        encoding="utf-8")
    assert produced == committed, "the demo is deterministic and its artifact is current"

    result = json.loads(produced)
    steps = {s["step"]: s for s in result["scenario_a_confirmed_path"]["steps"]}
    assert steps["confirm (POST /api/confirm)"]["status"] == "CONFIRMED"
    assert steps["SQLite records the execution"]["commit_count"] == 1
    lost = result["scenario_b_lost_response"]
    assert lost["confirm"]["status"] == "UNKNOWN"
    assert lost["status_lookup"]["status"] == "CONFIRMED"
    assert lost["retry_sent"] is False
    restart = result["scenario_c_restart_with_durable_state"]
    assert restart["first_lookup_after_restart"]["status"] == "CONFIRMED"
    forgot = result["scenario_d_restart_without_durable_state"]
    assert forgot["automation_api_lookup_after_restart"]["http_status"] == 404
    assert forgot["direct_hr_lookup_with_the_kept_id"]["confirmation_state"] == "CONFIRMED"
    assert result["security"] == {**result["security"], "note_text_found": False,
                                  "credential_found": False,
                                  "authorization_header_found": False}
