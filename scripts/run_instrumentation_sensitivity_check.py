#!/usr/bin/env python3
"""Day 4: does the Dataset-B automation recommendation survive removing
the evidence contributed by instrumentation-degraded sessions?

Method, deliberately blunt so it cannot be accused of moving the goal
posts: the Problem-2 pipeline is re-run END TO END, twice, by invoking
the EXISTING Day-3 scripts as subprocesses without modification --

    process_executions_dataset_b.json
        -> scripts/analyze_process_priority_dataset_b.py   (profiles, variants, priority)
        -> scripts/audit_problem2_process_mining.py        (Impact/Feasibility/Opportunity, post-entropy-fix)

CASE A: every Dataset-B session included (reproduces the Day-3 result).
CASE B: sessions the instrumentation diagnostic flagged are excluded.

The ONLY difference between the two runs is which executions are in the
input file. No scoring weight, formula, threshold, or script is touched,
which is what makes the comparison meaningful: any ranking change is
attributable to the excluded evidence, not to a changed method.

Recomputing profiles/variants from the filtered executions (rather than
filtering executions but keeping full-population aggregates) is
essential -- the opportunity score reads execution_count,
total_duration_ms, avg_manual_event_share, dominant_variant_share and
n_variants from the profiles, so reusing stale profiles would silently
mix the two populations.

Dataset B has no ground truth. Nothing here claims either case is "more
correct" as segmentation; the question is only whether the business
conclusion is sensitive to the degraded evidence.

Usage:
    python scripts/run_instrumentation_sensitivity_check.py \
        --executions reports/day3/process_executions_dataset_b.json \
        --health reports/day4/instrumentation_health_dataset_b.json \
        --out reports/day4
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PRIORITY_SCRIPT = REPO_ROOT / "scripts" / "analyze_process_priority_dataset_b.py"
AUDIT_SCRIPT = REPO_ROOT / "scripts" / "audit_problem2_process_mining.py"


def run_chain(executions: dict, work_dir: Path, label: str) -> dict:
    """Run the unmodified Day-3 Problem-2 chain over one execution set."""
    work_dir.mkdir(parents=True, exist_ok=True)
    exec_path = work_dir / "process_executions_dataset_b.json"
    exec_path.write_text(json.dumps(executions), encoding="utf-8")

    for script, argv in (
        (PRIORITY_SCRIPT, ["--executions", str(exec_path), "--out", str(work_dir)]),
        (AUDIT_SCRIPT, ["--day3-dir", str(work_dir), "--out", str(work_dir)]),
    ):
        proc = subprocess.run(
            [sys.executable, str(script), *argv],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        if proc.returncode != 0:
            print(proc.stdout[-2000:], file=sys.stderr)
            print(proc.stderr[-4000:], file=sys.stderr)
            raise SystemExit(f"[{label}] {script.name} failed (rc={proc.returncode})")

    return json.loads((work_dir / "problem2_audit_results.json").read_text(encoding="utf-8"))


def ranking_rows(audit: dict) -> list[dict]:
    return audit["default_ranking"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executions", required=True, type=Path)
    parser.add_argument("--health", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--work", type=Path, default=None)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    full = json.loads(args.executions.read_text(encoding="utf-8"))
    health = json.loads(args.health.read_text(encoding="utf-8"))
    degraded = sorted(health["summary"]["degraded_session_ids"])

    all_execs = full["executions"]
    kept = [e for e in all_execs if e["session_id"] not in set(degraded)]
    removed = [e for e in all_execs if e["session_id"] in set(degraded)]
    print(f"Dataset B: {len(all_execs)} executions; excluding {len(degraded)} degraded "
          f"session(s) removes {len(removed)}, leaving {len(kept)}", file=sys.stderr)

    tmp_ctx = tempfile.TemporaryDirectory() if args.work is None else None
    work_root = Path(tmp_ctx.name) if tmp_ctx else args.work
    try:
        print("Running CASE A (all sessions) ...", file=sys.stderr)
        audit_a = run_chain(full, work_root / "case_a", "case_a")
        print("Running CASE B (degraded sessions excluded) ...", file=sys.stderr)
        audit_b = run_chain({**full, "executions": kept}, work_root / "case_b", "case_b")
    finally:
        if tmp_ctx is not None:
            pass  # cleaned up below, after results are read into memory

    rows_a, rows_b = ranking_rows(audit_a), ranking_rows(audit_b)
    rank_a = {r["process_id"]: r for r in rows_a}
    rank_b = {r["process_id"]: r for r in rows_b}

    comparison = []
    for pid, ra in rank_a.items():
        rb = rank_b.get(pid)
        comparison.append({
            "process_id": pid,
            "readable_name": ra["readable_name"],
            "rank_case_a": ra["rank"],
            "rank_case_b": rb["rank"] if rb else None,
            "rank_delta": (rb["rank"] - ra["rank"]) if rb else None,
            "impact_a": ra["impact"], "impact_b": rb["impact"] if rb else None,
            "feasibility_a": ra["feasibility"], "feasibility_b": rb["feasibility"] if rb else None,
            "opportunity_a": ra["opportunity"], "opportunity_b": rb["opportunity"] if rb else None,
            "present_in_case_b": rb is not None,
        })
    comparison.sort(key=lambda r: r["rank_case_a"])

    top_a = rows_a[0]["process_id"] if rows_a else None
    top_b = rows_b[0]["process_id"] if rows_b else None

    result = {
        "question": "Does the Dataset-B automation recommendation survive removing "
                    "evidence from instrumentation-degraded sessions?",
        "method": "Identical Problem-2 chain (analyze_process_priority_dataset_b.py -> "
                  "audit_problem2_process_mining.py) run twice as subprocesses, unmodified. "
                  "Only the input execution population differs.",
        "no_ground_truth_note": "Dataset B has no ground truth; neither case is claimed "
                                "to be more correct as segmentation.",
        "excluded_sessions": degraded,
        "executions_total": len(all_execs),
        "executions_removed": len(removed),
        "executions_kept": len(kept),
        "n_processes_case_a": len(rows_a),
        "n_processes_case_b": len(rows_b),
        "top_candidate_case_a": top_a,
        "top_candidate_case_b": top_b,
        "top_candidate_unchanged": top_a == top_b,
        "pareto_case_a": audit_a.get("pareto_frontier", {}).get("hr_on_frontier"),
        "pareto_case_b": audit_b.get("pareto_frontier", {}).get("hr_on_frontier"),
        "sensitivity_summary_case_a": audit_a.get("sensitivity_summary"),
        "sensitivity_summary_case_b": audit_b.get("sensitivity_summary"),
        "ranking_comparison": comparison,
    }

    out_path = args.out / "instrumentation_sensitivity_check.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if tmp_ctx is not None:
        tmp_ctx.cleanup()

    print(f"\nTop candidate CASE A: {top_a}", file=sys.stderr)
    print(f"Top candidate CASE B: {top_b}", file=sys.stderr)
    print(f"Unchanged: {top_a == top_b}", file=sys.stderr)
    print(f"Wrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
