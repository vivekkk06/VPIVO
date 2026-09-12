#!/usr/bin/env python3
"""Run the full Day-1 data-quality audit (duplicates, missingness, timestamp
quality, payload/type-layer consistency, screenshot resolution, text quality,
session/chunk identity, GT deep-checks, cleaning simulation) across a dataset
and write one consolidated JSON that the Day 1 markdown reports are written
against.

Usage:
    python scripts/audit_dataset.py --dataset dataset_a --out reports/day1
    python scripts/audit_dataset.py --dataset dataset_b --out reports/day1
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from procmine.audit import (
    event_type_layer_consistency,
    exact_duplicate_events,
    extracted_text_profile,
    missingness_audit,
    payload_emptiness_by_type,
    semantic_duplicate_events,
    sequential_duplicate_events,
    session_chunk_identity_checks,
    text_input_complete_profile,
    timestamp_quality,
)
from procmine.cleaning import clean_session_events
from procmine.loaders.events import read_jsonl
from procmine.paths import discover_dataset
from procmine.validation import ValidationReport


def audit_session(session) -> dict:
    report = ValidationReport(scope=f"session:{session.session_id}")

    raw_by_chunk: dict[str, list[dict]] = {}
    all_raw: list[dict] = []
    for chunk in session.chunks:
        raw = read_jsonl(chunk.events_path, report)
        raw_by_chunk[chunk.chunk_dir.name] = raw
        all_raw.extend(raw)

    all_raw_sorted = sorted(all_raw, key=lambda e: e.get("timestamp_ms", 0))

    identity_issues = session_chunk_identity_checks(session, raw_by_chunk)
    cleaned, cleaning_log = clean_session_events(all_raw)
    semantic_dupes = semantic_duplicate_events(all_raw)
    sequential_dupes = sequential_duplicate_events(all_raw_sorted)
    sequential_dupes_by_type = dict(Counter(d["event_type"] for d in sequential_dupes))

    return {
        "session_id": session.session_id,
        "n_events": len(all_raw),
        "malformed_json_lines": len(report.malformed_json_lines),
        "exact_duplicates": exact_duplicate_events(all_raw),
        "semantic_duplicates": semantic_dupes[:20],  # cap for report size
        "n_semantic_duplicate_groups": len(semantic_dupes),
        "sequential_duplicates_count": len(sequential_dupes),
        "sequential_duplicates_by_type": sequential_dupes_by_type,
        "missingness": missingness_audit(all_raw),
        "timestamp_quality": timestamp_quality(all_raw_sorted).to_dict(),
        "type_layer_consistency": event_type_layer_consistency(all_raw),
        "payload_emptiness_by_type": payload_emptiness_by_type(all_raw),
        "extracted_text": extracted_text_profile(all_raw),
        "text_input_complete": text_input_complete_profile(all_raw),
        "session_chunk_identity_issues": identity_issues,
        "cleaning_log": cleaning_log,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    sessions = discover_dataset(args.dataset)

    per_session = [audit_session(s) for s in sessions]
    elapsed = time.time() - t0

    # Dataset-level rollups
    total_events = sum(s["n_events"] for s in per_session)
    total_exact_dupes = sum(len(s["exact_duplicates"]) for s in per_session)
    total_semantic_dupe_groups = sum(s["n_semantic_duplicate_groups"] for s in per_session)
    total_sequential_dupes = sum(s["sequential_duplicates_count"] for s in per_session)
    total_identity_issues = sum(len(s["session_chunk_identity_issues"]) for s in per_session)
    sequential_dupes_by_type: dict = {}
    for s in per_session:
        for k, v in s["sequential_duplicates_by_type"].items():
            sequential_dupes_by_type[k] = sequential_dupes_by_type.get(k, 0) + v

    unknown_layers: dict = {}
    unknown_types: dict = {}
    for s in per_session:
        for k, v in s["type_layer_consistency"]["unknown_layers"].items():
            unknown_layers[k] = unknown_layers.get(k, 0) + v
        for k, v in s["type_layer_consistency"]["unknown_event_type_for_layer"].items():
            unknown_types[k] = unknown_types.get(k, 0) + v

    result = {
        "dataset": args.dataset.name,
        "n_sessions": len(sessions),
        "n_events_total": total_events,
        "runtime_seconds": round(elapsed, 2),
        "events_per_second": round(total_events / elapsed, 1) if elapsed > 0 else None,
        "total_exact_duplicate_groups": total_exact_dupes,
        "total_semantic_duplicate_groups": total_semantic_dupe_groups,
        "total_sequential_duplicates": total_sequential_dupes,
        "sequential_duplicates_by_type": sequential_dupes_by_type,
        "total_session_chunk_identity_issues": total_identity_issues,
        "unknown_layers": unknown_layers,
        "unknown_event_type_for_layer": unknown_types,
        "sessions": per_session,
    }

    out_path = args.out / f"full_audit_{args.dataset.name}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str, ensure_ascii=False)

    print(f"Wrote {out_path}", file=sys.stderr)
    print(
        f"{args.dataset.name}: {len(sessions)} sessions, {total_events} events, "
        f"{elapsed:.2f}s ({result['events_per_second']} events/s)",
        file=sys.stderr,
    )
    print(
        f"exact_dupe_groups={total_exact_dupes} semantic_dupe_groups={total_semantic_dupe_groups} "
        f"sequential_dupes={total_sequential_dupes} identity_issues={total_identity_issues} "
        f"unknown_layers={unknown_layers} unknown_types={unknown_types}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
