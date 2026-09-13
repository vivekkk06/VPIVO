#!/usr/bin/env python3
"""Stage 8.3: first deterministic neighborhood-aware reconstruction
experiment (approved Design 2), compared against V1 and V2 baselines,
with Design 1 as an ablation.

Dataset A only. Does NOT retrain or retune V1/V2 (their exact LOSO
procedures and Stage 6 thresholds -- 0.9078, 0.8860 -- are re-run
unchanged, solely to obtain the candidate boundary set C = V1 predictions
UNION V2 predictions). Reconstruction only ever demotes members of C; it
never invents a boundary. All rule logic is implemented in
`procmine.segmentation.reconstruction` (unit-tested separately) --
reused here, not reimplemented.

GT (is_boundary labels, GT execution spans) is used in this script only
for: (a) selecting the Rule-4 continuity threshold from POOLED
out-of-fold evidence across all 63 sessions -- exactly the same
discipline, and the same kind of GT use, as Stage 6's original selection
of V1/V2's own thresholds -- and (b) evaluating the final, already-fixed
rule decisions afterward. The rule engine itself (reconstruction.py)
never receives GT as an input.

Usage:
    python scripts/run_reconstruction_experiment.py --dataset dataset_a --out reports/day2
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
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
from procmine.segmentation.reconstruction import (
    RULE_1_CHUNK_NOISE,
    RULE_2_RETURN_PATTERN,
    RULE_3_CLUSTER_PROTECTION,
    RULE_4_CONTINUITY,
    apply_design1_rule,
    apply_design2_rules,
    cluster_size_per_transition,
    compute_rule2_demotions,
    involves_duplicate_app_switch,
    union_candidates,
)
from procmine.segmentation.signals import app_switch_payload_key, deduplicate_consecutive, extract_boundaries
from procmine.segmentation.threshold_analysis import build_threshold_grid
from procmine.validation import ValidationReport

V1_THRESHOLD = 0.9078  # Stage 6 -- reused exactly, never retuned
V2_BOUNDARY_SCORE_THRESHOLD = 0.8860  # Stage 6 -- reused exactly, never retuned
TRAJECTORY_WINDOW_N = 10  # Stage 5's evidence-backed window -- reused for Rules 2 and 4 alike
RECALL_FLOOR = 0.5  # Stage 7's justified floor -- reused, not re-derived
ALL_RULES = [RULE_1_CHUNK_NOISE, RULE_2_RETURN_PATTERN, RULE_3_CLUSTER_PROTECTION, RULE_4_CONTINUITY]


def percentile(values, p):
    if not values:
        return None
    s = sorted(values)
    idx = min(int(len(s) * p), len(s) - 1)
    return s[idx]


def dist_summary(values):
    if not values:
        return {"n": 0}
    return {
        "n": len(values), "mean": round(statistics.fmean(values), 4),
        "median": round(statistics.median(values), 4),
        "std": round(statistics.pstdev(values), 4) if len(values) > 1 else 0.0,
        "min": round(min(values), 4), "max": round(max(values), 4),
    }


def load_dataset(dataset_dir: Path) -> dict[str, dict]:
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


def run_v1_loso(per_session: dict, session_ids: list[str]) -> dict[str, np.ndarray]:
    y_v1 = np.array([1 if lt.is_boundary else 0
                      for sid in session_ids for lt in per_session[sid]["is_boundary_labels"]])
    groups_v1 = np.array([sid for sid in session_ids for _ in per_session[sid]["is_boundary_labels"]])
    X_v1_all = np.vstack([per_session[sid]["X_v1"] for sid in session_ids])
    v1_pred_by_session = {}
    for held_out in session_ids:
        mask = groups_v1 != held_out
        pipeline = make_pipeline()
        pipeline.fit(X_v1_all[mask], y_v1[mask])
        probs = pipeline.predict_proba(per_session[held_out]["X_v1"])[:, 1]
        v1_pred_by_session[held_out] = probs >= V1_THRESHOLD
    return v1_pred_by_session


def run_v2_loso(per_session: dict, session_ids: list[str]) -> dict[str, np.ndarray]:
    X_v2_train, y_v2_train, groups_v2_train = [], [], []
    for sid in session_ids:
        d = per_session[sid]
        for x, cl in zip(d["X_v2"], d["clabels"]):
            if cl.excluded:
                continue
            X_v2_train.append(x); y_v2_train.append(cl.continuity_label); groups_v2_train.append(sid)
    X_v2_train = np.array(X_v2_train); y_v2_train = np.array(y_v2_train); groups_v2_train = np.array(groups_v2_train)
    v2_pred_by_session = {}
    for held_out in session_ids:
        mask = groups_v2_train != held_out
        pipeline = make_pipeline()
        pipeline.fit(X_v2_train[mask], y_v2_train[mask])
        s1_probs = pipeline.predict_proba(per_session[held_out]["X_v2"])[:, 1]
        boundary_score = 1 - s1_probs
        v2_pred_by_session[held_out] = boundary_score >= V2_BOUNDARY_SCORE_THRESHOLD
    return v2_pred_by_session


def evaluate_boundary_set(
    per_session: dict, session_ids: list[str], predicted_by_session: dict[str, list[bool]]
) -> dict:
    """Full pooled + per-session boundary and execution metrics for one
    predicted-boundary array per session, using the exact, unmodified
    `boundary_metrics`/`execution_metrics`/`segments_from_boundaries`."""
    all_lt = []
    all_preds = []
    per_session_metrics = {}
    total_gt_exec = 0
    total_fragmented = 0
    over_seg_num = over_seg_den = 0.0
    under_seg_num = under_seg_den = 0.0

    for sid in session_ids:
        d = per_session[sid]
        lt = d["is_boundary_labels"]
        preds = predicted_by_session[sid]
        all_lt.extend(lt)
        all_preds.extend(preds)

        sbm = boundary_metrics(lt, list(preds))
        segs = segments_from_boundaries(sid, d["ts"], list(preds))
        em = execution_metrics(d["executions"], segs)

        per_session_metrics[sid] = {
            "precision": sbm.precision, "recall": sbm.recall, "f1": sbm.f1,
            "n_gt_boundaries": sbm.n_gt_boundaries, "n_predicted": sbm.n_predicted,
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
    session_pct_frag = [m["pct_fragmented"] for m in per_session_metrics.values()]
    session_f1 = [m["f1"] for m in per_session_metrics.values()]

    return {
        "pooled": {
            "precision": pooled_bm.precision, "recall": pooled_bm.recall, "f1": pooled_bm.f1,
            "tp": pooled_bm.tp, "fp": pooled_bm.fp, "fn": pooled_bm.fn,
            "n_gt_boundaries": pooled_bm.n_gt_boundaries, "n_predicted": pooled_bm.n_predicted,
            "over_segmentation_rate": over_seg_num / over_seg_den if over_seg_den else None,
            "under_segmentation_rate": under_seg_num / under_seg_den if under_seg_den else None,
            "n_gt_executions_total": total_gt_exec,
            "n_gt_executions_fragmented": total_fragmented,
            "pct_gt_executions_fragmented": 100 * total_fragmented / total_gt_exec if total_gt_exec else None,
        },
        "per_session": per_session_metrics,
        "per_session_pct_fragmented_summary": dist_summary(session_pct_frag),
        "per_session_f1_summary": dist_summary(session_f1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    per_session = load_dataset(args.dataset)
    session_ids = sorted(per_session.keys())
    n_gt_exec_total = sum(len(d["executions"]) for d in per_session.values())
    n_transitions_total = sum(len(d["feats"]) for d in per_session.values())
    print(f"{len(session_ids)} sessions, {n_gt_exec_total} GT executions, "
          f"{n_transitions_total} transitions loaded", file=sys.stderr)

    print("Running V1 LOSO...", file=sys.stderr)
    v1_pred_by_session = run_v1_loso(per_session, session_ids)
    print("Running V2 LOSO...", file=sys.stderr)
    v2_pred_by_session = run_v2_loso(per_session, session_ids)
    print("Both LOSO runs complete.", file=sys.stderr)

    # === Per-session evidence needed by the rule engine (no GT involved) ===
    session_evidence = {}
    same_execution_indices_by_session: dict[str, set[int]] = {}
    for sid in session_ids:
        d = per_session[sid]
        feats = d["feats"]
        canonical = d["canonical"]
        n = len(feats)

        candidates = union_candidates(v1_pred_by_session[sid].tolist(), v2_pred_by_session[sid].tolist())
        chunk_boundary = [f.chunk_boundary for f in feats]
        duplicate_noise = [
            involves_duplicate_app_switch(f.event_i_id, f.event_next_id, d["duplicate_app_switch_ids"])
            for f in feats
        ]
        cluster_size = cluster_size_per_transition(candidates)
        candidate_indices = [i for i, c in enumerate(candidates) if c]
        rule2_demote_indices, rule2_details = compute_rule2_demotions(
            canonical, candidate_indices, TRAJECTORY_WINDOW_N
        )

        event_type_jaccard: list[float | None] = [None] * n
        for i in candidate_indices:
            traj = extract_trajectory_features(canonical, i, TRAJECTORY_WINDOW_N)
            event_type_jaccard[i] = traj.event_type_jaccard

        session_evidence[sid] = {
            "candidates": candidates, "chunk_boundary": chunk_boundary,
            "duplicate_noise": duplicate_noise, "cluster_size": cluster_size,
            "candidate_indices": candidate_indices,
            "rule2_demote_indices": rule2_demote_indices, "rule2_details": rule2_details,
            "event_type_jaccard": event_type_jaccard,
        }

        # same-execution transition set, for the rule-level diagnostic
        # breakdown ONLY (never fed into the rule engine) -- reuses
        # interruption_forensics.internal_transition_indices exactly.
        same_exec: set[int] = set()
        for execution in d["executions"]:
            start_ms = int(execution.start_ts.timestamp() * 1000)
            end_ms = int(execution.end_ts.timestamp() * 1000)
            same_exec.update(internal_transition_indices(feats, start_ms, end_ms))
        same_execution_indices_by_session[sid] = same_exec

    n_candidates_total = sum(len(ev["candidate_indices"]) for ev in session_evidence.values())
    print(f"{n_candidates_total} candidate boundaries (V1 UNION V2) across all sessions", file=sys.stderr)

    # === LEAKAGE AUDIT (structural, printed for the record) ===
    print("\n--- Leakage audit ---", file=sys.stderr)
    print("Rule-engine inputs: v1/v2 held-out predictions, chunk_boundary (raw-event-derived), "
          "duplicate_app_switch (raw-event-derived), cluster_size (derived from candidates only), "
          "return-pattern evidence (raw application/browser_domain fields only), "
          "event_type_jaccard (raw event-type sequence only).", file=sys.stderr)
    print("None of these reference GT case_id, process_code, process_variant, GT execution spans, "
          "GT boundary labels, or continuity labels. GT is used ONLY below, for threshold selection "
          "(pooled/global, mirroring how V1/V2's own thresholds were selected in Stage 6) and for "
          "post-hoc evaluation.", file=sys.stderr)

    # === Rule-4 threshold selection: pooled OOF evidence, Stage 7's grid method ===
    rule4_eligible_jaccards = []
    rule4_eligible_is_true_boundary = []
    for sid in session_ids:
        d = per_session[sid]
        ev = session_evidence[sid]
        for i in ev["candidate_indices"]:
            if ev["chunk_boundary"][i] or ev["duplicate_noise"][i]:
                continue
            if i in ev["rule2_demote_indices"]:
                continue
            if ev["cluster_size"][i] >= 2:
                continue
            jac = ev["event_type_jaccard"][i]
            if jac is None:
                continue
            rule4_eligible_jaccards.append(jac)
            rule4_eligible_is_true_boundary.append(d["is_boundary_labels"][i].is_boundary)

    print(f"\n{len(rule4_eligible_jaccards)} Rule-4-eligible candidates "
          f"(isolated, not chunk/noise, not return-pattern)", file=sys.stderr)
    grid = build_threshold_grid(np.array(rule4_eligible_jaccards))
    print(f"Threshold grid: {len(grid)} candidate values, range [{min(grid):.3f}, {max(grid):.3f}]",
          file=sys.stderr)

    def design2_final_boundary(tau: float) -> dict[str, list[bool]]:
        out = {}
        for sid in session_ids:
            ev = session_evidence[sid]
            r = apply_design2_rules(
                candidates=ev["candidates"], chunk_boundary=ev["chunk_boundary"],
                duplicate_noise=ev["duplicate_noise"], rule2_demote_indices=ev["rule2_demote_indices"],
                cluster_size=ev["cluster_size"], event_type_jaccard=ev["event_type_jaccard"],
                continuity_threshold=tau,
            )
            out[sid] = r.final_boundary
        return out

    sweep_rows = []
    for tau in grid:
        preds = design2_final_boundary(tau)
        result = evaluate_boundary_set(per_session, session_ids, preds)
        sweep_rows.append({
            "threshold": tau, "precision": result["pooled"]["precision"],
            "recall": result["pooled"]["recall"], "f1": result["pooled"]["f1"],
            "pct_gt_executions_fragmented": result["pooled"]["pct_gt_executions_fragmented"],
            "over_segmentation_rate": result["pooled"]["over_segmentation_rate"],
            "under_segmentation_rate": result["pooled"]["under_segmentation_rate"],
        })

    candidates_at_floor = [r for r in sweep_rows if r["recall"] >= RECALL_FLOOR]
    if candidates_at_floor:
        best = max(candidates_at_floor, key=lambda r: r["f1"])
    else:
        best = max(sweep_rows, key=lambda r: r["f1"])
    selected_tau = best["threshold"]

    print(f"\nSelected Rule-4 threshold: {selected_tau:.4f} "
          f"(P={best['precision']:.3f} R={best['recall']:.3f} F1={best['f1']:.3f} "
          f"frag%={best['pct_gt_executions_fragmented']:.1f})", file=sys.stderr)
    print("Selection rule: max F1 among thresholds with recall >= 0.5 (Stage 7's justified floor), "
          "reusing Stage 7's percentile-based grid construction.", file=sys.stderr)

    # === Final Design 2 and Design 1 (ablation) at the selected threshold ===
    design2_preds = design2_final_boundary(selected_tau)

    design1_preds = {}
    design1_rule_applied = {}
    design2_rule_applied = {}
    for sid in session_ids:
        ev = session_evidence[sid]
        r1 = apply_design1_rule(
            candidates=ev["candidates"], chunk_boundary=ev["chunk_boundary"],
            duplicate_noise=ev["duplicate_noise"], event_type_jaccard=ev["event_type_jaccard"],
            continuity_threshold=selected_tau,
        )
        design1_preds[sid] = r1.final_boundary
        design1_rule_applied[sid] = r1.rule_applied

        r2 = apply_design2_rules(
            candidates=ev["candidates"], chunk_boundary=ev["chunk_boundary"],
            duplicate_noise=ev["duplicate_noise"], rule2_demote_indices=ev["rule2_demote_indices"],
            cluster_size=ev["cluster_size"], event_type_jaccard=ev["event_type_jaccard"],
            continuity_threshold=selected_tau,
        )
        design2_rule_applied[sid] = r2.rule_applied

    v1_result = evaluate_boundary_set(per_session, session_ids, {sid: v1_pred_by_session[sid].tolist() for sid in session_ids})
    v2_result = evaluate_boundary_set(per_session, session_ids, {sid: v2_pred_by_session[sid].tolist() for sid in session_ids})
    design2_result = evaluate_boundary_set(per_session, session_ids, design2_preds)
    design1_result = evaluate_boundary_set(per_session, session_ids, design1_preds)

    print(f"\nV1 baseline:        F1={v1_result['pooled']['f1']:.3f} "
          f"frag%={v1_result['pooled']['pct_gt_executions_fragmented']:.1f}", file=sys.stderr)
    print(f"V2 baseline:        F1={v2_result['pooled']['f1']:.3f} "
          f"frag%={v2_result['pooled']['pct_gt_executions_fragmented']:.1f}", file=sys.stderr)
    print(f"Design 2 (recon):   F1={design2_result['pooled']['f1']:.3f} "
          f"frag%={design2_result['pooled']['pct_gt_executions_fragmented']:.1f}", file=sys.stderr)
    print(f"Design 1 (ablation):F1={design1_result['pooled']['f1']:.3f} "
          f"frag%={design1_result['pooled']['pct_gt_executions_fragmented']:.1f}", file=sys.stderr)

    # === Rule-level diagnostic breakdown (Design 2) ===
    rule_breakdown = {r: {"n_matched": 0, "n_removed": 0, "n_gt_correct_removed": 0,
                           "n_false_internal_removed": 0, "n_noise_gap_removed": 0}
                       for r in ALL_RULES}
    for sid in session_ids:
        d = per_session[sid]
        candidates = session_evidence[sid]["candidates"]
        rule_applied = design2_rule_applied[sid]
        final_boundary = design2_preds[sid]
        same_exec = same_execution_indices_by_session[sid]
        for i, cand in enumerate(candidates):
            if not cand:
                continue
            rule = rule_applied[i]
            rule_breakdown[rule]["n_matched"] += 1
            if not final_boundary[i]:
                rule_breakdown[rule]["n_removed"] += 1
                if d["is_boundary_labels"][i].is_boundary:
                    rule_breakdown[rule]["n_gt_correct_removed"] += 1
                elif i in same_exec:
                    rule_breakdown[rule]["n_false_internal_removed"] += 1
                else:
                    rule_breakdown[rule]["n_noise_gap_removed"] += 1

    print("\nRule-level breakdown (Design 2):", file=sys.stderr)
    for rule, stats in rule_breakdown.items():
        print(f"  {rule}: matched={stats['n_matched']} removed={stats['n_removed']} "
              f"gt_correct_removed={stats['n_gt_correct_removed']} "
              f"false_internal_removed={stats['n_false_internal_removed']} "
              f"noise_gap_removed={stats['n_noise_gap_removed']}", file=sys.stderr)

    # === Success gate checks ===
    v1_frag = v1_result["pooled"]["pct_gt_executions_fragmented"]
    v2_frag = v2_result["pooled"]["pct_gt_executions_fragmented"]
    d2_frag = design2_result["pooled"]["pct_gt_executions_fragmented"]
    d2_recall = design2_result["pooled"]["recall"]
    v1_underseg = v1_result["pooled"]["under_segmentation_rate"]
    v2_underseg = v2_result["pooled"]["under_segmentation_rate"]
    d2_underseg = design2_result["pooled"]["under_segmentation_rate"]

    total_removed = sum(s["n_removed"] for s in rule_breakdown.values())
    total_noise_removed = rule_breakdown[RULE_1_CHUNK_NOISE]["n_removed"]
    gain_explained_by_noise_only = (total_noise_removed / total_removed) if total_removed else 0.0

    session_deltas = []
    for sid in session_ids:
        base = min(v1_result["per_session"][sid]["pct_fragmented"], v2_result["per_session"][sid]["pct_fragmented"])
        d2 = design2_result["per_session"][sid]["pct_fragmented"]
        session_deltas.append(base - d2)  # positive = improvement

    gate = {
        "1_fragmentation_materially_lower_than_both": {
            "pass": (d2_frag is not None and v1_frag is not None and v2_frag is not None
                     and d2_frag < v1_frag and d2_frag < v2_frag),
            "v1_frag": v1_frag, "v2_frag": v2_frag, "design2_frag": d2_frag,
        },
        "2_recall_at_or_above_floor": {"pass": d2_recall >= RECALL_FLOOR, "recall": d2_recall, "floor": RECALL_FLOOR},
        "3_under_segmentation_not_materially_worse": {
            "pass": (d2_underseg is not None and v1_underseg is not None and v2_underseg is not None
                     and d2_underseg <= max(v1_underseg, v2_underseg) * 1.5),
            "v1_underseg": v1_underseg, "v2_underseg": v2_underseg, "design2_underseg": d2_underseg,
        },
        "4_improvement_not_concentrated_in_few_sessions": {
            "n_sessions_improved": sum(1 for x in session_deltas if x > 0),
            "n_sessions_worse": sum(1 for x in session_deltas if x < 0),
            "n_sessions_total": len(session_deltas),
            "mean_improvement_pp": round(statistics.fmean(session_deltas), 2),
            "std_improvement_pp": round(statistics.pstdev(session_deltas), 2) if len(session_deltas) > 1 else 0.0,
        },
        "5_gain_not_explained_solely_by_chunk_noise": {
            "pass": gain_explained_by_noise_only < 0.5,
            "fraction_of_removals_from_rule1": round(gain_explained_by_noise_only, 4),
        },
    }

    print("\n--- Success gate ---", file=sys.stderr)
    print(json.dumps(gate, indent=2, default=str), file=sys.stderr)

    # === Write artifacts ===
    out = {
        "n_sessions": len(session_ids), "n_gt_executions": n_gt_exec_total,
        "n_transitions_total": n_transitions_total,
        "n_candidates_total": n_candidates_total,
        "threshold_selection": {
            "n_rule4_eligible_candidates": len(rule4_eligible_jaccards),
            "grid": grid, "sweep": sweep_rows, "selected_threshold": selected_tau,
            "selected_row": best,
        },
        "v1_baseline": v1_result, "v2_baseline": v2_result,
        "design2_reconstruction": design2_result, "design1_ablation": design1_result,
        "rule_level_breakdown": rule_breakdown,
        "success_gate": gate,
    }
    out_path = args.out / f"reconstruction_experiment_{args.dataset.name}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nWrote {out_path}", file=sys.stderr)
    print("Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
