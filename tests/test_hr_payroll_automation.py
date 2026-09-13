from __future__ import annotations

import pytest

from procmine.automation.hr_payroll_automation import (
    AutomationSafetyError,
    ConfirmationFailedError,
    DuplicateElementError,
    ElementNotFoundError,
    InvalidNoteError,
    NavigationError,
    UnknownRouteError,
    confirm_submission,
    prepare_note_submission,
)
from procmine.automation.mock_hr_app import MockElement, MockHRApplication, RouteConfig
from procmine.process_discovery.dom_evidence import KNOWN_ROUTE_PREFIXES


# --- happy path, all four routes ------------------------------------------

@pytest.mark.parametrize("route", list(KNOWN_ROUTE_PREFIXES.keys()))
def test_valid_route_prepares_a_checkpoint_without_confirming(route):
    app = MockHRApplication()
    checkpoint = prepare_note_submission(app, route, "test note")
    prefix = KNOWN_ROUTE_PREFIXES[route]
    assert checkpoint.route == route
    assert checkpoint.note_field_id == f"{prefix}-note"
    assert checkpoint.confirm_button_id == f"btn-{prefix}-ok"
    assert checkpoint.confirmed is False
    # human-review boundary: the button must NOT have been clicked yet
    assert app.find_confirm_button()[0].clicked is False


def test_correct_route_navigation():
    app = MockHRApplication()
    prepare_note_submission(app, "#/onboarding", "note")
    assert app.current_route == "#/onboarding"


def test_note_is_actually_inserted():
    app = MockHRApplication()
    prepare_note_submission(app, "#/leave-applications", "please process this")
    assert app.find_note_field()[0].value == "please process this"


def test_action_log_records_every_step():
    app = MockHRApplication()
    checkpoint = prepare_note_submission(app, "#/payroll-items", "note")
    steps = [entry.step for entry in checkpoint.action_log]
    assert steps == [
        "route_check", "note_check", "navigate", "find_note_field",
        "insert_note", "find_confirm_button", "checkpoint",
    ]


# --- human-review checkpoint + confirmation ---------------------------------

def test_confirm_submission_clicks_the_button():
    app = MockHRApplication()
    checkpoint = prepare_note_submission(app, "#/payroll-items", "note")
    result = confirm_submission(app, checkpoint)
    assert result.confirmed is True
    assert app.find_confirm_button()[0].clicked is True


def test_confirm_submission_is_not_reentrant():
    app = MockHRApplication()
    checkpoint = prepare_note_submission(app, "#/payroll-items", "note")
    confirm_submission(app, checkpoint)
    with pytest.raises(RuntimeError):
        confirm_submission(app, checkpoint)


def test_confirm_submission_rejects_a_stale_checkpoint_after_navigating_away():
    app = MockHRApplication()
    checkpoint = prepare_note_submission(app, "#/payroll-items", "note")
    app.navigate("#/onboarding")  # simulate the app moving on before review completes
    with pytest.raises(RuntimeError):
        confirm_submission(app, checkpoint)


def test_confirm_submission_appends_to_the_existing_log_not_a_new_one():
    app = MockHRApplication()
    checkpoint = prepare_note_submission(app, "#/payroll-items", "note")
    n_before = len(checkpoint.action_log)
    result = confirm_submission(app, checkpoint)
    assert len(result.action_log) == n_before + 1
    assert result.action_log[-1].step == "confirm"


# --- safe-failure paths -----------------------------------------------------

def test_unknown_route_is_rejected_before_navigating():
    app = MockHRApplication()
    with pytest.raises(UnknownRouteError):
        prepare_note_submission(app, "#/not-a-real-route", "note")
    assert app.current_route is None  # never even attempted navigation


def test_missing_note_field_stops_the_pipeline():
    configs = {"#/payroll-items": RouteConfig(route="#/payroll-items", note_elements=[])}
    app = MockHRApplication(route_configs=configs)
    with pytest.raises(ElementNotFoundError):
        prepare_note_submission(app, "#/payroll-items", "note")


def test_missing_confirm_button_stops_the_pipeline():
    configs = {"#/payroll-items": RouteConfig(route="#/payroll-items", confirm_elements=[])}
    app = MockHRApplication(route_configs=configs)
    with pytest.raises(ElementNotFoundError):
        prepare_note_submission(app, "#/payroll-items", "note")


def test_duplicate_note_field_stops_the_pipeline():
    dup = [MockElement("pi-note", "textarea", "input"), MockElement("pi-note", "textarea", "input")]
    configs = {"#/payroll-items": RouteConfig(route="#/payroll-items", note_elements=dup)}
    app = MockHRApplication(route_configs=configs)
    with pytest.raises(DuplicateElementError):
        prepare_note_submission(app, "#/payroll-items", "note")


