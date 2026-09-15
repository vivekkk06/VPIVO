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
