#!/usr/bin/env python3
"""Stage 7: rigorous threshold/operating-point analysis for V1
(boundary-first) and V2 (continuity-first), on Dataset A only.

Evaluation only — no new model, no reconstruction, no feature/architecture
changes, no Dataset B. Runs each model's existing LOSO procedure exactly
once to get honest out-of-fold scores (session-aware: a score for session
X never came from a model that saw session X), then sweeps a threshold
grid cheaply on those cached scores. The threshold itself is selected
from the pooled out-of-fold scores across all sessions — never from an
individual held-out session, which would leak test information.

Reuses `evaluation.boundary_metrics`, `segments_from_boundaries`, and the
now-extended `execution_metrics` (added `n_fragmented`/`pct_fragmented`/
`fragmented_case_ids` this stage, additively, so no existing caller or
test broke) rather than redefining any metric.

Usage:
    python scripts/analyze_threshold_tradeoff.py --dataset dataset_a --out reports/day2
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np

from procmine.loaders.events import load_session_events
from procmine.loaders.ground_truth import load_gt_manifest, parse_gt_manifest_executions
from procmine.paths import discover_dataset
from procmine.segmentation.canonical import to_canonical_stream
from procmine.segmentation.continuity_labels import label_continuity
from procmine.segmentation.continuity_model import continuity_feature_vector
from procmine.segmentation.features import LabeledTransition, extract_transition_features, label_transitions
from procmine.segmentation.model import feature_vector as v1_feature_vector
from procmine.segmentation.model import make_pipeline
from procmine.segmentation.signals import extract_boundaries
from procmine.segmentation.threshold_analysis import build_threshold_grid, evaluate_at_threshold
from procmine.validation import ValidationReport

V1_REFERENCE_THRESHOLD = 0.9078  # Stage 6's chosen operating point, kept as a reference row
V2_REFERENCE_THRESHOLD = 0.8860  # boundary-score threshold, i.e. 1 - P(S=1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    fig_dir = args.out / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    sessions = discover_dataset(args.dataset)
    raw = {}
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
        is_boundary_labels = label_transitions(feats, [(b.timestamp_ms, b.is_resume) for b in boundaries])
        clabels = label_continuity(session.session_id, feats, boundaries, executions)

        X_v1 = np.array([v1_feature_vector(f) for f in feats])
        X_v2 = np.array([continuity_feature_vector(canonical, i, f) for i, f in enumerate(feats)])
        ts = [e.timestamp_ms for e in events]

        raw[session.session_id] = {
            "is_boundary_labels": is_boundary_labels, "clabels": clabels,
            "X_v1": X_v1, "X_v2": X_v2, "executions": executions, "ts": ts,
        }

    session_ids = sorted(raw.keys())
    print(f"{len(session_ids)} sessions loaded", file=sys.stderr)

    # === V1 LOSO (once) ===
    y_v1 = np.array([1 if lt.is_boundary else 0 for sid in session_ids for lt in raw[sid]["is_boundary_labels"]])
    groups_v1 = np.array([sid for sid in session_ids for _ in raw[sid]["is_boundary_labels"]])
    X_v1_all = np.vstack([raw[sid]["X_v1"] for sid in session_ids])
    print("Running V1 LOSO (once)...", file=sys.stderr)
    v1_scores_by_session = {}
    for held_out in session_ids:
        mask = groups_v1 != held_out
        pipeline = make_pipeline()
        pipeline.fit(X_v1_all[mask], y_v1[mask])
        v1_scores_by_session[held_out] = pipeline.predict_proba(raw[held_out]["X_v1"])[:, 1]

    # === V2 LOSO (once), trained on labeled subset, applied to all rows ===
    X_v2_train, y_v2_train, groups_v2_train = [], [], []
    for sid in session_ids:
        d = raw[sid]
        for x, cl in zip(d["X_v2"], d["clabels"]):
            if cl.excluded:
                continue
            X_v2_train.append(x); y_v2_train.append(cl.continuity_label); groups_v2_train.append(sid)
    X_v2_train = np.array(X_v2_train); y_v2_train = np.array(y_v2_train); groups_v2_train = np.array(groups_v2_train)
    print("Running V2 LOSO (once)...", file=sys.stderr)
    v2_boundary_scores_by_session = {}
    for held_out in session_ids:
        mask = groups_v2_train != held_out
        pipeline = make_pipeline()
        pipeline.fit(X_v2_train[mask], y_v2_train[mask])
        s1_probs = pipeline.predict_proba(raw[held_out]["X_v2"])[:, 1]
        v2_boundary_scores_by_session[held_out] = 1 - s1_probs

    print("Both LOSO runs complete.", file=sys.stderr)

    # === Assemble per-session structures shared by both models' sweeps ===
    per_session_v1, per_session_v2 = {}, {}
    all_v1_lt, all_v1_scores = [], []
    all_v2_lt, all_v2_scores = [], []

    for sid in session_ids:
        d = raw[sid]
        v1_lt = d["is_boundary_labels"]
        labeled_mask_v1 = [True] * len(v1_lt)  # V1's label is defined everywhere
        per_session_v1[sid] = {
            "labeled_lt": v1_lt, "labeled_mask": labeled_mask_v1,
            "v1_scores": v1_scores_by_session[sid],
            "ts": d["ts"], "executions": d["executions"],
        }
        all_v1_lt.extend(v1_lt)
        all_v1_scores.extend(v1_scores_by_session[sid].tolist())

        v2_lt = [LabeledTransition(features=None, is_boundary=(cl.continuity_label == 0), is_resume=None)
                 for cl in d["clabels"] if not cl.excluded]
        labeled_mask_v2 = [not cl.excluded for cl in d["clabels"]]
        per_session_v2[sid] = {
            "labeled_lt": v2_lt, "labeled_mask": labeled_mask_v2,
            "v2_scores": v2_boundary_scores_by_session[sid],
            "ts": d["ts"], "executions": d["executions"],
        }
        all_v2_lt.extend(v2_lt)
        all_v2_scores.extend([s for s, m in zip(v2_boundary_scores_by_session[sid], labeled_mask_v2) if m])

    all_v1_scores = np.array(all_v1_scores)
    all_v2_scores = np.array(all_v2_scores)

    grid_v1 = build_threshold_grid(all_v1_scores)
    grid_v2 = build_threshold_grid(all_v2_scores)
    print(f"V1 grid: {len(grid_v1)} thresholds, range [{min(grid_v1):.3f}, {max(grid_v1):.3f}]", file=sys.stderr)
    print(f"V2 grid: {len(grid_v2)} thresholds, range [{min(grid_v2):.3f}, {max(grid_v2):.3f}]", file=sys.stderr)

    print("Sweeping V1...", file=sys.stderr)
    v1_curve = [evaluate_at_threshold(t, all_v1_lt, all_v1_scores, per_session_v1, "v1_scores") for t in grid_v1]
    print("Sweeping V2...", file=sys.stderr)
    v2_curve = [evaluate_at_threshold(t, all_v2_lt, all_v2_scores, per_session_v2, "v2_scores") for t in grid_v2]

    # attach reference-threshold rows explicitly if not already in the grid
    for name, grid, curve, ref, lt, scores, ps, key in [
        ("V1", grid_v1, v1_curve, V1_REFERENCE_THRESHOLD, all_v1_lt, all_v1_scores, per_session_v1, "v1_scores"),
        ("V2", grid_v2, v2_curve, V2_REFERENCE_THRESHOLD, all_v2_lt, all_v2_scores, per_session_v2, "v2_scores"),
    ]:
        if ref not in grid:
            curve.append(evaluate_at_threshold(ref, lt, scores, ps, key))
            curve.sort(key=lambda r: r["threshold"])

    def summarize(curve, label):
        best_f1 = max(curve, key=lambda r: r["f1"])
        print(f"\n{label} best-F1: tau={best_f1['threshold']:.4f} P={best_f1['precision']:.3f} "
              f"R={best_f1['recall']:.3f} F1={best_f1['f1']:.3f} "
              f"frag%={best_f1['pct_gt_executions_fragmented']:.1f}", file=sys.stderr)
        return best_f1

    v1_best = summarize(v1_curve, "V1")
    v2_best = summarize(v2_curve, "V2")

    # Strip the heavy per-session diffing payload before the main dump,
    # save it separately (it's what Option-1-style diffing needs)
    def strip(curve):
        out = []
        frag_sets = {}
        f1_sets = {}
        for row in curve:
            r = dict(row)
            frag_sets[row["threshold"]] = {sid: sorted(s) for sid, s in row["_fragmented_by_session"].items()}
            f1_sets[row["threshold"]] = row["_per_session_f1"]
            del r["_fragmented_by_session"]
            del r["_per_session_f1"]
            out.append(r)
        return out, frag_sets, f1_sets

    v1_curve_clean, v1_frag_sets, v1_f1_sets = strip(v1_curve)
    v2_curve_clean, v2_frag_sets, v2_f1_sets = strip(v2_curve)

    out = {
        "n_sessions": len(session_ids),
        "grid_v1": grid_v1,
        "grid_v2": grid_v2,
        "v1_curve": v1_curve_clean,
        "v2_curve": v2_curve_clean,
        "v1_best_f1_point": {k: v for k, v in v1_best.items() if not k.startswith("_")},
        "v2_best_f1_point": {k: v for k, v in v2_best.items() if not k.startswith("_")},
    }
    out_path = args.out / f"threshold_tradeoff_{args.dataset.name}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {out_path}", file=sys.stderr)

    # per-session f1/fragmentation sets saved separately (large, only needed for deep-dive)
    with (args.out / f"threshold_tradeoff_session_detail_{args.dataset.name}.json").open("w", encoding="utf-8") as f:
        json.dump({"v1_fragmented_sets": v1_frag_sets, "v2_fragmented_sets": v2_frag_sets,
                   "v1_f1_sets": v1_f1_sets, "v2_f1_sets": v2_f1_sets}, f, ensure_ascii=False)

    # === Plots ===
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    def plot_metric(curves, key, ylabel, fname, title):
        fig, ax = plt.subplots(figsize=(7, 4.5))
        for label, curve in curves:
            xs = [r["threshold"] for r in curve]
            ys = [r[key] for r in curve]
            ax.plot(xs, ys, marker=".", label=label, alpha=0.8)
        ax.set_xlabel("threshold")
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.legend()
        fig.tight_layout()
        fig.savefig(fig_dir / fname, dpi=140)
        plt.close(fig)

    curves = [("V1", v1_curve_clean), ("V2", v2_curve_clean)]
    plot_metric(curves, "recall", "recall", "threshold_vs_recall.png", "Threshold vs. boundary recall")
    plot_metric(curves, "f1", "F1", "threshold_vs_f1.png", "Threshold vs. boundary F1")
    plot_metric(curves, "pct_gt_executions_fragmented", "% GT executions fragmented",
                "threshold_vs_fragmentation.png", "Threshold vs. fragmentation rate")
    plot_metric(curves, "over_segmentation_rate", "over-segmentation rate",
                "threshold_vs_over_segmentation.png", "Threshold vs. over-segmentation")
    plot_metric(curves, "under_segmentation_rate", "under-segmentation rate",
                "threshold_vs_under_segmentation.png", "Threshold vs. under-segmentation")

    fig, ax = plt.subplots(figsize=(6, 6))
    for label, curve in curves:
        xs = [r["recall"] for r in curve]
        ys = [r["precision"] for r in curve]
        ax.plot(xs, ys, marker=".", label=label, alpha=0.8)
    ax.set_xlabel("recall")
    ax.set_ylabel("precision")
    ax.set_title("Precision-recall trade-off")
    ax.legend()
    fig.tight_layout()
    fig.savefig(fig_dir / "precision_recall_tradeoff.png", dpi=140)
    plt.close(fig)

    print(f"Wrote 6 figures to {fig_dir}", file=sys.stderr)


if __name__ == "__main__":
    main()
