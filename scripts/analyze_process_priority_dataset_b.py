#!/usr/bin/env python3
"""Sections 4-13 of the Dataset-B process-discovery work: group the
Section-3 executions into underlying processes, discover variants,
measure frequency/time/repetitiveness, score automation priority on a
transparent normalized formula, and produce a ranked, evidence-based
automation candidate.

Reads `reports/day3/process_executions_dataset_b.json` (Section 3's
output) rather than rebuilding it, so this script is purely downstream
analysis of already-constructed, already-tested execution records.
Dataset B has no ground truth; every judgment-based component below
(business impact, risk, feasibility) is explicitly labeled as a
heuristic proxy, not a measured fact.

Usage:
    python scripts/analyze_process_priority_dataset_b.py --executions reports/day3/process_executions_dataset_b.json --out reports/day3
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from procmine.process_discovery.prioritization import PriorityInputs, compute_priority_scores
from procmine.process_discovery.variant_analysis import variant_signature

MANUAL_CATEGORIES = {"input", "pointer", "clipboard"}
CORE_SYSTEMS = {"system:財務会計システム", "system:HR人事給与システム", "system:受発注在庫管理システム"}
# Not real business processes in their own right -- recording/navigation
# infrastructure or unstructured communication, excluded from ranking
# per instruction #13 ("do not force every event into a business process").
EXCLUDED_PREFIXES = ("app:WindowsTerminal", "app:OpenWith", "app:Windows Explorer", "app:ms-teams")

# Literal document/system names translated for readability in reports --
# translations of real observed strings, not invented process names.
READABLE_NAMES = {
    "system:財務会計システム": "Financial Accounting System",
    "system:HR人事給与システム": "HR / Payroll System",
    "system:受発注在庫管理システム": "Order & Inventory Management System",
    "app:Microsoft Word::nyusha_checklist_shinsotsu_batch": "Word: New-Employee Checklist (New-Graduate Batch)",
    "app:Microsoft Word::keiyaku_kaijo_tetsuzuki": "Word: Contract Termination Procedure",
    "app:Microsoft Word::gyomu_itaku_kyuuyo_kitei": "Word: Outsourcing Compensation Regulations",
    "app:Microsoft Word::settai_keihi_kitei": "Word: Entertainment Expense Regulations",
    "app:Microsoft Word::gyomu_itaku_ukeire_tetsuzuki": "Word: Outsourcing Intake Procedure",
    "app:Microsoft Word::getsujitsu_teigaku_torihikisaki_ichiran": "Word: Monthly Fixed-Amount Trading-Partner List",
    "app:Microsoft Word::shinkuitorihikisaki_touroku_tetsuzuki": "Word: New Trading-Partner Registration Procedure",
    "app:Microsoft Word::gyomu_itaku_keihi_kitei": "Word: Outsourcing Expense Regulations",
    "app:Microsoft Word::shinkui_keiyaku_tetsuzuki": "Word: New Contract Procedure",
    "app:Microsoft Word::ikuji_kyuugyou_kitei": "Word: Childcare Leave Regulations",
    "app:Microsoft Word::kanrisya_kengen_shinsei_tetsuzuki": "Word: Administrator Authority Request Procedure",
    "app:Microsoft Word::kazoku_teate_kitei": "Word: Family Allowance Regulations",
    "app:Microsoft Word::kaigo_kyuugyou_kitei": "Word: Family-Care Leave Regulations",
    "app:Microsoft Excel::expense_calc": "Excel: Expense Calculation Workbook",
    "app:Microsoft Excel::budget_analysis": "Excel: Budget Analysis Workbook",
    "app:Notepad::在庫調整メモ": "Notepad: Inventory Adjustment Memo",
    "app:Notepad::精算確認メモ": "Notepad: Expense Settlement Confirmation Memo",
    "app:Notepad::IT申請メモ": "Notepad: IT Request Memo",
}


def readable(pid: str) -> str:
    return READABLE_NAMES.get(pid, pid)


def is_excluded(pid: str) -> bool:
    if pid.startswith(EXCLUDED_PREFIXES):
        return True
    if pid.startswith("browser:") and pid not in CORE_SYSTEMS:
        return True  # ambiguous port-only identity, no resolved system/document name
    if pid == "app:Notepad" or pid == "unknown":
        return True  # untitled/no-document-resolved fallback, too ambiguous to rank
    return False


def dist_summary(values):
    if not values:
        return {"n": 0}
    s = sorted(values)
    def pct(p):
        return s[min(int(len(s) * p), len(s) - 1)]
    return {
        "n": len(values), "mean": round(statistics.fmean(values), 2), "median": statistics.median(values),
        "p25": pct(0.25), "p75": pct(0.75), "min": min(values), "max": max(values),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executions", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    data = json.loads(args.executions.read_text(encoding="utf-8"))
    executions = data["executions"]
    print(f"Loaded {len(executions)} executions from {args.executions}", file=sys.stderr)

    # ================ Section 4: group into processes + variants ================
    by_process = defaultdict(list)
    for ex in executions:
        by_process[ex["dominant_context"]].append(ex)

    process_profiles = {}
    variant_report = {}
    step_frequency = {}
    time_analysis = {}

    for pid, execs in by_process.items():
        variants = Counter()
        for ex in execs:
            variants[variant_signature(ex["ordered_steps"])] += 1
        variant_list = [
            {"signature": list(sig), "frequency": n,
             "avg_duration_ms": round(statistics.fmean(
                 [e["duration_ms"] for e in execs if variant_signature(e["ordered_steps"]) == sig]), 1)}
            for sig, n in variants.most_common()
        ]
        dominant_variant_share = variants.most_common(1)[0][1] / len(execs) if execs else 0.0

        operators = Counter(e["operator"] for e in execs)
        durations = [e["duration_ms"] for e in execs]
        event_counts = [e["event_count"] for e in execs]

        # step frequency: every (system, interaction_category) step type seen
        # within this process's executions, with count + total/avg time
        step_counter = Counter()
        step_time = Counter()
        manual_events_per_exec = []
        categories_seen = set()
        extracted_text_flagged = 0
        total_steps = 0
        for ex in execs:
            manual_events, total_events_in_exec = 0, ex["event_count"]
            for step in ex["ordered_steps"]:
                key = (step["system"], step["interaction_category"])
                step_counter[key] += 1
                step_time[key] += step["end_ms"] - step["start_ms"]
                categories_seen.add(step["interaction_category"])
                if step["interaction_category"] in MANUAL_CATEGORIES:
                    manual_events += step["n_events"]
                for etype, cnt in step["dominant_event_types"]:
                    if etype == "text_input_complete":
                        extracted_text_flagged += cnt
                total_steps += 1
            manual_events_per_exec.append(manual_events / total_events_in_exec if total_events_in_exec else 0.0)

        step_frequency[pid] = [
            {"system": k[0], "interaction_category": k[1], "frequency": v,
             "total_time_ms": step_time[k], "avg_time_ms": round(step_time[k] / v, 1)}
            for k, v in step_counter.most_common()
        ]

        total_duration_ms = sum(durations)
        process_profiles[pid] = {
            "process_id": pid, "readable_name": readable(pid),
            "excluded_from_ranking": is_excluded(pid),
            "execution_count": len(execs),
            "n_variants": len(variants),
            "dominant_variant_share": round(dominant_variant_share, 4),
            "frequency_by_operator": dict(operators),
            "event_count_distribution": dist_summary(event_counts),
            "duration_ms_distribution": dist_summary(durations),
            "total_duration_ms": total_duration_ms,
            "total_human_hours": round(total_duration_ms / 3_600_000, 4),
            "avg_manual_event_share": round(statistics.fmean(manual_events_per_exec), 4) if manual_events_per_exec else 0.0,
            "n_distinct_interaction_categories": len(categories_seen),
            "avg_systems_touched_per_execution": round(
                statistics.fmean([len(variant_signature(e["ordered_steps"])) for e in execs]), 4
            ) if execs else 0.0,
        }
        variant_report[pid] = variant_list
        time_analysis[pid] = {
            "total_duration_ms": total_duration_ms, "total_human_hours": round(total_duration_ms / 3_600_000, 4),
            "avg_duration_ms": round(statistics.fmean(durations), 1) if durations else 0.0,
            "median_duration_ms": statistics.median(durations) if durations else 0.0,
            "min_duration_ms": min(durations) if durations else 0.0,
            "max_duration_ms": max(durations) if durations else 0.0,
            "execution_count": len(execs),
        }

    n_excluded = sum(1 for pid in process_profiles if process_profiles[pid]["excluded_from_ranking"])
    print(f"\n{len(process_profiles)} distinct processes discovered "
          f"({n_excluded} excluded from ranking as infrastructure/ambiguous/support)", file=sys.stderr)

    # ================ Section 9: priority scoring (only non-excluded processes) ================
    candidate_pids = [pid for pid in process_profiles if not process_profiles[pid]["excluded_from_ranking"]]
    raw_inputs = {}
    for pid in candidate_pids:
        p = process_profiles[pid]
        is_core = pid in CORE_SYSTEMS
        business_impact = 1.0 if is_core else 0.6  # heuristic proxy -- see report section 10
        risk = (1.0 if is_core else 0.3) + p["n_variants"]  # external-system dependency + edge-case count
        complexity = p["avg_systems_touched_per_execution"] + p["n_distinct_interaction_categories"]
        # Feasibility proxy: how consistent (single-path) the process already
        # is. A process where nearly every execution follows the same
        # variant is far easier to express as a deterministic rule/RPA
        # script than one with many divergent paths -- `dominant_variant_share`
        # is already exactly that measurement, reused directly rather than
        # inventing a second, redundant consistency metric.
        feasibility = p["dominant_variant_share"]
        raw_inputs[pid] = PriorityInputs(
            frequency=p["execution_count"], time_impact=p["total_human_hours"],
            manual_effort=p["avg_manual_event_share"], repetitiveness=p["dominant_variant_share"],
            feasibility=feasibility, business_impact=business_impact,
            risk=risk, complexity=complexity,
        )

    scores = compute_priority_scores(raw_inputs)
    ranked = sorted(candidate_pids, key=lambda pid: -scores[pid])

    print("\n--- Ranked automation candidates (default equal weights) ---", file=sys.stderr)
    for i, pid in enumerate(ranked[:10], 1):
        p = process_profiles[pid]
        print(f"  {i}. {readable(pid):<55} score={scores[pid]:.3f} "
              f"n={p['execution_count']} hrs={p['total_human_hours']:.2f} "
              f"variants={p['n_variants']} dom_share={p['dominant_variant_share']:.2f}", file=sys.stderr)

    # ================ Sensitivity analysis ================
    weight_sets = {
        "equal (default)": None,
        "time_heavy": {**{k: 1.0 for k in raw_inputs[ranked[0]].__dict__}, "time_impact": 3.0, "risk": 1.0, "complexity": 1.0},
        "frequency_heavy": {**{k: 1.0 for k in raw_inputs[ranked[0]].__dict__}, "frequency": 3.0},
        "risk_averse": {**{k: 1.0 for k in raw_inputs[ranked[0]].__dict__}, "risk": 3.0, "complexity": 2.0},
        "no_business_impact_proxy": {**{k: 1.0 for k in raw_inputs[ranked[0]].__dict__}, "business_impact": 0.0},
    }
    sensitivity = {}
    for name, w in weight_sets.items():
        s = compute_priority_scores(raw_inputs, weights=w)
        top = sorted(candidate_pids, key=lambda pid: -s[pid])[:3]
        sensitivity[name] = [readable(pid) for pid in top]
    print("\n--- Sensitivity: top-3 under alternate weightings ---", file=sys.stderr)
    for name, top3 in sensitivity.items():
        print(f"  {name:<28} {top3}", file=sys.stderr)

    winner_stable = len({s[0] for s in sensitivity.values()}) == 1
    print(f"\nTop-ranked candidate stable across all weight sets: {winner_stable}", file=sys.stderr)

    # ================ Write deliverables ================
    with (args.out / "process_profiles_dataset_b.json").open("w", encoding="utf-8") as f:
        json.dump(process_profiles, f, indent=2, ensure_ascii=False, default=str)
    with (args.out / "process_variants_dataset_b.json").open("w", encoding="utf-8") as f:
        json.dump(variant_report, f, indent=2, ensure_ascii=False, default=str)
    with (args.out / "step_frequency_dataset_b.json").open("w", encoding="utf-8") as f:
        json.dump(step_frequency, f, indent=2, ensure_ascii=False, default=str)
    with (args.out / "human_time_analysis_dataset_b.json").open("w", encoding="utf-8") as f:
        json.dump(time_analysis, f, indent=2, ensure_ascii=False, default=str)

    priority_out = {
        "excluded_processes": [pid for pid in process_profiles if process_profiles[pid]["excluded_from_ranking"]],
        "raw_inputs": {pid: vars(v) for pid, v in raw_inputs.items()},
        "scores_default_weights": scores,
        "ranking_default_weights": [{"rank": i + 1, "process_id": pid, "readable_name": readable(pid), "score": round(scores[pid], 4)}
                                     for i, pid in enumerate(ranked)],
        "sensitivity_top3_by_weight_set": sensitivity,
        "top_ranked_candidate_stable_across_weight_sets": winner_stable,
    }
    with (args.out / "automation_priority_dataset_b.json").open("w", encoding="utf-8") as f:
        json.dump(priority_out, f, indent=2, ensure_ascii=False, default=str)

    print(f"\nWrote process_profiles/process_variants/step_frequency/human_time_analysis/automation_priority "
          f"to {args.out}", file=sys.stderr)
    print("Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
