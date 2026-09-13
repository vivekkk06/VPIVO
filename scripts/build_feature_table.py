#!/usr/bin/env python3
"""Build the per-transition feature table for a dataset, labeled against
GT when available, and report gap-distribution evidence across the
regimes Phase 3 requires: within an execution, at a normal (non-resume)
boundary, at a resume boundary, and across a chunk-file transition.

This is the shared (X_i, y_i) artifact Stage 5/6's baseline and learned
model will consume — built once here rather than recomputed ad hoc.

Usage:
    python scripts/build_feature_table.py --dataset dataset_a --out reports/day2
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
from procmine.segmentation.canonical import to_canonical_stream
from procmine.segmentation.features import extract_transition_features, label_transitions
from procmine.segmentation.signals import extract_boundaries
from procmine.validation import ValidationReport


def summarize(values: list[int]) -> dict:
    if not values:
        return {"n": 0}
    values_sorted = sorted(values)
    n = len(values_sorted)
    return {
        "n": n,
        "median": statistics.median(values_sorted),
        "mean": round(statistics.fmean(values_sorted), 1),
        "p10": values_sorted[int(n * 0.10)],
        "p90": values_sorted[min(int(n * 0.90), n - 1)],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    sessions = discover_dataset(args.dataset)
    all_rows = []

    interior_gaps = []
    normal_boundary_gaps = []
    resume_boundary_gaps = []
    chunk_boundary_gaps = []
    chunk_boundary_non_gt_gaps = []  # chunk crossings that are NOT also a GT boundary

    per_session_boundary_gap_median: dict[str, float] = {}

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
        if not boundaries:
            continue
        n_sessions_with_gt += 1

        canonical = to_canonical_stream(events)
        feats = extract_transition_features(canonical)
        labeled = label_transitions(feats, [(b.timestamp_ms, b.is_resume) for b in boundaries])

        session_boundary_gaps = []
        for lt in labeled:
            f = lt.features
            row = {
                "session_id": f.session_id,
                "event_i_id": f.event_i_id,
                "delta_t_ms": f.delta_t_ms,
                "log1p_delta_t_ms": round(f.log1p_delta_t_ms, 4),
                "density_before": f.density_before,
                "density_after": f.density_after,
                "application_changed": f.application_changed,
                "window_title_changed": f.window_title_changed,
                "browser_domain_changed": f.browser_domain_changed,
                "interaction_category_changed": f.interaction_category_changed,
                "extracted_text_at_transition": f.extracted_text_at_transition,
                "chunk_boundary": f.chunk_boundary,
                "is_boundary": lt.is_boundary,
                "is_resume": lt.is_resume,
            }
            all_rows.append(row)

            if lt.is_boundary:
                session_boundary_gaps.append(f.delta_t_ms)
                if lt.is_resume:
                    resume_boundary_gaps.append(f.delta_t_ms)
                else:
                    normal_boundary_gaps.append(f.delta_t_ms)
            else:
                interior_gaps.append(f.delta_t_ms)

            if f.chunk_boundary:
                chunk_boundary_gaps.append(f.delta_t_ms)
                if not lt.is_boundary:
                    chunk_boundary_non_gt_gaps.append(f.delta_t_ms)

        if session_boundary_gaps:
            per_session_boundary_gap_median[session.session_id] = statistics.median(
                session_boundary_gaps
            )

    table_path = args.out / f"feature_table_{args.dataset.name}.json"
    with table_path.open("w", encoding="utf-8") as f:
        json.dump(all_rows, f, indent=None, ensure_ascii=False)
    print(f"Wrote {table_path} ({len(all_rows)} rows)", file=sys.stderr)

    medians = list(per_session_boundary_gap_median.values())
    regime_summary = {
        "interior": summarize(interior_gaps),
        "normal_boundary": summarize(normal_boundary_gaps),
        "resume_boundary": summarize(resume_boundary_gaps),
        "chunk_boundary_any": summarize(chunk_boundary_gaps),
        "chunk_boundary_not_a_gt_boundary": summarize(chunk_boundary_non_gt_gaps),
        "per_session_boundary_gap_median": {
            "n_sessions": len(medians),
            "mean_of_medians": round(statistics.fmean(medians), 1) if medians else None,
            "std_of_medians": round(statistics.pstdev(medians), 1) if len(medians) > 1 else None,
            "min": min(medians) if medians else None,
            "max": max(medians) if medians else None,
        },
        "n_sessions_with_gt": n_sessions_with_gt,
        "n_total_transitions": len(all_rows),
    }
    summary_path = args.out / f"time_gap_regime_summary_{args.dataset.name}.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(regime_summary, f, indent=2, ensure_ascii=False)
    print(f"Wrote {summary_path}", file=sys.stderr)
    print(json.dumps(regime_summary, indent=2), file=sys.stderr)


if __name__ == "__main__":
    main()
