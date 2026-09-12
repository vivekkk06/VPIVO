"""Edge cases found while auditing the Day 1 foundation: a single corrupted
manifest, an empty events file, or an event carrying the wrong session_id
must be reported, never allowed to crash the whole load."""

import json

from procmine.audit import session_chunk_identity_checks
from procmine.loaders.events import load_session_events, read_jsonl
from procmine.validation import ValidationReport


def test_corrupted_manifest_does_not_crash_session_load(synthetic_session):
    manifest_path = synthetic_session.chunks[0].manifest_path
    manifest_path.write_text("{not valid json", encoding="utf-8")

    report = ValidationReport(scope="test")
    events = load_session_events(synthetic_session, report)

    assert len(report.malformed_manifest_files) == 1
    assert len(events) == 5  # events.jsonl itself is untouched and still loads


def test_empty_events_file_returns_no_events_not_a_crash(synthetic_session):
    synthetic_session.chunks[1].events_path.write_text("", encoding="utf-8")

    report = ValidationReport(scope="test")
    events = load_session_events(synthetic_session, report)

    assert len(events) == 3  # only chunk 1's events remain
    assert report.malformed_json_lines == []  # an empty file is not malformed


def test_wrong_session_id_on_an_event_is_flagged_not_silently_fixed(synthetic_session):
    events_path = synthetic_session.chunks[0].events_path
    lines = events_path.read_text(encoding="utf-8").splitlines()
    d = json.loads(lines[0])
    d["session_id"] = "ses_some_other_session"
    lines[0] = json.dumps(d)
    events_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = ValidationReport(scope="test")
    raw_by_chunk = {}
    for chunk in synthetic_session.chunks:
        raw_by_chunk[chunk.chunk_dir.name] = read_jsonl(chunk.events_path, report)

    issues = session_chunk_identity_checks(synthetic_session, raw_by_chunk)

    assert any(i["issue"] == "event.session_id mismatch" for i in issues)
    # and the event itself must still be loadable — we flag, we don't drop
    events = load_session_events(synthetic_session, ValidationReport(scope="test"))
    assert len(events) == 5
