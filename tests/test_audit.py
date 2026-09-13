from procmine.audit import (
    event_type_layer_consistency,
    exact_duplicate_events,
    extracted_text_profile,
    missingness_audit,
    semantic_duplicate_events,
    sequential_duplicate_events,
    session_gt_coverage_check,
    text_input_complete_profile,
    timestamp_quality,
)


def _e(event_id, ts_ms, event_type="mouse_click", payload=None, session_id="s1", extracted_text=None):
    return {
        "event_id": event_id,
        "session_id": session_id,
        "timestamp_ms": ts_ms,
        "timestamp_iso": f"2026-01-01T00:00:{ts_ms // 1000:02d}.000Z",
        "layer": "L2",
        "event_type": event_type,
        "context": {"extracted_text": {"text": extracted_text}} if extracted_text is not None else {},
        "correlation": {},
        "payload": payload or {},
    }


def test_missingness_audit_distinguishes_absent_null_empty():
    events = [
        {"event_id": "a", "session_id": "s", "timestamp_ms": 1, "timestamp_iso": "x", "layer": "L2", "event_type": "t", "context": None, "correlation": {}, "payload": {}},
        {"event_id": "b", "session_id": "s", "timestamp_ms": 1, "timestamp_iso": "x", "layer": "L2", "event_type": "t", "correlation": {}, "payload": {}},
    ]
    report = missingness_audit(events)
    assert report["context"]["null"] == 1
    assert report["context"]["missing"] == 1


def test_exact_duplicate_events_detects_byte_identical_records():
    e = _e("a", 1000)
    events = [e, dict(e), _e("b", 2000)]
    dupes = exact_duplicate_events(events)
    assert len(dupes) == 1
    assert dupes[0]["count"] == 2


def test_semantic_duplicate_detects_same_payload_different_id():
    events = [
        _e("a", 1000, "browser_error", {"message": "x"}),
        _e("b", 1000, "browser_error", {"message": "x"}),
    ]
    dupes = semantic_duplicate_events(events)
    assert len(dupes) == 1
    assert set(dupes[0]["event_ids"]) == {"a", "b"}


def test_sequential_duplicate_requires_adjacency_and_same_payload():
    events = [
        _e("a", 1000, "app_switch", {"app": "chrome"}),
        _e("b", 1050, "app_switch", {"app": "chrome"}),  # duplicate, adjacent
        _e("c", 5000, "app_switch", {"app": "excel"}),
        _e("d", 9000, "app_switch", {"app": "chrome"}),  # same payload as a/b but not adjacent
    ]
    dupes = sequential_duplicate_events(events)
    assert len(dupes) == 1
    assert dupes[0] == {"first": "a", "second": "b", "event_type": "app_switch"}


def test_timestamp_quality_flags_ms_iso_mismatch():
    events = [_e("a", 1000)]
    events[0]["timestamp_iso"] = "2026-01-01T00:05:00.000Z"  # way off from timestamp_ms=1000
    rpt = timestamp_quality(events)
    assert len(rpt.ms_iso_mismatches) == 1


def test_timestamp_quality_flags_non_utc_iso():
    events = [_e("a", 1000)]
    events[0]["timestamp_iso"] = "2026-01-01T00:00:01.000+09:00"  # not UTC 'Z' form
    rpt = timestamp_quality(events)
    assert len(rpt.non_utc_iso) == 1


def test_timestamp_quality_counts_negative_gap():
    events = [_e("a", 2000), _e("b", 1000)]
    rpt = timestamp_quality(events)
    assert rpt.negative_gaps == 1


def test_event_type_layer_consistency_flags_unknown_combo():
    events = [_e("a", 1000, "totally_unknown_type")]
    report = event_type_layer_consistency(events)
    assert report["unknown_event_type_for_layer"] == {"L2:totally_unknown_type": 1}


def test_event_type_layer_consistency_accepts_known_combo():
    events = [_e("a", 1000, "app_switch")]
    report = event_type_layer_consistency(events)
    assert report["unknown_event_type_for_layer"] == {}


def test_extracted_text_profile_ignores_events_without_text():
    events = [_e("a", 1000), _e("b", 2000, extracted_text="hello")]
    profile = extracted_text_profile(events)
    assert profile["n_with_nonempty_text"] == 1
    assert profile["n_events"] == 2


def test_text_input_complete_profile_flags_missing_content():
    events = [
        _e("a", 1000, "text_input_complete", payload={"final_text": "hello"}),
        _e("b", 2000, "text_input_complete", payload={}),
    ]
    profile = text_input_complete_profile(events)
    assert profile["with_apparent_content"] == 1
    assert profile["missing_or_empty_content"] == 1


def test_text_input_complete_profile_flags_plaintext_password():
    events = [
        _e(
            "a", 1000, "text_input_complete",
            payload={"final_text": "hunter2", "input_context": {"is_password_field": True}},
        ),
    ]
    profile = text_input_complete_profile(events)
    assert profile["password_fields_with_plaintext_final_text"] == 1


def test_session_gt_coverage_check_flags_events_ending_well_before_gt_end():
    # events stop 16 minutes before gt_manifest's session end -> the real
    # anomaly this check was built to catch
    result = session_gt_coverage_check(last_event_ms=0, gt_session_end_ms=16 * 60_000)
    assert result["flagged"] is True
    assert result["events_end_before_gt_by_ms"] == 16 * 60_000


def test_session_gt_coverage_check_accepts_normal_trailing_activity():
    # events run a bit *past* gt_end, or end within the slack window before
    # it -- both are the normal, observed pattern, not a defect
    past_gt_end = session_gt_coverage_check(last_event_ms=100_000, gt_session_end_ms=90_000)
    within_slack = session_gt_coverage_check(last_event_ms=90_000, gt_session_end_ms=100_000)
    assert past_gt_end["flagged"] is False
    assert within_slack["flagged"] is False


def test_session_gt_coverage_check_respects_custom_slack():
    result = session_gt_coverage_check(
        last_event_ms=0, gt_session_end_ms=200_000, trailing_slack_ms=100_000
    )
    assert result["flagged"] is True
