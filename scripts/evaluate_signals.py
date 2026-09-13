#!/usr/bin/env python3
"""Evaluate candidate segmentation signals against real GT boundaries.

Persists and extends the methodology Day 1 used ad-hoc (never saved as
code) to measure whether a signal aligns with real process-transition
boundaries. Reproduces Day 1's three measured signals (deduplicated
app-switch, extracted-text presence, gap size) as a correctness check,
then evaluates the three signals Day 1 left as unmeasured hypotheses
(window-title change, browser navigation, clipboard timing).

Only usable on a dataset that has ground truth (gt_manifest.json per
session) — Dataset A today, any future labeled dataset later. Nothing in
this script is specific to Dataset A's session IDs, applications, or
process labels.

Usage:
    python scripts/evaluate_signals.py --dataset dataset_a --out reports/day2
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from procmine.loaders.events import load_session_events
from procmine.loaders.ground_truth import load_gt_manifest, parse_gt_manifest_executions
from procmine.paths import discover_dataset
from procmine.segmentation.signals import (
    app_switch_payload_key,
    deduplicate_consecutive,
    evaluate_signal,
    extract_boundaries,
    has_extracted_text,
    is_browser_navigation,
    is_clipboard_change,
    is_window_title_change,
)
from procmine.validation import ValidationReport


def gap_size_analysis(events_by_session, boundaries_by_session, executions_by_session) -> dict:
    """Reproduces Day 1's gap-size-at-boundary-vs-mid-execution comparison:
    the gap straddling a boundary vs. gaps strictly inside a closed
    execution's own [start_ts, end_ts) interval. Not a discrete event
    signal, so it doesn't fit evaluate_signal's shape."""
    import bisect

    boundary_gaps = []
    mid_gaps = []
    for session_id, events in events_by_session.items():
        ts = sorted(e.timestamp_ms for e in events)
        for b in boundaries_by_session.get(session_id, []):
            idx = bisect.bisect_left(ts, b.timestamp_ms)
            if 0 < idx < len(ts):
                boundary_gaps.append(ts[idx] - ts[idx - 1])

        for ex in executions_by_session.get(session_id, []):
            if ex.end_ts is None:
                continue
            s_ms = int(ex.start_ts.timestamp() * 1000)
            e_ms = int(ex.end_ts.timestamp() * 1000)
            lo = bisect.bisect_left(ts, s_ms)
            hi = bisect.bisect_left(ts, e_ms)
            inner = ts[lo:hi]
            for a, b_ts in zip(inner, inner[1:]):
                mid_gaps.append(b_ts - a)

    return {
        "boundary_gap_median_ms": statistics.median(boundary_gaps) if boundary_gaps else None,
        "boundary_gap_mean_ms": statistics.fmean(boundary_gaps) if boundary_gaps else None,
        "mid_execution_gap_median_ms": statistics.median(mid_gaps) if mid_gaps else None,
        "mid_execution_gap_mean_ms": statistics.fmean(mid_gaps) if mid_gaps else None,
        "n_boundary_gaps": len(boundary_gaps),
        "n_mid_execution_gaps": len(mid_gaps),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--window-ms", type=int, default=2000, help="alignment tolerance, matches Day 1's ±2s convention")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    sessions = discover_dataset(args.dataset)

    events_by_session = {}
    boundaries_by_session = {}
    executions_by_session = {}
    n_sessions_with_gt = 0

    for session in sessions:
        if session.gt_manifest_path is None:
            continue
        report = ValidationReport(scope=session.session_id)
        events = load_session_events(session, report)
        gt_manifest = load_gt_manifest(session.gt_manifest_path, report)
        if gt_manifest is None:
            continue
        executions = parse_gt_manifest_executions(gt_manifest)
        boundaries = extract_boundaries(session.session_id, executions)

        events_by_session[session.session_id] = events
        boundaries_by_session[session.session_id] = boundaries
        executions_by_session[session.session_id] = executions
        n_sessions_with_gt += 1

    total_boundaries = sum(len(b) for b in boundaries_by_session.values())
    total_resume = sum(1 for bs in boundaries_by_session.values() for b in bs if b.is_resume)
    print(
        f"{n_sessions_with_gt} sessions with GT, {total_boundaries} boundaries "
        f"({total_resume} resume-type, {total_boundaries - total_resume} normal)",
        file=sys.stderr,
    )

    # Deduplicated app_switch stream (reused across sessions for the
    # reproduction check below)
    deduped_events_by_session = {
        sid: deduplicate_consecutive(evts, "app_switch", app_switch_payload_key)
        for sid, evts in events_by_session.items()
    }

    def is_app_switch(e):
        return e.event_type == "app_switch"

    results = {}

    # --- Reproduction check: Day 1's three measured signals ---
    results["app_switch_deduplicated"] = evaluate_signal(
        "app_switch_deduplicated",
        deduped_events_by_session,
        boundaries_by_session,
        is_app_switch,
        window_ms=args.window_ms,
    ).to_dict()
    results["extracted_text"] = evaluate_signal(
        "extracted_text",
        events_by_session,
        boundaries_by_session,
        has_extracted_text,
        window_ms=args.window_ms,
    ).to_dict()
    results["gap_size"] = gap_size_analysis(events_by_session, boundaries_by_session, executions_by_session)

    # --- New signals (Day 1's unmeasured hypotheses) ---
    results["window_title_change"] = evaluate_signal(
        "window_title_change",
        events_by_session,
        boundaries_by_session,
        is_window_title_change,
        window_ms=args.window_ms,
    ).to_dict()
    results["browser_navigation"] = evaluate_signal(
        "browser_navigation",
        events_by_session,
        boundaries_by_session,
        is_browser_navigation,
        window_ms=args.window_ms,
    ).to_dict()
    results["clipboard_change"] = evaluate_signal(
        "clipboard_change",
        events_by_session,
        boundaries_by_session,
        is_clipboard_change,
        window_ms=args.window_ms,
    ).to_dict()

    out_path = args.out / f"signal_evaluation_{args.dataset.name}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str, ensure_ascii=False)
    print(f"Wrote {out_path}", file=sys.stderr)

    for name, r in results.items():
        if "boundary_coverage" in r:
            print(
                f"{name}: coverage={r['boundary_coverage']:.3f} precision={r['precision']:.3f} "
                f"lift={r['lift']} n_signal_events={r['n_signal_events']}",
                file=sys.stderr,
            )
        else:
            print(f"{name}: {r}", file=sys.stderr)


if __name__ == "__main__":
    main()
