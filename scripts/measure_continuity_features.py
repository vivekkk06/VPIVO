#!/usr/bin/env python3
"""Stage 5: measure univariate discrimination of candidate continuity
features against the approved S=1/S=0 labels, before any model training.

No model is trained here. No feature selection is finalized. This
produces the evidence Stage 6 (model training) will be scoped from.

Usage:
    python scripts/measure_continuity_features.py --dataset dataset_a --out reports/day2
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np
from sklearn.metrics import roc_auc_score

from procmine.loaders.events import load_session_events
from procmine.loaders.ground_truth import load_gt_manifest, parse_gt_manifest_executions
from procmine.paths import discover_dataset
from procmine.segmentation.canonical import to_canonical_stream
from procmine.segmentation.context_features import _hostname_only, extract_trajectory_features
from procmine.segmentation.continuity_labels import label_continuity
from procmine.segmentation.features import extract_transition_features
from procmine.segmentation.signals import extract_boundaries
from procmine.validation import ValidationReport

WINDOW_SIZES = [3, 5, 10]


def safe_auc(values: list, labels: list) -> dict:
    """Drops None entries before computing AUC; reports coverage
    separately since missingness itself is information about the feature,
    not something to silently paper over."""
    pairs = [(v, l) for v, l in zip(values, labels) if v is not None]
    coverage = len(pairs) / len(values) if values else 0.0
    if len(pairs) < 10 or len({l for _, l in pairs}) < 2:
        return {"auc": None, "n": len(pairs), "coverage": round(coverage, 4)}
    v = [p[0] for p in pairs]
    l = [p[1] for p in pairs]
    try:
        auc = roc_auc_score(l, v)
    except ValueError:
        return {"auc": None, "n": len(pairs), "coverage": round(coverage, 4)}
    # report as "distance from uninformative" -- 0.5 means no discrimination
    return {"auc": round(float(auc), 4), "n": len(pairs), "coverage": round(coverage, 4)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    sessions = discover_dataset(args.dataset)

    # rows: dict of feature_name -> list of values (None allowed), aligned
    # with `labels` and `session_ids` by index
    rows: dict[str, list] = {}
    labels: list[int] = []
    session_ids: list[str] = []

    def add(name, value):
        rows.setdefault(name, []).append(value)

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

        # session-relative temporal normalizer: median gap across ALL
        # transitions in this session (not just labeled ones) -- a
        # "local pace" reference, never touching GT
        all_gaps = [f.delta_t_ms for f in feats]
        session_median_gap = statistics.median(all_gaps) if all_gaps else 1.0
        session_median_gap = max(session_median_gap, 1.0)

        for i, (f, cl) in enumerate(zip(feats, clabels)):
            if cl.excluded:
                continue
            labels.append(cl.continuity_label)
            session_ids.append(session.session_id)

            # F0: existing V1 transition-level features
            add("V1_log1p_delta_t_ms", f.log1p_delta_t_ms)
            add("V1_density_before", float(f.density_before))
            add("V1_density_after", float(f.density_after))
            add("V1_application_changed", float(f.application_changed))
            add("V1_window_title_changed", float(f.window_title_changed))
            add("V1_browser_domain_changed_with_port", float(f.browser_domain_changed))
            add("V1_interaction_category_changed", float(f.interaction_category_changed))
            add("V1_extracted_text_at_transition", float(f.extracted_text_at_transition))
            add("V1_chunk_boundary", float(f.chunk_boundary))

            # T2: session-relative temporal normalization
            add("T2_delta_t_over_session_median", f.delta_t_ms / session_median_gap)

            # Browser domain V2 (host-only) at the single-transition level,
            # matching V1's port-inclusive comparison exactly
            host_i = _hostname_only(canonical[i].browser_url)
            host_next = _hostname_only(canonical[i + 1].browser_url)
            if host_i is None and host_next is None:
                add("V2_browser_domain_changed_host_only", None)
            else:
                add("V2_browser_domain_changed_host_only", float(host_i != host_next))

            # Trajectory features at each window size
            for n in WINDOW_SIZES:
                tf = extract_trajectory_features(canonical, i, n)
                add(f"N{n}_application_jaccard", tf.application_jaccard)
                add(f"N{n}_event_type_jaccard", tf.event_type_jaccard)
                add(f"N{n}_interaction_category_jaccard", tf.interaction_category_jaccard)
                add(f"N{n}_browser_domain_jaccard_with_port", tf.browser_domain_jaccard_with_port)
                add(f"N{n}_browser_domain_jaccard_host_only", tf.browser_domain_jaccard_host_only)
                add(f"N{n}_window_title_jaccard", tf.window_title_jaccard)
                add(f"N{n}_before_window_duration_ms", float(tf.before_window_duration_ms))
                add(f"N{n}_after_window_duration_ms", float(tf.after_window_duration_ms))

    print(f"{len(labels)} labeled transitions across {len(set(session_ids))} sessions", file=sys.stderr)

    # Note: for Jaccard-similarity features, S=1 (same execution) is
    # expected to correlate with HIGH similarity, so AUC should be
    # interpreted with that in mind -- report raw AUC and let >0.5 mean
    # "higher values predict S=1" throughout, consistently.
    results = {}
    for name, values in rows.items():
        results[name] = safe_auc(values, labels)

    print("\nPooled univariate AUC (0.5 = no discrimination):", file=sys.stderr)
    for name, r in sorted(results.items(), key=lambda kv: -abs((kv[1]["auc"] or 0.5) - 0.5)):
        auc_str = f"{r['auc']:.4f}" if r["auc"] is not None else "N/A"
        print(f"  {name:<45} AUC={auc_str}  coverage={r['coverage']:.3f}  n={r['n']}", file=sys.stderr)

    # Per-session AUC stability for the strongest few features
    top_features = sorted(
        (k for k, v in results.items() if v["auc"] is not None),
        key=lambda k: -abs(results[k]["auc"] - 0.5),
    )[:6]

    per_session_stability = {}
    for name in top_features:
        values = rows[name]
        by_session_vals: dict[str, list] = {}
        by_session_labels: dict[str, list] = {}
        for v, l, sid in zip(values, labels, session_ids):
            by_session_vals.setdefault(sid, []).append(v)
            by_session_labels.setdefault(sid, []).append(l)
        session_aucs = []
        for sid in by_session_vals:
            r = safe_auc(by_session_vals[sid], by_session_labels[sid])
            if r["auc"] is not None:
                session_aucs.append(r["auc"])
        if session_aucs:
            per_session_stability[name] = {
                "n_sessions_with_valid_auc": len(session_aucs),
                "mean": round(statistics.fmean(session_aucs), 4),
                "std": round(statistics.pstdev(session_aucs), 4) if len(session_aucs) > 1 else 0.0,
                "min": round(min(session_aucs), 4),
                "max": round(max(session_aucs), 4),
            }

    print("\nPer-session AUC stability for top features:", file=sys.stderr)
    for name, s in per_session_stability.items():
        print(f"  {name:<45} mean={s['mean']} std={s['std']} min={s['min']} max={s['max']} "
              f"(n_sessions={s['n_sessions_with_valid_auc']})", file=sys.stderr)

    out = {
        "n_labeled_transitions": len(labels),
        "n_sessions": len(set(session_ids)),
        "pooled_auc": results,
        "per_session_stability_top_features": per_session_stability,
    }
    out_path = args.out / f"continuity_feature_measurement_{args.dataset.name}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
