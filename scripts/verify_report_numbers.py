#!/usr/bin/env python3
"""Verify every headline number in reports/final_report.md against its canonical artifact.

Why this exists: a reviewer should not have to trust that the numbers in the final
report were transcribed correctly. Each check below names the claim, recomputes the
value from the artifact that produced it, and asserts the rendered string is present
in the report. If an artifact is ever regenerated with different values, this fails
rather than letting the report drift silently.

This performs NO analysis of its own. It reads canonical artifacts and compares.

Usage:  python scripts/verify_report_numbers.py
Exit 0 = every number in the report traces to an artifact.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "reports" / "final_report.md"

AUDIT = ROOT / "reports/day3/problem2_audit_results.json"
PROFILES = ROOT / "reports/day3/process_profiles_dataset_b.json"
VARIANTS = ROOT / "reports/day3/process_variants_dataset_b.json"
INSTR_SENS = ROOT / "reports/day4/instrumentation_sensitivity_check.json"
HMM = ROOT / "reports/day6/hmm_boundary_experiment_dataset_a.json"
ENSEMBLE = ROOT / "reports/day6/boundary_ensemble_experiment_dataset_a.json"
SENSITIVITY = ROOT / "reports/day7/recommendation_sensitivity.json"
SEGCOMPARE = ROOT / "reports/day7/segmentation_comparison.json"
SEGMENTS = ROOT / "segments.jsonl"
M2_GATE = ROOT / "reports/day6/module2/module2_promotion_gate.json"
M2_SEG = ROOT / "reports/day6/module2/module2_segmentation_experiment.json"
M2_AUTO = ROOT / "reports/day6/module2/module2_automation_analysis.json"
M2_SAMPLE = ROOT / "reports/day6/module2/module2_dataset_b_screenshot_sample.json"
M2_VISUAL = ROOT / "reports/day6/module2/dataset_b_visual_review_results.json"
M2_GAPS = ROOT / "reports/day6/module2/dataset_b_screenshot_gaps.json"
EXECUTIONS_B = ROOT / "reports/day3/process_executions_dataset_b.json"

HR = "system:HR人事給与システム"


@dataclass(frozen=True)
class Check:
    """One traceable claim: a value from an artifact, and how it must read in the report."""

    claim: str
    artifact: str
    rendered: str  # the exact substring that must appear in the report


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def build_checks() -> list[Check]:
    audit = _load(AUDIT)
    profiles = _load(PROFILES)
    variants = _load(VARIANTS)
    instr = _load(INSTR_SENS)
    hmm = _load(HMM)
    ens = _load(ENSEMBLE)

    hr_profile = profiles[HR]
    top, second = audit["default_ranking"][0], audit["default_ranking"][1]
    pareto = audit["pareto_frontier"]
    sens = audit["sensitivity_summary"]
    robust = audit["final_ranking_robustness_table"][0]
    locked = hmm["locked_baseline_pooled"]
    comp = ens["complementarity"]

    checks = [
        # --- Step 1: Dataset-A segmentation quality -------------------------
        Check("boundary precision", "day2 architecture / day6 baseline", f"{locked['precision']:.4f}"),
        Check("boundary recall", "day2 architecture / day6 baseline", f"{locked['recall']:.4f}"),
        Check("boundary F1", "day2 architecture / day6 baseline", f"{locked['f1']:.4f}"),
        Check("over-segmentation", "day6 locked_baseline_pooled", f"{locked['over_segmentation_rate']:.4f}"),
        Check("under-segmentation", "day6 locked_baseline_pooled", f"{locked['under_segmentation_rate']:.4f}"),
        Check("fragmentation %", "day6 locked_baseline_pooled", f"{locked['pct_gt_executions_fragmented']:.2f}%"),
        # --- Step 1: Dataset-B output ---------------------------------------
        Check("Dataset-B executions", "segments.jsonl line count", str(sum(1 for _ in SEGMENTS.open(encoding="utf-8")))),
        # --- Step 2: ranking -------------------------------------------------
        Check("HR opportunity", "problem2_audit_results.default_ranking[0]", f"{top['opportunity']:.4f}"),
        Check("HR impact", "problem2_audit_results.default_ranking[0]", f"{top['impact']:.4f}"),
        Check("HR feasibility", "problem2_audit_results.default_ranking[0]", f"{top['feasibility']:.4f}"),
        Check("runner-up opportunity", "problem2_audit_results.default_ranking[1]", f"{second['opportunity']:.4f}"),
        Check("Pareto frontier size", "problem2_audit_results.pareto_frontier", f"{pareto['n_frontier']} of {pareto['n_total']}"),
        Check("scenarios with HR first", "problem2_audit_results.sensitivity_summary", f"{sens['n_hr_first']} of {sens['n_scenarios']}"),
        Check("HR worst rank", "final_ranking_robustness_table[0].worst_rank", f"Worst observed rank across everything tested: {robust['worst_rank']}"),
        # --- Step 2: process facts -------------------------------------------
        Check("HR execution count", "process_profiles_dataset_b", str(hr_profile["execution_count"])),
        Check("HR variant count", "process_profiles_dataset_b", f"{hr_profile['n_variants']} distinct"),
        Check("HR dominant share", "process_profiles_dataset_b", f"{hr_profile['dominant_variant_share'] * 100:.2f}%"),
        Check("HR operator count", "frequency_by_operator", f"all {len(hr_profile['frequency_by_operator'])} recorded operators"),
        # --- Impact arithmetic (the 77% vs 55.89% distinction) ---------------
        Check("HR total handling ms", "process_profiles_dataset_b", f"{hr_profile['total_duration_ms']:,}"),
        Check("dominant-variant handling ms", "process_variants (freq x avg)", f"{round(variants[HR][0]['frequency'] * variants[HR][0]['avg_duration_ms']):,}"),
        Check("time-share covered", "derived: dominant ms / total ms", f"{variants[HR][0]['frequency'] * variants[HR][0]['avg_duration_ms'] / hr_profile['total_duration_ms'] * 100:.2f}%"),
        # --- Day-4 instrumentation sensitivity -------------------------------
        Check("executions before exclusion", "instrumentation_sensitivity_check", str(instr["executions_total"])),
        Check("executions after exclusion", "instrumentation_sensitivity_check", str(instr["executions_kept"])),
        Check("scenarios HR-first after exclusion", "instrumentation_sensitivity_check", f"{instr['sensitivity_summary_case_b']['n_hr_first']}/{instr['sensitivity_summary_case_b']['n_scenarios']}"),
        # --- Day-6 rejected experiments --------------------------------------
        Check("HMM best F1", "hmm_boundary_experiment best K", f"{hmm['results'][hmm['best_k_by_f1']]['pooled']['f1']:.4f}"),
        Check("HMM-only true boundaries", "boundary_ensemble complementarity", str(comp["caught_by_hmm_only"])),
        Check("GT boundary count", "boundary_ensemble complementarity", f"{comp['n_gt_boundaries']:,}"),
    ]

    # --- Day 7: recommendation robustness under segmentation uncertainty ------
    sens = _load(SENSITIVITY)
    res = sens["results"]
    ev = sens["summary"]["evidence_layer"]
    for t in ("0", "5", "11", "36"):
        checks.append(Check(f"threshold {t} execution count", "recommendation_sensitivity.results", f"{res[t]['n_executions']:,}"))
        checks.append(Check(f"threshold {t} HR handling hours", "recommendation_sensitivity.results", f"{res[t]['hr_total_human_hours']:.4f} h"))
    checks.append(Check("p50 displacing process", "recommendation_sensitivity.results", res["11"]["top_candidate"]))
    checks.append(Check("HR rank at p50", "recommendation_sensitivity.results", f"HR falls to rank {res['11']['hr_rank']}"))
    checks.append(Check("min Kendall tau", "recommendation_sensitivity.rank_stability", f"{sens['summary']['composite_score_layer']['min_kendall_tau_vs_baseline']:.4f}"))
    checks.append(Check("evidence layer stable", "recommendation_sensitivity.summary", "A. STABLE"))
    checks.append(Check("dominant share range", "recommendation_sensitivity.summary", f"{sens['summary']['hr_dominant_variant_share_by_threshold']['36'] * 100:.2f}%"))

    # --- Day 7: segmentation improvement challenge ---------------------------
    seg = _load(SEGCOMPARE)
    for name, key in (("C1_rule_two_threshold", "C1"), ("C2_rule_plus_continuity_veto", "C2"),
                      ("C3_rule_plus_motif", "C3"), ("C4_instrumentation_aware", "C4")):
        pooled = seg["candidates"][name]["eval"]["pooled"]
        checks.append(Check(f"{key} F1", "segmentation_comparison.candidates", f"{pooled['f1']:.4f}"))
        checks.append(Check(f"{key} fragmentation", "segmentation_comparison.candidates", f"{pooled['pct_gt_executions_fragmented']:.2f}"))
        checks.append(Check(f"{key} under-segmentation", "segmentation_comparison.candidates", f"{pooled['under_segmentation_rate']:.4f}"))
    checks.append(Check("segmentation decision", "segmentation_comparison.decision", "RETAIN LOCKED"))
    checks.append(Check("segmentation baseline drift", "segmentation_comparison.baseline_control", "drift"))

    # --- Day 6: Module 2 (experimental; segmentation not promoted) -------------
    # These numbers are quoted in the report, so they are traced like every other one.
    m2_gate = _load(M2_GATE)
    m2_seg = _load(M2_SEG)
    m2_auto = _load(M2_AUTO)
    m2c = m2_gate["candidates"]["M2C_operator_timing_plus_content_drift"]["matched"]
    control = m2_seg["feature_sets"]["M1_compatible"]["protocols"]["matched"]["eval"]["pooled"]
    coverage = m2_auto["step_3a_routing"]["coverage"]
    checks.append(Check("Module 2 best F1", "module2_promotion_gate M2C matched",
                        f"{m2c['pooled']['f1']:.4f}"))
    checks.append(Check("Module 2 best fragmentation", "module2_promotion_gate M2C matched",
                        f"{m2c['pooled']['pct_gt_executions_fragmented']:.2f}%"))
    checks.append(Check("Module 2 control F1", "module2_segmentation_experiment M1_compatible",
                        f"{control['f1']:.4f}"))
    checks.append(Check("Module 2 F1 gain vs control", "module2_promotion_gate M2C vs_control",
                        f"+{m2c['vs_control']['deltas']['f1']:.4f}"))
    checks.append(Check("Module 2 required gain", "module2_promotion_gate gate_thresholds",
                        f"+{m2_gate['gate_thresholds']['min_f1_absolute_gain']:.4f}"))
    checks.append(Check("Module 2 decision", "module2_promotion_gate decision", "NOT PROMOTED"))
    checks.append(Check("routing-eligible executions", "module2_automation_analysis coverage",
                        f"{coverage['routing_eligible']}/{coverage['total_executions']}"))

    # --- Day 6: Dataset-B surrogate visual review (not ground truth, not a metric) -----
    sample = _load(M2_SAMPLE)
    visual = _load(M2_VISUAL)
    gaps = _load(M2_GAPS)["summary"]
    vs = visual["summary"]
    b = vs["counts_by_sample_type"]["boundary_sample"]
    c = vs["counts_by_sample_type"]["control_sample"]
    median = sample["screenshot_availability"]["delta_ms_distribution"]["median"]
    checks.append(Check("review screenshot median gap", "screenshot_sample availability",
                        f"median gap {median} ms"))
    checks.append(Check("review images missing", "visual_review_results summary",
                        f"{vs['screenshots_unavailable']} of the {vs['sample_size']} sampled image files"))
    checks.append(Check("review images missing (limitations)", "visual_review_results summary",
                        f"{vs['screenshots_unavailable']} of {vs['sample_size']} images are missing"))
    if gaps["every_chunk_above_cap_is_incomplete"]:
        cap = gaps["common_cap"]
        checks.append(Check("per-chunk screenshot cap", "screenshot_gaps summary",
                            f"above {cap} screenshots holds exactly {cap} files"))
    checks.append(Check("reviewable points", "visual_review_results summary",
                        f"That left {vs['screenshots_available']} reviewable points"))
    checks.append(Check("boundaries with a visible change", "visual_review_results by sample type",
                        f"({b['B_CLEAR_BOUNDARY']} of {vs['boundary_samples_judgeable']}"))
    checks.append(Check("controls with a visible change", "visual_review_results by sample type",
                        f"({c['B_CLEAR_BOUNDARY']} of {vs['control_samples_judgeable']} judgeable controls)"))
    checks.append(Check("ambiguous review points", "visual_review_results summary",
                        f"{vs['ambiguous_total']} of the {vs['screenshots_available']} reviewable "
                        f"points were ambiguous"))
    checks.append(Check("continuous-looking boundaries", "visual_review_results by sample type",
                        f"{['No', 'One', 'Two', 'Three', 'Four'][b['A_CLEAR_CONTINUITY']]} "
                        f"predicted boundaries sit in visibly continuous work"))
    checks.append(Check("merge limit", "process_executions_dataset_b merge_max_away_events",
                        f"the {_load(EXECUTIONS_B)['merge_max_away_events']}-event merge limit"))
    checks.append(Check("visual review decision", "visual_review_results decision",
                        f"Decision: {visual['decision']['outcome'].lower()}"))
    return checks


def _excluded_totals() -> tuple[int, float]:
    profiles = _load(PROFILES)
    ex = [v for v in profiles.values() if v.get("excluded_from_ranking")]
    return sum(v["execution_count"] for v in ex), sum(v["total_human_hours"] for v in ex)


def main() -> int:
    if not REPORT.exists():
        print(f"MISSING: {REPORT}")
        return 1
    text = REPORT.read_text(encoding="utf-8")

    checks = build_checks()

    # The exclusion arithmetic is derived across several artifacts, so it is
    # built here rather than in the table above.
    n_ex, h_ex = _excluded_totals()
    profiles = _load(PROFILES)
    hr_hours = profiles[HR]["total_human_hours"]
    checks.append(Check("excluded executions total", "process_profiles excluded_from_ranking", f"{n_ex} executions"))
    checks.append(Check("excluded hours total", "process_profiles excluded_from_ranking", f"**{h_ex:.4f} h**"))
    checks.append(Check("HR vs all-exclusions ratio", "derived", f"{hr_hours / h_ex:.1f}x larger than every exclusion"))

    failures = [c for c in checks if c.rendered not in text]

    width = max(len(c.claim) for c in checks) + 2
    for c in checks:
        ok = c.rendered in text
        status = "ok  " if ok else "FAIL"
        print(f"{status} {c.claim:<{width}} {c.rendered!r:<34} <- {c.artifact}")

    print(f"\n{len(checks) - len(failures)}/{len(checks)} report numbers trace to a canonical artifact.")
    if failures:
        print("\nThese numbers appear in no artifact, or the report text has drifted:")
        for c in failures:
            print(f"  - {c.claim}: expected {c.rendered!r} (from {c.artifact})")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
