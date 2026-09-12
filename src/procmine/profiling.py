"""Dataset-level profiling: the numbers we need before designing Step 1.

Deliberately model-free — counts, distributions, availability rates. Built by
streaming each session's chunks once (no full-dataset materialization), since
events.jsonl files run into the hundreds of MB in aggregate.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from procmine.loaders.events import load_chunk_manifest, load_session_events
from procmine.paths import SessionPaths, discover_dataset
from procmine.validation import ValidationReport


def profile_session(session: SessionPaths) -> dict[str, Any]:
    report = ValidationReport(scope=f"session:{session.session_id}")
    events = load_session_events(session, report)

    layer_counts: Counter[str] = Counter(e.layer for e in events)
    type_counts: Counter[str] = Counter(e.event_type for e in events)
    apps: Counter[str] = Counter(e.active_app for e in events if e.active_app)

    extracted_text_count = sum(
        1 for e in events if (e.raw.get("context") or {}).get("extracted_text")
    )
    screenshot_count = sum(1 for e in events if e.event_type == "screenshot_smart")

    duration_s = None
    if events:
        duration_s = (events[-1].timestamp_ms - events[0].timestamp_ms) / 1000.0

    n_screenshot_files = sum(
        len(list(d.glob("*.jpg"))) for chunk in session.chunks for d in chunk.screenshot_dirs
    )

    return {
        "session_id": session.session_id,
        "n_chunks": len(session.chunks),
        "n_events": len(events),
        "duration_seconds": duration_s,
        "events_by_layer": dict(layer_counts),
        "events_by_type": dict(type_counts),
        "applications": dict(apps.most_common(20)),
        "extracted_text_events": extracted_text_count,
        "extracted_text_rate": extracted_text_count / len(events) if events else 0.0,
        "screenshot_events": screenshot_count,
        "screenshot_files_on_disk": n_screenshot_files,
        "has_ground_truth": session.gt_path is not None,
        "validation": report.summary(),
    }


def profile_dataset(dataset_dir: Path) -> dict[str, Any]:
    sessions = discover_dataset(dataset_dir)
    per_session = []
    session_errors = []
    for s in sessions:
        try:
            per_session.append(profile_session(s))
        except Exception as e:  # noqa: BLE001 - one bad session must not kill the batch
            session_errors.append({"session_id": s.session_id, "error": f"{type(e).__name__}: {e}"})

    total_events = sum(s["n_events"] for s in per_session)
    total_chunks = sum(s["n_chunks"] for s in per_session)

    layer_totals: Counter[str] = Counter()
    type_totals: Counter[str] = Counter()
    app_totals: Counter[str] = Counter()
    for s in per_session:
        layer_totals.update(s["events_by_layer"])
        type_totals.update(s["events_by_type"])
        app_totals.update(s["applications"])

    durations = [s["duration_seconds"] for s in per_session if s["duration_seconds"] is not None]

    return {
        "dataset": dataset_dir.name,
        "n_sessions_discovered": len(sessions),
        "n_sessions": len(per_session),
        "n_sessions_failed": len(session_errors),
        "session_errors": session_errors,
        "n_chunks": total_chunks,
        "n_events": total_events,
        "events_by_layer": dict(layer_totals),
        "events_by_type": dict(type_totals),
        "applications": dict(app_totals.most_common(20)),
        "session_duration_seconds": {
            "min": min(durations) if durations else None,
            "max": max(durations) if durations else None,
            "mean": sum(durations) / len(durations) if durations else None,
        },
        "sessions_with_ground_truth": sum(1 for s in per_session if s["has_ground_truth"]),
        "sessions": per_session,
    }
