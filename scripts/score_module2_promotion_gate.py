#!/usr/bin/env python3
"""Day 6 · Module 2 — evaluate the pre-registered promotion gate.

Reads the segmentation experiment artifact and scores every candidate against the gate
that was registered **before** any candidate was run. Kept as a separate step so the
expensive experiment is never re-run to change a verdict, and so the gate logic is
auditable on its own.

THE GATE IS NOT ADJUSTED AFTER SEEING RESULTS. It is the Day-7 segmentation-challenge
gate, reused verbatim, so Module 2 is held to exactly the standard the previous
challenge was held to.

Two reference points are scored, because each answers a different fair question:

  vs M1_compatible control  — same protocol, same harness, only the feature columns
                              differ. This isolates the effect of the added evidence.
  vs canonical locked       — the number the project actually ships (F1 0.3440233...).
                              Promotion would have to beat this to be worth the churn.

Usage:
    python scripts/score_module2_promotion_gate.py --artifact reports/day6/module2
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

CONTROL = "M1_compatible"
_SESSION_RE = re.compile(r"^ses_\d{8}-\d{6}-(.+)$")


def operator_of(session_id: str) -> str:
    m = _SESSION_RE.match(session_id or "")
    return m.group(1) if m else "UNKNOWN"


def dist(values) -> dict:
    values = [v for v in values if v is not None]
    if not values:
        return {"n": 0}
    return {"n": len(values), "mean": round(statistics.fmean(values), 4),
            "median": round(statistics.median(values), 4),
            "min": round(min(values), 4), "max": round(max(values), 4),
            "stdev": round(statistics.pstdev(values), 4) if len(values) > 1 else 0.0}


def robustness(base_ps: dict, cand_ps: dict) -> dict:
    deltas = []
    for sid in base_ps:
        d = cand_ps[sid]["f1"] - base_ps[sid]["f1"]
        deltas.append({"session_id": sid, "delta_f1": round(d, 4)})
    improved = sum(1 for d in deltas if d["delta_f1"] > 0.01)
    degraded = sum(1 for d in deltas if d["delta_f1"] < -0.01)
    deltas.sort(key=lambda x: x["delta_f1"])
    return {
        "sessions_improved": improved,
        "sessions_degraded": degraded,
        "sessions_unchanged": len(deltas) - improved - degraded,
        "delta_f1_distribution": dist([d["delta_f1"] for d in deltas]),
        "worst_5_sessions": deltas[:5],
        "best_5_sessions": deltas[-5:][::-1],
    }


def concentration(base_ps: dict, cand_ps: dict) -> dict:
    """Does the gain survive dropping the 3 most-improved sessions?

    An aggregate gain carried by two or three sessions is not an improvement to the
    method; it is an improvement to those sessions.
    """
    ranked = sorted(((cand_ps[s]["f1"] - base_ps[s]["f1"], s) for s in base_ps),
                    reverse=True)
    top3 = [s for _, s in ranked[:3]]
    rest = [s for s in base_ps if s not in top3]
    b = statistics.fmean([base_ps[s]["f1"] for s in rest])
    c = statistics.fmean([cand_ps[s]["f1"] for s in rest])
    return {
        "top_3_improved_sessions": top3,
        "mean_session_f1_excluding_top3_baseline": round(b, 4),
        "mean_session_f1_excluding_top3_candidate": round(c, 4),
        "gain_survives_removing_top3": bool(c > b),
    }


def machine_dominance(base_ps: dict, cand_ps: dict) -> dict:
    """Gate 7 — is the gain carried by one machine/operator?

    Session ids encode the recording machine, so this is directly checkable: drop the
    single most-improved operator and see whether the mean gain survives.
    """
    by_op: dict[str, list[float]] = defaultdict(list)
    for sid in base_ps:
        by_op[operator_of(sid)].append(cand_ps[sid]["f1"] - base_ps[sid]["f1"])
    means = {op: statistics.fmean(v) for op, v in by_op.items()}
    if not means:
        return {"checked": False}
    worst_offender = max(means, key=lambda k: means[k])
    rest = [d for op, v in by_op.items() if op != worst_offender for d in v]
    overall = statistics.fmean([d for v in by_op.values() for d in v])
    survives = bool(rest and statistics.fmean(rest) > 0)
    return {
        "checked": True,
        "mean_delta_f1_by_operator": {k: round(v, 4) for k, v in sorted(means.items())},
        "most_improved_operator": worst_offender,
        "mean_delta_f1_overall": round(overall, 4),
        "mean_delta_f1_excluding_most_improved_operator": (
            round(statistics.fmean(rest), 4) if rest else None),
        "gain_survives_removing_most_improved_operator": survives,
        "n_operators": len(means),
    }


def score(candidate_eval: dict, base_eval: dict, gate: dict, label: str) -> dict:
    p, bp = candidate_eval["pooled"], base_eval["pooled"]
    ps, bps = candidate_eval["per_session"], base_eval["per_session"]
    rob = robustness(bps, ps)
    conc = concentration(bps, ps)
    mach = machine_dominance(bps, ps)
    n_sessions = len(bps)

    checks = {
        "1_f1_gain_at_least_0.02": (p["f1"] - bp["f1"]) >= gate["min_f1_absolute_gain"],
        "2_recall_at_least_0.55": p["recall"] >= gate["min_recall"],
        "3_fragmentation_within_cap":
            p["pct_gt_executions_fragmented"] <= gate["max_fragmentation_pct"],
        "4_under_segmentation_within_cap":
            p["under_segmentation_rate"] <= gate["max_under_segmentation"],
        "5_over_segmentation_within_cap":
            p["over_segmentation_rate"] <= gate["max_over_segmentation"],
        "6_degraded_sessions_within_cap":
            rob["sessions_degraded"] / n_sessions <= gate["max_sessions_degraded_fraction"],
        "7_gain_survives_removing_top3_sessions": conc["gain_survives_removing_top3"],
        "8_no_single_machine_dominance":
            mach.get("gain_survives_removing_most_improved_operator", False),
    }
    return {
        "reference": label,
        "deltas": {
            "f1": round(p["f1"] - bp["f1"], 4),
            "f1_relative_pct": round(100 * (p["f1"] - bp["f1"]) / bp["f1"], 2),
            "recall": round(p["recall"] - bp["recall"], 4),
            "precision": round(p["precision"] - bp["precision"], 4),
            "fragmentation_pct": round(p["pct_gt_executions_fragmented"]
                                       - bp["pct_gt_executions_fragmented"], 2),
            "under_segmentation": round(p["under_segmentation_rate"]
                                        - bp["under_segmentation_rate"], 4),
            "over_segmentation": round(p["over_segmentation_rate"]
                                       - bp["over_segmentation_rate"], 4),
        },
        "robustness": rob,
        "concentration_check": conc,
        "machine_dominance_check": mach,
        "gate_checks": checks,
        "passes_all_gates": all(checks.values()),
        "failed_gates": [k for k, v in checks.items() if not v],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--artifact", required=True, type=Path)
    args = ap.parse_args()

    path = args.artifact / "module2_segmentation_experiment.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    gate = data["promotion_gate"]["thresholds"]
    canonical = data["canonical_baseline_control"]["canonical_pooled"]
    sets = data["feature_sets"]

    scored: dict[str, dict] = {}
    for name, entry in sets.items():
        if name == CONTROL:
            continue
        scored[name] = {}
        for protocol in ("matched", "locked"):
            cand = entry["protocols"][protocol]["eval"]
            control = sets[CONTROL]["protocols"][protocol]["eval"]
            scored[name][protocol] = {
                "pooled": cand["pooled"],
                "vs_control": score(cand, control, gate,
                                    f"{CONTROL} ({protocol} protocol)"),
                "f1_vs_canonical_locked": round(cand["pooled"]["f1"] - canonical["f1"], 4),
            }

    winners = [n for n, v in scored.items()
               if v["matched"]["vs_control"]["passes_all_gates"]
               and v["locked"]["vs_control"]["passes_all_gates"]]
    decision = ("PROMOTE " + max(winners,
                                 key=lambda n: scored[n]["matched"]["pooled"]["f1"])
                if winners else "MODULE 2 SEGMENTATION IS NOT PROMOTED")

    best = max(scored, key=lambda n: scored[n]["matched"]["pooled"]["f1"])
    out = {
        "module": "Module 2 — Adaptive Evidence-Guided Reconstruction & Automation",
        "gate_registered_before_candidates_were_scored": True,
        "gate_thresholds": gate,
        "gate_source": ("Day-7 segmentation-challenge gate, reused verbatim so Module 2 "
                        "is held to the standard the previous challenge was held to. "
                        "Not adjusted after seeing results."),
        "canonical_locked_pooled": canonical,
        "candidates": scored,
        "candidates_passing_all_gates": winners,
        "decision": decision,
        "best_candidate_by_f1": best,
        "module1_status": "CANONICAL / LOCKED — unchanged",
        "module2_status": ("EXPERIMENTAL — NOT PROMOTED" if not winners
                           else "PROMOTION CANDIDATE — requires review before any "
                                "canonical artifact is regenerated"),
    }
    out_path = args.artifact / "module2_promotion_gate.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"{'candidate':<44}{'proto':<9}{'F1':<9}{'dF1 ctrl':<10}{'gates'}")
    for name, v in scored.items():
        for protocol in ("matched", "locked"):
            s = v[protocol]
            print(f"{name:<44}{protocol:<9}{s['pooled']['f1']:<9.4f}"
                  f"{s['vs_control']['deltas']['f1']:<+10.4f}"
                  f"{'PASS' if s['vs_control']['passes_all_gates'] else 'fail: ' + ','.join(s['vs_control']['failed_gates'])}")
    print(f"\nDECISION: {decision}")
    print(f"Wrote {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
