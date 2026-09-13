#!/usr/bin/env python3
"""Stage 2 forensic analysis: why does the V1 boundary model predict false
boundaries inside otherwise-coherent GT executions?

Investigation only. Does not retrain with different settings, does not
choose a new threshold (reuses Stage 6's best_threshold=0.9078 exactly),
does not touch Dataset B, does not change features/reconstruction, adds
no merge/continuity logic.

Re-runs the identical LOSO procedure from Stage 6 manually rather than via
sklearn's cross_val_predict, specifically to keep each fold's fitted
pipeline — needed for honest per-transition feature-contribution
decomposition using the model that never saw a given session, not a
leakage-tainted one.

Usage:
    python scripts/forensic_false_boundaries.py --dataset dataset_a --out reports/day2
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from procmine.loaders.events import load_session_events
from procmine.loaders.ground_truth import load_gt_manifest, parse_gt_manifest_executions
from procmine.paths import discover_dataset
from procmine.segmentation.canonical import to_canonical_stream
from procmine.segmentation.features import extract_transition_features, label_transitions
from procmine.segmentation.model import FEATURE_NAMES, feature_vector, make_pipeline
from procmine.segmentation.signals import (
    app_switch_payload_key,
    deduplicate_consecutive,
    extract_boundaries,
)
from procmine.validation import ValidationReport

BEST_THRESHOLD = 0.9078  # from Stage 6 — reused exactly, not re-derived here


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    idx = min(int(len(s) * p), len(s) - 1)
    return s[idx]


def dist_summary(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "mean": round(statistics.fmean(values), 4),
        "median": round(statistics.median(values), 4),
        "p25": round(percentile(values, 0.25), 4),
        "p75": round(percentile(values, 0.75), 4),
        "p90": round(percentile(values, 0.90), 4),
        "p95": round(percentile(values, 0.95), 4),
    }


def rate_summary(bools: list[bool]) -> dict:
    if not bools:
        return {"n": 0, "rate": None}
    return {"n": len(bools), "rate": round(sum(bools) / len(bools), 4)}


def find_containing_execution(ts_i: int, ts_next: int, exec_spans: list[tuple]) -> tuple | None:
    """exec_spans: list of (start_ms, end_ms, case_id, process_code).
    Returns the span whose [start,end] fully contains this transition's two
    endpoints, or None (transition falls in an unlabeled noise gap, or spans
    across two different executions/labels)."""
    for span in exec_spans:
        start, end, _, _ = span
        if start <= ts_i and ts_next <= end:
            return span
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    sessions = discover_dataset(args.dataset)

    per_session = {}  # session_id -> dict of everything needed
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

        # deduplicated app_switch event_ids, to check overlap with duplicates
        deduped = deduplicate_consecutive(events, "app_switch", app_switch_payload_key)
        deduped_ids = {e.event_id for e in deduped if e.event_type == "app_switch"}
        raw_app_switch_ids = {e.event_id for e in events if e.event_type == "app_switch"}
        duplicate_app_switch_ids = raw_app_switch_ids - deduped_ids

        exec_spans = [
            (int(e.start_ts.timestamp() * 1000), int(e.end_ts.timestamp() * 1000), e.case_id, e.process_code)
            for e in executions
            if e.end_ts is not None
        ]

        per_session[session.session_id] = {
            "canonical": canonical,
            "labeled": labeled,
            "duplicate_app_switch_ids": duplicate_app_switch_ids,
            "exec_spans": exec_spans,
            "n_gt_executions": len(exec_spans),
        }

    print(f"{len(per_session)} sessions loaded", file=sys.stderr)

    # Flatten for LOSO, remembering row ranges per session
    X_rows, y_rows, groups = [], [], []
    row_session = []
    for sid, data in per_session.items():
        for lt in data["labeled"]:
            X_rows.append(feature_vector(lt.features))
            y_rows.append(1 if lt.is_boundary else 0)
            groups.append(sid)
            row_session.append(sid)
    X = np.array(X_rows)
    y = np.array(y_rows)
    session_ids_unique = sorted(per_session.keys())
    print(f"{X.shape[0]} transitions, {len(session_ids_unique)} sessions — running manual LOSO "
          f"(this fits {len(session_ids_unique)} models; identical procedure to Stage 6, "
          f"just keeping the per-fold pipelines this time)", file=sys.stderr)

    groups_arr = np.array(groups)
    oof_probs = np.zeros(len(y))
    fold_models: dict[str, object] = {}
    for held_out in session_ids_unique:
        train_mask = groups_arr != held_out
        test_mask = groups_arr == held_out
        pipeline = make_pipeline()
        pipeline.fit(X[train_mask], y[train_mask])
        oof_probs[test_mask] = pipeline.predict_proba(X[test_mask])[:, 1]
        fold_models[held_out] = pipeline

    print("LOSO complete.", file=sys.stderr)

    # --- Classify every transition, per session ---
    row_idx = 0
    all_records = []  # false-internal records
    session_summary = {}
    true_boundary_feat_rows = []
    false_internal_feat_rows = []
    true_boundary_probs = []
    false_internal_probs = []
    false_noise_count = 0
    tp_count = fn_count = tn_count = 0

    for sid in session_ids_unique:
        data = per_session[sid]
        labeled = data["labeled"]
        canonical = data["canonical"]
        exec_spans = data["exec_spans"]
        dup_ids = data["duplicate_app_switch_ids"]
        n = len(labeled)
        session_probs = oof_probs[row_idx : row_idx + n]
        pipeline = fold_models[sid]
        clf = pipeline.named_steps["clf"]
        scaler = pipeline.named_steps["scale"]

        n_predicted = 0
        n_false_internal = 0
        exec_false_count: dict = defaultdict(int)  # keyed by (case_id) -> count

        for i, (lt, prob) in enumerate(zip(labeled, session_probs)):
            predicted = bool(prob >= BEST_THRESHOLD)
            if predicted:
                n_predicted += 1

            f = lt.features
            if lt.is_boundary:
                if predicted:
                    tp_count += 1
                else:
                    fn_count += 1
                true_boundary_feat_rows.append(f)
                true_boundary_probs.append(float(prob))
                continue

            if not predicted:
                tn_count += 1
                continue

            # predicted=True, is_boundary=False -> false positive.
            # classify as internal (inside a GT execution span) vs noise (outside any)
            span = find_containing_execution(f.timestamp_ms, f.next_timestamp_ms, exec_spans)
            if span is None:
                false_noise_count += 1
                continue

            n_false_internal += 1
            exec_false_count[span[2]] += 1  # keyed by case_id
            false_internal_feat_rows.append(f)
            false_internal_probs.append(float(prob))

            # feature contribution: standardized_value * coefficient, per feature
            raw_vec = np.array(feature_vector(f)).reshape(1, -1)
            standardized = scaler.transform(raw_vec)[0]
            contributions = {
                name: round(float(standardized[j] * clf.coef_[0][j]), 4)
                for j, name in enumerate(FEATURE_NAMES)
            }

            before = canonical[i]
            after = canonical[i + 1]
            all_records.append(
                {
                    "session_id": sid,
                    "gt_case_id": span[2],
                    "gt_process_code": span[3],
                    "event_i_id": f.event_i_id,
                    "event_next_id": f.event_next_id,
                    "timestamp_before_ms": f.timestamp_ms,
                    "timestamp_after_ms": f.next_timestamp_ms,
                    "delta_t_ms": f.delta_t_ms,
                    "model_probability": round(float(prob), 4),
                    "application_before": before.application,
                    "application_after": after.application,
                    "application_changed": f.application_changed,
                    "window_title_changed": f.window_title_changed,
                    "browser_domain_changed": f.browser_domain_changed,
                    "interaction_category_before": before.interaction_category,
                    "interaction_category_after": after.interaction_category,
                    "event_type_before": before.event_type,
                    "event_type_after": after.event_type,
                    "extracted_text_at_transition": f.extracted_text_at_transition,
                    "chunk_boundary": f.chunk_boundary,
                    "duplicate_app_switch_involved": (
                        before.event_id in dup_ids or after.event_id in dup_ids
                    ),
                    "feature_contributions": contributions,
                }
            )

        n_exec = data["n_gt_executions"]
        fragmented = sum(1 for c in exec_false_count.values() if c > 0)
        session_summary[sid] = {
            "n_gt_executions": n_exec,
            "n_predicted_boundaries": n_predicted,
            "n_false_internal": n_false_internal,
            "false_splits_per_execution": round(n_false_internal / n_exec, 3) if n_exec else None,
            "pct_executions_fragmented": round(100 * fragmented / n_exec, 1) if n_exec else None,
            "worst_execution_false_count": max(exec_false_count.values()) if exec_false_count else 0,
            "median_execution_false_count": (
                statistics.median(list(exec_false_count.values()) + [0] * (n_exec - len(exec_false_count)))
                if n_exec
                else None
            ),
        }
        row_idx += n

    print(f"TP={tp_count} FN={fn_count} TN={tn_count} "
          f"false_internal={len(all_records)} false_noise(excluded)={false_noise_count}", file=sys.stderr)

    # --- Feature distribution comparison: true boundaries vs false internal ---
    def col(rows, attr):
        return [getattr(r, attr) for r in rows]

    feature_comparison = {}
    for feat_name, is_bool in [
        ("delta_t_ms", False), ("log1p_delta_t_ms", False),
        ("density_before", False), ("density_after", False),
        ("application_changed", True), ("window_title_changed", True),
        ("browser_domain_changed", True), ("interaction_category_changed", True),
        ("extracted_text_at_transition", True), ("chunk_boundary", True),
    ]:
        true_vals = col(true_boundary_feat_rows, feat_name)
        false_vals = col(false_internal_feat_rows, feat_name)
        if is_bool:
            feature_comparison[feat_name] = {
                "true_boundaries": rate_summary(true_vals),
                "false_internal": rate_summary(false_vals),
            }
        else:
            feature_comparison[feat_name] = {
                "true_boundaries": dist_summary(true_vals),
                "false_internal": dist_summary(false_vals),
            }

    probability_comparison = {
        "true_boundaries": dist_summary(true_boundary_probs),
        "false_internal": dist_summary(false_internal_probs),
    }

    # --- Feature contribution analysis: mean contribution among false internals ---
    contribution_agg = defaultdict(list)
    for rec in all_records:
        for name, val in rec["feature_contributions"].items():
            contribution_agg[name].append(val)
    contribution_summary = {
        name: {
            "mean_contribution": round(statistics.fmean(vals), 4),
            "positive_rate": round(sum(1 for v in vals if v > 0) / len(vals), 4),
        }
        for name, vals in contribution_agg.items()
    }

    # --- Noise/duplicate relationship ---
    n_dup_involved = sum(1 for r in all_records if r["duplicate_app_switch_involved"])
    n_chunk_boundary = sum(1 for r in all_records if r["chunk_boundary"])
    noise_relationship = {
        "n_false_internal_total": len(all_records),
        "involving_duplicate_app_switch": {
            "n": n_dup_involved,
            "rate": round(n_dup_involved / len(all_records), 4) if all_records else None,
        },
        "at_chunk_boundary": {
            "n": n_chunk_boundary,
            "rate": round(n_chunk_boundary / len(all_records), 4) if all_records else None,
        },
    }

    # --- Save artifacts ---
    with (args.out / f"false_boundary_records_{args.dataset.name}.json").open("w", encoding="utf-8") as f:
        json.dump(all_records, f, indent=None, ensure_ascii=False)
    with (args.out / f"false_boundary_session_summary_{args.dataset.name}.json").open("w", encoding="utf-8") as f:
        json.dump(session_summary, f, indent=2, ensure_ascii=False)

    summary = {
        "tp": tp_count, "fn": fn_count, "tn": tn_count,
        "n_false_internal": len(all_records),
        "n_false_noise_excluded": false_noise_count,
        "feature_comparison": feature_comparison,
        "probability_comparison": probability_comparison,
        "contribution_summary": contribution_summary,
        "noise_relationship": noise_relationship,
    }
    with (args.out / f"false_boundary_forensics_{args.dataset.name}.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(json.dumps(summary, indent=2), file=sys.stderr)
    print(f"\nWrote reports to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
