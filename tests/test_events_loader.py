from procmine.loaders.events import load_session_events
from procmine.paths import resolve_screenshot
from procmine.validation import ValidationReport


def test_merges_chunks_and_sorts_chronologically(synthetic_session):
    report = ValidationReport(scope="test")
    events = load_session_events(synthetic_session, report)

    assert [e.event_id for e in events] == ["evt_1", "evt_2", "evt_3", "evt_4", "evt_5"]
    assert all(events[i].timestamp_ms <= events[i + 1].timestamp_ms for i in range(len(events) - 1))


def test_preserves_original_sequence_metadata(synthetic_session):
    events = load_session_events(synthetic_session, ValidationReport(scope="test"))

    by_id = {e.event_id: e for e in events}
    assert by_id["evt_1"].chunk_id == "chunk_20260101-0000-TESTBOX"
    assert by_id["evt_1"].sequence_number == 0
    assert by_id["evt_4"].chunk_id == "chunk_20260101-0030-TESTBOX"
    assert by_id["evt_4"].sequence_number == 0


def test_no_false_positive_out_of_order(synthetic_session):
    report = ValidationReport(scope="test")
    load_session_events(synthetic_session, report)
    assert report.out_of_order_events == []
    assert report.chunk_order_issues == []
    assert report.duplicate_event_ids == []


def test_screenshot_resolves_via_sibling_short_named_dir(synthetic_session):
    chunk = synthetic_session.chunks[0]
    resolved = resolve_screenshot(chunk, "scr_smart_1000_monitor_1_post.jpg")
    assert resolved is not None
    assert resolved.name == "scr_smart_1000_monitor_1_post.jpg"


def test_missing_screenshot_returns_none(synthetic_session):
    chunk = synthetic_session.chunks[0]
    assert resolve_screenshot(chunk, "does_not_exist.jpg") is None


def test_malformed_json_line_is_flagged_not_raised(synthetic_session):
    events_path = synthetic_session.chunks[0].events_path
    with events_path.open("a", encoding="utf-8") as f:
        f.write("{not valid json\n")

    report = ValidationReport(scope="test")
    events = load_session_events(synthetic_session, report)

    assert len(report.malformed_json_lines) == 1
    assert len(events) == 5  # malformed line excluded, nothing else broken


def test_missing_required_field_is_flagged_and_skipped(synthetic_session):
    events_path = synthetic_session.chunks[1].events_path
    lines = events_path.read_text(encoding="utf-8").splitlines()
    import json

    d = json.loads(lines[0])
    del d["timestamp_ms"]
    lines[0] = json.dumps(d)
    events_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = ValidationReport(scope="test")
    events = load_session_events(synthetic_session, report)

    assert len(report.missing_required_fields) == 1
    assert len(events) == 4
