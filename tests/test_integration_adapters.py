"""Integration adapters and the interface that inverts the dependency (Day-5).

THE CLAIM UNDER TEST
--------------------
`procmine.automation.hr_payroll_automation` depends on the `HRApplication`
protocol, not on any concrete target. If that is true, the *unchanged* automation
service can drive an in-memory mock, a browser, or an HTTP-shaped service — and no
adapter contains a copy of the safety rules.

That claim was previously an assertion in a report. These tests make it structural:
one of them drives the real service against the REST adapter end to end, and another
reads the adapter sources and fails if policy has leaked into them.

Every target here is LOCAL. Nothing contacts a real HR system.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from procmine.automation.hr_payroll_automation import (
    UnknownRouteError, confirm_submission, prepare_note_submission,
)
from procmine.automation.mock_hr_app import MockHRApplication
from procmine.integrations.api_hr_application import ApiHRApplication
from procmine.integrations.hr_api_simulator import (
    CONFLICT, DUPLICATE_REQUEST, FORBIDDEN, NETWORK_ERROR, NOT_FOUND, RATE_LIMITED,
    SERVER_ERROR, SIMULATOR_TOKEN, SUCCESS, TIMEOUT, UNAUTHORIZED,
    HRApiError, HRApiSimulator,
)
from procmine.integrations.hr_application import HRApplication

VALID_ROUTE = "#/payroll-items"
NOTE = "Reviewed per standard process."
SRC = Path(__file__).resolve().parent.parent / "src" / "procmine"


def _api(mode: str = SUCCESS, **kw) -> tuple[ApiHRApplication, HRApiSimulator]:
    sim = HRApiSimulator(mode=mode, **kw)
    return ApiHRApplication(sim), sim


# --- the interface actually inverts the dependency -------------------------

def test_all_three_adapters_satisfy_the_interface():
    from procmine.automation.browser_adapter import BrowserHRApplication

    # Constructed, not started: this asserts shape, and must not launch a browser.
    for app in (MockHRApplication(), ApiHRApplication(HRApiSimulator()),
                BrowserHRApplication()):
        assert isinstance(app, HRApplication), type(app).__name__


def test_the_automation_service_declares_the_interface_not_a_concrete_target():
    import inspect

    from procmine.automation import hr_payroll_automation as svc

    for fn in (svc.prepare_note_submission, svc.confirm_submission):
        annotation = inspect.signature(fn).parameters["app"].annotation
        assert annotation in ("HRApplication", HRApplication), (fn.__name__, annotation)


def test_the_automation_service_imports_no_transport_library():
    """No Playwright, no HTTP client, no SQLite, no simulator in the service."""
    text = (SRC / "automation" / "hr_payroll_automation.py").read_text(encoding="utf-8")
    for forbidden in ("playwright", "requests", "httpx", "sqlite3", "urllib",
                      "hr_api_simulator"):
        assert forbidden not in text, forbidden


def test_the_unchanged_service_drives_the_rest_adapter_end_to_end():
    """The headline claim: a new target, and not one line of the service changed."""
    app, sim = _api()
    checkpoint = prepare_note_submission(app, VALID_ROUTE, NOTE)
    assert checkpoint.confirmed is False, "prepare must never confirm"
    result = confirm_submission(app, checkpoint)
    assert result.confirmed is True
    assert [c.split(":")[0] for c in sim.calls] == ["open_route", "set_note", "confirm"]


def test_the_same_service_drives_the_mock_to_the_same_outcome():
    app = MockHRApplication()
    result = confirm_submission(app, prepare_note_submission(app, VALID_ROUTE, NOTE))
    assert result.confirmed is True
    assert result.route == VALID_ROUTE


# --- policy lives above the adapters, not inside them ----------------------

@pytest.mark.parametrize("adapter", ["browser_adapter.py", None])
def test_no_adapter_contains_a_copy_of_the_safety_policy(adapter):
    path = (SRC / "automation" / adapter if adapter
            else SRC / "integrations" / "api_hr_application.py")
    text = path.read_text(encoding="utf-8")
    # The refusals belong to the service. An adapter that re-implemented them could
    # drift from it, which is the failure this guards.
    for policy_marker in ("UnknownRouteError", "InvalidNoteError", "not one of the four",
                          "must be non-empty", "awaiting human review"):
        assert policy_marker not in text, f"{path.name} contains policy: {policy_marker}"


def test_policy_refuses_an_invalid_route_before_the_target_is_ever_touched():
    """The strongest form of "adapters hold no policy": the target sees nothing."""
    app, sim = _api()
    with pytest.raises(UnknownRouteError):
        prepare_note_submission(app, "#/not-an-evidenced-route", NOTE)
    assert sim.calls == [], "the service must refuse before any integration call"


def test_policy_refuses_an_empty_note_before_the_target_is_ever_touched():
    app, sim = _api()
    with pytest.raises(Exception):
        prepare_note_submission(app, VALID_ROUTE, "   ")
    assert sim.calls == []


# --- API adapter: the failure modes Rule 4 requires ------------------------

def test_success_mode_completes_and_records_the_note_length_only():
    app, sim = _api()
    prepare_note_submission(app, VALID_ROUTE, NOTE)
    record = sim._records[VALID_ROUTE]
    assert record.note_length == len(NOTE)
    assert not hasattr(record, "note_text")


def test_unauthorized_fails_at_the_first_call_not_at_confirm():
    """A rejected service credential is rejected immediately, as a real one would be."""
    app, sim = _api(UNAUTHORIZED)
    with pytest.raises(RuntimeError) as exc:
        app.navigate(VALID_ROUTE)
    assert "INTEGRATION_UNAUTHORIZED" in str(exc.value)
    assert app.last_error.status == 401


def test_a_wrong_service_token_is_unauthorized():
    app = ApiHRApplication(HRApiSimulator(), token="not-the-service-token")
    with pytest.raises(RuntimeError):
        app.navigate(VALID_ROUTE)
    assert app.last_error.code == "INTEGRATION_UNAUTHORIZED"


def test_forbidden_is_distinct_from_unauthorized():
    app, _ = _api(FORBIDDEN)
    with pytest.raises(RuntimeError):
        app.navigate(VALID_ROUTE)
    assert app.last_error.code == "INTEGRATION_FORBIDDEN"
    assert app.last_error.status == 403


def test_not_found_surfaces_as_target_not_found():
    app, _ = _api(NOT_FOUND, fail_stage="open")
    with pytest.raises(RuntimeError):
        app.navigate(VALID_ROUTE)
    assert app.last_error.code == "TARGET_NOT_FOUND"


def test_an_unknown_route_is_not_found_at_the_target_too():
    app, _ = _api()
    with pytest.raises(RuntimeError):
        app.navigate("#/no-such-route")
    assert app.last_error.code == "TARGET_NOT_FOUND"


@pytest.mark.parametrize("mode,code,status", [
    (CONFLICT, "INTEGRATION_CONFLICT", 409),
    (RATE_LIMITED, "RATE_LIMITED", 429),
    (SERVER_ERROR, "INTEGRATION_SERVER_ERROR", 500),
    (TIMEOUT, "INTEGRATION_TIMEOUT", 504),
    (NETWORK_ERROR, "INTEGRATION_UNAVAILABLE", 503),
])
def test_confirm_stage_failures_map_to_stable_codes(mode, code, status):
    app, _ = _api(mode)
    checkpoint = prepare_note_submission(app, VALID_ROUTE, NOTE)
    with pytest.raises(Exception):
        confirm_submission(app, checkpoint)
    assert app.last_error.code == code
    assert app.last_error.status == status


def test_duplicate_request_is_reported_as_a_business_duplicate():
    """A *different* request trying to confirm an already-confirmed record."""
    app, _ = _api(DUPLICATE_REQUEST)
    checkpoint = prepare_note_submission(app, VALID_ROUTE, NOTE)
    with pytest.raises(Exception):
        confirm_submission(app, checkpoint)
    assert app.last_error.code == "DUPLICATE_REQUEST"
    assert app.last_error.status == 409


def test_a_failure_mode_does_not_break_navigation_by_default():
    """Otherwise the human review checkpoint could never be reached to fail after."""
    app, sim = _api(TIMEOUT)
    checkpoint = prepare_note_submission(app, VALID_ROUTE, NOTE)
    assert checkpoint.confirm_button_id == "btn-pi-ok"
    assert "confirm:" not in " ".join(sim.calls), "prepare must not have confirmed"


# --- the unknown outcome --------------------------------------------------

def test_a_plain_timeout_is_a_known_failure_not_an_unknown_one():
    app, _ = _api(TIMEOUT)
    with pytest.raises(Exception):
        confirm_submission(app, prepare_note_submission(app, VALID_ROUTE, NOTE))
    assert app.outcome_is_unknown is False


def test_a_lost_response_after_a_commit_is_an_unknown_outcome():
    app, _ = _api(TIMEOUT, applied_despite_failure=True)
    with pytest.raises(Exception):
        confirm_submission(app, prepare_note_submission(app, VALID_ROUTE, NOTE))
    assert app.outcome_is_unknown is True


def test_status_lookup_reveals_what_actually_happened():
    """The answer to the lost response: ask, never re-submit."""
    app, sim = _api(TIMEOUT, applied_despite_failure=True)
    with pytest.raises(Exception):
        confirm_submission(app, prepare_note_submission(app, VALID_ROUTE, NOTE))
    before = list(sim.calls)
    remote = app.query_remote_status()
    assert remote == {"found": True, "confirmed": True, "route": VALID_ROUTE}
    assert sim.calls == before + ["get_status"], "status lookup must not re-confirm"


def test_status_lookup_is_deliberately_outside_the_interface():
    """Mock and browser targets have no equivalent; the interface must not fake one."""
    assert not hasattr(MockHRApplication(), "query_remote_status")
    assert not hasattr(HRApplication, "query_remote_status")


def test_status_lookup_still_works_when_the_service_is_still_failing():
    """A status endpoint that fails the same way as the operation is useless."""
    app, sim = _api(TIMEOUT, applied_despite_failure=True)
    with pytest.raises(Exception):
        confirm_submission(app, prepare_note_submission(app, VALID_ROUTE, NOTE))
    assert sim.mode == TIMEOUT
    assert app.query_remote_status()["confirmed"] is True


def test_an_unconfirmed_key_reports_not_found_rather_than_guessing():
    sim = HRApiSimulator()
    assert sim.get_status(SIMULATOR_TOKEN, "idem_never_used") == {
        "found": False, "confirmed": False}


# --- idempotency at the transport ----------------------------------------

def test_the_same_idempotency_key_returns_the_first_outcome():
    sim = HRApiSimulator()
    sim.open_route(SIMULATOR_TOKEN, VALID_ROUTE)
    first = sim.confirm(SIMULATOR_TOKEN, VALID_ROUTE, "idem_same")
    second = sim.confirm(SIMULATOR_TOKEN, VALID_ROUTE, "idem_same")
    assert first["idempotent_replay"] is False
    assert second["idempotent_replay"] is True, "a safe repeat must not apply twice"


def test_each_adapter_gets_its_own_idempotency_key():
    a, _ = _api()
    b, _ = _api()
    assert a.idempotency_key != b.idempotency_key


def test_an_explicit_idempotency_key_is_honoured_not_regenerated():
    app = ApiHRApplication(HRApiSimulator(), idempotency_key="idem_supplied")
    assert app.idempotency_key == "idem_supplied"


def test_the_adapter_never_invents_a_key_per_call():
    app, sim = _api()
    key = app.idempotency_key
    confirm_submission(app, prepare_note_submission(app, VALID_ROUTE, NOTE))
    assert app.idempotency_key == key
    assert sim._by_idempotency[key] == VALID_ROUTE


def test_hr_api_error_carries_a_machine_readable_code():
    err = HRApiError("INTEGRATION_TIMEOUT", 504, "upstream timed out",
                     submitted_unknown=True)
    assert (err.code, err.status, err.submitted_unknown) == (
        "INTEGRATION_TIMEOUT", 504, True)
