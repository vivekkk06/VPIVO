#!/usr/bin/env python3
"""Stage 8.4: forensic investigation of Rule 4's 296 wrongly-demoted real
GT boundaries ("Population B") vs. its 3,667 correctly-demoted false
internal boundaries ("Population A").

Diagnostic only. Does NOT change Stage 8.3's reconstruction behavior,
does NOT implement a new rule, does NOT train a classifier, does NOT
touch Dataset B. Re-runs V1's/V2's exact LOSO procedures (same
thresholds, 0.9078/0.8860, never retuned) and Stage 8.3's exact Design 2
rule application (same selected threshold, tau=0.40, never re-selected)
solely to reproduce the same candidate set and the same Rule-4 decisions
-- this script's only new work is characterizing the two resulting
populations, not deciding anything new about them.

GT (is_boundary label, GT execution spans, process_code/case_id) is used
here ONLY for: (a) defining populations A and B (GT is what makes a
"correct" vs "incorrect" removal meaningful at all) and (b) the
post-hoc process/session concentration diagnostics (items 9-10). No GT
field is used as an input to any signal that could feed a future
reconstruction rule -- every signal reported here is computed from raw
events, held-out model scores, or the existing candidate/rule-2/N=10
machinery, exactly as Stage 8.3's rule engine itself is restricted to.

Usage:
    python scripts/analyze_rule4_errors.py --dataset dataset_a --out reports/day2
"""

from __future__ import annotations

import argparse
import bisect
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
from procmine.segmentation.context_features import extract_trajectory_features, before_window, after_window
from procmine.segmentation.continuity_labels import label_continuity
from procmine.segmentation.continuity_model import continuity_feature_vector
from procmine.segmentation.features import extract_transition_features, label_transitions
from procmine.segmentation.interruption_forensics import internal_transition_indices
from procmine.segmentation.model import feature_vector as v1_feature_vector
from procmine.segmentation.model import make_pipeline
from procmine.segmentation.reconstruction import (
    RULE_4_CONTINUITY,
    apply_design2_rules,
    cluster_size_per_transition,
    compute_rule2_demotions,
    involves_duplicate_app_switch,
    return_pattern_evidence_for_transition,
    union_candidates,
)
from procmine.segmentation.rule4_forensics import classify_candidate_source, hostname_only, port_only
from procmine.segmentation.signals import app_switch_payload_key, deduplicate_consecutive, extract_boundaries
from procmine.validation import ValidationReport

V1_THRESHOLD = 0.9078
V2_BOUNDARY_SCORE_THRESHOLD = 0.8860
TRAJECTORY_WINDOW_N = 10
SELECTED_RULE4_THRESHOLD = 0.40  # Stage 8.3's already-selected value -- reused, NOT re-selected here


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
        "p10": round(percentile(values, 0.10), 4), "p25": round(percentile(values, 0.25), 4),
        "p75": round(percentile(values, 0.75), 4), "p90": round(percentile(values, 0.90), 4),
        "p95": round(percentile(values, 0.95), 4),
        "min": round(min(values), 4), "max": round(max(values), 4),
    }


def rate_summary(bools):
    bools = [b for b in bools if b is not None]
    if not bools:
        return {"n": 0, "rate": None}
    return {"n": len(bools), "n_true": int(sum(bools)), "rate": round(sum(bools) / len(bools), 4)}


def safe_auc(a_values, b_values):
    """AUC treating population B as the positive class -- Stage 5's exact
    convention (>0.5: higher values associate with B; <0.5: with A; only
    closeness to 0.5 means uninformative). None if undefined (constant
    values or an empty side)."""
    a_values = [v for v in a_values if v is not None]
    b_values = [v for v in b_values if v is not None]
    if not a_values or not b_values:
        return None
    y = [0] * len(a_values) + [1] * len(b_values)
    scores = [float(v) for v in a_values] + [float(v) for v in b_values]
    if len(set(scores)) == 1:
        return None
    try:
        return round(float(roc_auc_score(y, scores)), 4)
    except ValueError:
        return None


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
            "canonical": canonical, "feats": feats, "boundaries": boundaries,
            "is_boundary_labels": is_boundary_labels, "clabels": clabels,
            "executions": executions_closed,
            "duplicate_app_switch_ids": duplicate_app_switch_ids,
            "X_v1": X_v1, "X_v2": X_v2, "ts": ts,
        }
    return per_session


