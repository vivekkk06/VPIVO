#!/usr/bin/env python3
"""Day-2-closing follow-up: segment-level coherence forensics on the
LOCKED Combined architecture's remaining errors.

Question: after Design 2 + Strategy Combined protection (the locked
architecture), 79.05% of GT executions are still fragmented. Is that
remaining fragmentation caused by a class of false boundaries that a
*segment*-scoped coherence check (the real, variable-length left/right
fragment implied by the current final-boundary set) could catch, where
the existing *fixed*-N=10-event-window features (Rule 4's
`event_type_jaccard`, the protection layer's `after_window_duration_ms`)
cannot?

This script does NOT retune V1 (0.9078), V2 (0.8860), Rule 4 (0.40), or
the tempo protection threshold (4680.2613ms) -- all four are re-applied
exactly as locked. It does NOT modify `reconstruction.py` or
`protected_boundary.py`. It is a forensic investigation first: GT is
used only to define which of Combined's *already-kept* final boundaries
are correct (population T) vs. remaining false positives (population
F), and for post-hoc evaluation of a possible Experiment-7 ablation --
never as a reconstruction input. Dataset B is never touched.

Usage:
    python scripts/analyze_segment_coherence_forensics.py --dataset dataset_a --out reports/day2
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
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
from procmine.segmentation.model import feature_vector as v1_feature_vector
from procmine.segmentation.model import make_pipeline
from procmine.segmentation.protected_boundary import (
    RULE_4_PROTECTED,
    STRATEGY_COMBINED,
    apply_protection,
)
from procmine.segmentation.reconstruction import (
    RULE_3_CLUSTER_PROTECTION,
    RULE_4_CONTINUITY,
    apply_design2_rules,
    cluster_size_per_transition,
    compute_rule2_demotions,
    involves_duplicate_app_switch,
    return_pattern_evidence_for_transition,
    union_candidates,
)
from procmine.segmentation.rule4_forensics import classify_candidate_source
from procmine.segmentation.segment_coherence import (
    compute_segment_coherence_evidence,
    segment_index_bounds,
)
from procmine.segmentation.signals import app_switch_payload_key, deduplicate_consecutive, extract_boundaries
from procmine.segmentation.threshold_analysis import build_threshold_grid
from procmine.validation import ValidationReport

V1_THRESHOLD = 0.9078
V2_BOUNDARY_SCORE_THRESHOLD = 0.8860
TRAJECTORY_WINDOW_N = 10
SELECTED_RULE4_THRESHOLD = 0.40  # locked -- reused, not re-selected
SELECTED_TEMPO_THRESHOLD = 4680.2613  # locked -- reused, not re-selected
POSITIVE_CLASS = "F"  # remaining false boundary (over-segmentation) -- what a new rule would target


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


def rate_summary(bools):
    bools = [b for b in bools if b is not None]
    if not bools:
        return {"n": 0, "rate": None}
    return {"n": len(bools), "n_true": int(sum(bools)), "rate": round(sum(bools) / len(bools), 4)}


def safe_auc(t_values, f_values):
    """AUC with population F (remaining false boundary) as the positive
    class -- same convention as Stage 8.4's `safe_auc` (>0.5: higher
    values associate with F; <0.5: with T). None if undefined."""
    t_values = [v for v in t_values if v is not None]
    f_values = [v for v in f_values if v is not None]
    if not t_values or not f_values:
        return None
    y = [0] * len(t_values) + [1] * len(f_values)
    scores = [float(v) for v in t_values] + [float(v) for v in f_values]
    if len(set(scores)) == 1:
        return None
    try:
        return round(float(roc_auc_score(y, scores)), 4)
    except ValueError:
        return None


def session_direction_consistency(sig_name, pop_t, pop_f):
    t_by_session = defaultdict(list)
    f_by_session = defaultdict(list)
    for r in pop_t:
        if r[sig_name] is not None:
            t_by_session[r["session_id"]].append(float(r[sig_name]))
    for r in pop_f:
        if r[sig_name] is not None:
            f_by_session[r["session_id"]].append(float(r[sig_name]))
    pooled_mean_t = statistics.fmean([v for vs in t_by_session.values() for v in vs]) if t_by_session else None
    pooled_mean_f = statistics.fmean([v for vs in f_by_session.values() for v in vs]) if f_by_session else None
    if pooled_mean_t is None or pooled_mean_f is None:
        return None
    pooled_direction = pooled_mean_f > pooled_mean_t
    n_agree = n_disagree = n_eligible = 0
    for sid in set(t_by_session) & set(f_by_session):
        n_eligible += 1
        session_mean_t = statistics.fmean(t_by_session[sid])
        session_mean_f = statistics.fmean(f_by_session[sid])
        if (session_mean_f > session_mean_t) == pooled_direction:
            n_agree += 1
        else:
            n_disagree += 1
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

    print("Running V1/V2 LOSO...", file=sys.stderr)
    loso = run_loso(per_session, session_ids)
    print("LOSO complete.", file=sys.stderr)

    # === Reproduce the LOCKED pipeline exactly: candidates -> Design 2 -> ===
    # === Strategy Combined protection. No threshold here is re-selected.  ===
    combined_by_session = {}
    design2_by_session = {}
    evidence_by_session = {}
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
        combined = apply_protection(
            design2_final_boundary=design2.final_boundary, design2_rule_applied=design2.rule_applied,
            flagged_by_both=flagged_by_both, tempo_value=after_window_duration_ms,
            strategy=STRATEGY_COMBINED, tempo_threshold=SELECTED_TEMPO_THRESHOLD,
        )
        combined_by_session[sid] = combined
        evidence_by_session[sid] = {
            "candidates": candidates, "flagged_by_both": flagged_by_both,
            "event_type_jaccard": event_type_jaccard, "after_window_duration_ms": after_window_duration_ms,
            "v1_pred": v1_pred, "v2_pred": v2_pred,
        }

    # === Reproducibility cross-check against the locked architecture JSON ===
    combined_result = evaluate_boundary_set(per_session, session_ids, {sid: combined_by_session[sid].final_boundary for sid in session_ids})
    p = combined_result["pooled"]
    print(f"\nReproduced Strategy_Combined: R={p['recall']:.4f} F1={p['f1']:.4f} "
          f"frag%={p['pct_gt_executions_fragmented']:.2f} under={p['under_segmentation_rate']:.4f} "
          f"over={p['over_segmentation_rate']:.4f} TP={p['tp']} FN={p['fn']} FP={p['fp']}", file=sys.stderr)
    print("Locked architecture JSON reported: R=0.6355 F1=0.3440 frag%=79.05 under=0.1412 "
          "over=1.6033 TP=1062 FN=609 FP=3441 -- cross-check.", file=sys.stderr)

    # === Build populations F (remaining false boundary) and T (correctly ===
    # === kept boundary) among Combined's final_boundary=True transitions. ===
    records = []
    for sid in session_ids:
        d = per_session[sid]
        canonical = d["canonical"]
        combined = combined_by_session[sid]
        ev = evidence_by_session[sid]
        n = len(d["feats"])
        seg_bounds = segment_index_bounds(len(canonical), combined.final_boundary)

        for i in range(n):
            if not combined.final_boundary[i]:
                continue
            is_true = d["is_boundary_labels"][i].is_boundary
            population = POSITIVE_CLASS if not is_true else "T"

            sc = compute_segment_coherence_evidence(canonical, combined.final_boundary, i, seg_bounds)
            rp = return_pattern_evidence_for_transition(canonical, i, TRAJECTORY_WINDOW_N)
            f = d["feats"][i]

            records.append({
                "population": population, "session_id": sid, "index": i,
                "rule_applied": combined.rule_applied[i],
                "candidate_source": classify_candidate_source(bool(ev["v1_pred"][i]), bool(ev["v2_pred"][i])),
                # --- segment-level (new, variable-length neighbor fragment) ---
                "segment_event_type_jaccard": sc.segment_event_type_jaccard,
                "segment_interaction_category_jaccard": sc.segment_interaction_category_jaccard,
                "segment_application_jaccard": sc.segment_application_jaccard,
                "segment_browser_domain_jaccard_host_only": sc.segment_browser_domain_jaccard_host_only,
                "rate_continuity_ratio": sc.rate_continuity_ratio,
                "min_segment_n_events": sc.min_segment_n_events,
                "min_segment_duration_ms": sc.min_segment_duration_ms,
                "left_n_events": sc.left_n_events, "right_n_events": sc.right_n_events,
                # --- existing fixed-N=10 baselines, for direct comparison ---
                "event_type_jaccard_n10": ev["event_type_jaccard"][i],
                "after_window_duration_ms_n10": ev["after_window_duration_ms"][i],
                "flagged_by_both_models": ev["flagged_by_both"][i],
                # --- existing Stage-5 baseline signals, reference only ---
                "delta_t_ms": f.delta_t_ms, "density_before": f.density_before, "density_after": f.density_after,
                "return_pattern_role": rp.role,
            })

    pop_t = [r for r in records if r["population"] == "T"]
    pop_f = [r for r in records if r["population"] == POSITIVE_CLASS]
    print(f"\nPopulation T (correctly kept boundaries): {len(pop_t)}", file=sys.stderr)
    print(f"Population F (remaining false boundaries, still kept): {len(pop_f)}", file=sys.stderr)

    # ================ rule_applied stratification (context) ================
    def rule_breakdown(pop):
        c = Counter(r["rule_applied"] for r in pop)
        n = len(pop)
        return {k: {"n": v, "rate": round(v / n, 4)} for k, v in c.items()} if n else {}
    rule_strat = {"T": rule_breakdown(pop_t), "F": rule_breakdown(pop_f)}

    # ================ candidate-source stratification (context) ================
    def source_breakdown(pop):
        c = Counter(r["candidate_source"] for r in pop)
        n = len(pop)
        return {k: {"n": v, "rate": round(v / n, 4)} for k, v in c.items()} if n else {}
    source_strat = {"T": source_breakdown(pop_t), "F": source_breakdown(pop_f)}

    # ================ Experiment 4: discrimination test ================
    numeric_signals = [
        "segment_event_type_jaccard", "segment_interaction_category_jaccard",
        "segment_application_jaccard", "segment_browser_domain_jaccard_host_only",
        "rate_continuity_ratio", "min_segment_n_events", "min_segment_duration_ms",
        "left_n_events", "right_n_events",
        "event_type_jaccard_n10", "after_window_duration_ms_n10",
        "delta_t_ms", "density_before", "density_after",
    ]
    boolean_signals = ["flagged_by_both_models"]

    distributions = {"numeric": {}, "boolean": {}}
    for sig in numeric_signals:
        t_vals = [r[sig] for r in pop_t]
        f_vals = [r[sig] for r in pop_f]
        distributions["numeric"][sig] = {
            "T": dist_summary(t_vals), "F": dist_summary(f_vals),
            "auc_F_positive": safe_auc(t_vals, f_vals),
        }
    for sig in boolean_signals:
        t_vals = [r[sig] for r in pop_t]
        f_vals = [r[sig] for r in pop_f]
        distributions["boolean"][sig] = {
            "T": rate_summary(t_vals), "F": rate_summary(f_vals),
            "auc_F_positive": safe_auc([1 if v else 0 for v in t_vals if v is not None],
                                        [1 if v else 0 for v in f_vals if v is not None]),
        }

    return_pattern_involvement = {
        "T": rate_summary([r["return_pattern_role"] is not None for r in pop_t]),
        "F": rate_summary([r["return_pattern_role"] is not None for r in pop_f]),
    }

    # Rank by |AUC-0.5|, same "separates" convention Stage 8.4 used
    def verdict(name, auc):
        sep = abs(auc - 0.5) if auc is not None else None
        return {"signal": name, "auc_F_positive": auc, "separation_from_uninformative": round(sep, 4) if sep is not None else None}

    signal_verdicts = [verdict(s, distributions["numeric"][s]["auc_F_positive"]) for s in numeric_signals]
    signal_verdicts += [verdict(s, distributions["boolean"][s]["auc_F_positive"]) for s in boolean_signals]
    signal_verdicts.sort(key=lambda v: -(v["separation_from_uninformative"] or 0))

    print("\n--- Discrimination test (T vs F, AUC with F positive) ---", file=sys.stderr)
    for v in signal_verdicts:
        print(f"  {v['signal']:<40} AUC={v['auc_F_positive']}  sep={v['separation_from_uninformative']}", file=sys.stderr)

    # === Session robustness for the top candidates ===
    top_signal_names = [v["signal"] for v in signal_verdicts[:6]]
    robustness = {}
    for sig in top_signal_names:
        robustness[sig] = session_direction_consistency(sig, pop_t, pop_f)
    print("\n--- Session-direction robustness (top 6 signals) ---", file=sys.stderr)
    print(json.dumps(robustness, indent=2), file=sys.stderr)

    # ================ Experiment 6: decision gate ================
    SEP_THRESHOLD = 0.10          # same descriptive bar Stage 8.4 used
    AGREEMENT_THRESHOLD = 0.75    # clearly separates Stage 8.4's STRONG (88.9%) from its REJECTED (41.3%) case
    MIN_ELIGIBLE_SESSIONS = 15    # "not dominated by one or two sessions" -- roughly a quarter of 63

    best = signal_verdicts[0]
    best_name = best["signal"]
    best_robustness = robustness.get(best_name)
    best_sep_ok = best["separation_from_uninformative"] is not None and best["separation_from_uninformative"] >= SEP_THRESHOLD
    best_robust_ok = (
        best_robustness is not None
        and best_robustness["agreement_rate"] is not None
        and best_robustness["agreement_rate"] >= AGREEMENT_THRESHOLD
        and best_robustness["n_sessions_eligible"] >= MIN_ELIGIBLE_SESSIONS
    )
    # non-redundancy: does the best NEW (segment-scoped) signal add anything
    # beyond the existing N=10 baselines already used by Rule 4 / protection?
    baseline_names = {"event_type_jaccard_n10", "after_window_duration_ms_n10", "flagged_by_both_models"}
    is_new_signal_family = best_name not in baseline_names
    baseline_best_sep = max(
        (v["separation_from_uninformative"] or 0) for v in signal_verdicts if v["signal"] in baseline_names
    )
    meaningfully_better_than_baseline = (best["separation_from_uninformative"] or 0) >= baseline_best_sep + 0.03

    hypothesis_supported = (
        best_sep_ok and best_robust_ok and is_new_signal_family and meaningfully_better_than_baseline
    )

    decision_gate = {
        "best_signal": best_name,
        "best_signal_auc": best["auc_F_positive"],
        "best_signal_separation": best["separation_from_uninformative"],
        "best_signal_session_robustness": best_robustness,
        "condition_1_discriminative_ge_0.10_separation": best_sep_ok,
        "condition_2_session_robust_ge_0.75_agreement_and_ge_15_eligible": best_robust_ok,
        "condition_3_is_new_signal_family_not_existing_n10_baseline": is_new_signal_family,
        "condition_4_meaningfully_better_than_best_existing_n10_baseline": {
            "pass": meaningfully_better_than_baseline,
            "best_existing_n10_baseline_separation": round(baseline_best_sep, 4),
            "best_new_signal_separation": best["separation_from_uninformative"],
        },
        "hypothesis_supported": hypothesis_supported,
    }
    print("\n--- Decision gate ---", file=sys.stderr)
    print(json.dumps(decision_gate, indent=2), file=sys.stderr)

    out = {
        "n_sessions": len(session_ids),
        "reproduced_combined_baseline": combined_result["pooled"],
        "locked_architecture_reference": {
            "recall": 0.6355, "f1": 0.3440, "pct_gt_executions_fragmented": 79.05,
            "under_segmentation_rate": 0.1412, "over_segmentation_rate": 1.6033,
            "tp": 1062, "fn": 609, "fp": 3441,
        },
        "population_sizes": {"n_T": len(pop_t), "n_F": len(pop_f)},
        "rule_applied_stratification": rule_strat,
        "candidate_source_stratification": source_strat,
        "return_pattern_involvement": return_pattern_involvement,
        "distributions": distributions,
        "signal_verdicts_ranked": signal_verdicts,
        "session_robustness_top6": robustness,
        "decision_gate": decision_gate,
    }

    ablation = None
    if hypothesis_supported:
        print(f"\nHypothesis SUPPORTED by {best_name} -- proceeding to Experiment 7 (single controlled ablation).", file=sys.stderr)
        ablation = run_ablation(
            per_session, session_ids, combined_by_session, evidence_by_session, records, best_name,
        )
        out["ablation"] = ablation
    else:
        print("\nHypothesis NOT SUPPORTED -- stopping. Combined remains the locked architecture.", file=sys.stderr)

    out_path = args.out / f"segment_coherence_forensics_{args.dataset.name}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nWrote {out_path}", file=sys.stderr)
    print("Done.", file=sys.stderr)


def run_ablation(per_session, session_ids, combined_by_session, evidence_by_session, records, signal_name):
    """Experiment 7 -- only reached if the decision gate passed. ONE new
    deterministic, demote-only rule: among Combined's final_boundary=True
    transitions, demote if `signal_name` (computed once per transition,
    already available in `records`) crosses a single GLOBAL threshold
    selected via the same pooled-OOF grid method Stage 7/8.3/8.5 used.
    Never adds a boundary; never touches V1/V2/Design2/the tempo or
    agreement protection logic; no per-session tuning; no GT as an input
    to the rule itself (GT is used here only to select the threshold and
    to evaluate the result, exactly as for every prior threshold in this
    project)."""
    by_key = {(r["session_id"], r["index"]): r for r in records}
    values = [r[signal_name] for r in records if r[signal_name] is not None]
    is_f = [r["population"] == POSITIVE_CLASS for r in records if r[signal_name] is not None]
    grid = build_threshold_grid(np.array(values))

    sweep_rows = []
    for tau in grid:
        demoted_true = sum(1 for v, f in zip(values, is_f) if v >= tau and not f)  # T wrongly demoted
        demoted_false = sum(1 for v, f in zip(values, is_f) if v >= tau and f)     # F correctly demoted
        n_demoted = demoted_true + demoted_false
        precision = demoted_false / n_demoted if n_demoted else 0.0  # of demotions, fraction correct
        recall = demoted_false / sum(is_f) if sum(is_f) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        sweep_rows.append({"tau": tau, "n_demoted": n_demoted, "n_T_wrongly_demoted": demoted_true,
                            "n_F_correctly_demoted": demoted_false, "precision": round(precision, 4),
                            "recall": round(recall, 4), "f1": round(f1, 4)})
    best_row = max(sweep_rows, key=lambda r: r["f1"])
    tau = best_row["tau"]
    print(f"\nAblation rule: demote if {signal_name} >= {tau:.4f} "
          f"(selected via max-F1 on pooled OOF evidence over the T/F population, "
          f"precision={best_row['precision']:.3f} recall={best_row['recall']:.3f})", file=sys.stderr)

    def build_ablation_boundary(sid):
        combined = combined_by_session[sid]
        n = len(combined.final_boundary)
        boundary = list(combined.final_boundary)
        for i in range(n):
            if not boundary[i]:
                continue
            r = by_key.get((sid, i))
            if r is None or r[signal_name] is None:
                continue
            if r[signal_name] >= tau:
                boundary[i] = False
        return boundary

    ablation_boundary = {sid: build_ablation_boundary(sid) for sid in session_ids}
    ablation_result = evaluate_boundary_set(per_session, session_ids, ablation_boundary)
    combined_result = evaluate_boundary_set(per_session, session_ids, {sid: combined_by_session[sid].final_boundary for sid in session_ids})

    ap, cp = ablation_result["pooled"], combined_result["pooled"]
    print(f"Combined:        R={cp['recall']:.4f} F1={cp['f1']:.4f} frag%={cp['pct_gt_executions_fragmented']:.2f} under={cp['under_segmentation_rate']:.4f}", file=sys.stderr)
    print(f"Combined+Rule5:  R={ap['recall']:.4f} F1={ap['f1']:.4f} frag%={ap['pct_gt_executions_fragmented']:.2f} under={ap['under_segmentation_rate']:.4f}", file=sys.stderr)

    n_sessions_improved = n_sessions_worsened = n_sessions_equal = 0
    for sid in session_ids:
        c = combined_result["per_session"][sid]["pct_fragmented"]
        a = ablation_result["per_session"][sid]["pct_fragmented"]
        if a < c - 1e-9:
            n_sessions_improved += 1
        elif a > c + 1e-9:
            n_sessions_worsened += 1
        else:
            n_sessions_equal += 1

    # sensitivity: nearest grid neighbors around tau
    sorted_grid = sorted(grid)
    idx = sorted_grid.index(tau)
    neighbor_idxs = range(max(0, idx - 4), min(len(sorted_grid), idx + 5))
    sensitivity = [r for r in sweep_rows if sorted_grid.index(r["tau"]) in neighbor_idxs]

    return {
        "rule_name": "rule5_segment_coherence", "signal_used": signal_name,
        "threshold_selection_method": "max F1 on pooled, global, out-of-fold T/F evidence -- Stage 7's grid method, not nested/cross-fitted, not per-session",
        "selected_threshold": tau, "selected_row": best_row,
        "global_comparison": {"Combined": cp, "Combined_plus_Rule5": ap},
        "per_session_fragmentation_change": {
            "n_sessions_improved": n_sessions_improved, "n_sessions_worsened": n_sessions_worsened,
            "n_sessions_equal": n_sessions_equal,
        },
        "sensitivity_neighbors": sensitivity,
    }


if __name__ == "__main__":
    main()
