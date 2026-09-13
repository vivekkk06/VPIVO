#!/usr/bin/env python3
"""Problem 2 final audit: redundancy-robustness comparison, Pareto
analysis, expanded sensitivity analysis (8 named scenarios), ablation
analysis, and outlier/winsorization robustness -- run against Dataset
B's real 21-candidate-process population.

Reads the existing Day-3 artifacts unchanged
(`process_profiles_dataset_b.json`, `process_variants_dataset_b.json`,
`process_executions_dataset_b.json`); this script is pure downstream
audit analysis, not a rebuild of anything upstream. Does not touch
Dataset A's locked segmentation architecture and does not modify any
prior Day-3 artifact.

Usage:
    python scripts/audit_problem2_process_mining.py --day3-dir reports/day3 --out reports/day3
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from procmine.process_discovery.opportunity_scoring import (
    ImpactFeasibilityInputs,
    automation_surface,
    compute_feasibility_scores,
    compute_impact_scores,
    compute_opportunity_scores,
    normalized_variant_entropy,
    rank_processes,
    variant_entropy,
)
from procmine.process_discovery.prioritization import min_max_normalize
from procmine.process_discovery.robustness_analysis import (
    kendall_tau,
    pareto_frontier,
    ranks_from_scores,
    spearman_rank_correlation,
    winsorize,
)

HR_PID = "system:HR人事給与システム"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day3-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    profiles = load_json(args.day3_dir / "process_profiles_dataset_b.json")
    variants = load_json(args.day3_dir / "process_variants_dataset_b.json")
    executions_data = load_json(args.day3_dir / "process_executions_dataset_b.json")

    candidate_pids = [pid for pid, p in profiles.items() if not p["excluded_from_ranking"]]
    print(f"{len(candidate_pids)} candidate processes", file=sys.stderr)

    total_exec = sum(profiles[pid]["execution_count"] for pid in candidate_pids)
    total_time = sum(profiles[pid]["total_duration_ms"] for pid in candidate_pids)

    # === build raw per-process quantities (all directly from existing artifacts) ===
    raw = {}
    for pid in candidate_pids:
        p = profiles[pid]
        freqs = [v["frequency"] for v in variants[pid]]
        raw[pid] = {
            "frequency_share": p["execution_count"] / total_exec,
            "time_share": p["total_duration_ms"] / total_time,
            "average_duration_ms": p["total_duration_ms"] / p["execution_count"],
            "manual_involvement": p["avg_manual_event_share"],
            "dominant_variant_share": p["dominant_variant_share"],
            "raw_entropy": variant_entropy(freqs),
            "normalized_entropy": normalized_variant_entropy(freqs),
            "automation_surface": automation_surface(p["dominant_variant_share"], p["avg_manual_event_share"]),
            "complexity_risk": p["avg_systems_touched_per_execution"] + p["n_distinct_interaction_categories"],
        }

    def build_inputs(freq_field, time_field) -> dict[str, ImpactFeasibilityInputs]:
        return {
            pid: ImpactFeasibilityInputs(
                frequency_share=raw[pid][freq_field], time_share=raw[pid][time_field],
                manual_involvement=raw[pid]["manual_involvement"],
                dominant_variant_share=raw[pid]["dominant_variant_share"],
                variant_entropy_value=raw[pid]["normalized_entropy"],  # the audit fix: normalized, not raw
                automation_surface_value=raw[pid]["automation_surface"],
                complexity_risk=raw[pid]["complexity_risk"],
            )
            for pid in candidate_pids
        }

    # === default (fixed) run, using NORMALIZED entropy per the audit fix ===
    default_inputs = build_inputs("frequency_share", "time_share")
    default_impact = compute_impact_scores(default_inputs)
    default_feasibility = compute_feasibility_scores(default_inputs)
    default_opportunity = compute_opportunity_scores(default_impact, default_feasibility)
    default_ranked = rank_processes(default_opportunity)
    default_ranks = ranks_from_scores(default_opportunity)

    print("\n--- Default ranking (normalized-entropy fix applied) ---", file=sys.stderr)
    for i, pid in enumerate(default_ranked[:10], 1):
        print(f"  {i}. {profiles[pid]['readable_name']:<45} Impact={default_impact[pid]:.3f} "
              f"Feasibility={default_feasibility[pid]:.3f} Opportunity={default_opportunity[pid]:.3f}", file=sys.stderr)
    print(f"HR/Payroll rank: {default_ranks[HR_PID]}", file=sys.stderr)

    # === Section 6: redundancy-robustness comparison ===
    def normalized_field(field):
        return min_max_normalize({pid: raw[pid][field] for pid in candidate_pids})

    freq_n, time_n, avgdur_n, manual_n = (normalized_field(f) for f in
                                           ["frequency_share", "time_share", "average_duration_ms", "manual_involvement"])

    def impact_from_components(components: list[dict[str, float]]) -> dict[str, float]:
        return {pid: sum(c[pid] for c in components) / len(components) for pid in candidate_pids}

    redundancy_variants = {
        "A_frequency_plus_total_duration": impact_from_components([freq_n, time_n, manual_n]),
        "B_frequency_plus_average_duration": impact_from_components([freq_n, avgdur_n, manual_n]),
        "C_total_duration_plus_average_duration": impact_from_components([time_n, avgdur_n, manual_n]),
        # D: genuinely non-redundant -- since total_duration ~= frequency
        # * average_duration (r=0.977 measured), including BOTH frequency
        # and total_duration (as in A) double-counts the same volume
        # signal twice. D drops total_duration entirely and uses only
        # frequency (a count, i.e. volume) + manual_involvement (a rate,
        # i.e. intensity) -- two dimensions that are NOT algebraically
        # related to each other, unlike frequency and total duration.
        "D_frequency_and_manual_only_nonredundant": impact_from_components([freq_n, manual_n]),
    }

    print("\n--- Section 6: redundancy-robustness comparison ---", file=sys.stderr)
    redundancy_results = {}
    for name, impact_variant in redundancy_variants.items():
        feas = default_feasibility  # feasibility untouched -- only Impact's volume components vary
        opp = compute_opportunity_scores(impact_variant, feas)
        ranked = rank_processes(opp)
        ranks = ranks_from_scores(opp)
        rho = spearman_rank_correlation(default_ranks, ranks)
        redundancy_results[name] = {
            "top5": [profiles[pid]["readable_name"] for pid in ranked[:5]],
            "hr_rank": ranks[HR_PID], "spearman_vs_default": round(rho, 4),
            "top_candidate_changed": ranked[0] != default_ranked[0],
        }
        print(f"  {name:<50} HR_rank={ranks[HR_PID]} top1={profiles[ranked[0]]['readable_name']} "
              f"spearman_vs_default={rho:.4f}", file=sys.stderr)

    # === Section 7: Pareto analysis ===
    points = {pid: (default_impact[pid], default_feasibility[pid]) for pid in candidate_pids}
    frontier = pareto_frontier(points)
    print(f"\n--- Section 7: Pareto frontier ({len(frontier)}/{len(candidate_pids)} processes) ---", file=sys.stderr)
    for pid in sorted(frontier, key=lambda p: -default_opportunity[p]):
        print(f"  {profiles[pid]['readable_name']:<45} Impact={default_impact[pid]:.3f} Feasibility={default_feasibility[pid]:.3f}", file=sys.stderr)
    hr_on_frontier = HR_PID in frontier
    print(f"HR/Payroll on Pareto frontier: {hr_on_frontier}", file=sys.stderr)
    if not hr_on_frontier:
        dominators = [pid for pid in candidate_pids if pid != HR_PID
                      and default_impact[pid] >= default_impact[HR_PID] and default_feasibility[pid] >= default_feasibility[HR_PID]
                      and (default_impact[pid] > default_impact[HR_PID] or default_feasibility[pid] > default_feasibility[HR_PID])]
        print(f"HR/Payroll is dominated by: {[profiles[p]['readable_name'] for p in dominators]}", file=sys.stderr)

    # === Section 8: sensitivity analysis, 8 named scenarios ===
    impact_scenarios = {
        "balanced": {"frequency": 1.0, "time": 1.0, "manual": 1.0},
        "frequency_heavy": {"frequency": 3.0, "time": 1.0, "manual": 1.0},
        "time_heavy": {"frequency": 1.0, "time": 3.0, "manual": 1.0},
        "manual_effort_heavy": {"frequency": 1.0, "time": 1.0, "manual": 3.0},
        "volume_deemphasized": {"frequency": 0.3, "time": 0.3, "manual": 3.0},
        # correlation-aware: since frequency_share and time_share correlate
        # at r=0.977 (measured previously), weight them as if they were
        # ONE combined volume signal (0.5 each, summing to the same total
        # weight as one un-split factor) rather than double-counting a
        # near-collinear pair at full weight each.
        "correlation_aware": {"frequency": 0.5, "time": 0.5, "manual": 1.0},
    }
    feasibility_scenarios = {
        "balanced": {"determinism": 1.0, "stability": 1.0, "surface": 1.0, "risk": 1.0},
        "feasibility_heavy": {"determinism": 2.0, "stability": 2.0, "surface": 2.0, "risk": 1.0},
        "risk_averse": {"determinism": 3.0, "stability": 1.0, "surface": 1.0, "risk": 3.0},
    }
    sensitivity = {}
    for iname, iw in impact_scenarios.items():
        for fname, fw in feasibility_scenarios.items():
            if iname != "balanced" and fname != "balanced":
                continue  # vary one axis at a time -- 6 impact x 1 + 1 x 3 feasibility = 8 named scenarios total, not a full 6x3 grid
            imp = compute_impact_scores(default_inputs, weights=iw)
            fea = compute_feasibility_scores(default_inputs, weights=fw)
            opp = compute_opportunity_scores(imp, fea)
            ranked = rank_processes(opp)
            ranks = ranks_from_scores(opp)
            rho = spearman_rank_correlation(default_ranks, ranks)
            scenario_name = iname if fname == "balanced" else f"feasibility_{fname}"
            sensitivity[scenario_name] = {
                "hr_rank": ranks[HR_PID], "top5": [profiles[pid]["readable_name"] for pid in ranked[:5]],
                "spearman_vs_default": round(rho, 4), "top_candidate_changed": ranked[0] != default_ranked[0],
                "_ranks": ranks,
            }
    print(f"\n--- Section 8: sensitivity analysis ({len(sensitivity)} named scenarios) ---", file=sys.stderr)
    for name, r in sensitivity.items():
        print(f"  {name:<25} HR_rank={r['hr_rank']} spearman={r['spearman_vs_default']} top1={r['top5'][0]}", file=sys.stderr)
    n_hr_first = sum(1 for r in sensitivity.values() if r["hr_rank"] == 1)
    kendall_values = [kendall_tau(default_ranks, r["_ranks"]) for r in sensitivity.values()]
    print(f"HR #1 in {n_hr_first}/{len(sensitivity)} named scenarios; "
          f"mean Kendall tau vs default = {sum(kendall_values)/len(kendall_values):.4f}", file=sys.stderr)

    # === Section 9: ablation analysis ===
    ablation_components = {
        "frequency": ("impact", "frequency"), "time": ("impact", "time"), "manual_effort": ("impact", "manual"),
        "variant_concentration": ("feasibility", "determinism"), "entropy": ("feasibility", "stability"),
        "automation_surface": ("feasibility", "surface"), "risk": ("feasibility", "risk"),
    }
    ablation_results = {}
    for comp_name, (dimension, weight_key) in ablation_components.items():
        if dimension == "impact":
            iw = {"frequency": 1.0, "time": 1.0, "manual": 1.0}
            iw[weight_key] = 0.0
            imp = compute_impact_scores(default_inputs, weights=iw)
            fea = default_feasibility
        else:
            fw = {"determinism": 1.0, "stability": 1.0, "surface": 1.0, "risk": 1.0}
            fw[weight_key] = 0.0
            imp = default_impact
            fea = compute_feasibility_scores(default_inputs, weights=fw)
        opp = compute_opportunity_scores(imp, fea)
        ranked = rank_processes(opp)
        ranks = ranks_from_scores(opp)
        rho = spearman_rank_correlation(default_ranks, ranks)
        ablation_results[comp_name] = {
            "hr_rank": ranks[HR_PID], "top_candidate": profiles[ranked[0]]["readable_name"],
            "top_candidate_changed": ranked[0] != default_ranked[0], "spearman_vs_full_model": round(rho, 4),
        }
    print(f"\n--- Section 9: ablation (leave-one-component-out) ---", file=sys.stderr)
    for name, r in ablation_results.items():
        print(f"  remove {name:<22} HR_rank={r['hr_rank']} top1={r['top_candidate']} "
              f"changed={r['top_candidate_changed']} spearman={r['spearman_vs_full_model']}", file=sys.stderr)

    # === Section 16: outlier robustness ===
    print(f"\n--- Section 16: outlier robustness (winsorization, limit=0.1) ---", file=sys.stderr)
    winsorized_raw = {
        field: winsorize({pid: raw[pid][field] for pid in candidate_pids}, limit=0.1)
        for field in ["frequency_share", "time_share", "manual_involvement"]
    }
    wfreq_n = min_max_normalize(winsorized_raw["frequency_share"])
    wtime_n = min_max_normalize(winsorized_raw["time_share"])
    wmanual_n = min_max_normalize(winsorized_raw["manual_involvement"])
    w_impact = impact_from_components([wfreq_n, wtime_n, wmanual_n])
    w_opp = compute_opportunity_scores(w_impact, default_feasibility)
    w_ranked = rank_processes(w_opp)
    w_ranks = ranks_from_scores(w_opp)
    w_rho = spearman_rank_correlation(default_ranks, w_ranks)
    print(f"  Winsorized HR_rank={w_ranks[HR_PID]} (default={default_ranks[HR_PID]}) "
          f"top1={profiles[w_ranked[0]]['readable_name']} spearman_vs_default={w_rho:.4f}", file=sys.stderr)

    # === Section 17: final ranking robustness table ===
    all_scenario_ranks = [r["_ranks"] for r in sensitivity.values()]
    robustness_table = []
    for pid in candidate_pids:
        ranks_here = [default_ranks[pid]] + [r[pid] for r in all_scenario_ranks]
        robustness_table.append({
            "process_id": pid, "readable_name": profiles[pid]["readable_name"],
            "default_rank": default_ranks[pid],
            "median_rank": sorted(ranks_here)[len(ranks_here) // 2],
            "best_rank": min(ranks_here), "worst_rank": max(ranks_here),
            "rank_range": max(ranks_here) - min(ranks_here),
            "pareto_status": "frontier" if pid in frontier else "dominated",
        })
    robustness_table.sort(key=lambda r: r["default_rank"])
    print(f"\n--- Section 17: final ranking robustness (top 8) ---", file=sys.stderr)
    for r in robustness_table[:8]:
        print(f"  {r['readable_name']:<45} default={r['default_rank']} median={r['median_rank']} "
              f"best={r['best_rank']} worst={r['worst_rank']} range={r['rank_range']} pareto={r['pareto_status']}", file=sys.stderr)

    out = {
        "entropy_fix": "feasibility now uses normalized_variant_entropy (H/H_max), not raw entropy -- see opportunity_scoring.py",
        "default_ranking": [{"rank": i + 1, "process_id": pid, "readable_name": profiles[pid]["readable_name"],
                              "impact": round(default_impact[pid], 4), "feasibility": round(default_feasibility[pid], 4),
                              "opportunity": round(default_opportunity[pid], 4)} for i, pid in enumerate(default_ranked)],
        "redundancy_robustness_comparison": redundancy_results,
        "pareto_frontier": {"processes": sorted(profiles[pid]["readable_name"] for pid in frontier),
                             "n_frontier": len(frontier), "n_total": len(candidate_pids), "hr_on_frontier": hr_on_frontier},
        "sensitivity_analysis": {k: {kk: vv for kk, vv in v.items() if kk != "_ranks"} for k, v in sensitivity.items()},
        "sensitivity_summary": {"n_scenarios": len(sensitivity), "n_hr_first": n_hr_first,
                                 "mean_kendall_tau_vs_default": round(sum(kendall_values) / len(kendall_values), 4)},
        "ablation_analysis": ablation_results,
        "outlier_robustness": {"winsorized_hr_rank": w_ranks[HR_PID], "default_hr_rank": default_ranks[HR_PID],
                                "spearman_vs_default": round(w_rho, 4), "top_candidate_changed": w_ranked[0] != default_ranked[0]},
        "final_ranking_robustness_table": robustness_table,
    }
    out_path = args.out / "problem2_audit_results.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nWrote {out_path}", file=sys.stderr)
    print("Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
