#!/usr/bin/env python3
"""Option 1: diagnose WHY the continuity model (V2) fragments more GT
executions (94.7%) than the boundary-first model (V1, 90.8%), even though
V2's total false-positive count is only marginally higher.

Investigation only — no threshold changes, no feature changes, no new
model. Re-runs both V1's and V2's exact LOSO procedures (same feature
sets, same thresholds already established: V1 P>=0.9078, V2 boundary-
score>=0.8860) to get per-transition predictions from both, then compares
which specific GT executions each model fragments.

Usage:
    python scripts/compare_v1_v2_fragmentation.py --dataset dataset_a --out reports/day2
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np

from procmine.loaders.events import load_session_events
from procmine.loaders.ground_truth import load_gt_manifest, parse_gt_manifest_executions
from procmine.paths import discover_dataset
from procmine.segmentation.canonical import to_canonical_stream
from procmine.segmentation.continuity_labels import label_continuity
from procmine.segmentation.continuity_model import continuity_feature_vector
from procmine.segmentation.features import extract_transition_features, label_transitions
from procmine.segmentation.model import feature_vector as v1_feature_vector
from procmine.segmentation.model import make_pipeline
from procmine.segmentation.signals import extract_boundaries
from procmine.validation import ValidationReport

V1_THRESHOLD = 0.9078
V2_BOUNDARY_SCORE_THRESHOLD = 0.8860


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
        is_boundary_labels = label_transitions(feats, [(b.timestamp_ms, b.is_resume) for b in boundaries])
        clabels = label_continuity(session.session_id, feats, boundaries, executions)

        X_v1 = np.array([v1_feature_vector(f) for f in feats])
        X_v2 = np.array([continuity_feature_vector(canonical, i, f) for i, f in enumerate(feats)])

        per_session[session.session_id] = {
            "feats": feats, "is_boundary_labels": is_boundary_labels, "clabels": clabels,
            "X_v1": X_v1, "X_v2": X_v2, "executions": executions,
        }

    session_ids = sorted(per_session.keys())
    print(f"{len(session_ids)} sessions loaded", file=sys.stderr)

    # --- LOSO for V1 (predicting is_boundary directly) ---
    y_v1_all = np.array([1 if lt.is_boundary else 0 for sid in session_ids for lt in per_session[sid]["is_boundary_labels"]])
    groups_v1_all = np.array([sid for sid in session_ids for _ in per_session[sid]["is_boundary_labels"]])
    X_v1_all = np.vstack([per_session[sid]["X_v1"] for sid in session_ids])

    print("Running V1 LOSO...", file=sys.stderr)
    v1_preds_by_session = {}
    for held_out in session_ids:
        mask = groups_v1_all != held_out
        pipeline = make_pipeline()
        pipeline.fit(X_v1_all[mask], y_v1_all[mask])
        probs = pipeline.predict_proba(per_session[held_out]["X_v1"])[:, 1]
        v1_preds_by_session[held_out] = (probs >= V1_THRESHOLD)

    # --- LOSO for V2 (predicting continuity, labeled subset only for training) ---
    X_v2_train, y_v2_train, groups_v2_train = [], [], []
    for sid in session_ids:
        d = per_session[sid]
        for x, cl in zip(d["X_v2"], d["clabels"]):
            if cl.excluded:
                continue
            X_v2_train.append(x); y_v2_train.append(cl.continuity_label); groups_v2_train.append(sid)
    X_v2_train = np.array(X_v2_train); y_v2_train = np.array(y_v2_train); groups_v2_train = np.array(groups_v2_train)

    print("Running V2 LOSO...", file=sys.stderr)
    v2_preds_by_session = {}
    for held_out in session_ids:
        mask = groups_v2_train != held_out
        pipeline = make_pipeline()
        pipeline.fit(X_v2_train[mask], y_v2_train[mask])
        s1_probs = pipeline.predict_proba(per_session[held_out]["X_v2"])[:, 1]
        boundary_score = 1 - s1_probs
        v2_preds_by_session[held_out] = (boundary_score >= V2_BOUNDARY_SCORE_THRESHOLD)

    print("Both LOSO runs complete. Computing per-execution fragmentation...", file=sys.stderr)

    # --- Per-execution fragmentation flags for both models ---
    confusion = Counter()  # (fragmented_by_v1, fragmented_by_v2) -> count
    only_v2_examples = []
    only_v1_examples = []
    both_examples_degree = []  # (v1_extra, v2_extra) for executions fragmented by both

    for sid in session_ids:
        d = per_session[sid]
        events_ts = [f.timestamp_ms for f in d["feats"]] + [d["feats"][-1].next_timestamp_ms] if d["feats"] else []
        v1_pred = v1_preds_by_session[sid]
        v2_pred = v2_preds_by_session[sid]

        # build predicted segments' (start,end) spans directly from boundary flags
        def segments_from(preds):
            segs = []
            start = events_ts[0]
            for i, p in enumerate(preds):
                if p:
                    segs.append((start, events_ts[i]))
                    start = events_ts[i + 1]
            segs.append((start, events_ts[-1]))
            return segs

        v1_segs = segments_from(v1_pred)
        v2_segs = segments_from(v2_pred)

        for ex in d["executions"]:
            if ex.end_ts is None:
                continue
            e_start = int(ex.start_ts.timestamp() * 1000)
            e_end = int(ex.end_ts.timestamp() * 1000)

            def n_overlap(segs):
                return sum(1 for s, e in segs if max(0, min(e, e_end) - max(s, e_start)) > 0)

            n_v1 = n_overlap(v1_segs)
            n_v2 = n_overlap(v2_segs)
            frag_v1 = n_v1 > 1
            frag_v2 = n_v2 > 1
            confusion[(frag_v1, frag_v2)] += 1

            if frag_v2 and not frag_v1:
                if len(only_v2_examples) < 8:
                    only_v2_examples.append({
                        "session_id": sid, "case_id": ex.case_id, "process_code": ex.process_code,
                        "n_v1_segments": n_v1, "n_v2_segments": n_v2,
                        "duration_s": round((ex.end_ts - ex.start_ts).total_seconds(), 1),
                    })
            if frag_v1 and not frag_v2:
                if len(only_v1_examples) < 8:
                    only_v1_examples.append({
                        "session_id": sid, "case_id": ex.case_id, "process_code": ex.process_code,
                        "n_v1_segments": n_v1, "n_v2_segments": n_v2,
                        "duration_s": round((ex.end_ts - ex.start_ts).total_seconds(), 1),
                    })
            if frag_v1 and frag_v2:
                both_examples_degree.append((n_v1 - 1, n_v2 - 1))

    print("\nFragmentation confusion matrix (rows=V1, cols=V2):", file=sys.stderr)
    print(f"  Neither fragmented:        {confusion[(False, False)]}", file=sys.stderr)
    print(f"  Only V1 fragmented:        {confusion[(True, False)]}", file=sys.stderr)
    print(f"  Only V2 fragmented:        {confusion[(False, True)]}", file=sys.stderr)
    print(f"  Both fragmented:           {confusion[(True, True)]}", file=sys.stderr)

    if both_examples_degree:
        v1_extra = [d[0] for d in both_examples_degree]
        v2_extra = [d[1] for d in both_examples_degree]
        print(f"\nFor executions fragmented by BOTH (n={len(both_examples_degree)}):", file=sys.stderr)
        print(f"  mean extra segments V1={sum(v1_extra)/len(v1_extra):.2f}  V2={sum(v2_extra)/len(v2_extra):.2f}", file=sys.stderr)

    print(f"\nExamples where V2 fragments but V1 doesn't ({len(only_v2_examples)} shown):", file=sys.stderr)
    for e in only_v2_examples:
        print(" ", e, file=sys.stderr)
    print(f"\nExamples where V1 fragments but V2 doesn't ({len(only_v1_examples)} shown):", file=sys.stderr)
    for e in only_v1_examples:
        print(" ", e, file=sys.stderr)

    out = {
        "confusion": {f"v1={k[0]}_v2={k[1]}": v for k, v in confusion.items()},
        "both_fragmented_mean_extra_segments": {
            "v1": sum(v1_extra) / len(v1_extra) if both_examples_degree else None,
            "v2": sum(v2_extra) / len(v2_extra) if both_examples_degree else None,
            "n": len(both_examples_degree),
        },
        "only_v2_fragmented_examples": only_v2_examples,
        "only_v1_fragmented_examples": only_v1_examples,
    }
    out_path = args.out / f"v1_v2_fragmentation_comparison_{args.dataset.name}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
