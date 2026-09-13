from datetime import datetime, timedelta, timezone

from procmine.models import Event, GTExecution
from procmine.segmentation.signals import (
    Boundary,
    app_switch_payload_key,
    deduplicate_consecutive,
    evaluate_signal,
    extract_boundaries,
    has_extracted_text,
    is_clipboard_change,
)


def _ev(event_id: str, ts_ms: int, event_type: str = "mouse_click", payload=None, extracted_text=None) -> Event:
    raw = {
        "event_id": event_id,
        "session_id": "s1",
        "timestamp_ms": ts_ms,
        "timestamp_iso": (
            datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=ts_ms)
        ).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
        + "Z",
        "layer": "L2",
        "event_type": event_type,
        "correlation": {},
        "context": {"extracted_text": {"text": extracted_text}} if extracted_text else {},
        "payload": payload or {},
    }
    return Event.from_dict(raw)


def _exec(code, case_id, start_s, end_s, split_id=None) -> GTExecution:
    return GTExecution(
        process_code=code,
        process_name=None,
        case_id=case_id,
        start_ts=datetime.fromtimestamp(start_s, tz=timezone.utc),
        end_ts=datetime.fromtimestamp(end_s, tz=timezone.utc),
        variant=None,
        split_id=split_id,
    )


def test_extract_boundaries_basic_ordering_and_timestamp():
    execs = [_exec("A", "c1", 0, 10), _exec("B", "c2", 15, 25)]
    boundaries = extract_boundaries("s1", execs)
    assert len(boundaries) == 1
    assert boundaries[0].timestamp_ms == 10_000  # end of A, in ms
    assert boundaries[0].prev_process_code == "A"
    assert boundaries[0].next_process_code == "B"


def test_extract_boundaries_tags_resume_via_split_id():
    execs = [_exec("A", "c1", 0, 10), _exec("A", "c1", 15, 25, split_id="split-1")]
    boundaries = extract_boundaries("s1", execs)
    assert boundaries[0].is_resume is True


def test_extract_boundaries_tags_normal_transition_as_not_resume():
    execs = [_exec("A", "c1", 0, 10), _exec("B", "c2", 15, 25)]
    boundaries = extract_boundaries("s1", execs)
    assert boundaries[0].is_resume is False


def test_extract_boundaries_ignores_open_executions():
    execs = [_exec("A", "c1", 0, 10), GTExecution("B", None, "c2", datetime.fromtimestamp(15, tz=timezone.utc), None, None)]
    boundaries = extract_boundaries("s1", execs)
    assert boundaries == []


def test_signal_that_fires_exactly_at_every_boundary_scores_perfectly():
    boundary = Boundary("s1", 10_000, False, "A", "B")
    events = [_ev("e1", 9_000), _ev("e2", 10_000, event_type="clipboard_change"), _ev("e3", 11_000)]
    result = evaluate_signal(
        "clipboard", {"s1": events}, {"s1": [boundary]}, is_clipboard_change, window_ms=2000
    )
    assert result.boundary_coverage == 1.0
    assert result.precision == 1.0


def test_lift_is_high_when_signal_concentrates_near_boundaries():
    boundary = Boundary("s1", 10_000, False, "A", "B")
    events = [
        _ev("e1", 9_000),
        _ev("e2", 10_000, event_type="clipboard_change"),
        _ev("e3", 11_000),
        # a large, mostly-non-signal interior population, so the interior
        # rate is nonzero but much lower than the boundary-window rate
        *[_ev(f"far{i}", 100_000 + i * 1000) for i in range(9)],
        _ev("far_signal", 500_000, event_type="clipboard_change"),
    ]
    result = evaluate_signal(
        "clipboard", {"s1": events}, {"s1": [boundary]}, is_clipboard_change, window_ms=2000
    )
    assert result.lift is not None and result.lift > 1


def test_signal_that_never_fires_near_boundary_scores_zero_coverage():
    boundary = Boundary("s1", 10_000, False, "A", "B")
    events = [_ev("e1", 0), _ev("e2", 100_000, event_type="clipboard_change")]
    result = evaluate_signal(
        "clipboard", {"s1": events}, {"s1": [boundary]}, is_clipboard_change, window_ms=2000
    )
    assert result.boundary_coverage == 0.0
    assert result.false_negative_rate == 1.0


def test_uniformly_common_signal_has_lift_near_one():
    boundary = Boundary("s1", 10_000, False, "A", "B")
    # extracted_text on every single event, everywhere -> no boundary-specific
    # concentration, lift should not indicate any special alignment.
    events = [_ev(f"e{i}", i * 1000, extracted_text="x") for i in range(20)]
    result = evaluate_signal(
        "extracted_text", {"s1": events}, {"s1": [boundary]}, has_extracted_text, window_ms=2000
    )
    assert result.lift == 1.0


def test_resume_and_normal_boundary_coverage_computed_separately():
    resume_b = Boundary("s1", 10_000, True, "A", "A")
    normal_b = Boundary("s1", 20_000, False, "A", "B")
    events = [_ev("e1", 10_000, event_type="clipboard_change")]  # only near the resume boundary
    result = evaluate_signal(
        "clipboard", {"s1": events}, {"s1": [resume_b, normal_b]}, is_clipboard_change, window_ms=2000
    )
    assert result.resume_boundary_coverage == 1.0
    assert result.normal_boundary_coverage == 0.0


def test_per_session_coverage_flags_unstable_signal():
    b1 = Boundary("s1", 10_000, False, "A", "B")
    b2 = Boundary("s2", 10_000, False, "A", "B")
    events_s1 = [_ev("e1", 10_000, event_type="clipboard_change")]
    events_s2 = [_ev("e2", 999_000, event_type="clipboard_change")]  # far from s2's boundary
    result = evaluate_signal(
        "clipboard",
        {"s1": events_s1, "s2": events_s2},
        {"s1": [b1], "s2": [b2]},
        is_clipboard_change,
        window_ms=2000,
    )
    assert result.per_session_coverage_min == 0.0
    assert result.per_session_coverage_max == 1.0
    assert result.per_session_coverage_std > 0


def test_deduplicate_consecutive_drops_only_adjacent_identical():
    events = [
        _ev("a", 0, event_type="app_switch", payload={"new_app": {"app_name": "chrome"}, "previous_app": {}}),
        _ev("b", 100, event_type="app_switch", payload={"new_app": {"app_name": "chrome"}, "previous_app": {}}),
        _ev("c", 5000, event_type="app_switch", payload={"new_app": {"app_name": "excel"}, "previous_app": {}}),
        _ev("d", 5100, event_type="app_switch", payload={"new_app": {"app_name": "chrome"}, "previous_app": {}}),
    ]
    deduped = deduplicate_consecutive(events, "app_switch", app_switch_payload_key)
    assert [e.event_id for e in deduped] == ["a", "c", "d"]


def test_deduplicate_consecutive_ignores_other_event_types():
    events = [
        _ev("a", 0, event_type="app_switch", payload={"new_app": {"app_name": "chrome"}, "previous_app": {}}),
        _ev("b", 100, event_type="mouse_click"),
        _ev("c", 200, event_type="app_switch", payload={"new_app": {"app_name": "chrome"}, "previous_app": {}}),
    ]
    deduped = deduplicate_consecutive(events, "app_switch", app_switch_payload_key)
    # the mouse_click in between means the two app_switch events are not
    # *adjacent* app_switch occurrences, so neither should be dropped
    assert [e.event_id for e in deduped] == ["a", "b", "c"]
