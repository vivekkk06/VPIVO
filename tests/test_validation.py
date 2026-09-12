from procmine.validation import (
    check_chronological_order,
    check_chunk_linkage,
    check_duplicate_event_ids,
    check_required_fields,
)


def test_check_required_fields_reports_missing():
    assert check_required_fields({"event_id": "e1"}) != []
    full = {
        "event_id": "e1", "session_id": "s1", "timestamp_ms": 1,
        "timestamp_iso": "x", "layer": "L2", "event_type": "mouse_click",
    }
    assert check_required_fields(full) == []


def test_check_duplicate_event_ids():
    events = [{"event_id": "a"}, {"event_id": "b"}, {"event_id": "a"}]
    assert check_duplicate_event_ids(events) == ["a"]


def test_check_chronological_order_detects_regression():
    events = [{"event_id": "a", "timestamp_ms": 100}, {"event_id": "b", "timestamp_ms": 50}]
    issues = check_chronological_order(events)
    assert len(issues) == 1
    assert issues[0]["after_event_id"] == "a"
    assert issues[0]["before_event_id"] == "b"


def test_check_chronological_order_accepts_sorted_input():
    events = [{"event_id": "a", "timestamp_ms": 1}, {"event_id": "b", "timestamp_ms": 2}]
    assert check_chronological_order(events) == []


def test_check_chunk_linkage_flags_dangling_reference():
    manifests = [{"chunk_id": "c1", "previous_chunk_id": None, "next_chunk_id": "c2", "gaps": []}]
    issues = check_chunk_linkage(manifests)
    assert len(issues) == 1
    assert issues[0]["issue"] == "next_chunk_id not found"


def test_check_chunk_linkage_reports_manifest_gaps():
    manifests = [{"chunk_id": "c1", "previous_chunk_id": None, "next_chunk_id": None, "gaps": [{"a": 1}]}]
    issues = check_chunk_linkage(manifests)
    assert any(i["issue"] == "manifest-reported gaps" for i in issues)
