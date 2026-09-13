from procmine.models import Event
from procmine.segmentation.canonical import CanonicalEvent
from procmine.segmentation.context_features import (
    TrajectoryFeatures,
    _hostname_only,
    after_window,
    before_window,
    extract_trajectory_features,
    summarize_window,
)


def _ce(event_id, ts_ms, app=None, event_type="mouse_click", window_title=None,
        url=None, text=None) -> CanonicalEvent:
    raw = {
        "event_id": event_id, "session_id": "s1", "timestamp_ms": ts_ms,
        "timestamp_iso": "2026-01-01T00:00:01.000Z", "layer": "L2", "event_type": event_type,
        "correlation": {},
        "context": {
            "active_app": {"app_name": app, "window_title": window_title} if app or window_title else {},
            **({"active_browser_tab": {"url": url}} if url else {}),
            **({"extracted_text": {"text": text}} if text else {}),
        },
        "payload": {},
    }
    return CanonicalEvent.from_event(Event.from_dict(raw))


def test_before_window_respects_stream_start():
    events = [_ce(f"e{i}", i * 100) for i in range(3)]
    w = before_window(events, index_i=1, n=10)  # asks for 10 but only 2 exist before/at index 1
    assert w.n_events == 2


def test_after_window_respects_stream_end():
    events = [_ce(f"e{i}", i * 100) for i in range(3)]
    w = after_window(events, index_next=1, n=10)
    assert w.n_events == 2  # events at index 1, 2


def test_short_stream_does_not_crash():
    events = [_ce("a", 0)]
    features = extract_trajectory_features(events, index_i=0, n=5)
    assert isinstance(features, TrajectoryFeatures)


def test_empty_window_summary_has_no_crash_and_none_jaccard():
    w = summarize_window([])
    assert w.n_events == 0
    from procmine.segmentation.context_features import _jaccard
    assert _jaccard(w.applications, w.applications) is None


def test_missing_browser_context_gives_none_not_zero():
    events = [_ce("a", 0), _ce("b", 100)]  # no url on either
    f = extract_trajectory_features(events, index_i=0, n=5)
    assert f.browser_domain_jaccard_with_port is None
    assert f.browser_domain_jaccard_host_only is None


def test_missing_window_title_gives_none_not_zero():
    events = [_ce("a", 0), _ce("b", 100)]
    f = extract_trajectory_features(events, index_i=0, n=5)
    assert f.window_title_jaccard is None


def test_missing_extracted_text_is_false_not_none():
    events = [_ce("a", 0), _ce("b", 100)]
    f = extract_trajectory_features(events, index_i=0, n=5)
    assert f.before_has_text is False
    assert f.after_has_text is False


def test_duplicate_consecutive_events_deduped_by_set_semantics():
    # 3 identical app_switch-like events with the same app -- Jaccard is
    # over sets, so duplicates don't inflate or distort the comparison
    before = [_ce("a1", 0, app="Chrome"), _ce("a2", 10, app="Chrome"), _ce("a3", 20, app="Chrome")]
    after = [_ce("b1", 1000, app="Chrome")]
    events = before + after
    f = extract_trajectory_features(events, index_i=2, n=5)
    assert f.application_jaccard == 1.0  # {"Chrome"} vs {"Chrome"} despite 3 duplicate-looking events


def test_hostname_only_strips_port():
    assert _hostname_only("http://127.0.0.1:5123/#/page") == "127.0.0.1"
    assert _hostname_only(None) is None
    assert _hostname_only("not a url at all") is None


def test_trajectory_features_expose_no_gt_metadata():
    events = [_ce("a", 0), _ce("b", 100)]
    f = extract_trajectory_features(events, index_i=0, n=5)
    forbidden = {"process_code", "case_id", "process_variant", "is_boundary", "continuity_label"}
    assert forbidden.isdisjoint(set(f.to_dict().keys()))


def test_application_trajectory_detects_resumed_same_app_after_different_middle():
    # Excel -> (gap, unrelated Chrome activity in between not included in
    # either window) -> Excel again: the two windows should show overlap
    before = [_ce("a1", 0, app="Excel"), _ce("a2", 10, app="Excel")]
    after = [_ce("a3", 100_000, app="Excel"), _ce("a4", 100_010, app="Excel")]
    events = before + after
    f = extract_trajectory_features(events, index_i=1, n=5)
    assert f.application_jaccard == 1.0


def test_application_trajectory_detects_genuine_change():
    before = [_ce("a1", 0, app="Excel")]
    after = [_ce("a2", 1000, app="Chrome")]
    events = before + after
    f = extract_trajectory_features(events, index_i=0, n=5)
    assert f.application_jaccard == 0.0
