from __future__ import annotations

import pytest

from procmine.segmentation.canonical import CanonicalEvent
from procmine.segmentation.features import extract_transition_features
from procmine.process_discovery.boundaries import (
    application_change_boundaries,
    debounced_system_change_boundaries,
    gap_threshold_boundaries,
    system_change_boundaries,
)


def _event(i, app=None, domain=None, ts=None) -> CanonicalEvent:
    from procmine.models import Event

    raw = {
        "event_id": f"e{i}", "session_id": "s1", "timestamp_ms": ts if ts is not None else i * 1000,
        "timestamp_iso": "2026-01-01T00:00:00Z", "layer": "l", "event_type": "mouse_click",
        "correlation": {}, "context": {},
    }
    src = Event.from_dict(raw)
    return CanonicalEvent(
        event_id=f"e{i}", session_id="s1", timestamp_ms=ts if ts is not None else i * 1000,
        event_type="mouse_click", layer="l", interaction_category="pointer",
        application=app, window_title=None, browser_domain=domain, browser_url=None,
        has_extracted_text=False, chunk_id=None, sequence_number=i, source_event=src,
    )


# --- gap_threshold_boundaries -----------------------------------------------

def test_gap_threshold_fires_only_above_threshold():
    events = [_event(0, ts=0), _event(1, ts=100), _event(2, ts=5000)]
    feats = extract_transition_features(events)
    assert gap_threshold_boundaries(feats, threshold_ms=1000) == [False, True]


def test_gap_threshold_boundary_is_inclusive_at_exact_value():
    events = [_event(0, ts=0), _event(1, ts=1000)]
    feats = extract_transition_features(events)
    assert gap_threshold_boundaries(feats, threshold_ms=1000) == [True]


# --- application_change_boundaries ------------------------------------------

def test_application_change_boundaries_matches_existing_feature():
    events = [_event(0, app="Word", ts=0), _event(1, app="Word", ts=100), _event(2, app="Excel", ts=200)]
    feats = extract_transition_features(events)
    assert application_change_boundaries(feats) == [False, True]


# --- system_change_boundaries ------------------------------------------------

def test_system_change_boundaries_splits_by_browser_domain_not_just_app():
    events = [
        _event(0, app="Edge", domain="127.0.0.1:5132", ts=0),
        _event(1, app="Edge", domain="127.0.0.1:5132", ts=100),
        _event(2, app="Edge", domain="127.0.0.1:5133", ts=200),
    ]
    assert system_change_boundaries(events) == [False, True]


def test_system_change_boundaries_noise_app_gives_no_boundary():
    events = [
        _event(0, app="Word", ts=0),
        _event(1, app="procmine-desktop-agent", ts=100),  # noise -> None, no evidence
        _event(2, app="Word", ts=200),
    ]
    # both transitions touch a None (no-evidence) side -> neither counted as a change
    assert system_change_boundaries(events) == [False, False]


def test_system_change_boundaries_detects_switch_across_a_sandwiched_noise_event():
    # a recording-agent window (no system evidence) sits between two
    # DIFFERENT real systems -- the switch must still be detected via
    # forward-filling, not silently missed because both sides only ever
    # get compared against the None in between.
    events = [
        _event(0, app="Word", ts=0),
        _event(1, app="procmine-desktop-agent", ts=100),
        _event(2, app="Excel", ts=200),
    ]
    assert system_change_boundaries(events) == [False, True]


def test_system_change_boundaries_length_matches_transitions():
    events = [_event(i, app="Word", ts=i * 100) for i in range(5)]
    assert len(system_change_boundaries(events)) == 4


# --- debounced_system_change_boundaries -------------------------------------

def test_debounce_filters_a_single_event_flicker():
    events = [
        _event(0, app="Word", ts=0),
        _event(1, app="Word", ts=100),
        _event(2, app="Excel", ts=200),  # one-event flicker back to Excel
        _event(3, app="Word", ts=300),
        _event(4, app="Word", ts=400),
    ]
    raw = system_change_boundaries(events)
    assert raw == [False, True, True, False]  # both switches look real without debouncing
    debounced = debounced_system_change_boundaries(events, min_persist=2)
    # the flicker into Excel (index 1) only persists 1 event -> filtered out;
    # the return to Word (index 2) persists 2 events afterward -> kept
    assert debounced == [False, False, True, False]


def test_debounce_keeps_a_change_that_persists():
    events = [
        _event(0, app="Word", ts=0),
        _event(1, app="Excel", ts=100),
        _event(2, app="Excel", ts=200),
        _event(3, app="Excel", ts=300),
    ]
    debounced = debounced_system_change_boundaries(events, min_persist=2)
    assert debounced == [True, False, False]


def test_debounce_min_persist_one_matches_raw():
    events = [
        _event(0, app="Word", ts=0),
        _event(1, app="Excel", ts=100),
        _event(2, app="Word", ts=200),
    ]
    assert debounced_system_change_boundaries(events, min_persist=1) == system_change_boundaries(events)


def test_debounce_rejects_invalid_min_persist():
    events = [_event(0, ts=0), _event(1, ts=100)]
    with pytest.raises(ValueError):
        debounced_system_change_boundaries(events, min_persist=0)
