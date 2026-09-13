#!/usr/bin/env python3
"""Stage 6: train the continuity model (Stage 5's recommended feature
set), evaluate with leave-one-session-out cross-validation, and compare
against the V1 boundary-first model on both boundary quality and
execution coherence.

Manual LOSO loop (not sklearn's cross_val_predict) so each fold's model
can also be applied to that session's EXCLUDED transitions (no continuity
label exists for these — NOISE_TO_NOISE / ENTRY_FROM_NOISE /
EXIT_TO_NOISE_UNRELIABLE_EXCLUDED) for full-session reconstruction only.
Boundary-quality metrics (precision/recall/F1) are computed ONLY on the
139,121 labeled transitions — the same evidence-backed subset training
used. Execution-level reconstruction runs on the full transition stream
per session, exactly like V1's did, with excluded-transition predictions
explicitly flagged as unvalidated (no ground truth exists to check them).

Does not touch Dataset B. Does not build the interruption-aware
reconstruction layer (Stage 8's job) — segment cutting here is the same
naive "cut at every predicted boundary" method V1 used, for a fair
apples-to-apples comparison.

Usage:
    python scripts/train_continuity_model.py --dataset dataset_a --out reports/day2
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np
from sklearn.metrics import precision_recall_curve

from procmine.loaders.events import load_session_events
from procmine.loaders.ground_truth import load_gt_manifest, parse_gt_manifest_executions
from procmine.paths import discover_dataset
from procmine.segmentation.canonical import to_canonical_stream
from procmine.segmentation.continuity_labels import label_continuity
from procmine.segmentation.continuity_model import (
    CONTINUITY_FEATURE_NAMES,
    continuity_feature_vector,
    feature_importance,
)
from procmine.segmentation.evaluation import (
    boundary_metrics,
    execution_metrics,
    segments_from_boundaries,
)
from procmine.segmentation.features import LabeledTransition, extract_transition_features
from procmine.segmentation.model import fit_full_model, make_pipeline
from procmine.segmentation.signals import extract_boundaries
from procmine.validation import ValidationReport


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    sessions = discover_dataset(args.dataset)

    per_session = {}
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
        clabels = label_continuity(session.session_id, feats, boundaries, executions)

        X_all = [continuity_feature_vector(canonical, i, f) for i, f in enumerate(feats)]
        ts = [e.timestamp_ms for e in events]

        per_session[session.session_id] = {
            "clabels": clabels,
            "X_all": X_all,
            "ts": ts,
            "executions": executions,
        }

    session_ids = sorted(per_session.keys())
    print(f"{len(session_ids)} sessions loaded", file=sys.stderr)

    # Build the LABELED-only training matrix (excluded rows carry no label)
    X_train_rows, y_train_rows, groups_train = [], [], []
    for sid in session_ids:
        d = per_session[sid]
        for x, cl in zip(d["X_all"], d["clabels"]):
            if cl.excluded:
                continue
            X_train_rows.append(x)
            y_train_rows.append(cl.continuity_label)
            groups_train.append(sid)
    X_train = np.array(X_train_rows)
    y_train = np.array(y_train_rows)
    groups_train_arr = np.array(groups_train)
    print(f"{X_train.shape[0]} labeled transitions for training/evaluation "
          f"({X_train.shape[1]} features)", file=sys.stderr)

    print(f"Running manual LOSO ({len(session_ids)} fits)...", file=sys.stderr)
    fold_models = {}
    for held_out in session_ids:
        mask = groups_train_arr != held_out
        pipeline = make_pipeline()
        pipeline.fit(X_train[mask], y_train[mask])
        fold_models[held_out] = pipeline
    print("LOSO complete.", file=sys.stderr)

    # Out-of-fold P(S=1) for every labeled row, in the same order as X_train
    oof_s_prob = np.zeros(len(y_train))
    idx = 0
    for sid in session_ids:
        d = per_session[sid]
        n_labeled_here = sum(1 for cl in d["clabels"] if not cl.excluded)
        rows = [x for x, cl in zip(d["X_all"], d["clabels"]) if not cl.excluded]
        if rows:
            probs = fold_models[sid].predict_proba(np.array(rows))[:, 1]
            oof_s_prob[idx : idx + n_labeled_here] = probs
        idx += n_labeled_here

    # Threshold selection on BOUNDARY (S=0) as the positive class of
    # interest, using out-of-fold predictions only.
    y_boundary = 1 - y_train
    score_boundary = 1 - oof_s_prob
    precisions, recalls, thresholds = precision_recall_curve(y_boundary, score_boundary)
    f1s = np.where((precisions + recalls) > 0, 2 * precisions * recalls / (precisions + recalls + 1e-12), 0.0)
    best_idx = int(np.argmax(f1s[:-1])) if len(thresholds) else 0
    best_threshold_boundary_score = float(thresholds[best_idx]) if len(thresholds) else 0.5
    print(f"Best boundary-score threshold: {best_threshold_boundary_score:.4f} "
          f"(P={precisions[best_idx]:.3f} R={recalls[best_idx]:.3f} F1={f1s[best_idx]:.3f})", file=sys.stderr)

    predicted_boundary_labeled = (score_boundary >= best_threshold_boundary_score).tolist()
    labeled_transitions_flat = [
        LabeledTransition(features=None, is_boundary=bool(yb), is_resume=None) for yb in y_boundary
    ]
    bm = boundary_metrics(labeled_transitions_flat, predicted_boundary_labeled)
    print(f"Boundary quality (on the {len(y_train)} labeled transitions only): {bm.to_dict()}", file=sys.stderr)

    # --- Full-session reconstruction (labeled + excluded transitions) ---
    over_seg_num, over_seg_den = 0.0, 0
    under_seg_num, under_seg_den = 0.0, 0
    per_session_f1 = {}
    n_gt_executions_total = 0
    n_gt_executions_fragmented = 0  # >1 overlapping predicted segment -- Stage 2's headline metric

    for sid in session_ids:
        d = per_session[sid]
        model = fold_models[sid]
        all_probs_s1 = model.predict_proba(np.array(d["X_all"]))[:, 1]
        all_predicted_boundary = ((1 - all_probs_s1) >= best_threshold_boundary_score).tolist()

        segs = segments_from_boundaries(sid, d["ts"], all_predicted_boundary)
        em = execution_metrics(d["executions"], segs)
        over_seg_num += em.over_segmentation_rate * em.n_gt_executions
        over_seg_den += em.n_gt_executions
        n_overlap_segs = em.n_predicted_segments - em.n_pure_noise_segments
        under_seg_num += em.under_segmentation_rate * n_overlap_segs
        under_seg_den += n_overlap_segs

        # directly comparable to Stage 2's "90.8% of GT executions fragmented"
        for ex in d["executions"]:
            if ex.end_ts is None:
                continue
            n_gt_executions_total += 1
            e_start = int(ex.start_ts.timestamp() * 1000)
            e_end = int(ex.end_ts.timestamp() * 1000)
            n_overlapping = sum(
                1 for s in segs if max(0, min(s.end_ms, e_end) - max(s.start_ms, e_start)) > 0
            )
            if n_overlapping > 1:
                n_gt_executions_fragmented += 1

        # per-session boundary F1 restricted to that session's labeled rows
        labeled_mask = [not cl.excluded for cl in d["clabels"]]
        session_y_boundary = [1 - cl.continuity_label for cl, m in zip(d["clabels"], labeled_mask) if m]
        session_pred_boundary = [
            p for p, m in zip(all_predicted_boundary, labeled_mask) if m
        ]
        session_lt = [LabeledTransition(features=None, is_boundary=bool(yb), is_resume=None) for yb in session_y_boundary]
        session_bm = boundary_metrics(session_lt, session_pred_boundary)
        per_session_f1[sid] = round(session_bm.f1, 4)

    over_seg_rate = over_seg_num / over_seg_den if over_seg_den else None
    under_seg_rate = under_seg_num / under_seg_den if under_seg_den else None
    pct_fragmented = 100 * n_gt_executions_fragmented / n_gt_executions_total if n_gt_executions_total else None
    print(f"Execution-level (full session, incl. unvalidated excluded-transition predictions): "
          f"over_seg={over_seg_rate} under_seg={under_seg_rate}", file=sys.stderr)
    print(f"GT executions fragmented (>1 overlapping predicted segment): "
          f"{n_gt_executions_fragmented}/{n_gt_executions_total} ({pct_fragmented:.1f}%) "
          f"-- Stage 2's V1 comparison point was 90.8%", file=sys.stderr)

    f1_values = list(per_session_f1.values())
    print(f"Per-session F1: mean={statistics.fmean(f1_values):.3f} std={statistics.pstdev(f1_values):.3f} "
          f"min={min(f1_values):.3f} max={max(f1_values):.3f}", file=sys.stderr)

    full_model = fit_full_model(X_train, y_train)
    importance = feature_importance(full_model)
    print("\nFeature importance (standardized coefficients, predicting S=1):", file=sys.stderr)
    for name, coef in importance:
        print(f"  {name:<32} {coef:+.4f}", file=sys.stderr)

    out = {
        "n_sessions": len(session_ids),
        "n_labeled_transitions": int(X_train.shape[0]),
        "best_boundary_score_threshold": best_threshold_boundary_score,
        "boundary_metrics_labeled_only": bm.to_dict(),
        "execution_metrics_full_session": {
            "over_segmentation_rate": over_seg_rate,
            "under_segmentation_rate": under_seg_rate,
            "n_gt_executions_fragmented": n_gt_executions_fragmented,
            "n_gt_executions_total": n_gt_executions_total,
            "pct_gt_executions_fragmented": pct_fragmented,
            "note": "computed over all transitions including the 14.49% excluded from training; "
                    "predictions on excluded transitions are unvalidated (no GT label exists for them)",
        },
        "per_session_f1": per_session_f1,
        "per_session_f1_summary": {
            "mean": statistics.fmean(f1_values), "std": statistics.pstdev(f1_values),
            "min": min(f1_values), "max": max(f1_values),
        },
        "feature_importance": [{"feature": n, "coefficient": float(c)} for n, c in importance],
    }
    out_path = args.out / f"continuity_model_{args.dataset.name}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
