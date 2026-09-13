from __future__ import annotations

from procmine.process_discovery.dom_evidence import (
    click_context_route,
    click_target,
    form_field_info,
    navigation_route_change,
    url_route,
)


def test_url_route_extracts_hash_fragment():
    assert url_route("http://127.0.0.1:5132/#/payroll-items") == "#/payroll-items"


def test_url_route_none_for_bare_root():
    assert url_route("http://127.0.0.1:5132/") is None


def test_url_route_none_for_missing_url():
    assert url_route(None) is None
    assert url_route("") is None


def test_click_target_extracts_id_and_class():
    raw = {"payload": {"element": {"attributes": {"id": "btn-pi-ok", "class": "btn success"}}}}
    assert click_target(raw) == {"id": "btn-pi-ok", "class": "btn success"}


def test_click_target_none_when_no_element_payload():
    raw = {"payload": {}}
    assert click_target(raw) is None


def test_click_target_none_when_attributes_are_all_null():
    raw = {"payload": {"element": {"attributes": {"id": None, "class": None}}}}
    assert click_target(raw) is None


def test_click_target_keeps_id_when_class_missing():
    raw = {"payload": {"element": {"attributes": {"id": "main"}}}}
    assert click_target(raw) == {"id": "main", "class": None}


def test_click_context_route_reads_active_browser_tab():
    raw = {"context": {"active_browser_tab": {"url": "http://127.0.0.1:5132/#/onboarding"}}}
    assert click_context_route(raw) == "#/onboarding"


def test_click_context_route_none_without_tab():
    assert click_context_route({"context": {}}) is None


def test_form_field_info_extracts_expected_fields():
    raw = {
        "payload": {
            "field": {"id": "pi-note", "label": "note label", "input_type": "textarea"},
            "input_method": "paste", "url": "http://127.0.0.1:5132/#/payroll-items", "value": None,
        }
    }
    info = form_field_info(raw)
    assert info == {
        "id": "pi-note", "label": "note label", "input_type": "textarea",
        "input_method": "paste", "url_route": "#/payroll-items",
    }


def test_form_field_info_none_without_field():
    assert form_field_info({"payload": {}}) is None


def test_navigation_route_change_extracts_from_and_to():
    raw = {"payload": {
        "previous_url": "http://127.0.0.1:5132/#/payroll-items",
        "url": "http://127.0.0.1:5132/#/onboarding",
        "navigation_type": "spa_popstate",
    }}
    assert navigation_route_change(raw) == {"from": "#/payroll-items", "to": "#/onboarding", "navigation_type": "spa_popstate"}


def test_navigation_route_change_none_when_both_missing():
    assert navigation_route_change({"payload": {}}) is None
