#!/usr/bin/env python3
"""Day 3 deliverable: convert the already-produced Dataset B execution
records into the exact `segments.jsonl` schema the assignment brief
requires.

This is a pure FORMAT conversion, not a re-segmentation. It does not
run any segmentation logic, does not invent, merge, split, or drop any
execution, and does not change any boundary decision -- every record
in the output corresponds 1:1 to a record already present in
`reports/day3/process_executions_dataset_b.json` (Day 3's
system-change-boundary + leave-and-return-merge pipeline, built fresh
for Dataset B per the assignment's own instruction not to assume
Dataset A's segmentation approach transfers -- see
`reports/day3/process_discovery.md`).

Field mapping:
  session_id -> execution's own `session_id` (unchanged)
  start/end  -> execution's `start_ms`/`end_ms`, converted to ISO 8601
                UTC with millisecond precision (e.g.
                "2026-07-01T16:44:24.390Z")
  label      -> the execution's `dominant_context`'s `readable_name`
                from `reports/day3/process_profiles_dataset_b.json`
                (already-computed, already-consistent per process; a
                process id that has no curated readable name keeps its
                own process-id string as the label -- still consistent,
                never blank). The same `dominant_context` always maps
                to the same label, by construction of the lookup
                (single dict, keyed by process id), which is exactly
                the "same process -> same label" requirement.

One known, explicit adjustment, logged below: 11 of 645 executions are
genuine single-event executions where `start_ms == end_ms` (the
recorded activity was instantaneous at millisecond resolution -- a
real, previously-documented finding, not a bug in this script). The
`segments.jsonl` schema requires `start < end`; for these 11 records
only, `end` is nudged forward by 1 millisecond in the OUTPUT
TIMESTAMP ONLY. This does not change which events belong to the
execution, does not merge/split/invent anything, and is reported
explicitly so it is never mistaken for a real duration.

Usage:
    python scripts/build_segments_jsonl.py --day3-dir reports/day3 --out segments.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def ms_to_iso_utc(ms: int) -> str:
    dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms % 1000:03d}Z"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day3-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    executions_data = json.loads((args.day3_dir / "process_executions_dataset_b.json").read_text(encoding="utf-8"))
    profiles = json.loads((args.day3_dir / "process_profiles_dataset_b.json").read_text(encoding="utf-8"))
    label_by_process_id = {pid: p["readable_name"] for pid, p in profiles.items()}

    executions = executions_data["executions"]
    # Deterministic order: by session_id, then start_ms -- matches the
    # order the underlying data is already in (chronological per
    # session), made explicit here rather than left to input order.
    executions_sorted = sorted(executions, key=lambda e: (e["session_id"], e["start_ms"]))

    n_zero_duration_nudged = 0
    lines = []
    for ex in executions_sorted:
        start_ms, end_ms = ex["start_ms"], ex["end_ms"]
        if start_ms >= end_ms:
            end_ms = start_ms + 1
            n_zero_duration_nudged += 1

        pid = ex["dominant_context"]
        label = label_by_process_id.get(pid, pid)

        record = {
            "session_id": ex["session_id"],
            "start": ms_to_iso_utc(start_ms),
            "end": ms_to_iso_utc(end_ms),
            "label": label,
        }
        lines.append(json.dumps(record, ensure_ascii=False))

    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Wrote {len(lines)} records to {args.out}", file=sys.stderr)
    print(f"Zero-duration executions (start_ms == end_ms) found and given a "
          f"1ms output-timestamp nudge so start < end holds: {n_zero_duration_nudged}", file=sys.stderr)
    print(f"Distinct session_ids: {len(set(ex['session_id'] for ex in executions))}", file=sys.stderr)
    print(f"Distinct labels: {len(set(label_by_process_id.get(ex['dominant_context'], ex['dominant_context']) for ex in executions))}", file=sys.stderr)
    print("Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
