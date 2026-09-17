#!/usr/bin/env python3
"""Day 6 · Module 2 — process analysis: effort, operators, Pareto, sensitivity.

WHAT THIS ADDS, AND WHAT IT REFUSES TO ADD
------------------------------------------
Module 1 answers "what should we automate?" with a single weighted Opportunity score.
That score is canonical and is **not** recomputed, replaced or re-weighted here.

Module 2 adds a second, weight-free decision view alongside it:

  2A  effort conversion   — executions, observed time, average duration, time share.
                            Monetary cost is NOT fabricated: no operator cost rate
                            exists in the telemetry, so the cost column stays empty and
                            says why (H4).
  2B  operator variants   — is variant behaviour concentrated by operator? (H5)
  2C  Pareto frontier     — trade-offs exposed rather than collapsed into a weight (H6).
  2D  sensitivity         — the canonical 8 scenarios, shown beside the Pareto view.

Dataset B has no ground truth, so nothing here is a supervised metric. These are
operational statistics.

Usage:
    python scripts/run_module2_process_analysis.py --out reports/day6/module2
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DAY3 = ROOT / "reports" / "day3"

PROFILES = DAY3 / "process_profiles_dataset_b.json"
EXECUTIONS = DAY3 / "process_executions_dataset_b.json"
AUDIT = DAY3 / "problem2_audit_results.json"
HR_FORENSICS = DAY3 / "hr_payroll_dominant_path_dataset_b.json"

MS_PER_HOUR = 3_600_000.0
#: chi-square 0.05 critical values, dof 1..6. Tabulated rather than computed so no new
#: dependency is introduced for one number; only small dof are ever needed here.
CHI2_CRIT_05 = {1: 3.841, 2: 5.991, 3: 7.815, 4: 9.488, 5: 11.070, 6: 12.592}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval — behaves sensibly at the small n these operators have."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (round((centre - margin) / denom, 4), round((centre + margin) / denom, 4))


# --- 2A: time / effort / cost ---------------------------------------------

def step_2a(profiles: dict, executions: list[dict]) -> dict:
    """Transparent measurable effort. No invented money.

        F_p  = execution count
        TD_p = sum of execution durations
        AD_p = TD_p / F_p
        TS_p = TD_p / sum_p TD_p
    """
    ranked = {pid: p for pid, p in profiles.items() if not p.get("excluded_from_ranking")}
    td_total = sum(p["total_duration_ms"] for p in ranked.values())

    # Independent cross-check: recompute TD from the execution records themselves.
    recomputed: dict[str, int] = defaultdict(int)
    for e in executions:
        recomputed[e.get("process_id") or e.get("dominant_context")] += e["duration_ms"]

    rows = []
    for pid, p in sorted(ranked.items(), key=lambda kv: -kv[1]["total_duration_ms"]):
        td = p["total_duration_ms"]
        f = p["execution_count"]
        rows.append({
            "process_id": pid,
            "readable_name": p["readable_name"],
            "executions_F_p": f,
            "total_observed_time_ms_TD_p": td,
            "total_observed_time_hours": round(td / MS_PER_HOUR, 4),
            "average_duration_ms_AD_p": round(td / f, 1) if f else None,
            "time_share_TS_p": round(td / td_total, 6) if td_total else None,
            "observed_effort_hours": round(td / MS_PER_HOUR, 4),
            "cost_input_available": False,
            "estimated_cost": None,
            "missing_inputs": ["operator hourly cost rate", "headcount",
                               "fully-loaded employment cost"],
        })

    return {
        "definitions": {
            "F_p": "execution frequency (count of executions of process p)",
            "TD_p": "total observed duration, sum of execution durations",
            "AD_p": "TD_p / F_p",
            "TS_p": "TD_p / sum over all ranked processes of TD",
            "ObservedEffort_p": "TD_p expressed in hours — an observed quantity, "
                                "not a cost",
        },
        "monetary_roi_statement": (
            "Direct monetary ROI cannot be estimated from the provided telemetry "
            "because operator cost/headcount cost is unavailable. No salary, rate or "
            "headcount figure appears anywhere in Dataset A or Dataset B, so any "
            "currency amount would be invented rather than measured."
        ),
        "environment_caveat": (
            "Dataset-B timing may reflect the assignment/test environment rather than "
            "production reality. Durations here are observed recording time, not "
            "validated production cycle times, and must not be presented as the latter."
        ),
        "n_ranked_processes": len(ranked),
        "n_excluded_processes": len(profiles) - len(ranked),
        "total_observed_time_hours_all_ranked": round(td_total / MS_PER_HOUR, 4),
        "cross_check_note": (
            "Process-level totals are read from the canonical profile artifact. "
            "Execution records carry no process_id field, so a per-process recomputation "
            "from executions is not possible without re-deriving the grouping; the "
            "profile totals are therefore used as canonical and not second-guessed."
        ),
        "table": rows,
    }


# --- 2B: operator-level variant behaviour ---------------------------------

def step_2b(profiles: dict, executions: list[dict], hr: dict) -> dict:
    """Is variant behaviour concentrated by operator? (H5)

    The canonical 94/24/4 HR split is **used, never reinterpreted**: the execution ids
    are read from the canonical forensic artifact and joined to their operator.
    """
    op_by_exec = {e["execution_id"]: e["operator"] for e in executions}

    def ids(block: str) -> list[str]:
        return [r["execution_id"] for r in hr[block]["per_execution"]]

    variant_ids = {
        "dominant": ids("dominant_variant_analysis"),
        "word_detour": ids("word_detour_variant_analysis"),
        "rare_edge": [r["execution_id"] for r in hr["rare_edge_cases"]],
    }
    split = hr["variant_split"]
    matches_canonical = all(len(variant_ids[k]) == split[k]["n"] for k in variant_ids)
    unmatched = [i for v in variant_ids.values() for i in v if i not in op_by_exec]

    table = defaultdict(Counter)
    for variant, id_list in variant_ids.items():
        for exec_id in id_list:
            table[op_by_exec.get(exec_id, "UNKNOWN")][variant] += 1

    total_dom = sum(c["dominant"] for c in table.values())
    total_n = sum(sum(c.values()) for c in table.values())
    pooled_share = total_dom / total_n if total_n else 0.0

    rows, chi2 = [], 0.0
    for op, c in sorted(table.items(), key=lambda kv: -sum(kv[1].values())):
        n = sum(c.values())
        lo, hi = wilson(c["dominant"], n)
        expected = n * pooled_share
        if expected > 0:
            chi2 += (c["dominant"] - expected) ** 2 / expected
            if n - expected > 0:
                chi2 += ((n - c["dominant"]) - (n - expected)) ** 2 / (n - expected)
        rows.append({
            "operator": op, "executions": n,
            "dominant": c["dominant"], "word_detour": c["word_detour"],
            "rare_edge": c["rare_edge"],
            "dominant_path_share": round(c["dominant"] / n, 4) if n else None,
            "dominant_share_95ci": [lo, hi],
            "ci_contains_pooled_share": lo <= pooled_share <= hi,
        })

    dof = max(len(rows) - 1, 1)
    crit = CHI2_CRIT_05.get(dof)
    shares = [r["dominant_path_share"] for r in rows if r["dominant_path_share"] is not None]

    # Concentration across ALL processes, from the canonical profile field.
    concentration = []
    for pid, p in profiles.items():
        freq = p.get("frequency_by_operator") or {}
        total = sum(freq.values())
        if total:
            concentration.append({
                "process_id": pid, "readable_name": p["readable_name"],
                "n_operators": len(freq), "executions": total,
                "largest_operator_share": round(max(freq.values()) / total, 4),
                "herfindahl": round(sum((v / total) ** 2 for v in freq.values()), 4),
            })
    concentration.sort(key=lambda r: -r["executions"])

    return {
        "hypothesis": "H5 — operator-level variant behaviour reveals rollout/training "
                      "risk hidden by process-level averages",
        "canonical_split_used_not_reinterpreted": {
            "dominant": split["dominant"]["n"], "word_detour": split["word_detour"]["n"],
            "rare_edge": split["rare_edge"]["n"],
            "join_matches_canonical_counts": matches_canonical,
            "execution_ids_unmatched_to_an_operator": len(unmatched),
        },
        "hr_operator_table": rows,
        "pooled_dominant_share": round(pooled_share, 4),
        "dispersion": {
            "min_share": round(min(shares), 4) if shares else None,
            "max_share": round(max(shares), 4) if shares else None,
            "spread": round(max(shares) - min(shares), 4) if shares else None,
            "stdev": round(statistics.pstdev(shares), 4) if len(shares) > 1 else None,
            "chi_square": round(chi2, 3),
            "dof": dof,
            "chi_square_0_05_critical": crit,
            "differs_beyond_chance_at_0_05": (crit is not None and chi2 > crit),
        },
        "interpretation_wording": (
            "Variant concentration differs across operators and may indicate a "
            "training/process-adherence consideration. No operator is characterised as "
            "performing badly: the samples are small (18-44 executions each), and the "
            "confidence intervals must be read before any rollout inference is drawn."
        ),
        "limitations": [
            "Only 4 operators appear in Dataset B, with 18-44 HR executions each.",
            "Operator identity is a machine/account label, not a verified person.",
            "Dataset B has no ground truth, so these are operational statistics only.",
            "A difference in variant mix does not establish a difference in competence, "
            "workload, or case difficulty — none of which is observable here.",
        ],
        "process_level_operator_concentration": concentration,
    }


# --- 2C: Pareto frontier ---------------------------------------------------

def dominates(a: dict, b: dict) -> bool:
    """A dominates B iff Impact_A >= Impact_B and Feasibility_A >= Feasibility_B,
    with at least one strict inequality."""
    ge = a["impact"] >= b["impact"] and a["feasibility"] >= b["feasibility"]
    strict = a["impact"] > b["impact"] or a["feasibility"] > b["feasibility"]
    return ge and strict


def step_2c(audit: dict, profiles: dict, effort_rows: list[dict], hr: dict) -> dict:
    ranking = audit["default_ranking"]
    frontier = [r for r in ranking if not any(dominates(o, r) for o in ranking if o is not r)]
    frontier_names = sorted(r["readable_name"] for r in frontier)
    canonical = sorted(audit["pareto_frontier"]["processes"])

    effort_by_id = {r["process_id"]: r for r in effort_rows}
    n_routes = len(hr.get("route_id_prefix_correspondence") or {})

    annotated = []
    for r in ranking:
        p = profiles.get(r["process_id"], {})
        eff = effort_by_id.get(r["process_id"], {})
        annotated.append({
            "process_id": r["process_id"], "readable_name": r["readable_name"],
            "rank_canonical": r["rank"],
            "impact": r["impact"], "feasibility": r["feasibility"],
            "opportunity_canonical": r["opportunity"],
            "on_pareto_frontier": r in frontier,
            "dominated_by": [o["readable_name"] for o in ranking
                             if o is not r and dominates(o, r)],
            # annotation dimensions, not new score components
            "executions": p.get("execution_count"),
            "time_share": eff.get("time_share_TS_p"),
            "dominant_variant_share": p.get("dominant_variant_share"),
            "automation_surface_evidenced_routes": (
                n_routes if r["process_id"] == hr.get("hr_process_id") else None),
        })

    return {
        "hypothesis": "H6 — a Pareto frontier communicates trade-offs more transparently "
                      "than a single weighted ranking",
        "dominance_definition": "A dominates B iff Impact_A >= Impact_B AND "
                                "Feasibility_A >= Feasibility_B, with at least one "
                                "strict inequality.",
        "dimensions_used": ["impact", "feasibility"],
        "annotation_dimensions_not_scored": ["executions", "time_share",
                                             "dominant_variant_share",
                                             "automation_surface_evidenced_routes"],
        "no_weighted_score_added": True,
        "canonical_opportunity_unchanged": True,
        "frontier_recomputed": frontier_names,
        "frontier_canonical": canonical,
        "recomputation_matches_canonical": frontier_names == canonical,
        "n_frontier": len(frontier_names),
        "n_total": len(ranking),
        "table": annotated,
    }


# --- 2D: sensitivity -------------------------------------------------------

def step_2d(audit: dict, pareto: dict) -> dict:
    scenarios = audit["sensitivity_analysis"]
    summary = audit["sensitivity_summary"]
    return {
        "canonical_scenarios_reused_not_invented": True,
        "n_scenarios": summary["n_scenarios"],
        "n_scenarios_hr_first": summary["n_hr_first"],
        "mean_kendall_tau_vs_default": summary["mean_kendall_tau_vs_default"],
        "weighted_view": {name: {"hr_rank": s["hr_rank"],
                                 "top_candidate_changed": s["top_candidate_changed"]}
                          for name, s in scenarios.items()},
        "pareto_view": {
            "frontier": pareto["frontier_recomputed"],
            "invariant_across_scenarios": True,
            "why": ("Pareto membership uses no weights, so re-weighting the Opportunity "
                    "score cannot move it. That is a structural property, not an "
                    "empirical finding."),
        },
        "comparison_note": (
            "Neither view is universally superior. The weighted view produces a single "
            "ordered recommendation and is sensitive to its weights; the Pareto view is "
            "weight-free but returns a set rather than a ranking and cannot break ties. "
            "They are shown side by side so the reader sees the trade-off rather than "
            "being handed one answer."
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    profiles = json.loads(PROFILES.read_text(encoding="utf-8"))
    executions = json.loads(EXECUTIONS.read_text(encoding="utf-8"))["executions"]
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    hr = json.loads(HR_FORENSICS.read_text(encoding="utf-8"))

    a = step_2a(profiles, executions)
    b = step_2b(profiles, executions, hr)
    c = step_2c(audit, profiles, a["table"], hr)
    d = step_2d(audit, c)

    out = {
        "module": "Module 2 — Adaptive Evidence-Guided Reconstruction & Automation",
        "dataset": "Dataset B (no ground truth)",
        "dataset_b_rule": ("Dataset B is used for operational validation, not supervised "
                           "segmentation evaluation. No accuracy, precision, recall or "
                           "F1 appears in this artifact."),
        "canonical_inputs": {
            "profiles": "reports/day3/process_profiles_dataset_b.json",
            "executions": "reports/day3/process_executions_dataset_b.json",
            "ranking_and_sensitivity": "reports/day3/problem2_audit_results.json",
            "hr_forensics": "reports/day3/hr_payroll_dominant_path_dataset_b.json",
        },
        "step_2a_effort": a,
        "step_2b_operator_variants": b,
        "step_2c_pareto": c,
        "step_2d_sensitivity": d,
    }
    path = args.out / "module2_process_analysis.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"2A: {a['n_ranked_processes']} ranked processes, "
          f"{a['total_observed_time_hours_all_ranked']} observed hours, "
          f"cost inputs available: NO", file=sys.stderr)
    print(f"2B: HR split join matches canonical: "
          f"{b['canonical_split_used_not_reinterpreted']['join_matches_canonical_counts']}; "
          f"operator dominant-share spread {b['dispersion']['spread']}, "
          f"chi2={b['dispersion']['chi_square']} (dof {b['dispersion']['dof']}, "
          f"crit {b['dispersion']['chi_square_0_05_critical']}) -> differs beyond chance: "
          f"{b['dispersion']['differs_beyond_chance_at_0_05']}", file=sys.stderr)
    print(f"2C: frontier {c['frontier_recomputed']} matches canonical: "
          f"{c['recomputation_matches_canonical']}", file=sys.stderr)
    print(f"2D: HR first in {d['n_scenarios_hr_first']}/{d['n_scenarios']} scenarios",
          file=sys.stderr)
    print(f"Wrote {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
