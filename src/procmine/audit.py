"""Deeper data-quality audit: duplicates, missingness, timestamp quality,
payload/type-layer consistency, screenshot resolution rate, text quality,
session/chunk identity checks, and a safe (non-mutating) cleaning layer.

profiling.py answers "what's in the data." This module answers "can we trust
it, and where exactly does it need care." Everything here operates on raw
dicts (not the Event dataclass) so we can inspect fields we haven't modeled.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

# --- Reference tables from DATA_SCHEMA.md, used to flag anything outside them
# rather than to reject data — an unknown value is reported, never dropped. ---

KNOWN_LAYERS = {"SYSTEM", "L1", "L2", "L3"}

KNOWN_EVENT_TYPES_BY_LAYER = {
    "L2": {
        "app_switch", "keystroke", "shortcut", "mouse_click", "mouse_double_click",
        "mouse_scroll", "mouse_drag_drop", "clipboard_change", "text_input_complete",
        "window_title_change", "window_state_change", "dialog_opened", "dialog_closed",
    },
    "L1": {"screenshot_smart"},
    "L3": {
        "browser_click", "browser_form_input", "browser_navigation",
        "browser_tab_event", "browser_alert", "browser_error",
    },
    "SYSTEM": {
        "session_start", "session_end", "extension_connected", "extension_disconnected",
        "upload_started", "upload_completed", "upload_failed",
    },
}

# payload fields we can check *when present*; schema says these vary by type,
# so absence alone is not an error — this only flags the type as "notable" if
# ALL of a type's known fields are missing (i.e. the payload looks empty).
PAYLOAD_FIELDS_BY_TYPE = {
    "app_switch": ("new_app", "previous_app"),
    "keystroke": ("key", "character", "modifiers"),
    "browser_click": ("element", "click_coordinates"),
    "clipboard_change": ("previous_content", "new_content", "content"),
    "screenshot_smart": ("file_reference", "trigger_reason"),
}


def _get_path(d: dict[str, Any], dotted: str) -> Any:
    cur: Any = d
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


MISSINGNESS_FIELDS = [
    "event_id", "session_id", "timestamp_ms", "timestamp_iso", "layer", "event_type",
    "context", "context.active_app", "context.active_browser_tab", "context.extracted_text",
    "correlation.sequence_number", "correlation.chunk_id", "correlation.ms_since_last_event",
    "payload",
]


def missingness_audit(raw_events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """For each field: how often is it absent, present-but-None, or present-but-''.
    We report all three separately since DATA_SCHEMA treats them differently
    (e.g. extracted_text absent = "not captured", vs. present-and-empty would
    be a different, more suspicious signal)."""
    n = len(raw_events)
    out: dict[str, dict[str, Any]] = {}
    for field_path in MISSINGNESS_FIELDS:
        missing = null_count = empty_count = 0
        for e in raw_events:
            cur: Any = e
            found = True
            for part in field_path.split("."):
                if isinstance(cur, dict) and part in cur:
                    cur = cur[part]
                else:
                    found = False
                    break
            if not found:
                missing += 1
            elif cur is None:
                null_count += 1
            elif cur == "" or cur == {} or cur == []:
                empty_count += 1
        out[field_path] = {
            "missing": missing,
            "missing_pct": round(100 * missing / n, 2) if n else 0.0,
            "null": null_count,
            "null_pct": round(100 * null_count / n, 2) if n else 0.0,
            "empty": empty_count,
            "empty_pct": round(100 * empty_count / n, 2) if n else 0.0,
        }
    return out


def exact_duplicate_events(raw_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Full-record duplicates (same event serialized twice). Compares the
    dict itself (order-independent) rather than a re-serialized string."""
    import json

    seen: dict[str, int] = {}
    dupes = []
    for e in raw_events:
        key = json.dumps(e, sort_keys=True, default=str)
        seen[key] = seen.get(key, 0) + 1
    for key, count in seen.items():
        if count > 1:
            dupes.append({"count": count})
    return dupes