def test_duplicate_confirm_button_stops_the_pipeline():
    dup = [MockElement("btn-pi-ok", "button", "btn success"), MockElement("btn-pi-ok", "button", "btn success")]
    configs = {"#/payroll-items": RouteConfig(route="#/payroll-items", confirm_elements=dup)}
    app = MockHRApplication(route_configs=configs)
    with pytest.raises(DuplicateElementError):
        prepare_note_submission(app, "#/payroll-items", "note")


def test_navigation_failure_stops_the_pipeline():
    configs = {"#/payroll-items": RouteConfig(route="#/payroll-items", navigation_fails=True)}
    app = MockHRApplication(route_configs=configs)
    with pytest.raises(NavigationError):
        prepare_note_submission(app, "#/payroll-items", "note")


def test_unexpected_note_field_id_stops_the_pipeline():
    wrong = [MockElement("some-other-id", "textarea", "input")]
    configs = {"#/payroll-items": RouteConfig(route="#/payroll-items", note_elements=wrong)}
    app = MockHRApplication(route_configs=configs)
    with pytest.raises(ElementNotFoundError):
        prepare_note_submission(app, "#/payroll-items", "note")


def test_every_safety_error_carries_the_partial_action_log():
    app = MockHRApplication()
    with pytest.raises(AutomationSafetyError) as excinfo:
        prepare_note_submission(app, "#/not-a-real-route", "note")
    assert len(excinfo.value.action_log) >= 1
    assert excinfo.value.action_log[0].step == "route_check"


def test_note_is_never_inserted_after_a_missing_confirm_button_failure():
    # a failure downstream of note insertion must not leave the automation
    # pretending the whole thing succeeded -- the note WAS written (that
    # step really happened), but no checkpoint/confirmation is possible.
    configs = {"#/payroll-items": RouteConfig(route="#/payroll-items", confirm_elements=[])}
    app = MockHRApplication(route_configs=configs)
    with pytest.raises(ElementNotFoundError):
        prepare_note_submission(app, "#/payroll-items", "note")
    assert app.find_note_field()[0].value == "note"  # the note step really did run
    assert app.find_confirm_button() == []  # and nothing was clicked, because nothing exists to click


def test_safe_failure_never_raises_a_bare_exception_type():
    # every stop condition raises a *specific*, catchable subclass of
    # AutomationSafetyError -- never a generic Exception the caller
    # would have to guess the meaning of.
    app = MockHRApplication()
    with pytest.raises(AutomationSafetyError):
        prepare_note_submission(app, "#/unknown", "note")


# --- empty/invalid note input -----------------------------------------------

@pytest.mark.parametrize("bad_note", ["", "   ", "\n\t", None])
def test_empty_or_whitespace_note_is_rejected_before_touching_the_ui(bad_note):
    app = MockHRApplication()
    with pytest.raises(InvalidNoteError):
        prepare_note_submission(app, "#/payroll-items", bad_note)
    # rejected before navigation was ever attempted
    assert app.current_route is None


def test_valid_note_with_surrounding_whitespace_is_accepted_verbatim():
    app = MockHRApplication()
    checkpoint = prepare_note_submission(app, "#/payroll-items", "  a real note  ")
    assert checkpoint.note_text == "  a real note  "  # not silently trimmed/altered


# --- confirmation-time failures (DOM changes during human review) ----------

def test_confirmation_fails_if_button_disappears_during_review():
    app = MockHRApplication()
    checkpoint = prepare_note_submission(app, "#/payroll-items", "note")
    # simulate the page changing while the human is reviewing
    app._routes["#/payroll-items"].confirm_elements = []
    with pytest.raises(ConfirmationFailedError):
        confirm_submission(app, checkpoint)
    assert checkpoint.confirmed is False


def test_confirmation_fails_if_a_second_button_appears_during_review():
    from procmine.automation.mock_hr_app import MockElement

    app = MockHRApplication()
    checkpoint = prepare_note_submission(app, "#/payroll-items", "note")
    app._routes["#/payroll-items"].confirm_elements = [
        MockElement("btn-pi-ok", "button", "btn success"),
        MockElement("btn-pi-ok-2", "button", "btn success"),
    ]
    with pytest.raises(ConfirmationFailedError):
        confirm_submission(app, checkpoint)
    assert checkpoint.confirmed is False


def test_confirmation_failure_preserves_the_action_log_up_to_the_failure():
    app = MockHRApplication()
    checkpoint = prepare_note_submission(app, "#/payroll-items", "note")
    n_before = len(checkpoint.action_log)
    app._routes["#/payroll-items"].confirm_elements = []
    with pytest.raises(ConfirmationFailedError) as excinfo:
        confirm_submission(app, checkpoint)
    assert len(excinfo.value.action_log) == n_before + 1
    assert "FAILED" in excinfo.value.action_log[-1].detail
