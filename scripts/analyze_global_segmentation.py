#!/usr/bin/env python3
"""Global-segmentation feasibility study (Day-2 follow-up research
question): is segmentation better formulated as a global sequence
optimization problem (minimize total intra-segment incoherence + a
per-boundary complexity penalty) than as independent per-transition
classification + local reconstruction rules?

This is a FORENSIC FEASIBILITY STUDY FIRST. It does not modify, retune,
or replace the locked Design 2 + Strategy Combined architecture
(`reconstruction.py`, `protected_boundary.py` are never imported here).
V1 (0.9078) and V2 (0.8860) are re-run only to reproduce the candidate
set C = V1 UNION V2 exactly as before -- not retrained differently, not
retuned. Dataset B is never touched.

Segment-cost components (see `global_segmentation_forensics.py`) are
built entirely from existing per-event/per-transition fields
(`CanonicalEvent.event_type` / `interaction_category`,
`TransitionFeatures.application_changed` / `browser_domain_changed` /
`log1p_delta_t_ms`), aggregated a new way (within one candidate-implied
segment), not a new feature family. No component, the composite score,
or the DP prototype (if reached) ever receives a GT-derived field as
input -- GT is used only to label a candidate TRUE/FALSE for the
forensic comparison, to select the threshold/lambda from pooled OOF
evidence (the same discipline as every prior threshold in this
project), and to evaluate the result.

Usage:
    python scripts/analyze_global_segmentation.py --dataset dataset_a --out reports/day2
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np
from sklearn.metrics import roc_auc_score

from procmine.loaders.events import load_session_events
from procmine.loaders.ground_truth import load_gt_manifest, parse_gt_manifest_executions
from procmine.paths import discover_dataset
from procmine.segmentation.canonical import to_canonical_stream
from procmine.segmentation.context_features import extract_trajectory_features
from procmine.segmentation.continuity_labels import label_continuity
from procmine.segmentation.continuity_model import continuity_feature_vector
from procmine.segmentation.evaluation import boundary_metrics, execution_metrics, segments_from_boundaries
from procmine.segmentation.features import extract_transition_features, label_transitions
from procmine.segmentation.global_segmentation_forensics import (
    compute_segment_cost,
    internal_feature_slice,
)
from procmine.segmentation.model import feature_vector as v1_feature_vector
from procmine.segmentation.model import make_pipeline
from procmine.segmentation.reconstruction import involves_duplicate_app_switch, union_candidates
from procmine.segmentation.segment_coherence import segment_index_bounds
from procmine.segmentation.signals import app_switch_payload_key, deduplicate_consecutive, extract_boundaries
from procmine.segmentation.threshold_analysis import build_threshold_grid
from procmine.validation import ValidationReport

V1_THRESHOLD = 0.9078
V2_BOUNDARY_SCORE_THRESHOLD = 0.8860
TRAJECTORY_WINDOW_N = 10
COMPONENTS = [
    "event_type_entropy_bits", "interaction_category_entropy_bits",
    "context_switch_rate", "temporal_irregularity_cv",
]
SEP_THRESHOLD = 0.10
AGREEMENT_THRESHOLD = 0.75
MIN_ELIGIBLE_SESSIONS = 15
RECALL_FLOOR = 0.5


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


def safe_auc(neg_values, pos_values):
    neg_values = [v for v in neg_values if v is not None]
    pos_values = [v for v in pos_values if v is not None]
    if not neg_values or not pos_values:
        return None
    y = [0] * len(neg_values) + [1] * len(pos_values)
    scores = [float(v) for v in neg_values] + [float(v) for v in pos_values]
    if len(set(scores)) == 1:
        return None
    try:
        return round(float(roc_auc_score(y, scores)), 4)
    except ValueError:
        return None


def session_direction_consistency(records, signal_key, positive_label):
    pos_by_session, neg_by_session = defaultdict(list), defaultdict(list)
    for r in records:
        v = r.get(signal_key)
        if v is None:
            continue
        (pos_by_session if r["label"] == positive_label else neg_by_session)[r["session_id"]].append(float(v))
    pooled_pos = statistics.fmean([v for vs in pos_by_session.values() for v in vs]) if pos_by_session else None
    pooled_neg = statistics.fmean([v for vs in neg_by_session.values() for v in vs]) if neg_by_session else None
    if pooled_pos is None or pooled_neg is None:
        return None
    pooled_direction = pooled_pos > pooled_neg
    n_agree = n_disagree = 0
    for sid in set(pos_by_session) & set(neg_by_session):
        sp = statistics.fmean(pos_by_session[sid])
        sn = statistics.fmean(neg_by_session[sid])
        if (sp > sn) == pooled_direction:
            n_agree += 1
        else:
            n_disagree += 1
    n_eligible = n_agree + n_disagree
    return {
        "n_sessions_eligible": n_eligible, "n_sessions_agree_with_pooled_direction": n_agree,
        "n_sessions_disagree": n_disagree,
        "agreement_rate": round(n_agree / n_eligible, 4) if n_eligible else None,
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
            "tp": pooled_bm.tp, "fp": pooled_bm.fp, "fn": pooled_bm.fn,
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

    print("Running V1/V2 LOSO (reproducing the candidate set only)...", file=sys.stderr)
    loso = run_loso(per_session, session_ids)
    print("LOSO complete.", file=sys.stderr)

    # === STEP 1/2: build the candidate-implied segmentation C' = ===
    # === (V1 UNION V2) minus Rule 1's already-validated chunk/    ===
    # === duplicate-noise override (reused, not re-litigated).     ===
    all_segments = []      # every (start,end) segment, every session -- for global cost normalization + purity check
    candidate_rows = []    # one row per C'-candidate, with SL/SR/merged costs
    n_candidates_total = n_rule1_filtered_total = 0

    for sid in session_ids:
        d = per_session[sid]
        feats = d["feats"]
        canonical = d["canonical"]
        n = len(feats)
        v1_pred = loso["v1_preds"][sid]
        v2_pred = loso["v2_preds"][sid]

        candidates = union_candidates(v1_pred.tolist(), v2_pred.tolist())
        n_candidates_total += sum(candidates)
        duplicate_noise = [
            involves_duplicate_app_switch(f.event_i_id, f.event_next_id, d["duplicate_app_switch_ids"])
            for f in feats
        ]
        c_prime = [c and not (f.chunk_boundary or dn) for c, f, dn in zip(candidates, feats, duplicate_noise)]
        n_rule1_filtered_total += sum(1 for c, cp in zip(candidates, c_prime) if c and not cp)

        bounds = segment_index_bounds(len(canonical), c_prime)
        seg_by_end = {end: (start, end) for start, end in bounds}
        seg_by_start = {start: (start, end) for start, end in bounds}

        seg_cost_cache = {}
        for start, end in bounds:
            cost = compute_segment_cost(canonical[start:end + 1], internal_feature_slice(feats, start, end))
            seg_cost_cache[(start, end)] = cost
            is_impure = any(d["is_boundary_labels"][j].is_boundary for j in range(start, end))
            all_segments.append({"session_id": sid, "label": "impure" if is_impure else "pure", **cost.to_dict()})

        for i in range(n):
            if not c_prime[i]:
                continue
            sl = seg_by_end[i]
            sr = seg_by_start[i + 1]
            cost_sl = seg_cost_cache[sl]
            cost_sr = seg_cost_cache[sr]
            cost_merged = compute_segment_cost(
                canonical[sl[0]:sr[1] + 1], internal_feature_slice(feats, sl[0], sr[1])
            )
            is_true = d["is_boundary_labels"][i].is_boundary
            row = {
                "session_id": sid, "index": i, "label": "TRUE" if is_true else "FALSE",
                "event_type_jaccard_n10": extract_trajectory_features(canonical, i, TRAJECTORY_WINDOW_N).event_type_jaccard,
            }
            for comp in COMPONENTS:
                row[f"sl_{comp}"] = getattr(cost_sl, comp)
                row[f"sr_{comp}"] = getattr(cost_sr, comp)
                row[f"merged_{comp}"] = getattr(cost_merged, comp)
            candidate_rows.append(row)

    n_true = sum(1 for r in candidate_rows if r["label"] == "TRUE")
    n_false = sum(1 for r in candidate_rows if r["label"] == "FALSE")
    print(f"\nCandidates (V1 UNION V2): {n_candidates_total}", file=sys.stderr)
    print(f"Rule-1-filtered (chunk/duplicate-noise, excluded from C'): {n_rule1_filtered_total}", file=sys.stderr)
    print(f"C' population: {len(candidate_rows)} (TRUE={n_true}, FALSE={n_false})", file=sys.stderr)
    print(f"Candidate-implied segments (all, for global cost scale + purity check): {len(all_segments)}", file=sys.stderr)

    # === Global normalization stats (population mean/std per component, ===
    # === computed once over every real candidate-implied segment -- a  ===
    # === data-driven scale, not a hand-picked constant).                ===
    global_stats = {}
    for comp in COMPONENTS:
        vals = [s[comp] for s in all_segments if s[comp] is not None]
        global_stats[comp] = {"mean": statistics.fmean(vals), "std": statistics.pstdev(vals) if len(vals) > 1 else 0.0}
    print("\nGlobal component scale (mean/std over all candidate-implied segments):", file=sys.stderr)
    print(json.dumps(global_stats, indent=2), file=sys.stderr)

    def z(value, comp):
        if value is None:
            return None
        std = global_stats[comp]["std"]
        return (value - global_stats[comp]["mean"]) / std if std > 0 else 0.0

    # ================ STEP 3: component-level forensics ================
    component_verdicts = []
    for comp in COMPONENTS:
        false_vals = [r[f"merged_{comp}"] for r in candidate_rows if r["label"] == "FALSE"]
        true_vals = [r[f"merged_{comp}"] for r in candidate_rows if r["label"] == "TRUE"]
        auc = safe_auc(false_vals, true_vals)  # positive class = TRUE (real boundary)
        sep = round(abs(auc - 0.5), 4) if auc is not None else None
        robustness = session_direction_consistency(
            [{"session_id": r["session_id"], "label": r["label"], f"merged_{comp}": r[f"merged_{comp}"]} for r in candidate_rows],
            f"merged_{comp}", "TRUE",
        )
        component_verdicts.append({
            "component": comp, "auc_TRUE_positive": auc, "separation": sep,
            "false_dist": dist_summary(false_vals), "true_dist": dist_summary(true_vals),
            "session_robustness": robustness,
        })
    print("\n--- STEP 3: component forensics (merged-segment cost, TRUE vs FALSE candidates) ---", file=sys.stderr)
    for v in component_verdicts:
        r = v["session_robustness"]
        print(f"  {v['component']:<35} AUC={v['auc_TRUE_positive']} sep={v['separation']} "
              f"agree={r['agreement_rate'] if r else None} (n_elig={r['n_sessions_eligible'] if r else None})",
              file=sys.stderr)

    # --- purity check: does a segment's OWN cost correlate with whether ---
    # --- it actually contains a missed (uncaptured) GT boundary?        ---
    purity_verdicts = []
    for comp in COMPONENTS:
        pure_vals = [s[comp] for s in all_segments if s["label"] == "pure"]
        impure_vals = [s[comp] for s in all_segments if s["label"] == "impure"]
        auc = safe_auc(pure_vals, impure_vals)  # positive class = impure (contains a missed real boundary)
        purity_verdicts.append({
            "component": comp, "auc_impure_positive": auc,
            "separation": round(abs(auc - 0.5), 4) if auc is not None else None,
            "pure_dist": dist_summary(pure_vals), "impure_dist": dist_summary(impure_vals),
            "n_pure": len(pure_vals), "n_impure": len(impure_vals),
        })
    print("\n--- STEP 3 (secondary): segment purity check (own cost, pure vs impure segment) ---", file=sys.stderr)
    for v in purity_verdicts:
        print(f"  {v['component']:<35} AUC={v['auc_impure_positive']} sep={v['separation']} "
              f"n_pure={v['n_pure']} n_impure={v['n_impure']}", file=sys.stderr)

    validated_components = [
        v["component"] for v in component_verdicts
        if v["separation"] is not None and v["separation"] >= SEP_THRESHOLD
        and v["session_robustness"] is not None
        and v["session_robustness"]["agreement_rate"] is not None
        and v["session_robustness"]["agreement_rate"] >= AGREEMENT_THRESHOLD
        and v["session_robustness"]["n_sessions_eligible"] >= MIN_ELIGIBLE_SESSIONS
    ]
    print(f"\nValidated components (Step 2 decision, from Step 3 evidence): {validated_components}", file=sys.stderr)

    out = {
        "n_sessions": len(session_ids),
        "population": {"n_candidates_total": n_candidates_total, "n_rule1_filtered": n_rule1_filtered_total,
                        "n_c_prime": len(candidate_rows), "n_TRUE": n_true, "n_FALSE": n_false},
        "global_component_scale": global_stats,
        "step3_component_forensics": component_verdicts,
        "step3_purity_check": purity_verdicts,
        "validated_components": validated_components,
    }

    if not validated_components:
        print("\nNo component cleared the discrimination/robustness bar. STOPPING -- "
              "the global-cost formulation is not supported by the evidence. Combined remains unchanged.",
              file=sys.stderr)
        out["decision_gate"] = {"hypothesis_supported": False, "reason": "no validated component"}
        write_output(args, out)
        return

    # ================ STEP 4: split-vs-merge counterfactual ================
    # Sign convention (defined explicitly, since C is an INCOHERENCE cost,
    # higher = worse): gap(i) = z(C(merged)) - [z(C(SL)) + z(C(SR))].
    # POSITIVE gap => merging concentrates more standardized incoherence
    # than the sum of the two separate fragments already had => evidence
    # FOR keeping the split (expect TRUE boundaries to score higher).
    # NEGATIVE/near-zero gap => merging doesn't add incoherence => evidence
    # FOR merging (expect FALSE candidates to score lower). This is the
    # opposite sign from the worked example in the brief's own Delta_i
    # formula, which read as internally inconsistent once "cost" is fixed
    # to mean "higher = more incoherent" -- resolved here explicitly rather
    # than silently guessed at.
    for r in candidate_rows:
        gap = 0.0
        any_component = False
        for comp in validated_components:
            zm, zl, zr = z(r[f"merged_{comp}"], comp), z(r[f"sl_{comp}"], comp), z(r[f"sr_{comp}"], comp)
            if zm is None or zl is None or zr is None:
                continue
            gap += zm - (zl + zr)
            any_component = True
        r["gap"] = gap if any_component else None

    gap_false = [r["gap"] for r in candidate_rows if r["label"] == "FALSE"]
    gap_true = [r["gap"] for r in candidate_rows if r["label"] == "TRUE"]
    gap_auc = safe_auc(gap_false, gap_true)
    gap_sep = round(abs(gap_auc - 0.5), 4) if gap_auc is not None else None
    gap_robustness = session_direction_consistency(candidate_rows, "gap", "TRUE")
    print(f"\n--- STEP 4: composite split-vs-merge gap (components: {validated_components}) ---", file=sys.stderr)
    print(f"  AUC(TRUE positive)={gap_auc} sep={gap_sep} robustness={gap_robustness}", file=sys.stderr)
    print(f"  FALSE dist: {dist_summary(gap_false)}", file=sys.stderr)
    print(f"  TRUE  dist: {dist_summary(gap_true)}", file=sys.stderr)

    out["step4_counterfactual_gap"] = {
        "sign_convention": "gap = z(C(merged)) - [z(C(SL)) + z(C(SR))]; positive => evidence for splitting (TRUE); "
                            "explicit deliberate divergence from the brief's own worked sign example -- see report",
        "auc_TRUE_positive": gap_auc, "separation": gap_sep, "session_robustness": gap_robustness,
        "false_dist": dist_summary(gap_false), "true_dist": dist_summary(gap_true),
    }

    # ================ STEP 5: lambda / threshold sweep ================
    gap_values = [r["gap"] for r in candidate_rows if r["gap"] is not None]
    is_true_for_gap = [r["label"] == "TRUE" for r in candidate_rows if r["gap"] is not None]
    grid = build_threshold_grid(np.array(gap_values))
    sweep = []
    for tau in grid:
        tp = sum(1 for g, t in zip(gap_values, is_true_for_gap) if g >= tau and t)
        fp = sum(1 for g, t in zip(gap_values, is_true_for_gap) if g >= tau and not t)
        fn = sum(1 for g, t in zip(gap_values, is_true_for_gap) if g < tau and t)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        sweep.append({"lambda": tau, "precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)})

    eligible = [r for r in sweep if r["recall"] >= RECALL_FLOOR]
    best_gap_row = max(eligible, key=lambda r: r["f1"]) if eligible else max(sweep, key=lambda r: r["f1"])
    print(f"\n--- STEP 5: lambda sweep (max F1 s.t. recall>={RECALL_FLOOR}, {len(grid)} grid points) ---", file=sys.stderr)
    print(f"  Selected lambda={best_gap_row['lambda']:.4f}  P={best_gap_row['precision']} R={best_gap_row['recall']} F1={best_gap_row['f1']}", file=sys.stderr)

    # Fair same-population reference baseline: Rule 4's own existing
    # feature (event_type_jaccard, N=10), best-F1-subject-to-recall-floor
    # on this exact C' population.
    jaccard_values = [r["event_type_jaccard_n10"] for r in candidate_rows if r["event_type_jaccard_n10"] is not None]
    is_true_for_jac = [r["label"] == "TRUE" for r in candidate_rows if r["event_type_jaccard_n10"] is not None]
    jac_grid = build_threshold_grid(np.array(jaccard_values))
    jac_sweep = []
    for tau in jac_grid:
        # Rule 4's own decision direction: LOW jaccard -> keep (predict TRUE); jaccard >= tau -> demote (predict FALSE)
        tp = sum(1 for jv, t in zip(jaccard_values, is_true_for_jac) if jv < tau and t)
        fp = sum(1 for jv, t in zip(jaccard_values, is_true_for_jac) if jv < tau and not t)
        fn = sum(1 for jv, t in zip(jaccard_values, is_true_for_jac) if jv >= tau and t)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        jac_sweep.append({"tau": tau, "precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)})
    jac_eligible = [r for r in jac_sweep if r["recall"] >= RECALL_FLOOR]
    best_jac_row = max(jac_eligible, key=lambda r: r["f1"]) if jac_eligible else max(jac_sweep, key=lambda r: r["f1"])
    print(f"  Reference baseline (event_type_jaccard_n10 on same C' population): "
          f"tau={best_jac_row['tau']:.4f} P={best_jac_row['precision']} R={best_jac_row['recall']} F1={best_jac_row['f1']}", file=sys.stderr)

    out["step5_lambda_sweep"] = {
        "grid_size": len(grid), "sweep": sweep, "selected": best_gap_row,
        "reference_baseline_event_type_jaccard_n10": {"grid_size": len(jac_grid), "selected": best_jac_row},
    }

    # ================ Decision gate before Step 6/7 ================
    gate = {
        "condition_A_at_least_one_component_validated": len(validated_components) > 0,
        "condition_B_composite_gap_discriminative": gap_sep is not None and gap_sep >= SEP_THRESHOLD,
        "condition_C_composite_gap_session_robust": (
            gap_robustness is not None and gap_robustness["agreement_rate"] is not None
            and gap_robustness["agreement_rate"] >= AGREEMENT_THRESHOLD
            and gap_robustness["n_sessions_eligible"] >= MIN_ELIGIBLE_SESSIONS
        ),
        "condition_D_gap_classifier_competitive_with_existing_baseline": {
            "pass": best_gap_row["f1"] >= best_jac_row["f1"],
            "gap_f1": best_gap_row["f1"], "existing_jaccard_baseline_f1": best_jac_row["f1"],
        },
    }
    hypothesis_supported = all([
        gate["condition_A_at_least_one_component_validated"],
        gate["condition_B_composite_gap_discriminative"],
        gate["condition_C_composite_gap_session_robust"],
        gate["condition_D_gap_classifier_competitive_with_existing_baseline"]["pass"],
    ])
    gate["hypothesis_supported"] = hypothesis_supported
    print("\n--- Decision gate (Steps 3-5 evidence) ---", file=sys.stderr)
    print(json.dumps(gate, indent=2), file=sys.stderr)
    out["decision_gate"] = gate

    if not hypothesis_supported:
        print("\nHypothesis NOT SUPPORTED -- stopping before Step 6 (DP prototype). "
              "Combined remains the locked architecture.", file=sys.stderr)
        write_output(args, out)
        return

    # ================ STEP 6/7: DP prototype + comparison vs Combined ================
    print(f"\nHypothesis SUPPORTED -- proceeding to Step 6 (DP prototype, lambda={best_gap_row['lambda']:.4f}).", file=sys.stderr)
    dp_result = run_dp_and_compare(per_session, session_ids, loso, validated_components, global_stats, best_gap_row["lambda"])
    out["step6_7_dp_prototype"] = dp_result

    write_output(args, out)


def run_dp_and_compare(per_session, session_ids, loso, validated_components, global_stats, lam):
    """Step 6: exact global optimum via dynamic programming, restricted to
    boundaries in the candidate set C' only (never invents a boundary
    outside V1 UNION V2, consistent with every other rule in this
    project). Step 7: compare against the locked Combined architecture on
    the exact same evaluation used throughout Day 2."""
    from procmine.segmentation.protected_boundary import STRATEGY_COMBINED, apply_protection
    from procmine.segmentation.reconstruction import (
        RULE_4_CONTINUITY, apply_design2_rules, cluster_size_per_transition, compute_rule2_demotions,
    )

    def z(value, comp):
        if value is None:
            return None
        std = global_stats[comp]["std"]
        return (value - global_stats[comp]["mean"]) / std if std > 0 else 0.0

    def composite_cost(canonical, feats, start, end):
        cost = compute_segment_cost(canonical[start:end + 1], internal_feature_slice(feats, start, end))
        total, any_component = 0.0, False
        for comp in validated_components:
            zc = z(getattr(cost, comp), comp)
            if zc is None:
                continue
            total += zc
            any_component = True
        return total if any_component else 0.0

    dp_boundary_by_session = {}
    for sid in session_ids:
        d = per_session[sid]
        feats = d["feats"]
        canonical = d["canonical"]
        n_events = len(canonical)
        v1_pred = loso["v1_preds"][sid]
        v2_pred = loso["v2_preds"][sid]
        candidates = union_candidates(v1_pred.tolist(), v2_pred.tolist())
        duplicate_noise = [
            involves_duplicate_app_switch(f.event_i_id, f.event_next_id, d["duplicate_app_switch_ids"])
            for f in feats
        ]
        c_prime_indices = [
            i for i, (c, f, dn) in enumerate(zip(candidates, feats, duplicate_noise))
            if c and not (f.chunk_boundary or dn)
        ]
        positions = sorted(set(c_prime_indices + [n_events - 1]))

        dp = {-1: 0.0}
        back = {-1: None}
        for p in positions:
            best_cost, best_prev = None, None
            for prev in ([-1] + [q for q in positions if q < p]):
                seg_cost = composite_cost(canonical, feats, prev + 1, p)
                total = dp[prev] + seg_cost + lam
                if best_cost is None or total < best_cost:
                    best_cost, best_prev = total, prev
            dp[p] = best_cost
            back[p] = best_prev

        chosen_ends = set()
        cur = n_events - 1
        while cur is not None and cur != -1:
            chosen_ends.add(cur)
            cur = back[cur]
        # every chosen end EXCEPT the final session-end position is a real boundary
        boundary = [False] * len(feats)
        for i in c_prime_indices:
            boundary[i] = i in chosen_ends and i != n_events - 1
        dp_boundary_by_session[sid] = boundary

    dp_result = evaluate_boundary_set(per_session, session_ids, dp_boundary_by_session)

    # Reproduce the locked Combined baseline for a same-run, apples-to-apples comparison
    combined_by_session = {}
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
        event_type_jaccard = [None] * n
        after_window_duration_ms = [None] * n
        for i in candidate_indices:
            traj = extract_trajectory_features(canonical, i, TRAJECTORY_WINDOW_N)
            event_type_jaccard[i] = traj.event_type_jaccard
            after_window_duration_ms[i] = float(traj.after_window_duration_ms)
        design2 = apply_design2_rules(
            candidates=candidates, chunk_boundary=chunk_boundary, duplicate_noise=duplicate_noise,
            rule2_demote_indices=rule2_demote_indices, cluster_size=cluster_size,
            event_type_jaccard=event_type_jaccard, continuity_threshold=0.40,
        )
        flagged_by_both = [bool(v1_pred[i]) and bool(v2_pred[i]) for i in range(n)]
        combined = apply_protection(
            design2_final_boundary=design2.final_boundary, design2_rule_applied=design2.rule_applied,
            flagged_by_both=flagged_by_both, tempo_value=after_window_duration_ms,
            strategy=STRATEGY_COMBINED, tempo_threshold=4680.2613,
        )
        combined_by_session[sid] = combined.final_boundary
    combined_result = evaluate_boundary_set(per_session, session_ids, combined_by_session)

    cp, dpp = combined_result["pooled"], dp_result["pooled"]
    print(f"\nCombined:      R={cp['recall']:.4f} F1={cp['f1']:.4f} frag%={cp['pct_gt_executions_fragmented']:.2f} under={cp['under_segmentation_rate']:.4f} over={cp['over_segmentation_rate']:.4f}", file=sys.stderr)
    print(f"DP prototype:  R={dpp['recall']:.4f} F1={dpp['f1']:.4f} frag%={dpp['pct_gt_executions_fragmented']:.2f} under={dpp['under_segmentation_rate']:.4f} over={dpp['over_segmentation_rate']:.4f}", file=sys.stderr)

    n_sessions_improved = n_sessions_worsened = n_sessions_equal = 0
    for sid in session_ids:
        c = combined_result["per_session"][sid]["pct_fragmented"]
        p = dp_result["per_session"][sid]["pct_fragmented"]
        if p < c - 1e-9:
            n_sessions_improved += 1
        elif p > c + 1e-9:
            n_sessions_worsened += 1
        else:
            n_sessions_equal += 1

    return {
        "lambda_used": lam, "validated_components": validated_components,
        "global_comparison": {"Combined": cp, "DP_prototype": dpp},
        "per_session_fragmentation_change": {
            "n_sessions_improved": n_sessions_improved, "n_sessions_worsened": n_sessions_worsened,
            "n_sessions_equal": n_sessions_equal,
        },
    }


def write_output(args, out):
    out_path = args.out / f"global_segmentation_hypothesis_{args.dataset.name}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nWrote {out_path}", file=sys.stderr)
    print("Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