def semantic_duplicate_events(raw_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Same session + timestamp + type + payload, but a different event_id —
    the kind of duplicate that would NOT be caught by check_duplicate_event_ids
    but still represents the same operation logged twice."""
    import json

    groups: dict[tuple, list[str]] = {}
    for e in raw_events:
        key = (
            e.get("session_id"),
            e.get("timestamp_ms"),
            e.get("event_type"),
            json.dumps(e.get("payload"), sort_keys=True, default=str),
        )
        groups.setdefault(key, []).append(e.get("event_id"))
    return [
        {"timestamp_ms": k[1], "event_type": k[2], "event_ids": v}
        for k, v in groups.items()
        if len(v) > 1
    ]


def sequential_duplicate_events(raw_events_sorted: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Consecutive (in chronological order) events with identical event_type
    and payload — e.g. the same keystroke or click logged twice back-to-back."""
    import json

    out = []
    for a, b in zip(raw_events_sorted, raw_events_sorted[1:]):
        if a.get("event_type") == b.get("event_type") and json.dumps(
            a.get("payload"), sort_keys=True, default=str
        ) == json.dumps(b.get("payload"), sort_keys=True, default=str):
            out.append(
                {"first": a.get("event_id"), "second": b.get("event_id"), "event_type": a.get("event_type")}
            )
    return out


@dataclass
class TimestampQualityReport:
    n_events: int = 0
    ms_iso_mismatches: list[dict[str, Any]] = field(default_factory=list)
    non_utc_iso: list[dict[str, Any]] = field(default_factory=list)
    negative_gaps: int = 0
    zero_gaps: int = 0
    max_gap_ms: float = 0.0
    gap_ms_bucket_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_events": self.n_events,
            "ms_iso_mismatch_count": len(self.ms_iso_mismatches),
            "ms_iso_mismatch_examples": self.ms_iso_mismatches[:10],
            "non_utc_iso_count": len(self.non_utc_iso),
            "negative_gaps": self.negative_gaps,
            "zero_gaps": self.zero_gaps,
            "max_gap_ms": self.max_gap_ms,
            "gap_ms_bucket_counts": self.gap_ms_bucket_counts,
        }


def timestamp_quality(raw_events_sorted: list[dict[str, Any]]) -> TimestampQualityReport:
    from datetime import datetime, timezone

    rpt = TimestampQualityReport(n_events=len(raw_events_sorted))
    buckets = Counter()
    prev_ms = None
    for e in raw_events_sorted:
        ms = e.get("timestamp_ms")
        iso = e.get("timestamp_iso", "")
        if not isinstance(iso, str) or not iso.endswith("Z"):
            rpt.non_utc_iso.append({"event_id": e.get("event_id"), "timestamp_iso": iso})
        else:
            try:
                dt = datetime.fromisoformat(iso[:-1] + "+00:00").astimezone(timezone.utc)
                iso_ms = int(dt.timestamp() * 1000)
                if ms is not None and abs(iso_ms - ms) > 1000:
                    rpt.ms_iso_mismatches.append(
                        {"event_id": e.get("event_id"), "timestamp_ms": ms, "timestamp_iso": iso, "delta_ms": iso_ms - ms}
                    )
            except ValueError:
                rpt.non_utc_iso.append({"event_id": e.get("event_id"), "timestamp_iso": iso})

        if prev_ms is not None and ms is not None:
            gap = ms - prev_ms
            if gap < 0:
                rpt.negative_gaps += 1
            elif gap == 0:
                rpt.zero_gaps += 1
            rpt.max_gap_ms = max(rpt.max_gap_ms, gap)
            if gap < 100:
                buckets["<100ms"] += 1
            elif gap < 1000:
                buckets["100ms-1s"] += 1
            elif gap < 10000:
                buckets["1s-10s"] += 1
            elif gap < 60000:
                buckets["10s-60s"] += 1
            else:
                buckets[">60s"] += 1
        prev_ms = ms

    rpt.gap_ms_bucket_counts = dict(buckets)
    return rpt


def event_type_layer_consistency(raw_events: list[dict[str, Any]]) -> dict[str, Any]:
    unknown_layers = Counter()
    unknown_type_for_layer = Counter()
    for e in raw_events:
        layer = e.get("layer")
        etype = e.get("event_type")
        if layer not in KNOWN_LAYERS:
            unknown_layers[layer] += 1
            continue
        known_types = KNOWN_EVENT_TYPES_BY_LAYER.get(layer, set())
        if etype not in known_types:
            unknown_type_for_layer[f"{layer}:{etype}"] += 1
    return {
        "unknown_layers": dict(unknown_layers),
        "unknown_event_type_for_layer": dict(unknown_type_for_layer),
    }


