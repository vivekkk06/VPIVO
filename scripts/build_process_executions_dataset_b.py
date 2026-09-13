#!/usr/bin/env python3
"""Section 3: build the final execution records for Dataset B.

Pipeline: raw events -> sorted CanonicalEvent stream -> system-change
candidate boundaries (Section 2, corrected for the forward-fill /
sandwiched-noise-event issue) -> short immediate leave-and-return
detours merged back in (Section 3, threshold measured from Dataset B's
own return-pattern distribution: p25 = 5 events) -> Execution records
with ordered, data-derived steps.

No Dataset-A fitted architecture (V1/V2/Design 2/Combined) is imported
or reused. Dataset B has no ground truth; this script does not attempt
to score against one.

Usage:
    python scripts/build_process_executions_dataset_b.py --dataset dataset_b --out reports/day3
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from procmine.loaders.events import load_session_events
from procmine.paths import discover_dataset
from procmine.process_discovery.boundaries import system_change_boundaries
from procmine.process_discovery.execution_construction import build_executions, merge_leave_and_return
from procmine.segmentation.canonical import to_canonical_stream
from procmine.validation import ValidationReport

MERGE_MAX_AWAY_EVENTS = 5  # p25 of Dataset B's own immediate return-pattern away-span (see process_discovery.md)


def dist_summary(values):
    if not values:
        return {"n": 0}
    s = sorted(values)
    def pct(p):
        return s[min(int(len(s) * p), len(s) - 1)]
    return {
        "n": len(values), "mean": round(statistics.fmean(values), 2), "median": statistics.median(values),
        "p25": pct(0.25), "p75": pct(0.75), "min": min(values), "max": max(values),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    sessions = discover_dataset(args.dataset)
    all_executions = []
    per_session_counts = {}
    for s in sessions:
        report = ValidationReport(scope=s.session_id)
        events = load_session_events(s, report)
        if not events:
            continue
        operator = events[0].raw.get("source", {}).get("machine_id", "unknown")
        canonical = to_canonical_stream(events)
        raw_boundary = system_change_boundaries(canonical)
        merged_boundary = merge_leave_and_return(canonical, raw_boundary, max_away_events=MERGE_MAX_AWAY_EVENTS)
        execs = build_executions(s.session_id, operator, canonical, merged_boundary)
        all_executions.extend(execs)
        per_session_counts[s.session_id] = {
            "operator": operator, "n_events": len(events),
            "n_raw_segments": sum(raw_boundary) + 1,
            "n_executions_after_merge": len(execs),
        }

    print(f"{len(sessions)} sessions, {len(all_executions)} executions built after leave-and-return merge "
          f"(threshold={MERGE_MAX_AWAY_EVENTS} events)", file=sys.stderr)
    for sid, c in per_session_counts.items():
        print(f"  {sid} ({c['operator']}): {c['n_raw_segments']} raw -> {c['n_executions_after_merge']} merged", file=sys.stderr)

    event_counts = [e.event_count for e in all_executions]
    durations = [e.duration_ms for e in all_executions]
    print(f"\nExecution event-count distribution: {dist_summary(event_counts)}", file=sys.stderr)
    print(f"Execution duration (ms) distribution: {dist_summary(durations)}", file=sys.stderr)

    out_path = args.out / f"process_executions_{args.dataset.name}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump({
            "n_sessions": len(sessions),
            "merge_max_away_events": MERGE_MAX_AWAY_EVENTS,
            "per_session_summary": per_session_counts,
            "event_count_distribution": dist_summary(event_counts),
            "duration_ms_distribution": dist_summary(durations),
            "executions": [e.to_dict() for e in all_executions],
        }, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nWrote {out_path}", file=sys.stderr)
    print("Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
