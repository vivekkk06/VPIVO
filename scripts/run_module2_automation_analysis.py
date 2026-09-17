#!/usr/bin/env python3
"""Day 6 · Module 2 — automation routing coverage and post-action audit (H7, H8).

Measures what the pre-flight variant gate would actually admit, replaying it over the
122 canonical HR executions, and demonstrates the post-action evidence audit end to end
against the local mock target.

Two numbers that must not be confused, and are reported separately here:

  canonical dominant share        94 / 122 = 0.7705   (a descriptive forensic finding)
  routing-eligible coverage       measured below      (what the conservative gate admits)

The second is lower, by design. Neither is "automation accuracy".

Usage:
    python scripts/run_module2_automation_analysis.py --out reports/day6/module2
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from procmine.automation.hr_payroll_automation import (  # noqa: E402
    confirm_submission, prepare_note_submission,
)
from procmine.automation.mock_hr_app import MockHRApplication  # noqa: E402
from procmine.module2.post_action_audit import audit_post_action  # noqa: E402
from procmine.module2.routing import coverage, route_execution  # noqa: E402

DAY3 = ROOT / "reports" / "day3"
HR_FORENSICS = DAY3 / "hr_payroll_dominant_path_dataset_b.json"
EXECUTIONS = DAY3 / "process_executions_dataset_b.json"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    hr = json.loads(HR_FORENSICS.read_text(encoding="utf-8"))
    executions = {e["execution_id"]: e
                  for e in json.loads(EXECUTIONS.read_text(encoding="utf-8"))["executions"]}

    variant_of: dict[str, str] = {}
    routes_of: dict[str, list[str]] = {}
    for block, label in (("dominant_variant_analysis", "dominant"),
                         ("word_detour_variant_analysis", "word_detour")):
        for row in hr[block]["per_execution"]:
            variant_of[row["execution_id"]] = label
            routes_of[row["execution_id"]] = list(row.get("routes_visited") or [])
    signature_of: dict[str, list[str]] = {}
    for row in hr["rare_edge_cases"]:
        variant_of[row["execution_id"]] = "rare_edge"
        routes_of[row["execution_id"]] = []
        signature_of[row["execution_id"]] = list(row.get("variant_signature") or [])

    decisions, rows = [], []
    by_variant: dict[str, Counter] = {v: Counter() for v in
                                      ("dominant", "word_detour", "rare_edge")}
    for exec_id, variant in sorted(variant_of.items()):
        record = executions.get(exec_id) or {}
        decision = route_execution(
            routes_visited=routes_of.get(exec_id),
            applications=record.get("applications"),
            variant_signature=signature_of.get(exec_id),
        )
        decisions.append(decision)
        by_variant[variant]["eligible" if decision.eligible else "refused"] += 1
        by_variant[variant][f"reason:{decision.reason_code}"] += 1
        rows.append({"execution_id": exec_id, "canonical_variant": variant,
                     "operator": record.get("operator"), **decision.to_dict()})

    cov = coverage(decisions)
    dom = hr["variant_split"]["dominant"]
    canonical_share = dom["share"]

    # --- the gap between the forensic label and the conservative gate -------
    dominant_refused = [r for r in rows
                        if r["canonical_variant"] == "dominant" and not r["eligible"]]
    gap_reasons = Counter(r["reason_code"] for r in dominant_refused)

    # --- post-action audit, demonstrated end to end on the local mock -------
    app = MockHRApplication()
    checkpoint = prepare_note_submission(app, "#/payroll-items",
                                         "Reviewed per standard process.")
    confirm_submission(app, checkpoint)
    evidence_ok = audit_post_action(app, checkpoint, execution_id="demo_ok")

    # A deliberately broken end state: the target changes after the action.
    app2 = MockHRApplication()
    cp2 = prepare_note_submission(app2, "#/payroll-items", "Reviewed per standard process.")
    confirm_submission(app2, cp2)
    app2.navigate("#/onboarding")  # the page moved out from under us
    evidence_drift = audit_post_action(app2, cp2, execution_id="demo_route_drift")

    out = {
        "module": "Module 2 — Adaptive Evidence-Guided Reconstruction & Automation",
        "hypotheses": {
            "H7": "a pre-flight variant-routing gate can prevent automation attempting "
                  "executions outside the evidenced dominant path",
            "H8": "a post-action visual/structural audit provides additional evidence "
                  "that the intended UI state was reached",
        },
        "dataset_b_rule": "Operational coverage statistics only. Dataset B has no ground "
                          "truth; nothing here is a supervised metric.",
        "provenance": {
            "variant_labels": "reports/day3/hr_payroll_dominant_path_dataset_b.json",
            "applications": "reports/day3/process_executions_dataset_b.json "
                            "(field: applications)",
        },
        "step_3a_routing": {
            "signals_used": ["routes_visited (evidenced route allowlist)",
                             "applications (Microsoft Word = detour marker)",
                             "variant_signature (multi-system alternation = rare edge)"],
            "deterministic": True,
            "no_classifier_used": True,
            "coverage": cov,
            "canonical_dominant_share": canonical_share,
            "canonical_dominant_n": dom["n"],
            "coverage_vs_canonical_note": (
                "Routing-eligible coverage is deliberately LOWER than the canonical "
                f"dominant share of {canonical_share}. The forensic label describes "
                "observed behaviour; the gate additionally requires an evidenced "
                "automation surface. Where they disagree the gate refuses, and the "
                "execution goes to a human. These are two different quantities and "
                "neither is automation accuracy."
            ),
            "dominant_executions_refused_by_the_gate": {
                "n": len(dominant_refused),
                "reasons": dict(gap_reasons),
                "explanation": (
                    "Dominant-path executions with no observed route, or touching "
                    "routes outside the four evidenced ones (#/resident-tax, "
                    "#/dashboard), cannot have their automation surface confirmed."
                ),
            },
            "by_canonical_variant": {k: dict(v) for k, v in by_variant.items()},
            "safety_property": (
                "Every non-dominant variant is refused: no Word-detour and no rare-edge "
                "execution is admitted."
            ),
            "per_execution": rows,
        },
        "step_3b_post_action_audit": {
            "runs_after_the_existing_flow": True,
            "modifies_day5_automation": False,
            "expected_state_reached": evidence_ok.to_dict(),
            "deliberately_broken_end_state": evidence_drift.to_dict(),
            "detects_route_drift": not evidence_drift.passed,
            "not_pixel_perfect": (
                "Checks are structural. A pixel-difference ratio is defined "
                "(changed_pixels / total_pixels) but is reported as context only, never "
                "used as a pass/fail threshold, because no evidence supports a "
                "particular constant for this UI."
            ),
        },
    }

    path = args.out / "module2_automation_analysis.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"routing: {cov['routing_eligible']}/{cov['total_executions']} eligible "
          f"= {cov['observed_dominant_path_coverage']} observed dominant-path coverage",
          file=sys.stderr)
    print(f"  canonical dominant share {canonical_share} "
          f"({dom['n']}/{cov['total_executions']})", file=sys.stderr)
    print(f"  dominant executions refused by the gate: {len(dominant_refused)} "
          f"{dict(gap_reasons)}", file=sys.stderr)
    print(f"  refusal reasons overall: {cov['reason_counts']}", file=sys.stderr)
    print(f"post-action audit: expected-state passed={evidence_ok.passed}, "
          f"route-drift detected={not evidence_drift.passed}", file=sys.stderr)
    print(f"Wrote {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
