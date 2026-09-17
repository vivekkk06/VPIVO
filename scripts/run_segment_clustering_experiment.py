#!/usr/bin/env python3
"""Day 6, Phase 6: can density-based clustering of segment-level behaviour
recover the Day-3 process grouping?

This tests the *labelling* question, which is separate from segmentation:
"which segments look like the same kind of work?" It never alters a
segmentation boundary — it consumes the already-validated Dataset-B
executions as given.

Critical design choice — avoiding a circular test:
`dominant_context` (the Day-3 process label) is itself derived from the
systems an execution touches. Clustering on system identity would therefore
recover the labels trivially and prove nothing. The primary feature set is
deliberately **behavioural only**: duration, event count, step count, number
of distinct systems touched (a count, never an identity), and the
distributions of interaction categories and event types. A second, clearly
marked variant *does* include system identity, purely to show the contrast
and make the circularity visible rather than hidden.

Correspondence with the Day-3 labels is measured with Adjusted Rand Index
and Normalised Mutual Information. These are agreement measures against an
existing grouping, not accuracy claims — Dataset B has no ground truth.

HDBSCAN comes from scikit-learn (already a dependency); no new package.

Usage:
    python scripts/run_segment_clustering_experiment.py \
        --executions reports/day3/process_executions_dataset_b.json \
        --out reports/day6
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.cluster import HDBSCAN
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score
from sklearn.preprocessing import StandardScaler

MIN_CLUSTER_SIZES = [5, 10, 15, 20]


def build_features(executions: list[dict], include_system_identity: bool):
    """Return (X, feature_names). Behavioural features only unless the
    circularity-demonstration variant is requested."""
    cats: set[str] = set()
    etypes: set[str] = set()
    systems: set[str] = set()
    for ex in executions:
        for s in ex.get("ordered_steps", []):
            cats.add(s.get("interaction_category") or "none")
            for t, _ in s.get("dominant_event_types", []):
                etypes.add(t)
            if s.get("system"):
                systems.add(s["system"])
    cats_l, etypes_l = sorted(cats), sorted(etypes)
    systems_l = sorted(systems)

    names = ["log_duration_ms", "log_event_count", "n_steps", "n_distinct_systems",
             "n_applications"]
    names += [f"cat::{c}" for c in cats_l]
    names += [f"etype::{t}" for t in etypes_l]
    if include_system_identity:
        names += [f"sys::{s}" for s in systems_l]

    rows = []
    for ex in executions:
        steps = ex.get("ordered_steps", [])
        cat_counts = Counter()
        etype_counts = Counter()
        sys_counts = Counter()
        for s in steps:
            cat_counts[s.get("interaction_category") or "none"] += s.get("n_events", 0)
            for t, n in s.get("dominant_event_types", []):
                etype_counts[t] += n
            if s.get("system"):
                sys_counts[s["system"]] += s.get("n_events", 0)

        total_cat = sum(cat_counts.values()) or 1
        total_et = sum(etype_counts.values()) or 1
        total_sy = sum(sys_counts.values()) or 1

        row = [
            float(np.log1p(ex.get("duration_ms", 0))),
            float(np.log1p(ex.get("event_count", 0))),
            float(len(steps)),
            float(len({s.get("system") for s in steps if s.get("system")})),
            float(len(ex.get("applications", []) or [])),
        ]
        row += [cat_counts[c] / total_cat for c in cats_l]
        row += [etype_counts[t] / total_et for t in etypes_l]
        if include_system_identity:
            row += [sys_counts[s] / total_sy for s in systems_l]
        rows.append(row)

    return np.array(rows, dtype=float), names


def run_variant(x: np.ndarray, labels_true: list[str], tag: str) -> dict:
    xs = StandardScaler().fit_transform(x)
    out = {}
    for mcs in MIN_CLUSTER_SIZES:
        model = HDBSCAN(min_cluster_size=mcs)
        pred = model.fit_predict(xs)
        noise = int(np.sum(pred == -1))
        clustered = pred != -1
        n_clusters = int(len({c for c in pred if c != -1}))

        # agreement measured on clustered points only: noise is not a group
        if clustered.sum() > 1 and n_clusters > 1:
            ari = float(adjusted_rand_score(
                [labels_true[i] for i in range(len(pred)) if clustered[i]],
                pred[clustered],
            ))
            nmi = float(normalized_mutual_info_score(
                [labels_true[i] for i in range(len(pred)) if clustered[i]],
                pred[clustered],
            ))
        else:
            ari = nmi = float("nan")

        sizes = sorted(Counter(pred[clustered].tolist()).values(), reverse=True)
        out[f"min_cluster_size={mcs}"] = {
            "n_clusters": n_clusters,
            "n_noise": noise,
            "noise_fraction": round(noise / len(pred), 4),
            "n_clustered": int(clustered.sum()),
            "cluster_sizes_top10": sizes[:10],
            "adjusted_rand_index_vs_day3_labels": None if np.isnan(ari) else round(ari, 4),
            "normalized_mutual_info_vs_day3_labels": None if np.isnan(nmi) else round(nmi, 4),
        }
        print(f"  [{tag}] mcs={mcs:>2}: clusters={n_clusters:>3} "
              f"noise={noise:>3} ({noise/len(pred):>5.1%}) "
              f"ARI={ari:.4f} NMI={nmi:.4f}", file=sys.stderr)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--executions", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    data = json.loads(args.executions.read_text(encoding="utf-8"))
    executions = data["executions"]
    labels_true = [ex["dominant_context"] for ex in executions]
    n_true = len(set(labels_true))
    print(f"{len(executions)} Dataset-B executions, {n_true} distinct Day-3 process labels",
          file=sys.stderr)

    print("\nPrimary variant — behavioural features only (system identity EXCLUDED):",
          file=sys.stderr)
    x_beh, names_beh = build_features(executions, include_system_identity=False)
    beh = run_variant(x_beh, labels_true, "behavioural")

    print("\nContrast variant — system identity INCLUDED (circular by construction):",
          file=sys.stderr)
    x_sys, names_sys = build_features(executions, include_system_identity=True)
    sysv = run_variant(x_sys, labels_true, "with-identity")

    best_beh = max(
        beh.values(),
        key=lambda r: (r["adjusted_rand_index_vs_day3_labels"] or -1),
    )
    best_sys = max(
        sysv.values(),
        key=lambda r: (r["adjusted_rand_index_vs_day3_labels"] or -1),
    )

    out = {
        "experiment": "Day-6 Phase 6 — HDBSCAN segment-level clustering for process grouping",
        "scope_note": "Clustering answers the labelling question only. No segmentation boundary "
                      "was altered; the Day-3 executions are consumed as given.",
        "no_ground_truth_note": "Dataset B has no ground truth. ARI/NMI measure agreement with "
                                "the existing Day-3 grouping, not accuracy.",
        "circularity_note": "dominant_context is derived from the systems an execution touches, "
                            "so the primary feature set excludes system identity. The contrast "
                            "variant includes it only to make that circularity visible.",
        "n_executions": len(executions),
        "n_day3_process_labels": n_true,
        "n_features_behavioural": len(names_beh),
        "n_features_with_identity": len(names_sys),
        "min_cluster_sizes": MIN_CLUSTER_SIZES,
        "behavioural_only": beh,
        "with_system_identity_circular": sysv,
        "best_ari_behavioural": best_beh["adjusted_rand_index_vs_day3_labels"],
        "best_ari_with_identity": best_sys["adjusted_rand_index_vs_day3_labels"],
    }
    path = args.out / "segment_clustering_experiment_dataset_b.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nBest ARI behavioural-only: {out['best_ari_behavioural']}", file=sys.stderr)
    print(f"Best ARI with identity:    {out['best_ari_with_identity']}", file=sys.stderr)
    print(f"Wrote {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
