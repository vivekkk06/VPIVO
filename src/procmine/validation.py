"""Validation checks, collected into a report instead of raised as exceptions.

We want a full picture of data quality per session/dataset, not a crash on the
first bad line. Loaders call into this module and accumulate issues; callers
decide what, if anything, is fatal.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ValidationReport:
    scope: str  # e.g. "session:ses_..." or "dataset:dataset_a"
    malformed_json_lines: list[dict[str, Any]] = field(default_factory=list)
    malformed_manifest_files: list[dict[str, Any]] = field(default_factory=list)
    missing_required_fields: list[dict[str, Any]] = field(default_factory=list)
    duplicate_event_ids: list[str] = field(default_factory=list)
    out_of_order_events: list[dict[str, Any]] = field(default_factory=list)
    chunk_order_issues: list[dict[str, Any]] = field(default_factory=list)
    gt_duplicate_starts: list[dict[str, Any]] = field(default_factory=list)
    gt_unpaired_switches: list[dict[str, Any]] = field(default_factory=list)
    gt_manifest_mismatches: list[dict[str, Any]] = field(default_factory=list)
    gt_resume_without_suspend: list[dict[str, Any]] = field(default_factory=list)
    gt_suspend_without_resume: list[dict[str, Any]] = field(default_factory=list)
    gt_overlapping_intervals: list[dict[str, Any]] = field(default_factory=list)

    def is_clean(self) -> bool:
        return not any(
            [
                self.malformed_json_lines,
                self.malformed_manifest_files,
                self.missing_required_fields,
                self.duplicate_event_ids,
                self.out_of_order_events,
                self.chunk_order_issues,
                self.gt_manifest_mismatches,
            ]
        )

    def summary(self) -> dict[str, int]:
        return {
            "malformed_json_lines": len(self.malformed_json_lines),
            "malformed_manifest_files": len(self.malformed_manifest_files),
            "missing_required_fields": len(self.missing_required_fields),
            "duplicate_event_ids": len(self.duplicate_event_ids),
            "out_of_order_events": len(self.out_of_order_events),
            "chunk_order_issues": len(self.chunk_order_issues),
            "gt_duplicate_starts": len(self.gt_duplicate_starts),
            "gt_unpaired_switches": len(self.gt_unpaired_switches),
            "gt_manifest_mismatches": len(self.gt_manifest_mismatches),
            "gt_resume_without_suspend": len(self.gt_resume_without_suspend),
            "gt_suspend_without_resume": len(self.gt_suspend_without_resume),
            "gt_overlapping_intervals": len(self.gt_overlapping_intervals),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "summary": self.summary(),
            "malformed_json_lines": self.malformed_json_lines,
            "malformed_manifest_files": self.malformed_manifest_files,
            "missing_required_fields": self.missing_required_fields,
            "duplicate_event_ids": self.duplicate_event_ids,
            "out_of_order_events": self.out_of_order_events,
            "chunk_order_issues": self.chunk_order_issues,
            "gt_duplicate_starts": self.gt_duplicate_starts,
            "gt_unpaired_switches": self.gt_unpaired_switches,
            "gt_manifest_mismatches": self.gt_manifest_mismatches,
            "gt_resume_without_suspend": self.gt_resume_without_suspend,
            "gt_suspend_without_resume": self.gt_suspend_without_resume,
            "gt_overlapping_intervals": self.gt_overlapping_intervals,
        }


REQUIRED_EVENT_FIELDS = (
    "event_id",
    "session_id",
    "timestamp_ms",
    "timestamp_iso",
    "layer",
    "event_type",
)


def check_required_fields(raw: dict[str, Any]) -> list[str]:
    return [f for f in REQUIRED_EVENT_FIELDS if f not in raw]


def check_duplicate_event_ids(events: list[dict[str, Any]]) -> list[str]:
    counts = Counter(e["event_id"] for e in events if "event_id" in e)
    return [eid for eid, n in counts.items() if n > 1]


def check_chronological_order(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues = []
    prev_ts = None
    prev_id = None
    for e in events:
        ts = e.get("timestamp_ms")
        if ts is None:
            continue
        if prev_ts is not None and ts < prev_ts:
            issues.append(
                {
                    "after_event_id": prev_id,
                    "before_event_id": e.get("event_id"),
                    "prev_timestamp_ms": prev_ts,
                    "this_timestamp_ms": ts,
                }
            )
        prev_ts, prev_id = ts, e.get("event_id")
    return issues


def check_chunk_linkage(manifests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cross-check each chunk's declared previous/next against the set actually
    present, and flag any manifest-reported gap."""
    issues = []
    present_ids = {m["chunk_id"] for m in manifests}
    for m in manifests:
        prev_id = m.get("previous_chunk_id")
        next_id = m.get("next_chunk_id")
        if prev_id and prev_id not in present_ids:
            issues.append(
                {"chunk_id": m["chunk_id"], "issue": "previous_chunk_id not found", "value": prev_id}
            )
        if next_id and next_id not in present_ids:
            issues.append(
                {"chunk_id": m["chunk_id"], "issue": "next_chunk_id not found", "value": next_id}
            )
        gaps = m.get("gaps") or []
        if gaps:
            issues.append({"chunk_id": m["chunk_id"], "issue": "manifest-reported gaps", "value": gaps})
    return issues
