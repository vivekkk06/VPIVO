"""Safe, non-destructive cleaning layer.

Rule: raw files on disk are never touched. This module takes the raw dicts
already read into memory and returns a *new* list plus a log of exactly what
changed and why — never a silent transformation. See
reports/day1/cleaning_policy.md for the policy this implements and the
rationale for what is deliberately NOT done here (no fabrication, no
similarity-based merging, no using ground truth to alter raw events).
"""

from __future__ import annotations

import json
from typing import Any


def clean_session_events(
    raw_events: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Returns (cleaned_events, transformation_log). Input list is not mutated."""
    log: list[dict[str, Any]] = []

    # 1. Exact full-record duplicate removal — identity is unambiguous here
    # (byte-for-byte identical record), so dropping the repeat loses nothing.
    seen_keys: set[str] = set()
    deduped: list[dict[str, Any]] = []
    n_exact_dupes_dropped = 0
    for e in raw_events:
        key = json.dumps(e, sort_keys=True, default=str)
        if key in seen_keys:
            n_exact_dupes_dropped += 1
            continue
        seen_keys.add(key)
        deduped.append(e)
    log.append(
        {
            "step": "drop_exact_duplicate_records",
            "reason": "byte-identical JSON record seen more than once; identity is unambiguous",
            "affected_events": n_exact_dupes_dropped,
            "information_lost": False,
            "note": "only the repeat is dropped, one copy of the record is kept",
        }
    )

    # 2. Chronological sort by timestamp_ms. This is the one place we reorder
    # data; nothing is added, removed, or renamed. Original correlation.
    # sequence_number/chunk_id are left untouched so provenance is intact.
    before_order = [e.get("event_id") for e in deduped]
    deduped.sort(key=lambda e: e.get("timestamp_ms", 0))
    after_order = [e.get("event_id") for e in deduped]
    n_reordered = sum(1 for a, b in zip(before_order, after_order) if a != b)
    log.append(
        {
            "step": "sort_chronologically_by_timestamp_ms",
            "reason": "raw file/chunk order is not guaranteed chronological (see timestamp_quality.md)",
            "affected_events": n_reordered,
            "information_lost": False,
        }
    )

    return deduped, log
