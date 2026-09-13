from procmine.models import Event
from procmine.segmentation.canonical import CanonicalEvent
from procmine.segmentation.features import extract_transition_features, label_transitions


def _ce(event_id, ts_ms, app="excel", window_title="w", event_type="mouse_click", chunk_id="c1", text=None) -> CanonicalEvent:
    raw = {
        "event_id": event_id,
        "session_id": "s1",
        "timestamp_ms": ts_ms,
        "timestamp_iso": "2026-01-01T00:00:01.000Z",
        "layer": "L2",
        "event_type": event_type,
        "correlation": {"chunk_id": chunk_id},
        "context": {
            "active_app": {"app_name": app, "window_title": window_title},
            **({"extracted_text": {"text": text}} if text else {}),
        },
        "payload": {},
    }
    return CanonicalEvent.from_event(Event.from_dict(raw))


def test_delta_t_and_log_transform():
    events = [_ce("a", 1000), _ce("b", 3500)]
    feats = extract_transition_features(events)
    assert feats[0].delta_t_ms == 2500
    assert feats[0].log1p_delta_t_ms > 0


def test_no_features_for_single_event():
    assert extract_transition_features([_ce("a", 1000)]) == []


def test_application_and_window_title_change_detected():
    events = [_ce("a", 0, app="Excel", window_title="Book1"), _ce("b", 1000, app="Chrome", window_title="Tab1")]
    feats = extract_transition_features(events)
    assert feats[0].application_changed is True
    assert feats[0].window_title_changed is True


def test_no_change_when_context_is_identical():
    events = [_ce("a", 0, app="Excel", window_title="Book1"), _ce("b", 1000, app="Excel", window_title="Book1")]
    feats = extract_transition_features(events)
    assert feats[0].application_changed is False
    assert feats[0].window_title_changed is False


def test_chunk_boundary_detected():
    events = [_ce("a", 0, chunk_id="c1"), _ce("b", 1000, chunk_id="c2")]
    feats = extract_transition_features(events)
    assert feats[0].chunk_boundary is True


def test_extracted_text_at_transition_true_if_either_side_has_it():
    events = [_ce("a", 0, text="hello"), _ce("b", 1000)]
    feats = extract_transition_features(events)
    assert feats[0].extracted_text_at_transition is True


def test_density_counts_events_in_window():
    # 5 events tightly packed, then a lone one far away
    events = [_ce(f"e{i}", i * 100) for i in range(5)] + [_ce("far", 60_000)]
    feats = extract_transition_features(events)
    # transition between the last tightly-packed event and the far one:
    # density_before should see the cluster, density_after should not
    last_transition = feats[-1]
    assert last_transition.density_before >= 4
    assert last_transition.density_after == 1  # just itself


def test_label_transitions_matches_boundary_that_falls_between_events_not_on_one():
    """This is the exact bug class caught during review: a GT boundary
    timestamp that doesn't equal any raw event's timestamp must still be
    correctly attributed to the one transition whose interval contains it."""
    events = [_ce("a", 1000), _ce("b", 5000), _ce("c", 9000)]
    feats = extract_transition_features(events)
    # boundary at 3000ms falls strictly between event "a" (1000) and "b" (5000),
    # not equal to either timestamp
    labeled = label_transitions(feats, [(3000, False)])
    assert labeled[0].is_boundary is True   # the a->b transition
    assert labeled[1].is_boundary is False  # the b->c transition


def test_label_transitions_carries_resume_flag():
    events = [_ce("a", 1000), _ce("b", 5000)]
    feats = extract_transition_features(events)
    labeled = label_transitions(feats, [(3000, True)])
    assert labeled[0].is_resume is True


def test_label_transitions_boundary_outside_any_interval_labels_nothing():
    events = [_ce("a", 1000), _ce("b", 5000)]
    feats = extract_transition_features(events)
    labeled = label_transitions(feats, [(999_999, False)])
    assert all(not lt.is_boundary for lt in labeled)