def run_loso(per_session: dict, session_ids: list[str]) -> tuple[dict, dict]:
    """Returns (v1_scores_by_session, v1_pred_by_session) and same for V2 --
    both raw continuous scores and thresholded booleans, since this stage
    needs the scores too."""
    y_v1 = np.array([1 if lt.is_boundary else 0
                      for sid in session_ids for lt in per_session[sid]["is_boundary_labels"]])
    groups_v1 = np.array([sid for sid in session_ids for _ in per_session[sid]["is_boundary_labels"]])
    X_v1_all = np.vstack([per_session[sid]["X_v1"] for sid in session_ids])
    v1_scores, v1_preds = {}, {}
    for held_out in session_ids:
        mask = groups_v1 != held_out
        pipeline = make_pipeline()
        pipeline.fit(X_v1_all[mask], y_v1[mask])
        probs = pipeline.predict_proba(per_session[held_out]["X_v1"])[:, 1]
        v1_scores[held_out] = probs
        v1_preds[held_out] = probs >= V1_THRESHOLD

    X_v2_train, y_v2_train, groups_v2_train = [], [], []
    for sid in session_ids:
        d = per_session[sid]
        for x, cl in zip(d["X_v2"], d["clabels"]):
            if cl.excluded:
                continue
            X_v2_train.append(x); y_v2_train.append(cl.continuity_label); groups_v2_train.append(sid)
    X_v2_train = np.array(X_v2_train); y_v2_train = np.array(y_v2_train); groups_v2_train = np.array(groups_v2_train)
    v2_scores, v2_preds = {}, {}
    for held_out in session_ids:
        mask = groups_v2_train != held_out
        pipeline = make_pipeline()
        pipeline.fit(X_v2_train[mask], y_v2_train[mask])
        s1_probs = pipeline.predict_proba(per_session[held_out]["X_v2"])[:, 1]
        boundary_score = 1 - s1_probs
        v2_scores[held_out] = boundary_score
        v2_preds[held_out] = boundary_score >= V2_BOUNDARY_SCORE_THRESHOLD

    return {"v1_scores": v1_scores, "v1_preds": v1_preds, "v2_scores": v2_scores, "v2_preds": v2_preds}


