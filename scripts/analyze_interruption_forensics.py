#!/usr/bin/env python3
"""Stage 8: forensic characterization of interruption/return patterns in
Dataset A GT executions — evidence-gathering only, ahead of designing a
neighborhood-aware reconstruction layer.

Does NOT train a new model, does NOT tune a new threshold, does NOT
modify V1/V2 methodology, does NOT touch Dataset B, does NOT implement
any reconstruction algorithm (clustering/DP/HMM/Viterbi/graph). V1's and
V2's existing LOSO procedures and thresholds (0.9078, 0.8860) are re-run
exactly as in Stages 2/6/7 solely to know, per transition, whether each
model would flag it — that classification is an input to this forensic
analysis, not something re-derived or re-tuned here.

GT (process_code, case_id, execution spans) is used throughout for
forensic labeling — grouping transitions by execution, computing which
GT category a transition belongs to (Stage 4's SAME_EXECUTION /
EXIT_TO_DIFFERENT_EXEC / EXIT_TO_NOISE_BOUNDARY scheme, reused unchanged)
— and NEVER as a model feature; the only feature vectors built here are
V1's and V2's existing, already-approved ones, unchanged.

Usage:
    python scripts/analyze_interruption_forensics.py --dataset dataset_a --out reports/day2
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np

from procmine.loaders.events import load_session_events
from procmine.loaders.ground_truth import load_gt_manifest, parse_gt_manifest_executions
from procmine.paths import discover_dataset
from procmine.segmentation.canonical import to_canonical_stream
from procmine.segmentation.context_features import extract_trajectory_features
from procmine.segmentation.continuity_labels import (
    EXIT_TO_DIFFERENT_EXEC,
    EXIT_TO_NOISE_BOUNDARY,
    SAME_EXECUTION,
    label_continuity,
)
from procmine.segmentation.continuity_model import continuity_feature_vector
from procmine.segmentation.features import extract_transition_features, label_transitions
from procmine.segmentation.interruption_forensics import (
    build_execution_profile,
    detect_return_patterns,
    internal_transition_indices,
)
from procmine.segmentation.model import feature_vector as v1_feature_vector
from procmine.segmentation.model import make_pipeline
from procmine.segmentation.signals import extract_boundaries
from procmine.validation import ValidationReport

V1_THRESHOLD = 0.9078  # Stage 6 -- reused exactly, not re-derived
V2_BOUNDARY_SCORE_THRESHOLD = 0.8860  # Stage 6 -- reused exactly, not re-derived
TRAJECTORY_WINDOW_N = 10  # Stage 5's evidence-backed window size -- reused, not re-chosen
TRUE_BOUNDARY_CATEGORIES = {EXIT_TO_DIFFERENT_EXEC, EXIT_TO_NOISE_BOUNDARY}


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
        "p10": round(percentile(values, 0.10), 4),
        "p25": round(percentile(values, 0.25), 4),
        "p75": round(percentile(values, 0.75), 4),
        "p90": round(percentile(values, 0.90), 4),
        "p95": round(percentile(values, 0.95), 4),
        "p99": round(percentile(values, 0.99), 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
    }


def rate_summary(bools: list[bool]) -> dict:
    if not bools:
        return {"n": 0, "rate": None}
    return {"n": len(bools), "n_true": int(sum(bools)), "rate": round(sum(bools) / len(bools), 4)}


@dataclass
class TransitionRecord:
    """One row per labeled (SAME_EXECUTION / EXIT_TO_DIFFERENT_EXEC /
    EXIT_TO_NOISE_BOUNDARY) transition, enriched with both models'
    predictions and N=10 trajectory evidence. Built once, sliced many
    ways below, so every downstream count comes from one consistent
    computation rather than several independently-written passes."""

    session_id: str
    case_id: str | None
    category: str
    delta_t_ms: int
    application_changed: bool
    window_title_changed: bool
    browser_domain_changed: bool
    interaction_category_changed: bool
    density_before: int
    density_after: int
    v1_predicted_boundary: bool
    v2_predicted_boundary: bool
    is_argmax_gap_for_execution: bool
    event_type_jaccard: float | None
    interaction_category_jaccard: float | None
    application_jaccard: float | None
    after_window_duration_ms: int


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    sessions = discover_dataset(args.dataset)
    per_session: dict[str, dict] = {}
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
        is_boundary_labels = label_transitions(
            feats, [(b.timestamp_ms, b.is_resume) for b in boundaries]
        )
        clabels = label_continuity(session.session_id, feats, boundaries, executions_all)
        executions_closed = [e for e in executions_all if e.end_ts is not None]

        X_v1 = np.array([v1_feature_vector(f) for f in feats])
        X_v2 = np.array([continuity_feature_vector(canonical, i, f) for i, f in enumerate(feats)])

        per_session[session.session_id] = {
            "canonical": canonical, "feats": feats,
            "is_boundary_labels": is_boundary_labels, "clabels": clabels,
            "executions": executions_closed,
            "X_v1": X_v1, "X_v2": X_v2,
        }

    session_ids = sorted(per_session.keys())
    n_gt_executions_total = sum(len(d["executions"]) for d in per_session.values())
    n_transitions_total = sum(len(d["feats"]) for d in per_session.values())
    print(f"{len(session_ids)} sessions, {n_gt_executions_total} GT executions, "
          f"{n_transitions_total} transitions loaded", file=sys.stderr)

    # === V1 LOSO (reused procedure/threshold, Stage 2/6) ===
    y_v1 = np.array([1 if lt.is_boundary else 0
                      for sid in session_ids for lt in per_session[sid]["is_boundary_labels"]])
    groups_v1 = np.array([sid for sid in session_ids for _ in per_session[sid]["is_boundary_labels"]])
    X_v1_all = np.vstack([per_session[sid]["X_v1"] for sid in session_ids])
    print("Running V1 LOSO...", file=sys.stderr)
    v1_pred_by_session: dict[str, np.ndarray] = {}
    for held_out in session_ids:
        mask = groups_v1 != held_out
        pipeline = make_pipeline()
        pipeline.fit(X_v1_all[mask], y_v1[mask])
        probs = pipeline.predict_proba(per_session[held_out]["X_v1"])[:, 1]
        v1_pred_by_session[held_out] = probs >= V1_THRESHOLD

    # === V2 LOSO (reused procedure/threshold, Stage 6/7), trained on the ===
    # === labeled subset, applied to every transition in the session      ===
    X_v2_train, y_v2_train, groups_v2_train = [], [], []
    for sid in session_ids:
        d = per_session[sid]
        for x, cl in zip(d["X_v2"], d["clabels"]):
            if cl.excluded:
                continue
            X_v2_train.append(x); y_v2_train.append(cl.continuity_label); groups_v2_train.append(sid)
    X_v2_train = np.array(X_v2_train); y_v2_train = np.array(y_v2_train); groups_v2_train = np.array(groups_v2_train)
    print("Running V2 LOSO...", file=sys.stderr)
    v2_pred_by_session: dict[str, np.ndarray] = {}
    for held_out in session_ids:
        mask = groups_v2_train != held_out
        pipeline = make_pipeline()
        pipeline.fit(X_v2_train[mask], y_v2_train[mask])
        s1_probs = pipeline.predict_proba(per_session[held_out]["X_v2"])[:, 1]
        boundary_score = 1 - s1_probs
        v2_pred_by_session[held_out] = boundary_score >= V2_BOUNDARY_SCORE_THRESHOLD

    print("Both LOSO runs complete.", file=sys.stderr)

    # === Global SAME_EXECUTION gap percentiles: the data-driven "large gap" ===
    # === thresholds used throughout (never an arbitrary constant).         ===
    same_exec_gaps = [
        f.delta_t_ms
        for sid in session_ids
        for f, cl in zip(per_session[sid]["feats"], per_session[sid]["clabels"])
        if cl.category == SAME_EXECUTION
    ]
    p50 = percentile(same_exec_gaps, 0.50)
    p75 = percentile(same_exec_gaps, 0.75)
    p90 = percentile(same_exec_gaps, 0.90)
    p95 = percentile(same_exec_gaps, 0.95)
    p99 = percentile(same_exec_gaps, 0.99)
    print(f"SAME_EXECUTION gap percentiles (ms): p50={p50} p75={p75} p90={p90} p95={p95} p99={p99}",
          file=sys.stderr)

    # === Per-execution interruption profiles (item 2) ===
    profiles = []
    internal_idx_by_exec: dict[tuple[str, str], list[int]] = {}
    for sid in session_ids:
        d = per_session[sid]
        for execution in d["executions"]:
            profile = build_execution_profile(sid, execution, d["feats"], p90, p95, p99)
            profiles.append(profile)
            start_ms = int(execution.start_ts.timestamp() * 1000)
            end_ms = int(execution.end_ts.timestamp() * 1000)
            internal_idx_by_exec[(sid, execution.case_id)] = internal_transition_indices(
                d["feats"], start_ms, end_ms
            )

    # === Enriched per-transition records + trajectory features (item 6) ===
    # One pass, reused for items 1, 2 (resumption evidence), 3, 4, 6.
    records: list[TransitionRecord] = []
    for sid in session_ids:
        d = per_session[sid]
        feats = d["feats"]
        canonical = d["canonical"]
        clabels = d["clabels"]
        v1_preds = v1_pred_by_session[sid]
        v2_preds = v2_pred_by_session[sid]

        argmax_indices_this_session: set[int] = {
            p.argmax_gap_transition_index
            for p in profiles
            if p.session_id == sid and p.argmax_gap_transition_index is not None
        }

        # find each transition's containing case_id (only meaningful for
        # SAME_EXECUTION category; None otherwise) via the same internal-
        # index lookup already built above (avoids a second span-membership
        # implementation)
        case_id_for_index: dict[int, str] = {}
        for (s, cid), idxs in internal_idx_by_exec.items():
            if s != sid:
                continue
            for i in idxs:
                case_id_for_index[i] = cid

        for i, (f, cl) in enumerate(zip(feats, clabels)):
            if cl.category not in (SAME_EXECUTION, EXIT_TO_DIFFERENT_EXEC, EXIT_TO_NOISE_BOUNDARY):
                continue
            traj = extract_trajectory_features(canonical, i, TRAJECTORY_WINDOW_N)
            records.append(
                TransitionRecord(
                    session_id=sid,
                    case_id=case_id_for_index.get(i),
                    category=cl.category,
                    delta_t_ms=f.delta_t_ms,
                    application_changed=f.application_changed,
                    window_title_changed=f.window_title_changed,
                    browser_domain_changed=f.browser_domain_changed,
                    interaction_category_changed=f.interaction_category_changed,
                    density_before=f.density_before,
                    density_after=f.density_after,
                    v1_predicted_boundary=bool(v1_preds[i]),
                    v2_predicted_boundary=bool(v2_preds[i]),
                    is_argmax_gap_for_execution=(i in argmax_indices_this_session),
                    event_type_jaccard=traj.event_type_jaccard,
                    interaction_category_jaccard=traj.interaction_category_jaccard,
                    application_jaccard=traj.application_jaccard,
                    after_window_duration_ms=traj.after_window_duration_ms,
                )
            )

    print(f"{len(records)} enriched transition records built "
          f"(SAME_EXECUTION={sum(1 for r in records if r.category == SAME_EXECUTION)}, "
          f"true boundaries={sum(1 for r in records if r.category in TRUE_BOUNDARY_CATEGORIES)})",
          file=sys.stderr)

    same_exec_records = [r for r in records if r.category == SAME_EXECUTION]
    true_boundary_records = [r for r in records if r.category in TRUE_BOUNDARY_CATEGORIES]
    v1_false_internal = [r for r in same_exec_records if r.v1_predicted_boundary]
    v2_false_internal = [r for r in same_exec_records if r.v2_predicted_boundary]
    v1_ordinary_same_exec = [r for r in same_exec_records if not r.v1_predicted_boundary]
    v2_ordinary_same_exec = [r for r in same_exec_records if not r.v2_predicted_boundary]

    print(f"V1 false-internal-boundaries: {len(v1_false_internal)} / {len(same_exec_records)} "
          f"SAME_EXECUTION transitions", file=sys.stderr)
    print(f"V2 false-internal-boundaries: {len(v2_false_internal)} / {len(same_exec_records)} "
          f"SAME_EXECUTION transitions", file=sys.stderr)

    # ==========================================================================
    # ITEM 1: signal rates + combinations, within SAME_EXECUTION transitions
    # ==========================================================================
    def signal_vector(r: TransitionRecord) -> tuple[bool, bool, bool, bool, bool]:
        return (
            r.delta_t_ms >= p90,
            r.application_changed,
            r.window_title_changed,
            r.browser_domain_changed,
            r.interaction_category_changed,
        )

    signal_names = ["long_gap_ge_p90", "app_switch", "window_title_change",
                     "browser_domain_change", "interaction_category_change"]
    signal_matrix = [signal_vector(r) for r in same_exec_records]

    individual_rates = {
        name: rate_summary([row[j] for row in signal_matrix])
        for j, name in enumerate(signal_names)
    }
    pairwise_cooccurrence = {}
    for a in range(len(signal_names)):
        for b in range(a + 1, len(signal_names)):
            both = sum(1 for row in signal_matrix if row[a] and row[b])
            either = sum(1 for row in signal_matrix if row[a] or row[b])
            pairwise_cooccurrence[f"{signal_names[a]}+{signal_names[b]}"] = {
                "n_both": both,
                "rate_of_all_internal": round(both / len(signal_matrix), 4) if signal_matrix else None,
                "jaccard_of_the_two_signals": round(both / either, 4) if either else None,
            }
    n_signals_histogram = defaultdict(int)
    for row in signal_matrix:
        n_signals_histogram[sum(row)] += 1
    n_signals_histogram = {str(k): v for k, v in sorted(n_signals_histogram.items())}

    item1 = {
        "n_same_execution_transitions": len(same_exec_records),
        "large_gap_threshold_ms_p90": p90,
        "individual_signal_rates": individual_rates,
        "pairwise_cooccurrence": pairwise_cooccurrence,
        "n_signals_firing_simultaneously_histogram": n_signals_histogram,
    }

    # ==========================================================================
    # ITEM 2: per-execution interruption-pattern characterization
    # ==========================================================================
    max_gaps = [p.max_internal_gap_ms for p in profiles if p.max_internal_gap_ms is not None]
    n_gaps_p90 = [p.n_gaps_ge_p90 for p in profiles]
    n_app_switches = [p.n_app_switches for p in profiles]
    n_domain_changes = [p.n_browser_domain_changes for p in profiles]
    n_window_changes = [p.n_window_title_changes for p in profiles]
    n_category_changes = [p.n_interaction_category_changes for p in profiles]

    # "resumes after the interruption": at each execution's own largest
    # internal gap (when that gap reaches the dataset-wide p90 "large gap"
    # bar), does the N=10 trajectory evidence around it look like ordinary
    # same-execution continuity? Reference bar = the SAME_EXECUTION
    # population's own median trajectory-jaccard (data-driven).
    same_exec_event_type_jaccards = [r.event_type_jaccard for r in same_exec_records if r.event_type_jaccard is not None]
    same_exec_interaction_jaccards = [r.interaction_category_jaccard for r in same_exec_records if r.interaction_category_jaccard is not None]
    median_event_type_jaccard = statistics.median(same_exec_event_type_jaccards) if same_exec_event_type_jaccards else None
    median_interaction_jaccard = statistics.median(same_exec_interaction_jaccards) if same_exec_interaction_jaccards else None

    large_gap_records_at_argmax = [
        r for r in same_exec_records
        if r.is_argmax_gap_for_execution and r.delta_t_ms >= p90
    ]
    n_resuming_by_event_type = sum(
        1 for r in large_gap_records_at_argmax
        if r.event_type_jaccard is not None and median_event_type_jaccard is not None
        and r.event_type_jaccard >= median_event_type_jaccard
    )
    n_resuming_by_interaction_category = sum(
        1 for r in large_gap_records_at_argmax
        if r.interaction_category_jaccard is not None and median_interaction_jaccard is not None
        and r.interaction_category_jaccard >= median_interaction_jaccard
    )

    item2 = {
        "n_gt_executions": len(profiles),
        "n_executions_with_zero_internal_transitions": sum(1 for p in profiles if p.n_internal_transitions == 0),
        "max_internal_gap_ms_distribution": dist_summary(max_gaps),
        "n_gaps_ge_p90_per_execution_distribution": dist_summary(n_gaps_p90),
        "n_app_switches_per_execution_distribution": dist_summary(n_app_switches),
        "n_browser_domain_changes_per_execution_distribution": dist_summary(n_domain_changes),
        "n_window_title_changes_per_execution_distribution": dist_summary(n_window_changes),
        "n_interaction_category_changes_per_execution_distribution": dist_summary(n_category_changes),
        "resumption_evidence": {
            "n_executions_with_a_large_gap_ge_p90": len(large_gap_records_at_argmax),
            "reference_median_event_type_jaccard_same_execution_population": median_event_type_jaccard,
            "reference_median_interaction_category_jaccard_same_execution_population": median_interaction_jaccard,
            "n_at_or_above_median_event_type_jaccard": n_resuming_by_event_type,
            "pct_at_or_above_median_event_type_jaccard": (
                round(100 * n_resuming_by_event_type / len(large_gap_records_at_argmax), 1)
                if large_gap_records_at_argmax else None
            ),
            "n_at_or_above_median_interaction_category_jaccard": n_resuming_by_interaction_category,
            "pct_at_or_above_median_interaction_category_jaccard": (
                round(100 * n_resuming_by_interaction_category / len(large_gap_records_at_argmax), 1)
                if large_gap_records_at_argmax else None
            ),
            "density_after_at_max_gap_distribution": dist_summary(
                [p.density_after_at_max_gap for p in profiles if p.density_after_at_max_gap is not None]
            ),
        },
    }

    # ==========================================================================
    # ITEM 3: internal (SAME_EXECUTION) vs. true-boundary comparison
    # ==========================================================================
    def feature_comparison_row(attr: str, is_bool: bool) -> dict:
        same_vals = [getattr(r, attr) for r in same_exec_records]
        bound_vals = [getattr(r, attr) for r in true_boundary_records]
        if is_bool:
            return {"same_execution": rate_summary(same_vals), "true_boundary": rate_summary(bound_vals)}
        return {"same_execution": dist_summary(same_vals), "true_boundary": dist_summary(bound_vals)}

    item3 = {
        "n_same_execution": len(same_exec_records),
        "n_true_boundary": len(true_boundary_records),
        "note": "true_boundary = EXIT_TO_DIFFERENT_EXEC + EXIT_TO_NOISE_BOUNDARY "
                "(Stage 4's approved continuity-label categories, reused unchanged) "
                "-- a different, narrower cut than time_gap_analysis.md's 'interior "
                "vs. boundary-window' framing; both are valid, not to be conflated.",
        "delta_t_ms": feature_comparison_row("delta_t_ms", False),
        "density_before": feature_comparison_row("density_before", False),
        "density_after": feature_comparison_row("density_after", False),
        "application_changed": feature_comparison_row("application_changed", True),
        "window_title_changed": feature_comparison_row("window_title_changed", True),
        "browser_domain_changed": feature_comparison_row("browser_domain_changed", True),
        "interaction_category_changed": feature_comparison_row("interaction_category_changed", True),
        "event_type_jaccard_n10": {
            "same_execution": dist_summary([r.event_type_jaccard for r in same_exec_records if r.event_type_jaccard is not None]),
            "true_boundary": dist_summary([r.event_type_jaccard for r in true_boundary_records if r.event_type_jaccard is not None]),
        },
        "interaction_category_jaccard_n10": {
            "same_execution": dist_summary([r.interaction_category_jaccard for r in same_exec_records if r.interaction_category_jaccard is not None]),
            "true_boundary": dist_summary([r.interaction_category_jaccard for r in true_boundary_records if r.interaction_category_jaccard is not None]),
        },
    }

    # ==========================================================================
    # ITEM 4: false-internal-boundary characterization, per model (V1, V2)
    # ==========================================================================
    def cluster_sizes(flagged_case_transition_map: dict[tuple[str, str], list[bool]]) -> list[int]:
        sizes = []
        for flags in flagged_case_transition_map.values():
            run = 0
            for f in flags:
                if f:
                    run += 1
                else:
                    if run:
                        sizes.append(run)
                    run = 0
            if run:
                sizes.append(run)
        return sizes

    def build_flag_map(pred_attr: str) -> dict[tuple[str, str], list[bool]]:
        out: dict[tuple[str, str], list[bool]] = {}
        for (sid, cid), idxs in internal_idx_by_exec.items():
            d = per_session[sid]
            preds = v1_pred_by_session[sid] if pred_attr == "v1" else v2_pred_by_session[sid]
            out[(sid, cid)] = [bool(preds[i]) for i in idxs]
        return out

    def characterize_model(model_name: str, flagged: list[TransitionRecord], ordinary: list[TransitionRecord],
                            pred_attr: str) -> dict:
        flag_map = build_flag_map(pred_attr)
        sizes = cluster_sizes(flag_map)
        size_histogram = defaultdict(int)
        for s in sizes:
            size_histogram[s if s <= 4 else "5+"] += 1
        size_histogram = {str(k): v for k, v in sorted(size_histogram.items(), key=lambda kv: (isinstance(kv[0], str), kv[0]))}

        traj_flagged_evt = [r.event_type_jaccard for r in flagged if r.event_type_jaccard is not None]
        traj_ordinary_evt = [r.event_type_jaccard for r in ordinary if r.event_type_jaccard is not None]
        traj_flagged_cat = [r.interaction_category_jaccard for r in flagged if r.interaction_category_jaccard is not None]
        traj_ordinary_cat = [r.interaction_category_jaccard for r in ordinary if r.interaction_category_jaccard is not None]

        n_high_evidence = sum(
            1 for v in traj_flagged_evt if median_event_type_jaccard is not None and v >= median_event_type_jaccard
        )

        density_ratios = []
        exec_mean_density = {(p.session_id, p.case_id): p.mean_density_before for p in profiles}
        for r in flagged:
            mean_d = exec_mean_density.get((r.session_id, r.case_id))
            if mean_d and mean_d > 0:
                density_ratios.append(r.density_before / mean_d)

        return {
            "model": model_name,
            "n_false_internal": len(flagged),
            "n_ordinary_same_execution": len(ordinary),
            "isolated_vs_clustered": {
                "cluster_size_histogram": size_histogram,
                "n_isolated_single_transition": size_histogram.get("1", 0),
                "n_in_clusters_of_2_or_more": sum(v for k, v in size_histogram.items() if k != "1"),
            },
            "gap_association": {
                "flagged": dist_summary([r.delta_t_ms for r in flagged]),
                "ordinary_same_execution": dist_summary([r.delta_t_ms for r in ordinary]),
            },
            "context_change_association": {
                "application_changed": {"flagged": rate_summary([r.application_changed for r in flagged]),
                                         "ordinary": rate_summary([r.application_changed for r in ordinary])},
                "window_title_changed": {"flagged": rate_summary([r.window_title_changed for r in flagged]),
                                          "ordinary": rate_summary([r.window_title_changed for r in ordinary])},
                "browser_domain_changed": {"flagged": rate_summary([r.browser_domain_changed for r in flagged]),
                                            "ordinary": rate_summary([r.browser_domain_changed for r in ordinary])},
                "interaction_category_changed": {"flagged": rate_summary([r.interaction_category_changed for r in flagged]),
                                                  "ordinary": rate_summary([r.interaction_category_changed for r in ordinary])},
            },
            "neighborhood_evidence_of_return_to_context": {
                "event_type_jaccard_n10": {"flagged": dist_summary(traj_flagged_evt), "ordinary": dist_summary(traj_ordinary_evt)},
                "interaction_category_jaccard_n10": {"flagged": dist_summary(traj_flagged_cat), "ordinary": dist_summary(traj_ordinary_cat)},
                "reference_median_event_type_jaccard_same_execution_population": median_event_type_jaccard,
                "n_flagged_at_or_above_reference_median": n_high_evidence,
                "pct_flagged_at_or_above_reference_median": (
                    round(100 * n_high_evidence / len(traj_flagged_evt), 1) if traj_flagged_evt else None
                ),
            },
            "surrounded_by_continuous_activity": {
                "density_before_ratio_to_executions_own_mean_distribution": dist_summary(density_ratios),
                "note": "ratio of this transition's density_before to its own GT execution's "
                        "mean internal density_before -- a ratio near 1 means the flagged "
                        "transition sits in an otherwise-ordinary-density stretch, not an "
                        "isolated sparse spot.",
            },
        }

    item4_v1 = characterize_model("V1", v1_false_internal, v1_ordinary_same_exec, "v1")
    item4_v2 = characterize_model("V2", v2_false_internal, v2_ordinary_same_exec, "v2")

    # ==========================================================================
    # ITEM 5: A -> B -> A / general return-pattern detection
    # ==========================================================================
    return_pattern_records = []
    for sid in session_ids:
        d = per_session[sid]
        canonical = d["canonical"]
        for execution in d["executions"]:
            start_ms = int(execution.start_ts.timestamp() * 1000)
            end_ms = int(execution.end_ts.timestamp() * 1000)
            exec_events_idx = [
                i for i, e in enumerate(canonical) if start_ms <= e.timestamp_ms <= end_ms
            ]
            if len(exec_events_idx) < 3:
                continue
            for field in ("application", "browser_domain"):
                values_with_idx = [
                    (getattr(canonical[i], field), i) for i in exec_events_idx
                    if getattr(canonical[i], field) is not None
                ]
                if len(values_with_idx) < 3:
                    continue
                values = [v for v, _ in values_with_idx]
                orig_idx = [i for _, i in values_with_idx]
                patterns = detect_return_patterns(values, field=field)
                for pat in patterns:
                    left_event_idx = orig_idx[pat.left_run_end_index]
                    returned_event_idx = orig_idx[pat.returned_run_start_index]
                    # the transition immediately after "left" and immediately
                    # before "returned" are the leave/return transitions --
                    # these correspond 1:1 to TransitionFeatures index left_event_idx
                    # (transition between event i and i+1)
                    leave_transition_idx = left_event_idx
                    return_transition_idx = returned_event_idx - 1
                    v1_preds = v1_pred_by_session[sid]
                    v2_preds = v2_pred_by_session[sid]

                    def safe_pred(preds, idx):
                        return bool(preds[idx]) if 0 <= idx < len(preds) else None

                    return_pattern_records.append({
                        "session_id": sid, "case_id": execution.case_id, "field": field,
                        "value": pat.value, "is_immediate": pat.is_immediate,
                        "n_away_values": len(pat.away_values),
                        "away_duration_ms": (
                            canonical[returned_event_idx].timestamp_ms - canonical[left_event_idx].timestamp_ms
                        ),
                        "v1_flags_leave_transition": safe_pred(v1_preds, leave_transition_idx),
                        "v1_flags_return_transition": safe_pred(v1_preds, return_transition_idx),
                        "v2_flags_leave_transition": safe_pred(v2_preds, leave_transition_idx),
                        "v2_flags_return_transition": safe_pred(v2_preds, return_transition_idx),
                    })

    n_return_patterns = len(return_pattern_records)
    n_executions_with_return_pattern = len({(r["session_id"], r["case_id"]) for r in return_pattern_records})
    by_field = defaultdict(list)
    for r in return_pattern_records:
        by_field[r["field"]].append(r)

    item5 = {
        "n_return_pattern_instances_total": n_return_patterns,
        "n_gt_executions_with_at_least_one_return_pattern": n_executions_with_return_pattern,
        "pct_gt_executions_with_at_least_one_return_pattern": (
            round(100 * n_executions_with_return_pattern / len(profiles), 1) if profiles else None
        ),
        "by_field": {
            field: {
                "n_instances": len(recs),
                "n_immediate_a_b_a": sum(1 for r in recs if r["is_immediate"]),
                "n_general_multi_hop_return": sum(1 for r in recs if not r["is_immediate"]),
                "away_duration_ms_distribution": dist_summary([r["away_duration_ms"] for r in recs]),
                "v1_flags_leave_transition_rate": rate_summary(
                    [r["v1_flags_leave_transition"] for r in recs if r["v1_flags_leave_transition"] is not None]
                ),
                "v1_flags_return_transition_rate": rate_summary(
                    [r["v1_flags_return_transition"] for r in recs if r["v1_flags_return_transition"] is not None]
                ),
                "v2_flags_leave_transition_rate": rate_summary(
                    [r["v2_flags_leave_transition"] for r in recs if r["v2_flags_leave_transition"] is not None]
                ),
                "v2_flags_return_transition_rate": rate_summary(
                    [r["v2_flags_return_transition"] for r in recs if r["v2_flags_return_transition"] is not None]
                ),
            }
            for field, recs in by_field.items()
        },
    }

    # ==========================================================================
    # ITEM 6: neighborhood evidence vs. single-transition evidence -- direct summary
    # ==========================================================================
    item6 = {
        "note": "Compares N=10 trajectory-jaccard (neighborhood evidence, unchanged "
                "from Stage 5's context_features.py) against the single-transition "
                "features that actually drive V1/V2's predictions, across three "
                "groups: true boundaries (context genuinely changes), false-internal "
                "boundaries per model (flagged but GT says same execution), and "
                "ordinary unflagged same-execution transitions.",
        "event_type_jaccard_n10": {
            "true_boundary": dist_summary([r.event_type_jaccard for r in true_boundary_records if r.event_type_jaccard is not None]),
            "v1_false_internal": dist_summary([r.event_type_jaccard for r in v1_false_internal if r.event_type_jaccard is not None]),
            "v2_false_internal": dist_summary([r.event_type_jaccard for r in v2_false_internal if r.event_type_jaccard is not None]),
            "ordinary_same_execution_v1": dist_summary([r.event_type_jaccard for r in v1_ordinary_same_exec if r.event_type_jaccard is not None]),
        },
        "interaction_category_jaccard_n10": {
            "true_boundary": dist_summary([r.interaction_category_jaccard for r in true_boundary_records if r.interaction_category_jaccard is not None]),
            "v1_false_internal": dist_summary([r.interaction_category_jaccard for r in v1_false_internal if r.interaction_category_jaccard is not None]),
            "v2_false_internal": dist_summary([r.interaction_category_jaccard for r in v2_false_internal if r.interaction_category_jaccard is not None]),
            "ordinary_same_execution_v1": dist_summary([r.interaction_category_jaccard for r in v1_ordinary_same_exec if r.interaction_category_jaccard is not None]),
        },
        "single_transition_gap_ms_for_contrast": {
            "true_boundary": dist_summary([r.delta_t_ms for r in true_boundary_records]),
            "v1_false_internal": dist_summary([r.delta_t_ms for r in v1_false_internal]),
            "ordinary_same_execution_v1": dist_summary([r.delta_t_ms for r in v1_ordinary_same_exec]),
        },
    }

    # === Representative examples (item: "at least a few representative GT ===
    # === execution examples", not cherry-picked -- median and high end)  ===
    profiles_sorted = sorted(
        [p for p in profiles if p.max_internal_gap_ms is not None],
        key=lambda p: p.max_internal_gap_ms,
    )

    def profile_example(p) -> dict:
        return {**p.to_dict()}

    examples = {
        "median_max_internal_gap_execution": profile_example(profiles_sorted[len(profiles_sorted) // 2]) if profiles_sorted else None,
        "p90_max_internal_gap_execution": profile_example(profiles_sorted[int(len(profiles_sorted) * 0.9)]) if profiles_sorted else None,
        "highest_max_internal_gap_execution": profile_example(profiles_sorted[-1]) if profiles_sorted else None,
        "sample_return_pattern_instances": return_pattern_records[:5],
    }

    # === Write artifacts ===
    out = {
        "n_sessions": len(session_ids),
        "n_gt_executions": len(profiles),
        "n_transitions_total": n_transitions_total,
        "gap_percentiles_same_execution_ms": {"p50": p50, "p75": p75, "p90": p90, "p95": p95, "p99": p99},
        "item1_signal_rates_and_combinations": item1,
        "item2_per_execution_interruption_pattern": item2,
        "item3_internal_vs_true_boundary": item3,
        "item4_false_internal_boundary_characterization": {"v1": item4_v1, "v2": item4_v2},
        "item5_return_patterns": item5,
        "item6_neighborhood_vs_single_transition_evidence": item6,
        "examples": examples,
    }
    out_path = args.out / f"interruption_forensics_dataset_a.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nWrote {out_path}", file=sys.stderr)

    with (args.out / "interruption_forensics_execution_profiles_dataset_a.json").open("w", encoding="utf-8") as f:
        json.dump([p.to_dict() for p in profiles], f, ensure_ascii=False, default=str)
    with (args.out / "interruption_forensics_return_patterns_dataset_a.json").open("w", encoding="utf-8") as f:
        json.dump(return_pattern_records, f, ensure_ascii=False, default=str)

    print("Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
