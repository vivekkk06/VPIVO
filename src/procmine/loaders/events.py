"""Loaders for events.jsonl and manifest.json, at chunk and session level.

Design: chunk boundaries are a recording artifact (DATA_SCHEMA.md, "Sessions
and chunks"), not a business one. So the unit callers should reach for is a
*session's* full, chronologically-sorted event stream — `load_session_events`
below — with chunk merging handled internally. The single-chunk loader still
exists because validation and profiling need to reason per-chunk too (e.g.
comparing manifest statistics against what was actually read).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from procmine.models import ChunkManifest, Event
from procmine.paths import ChunkPaths, SessionPaths
from procmine.validation import (
    ValidationReport,
    check_chronological_order,
    check_chunk_linkage,
    check_duplicate_event_ids,
    check_required_fields,
)


def read_jsonl(path: Path, report: ValidationReport) -> list[dict[str, Any]]:
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                report.malformed_json_lines.append(
                    {"file": str(path), "line_no": line_no, "error": str(e)}
                )
    return records


def _read_manifest_raw(path: Path, report: ValidationReport) -> dict[str, Any] | None:
    """A malformed manifest.json must not take down the whole session/dataset
    load — we've seen this crash for real (see existing_implementation_audit.md).
    Record it and let the caller proceed without that chunk's manifest info."""
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        report.malformed_manifest_files.append({"file": str(path), "error": str(e)})
        return None


def load_chunk_manifest(chunk: ChunkPaths, report: ValidationReport | None = None) -> ChunkManifest | None:
    if report is None:
        report = ValidationReport(scope=f"chunk:{chunk.chunk_dir.name}")
    raw = _read_manifest_raw(chunk.manifest_path, report)
    if raw is None:
        return None
    return ChunkManifest.from_dict(raw)


def load_chunk_events(
    chunk: ChunkPaths, report: ValidationReport
) -> list[Event]:
    raw_records = read_jsonl(chunk.events_path, report)

    events = []
    for raw in raw_records:
        missing = check_required_fields(raw)
        if missing:
            report.missing_required_fields.append(
                {"file": str(chunk.events_path), "event_id": raw.get("event_id"), "missing": missing}
            )
            continue
        events.append(Event.from_dict(raw))
    return events


def load_session_events(
    session: SessionPaths, report: ValidationReport | None = None
) -> list[Event]:
    """Load every chunk belonging to a session, merged into one chronological
    stream. Original `sequence_number`/`chunk_id` are preserved on each Event
    so provenance survives the merge."""
    if report is None:
        report = ValidationReport(scope=f"session:{session.session_id}")

    all_raw_events: list[dict[str, Any]] = []
    manifests_raw: list[dict[str, Any]] = []

    for chunk in session.chunks:
        chunk_raw = read_jsonl(chunk.events_path, report)
        for raw in chunk_raw:
            missing = check_required_fields(raw)
            if missing:
                report.missing_required_fields.append(
                    {"file": str(chunk.events_path), "event_id": raw.get("event_id"), "missing": missing}
                )
                continue
            all_raw_events.append(raw)

        if chunk.manifest_path.exists():
            manifest_raw = _read_manifest_raw(chunk.manifest_path, report)
            if manifest_raw is not None:
                manifests_raw.append(manifest_raw)

    report.duplicate_event_ids.extend(check_duplicate_event_ids(all_raw_events))
    report.chunk_order_issues.extend(check_chunk_linkage(manifests_raw))

    # Check chronology of the *natural* concatenation (chunks in directory
    # order, each chunk's own file order) before re-sorting — this is what
    # actually surfaces clock skew or overlapping chunks. A stable sort by
    # timestamp_ms then gives us the final, safe-to-use stream.
    report.out_of_order_events.extend(check_chronological_order(all_raw_events))

    all_raw_events.sort(key=lambda e: e["timestamp_ms"])

    return [Event.from_dict(r) for r in all_raw_events]
