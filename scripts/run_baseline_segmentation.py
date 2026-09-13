#!/usr/bin/env python3
"""Threshold sensitivity sweep + baseline comparison against real GT.

Builds features fresh per session (reusing Stage 3/4 modules), sweeps a
range of temporal thresholds for Baseline 1 (temporal-only), reports
boundary-level (precision/recall/F1) and execution-level (over/under-
segmentation) metrics pooled across all sessions, then compares Baselines
2 and 3 (temporal + context) against Baseline 1 at the best-F1 threshold
found. Also reports per-session F1 at that threshold so no bad session is
hidden behind the aggregate.

Usage:
    python scripts/run_baseline_segmentation.py --dataset dataset_a --out reports/day2
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
from procmine.segmentation.baselines import (
    baseline_temporal_and_context,
    baseline_temporal_only,
    baseline_temporal_or_context,
)
from procmine.segmentation.canonical import to_canonical_stream
from procmine.segmentation.evaluation import (
    boundary_metrics,
    execution_metrics,
    segments_from_boundaries,
)
from procmine.segmentation.features import extract_transition_features, label_transitions
from procmine.segmentation.signals import extract_boundaries
from procmine.validation import ValidationReport

THRESHOLDS_MS = [50, 100, 200, 300, 400, 500, 600, 750, 900, 1000, 1200, 1500, 2000, 3000, 5000, 7500, 10000]

KNOWN_INCOMPLETE_SESSION = "ses_20260701-152030-CHAITANYA0BCF"  # see time_gap_analysis.md


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    sessions = discover_dataset(args.dataset)

    per_session_data = []  # (session_id, labeled_transitions, event_timestamps, executions)
    for session in sessions:
        if session.gt_manifest_path is None:
            continue
        report = ValidationReport(scope=session.session_id)
        events = load_session_events(session, report)
        gt_manifest = load_gt_manifest(session.gt_manifest_path, report)
        if gt_manifest is None or not events:
            continue
        executions = parse_gt_manifest_executions(gt_manifest)
        boundaries = extract_boundaries(session.session_id, executions)
        canonical = to_canonical_stream(events)
        feats = extract_transition_features(canonical)
        labeled = label_transitions(feats, [(b.timestamp_ms, b.is_resume) for b in boundaries])
        ts = [e.timestamp_ms for e in events]
        per_session_data.append((session.session_id, labeled, ts, executions))

    print(f"{len(per_session_data)} sessions loaded", file=sys.stderr)

    # --- Threshold sweep for Baseline 1 ---
    sweep_results = []
    for tau in THRESHOLDS_MS:
        all_labeled = []
        all_preds = []
        over_seg_num, over_seg_den = 0.0, 0
        under_seg_num, under_seg_den = 0.0, 0

        for session_id, labeled, ts, executions in per_session_data:
            feats = [lt.features for lt in labeled]
            preds = baseline_temporal_only(feats, tau)
            all_labeled.extend(labeled)
            all_preds.extend(preds)

            segs = segments_from_boundaries(session_id, ts, preds)
            em = execution_metrics(executions, segs)
            over_seg_num += em.over_segmentation_rate * em.n_gt_executions
            over_seg_den += em.n_gt_executions
            # under-seg rate already averaged over segments-with-overlap; weight by that count
            n_overlap_segs = em.n_predicted_segments - em.n_pure_noise_segments
            under_seg_num += em.under_segmentation_rate * n_overlap_segs
            under_seg_den += n_overlap_segs

        bm = boundary_metrics(all_labeled, all_preds)
        sweep_results.append(
            {
                "tau_ms": tau,
                "precision": round(bm.precision, 4),
                "recall": round(bm.recall, 4),
                "f1": round(bm.f1, 4),
                "over_segmentation_rate": round(over_seg_num / over_seg_den, 4) if over_seg_den else None,
                "under_segmentation_rate": round(under_seg_num / under_seg_den, 4) if under_seg_den else None,
            }
        )

    best = max(sweep_results, key=lambda r: r["f1"])
    print("Threshold sweep (Baseline 1: temporal-only):", file=sys.stderr)
    for r in sweep_results:
        marker = "  <-- best F1" if r["tau_ms"] == best["tau_ms"] else ""
        print(f"  tau={r['tau_ms']:>6}ms  P={r['precision']:.3f} R={r['recall']:.3f} F1={r['f1']:.3f} "
              f"over_seg={r['over_segmentation_rate']} under_seg={r['under_segmentation_rate']}{marker}", file=sys.stderr)

    best_tau = best["tau_ms"]

    # --- Baseline comparison at best_tau ---
    baseline_comparison = {}
    for name, fn in [
        ("baseline1_temporal_only", baseline_temporal_only),
        ("baseline2_temporal_and_context", baseline_temporal_and_context),
        ("baseline3_temporal_or_context", baseline_temporal_or_context),
    ]:
        all_labeled = []
        all_preds = []
        over_seg_num, over_seg_den = 0.0, 0
        under_seg_num, under_seg_den = 0.0, 0
        for session_id, labeled, ts, executions in per_session_data:
            feats = [lt.features for lt in labeled]
            preds = fn(feats, best_tau)
            all_labeled.extend(labeled)
            all_preds.extend(preds)
            segs = segments_from_boundaries(session_id, ts, preds)
            em = execution_metrics(executions, segs)
            over_seg_num += em.over_segmentation_rate * em.n_gt_executions
            over_seg_den += em.n_gt_executions
            n_overlap_segs = em.n_predicted_segments - em.n_pure_noise_segments
            under_seg_num += em.under_segmentation_rate * n_overlap_segs
            under_seg_den += n_overlap_segs

        bm = boundary_metrics(all_labeled, all_preds)
        baseline_comparison[name] = {
            "tau_ms": best_tau,
            **bm.to_dict(),
            "over_segmentation_rate": round(over_seg_num / over_seg_den, 4) if over_seg_den else None,
            "under_segmentation_rate": round(under_seg_num / under_seg_den, 4) if under_seg_den else None,
        }

    print("\nBaseline comparison at tau =", best_tau, "ms:", file=sys.stderr)
    for name, r in baseline_comparison.items():
        print(f"  {name}: P={r['precision']:.3f} R={r['recall']:.3f} F1={r['f1']:.3f} "
              f"over_seg={r['over_segmentation_rate']} under_seg={r['under_segmentation_rate']}", file=sys.stderr)

    # --- Per-session F1 at best_tau, baseline 1 (stability check) ---
    per_session_f1 = {}
    for session_id, labeled, ts, executions in per_session_data:
        feats = [lt.features for lt in labeled]
        preds = baseline_temporal_only(feats, best_tau)
        bm = boundary_metrics(labeled, preds)
        per_session_f1[session_id] = round(bm.f1, 4)

    f1_values = list(per_session_f1.values())
    f1_values_excl_known = [v for sid, v in per_session_f1.items() if sid != KNOWN_INCOMPLETE_SESSION]

    print("\nPer-session F1 (baseline 1) stability:", file=sys.stderr)
    print(f"  mean={statistics.fmean(f1_values):.3f} std={statistics.pstdev(f1_values):.3f} "
          f"min={min(f1_values):.3f} max={max(f1_values):.3f}", file=sys.stderr)
    print(f"  excluding known-incomplete session: mean={statistics.fmean(f1_values_excl_known):.3f} "
          f"std={statistics.pstdev(f1_values_excl_known):.3f}", file=sys.stderr)
    worst = sorted(per_session_f1.items(), key=lambda kv: kv[1])[:5]
    print("  worst 5 sessions:", worst, file=sys.stderr)

    out = {
        "threshold_sweep": sweep_results,
        "best_tau_ms": best_tau,
        "baseline_comparison_at_best_tau": baseline_comparison,
        "per_session_f1_baseline1_at_best_tau": per_session_f1,
        "per_session_f1_summary": {
            "all": {"mean": statistics.fmean(f1_values), "std": statistics.pstdev(f1_values),
                    "min": min(f1_values), "max": max(f1_values)},
            "excluding_known_incomplete_session": {
                "mean": statistics.fmean(f1_values_excl_known),
                "std": statistics.pstdev(f1_values_excl_known),
            },
        },
        "n_sessions": len(per_session_data),
    }
    out_path = args.out / f"baseline_segmentation_{args.dataset.name}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