def boundary_lookup_for_session(feats, boundaries) -> dict[int, object]:
    """Maps a transition index to the real `Boundary` record (with
    prev/next process_code, is_resume) it corresponds to -- the exact
    same containment-join convention `features.label_transitions` uses,
    just also keeping the matched Boundary object for post-hoc diagnosis
    instead of only a boolean. GT-derived; used only for item 10's
    post-reconstruction diagnostic, never as a reconstruction input."""
    ts = [f.timestamp_ms for f in feats]
    out = {}
    for b in boundaries:
        idx = bisect.bisect_right(ts, b.timestamp_ms) - 1
        if 0 <= idx < len(feats) and b.timestamp_ms < feats[idx].next_timestamp_ms:
            out[idx] = b
    return out


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
    print("Running V2 LOSO complete.", file=sys.stderr)

    # === Reproduce Stage 8.3's exact candidate set and Design 2 decisions ===
    records = []  # one dict per Rule-4-demoted transition
    session_b_counts = Counter()
    for sid in session_ids:
        d = per_session[sid]
        feats = d["feats"]
        canonical = d["canonical"]
        n = len(feats)

        v1_pred = loso["v1_preds"][sid]
        v2_pred = loso["v2_preds"][sid]
        v1_score = loso["v1_scores"][sid]
        v2_score = loso["v2_scores"][sid]

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
        for i in candidate_indices:
            traj = extract_trajectory_features(canonical, i, TRAJECTORY_WINDOW_N)
            event_type_jaccard[i] = traj.event_type_jaccard

        result = apply_design2_rules(
            candidates=candidates, chunk_boundary=chunk_boundary, duplicate_noise=duplicate_noise,
            rule2_demote_indices=rule2_demote_indices, cluster_size=cluster_size,
            event_type_jaccard=event_type_jaccard, continuity_threshold=SELECTED_RULE4_THRESHOLD,
        )

        same_exec: set[int] = set()
        for execution in d["executions"]:
            start_ms = int(execution.start_ts.timestamp() * 1000)
            end_ms = int(execution.end_ts.timestamp() * 1000)
            same_exec.update(internal_transition_indices(feats, start_ms, end_ms))

        boundary_lookup = boundary_lookup_for_session(feats, d["boundaries"])

        for i in range(n):
            if result.rule_applied[i] != RULE_4_CONTINUITY or result.final_boundary[i]:
                continue  # only Rule-4 DEMOTIONS are in scope for this investigation
            lt = d["is_boundary_labels"][i]
            if lt.is_boundary:
                population = "B"  # Rule-4-incorrect removal: a real GT boundary
                session_b_counts[sid] += 1
            elif i in same_exec:
                population = "A"  # Rule-4-correct removal: false internal boundary
            else:
                continue  # removed in a noise gap -- neither A nor B as defined by the brief

            traj = extract_trajectory_features(canonical, i, TRAJECTORY_WINDOW_N)
            f = feats[i]
            before_evt = canonical[i]
            after_evt = canonical[i + 1]
            rp = return_pattern_evidence_for_transition(canonical, i, TRAJECTORY_WINDOW_N)
            before_win = before_window(canonical, i, TRAJECTORY_WINDOW_N)
            after_win = after_window(canonical, i + 1, TRAJECTORY_WINDOW_N)

            host_before, host_after = hostname_only(before_evt.browser_url), hostname_only(after_evt.browser_url)
            port_before, port_after = port_only(before_evt.browser_url), port_only(after_evt.browser_url)

            b = boundary_lookup.get(i)
            records.append({
                "population": population, "session_id": sid,
                "event_i_id": f.event_i_id, "event_next_id": f.event_next_id,
                "delta_t_ms": f.delta_t_ms, "log1p_delta_t_ms": f.log1p_delta_t_ms,
                "density_before": f.density_before, "density_after": f.density_after,
                "application_changed": f.application_changed,
                "window_title_changed": f.window_title_changed,
                "browser_domain_changed": f.browser_domain_changed,
                "interaction_category_changed": f.interaction_category_changed,
                "extracted_text_at_transition": f.extracted_text_at_transition,
                "chunk_boundary": f.chunk_boundary,
                "duplicate_app_switch": duplicate_noise[i],
                "event_type_jaccard": traj.event_type_jaccard,
                "interaction_category_jaccard": traj.interaction_category_jaccard,
                "application_jaccard": traj.application_jaccard,
                "browser_domain_jaccard_with_port": traj.browser_domain_jaccard_with_port,
                "browser_domain_jaccard_host_only": traj.browser_domain_jaccard_host_only,
                "window_title_jaccard": traj.window_title_jaccard,
                "before_window_duration_ms": traj.before_window_duration_ms,
                "after_window_duration_ms": traj.after_window_duration_ms,
                "candidate_source": classify_candidate_source(bool(v1_pred[i]), bool(v2_pred[i])),
                "flagged_by_both_models": bool(v1_pred[i]) and bool(v2_pred[i]),
                "v1_score": float(v1_score[i]), "v2_boundary_score": float(v2_score[i]),
                "return_pattern_role": rp.role, "return_pattern_field": rp.field,
                "hostname_changed": (host_before != host_after) if (host_before or host_after) else None,
                "port_changed": (port_before != port_after) if (port_before is not None or port_after is not None) else None,
                "high_event_type_jaccard_but_context_changed": (
                    traj.event_type_jaccard is not None and traj.event_type_jaccard >= 0.5
                    and (f.application_changed or f.browser_domain_changed or f.window_title_changed)
                ),
                "before_event_types": sorted(before_win.event_types),
                "after_event_types": sorted(after_win.event_types),
                "before_interaction_categories": sorted(before_win.interaction_categories),
                "after_interaction_categories": sorted(after_win.interaction_categories),
                "is_resume_boundary": b.is_resume if b else None,
                "prev_process_code": b.prev_process_code if b else None,
                "next_process_code": b.next_process_code if b else None,
                "immediate_before_event_type": before_evt.event_type,
                "immediate_after_event_type": after_evt.event_type,
            })

    pop_a = [r for r in records if r["population"] == "A"]
    pop_b = [r for r in records if r["population"] == "B"]
    print(f"\nPopulation A (Rule-4-correct removals): {len(pop_a)}", file=sys.stderr)
    print(f"Population B (Rule-4-incorrect removals): {len(pop_b)}", file=sys.stderr)
    print("(Stage 8.3 reported 3,667 and 296 respectively -- cross-check.)", file=sys.stderr)

    # ===================== 1. Count and proportion =====================
    item1 = {
        "n_A": len(pop_a), "n_B": len(pop_b),
        "proportion_B_of_total_rule4_demotions": round(len(pop_b) / (len(pop_a) + len(pop_b)), 4) if (pop_a or pop_b) else None,
        "ratio_A_to_B": round(len(pop_a) / len(pop_b), 2) if pop_b else None,
    }

    # ============ 2. Distribution comparison across named signals ============
    numeric_signals = [
        "event_type_jaccard", "interaction_category_jaccard", "application_jaccard",
        "browser_domain_jaccard_with_port", "browser_domain_jaccard_host_only", "window_title_jaccard",
        "delta_t_ms", "log1p_delta_t_ms", "density_before", "density_after",
        "before_window_duration_ms", "after_window_duration_ms", "v1_score", "v2_boundary_score",
    ]
    boolean_signals = [
        "application_changed", "window_title_changed", "browser_domain_changed",
        "interaction_category_changed", "extracted_text_at_transition", "chunk_boundary",
        "duplicate_app_switch", "hostname_changed", "port_changed",
        "high_event_type_jaccard_but_context_changed", "flagged_by_both_models",
    ]

    item2 = {"numeric": {}, "boolean": {}}
    for sig in numeric_signals:
        a_vals = [r[sig] for r in pop_a]
        b_vals = [r[sig] for r in pop_b]
        item2["numeric"][sig] = {
            "A": dist_summary(a_vals), "B": dist_summary(b_vals),
            "auc_B_positive": safe_auc(a_vals, b_vals),
        }
    for sig in boolean_signals:
        a_vals = [r[sig] for r in pop_a]
        b_vals = [r[sig] for r in pop_b]
        item2["boolean"][sig] = {
            "A": rate_summary(a_vals), "B": rate_summary(b_vals),
            "auc_B_positive": safe_auc([1 if v else 0 for v in a_vals if v is not None],
                                        [1 if v else 0 for v in b_vals if v is not None]),
        }

    # ================ 3. Candidate-source breakdown ================
    def source_breakdown(pop):
        c = Counter(r["candidate_source"] for r in pop)
        n = len(pop)
        return {k: {"n": v, "rate": round(v / n, 4)} for k, v in c.items()} if n else {}
    item3 = {"A": source_breakdown(pop_a), "B": source_breakdown(pop_b)}

    # ================ 4. Leave-and-return involvement ================
    def return_breakdown(pop):
        n = len(pop)
        n_involved = sum(1 for r in pop if r["return_pattern_role"] is not None)
        return {
            "n_total": n, "n_involved_in_return_pattern": n_involved,
            "rate": round(n_involved / n, 4) if n else None,
            "role_counts": dict(Counter(r["return_pattern_role"] for r in pop if r["return_pattern_role"])),
        }
    item4 = {"A": return_breakdown(pop_a), "B": return_breakdown(pop_b)}

    # ========== 5. Local positional pattern (immediate adjacent event, ==========
    # ========== fixed +/-1 event neighborhood, no GT execution scoping) ==========
    def immediate_neighbor_breakdown(pop, key):
        counter = Counter(r[key] for r in pop)
        n = len(pop)
        return {k: {"n": v, "rate": round(v / n, 4)} for k, v in counter.most_common(15)} if n else {}

    item5 = {
        "A": {
            "immediate_before_event_type": immediate_neighbor_breakdown(pop_a, "immediate_before_event_type"),
            "immediate_after_event_type": immediate_neighbor_breakdown(pop_a, "immediate_after_event_type"),
        },
        "B": {
            "immediate_before_event_type": immediate_neighbor_breakdown(pop_b, "immediate_before_event_type"),
            "immediate_after_event_type": immediate_neighbor_breakdown(pop_b, "immediate_after_event_type"),
        },
        "note": "Immediate (+/-1 event) neighbor identity -- a narrower, positional "
                "complement to item 6's full +/-10 event window composition below. "
                "No GT execution identity is used to define this neighborhood.",
    }

    # ================ 6. N=10 composition (event types / categories) ================
    def composition(pop, key):
        counter = Counter()
        for r in pop:
            counter.update(r[key])
        n = len(pop)
        return {k: {"n_windows_containing": v, "rate": round(v / n, 4)} for k, v in counter.most_common(15)} if n else {}

    item6 = {
        "A": {
            "before_event_types": composition(pop_a, "before_event_types"),
            "after_event_types": composition(pop_a, "after_event_types"),
            "before_interaction_categories": composition(pop_a, "before_interaction_categories"),
            "after_interaction_categories": composition(pop_a, "after_interaction_categories"),
        },
        "B": {
            "before_event_types": composition(pop_b, "before_event_types"),
            "after_event_types": composition(pop_b, "after_event_types"),
            "before_interaction_categories": composition(pop_b, "before_interaction_categories"),
            "after_interaction_categories": composition(pop_b, "after_interaction_categories"),
        },
    }

    # ============ 7. context (already covered by item2's boolean block; ============
    # ============ add the explicit combined "same X" framing requested) ============
    def same_rate(pop, changed_key):
        vals = [not r[changed_key] for r in pop if r[changed_key] is not None]
        return rate_summary(vals)

    item7 = {
        "same_application": {"A": same_rate(pop_a, "application_changed"), "B": same_rate(pop_b, "application_changed")},
        "same_browser_host": {"A": same_rate(pop_a, "hostname_changed"), "B": same_rate(pop_b, "hostname_changed")},
        "same_browser_port": {"A": same_rate(pop_a, "port_changed"), "B": same_rate(pop_b, "port_changed")},
        "same_window_title": {"A": same_rate(pop_a, "window_title_changed"), "B": same_rate(pop_b, "window_title_changed")},
        "same_interaction_category": {"A": same_rate(pop_a, "interaction_category_changed"), "B": same_rate(pop_b, "interaction_category_changed")},
        "high_event_type_jaccard_but_context_changed": {
            "A": rate_summary([r["high_event_type_jaccard_but_context_changed"] for r in pop_a]),
            "B": rate_summary([r["high_event_type_jaccard_but_context_changed"] for r in pop_b]),
        },
    }

    # ================ 8. Gap regime, with reference tiers ================
    all_true_boundary_gaps = [
        f.delta_t_ms for sid in session_ids
        for f, lt in zip(per_session[sid]["feats"], per_session[sid]["is_boundary_labels"]) if lt.is_boundary
    ]
    item8 = {
        "all_GT_true_boundaries_gap_ms": dist_summary(all_true_boundary_gaps),
        "population_B_gap_ms": dist_summary([r["delta_t_ms"] for r in pop_b]),
        "population_A_gap_ms": dist_summary([r["delta_t_ms"] for r in pop_a]),
        "note": "population_B is the subset of true boundaries Rule 4 wrongly demoted; "
                "all_GT_true_boundaries is every true boundary regardless of candidate/rule "
                "outcome, for reference on whether B has an unusual gap regime.",
    }

    # ================ 9. Session concentration (diagnostic only) ================
    b_counts_all_sessions = [session_b_counts.get(sid, 0) for sid in session_ids]
    item9 = {
        "n_sessions_with_zero_B": sum(1 for c in b_counts_all_sessions if c == 0),
        "n_sessions_with_at_least_one_B": sum(1 for c in b_counts_all_sessions if c > 0),
        "distribution_of_B_count_per_session": dist_summary(b_counts_all_sessions),
        "top_10_sessions_by_B_count": sorted(session_b_counts.items(), key=lambda kv: -kv[1])[:10],
    }

    # ================ 10. Process concentration (post-hoc GT use) ================
    prev_codes = Counter(r["prev_process_code"] for r in pop_b if r["prev_process_code"])
    next_codes = Counter(r["next_process_code"] for r in pop_b if r["next_process_code"])
    n_resume = sum(1 for r in pop_b if r["is_resume_boundary"])
    item10 = {
        "n_resume_boundaries_in_B": n_resume,
        "rate_resume_boundaries_in_B": round(n_resume / len(pop_b), 4) if pop_b else None,
        "prev_process_code_counts": dict(prev_codes.most_common(15)),
        "next_process_code_counts": dict(next_codes.most_common(15)),
        "note": "GT process_code used here ONLY for post-hoc diagnosis of population B, "
                "after all reconstruction decisions were already made without it.",
    }

    # ================ 11. Candidate discriminative signal verdicts ================
    def verdict(sig_name, auc, is_gt_free, is_reconstruction_time_available, notes=""):
        if auc is None:
            separates = False
        else:
            separates = abs(auc - 0.5) >= 0.10  # descriptive framing threshold, not a rule threshold
        return {
            "signal": sig_name, "auc_B_positive": auc, "separation_from_uninformative": round(abs(auc - 0.5), 4) if auc is not None else None,
            "derivable_from_raw_events_no_GT": is_gt_free,
            "available_at_reconstruction_time": is_reconstruction_time_available,
            "notes": notes,
        }

    signal_verdicts = []
    for sig in numeric_signals:
        auc = item2["numeric"][sig]["auc_B_positive"]
        signal_verdicts.append(verdict(sig, auc, True, True, ""))
    for sig in boolean_signals:
        auc = item2["boolean"][sig]["auc_B_positive"]
        signal_verdicts.append(verdict(sig, auc, True, True, ""))
    signal_verdicts.append(verdict(
        "return_pattern_involvement",
        safe_auc([1 if r["return_pattern_role"] is not None else 0 for r in pop_a],
                 [1 if r["return_pattern_role"] is not None else 0 for r in pop_b]),
        True, True, "",
    ))
    signal_verdicts.sort(key=lambda v: -(v["separation_from_uninformative"] or 0))

    # === Robustness check for the top candidate signals: does the pooled ===
    # === direction of the effect hold session-by-session, or is it driven ===
    # === by a small number of sessions? Only sessions with >=1 record in ===
    # === BOTH populations can contribute a directional comparison.        ===
    def session_direction_consistency(sig_name, pop_a, pop_b):
        a_by_session = defaultdict(list)
        b_by_session = defaultdict(list)
        for r in pop_a:
            if r[sig_name] is not None:
                a_by_session[r["session_id"]].append(float(r[sig_name]))
        for r in pop_b:
            if r[sig_name] is not None:
                b_by_session[r["session_id"]].append(float(r[sig_name]))
        pooled_mean_a = statistics.fmean([v for vs in a_by_session.values() for v in vs]) if a_by_session else None
        pooled_mean_b = statistics.fmean([v for vs in b_by_session.values() for v in vs]) if b_by_session else None
        if pooled_mean_a is None or pooled_mean_b is None:
            return None
        pooled_direction = pooled_mean_b > pooled_mean_a
        n_agree = n_disagree = n_eligible = 0
        for sid in set(a_by_session) & set(b_by_session):
            n_eligible += 1
            session_mean_a = statistics.fmean(a_by_session[sid])
            session_mean_b = statistics.fmean(b_by_session[sid])
            if (session_mean_b > session_mean_a) == pooled_direction:
                n_agree += 1
            else:
                n_disagree += 1
        return {
            "n_sessions_eligible": n_eligible, "n_sessions_agree_with_pooled_direction": n_agree,
            "n_sessions_disagree": n_disagree,
            "agreement_rate": round(n_agree / n_eligible, 4) if n_eligible else None,
        }

    top_signal_names = [v["signal"] for v in signal_verdicts[:6]]
    robustness = {}
    for sig in top_signal_names:
        if sig in numeric_signals:
            a_vals_by_rec, b_vals_by_rec = pop_a, pop_b
        elif sig in boolean_signals:
            a_vals_by_rec, b_vals_by_rec = pop_a, pop_b
        else:
            continue
        robustness[sig] = session_direction_consistency(sig, a_vals_by_rec, b_vals_by_rec)
    item11b_robustness = robustness

    out = {
        "selected_rule4_threshold_reused": SELECTED_RULE4_THRESHOLD,
        "item1_counts": item1,
        "item2_distributions": item2,
        "item3_candidate_source": item3,
        "item4_return_pattern_involvement": item4,
        "item5_local_positional_pattern": item5,
        "item6_n10_composition": item6,
        "item7_application_browser_window_context": item7,
        "item8_gap_regime": item8,
        "item9_session_concentration": item9,
        "item10_process_concentration": item10,
        "item11_signal_verdicts_ranked": signal_verdicts,
        "item11b_top_signal_session_robustness": item11b_robustness,
    }
    out_path = args.out / f"rule4_error_forensics_{args.dataset.name}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nWrote {out_path}", file=sys.stderr)

    print("\nTop signals by |AUC - 0.5|:", file=sys.stderr)
    for v in signal_verdicts[:10]:
        print(f"  {v['signal']:<45} AUC={v['auc_B_positive']}  sep={v['separation_from_uninformative']}", file=sys.stderr)

    print("Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
