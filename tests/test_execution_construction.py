from __future__ import annotations

import pytest

from procmine.segmentation.canonical import CanonicalEvent
from procmine.process_discovery.boundaries import system_change_boundaries
from procmine.process_discovery.execution_construction import (
    Execution,
    build_executions,
    merge_leave_and_return,
)


def _event(i, app=None, title=None, category="pointer", ts=None) -> CanonicalEvent:
    from procmine.models import Event

    raw = {
        "event_id": f"e{i}", "session_id": "s1", "timestamp_ms": ts if ts is not None else i * 1000,
        "timestamp_iso": "2026-01-01T00:00:00Z", "layer": "l", "event_type": "mouse_click",
        "correlation": {}, "context": {},
    }
    src = Event.from_dict(raw)
    return CanonicalEvent(
        event_id=f"e{i}", session_id="s1", timestamp_ms=ts if ts is not None else i * 1000,
        event_type="mouse_click", layer="l", interaction_category=category,
        application=app, window_title=title, browser_domain=None, browser_url=None,
        has_extracted_text=False, chunk_id=None, sequence_number=i, source_event=src,
    )


# --- merge_leave_and_return --------------------------------------------------

def test_short_immediate_detour_is_merged():
    # A (3 events), brief detour to B (2 events), back to A (3 events)
    events = (
        [_event(i, app="A", ts=i * 100) for i in range(3)]
        + [_event(i, app="B", ts=i * 100) for i in range(3, 5)]
        + [_event(i, app="A", ts=i * 100) for i in range(5, 8)]
    )
    boundary = system_change_boundaries(events)
    assert boundary == [False, False, True, False, True, False, False]  # both edges are candidates
    merged = merge_leave_and_return(events, boundary, max_away_events=2)
    assert merged == [False] * 7  # both edges demoted -- the detour is absorbed


def test_long_immediate_detour_is_not_merged():
    events = (
        [_event(i, app="A", ts=i * 100) for i in range(3)]
        + [_event(i, app="B", ts=i * 100) for i in range(3, 9)]  # 6-event detour
        + [_event(i, app="A", ts=i * 100) for i in range(9, 12)]
    )
    boundary = system_change_boundaries(events)
    merged = merge_leave_and_return(events, boundary, max_away_events=2)
    assert merged == boundary  # detour too long relative to the threshold -- left alone


def test_merge_never_adds_a_boundary():
    events = [_event(i, app="A", ts=i * 100) for i in range(5)]
    boundary = system_change_boundaries(events)  # all False, no candidates at all
    merged = merge_leave_and_return(events, boundary, max_away_events=10)
    assert merged == boundary
    assert not any(merged)


def test_merge_wrong_length_raises():
    events = [_event(i, ts=i * 100) for i in range(4)]
    with pytest.raises(ValueError):
        merge_leave_and_return(events, [True, False], max_away_events=5)  # should be 3 entries


# --- build_executions ---------------------------------------------------------

def test_build_executions_splits_into_expected_segments():
    events = (
        [_event(i, app="A", ts=i * 1000) for i in range(3)]
        + [_event(i, app="B", ts=i * 1000) for i in range(3, 6)]
    )
    boundary = system_change_boundaries(events)
    execs = build_executions("s1", "op1", events, boundary)
    assert len(execs) == 2
    assert execs[0].event_count == 3
    assert execs[1].event_count == 3
    assert execs[0].applications == ["A"]
    assert execs[1].applications == ["B"]


def test_build_executions_ids_are_stable_and_ordered():
    events = [_event(i, app="A" if i < 2 else "B", ts=i * 1000) for i in range(4)]
    boundary = system_change_boundaries(events)
    execs = build_executions("sessX", "op1", events, boundary)
    assert [e.execution_id for e in execs] == ["sessX::exec0", "sessX::exec1"]


def test_build_executions_excludes_noise_applications_from_applications_list():
    events = [
        _event(0, app="Word", ts=0),
        _event(1, app="procmine-desktop-agent", ts=100),
        _event(2, app="Word", ts=200),
    ]
    boundary = [False, False]  # single execution, no boundary
    execs = build_executions("s1", "op1", events, boundary)
    assert len(execs) == 1
    assert execs[0].applications == ["Word"]


def test_build_executions_ordered_steps_collapse_same_context_runs():
    events = (
        [_event(i, app="A", category="input", ts=i * 100) for i in range(3)]
        + [_event(i, app="A", category="pointer", ts=i * 100) for i in range(3, 5)]
    )
    boundary = [False] * 4  # one execution
    execs = build_executions("s1", "op1", events, boundary)
    steps = execs[0].ordered_steps
    assert len(steps) == 2
    assert steps[0]["interaction_category"] == "input"
    assert steps[0]["n_events"] == 3
    assert steps[1]["interaction_category"] == "pointer"
    assert steps[1]["n_events"] == 2


def test_build_executions_duration_and_timestamps():
    events = [_event(i, app="A", ts=i * 500) for i in range(4)]
    boundary = [False] * 3
    execs = build_executions("s1", "op1", events, boundary)
    assert execs[0].start_ms == 0
    assert execs[0].end_ms == 1500
    assert execs[0].duration_ms == 1500


def test_build_executions_empty_session_gives_no_executions():
    assert build_executions("s1", "op1", [], []) == []


def test_dominant_context_falls_back_to_system_for_non_office_app():
    events = [_event(i, app="A", ts=i * 100) for i in range(4)]
    execs = build_executions("s1", "op1", events, [False] * 3)
    assert execs[0].dominant_context == "app:A"


def test_dominant_context_refines_with_document_name_for_word():
    events = [_event(i, app="Microsoft Word", title="budget_report - Word", ts=i * 100) for i in range(4)]
    execs = build_executions("s1", "op1", events, [False] * 3)
    assert execs[0].dominant_context == "app:Microsoft Word::budget_report"


def test_build_executions_wrong_length_raises():
    events = [_event(i, ts=i * 100) for i in range(3)]
    with pytest.raises(ValueError):
        build_executions("s1", "op1", events, [True])
