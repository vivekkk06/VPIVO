#!/usr/bin/env python3
"""Section 2 of the Dataset-B process-discovery work: build the
time-ordered event series per session and compare several candidate
execution-boundary methods against Dataset B's own evidence.

Dataset B has no ground truth, so this is NOT an F1/precision-recall
comparison like Day 2's Dataset-A work -- it is a descriptive
comparison (segment count, length distribution) plus a qualitative
check (does a method's boundary line up with a real system/window
change, spot-checked against actual window titles). No method here is
carried over from Dataset A's fitted architecture (V1/V2/Design 2/
Combined are not imported); only the generic, dataset-agnostic
CanonicalEvent/TransitionFeatures representation is reused.

Usage:
    python scripts/discover_executions_dataset_b.py --dataset dataset_b --out reports/day3
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from procmine.loaders.events import load_session_events
from procmine.paths import discover_dataset
from procmine.process_discovery.boundaries import (
    application_change_boundaries,
    debounced_system_change_boundaries,
    gap_threshold_boundaries,
    system_change_boundaries,
)
from procmine.process_discovery.system_identity import system_identity
from procmine.segmentation.canonical import to_canonical_stream
from procmine.segmentation.features import extract_transition_features
from procmine.validation import ValidationReport


def dist_summary(values):
    if not values:
        return {"n": 0}
    s = sorted(values)
    def pct(p):
        return s[min(int(len(s) * p), len(s) - 1)]
    return {
        "n": len(values), "mean": round(statistics.fmean(values), 2),
        "median": statistics.median(values), "p25": pct(0.25), "p75": pct(0.75),
        "min": min(values), "max": max(values),
    }


def segments_from_boundary(n_events: int, boundary: list[bool]) -> list[tuple[int, int]]:
    if n_events == 0:
        return []
    bounds, start = [], 0
    for i, b in enumerate(boundary):
        if b:
            bounds.append((start, i))
            start = i + 1
    bounds.append((start, n_events - 1))
    return bounds


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    sessions = discover_dataset(args.dataset)
    per_session = {}
    for s in sessions:
        report = ValidationReport(scope=s.session_id)
        events = load_session_events(s, report)
        canonical = to_canonical_stream(events)
        feats = extract_transition_features(canonical)
        per_session[s.session_id] = {"canonical": canonical, "feats": feats}
    session_ids = sorted(per_session.keys())
    print(f"{len(session_ids)} sessions loaded", file=sys.stderr)

    # === Dataset-B-own gap percentiles (recomputed here, not reused from ===
    # === the profile report, so this script is self-contained) ===
    all_gaps = sorted(f.delta_t_ms for d in per_session.values() for f in d["feats"])
    def gap_pct(p):
        return all_gaps[min(int(len(all_gaps) * p), len(all_gaps) - 1)]
    gap_thresholds = {"p90": gap_pct(0.90), "p95": gap_pct(0.95), "p99": gap_pct(0.99)}
    print(f"Dataset B gap percentiles used as thresholds: {gap_thresholds}", file=sys.stderr)

    methods = {}
    for name, tau in gap_thresholds.items():
        methods[f"gap_{name}_{tau}ms"] = lambda d, tau=tau: gap_threshold_boundaries(d["feats"], tau)
    methods["application_change"] = lambda d: application_change_boundaries(d["feats"])
    methods["system_change"] = lambda d: system_change_boundaries(d["canonical"])
    for k in (2, 3, 5, 8, 12):
        methods[f"system_change_debounced_{k}"] = lambda d, k=k: debounced_system_change_boundaries(d["canonical"], min_persist=k)

    comparison = {}
    for method_name, fn in methods.items():
        seg_lengths_events, seg_lengths_ms, n_boundaries_per_session = [], [], []
        for sid in session_ids:
            d = per_session[sid]
            boundary = fn(d)
            n_boundaries_per_session.append(sum(boundary))
            segs = segments_from_boundary(len(d["canonical"]), boundary)
            for start, end in segs:
                seg_lengths_events.append(end - start + 1)
                seg_lengths_ms.append(d["canonical"][end].timestamp_ms - d["canonical"][start].timestamp_ms)
        comparison[method_name] = {
            "total_boundaries": sum(n_boundaries_per_session),
            "boundaries_per_session": dist_summary(n_boundaries_per_session),
            "segment_length_events": dist_summary(seg_lengths_events),
            "segment_length_ms": dist_summary(seg_lengths_ms),
            "n_segments_total": len(seg_lengths_events),
        }

    print("\n--- Method comparison (descriptive, no GT to score against) ---", file=sys.stderr)
    for name, c in comparison.items():
        print(f"{name:<28} n_segments={c['n_segments_total']:<6} "
              f"median_len_events={c['segment_length_events'].get('median')} "
              f"median_len_ms={c['segment_length_ms'].get('median')}", file=sys.stderr)

    # === Qualitative spot-check: for system_change_debounced_2, sample a ===
    # === few segments from one session and print their dominant system   ===
    # === identity + a real window_title, to see if segments look like    ===
    # === coherent single-system stretches.                                ===
    spot_check_sid = session_ids[0]
    d = per_session[spot_check_sid]
    boundary = debounced_system_change_boundaries(d["canonical"], min_persist=2)
    segs = segments_from_boundary(len(d["canonical"]), boundary)
    spot_check = []
    for start, end in segs[:15]:
        seg_events = d["canonical"][start:end + 1]
        ids = Counter(system_identity(e) for e in seg_events if system_identity(e) is not None)
        titles = Counter(e.window_title for e in seg_events if e.window_title)
        spot_check.append({
            "n_events": end - start + 1,
            "duration_ms": seg_events[-1].timestamp_ms - seg_events[0].timestamp_ms,
            "dominant_system_ids": ids.most_common(2),
            "dominant_window_titles": titles.most_common(2),
        })
    print(f"\n--- Spot check: first 15 segments of {spot_check_sid} under system_change_debounced_2 ---", file=sys.stderr)
    for i, sc in enumerate(spot_check):
        print(f"  seg{i}: n={sc['n_events']} dur={sc['duration_ms']}ms sys={sc['dominant_system_ids']} title={sc['dominant_window_titles']}", file=sys.stderr)

    out = {
        "n_sessions": len(session_ids),
        "gap_thresholds_ms": gap_thresholds,
        "method_comparison": comparison,
        "spot_check_session": spot_check_sid,
        "spot_check_segments_system_change_debounced_2": spot_check,
    }
    out_path = args.out / f"execution_boundary_method_comparison_{args.dataset.name}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nWrote {out_path}", file=sys.stderr)
    print("Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
