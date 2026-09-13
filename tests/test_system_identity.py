from __future__ import annotations

from procmine.segmentation.canonical import CanonicalEvent
from procmine.process_discovery.system_identity import fill_forward, system_identity, system_identity_changed


def _event(i, app=None, domain=None, title=None) -> CanonicalEvent:
    from procmine.models import Event

    raw = {
        "event_id": f"e{i}", "session_id": "s1", "timestamp_ms": i * 1000,
        "timestamp_iso": "2026-01-01T00:00:00Z", "layer": "l", "event_type": "mouse_click",
        "correlation": {}, "context": {},
    }
    src = Event.from_dict(raw)
    return CanonicalEvent(
        event_id=f"e{i}", session_id="s1", timestamp_ms=i * 1000, event_type="mouse_click",
        layer="l", interaction_category="pointer", application=app, window_title=title,
        browser_domain=domain, browser_url=None, has_extracted_text=False,
        chunk_id=None, sequence_number=i, source_event=src,
    )


def test_no_application_gives_none():
    assert system_identity(_event(0, app=None)) is None


def test_recording_agent_is_treated_as_noise():
    assert system_identity(_event(0, app="procmine-desktop-agent")) is None


def test_parallels_control_center_is_treated_as_noise():
    assert system_identity(_event(0, app="prl_cc")) is None


def test_non_browser_application_uses_app_prefix():
    assert system_identity(_event(0, app="Microsoft Word", title="budget_analysis - Word")) == "app:Microsoft Word"


def test_known_system_title_wins_even_without_browser_domain():
    ev = system_identity(_event(0, app="Microsoft Edge", domain=None, title="HR人事給与システム - Profile 1 - Microsoft​ Edge"))
    assert ev == "system:HR人事給与システム"


def test_known_system_title_matches_with_extra_tab_count_suffix():
    ev = system_identity(_event(0, app="Microsoft Edge", domain=None, title="財務会計システム and 2 more pages - Profile 1 - Microsoft​ Edge"))
    assert ev == "system:財務会計システム"


def test_different_named_systems_are_different():
    a = system_identity(_event(0, app="Microsoft Edge", title="HR人事給与システム - Profile 1 - Microsoft​ Edge"))
    b = system_identity(_event(1, app="Microsoft Edge", title="受発注在庫管理システム - Profile 1 - Microsoft​ Edge"))
    assert a != b


def test_browser_chrome_noise_title_gives_none():
    assert system_identity(_event(0, app="Microsoft Edge", title="Restore pages")) is None
    assert system_identity(_event(1, app="Microsoft Edge", title="Turn off extensions in developer mode")) is None
    assert system_identity(_event(2, app="Microsoft Edge", title="Untitled - Profile 1 - Microsoft​ Edge")) is None


def test_browser_domain_used_as_fallback_for_unrecognized_real_site():
    ev = system_identity(_event(0, app="Microsoft Edge", domain="app.slack.com", title="Chat | Slack"))
    assert ev == "browser:app.slack.com"


def test_browser_without_domain_or_known_title_falls_back_to_app_name():
    assert system_identity(_event(0, app="Microsoft Edge", domain=None, title=None)) == "app:Microsoft Edge"


def test_system_identity_changed_detects_real_change():
    assert system_identity_changed("app:Word", "app:Excel") is True


def test_system_identity_changed_same_value_is_false():
    assert system_identity_changed("app:Word", "app:Word") is False


def test_system_identity_changed_none_on_either_side_is_false_not_true():
    assert system_identity_changed(None, "app:Word") is False
    assert system_identity_changed("app:Word", None) is False
    assert system_identity_changed(None, None) is False


def test_fill_forward_carries_previous_value_through_none():
    assert fill_forward(["A", None, None, "B"]) == ["A", "A", "A", "B"]


def test_fill_forward_leading_none_stays_none():
    assert fill_forward([None, None, "A"]) == [None, None, "A"]


def test_fill_forward_no_nones_is_unchanged():
    assert fill_forward(["A", "B", "C"]) == ["A", "B", "C"]


def test_fill_forward_all_none_stays_all_none():
    assert fill_forward([None, None]) == [None, None]
