"""The Day-5 API integration boundary (`scripts/serve_hr_demo_api.py`).

`test_hr_demo_api.py` covers the original contract and must keep passing unchanged.
This file covers what the integration upgrade added: execution identity and status,
the lost-response path, the authentication/authorisation boundary, the CORS
allowlist, integration-mode selection and metrics.

A real server is started on an ephemeral port so the handler is exercised end to end,
including status codes and response headers.

Every target reachable from here is LOCAL. No test contacts a real HR system.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "serve_hr_demo_api.py"
_spec = importlib.util.spec_from_file_location("serve_hr_demo_api_integration", _SCRIPT)
_module = importlib.util.module_from_spec(_spec)
sys.modules["serve_hr_demo_api_integration"] = _module
_spec.loader.exec_module(_module)

VALID_ROUTE = "#/payroll-items"
NOTE = "Reviewed per standard process."


@pytest.fixture(scope="module")
def api():
    server = _module.build_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def call(method: str, path: str, body: dict | None = None, *,
             token: str | None = None, origin: str | None = None):
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if origin:
            headers["Origin"] = origin
        req = urllib.request.Request(base + path, data=data, method=method,
                                     headers=headers)
        try:
            with urllib.request.urlopen(req) as resp:
                # A 204 preflight carries no body, so an empty read is expected
                # rather than a failure.
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else {}), dict(resp.headers)
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                return exc.code, json.loads(raw), dict(exc.headers)
            except json.JSONDecodeError:
                return exc.code, {}, dict(exc.headers)

    yield call
    server.shutdown()
    server.server_close()


def _prepare(api, **over):
    body = {"route": VALID_ROUTE, "note_text": NOTE}
    body.update(over)
    return api("POST", "/api/prepare", body)


def _confirm(api, checkpoint, **kw):
    return api("POST", "/api/confirm",
               {"checkpoint_token": checkpoint["checkpoint_token"]}, **kw)


# --- integration modes ----------------------------------------------------

def test_the_selectable_targets_are_advertised(api):
    status, payload, _ = api("GET", "/api/integration-modes")
    assert status == 200
    # `http` joined in the final extension: real HTTP to the LOCAL HR API simulator.
    assert {m["id"] for m in payload["modes"]} == {"mock", "browser", "api_simulator", "http"}
    assert payload["default"] == "mock"


def test_every_advertised_target_is_labelled_local(api):
    """The UI must never be able to imply a real HR system is reachable."""
    _, payload, _ = api("GET", "/api/integration-modes")
    for mode in payload["modes"]:
        assert mode["label"].startswith("LOCAL"), mode
    assert "No real HR system" in payload["note"]


def test_an_unknown_integration_mode_is_rejected(api):
    status, payload, _ = _prepare(api, integration_mode="real_hr_production")
    assert status == 400
    assert payload["error_type"] == "MALFORMED_REQUEST"


def test_an_unknown_failure_mode_is_rejected(api):
    status, payload, _ = _prepare(api, integration_mode="api_simulator",
                                  failure_mode="EXPLODE")
    assert status == 400
    assert payload["error_type"] == "MALFORMED_REQUEST"


def test_the_default_target_stays_the_mock(api):
    _, checkpoint, _ = _prepare(api)
    assert checkpoint["integration_mode"] == "mock"


def test_a_target_that_cannot_start_is_a_503_not_a_crash(api, monkeypatch):
    def unavailable(*_args, **_kw):
        raise _module.IntegrationUnavailable("browser target unavailable: no browser")

    monkeypatch.setattr(_module, "_build_adapter", unavailable)
    status, payload, _ = _prepare(api, integration_mode="browser")
    assert status == 503
    assert payload["error_type"] == "INTEGRATION_UNAVAILABLE"


# --- execution identity and status ---------------------------------------

def test_prepare_issues_an_execution_id_and_a_status(api):
    status, checkpoint, _ = _prepare(api)
    assert status == 200
    assert checkpoint["execution_id"].startswith("exec_")
    assert checkpoint["status"] == "AWAITING_CONFIRMATION"
    assert checkpoint["confirmed"] is False


def test_the_execution_status_can_be_queried_after_confirmation(api):
    _, checkpoint, _ = _prepare(api)
    _confirm(api, checkpoint)
    status, payload, _ = api(
        "GET", f"/api/executions/{checkpoint['execution_id']}/status")
    assert status == 200
    assert payload["status"] == "CONFIRMED"
    assert payload["terminal"] is True


def test_the_status_payload_reports_the_integration_mode(api):
    _, checkpoint, _ = _prepare(api, integration_mode="api_simulator")
    _, payload, _ = api("GET", f"/api/executions/{checkpoint['execution_id']}/status")
    assert payload["integration_mode"] == "api_simulator"


def test_the_status_of_an_unissued_execution_is_404(api):
    status, payload, _ = api("GET", "/api/executions/exec_never_issued/status")
    assert status == 404
    assert payload["error_type"] == "TARGET_NOT_FOUND"


def test_the_status_history_shows_how_the_execution_got_there(api):
    _, checkpoint, _ = _prepare(api)
    _confirm(api, checkpoint)
    _, payload, _ = api("GET", f"/api/executions/{checkpoint['execution_id']}/status")
    assert [h["to"] for h in payload["history"]] == [
        "AWAITING_CONFIRMATION", "CONFIRMING", "CONFIRMED"]


# --- the lost-response path: the reason this upgrade exists --------------

def test_a_lost_confirmation_response_returns_202_and_an_unknown_status(api):
    _, checkpoint, _ = _prepare(api, integration_mode="api_simulator",
                                failure_mode="TIMEOUT", lose_response=True)
    status, payload, _ = _confirm(api, checkpoint)
    assert status == 202, "an unknown outcome is not a success and not a failure"
    assert payload["status"] == "UNKNOWN"
    assert payload["error_type"] == "CONFIRMATION_UNKNOWN"
    assert payload["confirmed"] is False


def test_the_unknown_response_tells_the_client_where_to_look(api):
    _, checkpoint, _ = _prepare(api, integration_mode="api_simulator",
                                failure_mode="TIMEOUT", lose_response=True)
    _, payload, _ = _confirm(api, checkpoint)
    assert payload["status_url"] == f"/api/executions/{checkpoint['execution_id']}/status"
    assert "never retried automatically" in payload["message"]


def test_the_status_lookup_resolves_the_unknown_outcome(api):
    _, checkpoint, _ = _prepare(api, integration_mode="api_simulator",
                                failure_mode="TIMEOUT", lose_response=True)
    _confirm(api, checkpoint)
    status, payload, _ = api(
        "GET", f"/api/executions/{checkpoint['execution_id']}/status")
    assert status == 200
    assert payload["status"] == "CONFIRMED"
    assert payload["resolved_from_unknown"] is True


def test_a_resolved_execution_stays_resolved(api):
    _, checkpoint, _ = _prepare(api, integration_mode="api_simulator",
                                failure_mode="TIMEOUT", lose_response=True)
    _confirm(api, checkpoint)
    path = f"/api/executions/{checkpoint['execution_id']}/status"
    api("GET", path)
    _, second, _ = api("GET", path)
    assert second["status"] == "CONFIRMED"
    assert second["resolved_from_unknown"] is False, "already settled, nothing to resolve"


def test_a_clean_integration_failure_is_422_and_stays_failed(api):
    """No commit happened, so the outcome is known. It must not become UNKNOWN."""
    _, checkpoint, _ = _prepare(api, integration_mode="api_simulator",
                                failure_mode="TIMEOUT")
    status, payload, _ = _confirm(api, checkpoint)
    assert status == 422
    assert payload["status"] == "FAILED"
    assert payload["error_type"] == "INTEGRATION_TIMEOUT"

    _, after, _ = api("GET", f"/api/executions/{checkpoint['execution_id']}/status")
    assert after["status"] == "FAILED", "a failure must not be silently retried"


def test_a_consumed_checkpoint_cannot_be_confirmed_again_even_when_unknown(api):
    _, checkpoint, _ = _prepare(api, integration_mode="api_simulator",
                                failure_mode="TIMEOUT", lose_response=True)
    _confirm(api, checkpoint)
    status, payload, _ = _confirm(api, checkpoint)
    assert status == 400
    assert payload["error_type"] == "REPLAYED_REQUEST"


@pytest.mark.parametrize("failure_mode,expected", [
    ("CONFLICT", "INTEGRATION_CONFLICT"),
    ("RATE_LIMITED", "RATE_LIMITED"),
    ("SERVER_ERROR", "INTEGRATION_SERVER_ERROR"),
    ("NETWORK_ERROR", "INTEGRATION_UNAVAILABLE"),
    ("DUPLICATE_REQUEST", "DUPLICATE_REQUEST"),
])
def test_integration_failures_surface_stable_machine_readable_codes(
        api, failure_mode, expected):
    _, checkpoint, _ = _prepare(api, integration_mode="api_simulator",
                                failure_mode=failure_mode)
    status, payload, _ = _confirm(api, checkpoint)
    assert status == 422
    assert payload["error_type"] == expected


def test_a_service_credential_failure_stops_at_prepare(api):
    """A rejected service account fails on first contact, before any review."""
    status, payload, _ = _prepare(api, integration_mode="api_simulator",
                                  failure_mode="UNAUTHORIZED")
    assert status == 422
    assert payload["error_type"] == "INTEGRATION_UNAUTHORIZED"


# --- the authentication / authorisation boundary -------------------------

def test_an_invalid_credential_is_401(api):
    status, payload, _ = api("GET", "/api/metrics", token="not-a-real-token")
    assert status == 401
    assert payload["error_type"] == "AUTHENTICATION_FAILED"


def test_an_operator_may_prepare(api):
    status, _, _ = _prepare(api, )
    assert status == 200
    status, _, _ = api("POST", "/api/prepare",
                       {"route": VALID_ROUTE, "note_text": NOTE},
                       token="dev-operator-token")
    assert status == 200


def test_an_operator_may_not_confirm(api):
    """The human-review checkpoint, enforced as an authorisation rule."""
    _, checkpoint, _ = api("POST", "/api/prepare",
                           {"route": VALID_ROUTE, "note_text": NOTE},
                           token="dev-operator-token")
    status, payload, _ = _confirm(api, checkpoint, token="dev-operator-token")
    assert status == 403
    assert payload["error_type"] == "AUTHORIZATION_FAILED"
    assert payload["required_permission"] == "automation:confirm"


def test_a_reviewer_may_confirm_what_an_operator_prepared(api):
    _, checkpoint, _ = api("POST", "/api/prepare",
                           {"route": VALID_ROUTE, "note_text": NOTE},
                           token="dev-operator-token")
    status, payload, _ = _confirm(api, checkpoint, token="dev-reviewer-token")
    assert status == 200
    assert payload["confirmed"] is True


def test_the_audit_trail_requires_more_than_the_default_principal(api):
    status, _, _ = api("GET", "/api/audit")
    assert status == 403, "the default local principal must not read the audit trail"


def test_an_admin_may_read_the_audit_trail(api):
    status, payload, _ = api("GET", "/api/audit", token="dev-admin-token")
    assert status == 200
    assert isinstance(payload["events"], list)


def test_authentication_can_be_made_mandatory(api, monkeypatch):
    """What a deployment would set. Local default is open for demo convenience."""
    monkeypatch.setattr(_module, "AUTH_REQUIRED", True)
    status, payload, _ = api("GET", "/api/metrics")
    assert status == 401
    assert payload["error_type"] == "AUTHENTICATION_FAILED"
    # a valid credential still works while closed
    assert api("GET", "/api/metrics", token="dev-reviewer-token")[0] == 200


def test_health_stays_open_and_leaks_no_configuration(api):
    status, payload, _ = api("GET", "/health")
    assert status == 200
    assert set(payload) == {"status", "version"}


# --- CORS -----------------------------------------------------------------

def test_an_allowlisted_dev_origin_is_echoed(api):
    _, _, headers = api("GET", "/api/routes", origin="http://localhost:5173")
    assert headers.get("Access-Control-Allow-Origin") == "http://localhost:5173"
    assert headers.get("Vary") == "Origin"


def test_an_unlisted_origin_receives_no_cors_header(api):
    _, _, headers = api("GET", "/api/routes", origin="http://evil.example.com")
    assert "Access-Control-Allow-Origin" not in headers


def test_the_api_never_sends_a_wildcard_origin():
    source = _SCRIPT.read_text(encoding="utf-8")
    assert '"Access-Control-Allow-Origin", "*"' not in source


def test_the_preflight_advertises_the_authorization_header(api):
    _, _, headers = api("OPTIONS", "/api/prepare", origin="http://localhost:5173")
    assert "Authorization" in headers.get("Access-Control-Allow-Headers", "")


# --- observability --------------------------------------------------------

def test_metrics_expose_the_counters_that_matter(api):
    _, checkpoint, _ = _prepare(api)
    _confirm(api, checkpoint)
    status, payload, _ = api("GET", "/api/metrics")
    assert status == 200
    metrics = payload["metrics"]
    assert metrics["automation_requests_total"] > 0
    assert metrics["automation_success_total"] > 0


def test_metrics_are_numbers_only(api):
    _, payload, _ = api("GET", "/api/metrics")
    assert all(isinstance(v, (int, float)) for v in payload["metrics"].values())


def test_an_execution_is_traceable_through_request_and_execution_id(api):
    _, checkpoint, _ = _prepare(api)
    _confirm(api, checkpoint)
    _, payload, _ = api("GET", "/api/metrics")
    traced = [e for e in payload["recent_events"]
              if e.get("execution_id") == checkpoint["execution_id"]]
    assert traced, "the execution left no trace"
    assert {e["event"] for e in traced} >= {"PREPARED", "CONFIRMED"}


# --- security -------------------------------------------------------------

def test_the_note_text_never_reaches_the_audit_trail(api):
    secret = "Confidential March adjustment for employee 4471"
    _prepare(api, note_text=secret)
    _, payload, _ = api("GET", "/api/audit", token="dev-admin-token")
    assert secret not in json.dumps(payload)


def test_the_status_payload_carries_no_note_content(api):
    secret = "Another confidential payroll note"
    _, checkpoint, _ = _prepare(api, note_text=secret)
    _confirm(api, checkpoint)
    _, payload, _ = api("GET", f"/api/executions/{checkpoint['execution_id']}/status")
    assert secret not in json.dumps(payload)
    assert payload["note_length"] == len(secret)


def test_no_credential_appears_in_the_audit_trail(api):
    _, checkpoint, _ = _prepare(api)
    _confirm(api, checkpoint, token="dev-reviewer-token")
    _, payload, _ = api("GET", "/api/audit", token="dev-admin-token")
    blob = json.dumps(payload)
    for leak in ("dev-reviewer-token", "dev-admin-token",
                 checkpoint["checkpoint_token"]):
        assert leak not in blob, leak


def test_an_error_response_exposes_no_internal_traceback(api):
    status, payload, _ = _prepare(api, route="#/not-a-real-route")
    assert status == 422
    blob = json.dumps(payload)
    assert "Traceback" not in blob and "File \"/" not in blob
