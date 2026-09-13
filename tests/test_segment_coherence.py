"""Focused tests for the new segment-level coherence forensics module
(`segment_coherence.py`, used only by
`scripts/analyze_segment_coherence_forensics.py`; not wired into
`reconstruction.py` or `protected_boundary.py`)."""

from __future__ import annotations

import pytest

from procmine.segmentation.canonical import CanonicalEvent
from procmine.segmentation.segment_coherence import (
    compute_segment_coherence_evidence,
    segment_index_bounds,
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


# --- segment_index_bounds -------------------------------------------------

def test_segment_index_bounds_no_boundaries_is_one_segment():
    assert segment_index_bounds(5, [False, False, False, False]) == [(0, 4)]


def test_segment_index_bounds_splits_at_every_true():
    # 6 events, transitions at indices 0..4; boundary at transition 1 and 3
    assert segment_index_bounds(6, [False, True, False, True, False]) == [(0, 1), (2, 3), (4, 5)]


def test_segment_index_bounds_boundary_at_first_and_last_transition():
    assert segment_index_bounds(4, [True, False, True]) == [(0, 0), (1, 2), (3, 3)]


def test_segment_index_bounds_empty_session():
    assert segment_index_bounds(0, []) == []


def test_segment_index_bounds_single_event_session():
    assert segment_index_bounds(1, []) == [(0, 0)]


def test_segment_index_bounds_wrong_length_raises():
    with pytest.raises(ValueError):
        segment_index_bounds(5, [False, True])  # should be 4 entries, not 2


# --- compute_segment_coherence_evidence -----------------------------------

def test_identical_event_types_both_sides_gives_high_jaccard_and_rate_continuity():
    # left segment: 4 mouse_click events 0..3000ms; right segment: 4 mouse_click
    # events 4000..7000ms. Same event type both sides, same rate -> should look
    # like a coherent, mergeable trajectory.
    events = [_event(i, event_type="mouse_click", ts=i * 1000) for i in range(8)]
    final_boundary = [False, False, False, True, False, False, False]
    ev = compute_segment_coherence_evidence(events, final_boundary, index_i=3)
    assert ev.left_n_events == 4
    assert ev.right_n_events == 4
    assert ev.segment_event_type_jaccard == 1.0
    assert ev.rate_continuity_ratio == pytest.approx(1.0)


def test_disjoint_event_types_gives_zero_jaccard():
    left = [_event(i, event_type="mouse_click", ts=i * 1000) for i in range(3)]
    right = [_event(i, event_type="keystroke", ts=(i + 3) * 1000) for i in range(3)]
    events = left + right
    final_boundary = [False, False, True, False, False]
    ev = compute_segment_coherence_evidence(events, final_boundary, index_i=2)
    assert ev.segment_event_type_jaccard == 0.0


def test_very_different_activity_rate_gives_low_rate_continuity_ratio():
    # left: 5 events packed into 100ms (dense); right: 5 events spread over
    # 100000ms (sparse) -- should register as a rate mismatch even if the
    # event types are identical.
    left = [_event(i, event_type="mouse_click", ts=i * 20) for i in range(5)]
    right = [_event(i + 5, event_type="mouse_click", ts=100 + i * 20000) for i in range(5)]
    events = left + right
    final_boundary = [False, False, False, False, True, False, False, False, False]
    ev = compute_segment_coherence_evidence(events, final_boundary, index_i=4)
    assert ev.rate_continuity_ratio is not None
    assert ev.rate_continuity_ratio < 0.05


def test_min_segment_n_events_flags_a_thin_fragment():
    # left segment is a single isolated event; right segment has 5.
    left = [_event(0, ts=0)]
    right = [_event(i + 1, ts=(i + 1) * 1000) for i in range(5)]
    events = left + right
    final_boundary = [True, False, False, False, False]
    ev = compute_segment_coherence_evidence(events, final_boundary, index_i=0)
    assert ev.left_n_events == 1
    assert ev.min_segment_n_events == 1


def test_zero_duration_segment_gives_none_rate_not_zero():
    # two events at the exact same timestamp -> duration_ms == 0, so rate
    # must be None (no evidence), never treated as a literal zero rate.
    events = [_event(0, ts=1000), _event(1, ts=1000), _event(2, ts=5000)]
    final_boundary = [True, False]
    ev = compute_segment_coherence_evidence(events, final_boundary, index_i=0)
    assert ev.left_duration_ms == 0
    assert ev.left_event_rate_per_s is None
    assert ev.rate_continuity_ratio is None


def test_precomputed_segment_bounds_gives_same_result_as_recomputing():
    from procmine.segmentation.segment_coherence import segment_index_bounds

    events = [_event(i, ts=i * 1000) for i in range(6)]
    final_boundary = [False, True, False, False, True]
    bounds = segment_index_bounds(len(events), final_boundary)
    a = compute_segment_coherence_evidence(events, final_boundary, index_i=1)
    b = compute_segment_coherence_evidence(events, final_boundary, index_i=1, segment_bounds=bounds)
    assert a == b


def test_index_not_a_final_boundary_raises():
    events = [_event(i, ts=i * 1000) for i in range(4)]
    final_boundary = [False, False, False]
    with pytest.raises(ValueError):
        compute_segment_coherence_evidence(events, final_boundary, index_i=1)


def test_evidence_is_deterministic():
    events = [_event(i, event_type=("mouse_click" if i % 2 == 0 else "keystroke"), ts=i * 500) for i in range(10)]
    final_boundary = [False] * 4 + [True] + [False] * 4
    a = compute_segment_coherence_evidence(events, final_boundary, index_i=4)
    b = compute_segment_coherence_evidence(events, final_boundary, index_i=4)
    assert a == b