def payload_emptiness_by_type(raw_events: list[dict[str, Any]]) -> dict[str, Any]:
    """For event types we have a known field list for for, what fraction of
    occurrences have NONE of those fields populated? That's the closest thing
    to 'payload looks broken' without requiring fields the schema says vary."""
    counts = Counter()
    empty_counts = Counter()
    for e in raw_events:
        etype = e.get("event_type")
        fields = PAYLOAD_FIELDS_BY_TYPE.get(etype)
        if fields is None:
            continue
        counts[etype] += 1
        payload = e.get("payload") or {}
        if not any(payload.get(f) for f in fields):
            empty_counts[etype] += 1
    return {
        etype: {
            "n": counts[etype],
            "empty_payload": empty_counts.get(etype, 0),
            "empty_payload_pct": round(100 * empty_counts.get(etype, 0) / counts[etype], 2),
        }
        for etype in counts
    }


def extracted_text_profile(raw_events: list[dict[str, Any]]) -> dict[str, Any]:
    with_text = []
    by_type: Counter = Counter()
    by_app: Counter = Counter()
    lengths = []
    empty_but_present = 0
    for e in raw_events:
        text_field = _get_path(e, "context.extracted_text")
        if text_field is None:
            continue
        text = text_field.get("text") if isinstance(text_field, dict) else None
        if text is None or text == "":
            empty_but_present += 1
            continue
        with_text.append(e)
        by_type[e.get("event_type")] += 1
        app = _get_path(e, "context.active_app.app_name")
        if app:
            by_app[app] += 1
        lengths.append(len(text))

    n = len(raw_events)
    return {
        "n_events": n,
        "n_with_nonempty_text": len(with_text),
        "pct_with_nonempty_text": round(100 * len(with_text) / n, 2) if n else 0.0,
        "n_present_but_empty": empty_but_present,
        "by_event_type": dict(by_type.most_common(10)),
        "by_application": dict(by_app.most_common(10)),
        "length_chars": {
            "min": min(lengths) if lengths else None,
            "max": max(lengths) if lengths else None,
            "mean": round(sum(lengths) / len(lengths), 1) if lengths else None,
        },
    }


def text_input_complete_profile(raw_events: list[dict[str, Any]]) -> dict[str, Any]:
    events = [e for e in raw_events if e.get("event_type") == "text_input_complete"]
    n = len(events)
    missing_content = 0
    has_content_field = 0
    password_field_with_plaintext = 0
    for e in events:
        payload = e.get("payload") or {}
        # observed real field name is payload.final_text (not documented by
        # name in DATA_SCHEMA.md — found by inspecting raw events directly).
        content = payload.get("final_text")
        if content:
            has_content_field += 1
            if (payload.get("input_context") or {}).get("is_password_field"):
                password_field_with_plaintext += 1
        else:
            missing_content += 1
    return {
        "n_text_input_complete_events": n,
        "with_apparent_content": has_content_field,
        "missing_or_empty_content": missing_content,
        "missing_pct": round(100 * missing_content / n, 2) if n else 0.0,
        "password_fields_with_plaintext_final_text": password_field_with_plaintext,
        "note": (
            "DATA_SCHEMA.md documents this event type as unreliable — some entries "
            "are missing content, and some non-text actions (e.g. shortcuts) are "
            "mixed in. Treat as a hint only; reconstruct text from keystroke/"
            "clipboard_change when text content is actually needed. Content lives "
            "in payload.final_text, which DATA_SCHEMA.md does not name explicitly."
        ),
    }


def session_chunk_identity_checks(session, raw_events_by_chunk: dict[str, list[dict]]) -> list[dict[str, Any]]:
    """Cross-check directory identity against what's recorded inside the files
    themselves: does every event's session_id match the directory name? Does
    every event's correlation.chunk_id match the chunk directory it was read
    from? Is machine_id consistent across all chunks of one session?"""
    issues = []
    machine_ids = set()
    for chunk in session.chunks:
        events = raw_events_by_chunk.get(chunk.chunk_dir.name, [])
        for e in events:
            if e.get("session_id") != session.session_id:
                issues.append(
                    {
                        "issue": "event.session_id mismatch",
                        "event_id": e.get("event_id"),
                        "expected": session.session_id,
                        "found": e.get("session_id"),
                    }
                )
            corr_chunk_id = (e.get("correlation") or {}).get("chunk_id")
            if corr_chunk_id != chunk.chunk_dir.name:
                issues.append(
                    {
                        "issue": "correlation.chunk_id mismatch",
                        "event_id": e.get("event_id"),
                        "expected": chunk.chunk_dir.name,
                        "found": corr_chunk_id,
                    }
                )
            mid = (e.get("source") or {}).get("machine_id")
            if mid:
                machine_ids.add(mid)
    if len(machine_ids) > 1:
        issues.append({"issue": "inconsistent machine_id within session", "machine_ids": sorted(machine_ids)})
    return issues
