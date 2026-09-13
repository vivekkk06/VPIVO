#!/usr/bin/env python3
"""Train and evaluate the learned boundary model against real GT, with
leave-one-session-out cross-validation (no session's own data ever
informs the model that predicts on it).

Loads fresh from the dataset (same pattern as Stage 5's baseline script)
rather than the persisted feature table, since execution-level scoring
needs per-session event timestamps the persisted JSON doesn't carry.

Usage:
    python scripts/train_boundary_model.py --dataset dataset_a --out reports/day2
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

import numpy as np
from sklearn.metrics import precision_recall_curve

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from procmine.loaders.events import load_session_events
from procmine.loaders.ground_truth import load_gt_manifest, parse_gt_manifest_executions
from procmine.paths import discover_dataset
from procmine.segmentation.canonical import to_canonical_stream
from procmine.segmentation.evaluation import (
    boundary_metrics,
    execution_metrics,
    segments_from_boundaries,
)
from procmine.segmentation.features import extract_transition_features, label_transitions
from procmine.segmentation.model import (
    cross_validated_probabilities,
    feature_importance,
    feature_vector,
    fit_full_model,
)
from procmine.segmentation.signals import extract_boundaries
from procmine.validation import ValidationReport


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    sessions = discover_dataset(args.dataset)

    per_session_data = []
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

    # Flatten into one global (X, y, groups) array, remembering each
    # session's row range so out-of-fold probabilities can be sliced back
    # into per-session order for execution-level scoring.
    X_rows, y_rows, groups = [], [], []
    session_row_ranges: dict[str, tuple[int, int]] = {}
    all_labeled_flat = []
    for session_id, labeled, ts, executions in per_session_data:
        start = len(X_rows)
        for lt in labeled:
            X_rows.append(feature_vector(lt.features))
            y_rows.append(1 if lt.is_boundary else 0)
            groups.append(session_id)
            all_labeled_flat.append(lt)
        session_row_ranges[session_id] = (start, len(X_rows))

    X = np.array(X_rows)
    y = np.array(y_rows)
    groups_arr = np.array(groups)
    print(f"{X.shape[0]} transitions, {X.shape[1]} features, {len(set(groups))} groups", file=sys.stderr)

    print("Running leave-one-session-out cross-validation (this fits 63 models)...", file=sys.stderr)
    oof_probs = cross_validated_probabilities(X, y, groups_arr)

    # Threshold selection on out-of-fold predictions only (never on
    # in-sample predictions) — exact best-F1 point via precision_recall_curve.
    precisions, recalls, thresholds = precision_recall_curve(y, oof_probs)
    f1s = np.where(
        (precisions + recalls) > 0, 2 * precisions * recalls / (precisions + recalls + 1e-12), 0.0
    )
    best_idx = int(np.argmax(f1s[:-1])) if len(thresholds) else 0  # last point has no threshold
    best_threshold = float(thresholds[best_idx]) if len(thresholds) else 0.5
    print(
        f"Best out-of-fold threshold: {best_threshold:.4f} "
        f"(P={precisions[best_idx]:.3f} R={recalls[best_idx]:.3f} F1={f1s[best_idx]:.3f})",
        file=sys.stderr,
    )

    predictions_flat = (oof_probs >= best_threshold).tolist()
    bm = boundary_metrics(all_labeled_flat, predictions_flat)
    print(f"Pooled boundary metrics at best threshold: {bm.to_dict()}", file=sys.stderr)

    # Execution-level metrics, per session, using the same threshold.
    over_seg_num, over_seg_den = 0.0, 0
    under_seg_num, under_seg_den = 0.0, 0
    per_session_f1 = {}
    for session_id, labeled, ts, executions in per_session_data:
        start, end = session_row_ranges[session_id]
        session_preds = predictions_flat[start:end]
        session_labeled = all_labeled_flat[start:end]
        segs = segments_from_boundaries(session_id, ts, session_preds)
        em = execution_metrics(executions, segs)
        over_seg_num += em.over_segmentation_rate * em.n_gt_executions
        over_seg_den += em.n_gt_executions
        n_overlap_segs = em.n_predicted_segments - em.n_pure_noise_segments
        under_seg_num += em.under_segmentation_rate * n_overlap_segs
        under_seg_den += n_overlap_segs
        session_bm = boundary_metrics(session_labeled, session_preds)
        per_session_f1[session_id] = round(session_bm.f1, 4)

    over_seg_rate = over_seg_num / over_seg_den if over_seg_den else None
    under_seg_rate = under_seg_num / under_seg_den if under_seg_den else None
    print(f"Execution-level: over_seg={over_seg_rate} under_seg={under_seg_rate}", file=sys.stderr)

    f1_values = list(per_session_f1.values())
    print(
        f"Per-session F1: mean={statistics.fmean(f1_values):.3f} "
        f"std={statistics.pstdev(f1_values):.3f} min={min(f1_values):.3f} max={max(f1_values):.3f}",
        file=sys.stderr,
    )
    worst = sorted(per_session_f1.items(), key=lambda kv: kv[1])[:5]
    print("Worst 5 sessions:", worst, file=sys.stderr)

    # Feature importance, from a model fit on all data (descriptive only,
    # never used to generate the evaluated predictions above).
    full_model = fit_full_model(X, y)
    importance = feature_importance(full_model)
    print("\nFeature importance (standardized logistic regression coefficients):", file=sys.stderr)
    for name, coef in importance:
        print(f"  {name:<32} {coef:+.4f}", file=sys.stderr)

    out = {
        "n_sessions": len(per_session_data),
        "n_transitions": int(X.shape[0]),
        "n_features": int(X.shape[1]),
        "best_threshold": best_threshold,
        "pooled_boundary_metrics": bm.to_dict(),
        "over_segmentation_rate": over_seg_rate,
        "under_segmentation_rate": under_seg_rate,
        "per_session_f1": per_session_f1,
        "per_session_f1_summary": {
            "mean": statistics.fmean(f1_values),
            "std": statistics.pstdev(f1_values),
            "min": min(f1_values),
            "max": max(f1_values),
        },
        "feature_importance": [{"feature": n, "coefficient": float(c)} for n, c in importance],
    }
    out_path = args.out / f"learned_model_{args.dataset.name}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
