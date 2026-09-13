from __future__ import annotations

import pytest

from procmine.automation.mock_hr_app import MockElement, MockHRApplication, RouteConfig, render_demo_html
from procmine.process_discovery.dom_evidence import KNOWN_ROUTE_PREFIXES


def test_default_app_supports_all_four_evidenced_routes():
    app = MockHRApplication()
    for route in KNOWN_ROUTE_PREFIXES:
        app.navigate(route)
        assert app.current_route == route


def test_navigate_to_known_route_sets_current_route():
    app = MockHRApplication()
    app.navigate("#/payroll-items")
    assert app.current_route == "#/payroll-items"


def test_navigate_to_unknown_route_raises_key_error():
    app = MockHRApplication()
    with pytest.raises(KeyError):
        app.navigate("#/does-not-exist")


def test_default_note_field_matches_evidenced_id_pattern():
    app = MockHRApplication()
    app.navigate("#/onboarding")
    fields = app.find_note_field()
    assert len(fields) == 1
    assert fields[0].element_id == "ob-note"


def test_default_confirm_button_matches_evidenced_id_pattern():
    app = MockHRApplication()
    app.navigate("#/social-insurance")
    buttons = app.find_confirm_button()
    assert len(buttons) == 1
    assert buttons[0].element_id == "btn-si-ok"


def test_find_note_field_before_navigating_raises():
    app = MockHRApplication()
    with pytest.raises(RuntimeError):
        app.find_note_field()


def test_set_note_value_updates_the_field():
    app = MockHRApplication()
    app.navigate("#/leave-applications")
    app.set_note_value("la-note", "test note")
    assert app.find_note_field()[0].value == "test note"


def test_click_marks_the_button_clicked():
    app = MockHRApplication()
    app.navigate("#/payroll-items")
    app.click("btn-pi-ok")
    assert app.find_confirm_button()[0].clicked is True


def test_click_unknown_element_id_raises_key_error():
    app = MockHRApplication()
    app.navigate("#/payroll-items")
    with pytest.raises(KeyError):
        app.click("btn-does-not-exist")


# --- fault injection ---------------------------------------------------

def test_missing_note_field_injection():
    configs = {"#/payroll-items": RouteConfig(route="#/payroll-items", note_elements=[])}
    app = MockHRApplication(route_configs=configs)
    app.navigate("#/payroll-items")
    assert app.find_note_field() == []


def test_missing_confirm_button_injection():
    configs = {"#/payroll-items": RouteConfig(route="#/payroll-items", confirm_elements=[])}
    app = MockHRApplication(route_configs=configs)
    app.navigate("#/payroll-items")
    assert app.find_confirm_button() == []


def test_duplicate_note_field_injection():
    dup = [MockElement("pi-note", "textarea", "input"), MockElement("pi-note", "textarea", "input")]
    configs = {"#/payroll-items": RouteConfig(route="#/payroll-items", note_elements=dup)}
    app = MockHRApplication(route_configs=configs)
    app.navigate("#/payroll-items")
    assert len(app.find_note_field()) == 2


def test_partial_override_keeps_the_other_side_at_its_default():
    # regression test for a real bug caught before shipping: using
    # empty-list truthiness to mean "not specified" would have silently
    # wiped out the confirm button too when only note_elements was
    # overridden with an intentional [] (or vice versa).
    configs = {"#/payroll-items": RouteConfig(route="#/payroll-items", note_elements=[])}
    app = MockHRApplication(route_configs=configs)
    app.navigate("#/payroll-items")
    assert app.find_note_field() == []
    assert len(app.find_confirm_button()) == 1
    assert app.find_confirm_button()[0].element_id == "btn-pi-ok"


def test_navigation_failure_injection():
    configs = {"#/payroll-items": RouteConfig(route="#/payroll-items", navigation_fails=True)}
    app = MockHRApplication(route_configs=configs)
    with pytest.raises(RuntimeError):
        app.navigate("#/payroll-items")
    assert app.current_route is None


def test_wrong_element_id_simulates_dom_structure_difference():
    wrong = [MockElement("unexpected-id", "textarea", "input")]
    configs = {"#/payroll-items": RouteConfig(route="#/payroll-items", note_elements=wrong)}
    app = MockHRApplication(route_configs=configs)
    app.navigate("#/payroll-items")
    assert app.find_note_field()[0].element_id == "unexpected-id"


# --- demo HTML rendering -------------------------------------------------

def test_render_demo_html_labels_itself_as_a_prototype():
    html = render_demo_html()
    assert "PROTOTYPE" in html or "DEMO" in html


def test_render_demo_html_contains_all_route_ids():
    html = render_demo_html()
    for prefix in KNOWN_ROUTE_PREFIXES.values():
        assert f"{prefix}-note" in html
        assert f"btn-{prefix}-ok" in html


def test_render_demo_html_is_well_formed_enough_to_have_a_title():
    html = render_demo_html()
    assert "<title>" in html and "</html>" in html
