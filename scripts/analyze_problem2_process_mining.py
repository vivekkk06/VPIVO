#!/usr/bin/env python3
"""Problem 2 investigation: does a systematic process-mining
methodology (trace abstraction, DFG, variant-similarity, entropy,
separated Impact/Feasibility scoring) improve on the existing Day-3
prioritization approach, tested against Dataset B's actual process
population?

Reads the already-computed Day-3 artifacts
(`process_executions_dataset_b.json`, `process_profiles_dataset_b.json`,
`process_variants_dataset_b.json`, `automation_priority_dataset_b.json`)
rather than recomputing them from raw events -- this script is pure
downstream analysis, reusing exactly what Sections 4-13 of the earlier
Day-3 work already produced and validated. Does not touch Dataset A's
locked segmentation architecture and does not modify any prior Day-3
artifact.

Usage:
    python scripts/analyze_problem2_process_mining.py --day3-dir reports/day3 --out reports/day3
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from procmine.process_discovery.directly_follows_graph import build_dfg, self_loops, start_activities
from procmine.process_discovery.opportunity_scoring import (
    ImpactFeasibilityInputs,
    automation_surface,
    compute_feasibility_scores,
    compute_impact_scores,
    compute_opportunity_scores,
    rank_processes,
    variant_entropy,
)
from procmine.process_discovery.sequence_similarity import (
    jaccard_similarity,
    lcs_similarity,
    normalized_levenshtein_similarity,
)
from procmine.process_discovery.trace_representation import activity_level_trace, system_level_trace

HR_PROCESS_ID = "system:HR人事給与システム"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def dist_summary(values):
    if not values:
        return {"n": 0}
    return {"n": len(values), "mean": round(statistics.fmean(values), 4), "median": statistics.median(values)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day3-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    executions_data = load_json(args.day3_dir / "process_executions_dataset_b.json")
    profiles = load_json(args.day3_dir / "process_profiles_dataset_b.json")
    variants = load_json(args.day3_dir / "process_variants_dataset_b.json")
    old_priority = load_json(args.day3_dir / "automation_priority_dataset_b.json")

    executions = executions_data["executions"]
    print(f"Loaded {len(executions)} executions, {len(profiles)} processes", file=sys.stderr)

    # === Section 7: trace representation, built for every execution ===
    by_process_system_traces = defaultdict(list)
    by_process_activity_traces = defaultdict(list)
    for ex in executions:
        pid = ex["dominant_context"]
        by_process_system_traces[pid].append(system_level_trace(ex["ordered_steps"]))
        by_process_activity_traces[pid].append(activity_level_trace(ex["ordered_steps"]))

    avg_sys_len = statistics.fmean(len(t) for ts in by_process_system_traces.values() for t in ts)
    avg_act_len = statistics.fmean(len(t) for ts in by_process_activity_traces.values() for t in ts)
    print(f"Trace length -- SYSTEM_LEVEL avg {avg_sys_len:.2f} tokens, "
          f"ACTIVITY_LEVEL avg {avg_act_len:.2f} tokens", file=sys.stderr)

    # === Section 9: DFG per process (system-level, the more interpretable of the two) ===
    process_dfg = {}
    for pid, traces in by_process_system_traces.items():
        edges = build_dfg(traces)
        process_dfg[pid] = {
            "n_edges": len(edges),
            "top_edges": [e.to_dict() for e in edges[:5]],
            "self_loops": [e.to_dict() for e in self_loops(edges)],
            "start_activities": dict(start_activities(traces)),
        }

    print(f"\n--- HR/Payroll DFG (system-level) ---", file=sys.stderr)
    for e in process_dfg[HR_PROCESS_ID]["top_edges"]:
        print(f"  {e['source']} -> {e['target']}: count={e['count']} P={e['probability']:.3f}", file=sys.stderr)

    # === Section 8: sequence-similarity investigation, HR/Payroll as the validation case ===
    hr_activity_traces = by_process_activity_traces[HR_PROCESS_ID]
    hr_system_traces = by_process_system_traces[HR_PROCESS_ID]
    dominant_idx = [i for i, t in enumerate(hr_system_traces) if t == (HR_PROCESS_ID,)]
    detour_idx = [i for i, t in enumerate(hr_system_traces) if "app:Microsoft Word" in t]
    print(f"\nHR/Payroll: {len(dominant_idx)} dominant-path traces, {len(detour_idx)} word-detour traces "
          f"(activity-level similarity investigation)", file=sys.stderr)

    def mean_pairwise(idx_a, idx_b, fn):
        vals = []
        for i in idx_a:
            for j in idx_b:
                if i == j:
                    continue
                v = fn(hr_activity_traces[i], hr_activity_traces[j])
                if v is not None:
                    vals.append(v)
        return statistics.fmean(vals) if vals else None

    t0 = time.perf_counter()
    similarity_results = {}
    for name, fn in [("levenshtein", normalized_levenshtein_similarity), ("lcs", lcs_similarity), ("jaccard", jaccard_similarity)]:
        within_dominant = mean_pairwise(dominant_idx, dominant_idx, fn)
        within_detour = mean_pairwise(detour_idx, detour_idx, fn)
        between = mean_pairwise(dominant_idx, detour_idx, fn)
        similarity_results[name] = {
            "within_dominant": round(within_dominant, 4) if within_dominant is not None else None,
            "within_detour": round(within_detour, 4) if within_detour is not None else None,
            "between_dominant_and_detour": round(between, 4) if between is not None else None,
        }
    elapsed = time.perf_counter() - t0
    n_pairs = len(dominant_idx) ** 2 + len(detour_idx) ** 2 + 2 * len(dominant_idx) * len(detour_idx)
    print(f"Pairwise similarity over {n_pairs} pairs computed in {elapsed:.3f}s "
          f"(O(N^2) pairwise, N=122 for HR/Payroll -- trivial at this scale)", file=sys.stderr)
    for name, r in similarity_results.items():
        print(f"  {name}: within_dominant={r['within_dominant']} within_detour={r['within_detour']} "
              f"between={r['between_dominant_and_detour']}", file=sys.stderr)

    # distinct applications actually touched per process -- read directly
    # from each execution's own `applications` field (already computed by
    # Section 3's `build_executions`), not approximated from something
    # else (interaction-category count is a different concept and would
    # be a mislabeled substitute).
    process_applications = defaultdict(set)
    for ex in executions:
        process_applications[ex["dominant_context"]].update(ex["applications"])

    # === Section 10/11: metrics -- reusing existing profiles/variants, adding entropy + automation_surface ===
    candidate_pids = [pid for pid, p in profiles.items() if not p["excluded_from_ranking"]]
    print(f"\n{len(candidate_pids)} candidate processes for scoring (excluded: "
          f"{sum(1 for p in profiles.values() if p['excluded_from_ranking'])})", file=sys.stderr)

    total_exec = sum(profiles[pid]["execution_count"] for pid in candidate_pids)
    total_time = sum(profiles[pid]["total_duration_ms"] for pid in candidate_pids)

    process_metrics = {}
    raw_inputs = {}
    for pid in candidate_pids:
        p = profiles[pid]
        freqs = [v["frequency"] for v in variants[pid]]
        entropy = variant_entropy(freqs)
        surface = automation_surface(p["dominant_variant_share"], p["avg_manual_event_share"])
        complexity_risk = p["avg_systems_touched_per_execution"] + p["n_distinct_interaction_categories"]
        freq_share = p["execution_count"] / total_exec
        time_share = p["total_duration_ms"] / total_time

        process_metrics[pid] = {
            "process_id": pid, "readable_name": p["readable_name"],
            "execution_count": p["execution_count"], "frequency_share": round(freq_share, 4),
            "total_duration_ms": p["total_duration_ms"], "average_duration_ms": round(p["total_duration_ms"] / p["execution_count"], 1),
            "time_share": round(time_share, 4),
            "user_count": len(p["frequency_by_operator"]),
            "application_count": len(process_applications[pid]),
            "event_count": p["event_count_distribution"].get("mean"),
            "variant_count": p["n_variants"], "dominant_variant_share": p["dominant_variant_share"],
            "variant_entropy": round(entropy, 4),
            "manual_interaction_count": round(p["avg_manual_event_share"] * p["event_count_distribution"].get("mean", 0) * p["execution_count"]),
            "automation_surface": round(surface, 4),
        }
        raw_inputs[pid] = ImpactFeasibilityInputs(
            frequency_share=freq_share, time_share=time_share, manual_involvement=p["avg_manual_event_share"],
            dominant_variant_share=p["dominant_variant_share"], variant_entropy_value=entropy,
            automation_surface_value=surface, complexity_risk=complexity_risk,
        )

    # === Section 14: double-counting check -- correlation between frequency and total time ===
    exec_counts = [profiles[pid]["execution_count"] for pid in candidate_pids]
    durations = [profiles[pid]["total_duration_ms"] for pid in candidate_pids]
    correlation = statistics.correlation(exec_counts, durations)
    print(f"\nPearson correlation(execution_count, total_duration_ms) across {len(candidate_pids)} processes: "
          f"{correlation:.4f}", file=sys.stderr)

    # === Section 12/13: Impact, Feasibility, Opportunity (default equal weights) ===
    impact = compute_impact_scores(raw_inputs)
    feasibility = compute_feasibility_scores(raw_inputs)
    opportunity = compute_opportunity_scores(impact, feasibility)
    ranked = rank_processes(opportunity)

    print("\n--- New methodology ranking (default weights) ---", file=sys.stderr)
    for i, pid in enumerate(ranked[:10], 1):
        print(f"  {i}. {profiles[pid]['readable_name']:<45} Impact={impact[pid]:.3f} "
              f"Feasibility={feasibility[pid]:.3f} Opportunity={opportunity[pid]:.3f}", file=sys.stderr)

    hr_rank_new = ranked.index(HR_PROCESS_ID) + 1
    old_ranked_pids = [r["process_id"] for r in old_priority["ranking_default_weights"]]
    hr_rank_old = old_ranked_pids.index(HR_PROCESS_ID) + 1
    print(f"\nHR/Payroll rank: OLD={hr_rank_old}, NEW={hr_rank_new}", file=sys.stderr)

    # === Section 17: sensitivity analysis over Impact/Feasibility weight scenarios ===
    impact_weight_scenarios = {
        "balanced": {"frequency": 1.0, "time": 1.0, "manual": 1.0},
        "frequency_heavy": {"frequency": 3.0, "time": 1.0, "manual": 1.0},
        "time_heavy": {"frequency": 1.0, "time": 3.0, "manual": 1.0},
        # deliberately de-emphasizes volume (the dimension HR dominates on)
        # to give a "small, simple process wins" scenario a fair chance --
        # the multiplicative-score analogue of the OLD approach's
        # "risk_averse"/"no_business_impact_proxy" scenarios, which DID
        # displace HR/Payroll from #1. Testing this is what makes the
        # stability comparison below fair rather than convenient.
        "volume_deemphasized": {"frequency": 0.2, "time": 0.2, "manual": 3.0},
    }
    feasibility_weight_scenarios = {
        "balanced": {"determinism": 1.0, "stability": 1.0, "surface": 1.0, "risk": 1.0},
        "feasibility_heavy": {"determinism": 2.0, "stability": 2.0, "surface": 2.0, "risk": 1.0},
        # heavily rewards small/simple/low-risk processes specifically --
        # the condition under which the OLD approach's tiny, single-variant
        # Excel workbooks overtook HR/Payroll.
        "risk_averse": {"determinism": 3.0, "stability": 1.0, "surface": 1.0, "risk": 3.0},
    }
    sensitivity = {}
    for iname, iw in impact_weight_scenarios.items():
        for fname, fw in feasibility_weight_scenarios.items():
            imp = compute_impact_scores(raw_inputs, weights=iw)
            fea = compute_feasibility_scores(raw_inputs, weights=fw)
            opp = compute_opportunity_scores(imp, fea)
            rk = rank_processes(opp)
            scenario_name = f"impact={iname},feasibility={fname}"
            sensitivity[scenario_name] = {
                "top3": [profiles[pid]["readable_name"] for pid in rk[:3]],
                "hr_rank": rk.index(HR_PROCESS_ID) + 1,
            }
    print("\n--- Sensitivity: HR/Payroll rank under each scenario ---", file=sys.stderr)
    for name, r in sensitivity.items():
        print(f"  {name:<45} HR_rank={r['hr_rank']} top3={r['top3']}", file=sys.stderr)
    n_scenarios = len(sensitivity)
    n_hr_first = sum(1 for r in sensitivity.values() if r["hr_rank"] == 1)
    print(f"\nHR/Payroll ranked #1 in {n_hr_first}/{n_scenarios} scenarios tested "
          f"(including the 3 deliberately volume-deemphasizing/risk-averse scenarios "
          f"designed to give a small, simple process a fair chance to win, mirroring "
          f"the OLD approach's own risk_averse/no_business_impact_proxy scenarios)", file=sys.stderr)

    out = {
        "trace_representation": {"avg_system_level_length": round(avg_sys_len, 2), "avg_activity_level_length": round(avg_act_len, 2)},
        "hr_payroll_dfg": process_dfg[HR_PROCESS_ID],
        "hr_payroll_similarity_investigation": {
            "n_dominant_traces": len(dominant_idx), "n_detour_traces": len(detour_idx),
            "n_pairs_compared": n_pairs, "elapsed_seconds": round(elapsed, 4),
            "results": similarity_results,
        },
        "process_metrics": process_metrics,
        "double_counting_check": {
            "pearson_correlation_execution_count_vs_total_duration": round(correlation, 4),
        },
        "impact_scores": {pid: round(v, 4) for pid, v in impact.items()},
        "feasibility_scores": {pid: round(v, 4) for pid, v in feasibility.items()},
        "opportunity_scores": {pid: round(v, 4) for pid, v in opportunity.items()},
        "ranking_default_weights": [
            {"rank": i + 1, "process_id": pid, "readable_name": profiles[pid]["readable_name"],
             "impact": round(impact[pid], 4), "feasibility": round(feasibility[pid], 4), "opportunity": round(opportunity[pid], 4)}
            for i, pid in enumerate(ranked)
        ],
        "hr_payroll_rank": {"old_approach": hr_rank_old, "new_approach": hr_rank_new},
        "sensitivity_analysis": sensitivity,
        "hr_rank_first_place_count": {"n_scenarios": n_scenarios, "n_hr_first": n_hr_first},
    }

    enriched_metrics = {
        pid: {**process_metrics[pid], "impact_score": round(impact[pid], 4),
              "feasibility_score": round(feasibility[pid], 4), "opportunity_score": round(opportunity[pid], 4),
              "rank": ranked.index(pid) + 1}
        for pid in candidate_pids
    }
    out_json = args.out / "problem2_process_metrics.json"
    with out_json.open("w", encoding="utf-8") as f:
        json.dump(enriched_metrics, f, indent=2, ensure_ascii=False, default=str)

    out_full = args.out / "problem2_process_mining_full_results.json"
    with out_full.open("w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)

    print(f"\nWrote {out_json}", file=sys.stderr)
    print(f"Wrote {out_full}", file=sys.stderr)
    print("Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
