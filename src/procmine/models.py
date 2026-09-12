"""Typed views over the raw JSON records.

Every model keeps the untouched source dict on `.raw`, so any field we have not
modeled yet is still reachable. We only pull out the fields Day 1 actually needs
(loading, profiling, validation, GT parsing) — we do not invent or rename fields
that are not in DATA_SCHEMA.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def _parse_iso(ts: str) -> datetime:
    # timestamps end in "Z"; datetime.fromisoformat wants "+00:00" before 3.11-era
    # quirks, so normalize explicitly rather than relying on version behaviour.
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts).astimezone(timezone.utc)


@dataclass
class Event:
    event_id: str
    session_id: str
    timestamp_ms: int
    timestamp_iso: datetime
    layer: str
    event_type: str
    chunk_id: Optional[str]
    sequence_number: Optional[int]
    active_app: Optional[str]
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Event":
        correlation = d.get("correlation") or {}
        context = d.get("context") or {}
        active_app = context.get("active_app")
        return cls(
            event_id=d["event_id"],
            session_id=d["session_id"],
            timestamp_ms=d["timestamp_ms"],
            timestamp_iso=_parse_iso(d["timestamp_iso"]),
            layer=d["layer"],
            event_type=d["event_type"],
            chunk_id=correlation.get("chunk_id"),
            sequence_number=correlation.get("sequence_number"),
            active_app=(active_app or {}).get("app_name") if active_app else None,
            raw=d,
        )


@dataclass
class ChunkManifest:
    chunk_id: str
    session_id: str
    start_ms: int
    end_ms: int
    total_events: int
    previous_chunk_id: Optional[str]
    next_chunk_id: Optional[str]
    is_session_start: bool
    is_session_end: bool
    raw: dict[str, Any] = field(repr=False)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ChunkManifest":
        tr = d["time_range"]
        return cls(
            chunk_id=d["chunk_id"],
            session_id=d["session_id"],
            start_ms=tr["start_ms"],
            end_ms=tr["end_ms"],
            total_events=d["statistics"]["total_events"],
            previous_chunk_id=d.get("previous_chunk_id"),
            next_chunk_id=d.get("next_chunk_id"),
            is_session_start=bool(d.get("is_session_start")),
            is_session_end=bool(d.get("is_session_end")),
            raw=d,
        )


@dataclass
class GTExecution:
    """One reconstructed execution of a business process, from gt.jsonl."""

    process_code: str
    process_name: Optional[str]
    case_id: Optional[str]
    start_ts: datetime
    end_ts: Optional[datetime]
    variant: Optional[str]
    suspended: bool = False
    split_id: Optional[str] = None
    task_ids: list[str] = field(default_factory=list)
    apps_touched: list[str] = field(default_factory=list)
