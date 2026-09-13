from procmine.audit import KNOWN_EVENT_TYPES_BY_LAYER
from procmine.models import Event
from procmine.segmentation.canonical import (
    INTERACTION_CATEGORY_BY_EVENT_TYPE,
    CanonicalEvent,
    interaction_category,
    to_canonical_stream,
)


def _ev(event_type="mouse_click", context=None) -> Event:
    raw = {
        "event_id": "e1",
        "session_id": "s1",
        "timestamp_ms": 1000,
        "timestamp_iso": "2026-01-01T00:00:01.000Z",
        "layer": "L2",
        "event_type": event_type,
        "correlation": {"chunk_id": "c1", "sequence_number": 5},
        "context": context or {},
        "payload": {},
    }
    return Event.from_dict(raw)


def test_every_data_schema_event_type_has_a_category_mapping():
    """Fails loudly if a new event type is ever added to the DATA_SCHEMA
    taxonomy without a corresponding category decision here — matches the
    module docstring's promise, otherwise that promise is just a comment."""
    all_known = {t for types in KNOWN_EVENT_TYPES_BY_LAYER.values() for t in types}
    missing = all_known - set(INTERACTION_CATEGORY_BY_EVENT_TYPE)
    assert missing == set(), f"event types missing a category: {missing}"


def test_unknown_event_type_falls_back_without_raising():
    assert interaction_category("some_future_event_type") == "unknown"


def test_from_event_extracts_window_title_and_application():
    e = _ev(context={"active_app": {"app_name": "Notepad", "window_title": "untitled"}})
    ce = CanonicalEvent.from_event(e)
    assert ce.application == "Notepad"
    assert ce.window_title == "untitled"
    assert ce.interaction_category == "pointer"


def test_from_event_extracts_browser_domain_from_url():
    e = _ev(
        event_type="browser_navigation",
        context={"active_browser_tab": {"url": "http://127.0.0.1:5123/#/social-insurance"}},
    )
    ce = CanonicalEvent.from_event(e)
    assert ce.browser_domain == "127.0.0.1:5123"
    assert ce.browser_url == "http://127.0.0.1:5123/#/social-insurance"
    assert ce.interaction_category == "navigation"


def test_missing_browser_context_is_none_not_empty_string():
    e = _ev(event_type="keystroke")
    ce = CanonicalEvent.from_event(e)
    assert ce.browser_domain is None
    assert ce.browser_url is None
    assert ce.window_title is None
    assert ce.interaction_category == "input"


def test_has_extracted_text_flag():
    with_text = _ev(context={"extracted_text": {"text": "hello"}})
    without_text = _ev(context={})
    assert CanonicalEvent.from_event(with_text).has_extracted_text is True
    assert CanonicalEvent.from_event(without_text).has_extracted_text is False


def test_to_canonical_stream_preserves_order_and_provenance():
    events = [_ev(), _ev()]
    events[0].event_id = "a"
    events[1].event_id = "b"
    stream = to_canonical_stream(events)
    assert [c.event_id for c in stream] == ["a", "b"]
    assert stream[0].source_event is events[0]
