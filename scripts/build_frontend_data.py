#!/usr/bin/env python3
"""Day 5: build the static JSON bundle the frontend dashboard consumes.

This is a READ -> SELECT -> RESHAPE -> WRITE adapter and nothing else. It
contains no analytical logic: it does not segment, score, threshold,
compute entropy, build directly-follows graphs, or re-derive any
aggregate that already exists in a Day-1..Day-4 artifact. Every number it
emits is either copied verbatim from a source artifact or is a clearly
marked derived field (a count, a key lift, or a dict lookup) documented in
`reports/day5/data_contract.md`.

That restriction is the point of the file. The frontend must visualise the
existing analysis, never fork it -- if a formula ever appears below, the
frontend and the pipeline can silently disagree, which is exactly the
failure this bridge exists to prevent.

CANONICAL SOURCE NOTE (important): three ranking artifacts exist in
`reports/day3/` with different values. `automation_priority_dataset_b.json`
holds the superseded 8-factor score and `problem2_process_metrics.json` /
`problem2_process_mining_full_results.json` hold PRE-entropy-fix scores
(HR opportunity 0.4186). Only `problem2_audit_results.json` carries the
post-fix values (HR opportunity 0.4401). This script reads the ranking
exclusively from `problem2_audit_results.json`; the full-results file is
read ONLY for the HR directly-follows graph and similarity investigation,
which the audit file does not contain.

Usage:
    python scripts/build_frontend_data.py --out frontend/public/data
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# --- Canonical sources. Nothing outside this map is read. -----------------
SOURCES = {
    "dataset_a_metrics": Path("reports/day2/protected_boundary_experiment_dataset_a.json"),
    "executions": Path("reports/day3/process_executions_dataset_b.json"),
    "profiles": Path("reports/day3/process_profiles_dataset_b.json"),
    "variants": Path("reports/day3/process_variants_dataset_b.json"),
    "mining_full": Path("reports/day3/problem2_process_mining_full_results.json"),
    "audit": Path("reports/day3/problem2_audit_results.json"),
    "hr_dominant_path": Path("reports/day3/hr_payroll_dominant_path_dataset_b.json"),
    "health_a": Path("reports/day4/instrumentation_health_dataset_a.json"),
    "health_b": Path("reports/day4/instrumentation_health_dataset_b.json"),
    "day4_sensitivity": Path("reports/day4/instrumentation_sensitivity_check.json"),
    "day7_classifier": Path("reports/day7/process_classifier_experiment.json"),
    "day7_browser": Path("reports/day7/browser_automation_demo.json"),
    "day7_segmentation": Path("reports/day7/segmentation_comparison.json"),
}

# Day-1 / Day-2 / Day-4 investigation pages. These artifacts were always part of the
# record; the first bundle simply had no screen for them. `investigation.json` is built
# from them with the same rule as everything else: copy, count, or look up -- never score.
INVESTIGATION_SOURCES = {
    "day1_inventory": Path("reports/day1/dataset_inventory.json"),
    "day1_profile_a": Path("reports/day1/profile_dataset_a.json"),
    "day1_profile_b": Path("reports/day1/profile_dataset_b.json"),
    "day1_audit_a": Path("reports/day1/full_audit_dataset_a.json"),
    "day1_audit_b": Path("reports/day1/full_audit_dataset_b.json"),
    "day1_validation_a": Path("reports/day1/validation_dataset_a.json"),
    "day1_validation_b": Path("reports/day1/validation_dataset_b.json"),
    "day2_baselines": Path("reports/day2/baseline_segmentation_dataset_a.json"),
    "day2_learned": Path("reports/day2/learned_model_dataset_a.json"),
    "day2_threshold_tradeoff": Path("reports/day2/threshold_tradeoff_dataset_a.json"),
    "day6_ensemble": Path("reports/day6/boundary_ensemble_experiment_dataset_a.json"),
}

# A few figures exist only in a written Day-1 / Day-3 / Day-4 report, not in a JSON
# artifact. Each is carried together with the exact fragment it was taken from, and the
# build fails if that fragment is no longer in the report -- so the screen cannot drift
# away from what the report says.
DOCUMENTED = {
    "raw_order_screenshot_share": (
        "68%", "reports/day1/timestamp_quality.md",
        "**68% of these near-simultaneous"),
    "negative_gap_events": (
        "443 events (0.27%)", "reports/day1/data_quality_report.md",
        "443 events (0.27%) have"),
    "negative_gap_minimum": (
        "-713,900 ms", "reports/day1/data_quality_report.md",
        "| min | **-713,900 ms** |"),
    "screenshot_resolution_a": (
        "7.2%", "reports/day1/data_quality_report.md",
        "| **Resolution rate** | **7.2%** | **81.2%** |"),
    "screenshot_resolution_b": (
        "81.2%", "reports/day1/data_quality_report.md",
        "| **Resolution rate** | **7.2%** | **81.2%** |"),
    "screenshots_resolved_a": (
        "2,489", "reports/day1/data_quality_report.md", "| 2,489 | ~3,865 |"),
    "screenshots_resolved_b": (
        "~3,865", "reports/day1/data_quality_report.md", "| 2,489 | ~3,865 |"),
    "app_switch_duplication": (
        "65%", "reports/day1/cleaning_policy.md", "(65% duplication measured)"),
    "semantic_duplicates_browser_error": (
        "100%", "reports/day1/data_quality_report.md",
        "| 42 groups / 84 events | 100% `event_type: browser_error` |"),
    "gt_executions": (
        "2,009", "reports/day1/ground_truth_validation.md",
        "**Total: 2,009 executions reconstructed across 63 sessions.**"),
    "gt_abandoned_suspension": (
        "1 occurrence", "reports/day1/ground_truth_validation.md",
        "| **1 occurrence** | **real, actual inconsistency**"),
    "domain_change_share": (
        "96.6%", "reports/day4/instrumentation_health_analysis.md",
        "**96.6%** of ground-truth boundaries on normally-instrumented sessions"),
    "coverage_gap": (
        "26.00 → 46.42", "reports/day4/instrumentation_health_analysis.md",
        "**26.00 → 46.42 (20.4pp)**"),
    "coverage_margin": (
        "6.4pp", "reports/day4/instrumentation_health_analysis.md", "**6.4pp margin**"),
    "impact_formula": (
        "Impact_p = mean(norm(FS_p), norm(TS_p), norm(manual_p))",
        "reports/day3/problem2_process_mining_analysis.md",
        "`Impact_p = mean(norm(FS_p), norm(TS_p), norm(manual_p))`"),
    "feasibility_formula": (
        "Feasibility_p = mean(norm(C_p), 1-norm(H_norm_p), norm(AS_p), 1-norm(risk_p))",
        "reports/day3/problem2_process_mining_analysis.md",
        "`Feasibility_p = mean(norm(C_p), 1-norm(H_norm_p), norm(AS_p), 1-norm(risk_p))`"),
    "opportunity_formula": (
        "Opportunity_p = Impact_p × Feasibility_p",
        "reports/day3/problem2_process_mining_analysis.md",
        "`Opportunity_p = Impact_p × Feasibility_p`"),
    "surface_formula": (
        "AS_p = dominant_variant_share × avg_manual_event_share",
        "reports/day3/problem2_process_mining_analysis.md",
        "`AS_p = dominant_variant_share × avg_manual_event_share`"),
    "hr_normalized_entropy": (
        "0.419", "reports/day3/problem2_process_mining_analysis.md",
        "| `variant_entropy` (normalized) | 0.419 | DERIVED |"),
}

# Day-6 Module 2 artifacts. OPTIONAL on purpose: Module 2 is an experimental module,
# and the bundle must still build for anyone who has not run its experiments. When all
# are present, `module-comparison.json` is emitted; otherwise it is skipped.
OPTIONAL_SOURCES = {
    "module2_segmentation": Path("reports/day6/module2/module2_segmentation_experiment.json"),
    "module2_gate": Path("reports/day6/module2/module2_promotion_gate.json"),
    "module2_process": Path("reports/day6/module2/module2_process_analysis.json"),
    "module2_automation": Path("reports/day6/module2/module2_automation_analysis.json"),
    "module2_screenshots": Path("reports/day6/module2/module2_dataset_b_screenshot_sample.json"),
}

# The completed surrogate visual review of that sample. Optional on its own: without it
# the comparison still builds and the screen says the review has not been run.
VISUAL_REVIEW_SOURCE = Path("reports/day6/module2/dataset_b_visual_review_results.json")


def _visual_review(results: dict | None) -> dict | None:
    """Dataset-B surrogate visual review, copied verbatim. Descriptive counts only."""
    if results is None:
        return None
    s = results["summary"]
    d = results["decision"]
    return {
        "label": results["label"],
        "status": results["status"],
        "reviewer": results["reviewer"],
        "human_review": results["human_review"],
        "seed": results["protocol"]["seed"],
        "hash_verified_at_reveal": results["blindness"]["hash_verified_at_reveal"],
        "sample_size": s["sample_size"],
        "screenshots_available": s["screenshots_available"],
        "screenshots_unavailable": s["screenshots_unavailable"],
        "screenshots_recovered": results["recovery"]["recovered"],
        "counts": s["counts"],
        "counts_by_sample_type": s["counts_by_sample_type"],
        "boundary_samples_judgeable": s["boundary_samples_judgeable"],
        "control_samples_judgeable": s["control_samples_judgeable"],
        "boundary_sample_visual_support_rate": s["boundary_sample_visual_support_rate"],
        "control_sample_visual_continuity_rate": s["control_sample_visual_continuity_rate"],
        "ambiguous_total": s["ambiguous_total"],
        "not_metrics_note": s["not_metrics_note"],
        "decision": {k: d[k] for k in ("outcome", "statement", "basis", "module2_promotion")},
        "missing_cause": (results.get("missing_screenshots") or {}).get("cause"),
    }


def _module_comparison(src: dict) -> dict:
    """Day-6 Module 1 vs Module 2, copied verbatim from the Module 2 artifacts.

    No arithmetic beyond selecting which candidate to display. Every number the
    comparison screen renders is read from an artifact here, never computed in React.
    """
    seg = src["module2_segmentation"]
    gate = src["module2_gate"]
    proc = src["module2_process"]
    auto = src["module2_automation"]
    shots = src["module2_screenshots"]

    sets = seg["feature_sets"]
    best_key = gate["best_candidate_by_f1"]

    def pooled(key: str, protocol: str) -> dict:
        return sets[key]["protocols"][protocol]["eval"]["pooled"]

    best_gate = gate["candidates"][best_key]["matched"]["vs_control"]
    routing = auto["step_3a_routing"]

    return {
        "module1": {
            "name": "Module 1 — Continuity-Based Reconstruction",
            "status": "CANONICAL / LOCKED",
            "canonical_pooled": gate["canonical_locked_pooled"],
            "control_matched": pooled("M1_compatible", "matched"),
            "control_locked": pooled("M1_compatible", "locked"),
        },
        "module2": {
            "name": "Module 2 — Adaptive Evidence-Guided Reconstruction & Automation",
            "status": gate["module2_status"],
            "decision": gate["decision"],
            "best_candidate_key": best_key,
            "best_matched": pooled(best_key, "matched"),
            "best_locked": pooled(best_key, "locked"),
            "f1_vs_canonical_locked": gate["candidates"][best_key]["matched"][
                "f1_vs_canonical_locked"],
            "feature_sets": {k: {"extra_features": v["extra_features"],
                                 "matched": pooled(k, "matched"),
                                 "locked": pooled(k, "locked")}
                             for k, v in sets.items()},
            "content_drift_coverage": seg["content_drift_coverage"],
        },
        "gate": {
            "registered_before_candidates_were_scored":
                gate["gate_registered_before_candidates_were_scored"],
            "thresholds": gate["gate_thresholds"],
            "source": gate["gate_source"],
            "checks": best_gate["gate_checks"],
            "failed_gates": best_gate["failed_gates"],
            "deltas": best_gate["deltas"],
            "robustness": {k: v for k, v in best_gate["robustness"].items()
                           if k != "worst_5_sessions" and k != "best_5_sessions"},
            "concentration_check": best_gate["concentration_check"],
            "machine_dominance_check": best_gate["machine_dominance_check"],
        },
        "automation": {
            "coverage": routing["coverage"],
            "canonical_dominant_share": routing["canonical_dominant_share"],
            "canonical_dominant_n": routing["canonical_dominant_n"],
            "by_canonical_variant": routing["by_canonical_variant"],
            "dominant_refused": routing["dominant_executions_refused_by_the_gate"],
            "post_action_expected_state_passed":
                auto["step_3b_post_action_audit"]["expected_state_reached"]["passed"],
            "post_action_detects_route_drift":
                auto["step_3b_post_action_audit"]["detects_route_drift"],
        },
        "process_analysis": {
            "effort_table": proc["step_2a_effort"]["table"][:8],
            "total_observed_time_hours":
                proc["step_2a_effort"]["total_observed_time_hours_all_ranked"],
            "monetary_roi_statement": proc["step_2a_effort"]["monetary_roi_statement"],
            "operator_table": proc["step_2b_operator_variants"]["hr_operator_table"],
            "operator_dispersion": proc["step_2b_operator_variants"]["dispersion"],
            "pareto_frontier": proc["step_2c_pareto"]["frontier_recomputed"],
            "pareto_matches_canonical":
                proc["step_2c_pareto"]["recomputation_matches_canonical"],
            "pareto_table": proc["step_2c_pareto"]["table"],
            "sensitivity": proc["step_2d_sensitivity"],
        },
        "dataset_b_review": {
            "sampling": shots["sampling"],
            "screenshot_availability": shots["screenshot_availability"],
            "review_status": shots["review_status"],
            "dataset_b_rule": shots["dataset_b_rule"],
        },
        "dataset_b_visual_review": _visual_review(src.get("module2_visual_review")),
    }



def _segmentation_challenge(seg: dict) -> dict:
    """Day-7 segmentation challenge, copied verbatim from the comparison artifact.

    Carries the baseline and the best rejected candidate side by side so the
    Dashboard can show the fragmentation/under-segmentation trade-off without any
    arithmetic in React. `max()` here only SELECTS which candidate to display; every
    number reported is read from that candidate's own pooled metrics.
    """
    best_name = max(seg["candidates"], key=lambda k: seg["candidates"][k]["eval"]["pooled"]["f1"])
    best = seg["candidates"][best_name]["eval"]["pooled"]
    base = seg["baseline"]["pooled"]
    return {
        "decision": seg["decision"],
        "candidates_tested": len(seg["candidates"]),
        "baseline_f1": base["f1"],
        "baseline_fragmentation_pct": base["pct_gt_executions_fragmented"],
        "baseline_under_segmentation": base["under_segmentation_rate"],
        "best_candidate_key": best_name,
        "best_candidate_label": best_name.split("_")[0],
        "best_candidate_f1": best["f1"],
        "best_candidate_fragmentation_pct": best["pct_gt_executions_fragmented"],
        "best_candidate_under_segmentation": best["under_segmentation_rate"],
        "validation": "leave-one-session-out; parameters fitted on training sessions only",
        "note": "Four simpler alternatives were tested with session-aware "
                "validation; none passed the promotion gates.",
    }


def _documented(root: Path) -> dict:
    """Report-only figures, each verified against the sentence it was copied from."""
    out: dict[str, dict] = {}
    texts: dict[str, str] = {}
    for key, (value, rel, quote) in DOCUMENTED.items():
        if value not in quote:
            raise SystemExit(f"documented figure {key!r}: value is not inside its quote")
        if rel not in texts:
            path = root / rel
            if not path.exists():
                raise SystemExit(f"missing documented source: {path}")
            texts[rel] = path.read_text(encoding="utf-8")
        if quote not in texts[rel]:
            raise SystemExit(f"documented figure {key!r} no longer appears in {rel}")
        out[key] = {"value": value, "source": rel}
    return out


POOLED_KEYS = ("precision", "recall", "f1", "pct_gt_executions_fragmented",
               "under_segmentation_rate", "over_segmentation_rate")


def _pooled(p: dict) -> dict:
    """The six headline boundary metrics. A metric an artifact does not carry stays None."""
    return {k: p.get(k) for k in POOLED_KEYS}


def _day1(src: dict) -> dict:
    """Day-1 audit: verbatim totals, plus counts and sums over the per-session audit rows.

    Only counts are read from the text-input and clipboard checks. No typed value, pasted
    value or password is read, carried or written.
    """
    inventory = src["day1_inventory"]
    datasets: dict[str, dict] = {}
    checks: dict[str, dict] = {}
    for key, suffix in (("dataset_a", "a"), ("dataset_b", "b")):
        inv = inventory[key]
        profile = src[f"day1_profile_{suffix}"]
        audit = src[f"day1_audit_{suffix}"]
        rows = [v["summary"] for v in src[f"day1_validation_{suffix}"]]
        sessions = audit["sessions"]
        text_input = [s["text_input_complete"] for s in sessions]
        clipboard = [s["payload_emptiness_by_type"]["clipboard_change"] for s in sessions
                     if "clipboard_change" in s["payload_emptiness_by_type"]]
        datasets[key] = {
            "sessions": inv["n_sessions"],
            "chunks": inv["n_chunks"],
            "events": audit["n_events_total"],
            "screenshot_dirs": inv["n_screenshot_dirs"],
            "ground_truth_files": inv["n_gt_files"],
            "sessions_with_ground_truth": profile["sessions_with_ground_truth"],
            # DERIVED: inventory rows listing two or more chunk files.
            "multi_chunk_sessions": sum(1 for s in inv["sessions"] if s["n_chunks"] >= 2),
            "events_by_layer": profile["events_by_layer"],
            "screenshot_events": profile["events_by_type"].get("screenshot_smart", 0),
            "session_duration_seconds": profile["session_duration_seconds"],
            "n_applications": len(profile["applications"]),
        }
        checks[key] = {
            # DERIVED: counts and sums over the per-session validation rows.
            "sessions_with_out_of_order_pairs":
                sum(1 for r in rows if r.get("out_of_order_events", 0) > 0),
            "out_of_order_pairs": sum(r.get("out_of_order_events", 0) for r in rows),
            "malformed_json_lines": sum(r.get("malformed_json_lines", 0) for r in rows),
            "duplicate_event_ids": sum(r.get("duplicate_event_ids", 0) for r in rows),
            "gt_manifest_mismatches": sum(r.get("gt_manifest_mismatches", 0) for r in rows),
            "exact_duplicate_groups": audit["total_exact_duplicate_groups"],
            "semantic_duplicate_groups": audit["total_semantic_duplicate_groups"],
            "sequential_duplicates": audit["total_sequential_duplicates"],
            "sequential_duplicates_by_type": audit["sequential_duplicates_by_type"],
            "chunk_identity_issues": audit["total_session_chunk_identity_issues"],
            "timestamp_iso_mismatches":
                sum(s["timestamp_quality"]["ms_iso_mismatch_count"] for s in sessions),
            "non_utc_timestamps":
                sum(s["timestamp_quality"]["non_utc_iso_count"] for s in sessions),
            "text_input_complete": {
                "events": sum(t.get("n_text_input_complete_events", 0) for t in text_input),
                "with_content": sum(t.get("with_apparent_content", 0) for t in text_input),
                "missing_or_empty": sum(t.get("missing_or_empty_content", 0) for t in text_input),
                "password_fields_with_plaintext": sum(
                    t.get("password_fields_with_plaintext_final_text", 0) for t in text_input),
                "sessions_with_plaintext_password_fields": sum(
                    1 for t in text_input if t.get("password_fields_with_plaintext_final_text")),
            },
            "clipboard_change": {
                "events": sum(c["n"] for c in clipboard),
                "empty_payload": sum(c["empty_payload"] for c in clipboard),
            },
        }
    return {"datasets": datasets, "checks": checks}


# The Day-2 -> Day-7 experiment record, in the order it happened. The wording is the
# narrative; every number the screen shows next to it is copied from an artifact below.
EXPERIMENTS = [
    {"id": "temporal", "day": "Day 2", "stage": "Temporal baseline",
     "name": "Temporal baseline", "metrics_from": "temporal_baselines.temporal_only",
     "approach": "Split wherever the pause between two events is longer than a fixed gap. "
                 "The gap was swept and the best value kept.",
     "status": "REFERENCE",
     "result": "A usable floor, far from the target.",
     "failure_mode": "A long pause is a weak cue: most real boundaries are missed, and many "
                     "pauses inside a single execution are cut.",
     "decision": "Kept as the floor every later approach had to beat."},
    {"id": "contextual", "day": "Day 2", "stage": "Contextual rules",
     "name": "Contextual rules", "metrics_from": "temporal_baselines.temporal_and_context",
     "approach": "A pause and a change of application or browser context. The OR variant "
                 "was tested as well.",
     "status": "REFERENCE",
     "result": "AND barely moves F1. OR finds almost every boundary but flags more than half "
               "of all transitions.",
     "failure_mode": "Hand-set rules cannot trade recall against false splits.",
     "decision": "Move to a learned transition model over several signals."},
    {"id": "v1", "day": "Day 2", "stage": "Classifier / boundary-first",
     "name": "Boundary-first classifier (V1)", "metrics_from": "systems.V1",
     "approach": "Logistic regression on transition features, leave-one-session-out. Each "
                 "transition is scored as a boundary or not.",
     "status": "FAILED",
     "result": "Clearly better F1 than the rules, with much higher recall.",
     "failure_mode": "Heavy fragmentation: most true executions are cut into pieces by false "
                     "boundaries.",
     "decision": "Reframe the question around continuity instead of boundaries."},
    {"id": "v2", "day": "Day 2", "stage": "Continuity-first",
     "name": "Continuity-first classifier (V2)", "metrics_from": "systems.V2",
     "approach": "The same features, trained to predict that the current execution continues.",
     "status": "FAILED",
     "result": "Higher recall and less under-segmentation than V1.",
     "failure_mode": "Fragmentation got worse, not better, and F1 dropped.",
     "decision": "Use both classifiers only as a source of candidates, then prune the "
                 "candidates with rules."},
    {"id": "design2", "day": "Day 2", "stage": "Continuity rules",
     "name": "Candidate union + demotion rules (Design 2)",
     "metrics_from": "systems.Design2_original",
     "approach": "Candidates from V1 or V2, then four demote-only rules: noise override, "
                 "leave-and-return, cluster, and a ten-event continuity check.",
     "status": "PROMISING",
     "result": "The first real drop in fragmentation, and the best F1 so far.",
     "failure_mode": "The continuity rule also removed real boundaries, so "
                     "under-segmentation rose sharply.",
     "decision": "Protect likely-real boundaries from that rule."},
    {"id": "agreement", "day": "Day 2", "stage": "Protection experiments",
     "name": "Protection: classifier agreement", "metrics_from": "systems.Strategy_Agreement",
     "approach": "Keep a demoted candidate when V1 and V2 both flagged it.",
     "status": "REJECTED",
     "result": "Recall recovered.",
     "failure_mode": "It protected far more false boundaries than true ones and brought "
                     "fragmentation back to the V1/V2 level.",
     "decision": "Rejected: failed the fragmentation and protection-ratio gates."},
    {"id": "tempo", "day": "Day 2", "stage": "Protection experiments",
     "name": "Protection: tempo", "metrics_from": "systems.Strategy_Tempo",
     "approach": "Keep a demoted candidate when the next ten events unfold slowly (duration "
                 "above a threshold selected once on Dataset A).",
     "status": "NOT SELECTED",
     "result": "Passed every registered gate.",
     "failure_mode": "Lower F1 and more fragmentation than the combined rule, although its "
                     "under-segmentation was better.",
     "decision": "Not selected: the combined rule was preferred on fragmentation and F1."},
    {"id": "combined", "day": "Day 2", "stage": "Combined strategy → locked baseline",
     "name": "Protection: combined (locked baseline)",
     "metrics_from": "systems.Strategy_Combined",
     "approach": "Keep a demoted candidate only when agreement and the tempo cue both hold.",
     "status": "LOCKED",
     "result": "The best accepted trade-off under the registered gates.",
     "failure_mode": "Still imperfect: roughly four in five true executions contain at least "
                     "one false split.",
     "decision": "Locked as Module 1. Every downstream number uses it."},
    {"id": "hmm", "day": "Day 6", "stage": "Later challenge",
     "name": "Unsupervised HMM", "metrics_from": "day6.hmm_only",
     "approach": "A two-state hidden Markov model over the event stream, trained without labels.",
     "status": "REJECTED",
     "result": "Finds some boundaries the locked baseline misses.",
     "failure_mode": "Predicts boundaries almost everywhere, so F1 collapses.",
     "decision": "Not usable on its own; tried as an ensemble partner."},
    {"id": "ensemble_or", "day": "Day 6", "stage": "Later challenge",
     "name": "Ensemble: either model flags", "metrics_from": "day6.ensemble_or",
     "approach": "A boundary wherever the locked baseline or the HMM flags one.",
     "status": "REJECTED",
     "result": "The highest recall of any system tested.",
     "failure_mode": "Every extra true boundary costs hundreds of false ones.",
     "decision": "Rejected."},
    {"id": "ensemble_and", "day": "Day 6", "stage": "Later challenge",
     "name": "Ensemble: both must agree", "metrics_from": "day6.ensemble_and",
     "approach": "A boundary only where the locked baseline and the HMM agree.",
     "status": "REJECTED",
     "result": "Very low fragmentation.",
     "failure_mode": "Only because most real boundaries are missed: under-segmentation is severe.",
     "decision": "Rejected."},
    {"id": "module2", "day": "Day 6", "stage": "Later challenge",
     "name": "Module 2: operator timing + content drift", "metrics_from": "module2",
     "approach": "Module 1 features plus operator-normalised timing and content drift, with "
                 "thresholds re-selected by one fixed rule.",
     "status": "NOT PROMOTED",
     "result": "A small F1 gain over the matched control and slightly lower fragmentation.",
     "failure_mode": "The F1 gain is below the pre-registered minimum.",
     "decision": "Kept as an experimental extension. Module 1 stays canonical."},
]

DAY7_NAMES = {
    "C1_rule_two_threshold": "C1 · two-threshold rule",
    "C2_rule_plus_continuity_veto": "C2 · rule + continuity veto",
    "C3_rule_plus_motif": "C3 · rule + motif",
    "C4_instrumentation_aware": "C4 · instrumentation-aware rule",
}


DAY7_GATE_WORDS = {
    "f1_gain_at_least_0.02": "F1 gain",
    "recall_at_least_0.55": "recall",
    "fragmentation_within_cap": "fragmentation cap",
    "under_segmentation_within_cap": "under-segmentation cap",
    "over_segmentation_within_cap": "over-segmentation cap",
    "degraded_sessions_within_cap": "sessions made worse",
    "gain_survives_removing_top3": "gain not concentrated",
}


def _day2(src: dict) -> dict:
    """Day-2 reconstruction record plus the Day-6 / Day-7 challenges to it, verbatim."""
    protected = src["dataset_a_metrics"]
    systems = protected["systems"]
    baselines = src["day2_baselines"]
    at_tau = baselines["baseline_comparison_at_best_tau"]
    learned = src["day2_learned"]
    ensemble = src["day6_ensemble"]
    seg7 = src["day7_segmentation"]

    record = {
        "problem": {
            "n_sessions": protected["n_sessions"],
            "n_transitions": at_tau["baseline1_temporal_only"]["n_transitions"],
            "n_gt_boundaries": at_tau["baseline1_temporal_only"]["n_gt_boundaries"],
            "n_gt_executions": systems["Strategy_Combined"]["pooled"]["n_gt_executions_total"],
        },
        "locked_strategy": "Strategy_Combined",
        "systems": {name: _pooled(s["pooled"]) for name, s in systems.items()},
        "protection": {
            name: {
                "false_to_true_protection_ratio":
                    protected["rule_level_analysis"][name]["false_to_true_protection_ratio"],
                "gates_total": len(protected["success_gate"][name]),
                "gates_failed": [gate for gate, v in protected["success_gate"][name].items()
                                 if not v.get("pass")],
            }
            for name in ("Strategy_Agreement", "Strategy_Tempo", "Strategy_Combined")
        },
        "temporal_baselines": {
            "tau_ms": baselines["best_tau_ms"],
            "temporal_only": _pooled(at_tau["baseline1_temporal_only"]),
            "temporal_and_context": _pooled(at_tau["baseline2_temporal_and_context"]),
            "temporal_or_context": _pooled(at_tau["baseline3_temporal_or_context"]),
            "temporal_or_context_predicted": at_tau["baseline3_temporal_or_context"]["n_predicted"],
        },
        "learned_classifier": {
            "n_features": learned["n_features"],
            "threshold": learned["best_threshold"],
            "precision": learned["pooled_boundary_metrics"]["precision"],
            "recall": learned["pooled_boundary_metrics"]["recall"],
            "f1": learned["pooled_boundary_metrics"]["f1"],
        },
        # Only the boundary-first sweep: it is scored on the same full-session basis as
        # every system above. The continuity-first sweep was scored on labelled
        # transitions only, so it is deliberately not carried into the same chart.
        "v1_threshold_curve": [
            {"threshold": pt["threshold"], **_pooled(pt)}
            for pt in src["day2_threshold_tradeoff"]["v1_curve"]
        ],
        "day6": {
            "hmm_only": _pooled(ensemble["systems"]["hmm_only"]),
            "ensemble_or": _pooled(ensemble["systems"]["ensemble_OR_either_flags"]),
            "ensemble_and": _pooled(ensemble["systems"]["ensemble_AND_both_must_agree"]),
            "complementarity": ensemble["complementarity"],
            "locked_reproduced_f1": ensemble["reproduction_check"]["locked_pooled"]["f1"],
        },
        "day7": {
            "question": seg7["question"],
            "validation": seg7["validation"],
            "decision": seg7["decision"],
            "baseline_reproduced": seg7["baseline_control"]["reproduced"],
            "gates": seg7["promotion_criteria"]["gates"],
            "candidates": [
                {
                    "id": name,
                    "name": DAY7_NAMES.get(name, name),
                    "method": c["method"],
                    "metrics": _pooled(c["eval"]["pooled"]),
                    "passes_all_gates": c["passes_all_gates"],
                    "failed_gates": [g for g, ok in c["gate_checks"].items() if not ok],
                    "failed_gate_labels": [DAY7_GATE_WORDS.get(g, g)
                                           for g, ok in c["gate_checks"].items() if not ok],
                }
                for name, c in seg7["candidates"].items()
            ],
        },
    }

    module2 = None
    if "module2_segmentation" in src and "module2_gate" in src:
        gate = src["module2_gate"]
        best = gate["best_candidate_by_f1"]
        protocols = src["module2_segmentation"]["feature_sets"]
        module2 = {
            "metrics": _pooled(protocols[best]["protocols"]["matched"]["eval"]["pooled"]),
            "control_f1": protocols["M1_compatible"]["protocols"]["matched"]["eval"]["pooled"]["f1"],
            "f1_gain": gate["candidates"][best]["matched"]["vs_control"]["deltas"]["f1"],
            "required_gain": gate["gate_thresholds"]["min_f1_absolute_gain"],
            "status": gate["module2_status"],
        }

    def metrics_for(ref: str) -> dict | None:
        if ref == "module2":
            return module2["metrics"] if module2 else None
        node: object = record
        for part in ref.split("."):
            node = node[part]  # type: ignore[index]
        return node  # type: ignore[return-value]

    experiments = []
    for exp in EXPERIMENTS:
        if exp["metrics_from"] == "module2" and module2 is None:
            continue
        row = {k: v for k, v in exp.items() if k != "metrics_from"}
        row["metrics"] = metrics_for(exp["metrics_from"])
        row["metrics_source"] = exp["metrics_from"]
        experiments.append(row)
    locked = record["systems"]["Strategy_Combined"]
    for cand in record["day7"]["candidates"]:
        m = cand["metrics"]
        failed = cand["failed_gate_labels"]
        lower_frag = m["pct_gt_executions_fragmented"] < locked["pct_gt_executions_fragmented"]
        merged = m["under_segmentation_rate"] > locked["under_segmentation_rate"]
        experiments.append({
            "id": cand["id"], "day": "Day 7", "stage": "Later challenge",
            "name": cand["name"], "approach": cand["method"],
            "status": "PASSED" if cand["passes_all_gates"] else "REJECTED",
            "result": ("Lower fragmentation than the locked baseline." if lower_frag
                       else "No fragmentation gain over the locked baseline."),
            "failure_mode": (("Fragmentation fell because work was merged. " if lower_frag and merged
                              else "") + "Failed gates: " + ", ".join(failed) + "."
                             if failed else "No gate failed."),
            "decision": ("Rejected by the pre-registered gates; baseline retained."
                         if not cand["passes_all_gates"] else "Passed the registered gates."),
            "metrics": m,
            "metrics_source": f"day7.candidates.{cand['id']}",
        })
    record["experiments"] = experiments
    record["module2"] = module2
    return record


def _machine_labels(*health_files: dict) -> dict[str, str]:
    """Anonymous, stable machine labels. Host names add nothing to the evidence, so the
    investigation view never shows them. Machines are lettered in the order their first
    session was recorded, which does not encode the names themselves."""
    first_seen: dict[str, str] = {}
    for health in health_files:
        for machine, info in health["by_machine"].items():
            earliest = min(info["sessions"])
            if machine not in first_seen or earliest < first_seen[machine]:
                first_seen[machine] = earliest
    ordered = sorted(first_seen, key=lambda m: (first_seen[m], m))
    return {m: f"Machine {chr(ord('A') + i)}" for i, m in enumerate(ordered)}


def _day4(src: dict) -> dict:
    """Day-4 instrumentation diagnostic, verbatim, with host names replaced by labels."""
    health_a, health_b = src["health_a"], src["health_b"]
    labels = _machine_labels(health_a, health_b)
    agreement = {k: v for k, v in health_a["baseline_agreement"].items()
                 if k != "flagged_sessions"}

    def machines(health: dict) -> list[dict]:
        rows = [{"label": labels[m], "sessions": info["n"], "flagged": info["n_degraded"]}
                for m, info in health["by_machine"].items()]
        return sorted(rows, key=lambda r: r["label"])

    return {
        "question": "Can instrumentation health be detected before segmentation?",
        "thresholds": health_a["summary"]["thresholds"],
        "summary": {
            key: {k: h["summary"][k] for k in ("n_sessions", "n_healthy", "n_degraded")}
            for key, h in (("dataset_a", health_a), ("dataset_b", health_b))
        },
        "agreement": agreement,
        "flagged_sessions_a": [
            {"machine": labels[s["machine"]], "coverage": s["coverage"],
             "distinct_domains": s["distinct_domains"], "baseline_f1": s["baseline_f1"],
             "baseline_under_segmentation": s["baseline_under_segmentation"]}
            for s in health_a["baseline_agreement"]["flagged_sessions"]
        ],
        "machines_a": machines(health_a),
        "machines_b": machines(health_b),
        "limitations": [
            "Diagnostic only: it flags sessions, it never changes the canonical segmentation.",
            "Both thresholds were derived on Dataset A; Dataset B has no ground truth to "
            "check them against.",
            "Instrumentation health describes evidence availability, not segmentation quality.",
            "Two poorly segmented Dataset-A sessions were well instrumented, so bad "
            "instrumentation is not the only cause of poor segmentation.",
            "Ground truth was used only to evaluate the diagnostic, never as its input.",
        ],
    }


def _day3(src: dict) -> dict:
    """Operational metrics per process -- the inputs to scoring, not the scores.

    The full-results file holds pre-entropy-fix SCORES, which are never read here. Its
    per-process operational metrics (time share, raw variant entropy, automation
    surface, operator count) are unaffected by that fix, which changed only how
    Feasibility uses the entropy.
    """
    metrics = src["mining_full"]["process_metrics"]
    keep = ("execution_count", "time_share", "frequency_share", "variant_count",
            "dominant_variant_share", "variant_entropy", "automation_surface", "user_count")
    return {
        "process_metrics": {pid: {k: m.get(k) for k in keep} for pid, m in metrics.items()},
        "entropy_note": src["audit"]["entropy_fix"],
    }


def _investigation(root: Path, src: dict) -> dict:
    return {
        "day1": _day1(src),
        "day2": _day2(src),
        "day3": _day3(src),
        "day4": _day4(src),
        "documented": _documented(root),
        "note": "Investigation views for Day 1-4. Totals are copied from the Day-1..Day-7 "
                "artifacts; counts and sums over per-session rows are marked DERIVED in "
                "the adapter; report-only figures carry their source and are checked "
                "against it at build time. Nothing is scored here.",
    }


def operator_of(session_id: str) -> str:
    """DERIVED. Sessions are named ses_<date>-<time>-<machine>; the machine
    segment is the operator. Verified in tests against the `operator` field
    the Dataset-B execution records already carry."""
    parts = session_id.split("-", 2)
    return parts[2] if len(parts) > 2 else "unknown"


def write_json(out_dir: Path, relative: str, payload: object) -> Path:
    """Write one JSON file, refusing any path that escapes `out_dir`."""
    out_dir = out_dir.resolve()
    target = (out_dir / relative).resolve()
    if target != out_dir and out_dir not in target.parents:
        raise ValueError(f"refusing to write outside --out: {relative!r}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def build(root: Path, out_dir: Path) -> dict:
    """`root` is the repository root; every path in SOURCES is relative to it."""
    src = {}
    sizes = {}
    for name, rel in SOURCES.items():
        path = root / rel
        if not path.exists():
            raise SystemExit(f"missing source artifact: {path}")
        src[name] = json.loads(path.read_text(encoding="utf-8"))
        sizes[name] = {"path": str(rel), "bytes": path.stat().st_size}

    for name, rel in INVESTIGATION_SOURCES.items():
        path = root / rel
        if not path.exists():
            raise SystemExit(f"missing source artifact: {path}")
        src[name] = json.loads(path.read_text(encoding="utf-8"))
        sizes[name] = {"path": str(rel), "bytes": path.stat().st_size}

    # Optional Day-6 Module 2 artifacts. Absence is not an error: the bundle must
    # still build for anyone who has not run the experimental module.
    have_module2 = True
    for name, rel in OPTIONAL_SOURCES.items():
        path = root / rel
        if not path.exists():
            have_module2 = False
            continue
        src[name] = json.loads(path.read_text(encoding="utf-8"))
        sizes[name] = {"path": str(rel), "bytes": path.stat().st_size}
    visual = root / VISUAL_REVIEW_SOURCE
    if have_module2 and visual.exists():
        src["module2_visual_review"] = json.loads(visual.read_text(encoding="utf-8"))
        sizes["module2_visual_review"] = {"path": str(VISUAL_REVIEW_SOURCE),
                                          "bytes": visual.stat().st_size}

    written: dict[str, int] = {}

    # --- dataset-a-metrics.json : verbatim locked-baseline numbers --------
    combined = src["dataset_a_metrics"]["systems"]["Strategy_Combined"]
    write_json(out_dir, "dataset-a-metrics.json", {
        "strategy": "Strategy_Combined",
        "pooled": combined["pooled"],
        "per_session": combined["per_session"],
        "note": "Locked Day-2 architecture. Copied verbatim; not recomputed.",
    })
    written["dataset-a-metrics.json"] = len(combined["per_session"])

    # --- executions ------------------------------------------------------
    executions = src["executions"]["executions"]
    profiles = src["profiles"]
    label_by_pid = {pid: p["readable_name"] for pid, p in profiles.items()}

    executions_sorted = sorted(executions, key=lambda e: (e["session_id"], e["start_ms"]))

    index_rows = []
    by_session: dict[str, list] = {}
    for ex in executions_sorted:
        row = {k: v for k, v in ex.items() if k != "ordered_steps"}
        # DERIVED: dict lookup of the already-computed readable name.
        row["process_readable_name"] = label_by_pid.get(
            ex["dominant_context"], ex["dominant_context"]
        )
        index_rows.append(row)
        by_session.setdefault(ex["session_id"], []).append(ex)

    write_json(out_dir, "executions-index.json", index_rows)
    written["executions-index.json"] = len(index_rows)

    for session_id, rows in sorted(by_session.items()):
        if "/" in session_id or "\\" in session_id or session_id.startswith("."):
            raise ValueError(f"unsafe session_id for a filename: {session_id!r}")
        enriched = []
        for ex in rows:
            item = dict(ex)
            item["process_readable_name"] = label_by_pid.get(
                ex["dominant_context"], ex["dominant_context"]
            )
            enriched.append(item)
        write_json(out_dir, f"executions/{session_id}.json", enriched)
    written["executions/"] = len(by_session)

    # --- sessions.json : health joined with execution counts -------------
    exec_count_by_session = {sid: len(rows) for sid, rows in by_session.items()}
    sessions = []
    for dataset_key, health in (("dataset_a", src["health_a"]), ("dataset_b", src["health_b"])):
        for h in health["per_session"]:
            sid = h["session_id"]
            sessions.append({
                "session_id": sid,
                # DERIVED: which health artifact the row came from.
                "dataset": dataset_key,
                # DERIVED: parsed from session_id.
                "operator": operator_of(sid),
                "n_events": h["n_events"],
                "n_events_with_browser_domain": h["n_events_with_browser_domain"],
                "browser_domain_coverage": h["browser_domain_coverage"],
                "n_distinct_browser_domains": h["n_distinct_browser_domains"],
                "status": h["status"],
                "warnings": h["warnings"],
                # DERIVED: counted from the execution artifact. Dataset A has
                # no persisted executions, so this is null there rather than 0.
                "n_executions": exec_count_by_session.get(sid)
                if dataset_key == "dataset_b" else None,
            })
    sessions.sort(key=lambda s: (s["dataset"], s["session_id"]))
    write_json(out_dir, "sessions.json", sessions)
    written["sessions.json"] = len(sessions)

    # --- processes.json : profiles verbatim, as a list -------------------
    process_rows = [dict(p) for p in profiles.values()]
    process_rows.sort(key=lambda p: (-p["execution_count"], p["process_id"]))
    write_json(out_dir, "processes.json", process_rows)
    written["processes.json"] = len(process_rows)

    # --- variants.json : flattened, process_id lifted from the key -------
    variant_rows = []
    for pid, rows in src["variants"].items():
        for v in rows:
            variant_rows.append({
                # DERIVED: the source keys this list by process_id.
                "process_id": pid,
                "readable_name": label_by_pid.get(pid, pid),
                "signature": v["signature"],
                "frequency": v["frequency"],
                "avg_duration_ms": v["avg_duration_ms"],
            })
    variant_rows.sort(key=lambda v: (v["process_id"], -v["frequency"], str(v["signature"])))
    write_json(out_dir, "variants.json", variant_rows)
    written["variants.json"] = len(variant_rows)

    # --- opportunities.json : CANONICAL ranking only ---------------------
    audit = src["audit"]
    robustness_by_pid = {r["process_id"]: r for r in audit["final_ranking_robustness_table"]}
    opportunities = []
    for row in audit["default_ranking"]:
        pid = row["process_id"]
        rb = robustness_by_pid.get(pid, {})
        opportunities.append({
            "rank": row["rank"],
            "process_id": pid,
            "readable_name": row["readable_name"],
            "impact": row["impact"],
            "feasibility": row["feasibility"],
            "opportunity": row["opportunity"],
            "pareto_status": rb.get("pareto_status"),
            "median_rank": rb.get("median_rank"),
            "best_rank": rb.get("best_rank"),
            "worst_rank": rb.get("worst_rank"),
            "rank_range": rb.get("rank_range"),
        })
    write_json(out_dir, "opportunities.json", {
        "canonical_source": str(SOURCES["audit"]),
        "canonical_note": "Post-entropy-fix scores. problem2_process_metrics.json "
                          "and automation_priority_dataset_b.json hold superseded "
                          "values and are deliberately NOT read.",
        "pareto_frontier": audit["pareto_frontier"],
        "sensitivity_summary": audit.get("sensitivity_summary"),
        # Per-scenario detail, copied verbatim from the same canonical audit
        # artifact the ranking itself comes from. Needed by the Decision
        # Center to show WHICH assumptions move the recommendation, rather
        # than only the aggregate "#1 in 5 of 8". No scenario is renamed,
        # reweighted, or recomputed here.
        "sensitivity_scenarios": audit.get("sensitivity_analysis", {}),
        "ranking": opportunities,
    })
    written["opportunities.json"] = len(opportunities)

    # --- instrumentation-sensitivity.json : Day-4 Case A vs Case B -------
    day4 = src["day4_sensitivity"]
    write_json(out_dir, "instrumentation-sensitivity.json", {
        "question": day4["question"],
        "method": day4["method"],
        "no_ground_truth_note": day4["no_ground_truth_note"],
        "excluded_sessions": day4["excluded_sessions"],
        "executions_total": day4["executions_total"],
        "executions_removed": day4["executions_removed"],
        "executions_kept": day4["executions_kept"],
        "top_candidate_case_a": day4["top_candidate_case_a"],
        "top_candidate_case_b": day4["top_candidate_case_b"],
        "top_candidate_unchanged": day4["top_candidate_unchanged"],
        "pareto_case_a": day4["pareto_case_a"],
        "pareto_case_b": day4["pareto_case_b"],
        "sensitivity_summary_case_a": day4["sensitivity_summary_case_a"],
        "sensitivity_summary_case_b": day4["sensitivity_summary_case_b"],
        "ranking_comparison": day4["ranking_comparison"],
        "note": "Day-4 result copied verbatim. Case B re-ran the Day-3 chain "
                "with instrumentation-degraded sessions excluded; only the input "
                "population differed. Nothing is recomputed in the frontend.",
    })
    written["instrumentation-sensitivity.json"] = len(day4["ranking_comparison"])

    # --- engineering-upgrade.json : Day-7 model + browser + boundary ------
    # Every value here is copied from a Day-7 artifact. The frontend must not be
    # able to imply a capability the repository does not actually have, so the
    # status strings are produced here from artifact contents, not typed in React.
    clf = src["day7_classifier"]
    browser = src["day7_browser"]
    seg = src["day7_segmentation"]
    browser_steps = {st["step"]: st for st in browser["steps"]}
    write_json(out_dir, "engineering-upgrade.json", {
        "model": {
            "status": "RESEARCH / VALIDATION SIGNAL — not in the canonical pipeline",
            "task": clf["question"],
            "why_not_circular": clf["why_not_circular"],
            "leakage_control": clf["leakage_control"],
            "n_executions": clf["results"]["behavioural_only"]["random_forest"]["n_test_predictions"],
            "n_classes": clf["n_classes"],
            "behavioural_only_macro_f1": clf["headline"]["behavioural_only_macro_f1"],
            "with_system_identity_macro_f1": clf["headline"]["with_system_identity_macro_f1"],
            "stratified_baseline_macro_f1": clf["results"]["behavioural_only"]["baseline_stratified"]["macro_f1"],
            "identity_uplift": clf["headline"]["identity_uplift"],
            "top_features": clf["results"]["with_system_identity"]["top_features_random_forest"][:5],
            "finding": "Behaviour alone carries real but insufficient process signal; "
                       "system identity roughly doubles macro F1. This confirms the "
                       "Day-3 decision to group on system context.",
            "prohibited_use": "Not the reason for the HR/Payroll selection, and not "
                              "used to relabel Dataset B.",
        },
        "browser": {
            "status": "LOCAL VALIDATED",
            "status_detail": "Browser automation validated against the local HR "
                             "prototype page. NOT connected to a real HR system.",
            "target": browser["target"],
            "not_connected_to_real_hr_system": browser["not_connected_to_real_hr_system"],
            "confirmed": browser_steps.get("valid_route", {}).get("confirmed"),
            "note_reached_dom": browser_steps.get("valid_route", {}).get("note_reached_dom"),
            "replay_refused": browser_steps.get("replay", {}).get("refused"),
            "invalid_route_refused": browser_steps.get("invalid_route", {}).get("refused"),
            "empty_note_refused": browser_steps.get("empty_note", {}).get("refused"),
            "prepare_seconds": browser_steps.get("valid_route", {}).get("prepare_seconds"),
            "confirm_seconds": browser_steps.get("valid_route", {}).get("confirm_seconds"),
            "automation_logic_unchanged": True,
        },
        "production_boundary": {
            "implemented": [
                "Automation API (prepare / confirm) with request and execution ids",
                "Route allowlist and note validation before any UI contact",
                "Mandatory human review checkpoint, held server-side",
                "Confirm-time re-verification of the target element",
                "Single-use tokens — a checkpoint cannot be confirmed twice",
                "Structured audit log with note content and credentials redacted",
                "Error taxonomy with safe stops",
                "Browser adapter driving a real Chromium DOM",
                "Health endpoint",
                "Local HTTP integration: HTTP adapter to a separate local HR API "
                "simulator with SQLite state, idempotent by execution id, "
                "lost responses settled by status lookup (also after a restart)",
            ],
            "requires_production_integration": [
                "Real HR system URL (this targets a local prototype page)",
                "Enterprise authentication and authorisation",
                "Secrets management",
                "Production browser infrastructure",
                "Business-owner confirmation that the confirm click means submit",
                "Governance and security review for payroll data",
                "Reconciliation against the real HR system of record (the local "
                "HTTP target is a simulator)",
                "TLS and service-to-service identity for a real HR API",
            ],
        },
        "segmentation_challenge": _segmentation_challenge(seg),
    })
    written["engineering-upgrade.json"] = 4

    # --- instrumentation.json : Day-4 output verbatim --------------------
    write_json(out_dir, "instrumentation.json", {
        "dataset_a": src["health_a"],
        "dataset_b": src["health_b"],
        "note": "Day-4 diagnostic output copied verbatim. Thresholds and "
                "status are owned by procmine.instrumentation_health.",
    })
    written["instrumentation.json"] = (
        src["health_a"]["summary"]["n_sessions"] + src["health_b"]["summary"]["n_sessions"]
    )

    # --- hr-payroll.json : evidence panel --------------------------------
    hr = src["hr_dominant_path"]
    write_json(out_dir, "hr-payroll.json", {
        "dominant_path": hr,
        "variant_split": hr["variant_split"],
        "dfg": src["mining_full"]["hr_payroll_dfg"],
        "similarity_investigation": src["mining_full"]["hr_payroll_similarity_investigation"],
        "note": "variant_split (dominant / word_detour / rare_edge) is carried "
                "explicitly because it is NOT derivable from variants.json, "
                "which holds generic per-signature variants.",
    })
    written["hr-payroll.json"] = hr["n_hr_executions_total"]

    # --- investigation.json : Day-1..Day-4 investigation views ----------
    # Copies, counts and look-ups only. Report-only figures are checked against the
    # sentence they come from, so this file fails to build rather than drift.
    investigation = _investigation(root, src)
    write_json(out_dir, "investigation.json", investigation)
    written["investigation.json"] = len(investigation["day2"]["experiments"])

    # --- module-comparison.json : Day-6 Module 1 vs Module 2 -------------
    # Emitted only when every Module 2 artifact is present. Values are copied
    # verbatim; the comparison screen performs no arithmetic of its own.
    if have_module2:
        write_json(out_dir, "module-comparison.json", _module_comparison(src))
        written["module-comparison.json"] = len(
            src["module2_segmentation"]["feature_sets"])

    # --- meta.json : provenance. Only file containing a timestamp. -------
    write_json(out_dir, "meta.json", {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generator": "scripts/build_frontend_data.py",
        "canonical_sources": sizes,
        "outputs": written,
        "not_available": [
            "raw per-event streams (dataset_a/ and dataset_b/ are gitignored; "
            "the finest persisted grain is executions[].ordered_steps)",
            "Dataset-A PREDICTED execution boundaries (never serialised by the "
            "locked pipeline; only aggregate and per-session metrics exist)",
            "directly-follows graphs for the 20 non-HR processes (computed "
            "in-memory by the Day-3 script but not persisted)",
        ],
    })

    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--root", type=Path, default=REPO_ROOT,
                        help="repository root that SOURCES paths resolve against")
    args = parser.parse_args()

    written = build(args.root, args.out)
    for name, count in sorted(written.items()):
        print(f"  {name:26s} {count}", file=sys.stderr)
    print(f"Wrote frontend data bundle to {args.out}", file=sys.stderr)
    print("Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
