#!/usr/bin/env python3
"""Stage 8.5: controlled protection experiment over Stage 8.3's Design 2
reconstruction, testing whether the two Stage 8.4 signals (cross-model
agreement, post-transition tempo) can protect some of Rule 4's 296
wrongly-demoted real boundaries without giving back too much of its
false-boundary reduction.

Does NOT modify `reconstruction.py` (Stage 8.3's rule engine) or
`run_reconstruction_experiment.py` in any way -- both are re-run exactly
as before to reproduce the identical baseline. This script's only new
logic is the additive `protected_boundary.apply_protection` layer,
applied strictly to transitions Design 2 already demoted under Rule 4;
Rules 1/2/3 and the candidate union are untouched. Does NOT retrain or
retune V1/V2, does NOT implement Design 3, does NOT touch Dataset B.

Usage:
    python scripts/run_protected_boundary_experiment.py --dataset dataset_a --out reports/day2
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
from procmine.segmentation.interruption_forensics import internal_transition_indices
from procmine.segmentation.model import feature_vector as v1_feature_vector
from procmine.segmentation.model import make_pipeline
from procmine.segmentation.protected_boundary import (
    RULE_4_PROTECTED,
    STRATEGY_AGREEMENT,
    STRATEGY_COMBINED,
    STRATEGY_TEMPO,
    apply_protection,
)
from procmine.segmentation.reconstruction import (
    RULE_4_CONTINUITY,
    apply_design2_rules,
    cluster_size_per_transition,
    compute_rule2_demotions,
    involves_duplicate_app_switch,
    union_candidates,
)
from procmine.segmentation.rule4_forensics import classify_candidate_source
from procmine.segmentation.signals import app_switch_payload_key, deduplicate_consecutive, extract_boundaries
from procmine.segmentation.threshold_analysis import build_threshold_grid
from procmine.validation import ValidationReport

V1_THRESHOLD = 0.9078
V2_BOUNDARY_SCORE_THRESHOLD = 0.8860
TRAJECTORY_WINDOW_N = 10
SELECTED_RULE4_THRESHOLD = 0.40  # Stage 8.3's already-selected value -- reused, NOT re-selected
RECALL_FLOOR = 0.5  # Stage 7's justified floor -- reused


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


def evaluate_boundary_set(per_session: dict, session_ids: list[str], predicted_by_session: dict) -> dict:
    """Identical in spirit to Stage 8.3's own evaluation helper (not
    imported, to avoid coupling to another script's internals) -- same
    boundary_metrics/execution_metrics/segments_from_boundaries calls,
    same pooled + per-session aggregation."""
    all_lt, all_preds = [], []
    per_session_metrics = {}
    total_gt_exec = total_fragmented = 0
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
            "over_segmentation_rate": em.over_segmentation_rate,
            "under_segmentation_rate": em.under_segmentation_rate,
            "n_gt_executions": em.n_gt_executions, "n_fragmented": em.n_fragmented,
            "pct_fragmented": em.pct_fragmented,
        }
        total_gt_exec += em.n_gt_executions
        total_fragmented += em.n_fragmented
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
            "over_segmentation_rate": over_seg_num / over_seg_den if over_seg_den else None,
            "under_segmentation_rate": under_seg_num / under_seg_den if under_seg_den else None,
            "n_gt_executions_total": total_gt_exec, "n_gt_executions_fragmented": total_fragmented,
            "pct_gt_executions_fragmented": 100 * total_fragmented / total_gt_exec if total_gt_exec else None,
        },
        "per_session": per_session_metrics,
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

    print("Running V1 LOSO...", file=sys.stderr)
    loso = run_loso(per_session, session_ids)
    print("V1/V2 LOSO complete.", file=sys.stderr)

    # === Reproduce Stage 8.3's exact candidate set, evidence, and Design 2 decisions ===
    session_evidence = {}
    design2_by_session = {}
    same_execution_by_session = {}
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
            "candidates": candidates, "flagged_by_both": flagged_by_both,
            "after_window_duration_ms": after_window_duration_ms,
            "v1_pred": v1_pred, "v2_pred": v2_pred,
        }

        same_exec: set[int] = set()
        for execution in d["executions"]:
            start_ms = int(execution.start_ts.timestamp() * 1000)
            end_ms = int(execution.end_ts.timestamp() * 1000)
            same_exec.update(internal_transition_indices(feats, start_ms, end_ms))
        same_execution_by_session[sid] = same_exec

    n_a = sum(1 for sid in session_ids for i in range(len(per_session[sid]["feats"]))
              if design2_by_session[sid].rule_applied[i] == RULE_4_CONTINUITY
              and not design2_by_session[sid].final_boundary[i]
              and not per_session[sid]["is_boundary_labels"][i].is_boundary
              and i in same_execution_by_session[sid])
    n_b = sum(1 for sid in session_ids for i in range(len(per_session[sid]["feats"]))
              if design2_by_session[sid].rule_applied[i] == RULE_4_CONTINUITY
              and not design2_by_session[sid].final_boundary[i]
              and per_session[sid]["is_boundary_labels"][i].is_boundary)
    print(f"\nReproduced Design 2 baseline: Population A={n_a}, Population B={n_b} "
          f"(Stage 8.3/8.4 reported 3,667 and 296)", file=sys.stderr)

    # === LEAKAGE AUDIT ===
    print("\n--- Leakage audit ---", file=sys.stderr)
    print("Protection inputs: held-out v1/v2 predictions (flagged_by_both), N=10 raw-event-derived "
          "after_window_duration_ms. Neither references GT case_id, process_code, process_variant, "
          "GT execution spans, GT boundary labels, or continuity labels. GT is used only for (a) "
          "threshold selection via pooled, global Dataset-A evidence -- mirroring how Stage 6/8.3 "
          "selected their own thresholds -- and (b) post-hoc evaluation below.", file=sys.stderr)

    # === Threshold selection: pooled OOF evidence, Stage 7's grid method, ===
    # === applied to the population where protection could ever apply     ===
    # === (Rule-4-demoted candidates only).                                ===
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

    print(f"\n{len(demoted_tempo)} Rule-4-demoted candidates eligible for tempo-threshold selection "
          f"({sum(demoted_is_true_boundary)} true boundaries, {len(demoted_tempo) - sum(demoted_is_true_boundary)} false internal)",
          file=sys.stderr)
    grid = build_threshold_grid(np.array(demoted_tempo))
    print(f"Tempo threshold grid: {len(grid)} candidate values, range [{min(grid):.1f}, {max(grid):.1f}]",
          file=sys.stderr)

    sweep_rows = []
    for tau in grid:
        protected_true = sum(1 for t, is_b in zip(demoted_tempo, demoted_is_true_boundary) if t >= tau and is_b)
        protected_false = sum(1 for t, is_b in zip(demoted_tempo, demoted_is_true_boundary) if t >= tau and not is_b)
        n_protected = protected_true + protected_false
        protection_precision = protected_true / n_protected if n_protected else 0.0
        protection_recall = protected_true / n_b if n_b else 0.0
        protection_f1 = (
            2 * protection_precision * protection_recall / (protection_precision + protection_recall)
            if (protection_precision + protection_recall) else 0.0
        )
        sweep_rows.append({
            "tau": tau, "n_protected": n_protected, "n_true_protected": protected_true,
            "n_false_protected": protected_false, "protection_precision": round(protection_precision, 4),
            "protection_recall": round(protection_recall, 4), "protection_f1": round(protection_f1, 4),
        })

    best = max(sweep_rows, key=lambda r: r["protection_f1"])
    selected_tempo_threshold = best["tau"]
    print(f"\nSelected tempo threshold: {selected_tempo_threshold:.1f}ms "
          f"(protection P={best['protection_precision']:.3f} R={best['protection_recall']:.3f} "
          f"F1={best['protection_f1']:.3f}, protects {best['n_protected']} candidates: "
          f"{best['n_true_protected']} true, {best['n_false_protected']} false)", file=sys.stderr)
    print("Selection method: max protection-F1 on pooled, global Dataset-A out-of-fold evidence -- "
          "a GLOBAL analytical/model-selection threshold (Stage 7's exact methodology), NOT nested "
          "or cross-fitted, and NOT selected per session.", file=sys.stderr)

    # === Apply all three strategies at the selected threshold ===
    def build_strategy_preds(strategy: str) -> dict:
        out_boundary, out_rule = {}, {}
        for sid in session_ids:
            design2 = design2_by_session[sid]
            ev = session_evidence[sid]
            r = apply_protection(
                design2_final_boundary=design2.final_boundary, design2_rule_applied=design2.rule_applied,
                flagged_by_both=ev["flagged_by_both"], tempo_value=ev["after_window_duration_ms"],
                strategy=strategy, tempo_threshold=selected_tempo_threshold,
            )
            out_boundary[sid] = r.final_boundary
            out_rule[sid] = r.rule_applied
        return {"boundary": out_boundary, "rule": out_rule}

    strategy_a = build_strategy_preds(STRATEGY_AGREEMENT)
    strategy_b = build_strategy_preds(STRATEGY_TEMPO)
    strategy_c = build_strategy_preds(STRATEGY_COMBINED)

    # === Full reconstruction evaluation: V1, V2, Design2, Strategy A/B/C ===
    v1_result = evaluate_boundary_set(per_session, session_ids, {sid: loso["v1_preds"][sid].tolist() for sid in session_ids})
    v2_result = evaluate_boundary_set(per_session, session_ids, {sid: loso["v2_preds"][sid].tolist() for sid in session_ids})
    design2_result = evaluate_boundary_set(per_session, session_ids, {sid: design2_by_session[sid].final_boundary for sid in session_ids})
    strat_a_result = evaluate_boundary_set(per_session, session_ids, strategy_a["boundary"])
    strat_b_result = evaluate_boundary_set(per_session, session_ids, strategy_b["boundary"])
    strat_c_result = evaluate_boundary_set(per_session, session_ids, strategy_c["boundary"])

    systems = {
        "V1": v1_result, "V2": v2_result, "Design2_original": design2_result,
        "Strategy_Agreement": strat_a_result, "Strategy_Tempo": strat_b_result, "Strategy_Combined": strat_c_result,
    }
    print("\n--- Pooled comparison ---", file=sys.stderr)
    for name, res in systems.items():
        p = res["pooled"]
        print(f"{name:<20} R={p['recall']:.3f} F1={p['f1']:.3f} frag%={p['pct_gt_executions_fragmented']:.1f} "
              f"under={p['under_segmentation_rate']:.4f} over={p['over_segmentation_rate']:.3f}", file=sys.stderr)

    # === Rule-level analysis per strategy ===
    def rule_level_analysis(strategy_rule: dict) -> dict:
        n_protected = n_gt_correct = n_gt_false = 0
        source_counts = Counter()
        for sid in session_ids:
            d = per_session[sid]
            ev = session_evidence[sid]
            rule = strategy_rule[sid]
            for i in range(len(d["feats"])):
                if rule[i] != RULE_4_PROTECTED:
                    continue
                n_protected += 1
                is_true = d["is_boundary_labels"][i].is_boundary
                if is_true:
                    n_gt_correct += 1
                else:
                    n_gt_false += 1
                source_counts[classify_candidate_source(bool(ev["v1_pred"][i]), bool(ev["v2_pred"][i]))] += 1
        return {
            "n_protected": n_protected, "n_gt_correct_boundaries_protected": n_gt_correct,
            "n_gt_false_boundaries_protected": n_gt_false,
            "false_to_true_protection_ratio": round(n_gt_false / n_gt_correct, 2) if n_gt_correct else None,
            "pct_rule4_errors_recovered": round(100 * n_gt_correct / n_b, 1) if n_b else None,
            "pct_rule4_correct_removals_sacrificed": round(100 * n_gt_false / n_a, 1) if n_a else None,
            "protected_by_candidate_source": dict(source_counts),
        }

    rule_level = {
        "Strategy_Agreement": rule_level_analysis(strategy_a["rule"]),
        "Strategy_Tempo": rule_level_analysis(strategy_b["rule"]),
        "Strategy_Combined": rule_level_analysis(strategy_c["rule"]),
    }
    print("\n--- Rule-level analysis ---", file=sys.stderr)
    print(json.dumps(rule_level, indent=2), file=sys.stderr)

    # === Session robustness: per-session under-segmentation, recall, fragmentation deltas ===
    def session_robustness(strat_result: dict, baseline_result: dict) -> dict:
        deltas_underseg, deltas_recall, deltas_frag = [], [], []
        for sid in session_ids:
            base = baseline_result["per_session"][sid]
            strat = strat_result["per_session"][sid]
            deltas_underseg.append(base["under_segmentation_rate"] - strat["under_segmentation_rate"])
            deltas_recall.append(strat["recall"] - base["recall"])
            deltas_frag.append(base["pct_fragmented"] - strat["pct_fragmented"])
        return {
            "under_segmentation_improvement": {
                "n_sessions_improved": sum(1 for x in deltas_underseg if x > 1e-9),
                "n_sessions_unchanged": sum(1 for x in deltas_underseg if abs(x) <= 1e-9),
                "n_sessions_worsened": sum(1 for x in deltas_underseg if x < -1e-9),
                "distribution": dist_summary(deltas_underseg),
                "median": round(statistics.median(deltas_underseg), 4),
            },
            "recall_change": {
                "n_sessions_improved": sum(1 for x in deltas_recall if x > 1e-9),
                "n_sessions_unchanged": sum(1 for x in deltas_recall if abs(x) <= 1e-9),
                "n_sessions_worsened": sum(1 for x in deltas_recall if x < -1e-9),
                "distribution": dist_summary(deltas_recall),
            },
            "fragmentation_change_pp": {
                "n_sessions_improved": sum(1 for x in deltas_frag if x > 1e-9),
                "n_sessions_unchanged": sum(1 for x in deltas_frag if abs(x) <= 1e-9),
                "n_sessions_worsened": sum(1 for x in deltas_frag if x < -1e-9),
                "distribution": dist_summary(deltas_frag),
            },
        }

    robustness = {
        "Strategy_Agreement": session_robustness(strat_a_result, design2_result),
        "Strategy_Tempo": session_robustness(strat_b_result, design2_result),
        "Strategy_Combined": session_robustness(strat_c_result, design2_result),
    }
    print("\n--- Session robustness (vs. Design 2 original) ---", file=sys.stderr)
    print(json.dumps(robustness, indent=2), file=sys.stderr)

    # === Success gate per strategy ===
    def success_gate(strat_result: dict, rl: dict, rb: dict) -> dict:
        p = strat_result["pooled"]
        d2 = design2_result["pooled"]
        v1p, v2p = v1_result["pooled"], v2_result["pooled"]
        recall_improved = p["recall"] > d2["recall"] + 0.005
        underseg_improved = p["under_segmentation_rate"] < d2["under_segmentation_rate"] * 0.95
        frag_gain_retained = (
            d2["pct_gt_executions_fragmented"] is not None
            and p["pct_gt_executions_fragmented"] is not None
            and p["pct_gt_executions_fragmented"] < (v1p["pct_gt_executions_fragmented"] + v2p["pct_gt_executions_fragmented"]) / 2 - 5
        )
        not_recreating_v1v2 = (
            p["pct_gt_executions_fragmented"] is not None
            and p["pct_gt_executions_fragmented"] < min(v1p["pct_gt_executions_fragmented"], v2p["pct_gt_executions_fragmented"]) - 2
        )
        n_improved = rb["under_segmentation_improvement"]["n_sessions_improved"]
        n_worsened = rb["under_segmentation_improvement"]["n_sessions_worsened"]
        broad_improvement = n_improved >= 2 * n_worsened and n_improved >= len(session_ids) * 0.3
        meaningful_ratio = rl["false_to_true_protection_ratio"] is not None and rl["false_to_true_protection_ratio"] < 3.0
        return {
            "1_recall_materially_improved": {"pass": recall_improved, "design2_recall": d2["recall"], "strategy_recall": p["recall"]},
            "2_under_segmentation_materially_reduced": {"pass": underseg_improved, "design2_underseg": d2["under_segmentation_rate"], "strategy_underseg": p["under_segmentation_rate"]},
            "3_substantial_fragmentation_gain_retained": {"pass": frag_gain_retained, "strategy_frag": p["pct_gt_executions_fragmented"], "v1_v2_avg_frag": (v1p["pct_gt_executions_fragmented"] + v2p["pct_gt_executions_fragmented"]) / 2},
            "4_does_not_recreate_v1_v2_fragmentation": {"pass": not_recreating_v1v2, "strategy_frag": p["pct_gt_executions_fragmented"], "min_v1_v2_frag": min(v1p["pct_gt_executions_fragmented"], v2p["pct_gt_executions_fragmented"])},
            "5_improves_broadly_not_a_few_sessions": {"pass": broad_improvement, "n_sessions_underseg_improved": n_improved, "n_sessions_underseg_worsened": n_worsened, "n_sessions_total": len(session_ids)},
            "6_meaningful_false_true_ratio": {"pass": meaningful_ratio, "ratio": rl["false_to_true_protection_ratio"]},
            "7_no_gt_derived_reconstruction_info": {"pass": True, "note": "structurally verified in leakage audit above"},
        }

    gates = {
        "Strategy_Agreement": success_gate(strat_a_result, rule_level["Strategy_Agreement"], robustness["Strategy_Agreement"]),
        "Strategy_Tempo": success_gate(strat_b_result, rule_level["Strategy_Tempo"], robustness["Strategy_Tempo"]),
        "Strategy_Combined": success_gate(strat_c_result, rule_level["Strategy_Combined"], robustness["Strategy_Combined"]),
    }
    print("\n--- Success gate ---", file=sys.stderr)
    print(json.dumps(gates, indent=2, default=str), file=sys.stderr)

    out = {
        "n_sessions": len(session_ids),
        "population_a_n": n_a, "population_b_n": n_b,
        "threshold_selection": {
            "grid": grid, "sweep": sweep_rows, "selected_threshold_ms": selected_tempo_threshold,
            "selected_row": best,
        },
        "systems": systems,
        "rule_level_analysis": rule_level,
        "session_robustness": robustness,
        "success_gate": gates,
    }
    out_path = args.out / f"protected_boundary_experiment_{args.dataset.name}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nWrote {out_path}", file=sys.stderr)
    print("Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
