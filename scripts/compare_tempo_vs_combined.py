#!/usr/bin/env python3
"""Day 2 architecture lock, Steps 2-3: controlled final comparison between
Strategy Tempo and Strategy Combined (Stage 8.5), plus a threshold-
sensitivity check around the already-selected tempo threshold (4,680.3ms).

Reuses the exact same pipeline as Stage 8.3/8.5 (V1/V2 LOSO, unchanged
thresholds; apply_design2_rules with tau=0.40, unchanged; apply_protection,
unchanged) -- no new classifier, no new feature family, no Design 3, no
per-session tuning, no GT-derived reconstruction input, no Dataset B.

This script does NOT re-select a threshold. Section 2 evaluates Tempo and
Combined at the already-selected tempo threshold with an extended metric
set. Section 3 sweeps the SAME threshold grid Stage 8.5 already built
(deterministic, reproduced here, not re-derived) to check whether the
Tempo-vs-Combined ordering and the fragmentation/recall trade-off are
stable near the selected point -- sensitivity analysis, not re-tuning.

Usage:
    python scripts/compare_tempo_vs_combined.py --dataset dataset_a --out reports/day2
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np

from procmine.loaders.events import load_session_events
from procmine.loaders.ground_truth import load_gt_manifest, parse_gt_manifest_executions
from procmine.paths import discover_dataset
from procmine.segmentation.canonical import to_canonical_stream
from procmine.segmentation.context_features import extract_trajectory_features
from procmine.segmentation.continuity_labels import label_continuity
from procmine.segmentation.continuity_model import continuity_feature_vector
from procmine.segmentation.evaluation import boundary_metrics, execution_metrics, segments_from_boundaries
from procmine.segmentation.features import extract_transition_features, label_transitions
from procmine.segmentation.model import feature_vector as v1_feature_vector
from procmine.segmentation.model import make_pipeline
from procmine.segmentation.protected_boundary import STRATEGY_COMBINED, STRATEGY_TEMPO, apply_protection
from procmine.segmentation.reconstruction import (
    RULE_4_CONTINUITY,
    apply_design2_rules,
    cluster_size_per_transition,
    compute_rule2_demotions,
    involves_duplicate_app_switch,
    union_candidates,
)
from procmine.segmentation.signals import app_switch_payload_key, deduplicate_consecutive, extract_boundaries
from procmine.segmentation.threshold_analysis import build_threshold_grid
from procmine.validation import ValidationReport

V1_THRESHOLD = 0.9078
V2_BOUNDARY_SCORE_THRESHOLD = 0.8860
TRAJECTORY_WINDOW_N = 10
SELECTED_RULE4_THRESHOLD = 0.40
SELECTED_TEMPO_THRESHOLD = 4680.2613  # Stage 8.5's already-selected value -- reused, NOT re-selected


def percentile(values, p):
    if not values:
        return None
    s = sorted(values)
    idx = min(int(len(s) * p), len(s) - 1)
    return s[idx]


def dist_summary(values):
    values = [v for v in values if v is not None]
    if not values:
        return {"n": 0}
    return {
        "n": len(values), "mean": round(statistics.fmean(values), 4),
        "median": round(statistics.median(values), 4),
        "std": round(statistics.pstdev(values), 4) if len(values) > 1 else 0.0,
        "p25": round(percentile(values, 0.25), 4), "p75": round(percentile(values, 0.75), 4),
        "min": round(min(values), 4), "max": round(max(values), 4),
    }


def load_dataset(dataset_dir: Path) -> dict:
    sessions = discover_dataset(dataset_dir)
    per_session = {}
    for session in sessions:
        if session.gt_manifest_path is None:
            continue
        report = ValidationReport(scope=session.session_id)
        events = load_session_events(session, report)
        gt_manifest = load_gt_manifest(session.gt_manifest_path, report)
        if gt_manifest is None or not events:
            continue
        executions_all = parse_gt_manifest_executions(gt_manifest)
        boundaries = extract_boundaries(session.session_id, executions_all)
        canonical = to_canonical_stream(events)
        feats = extract_transition_features(canonical)
        is_boundary_labels = label_transitions(feats, [(b.timestamp_ms, b.is_resume) for b in boundaries])
        clabels = label_continuity(session.session_id, feats, boundaries, executions_all)
        executions_closed = [e for e in executions_all if e.end_ts is not None]

        deduped = deduplicate_consecutive(events, "app_switch", app_switch_payload_key)
        deduped_ids = {e.event_id for e in deduped if e.event_type == "app_switch"}
        raw_app_switch_ids = {e.event_id for e in events if e.event_type == "app_switch"}
        duplicate_app_switch_ids = frozenset(raw_app_switch_ids - deduped_ids)

        X_v1 = np.array([v1_feature_vector(f) for f in feats])
        X_v2 = np.array([continuity_feature_vector(canonical, i, f) for i, f in enumerate(feats)])
        ts = [e.timestamp_ms for e in events]

        per_session[session.session_id] = {
            "canonical": canonical, "feats": feats,
            "is_boundary_labels": is_boundary_labels, "clabels": clabels,
            "executions": executions_closed,
            "duplicate_app_switch_ids": duplicate_app_switch_ids,
            "X_v1": X_v1, "X_v2": X_v2, "ts": ts,
        }
    return per_session


def run_loso(per_session: dict, session_ids: list[str]) -> dict:
    y_v1 = np.array([1 if lt.is_boundary else 0
                      for sid in session_ids for lt in per_session[sid]["is_boundary_labels"]])
    groups_v1 = np.array([sid for sid in session_ids for _ in per_session[sid]["is_boundary_labels"]])
    X_v1_all = np.vstack([per_session[sid]["X_v1"] for sid in session_ids])
    v1_preds = {}
    for held_out in session_ids:
        mask = groups_v1 != held_out
        pipeline = make_pipeline()
        pipeline.fit(X_v1_all[mask], y_v1[mask])
        probs = pipeline.predict_proba(per_session[held_out]["X_v1"])[:, 1]
        v1_preds[held_out] = probs >= V1_THRESHOLD

    X_v2_train, y_v2_train, groups_v2_train = [], [], []
    for sid in session_ids:
        d = per_session[sid]
        for x, cl in zip(d["X_v2"], d["clabels"]):
            if cl.excluded:
                continue
            X_v2_train.append(x); y_v2_train.append(cl.continuity_label); groups_v2_train.append(sid)
    X_v2_train = np.array(X_v2_train); y_v2_train = np.array(y_v2_train); groups_v2_train = np.array(groups_v2_train)
    v2_preds = {}
    for held_out in session_ids:
        mask = groups_v2_train != held_out
        pipeline = make_pipeline()
        pipeline.fit(X_v2_train[mask], y_v2_train[mask])
        s1_probs = pipeline.predict_proba(per_session[held_out]["X_v2"])[:, 1]
        boundary_score = 1 - s1_probs
        v2_preds[held_out] = boundary_score >= V2_BOUNDARY_SCORE_THRESHOLD
    return {"v1_preds": v1_preds, "v2_preds": v2_preds}


def evaluate_full(per_session: dict, session_ids: list[str], predicted_by_session: dict) -> dict:
    all_lt, all_preds = [], []
    per_session_metrics = {}
    total_gt_exec = total_fragmented = total_tp = total_fp = 0
    over_seg_num = over_seg_den = under_seg_num = under_seg_den = 0.0

    for sid in session_ids:
        d = per_session[sid]
        lt = d["is_boundary_labels"]
        preds = list(predicted_by_session[sid])
        all_lt.extend(lt)
        all_preds.extend(preds)

        sbm = boundary_metrics(lt, preds)
        segs = segments_from_boundaries(sid, d["ts"], preds)
        em = execution_metrics(d["executions"], segs)

        per_session_metrics[sid] = {
            "precision": sbm.precision, "recall": sbm.recall, "f1": sbm.f1,
            "tp": sbm.tp, "fp": sbm.fp, "fn": sbm.fn,
            "over_segmentation_rate": em.over_segmentation_rate,
            "under_segmentation_rate": em.under_segmentation_rate,
            "n_gt_executions": em.n_gt_executions, "n_fragmented": em.n_fragmented,
            "pct_fragmented": em.pct_fragmented,
            "fragmented_case_ids": sorted(em.fragmented_case_ids),
        }
        total_gt_exec += em.n_gt_executions
        total_fragmented += em.n_fragmented
        total_tp += sbm.tp
        total_fp += sbm.fp
        over_seg_num += em.over_segmentation_rate * em.n_gt_executions
        over_seg_den += em.n_gt_executions
        n_overlap_segs = em.n_predicted_segments - em.n_pure_noise_segments
        under_seg_num += em.under_segmentation_rate * n_overlap_segs
        under_seg_den += n_overlap_segs

    pooled_bm = boundary_metrics(all_lt, all_preds)
    return {
        "pooled": {
            "precision": pooled_bm.precision, "recall": pooled_bm.recall, "f1": pooled_bm.f1,
            "n_gt_boundaries": pooled_bm.n_gt_boundaries, "n_predicted": pooled_bm.n_predicted,
            "tp_true_boundaries_kept": pooled_bm.tp, "fn_true_boundaries_demoted": pooled_bm.fn,
            "fp_false_boundaries_kept": pooled_bm.fp,
            "tn_false_boundaries_correctly_absent": pooled_bm.n_transitions - pooled_bm.tp - pooled_bm.fp - pooled_bm.fn,
            "over_segmentation_rate_extra_fragments_per_execution": over_seg_num / over_seg_den if over_seg_den else None,
            "under_segmentation_rate": under_seg_num / under_seg_den if under_seg_den else None,
            "n_gt_executions_total": total_gt_exec, "n_gt_executions_fragmented": total_fragmented,
            "pct_gt_executions_fragmented": 100 * total_fragmented / total_gt_exec if total_gt_exec else None,
        },
        "per_session": per_session_metrics,
        "per_session_summaries": {
            "precision": dist_summary([m["precision"] for m in per_session_metrics.values()]),
            "recall": dist_summary([m["recall"] for m in per_session_metrics.values()]),
            "f1": dist_summary([m["f1"] for m in per_session_metrics.values()]),
            "pct_fragmented": dist_summary([m["pct_fragmented"] for m in per_session_metrics.values()]),
            "under_segmentation_rate": dist_summary([m["under_segmentation_rate"] for m in per_session_metrics.values()]),
            "over_segmentation_rate": dist_summary([m["over_segmentation_rate"] for m in per_session_metrics.values()]),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    per_session = load_dataset(args.dataset)
    session_ids = sorted(per_session.keys())
    print(f"{len(session_ids)} sessions loaded", file=sys.stderr)

    print("Running V1/V2 LOSO...", file=sys.stderr)
    loso = run_loso(per_session, session_ids)
    print("LOSO complete.", file=sys.stderr)

    session_evidence = {}
    design2_by_session = {}
    for sid in session_ids:
        d = per_session[sid]
        feats = d["feats"]
        canonical = d["canonical"]
        n = len(feats)
        v1_pred = loso["v1_preds"][sid]
        v2_pred = loso["v2_preds"][sid]

        candidates = union_candidates(v1_pred.tolist(), v2_pred.tolist())
        chunk_boundary = [f.chunk_boundary for f in feats]
        duplicate_noise = [
            involves_duplicate_app_switch(f.event_i_id, f.event_next_id, d["duplicate_app_switch_ids"])
            for f in feats
        ]
        cluster_size = cluster_size_per_transition(candidates)
        candidate_indices = [i for i, c in enumerate(candidates) if c]
        rule2_demote_indices, _ = compute_rule2_demotions(canonical, candidate_indices, TRAJECTORY_WINDOW_N)

        event_type_jaccard: list[float | None] = [None] * n
        after_window_duration_ms: list[float | None] = [None] * n
        for i in candidate_indices:
            traj = extract_trajectory_features(canonical, i, TRAJECTORY_WINDOW_N)
            event_type_jaccard[i] = traj.event_type_jaccard
            after_window_duration_ms[i] = float(traj.after_window_duration_ms)

        design2 = apply_design2_rules(
            candidates=candidates, chunk_boundary=chunk_boundary, duplicate_noise=duplicate_noise,
            rule2_demote_indices=rule2_demote_indices, cluster_size=cluster_size,
            event_type_jaccard=event_type_jaccard, continuity_threshold=SELECTED_RULE4_THRESHOLD,
        )
        design2_by_session[sid] = design2
        flagged_by_both = [bool(v1_pred[i]) and bool(v2_pred[i]) for i in range(n)]
        session_evidence[sid] = {
            "flagged_by_both": flagged_by_both, "after_window_duration_ms": after_window_duration_ms,
        }

    def build_strategy(strategy: str, tempo_threshold: float) -> dict:
        out = {}
        for sid in session_ids:
            design2 = design2_by_session[sid]
            ev = session_evidence[sid]
            r = apply_protection(
                design2_final_boundary=design2.final_boundary, design2_rule_applied=design2.rule_applied,
                flagged_by_both=ev["flagged_by_both"], tempo_value=ev["after_window_duration_ms"],
                strategy=strategy, tempo_threshold=tempo_threshold,
            )
            out[sid] = r.final_boundary
        return out

    # ===================== STEP 2: controlled comparison =====================
    tempo_preds = build_strategy(STRATEGY_TEMPO, SELECTED_TEMPO_THRESHOLD)
    combined_preds = build_strategy(STRATEGY_COMBINED, SELECTED_TEMPO_THRESHOLD)

    tempo_result = evaluate_full(per_session, session_ids, tempo_preds)
    combined_result = evaluate_full(per_session, session_ids, combined_preds)

    print("\n--- Step 2: Tempo vs Combined, global ---", file=sys.stderr)
    for name, res in [("Tempo", tempo_result), ("Combined", combined_result)]:
        p = res["pooled"]
        print(f"{name}: P={p['precision']:.4f} R={p['recall']:.4f} F1={p['f1']:.4f} "
              f"frag%={p['pct_gt_executions_fragmented']:.2f} under={p['under_segmentation_rate']:.4f} "
              f"over={p['over_segmentation_rate_extra_fragments_per_execution']:.4f} "
              f"TP={p['tp_true_boundaries_kept']} FN={p['fn_true_boundaries_demoted']} "
              f"FP={p['fp_false_boundaries_kept']}", file=sys.stderr)

    # Session-level comparison
    session_compare = {"pct_fragmented": {"tempo_better": 0, "combined_better": 0, "equal": 0},
                        "under_segmentation_rate": {"tempo_better": 0, "combined_better": 0, "equal": 0},
                        "recall": {"tempo_better": 0, "combined_better": 0, "equal": 0}}
    for sid in session_ids:
        t = tempo_result["per_session"][sid]
        c = combined_result["per_session"][sid]
        for metric, lower_is_better in [("pct_fragmented", True), ("under_segmentation_rate", True), ("recall", False)]:
            tv, cv = t[metric], c[metric]
            if abs(tv - cv) < 1e-9:
                session_compare[metric]["equal"] += 1
            elif (tv < cv) == lower_is_better:
                session_compare[metric]["tempo_better"] += 1
            else:
                session_compare[metric]["combined_better"] += 1

    # GT-execution-level comparison (fragmented under Tempo vs Combined)
    exec_compare = Counter()
    for sid in session_ids:
        t_frag = set(tempo_result["per_session"][sid]["fragmented_case_ids"])
        c_frag = set(combined_result["per_session"][sid]["fragmented_case_ids"])
        all_cases = t_frag | c_frag | {
            cid for cid in [e.case_id for e in per_session[sid]["executions"]]
        }
        for cid in all_cases:
            in_t, in_c = cid in t_frag, cid in c_frag
            if in_t and in_c:
                exec_compare["fragmented_under_both"] += 1
            elif in_t and not in_c:
                exec_compare["fragmented_under_tempo_only"] += 1
            elif in_c and not in_t:
                exec_compare["fragmented_under_combined_only"] += 1
            else:
                exec_compare["fragmented_under_neither"] += 1

    print("\nSession-level comparison (Tempo vs Combined):", file=sys.stderr)
    print(json.dumps(session_compare, indent=2), file=sys.stderr)
    print("\nGT-execution-level comparison:", file=sys.stderr)
    print(json.dumps(dict(exec_compare), indent=2), file=sys.stderr)

    # ===================== STEP 3: sensitivity analysis =====================
    # Reuses the exact same population and grid-construction method Stage
    # 8.5 already used -- deterministic reproduction, not a new selection.
    demoted_tempo, demoted_is_true_boundary = [], []
    for sid in session_ids:
        d = per_session[sid]
        design2 = design2_by_session[sid]
        ev = session_evidence[sid]
        for i in range(len(d["feats"])):
            if design2.rule_applied[i] != RULE_4_CONTINUITY or design2.final_boundary[i]:
                continue
            tempo = ev["after_window_duration_ms"][i]
            if tempo is None:
                continue
            demoted_tempo.append(tempo)
            demoted_is_true_boundary.append(d["is_boundary_labels"][i].is_boundary)

    grid = build_threshold_grid(np.array(demoted_tempo))
    grid_sorted = sorted(grid)
    selected_idx = min(range(len(grid_sorted)), key=lambda i: abs(grid_sorted[i] - SELECTED_TEMPO_THRESHOLD))
    neighborhood = grid_sorted[max(0, selected_idx - 4): selected_idx + 5]

    print(f"\n--- Step 3: sensitivity analysis around tau={SELECTED_TEMPO_THRESHOLD:.1f}ms ---", file=sys.stderr)
    print(f"Evaluating the {len(neighborhood)} grid points nearest the selected threshold "
          f"(same 52-point grid Stage 8.5 already built).", file=sys.stderr)

    sensitivity_rows = []
    for tau in neighborhood:
        t_preds = build_strategy(STRATEGY_TEMPO, tau)
        c_preds = build_strategy(STRATEGY_COMBINED, tau)
        t_res = evaluate_full(per_session, session_ids, t_preds)
        c_res = evaluate_full(per_session, session_ids, c_preds)
        row = {
            "tau": tau,
            "tempo": {"recall": t_res["pooled"]["recall"], "f1": t_res["pooled"]["f1"],
                      "pct_fragmented": t_res["pooled"]["pct_gt_executions_fragmented"],
                      "under_seg": t_res["pooled"]["under_segmentation_rate"]},
            "combined": {"recall": c_res["pooled"]["recall"], "f1": c_res["pooled"]["f1"],
                         "pct_fragmented": c_res["pooled"]["pct_gt_executions_fragmented"],
                         "under_seg": c_res["pooled"]["under_segmentation_rate"]},
        }
        sensitivity_rows.append(row)
        marker = " <-- selected" if abs(tau - SELECTED_TEMPO_THRESHOLD) < 1e-6 else ""
        print(f"  tau={tau:>10.1f}  Tempo: R={row['tempo']['recall']:.3f} F1={row['tempo']['f1']:.3f} "
              f"frag%={row['tempo']['pct_fragmented']:.1f} under={row['tempo']['under_seg']:.3f}  |  "
              f"Combined: R={row['combined']['recall']:.3f} F1={row['combined']['f1']:.3f} "
              f"frag%={row['combined']['pct_fragmented']:.1f} under={row['combined']['under_seg']:.3f}{marker}",
              file=sys.stderr)

    n_combined_higher_f1 = sum(1 for r in sensitivity_rows if r["combined"]["f1"] >= r["tempo"]["f1"])
    print(f"\nOrdering check: Combined F1 >= Tempo F1 in {n_combined_higher_f1}/{len(sensitivity_rows)} "
          f"neighboring grid points.", file=sys.stderr)

    out = {
        "step2_global": {"Tempo": tempo_result["pooled"], "Combined": combined_result["pooled"]},
        "step2_per_session_summaries": {
            "Tempo": tempo_result["per_session_summaries"], "Combined": combined_result["per_session_summaries"],
        },
        "step2_per_session": {"Tempo": tempo_result["per_session"], "Combined": combined_result["per_session"]},
        "step2_session_level_comparison": session_compare,
        "step2_execution_level_comparison": dict(exec_compare),
        "step3_sensitivity": {
            "selected_threshold": SELECTED_TEMPO_THRESHOLD,
            "neighborhood_grid": neighborhood,
            "rows": sensitivity_rows,
            "n_combined_f1_ge_tempo_f1_in_neighborhood": n_combined_higher_f1,
            "n_neighborhood_points": len(sensitivity_rows),
        },
    }
    out_path = args.out / f"tempo_vs_combined_comparison_{args.dataset.name}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nWrote {out_path}", file=sys.stderr)
    print("Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
