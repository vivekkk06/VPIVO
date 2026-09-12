"""Builds a tiny synthetic session (2 chunks, a handful of events, a gt.jsonl
with the documented quirks baked in) under tmp_path. Tests run against this,
never against the real multi-GB dataset."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _event(event_id: str, ts_ms: int, seq: int, chunk_id: str, event_type: str = "mouse_click", app: str = "excel") -> dict:
    return {
        "schema_version": "1.0.0",
        "event_id": event_id,
        "session_id": "ses_20260101-000000-TESTBOX",
        "timestamp_ms": ts_ms,
        "timestamp_iso": f"2026-01-01T00:00:{ts_ms // 1000:02d}.000Z",
        "layer": "L2",
        "event_type": event_type,
        "source": {"agent_version": "1.0.0", "machine_id": "TESTBOX", "os": "Windows", "username_hash": "sha256:x"},
        "context": {"active_app": {"app_name": app, "process_name": f"{app}.exe", "window_title": "t"}},
        "correlation": {"triggered_by": None, "correlated_events": [], "sequence_number": seq, "chunk_id": chunk_id, "ms_since_last_event": 0},
        "payload": {},
        "metadata": {},
        "extensions": {},
    }


def _manifest(chunk_id: str, session_id: str, start_ms: int, end_ms: int, total_events: int, prev_id, next_id, is_start: bool, is_end: bool) -> dict:
    return {
        "manifest_version": "1.0.0",
        "chunk_id": chunk_id,
        "session_id": session_id,
        "machine_id": "TESTBOX",
        "time_range": {"start_ms": start_ms, "start_iso": "x", "end_ms": end_ms, "end_iso": "x"},
        "schema_version": "1.0.0",
        "agent_version": "1.0.0",
        "statistics": {"total_events": total_events, "events_by_layer": {}, "events_by_type": {}, "sequence_number_range": {"first": 0, "last": total_events - 1}},
        "files": {},
        "integrity": {},
        "previous_chunk_id": prev_id,
        "next_chunk_id": next_id,
        "is_session_start": is_start,
        "is_session_end": is_end,
        "session_info": None,
        "gaps": [],
    }


@pytest.fixture
def synthetic_session(tmp_path: Path):
    from procmine.paths import discover_session

    session_id = "ses_20260101-000000-TESTBOX"
    session_dir = tmp_path / session_id
    chunk1_id = "chunk_20260101-0000-TESTBOX"
    chunk2_id = "chunk_20260101-0030-TESTBOX"

    chunk1_dir = session_dir / chunk1_id
    chunk2_dir = session_dir / chunk2_id
    chunk1_dir.mkdir(parents=True)
    chunk2_dir.mkdir(parents=True)

    # Chunk 2 is written with an out-of-order-looking file (later timestamp
    # first) to exercise the merge/sort behaviour honestly.
    _write_jsonl(
        chunk1_dir / "events.jsonl",
        [
            _event("evt_1", 1000, 0, chunk1_id, "session_start"),
            _event("evt_2", 2000, 1, chunk1_id, "app_switch"),
            _event("evt_3", 3000, 2, chunk1_id, "mouse_click"),
        ],
    )
    _write_jsonl(
        chunk2_dir / "events.jsonl",
        [
            _event("evt_4", 4000, 0, chunk2_id, "keystroke"),
            _event("evt_5", 5000, 1, chunk2_id, "mouse_click"),
        ],
    )
    (chunk1_dir / "manifest.json").write_text(
        json.dumps(_manifest(chunk1_id, session_id, 1000, 3000, 3, None, chunk2_id, True, False)),
        encoding="utf-8",
    )
    (chunk2_dir / "manifest.json").write_text(
        json.dumps(_manifest(chunk2_id, session_id, 4000, 5000, 2, chunk1_id, None, False, True)),
        encoding="utf-8",
    )

    # Screenshot layout quirk: a screenshots-only sibling dir using the short
    # chunk_HHMM naming, distinct from the full chunk dir that has events.jsonl.
    short_dir = session_dir / "chunk_0000"
    (short_dir / "screenshots").mkdir(parents=True)
    (short_dir / "screenshots" / "scr_smart_1000_monitor_1_post.jpg").write_bytes(b"fake-jpeg")

    return discover_session(session_dir)


@pytest.fixture
def synthetic_gt(tmp_path: Path) -> Path:
    gt_path = tmp_path / "gt.jsonl"
    records = [
        {"ts_utc": "2026-01-01T00:00:00+00:00", "event": "run_config", "run_id": "r1"},
        {"ts_utc": "2026-01-01T00:00:01+00:00", "event": "process_started", "process_code": "A", "process_name": "Test Process", "case_id": "C-1", "process_variant": "std"},
        # documented defect: duplicate consecutive process_started
        {"ts_utc": "2026-01-01T00:00:02+00:00", "event": "process_started", "process_code": "A", "process_name": "Test Process", "case_id": "C-1", "process_variant": "std"},
        {"ts_utc": "2026-01-01T00:00:03+00:00", "event": "task_started", "current_process": "A", "task_id": "T-1", "action": "approve", "entity": "x"},
        {"ts_utc": "2026-01-01T00:00:10+00:00", "event": "process_switched_out", "from": "A", "to": "B"},
        # documented defect: switched_out with no matching open process
        {"ts_utc": "2026-01-01T00:00:11+00:00", "event": "process_switched_out", "from": "Z", "to": "A"},
        {"ts_utc": "2026-01-01T00:00:20+00:00", "event": "session_ended", "total_tasks": 1, "duration_seconds": 20},
    ]
    with gt_path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return gt_path
