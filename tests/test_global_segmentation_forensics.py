"""Focused tests for the global-segmentation feasibility study's cost
module (`global_segmentation_forensics.py`). Diagnostic-only -- not
wired into `reconstruction.py` or `protected_boundary.py`."""

from __future__ import annotations

from procmine.segmentation.canonical import CanonicalEvent
from procmine.segmentation.features import extract_transition_features
from procmine.segmentation.global_segmentation_forensics import (
    compute_segment_cost,
    entropy_bits,
    internal_feature_slice,
)


def _event(i, event_type="mouse_click", interaction_category="pointer", app=None, domain=None, ts=None) -> CanonicalEvent:
    from procmine.models import Event

    raw = {
        "event_id": f"e{i}", "session_id": "s1", "timestamp_ms": ts if ts is not None else i * 1000,
        "timestamp_iso": "2026-01-01T00:00:00Z", "layer": "l", "event_type": event_type,
        "correlation": {}, "context": {},
    }
    src = Event.from_dict(raw)
    return CanonicalEvent(
        event_id=f"e{i}", session_id="s1", timestamp_ms=ts if ts is not None else i * 1000,
        event_type=event_type, layer="l", interaction_category=interaction_category,
        application=app, window_title=None, browser_domain=domain, browser_url=None,
        has_extracted_text=False, chunk_id=None, sequence_number=i, source_event=src,
    )


# --- entropy_bits ----------------------------------------------------------

def test_entropy_bits_single_category_is_zero():
    assert entropy_bits([5]) == 0.0


def test_entropy_bits_empty_is_zero():
    assert entropy_bits([]) == 0.0


def test_entropy_bits_two_equal_categories_is_one_bit():
    assert entropy_bits([4, 4]) == 1.0


def test_entropy_bits_more_categories_is_higher():
    assert entropy_bits([1, 1, 1, 1]) > entropy_bits([1, 1])


# --- internal_feature_slice --------------------------------------------------

def test_internal_feature_slice_matches_bounds_convention():
    events = [_event(i, ts=i * 1000) for i in range(6)]
    feats = extract_transition_features(events)  # 5 transitions, indices 0..4
    # segment spanning event indices 1..4 (inclusive) has internal
    # transitions 1, 2, 3 (feats[1:4])
    sliced = internal_feature_slice(feats, 1, 4)
    assert sliced == feats[1:4]
    assert len(sliced) == 3


def test_internal_feature_slice_single_event_segment_is_empty():
    events = [_event(i, ts=i * 1000) for i in range(4)]
    feats = extract_transition_features(events)
    assert internal_feature_slice(feats, 2, 2) == []


# --- compute_segment_cost ---------------------------------------------------

def test_uniform_event_type_segment_has_zero_type_entropy():
    events = [_event(i, event_type="mouse_click", ts=i * 1000) for i in range(5)]
    feats = extract_transition_features(events)
    cost = compute_segment_cost(events, internal_feature_slice(feats, 0, 4))
    assert cost.event_type_entropy_bits == 0.0
    assert cost.n_events == 5
    assert cost.n_internal_transitions == 4


def test_mixed_event_type_segment_has_positive_entropy():
    events = [_event(i, event_type=("mouse_click" if i % 2 == 0 else "keystroke"), ts=i * 1000) for i in range(6)]
    feats = extract_transition_features(events)
    cost = compute_segment_cost(events, internal_feature_slice(feats, 0, 5))
    assert cost.event_type_entropy_bits > 0.0


def test_no_application_changes_gives_zero_context_switch_rate():
    events = [_event(i, app="chrome", ts=i * 1000) for i in range(4)]
    feats = extract_transition_features(events)
    cost = compute_segment_cost(events, internal_feature_slice(feats, 0, 3))
    assert cost.context_switch_rate == 0.0


def test_every_transition_an_application_change_gives_rate_one():
    events = [_event(i, app=("chrome" if i % 2 == 0 else "vscode"), ts=i * 1000) for i in range(4)]
    feats = extract_transition_features(events)
    cost = compute_segment_cost(events, internal_feature_slice(feats, 0, 3))
    assert cost.context_switch_rate == 1.0


def test_single_event_segment_gives_none_switch_rate_not_zero():
    events = [_event(0, ts=0)]
    feats = extract_transition_features(events)  # no transitions at all in the full session
    cost = compute_segment_cost(events, internal_feature_slice(feats, 0, 0))
    assert cost.n_internal_transitions == 0
    assert cost.context_switch_rate is None
    assert cost.temporal_irregularity_cv is None


def test_regular_gaps_give_lower_cv_than_irregular_gaps():
    regular = [_event(i, ts=i * 1000) for i in range(6)]  # constant 1000ms gaps
    irregular_ts = [0, 100, 200, 50000, 50100, 100000]
    irregular = [_event(i, ts=t) for i, t in enumerate(irregular_ts)]

    regular_feats = extract_transition_features(regular)
    irregular_feats = extract_transition_features(irregular)

    regular_cost = compute_segment_cost(regular, internal_feature_slice(regular_feats, 0, 5))
    irregular_cost = compute_segment_cost(irregular, internal_feature_slice(irregular_feats, 0, 5))

    assert regular_cost.temporal_irregularity_cv is not None
    assert irregular_cost.temporal_irregularity_cv is not None
    assert regular_cost.temporal_irregularity_cv < irregular_cost.temporal_irregularity_cv


def test_two_transitions_minimum_for_defined_cv():
    events = [_event(i, ts=i * 1000) for i in range(3)]
    feats = extract_transition_features(events)
    one_transition = compute_segment_cost(events[:2], internal_feature_slice(feats, 0, 1))
    two_transitions = compute_segment_cost(events, internal_feature_slice(feats, 0, 2))
    assert one_transition.temporal_irregularity_cv is None
    assert two_transitions.temporal_irregularity_cv is not None


def test_compute_segment_cost_is_deterministic():
    events = [_event(i, event_type=("mouse_click" if i % 2 == 0 else "keystroke"), app=("a" if i < 3 else "b"), ts=i * 500) for i in range(8)]
    feats = extract_transition_features(events)
    a = compute_segment_cost(events, internal_feature_slice(feats, 0, 7))
    b = compute_segment_cost(events, internal_feature_slice(feats, 0, 7))
    assert a == b
