#!/usr/bin/env python3
"""Day 7 — can simpler, auditable segmentation beat the locked baseline?

WHY THIS EXPERIMENT
-------------------
Segmentation is upstream of every downstream conclusion in this project. The locked
architecture reaches F1 0.3440 using a union of two learned models, a four-rule
reconstruction layer and a protection layer. Before adding anything more, the honest
question is the opposite one: does a handful of explicit conditions do as well? If it
does, the existing machinery is not earning its complexity. If it does not, that is
positive evidence FOR the locked design.

CANDIDATES (cheapest first, by design)
--------------------------------------
  baseline  locked Combined, reproduced and verified against the Day-2 artifact
  C1        two-threshold rule: (context change AND gap > s) OR (gap > l)
  C2        C1 + demote-only continuity veto on N=10 event-type jaccard
  C3        C1 where a *familiar* app hop does not count as a context change
  C4        C1 with separate thresholds where browser-domain coverage is degraded

VALIDATION
----------
Leave-one-session-out. For each held-out session, parameters are chosen on the other
62 sessions pooled, then applied to the held-out session. No session's own ground
truth ever informs its own prediction. The sweep is made cheap by precomputing
per-session (tp, fp, fn) for every parameter combination once, so each fold is a sum
over counts rather than a re-scan of the data.

Candidate predictions are scored with the LOCKED evaluator
(`evaluate_boundary_set`), so every number is directly comparable to the baseline.

Nothing canonical is written. Output goes to reports/day7/.

Usage:
    python scripts/run_segmentation_improvement_experiment.py \
        --dataset dataset_a --out reports/day7 \
        --baseline reports/day2/protected_boundary_experiment_dataset_a.json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from procmine.experiments.rule_boundary import (  # noqa: E402
    SessionArrays, confusion, f1_from_counts, predict_rule,
    predict_rule_instrumentation_aware, predict_rule_with_continuity_veto,
    predict_rule_with_motif,
)
from procmine.segmentation.context_features import extract_trajectory_features  # noqa: E402

# ---- parameter grids -------------------------------------------------------
# Gap values span the human-pause scales Day-2 measured: real boundaries had a
# median gap of 526 ms and mid-task pauses a median of 2,627 ms, so the grid must
# cover both sides of that overlap rather than only the comfortable end.
SMALL_GAPS = [250, 500, 1000, 2000, 3000, 5000]
LARGE_GAPS = [5000, 10000, 20000, 30000, 60000, 120000]
VETO_THRESHOLDS = [0.5, 0.6, 0.7, 0.8]
MOTIF_MIN_COUNTS = [10, 50, 200]
COVERAGE_FLOOR = 0.40  # Day-4 diagnostic threshold, reused not re-selected


def _load_locked():
    spec = importlib.util.spec_from_file_location(
        "locked_experiment", ROOT / "scripts" / "run_protected_boundary_experiment.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["locked_experiment"] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_ensemble():
    spec = importlib.util.spec_from_file_location(
        "ensemble_experiment", ROOT / "scripts" / "run_boundary_ensemble_experiment.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ensemble_experiment"] = mod
    spec.loader.exec_module(mod)
    return mod


def build_arrays(per_session: dict, sid: str) -> SessionArrays:
    d = per_session[sid]
    feats, canonical = d["feats"], d["canonical"]
    n_with_domain = sum(1 for e in canonical if e.browser_domain)
    coverage = n_with_domain / len(canonical) if canonical else 0.0
    pairs = []
    for i in range(len(feats)):
        pairs.append((canonical[i].application, canonical[i + 1].application))
    return SessionArrays(
        session_id=sid,
        delta_t_ms=tuple(f.delta_t_ms for f in feats),
        application_changed=tuple(f.application_changed for f in feats),
        browser_domain_changed=tuple(f.browser_domain_changed for f in feats),
        window_title_changed=tuple(f.window_title_changed for f in feats),
        interaction_category_changed=tuple(f.interaction_category_changed for f in feats),
        chunk_boundary=tuple(f.chunk_boundary for f in feats),
        app_pair=tuple(pairs),
        browser_domain_coverage=coverage,
    )


def dist(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "mean": round(statistics.fmean(values), 4),
        "median": round(statistics.median(values), 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "stdev": round(statistics.pstdev(values), 4),
    }


def loso_rule(
    arrays: dict, labels: dict, session_ids: list[str], predictor, param_grid: list[dict]
) -> tuple[dict, dict]:
    """Generic LOSO parameter selection.

    Returns (predictions_by_session, chosen_params_by_session). Counts for every
    (session, params) pair are computed once; each fold then sums the counts of the
    62 training sessions and picks the best-F1 parameter set.
    """
    counts: dict[int, dict[str, tuple[int, int, int]]] = {}
    preds_cache: dict[int, dict[str, list[bool]]] = {}
    for pi, params in enumerate(param_grid):
        counts[pi], preds_cache[pi] = {}, {}
        for sid in session_ids:
            p = predictor(arrays[sid], params, sid)
            preds_cache[pi][sid] = p
            counts[pi][sid] = confusion(p, labels[sid])

    predictions, chosen = {}, {}
    for held in session_ids:
        best_pi, best_f1 = None, -1.0
        for pi in range(len(param_grid)):
            tp = fp = fn = 0
            for sid in session_ids:
                if sid == held:
                    continue
                a, b, c = counts[pi][sid]
                tp += a
                fp += b
                fn += c
            f1 = f1_from_counts(tp, fp, fn)
            if f1 > best_f1:
                best_f1, best_pi = f1, pi
        predictions[held] = preds_cache[best_pi][held]
        chosen[held] = param_grid[best_pi]
    return predictions, chosen


def summarize_params(chosen: dict) -> dict:
    """How stable was the LOSO parameter choice? Wild variation means overfitting."""
    keys = sorted({k for v in chosen.values() for k in v})
    out = {}
    for k in keys:
        vals = [v[k] for v in chosen.values() if k in v]
        c = Counter(map(str, vals))
        out[k] = {"most_common": c.most_common(3), "n_distinct": len(c)}
    return out


def robustness(baseline_ps: dict, cand_ps: dict, session_ids: list[str]) -> dict:
    improved = degraded = unchanged = 0
    deltas = []
    for sid in session_ids:
        d = cand_ps[sid]["f1"] - baseline_ps[sid]["f1"]
        deltas.append({"session_id": sid, "delta_f1": round(d, 4),
                       "baseline_f1": round(baseline_ps[sid]["f1"], 4),
                       "candidate_f1": round(cand_ps[sid]["f1"], 4)})
        if d > 0.01:
            improved += 1
        elif d < -0.01:
            degraded += 1
        else:
            unchanged += 1
    deltas.sort(key=lambda x: x["delta_f1"])
    return {
        "sessions_improved": improved,
        "sessions_degraded": degraded,
        "sessions_unchanged": unchanged,
        "delta_f1_distribution": dist([d["delta_f1"] for d in deltas]),
        "worst_5_sessions": deltas[:5],
        "best_5_sessions": deltas[-5:][::-1],
    }


def concentration_check(baseline_ps, cand_ps, session_ids, pooled_delta) -> dict:
    """Does the gain survive dropping the 3 most-improved sessions?

    An aggregate gain carried by two or three sessions is not an improvement to the
    method; it is an improvement to those sessions.
    """
    deltas = sorted(
        ((cand_ps[s]["f1"] - baseline_ps[s]["f1"], s) for s in session_ids), reverse=True
    )
    top3 = [s for _, s in deltas[:3]]
    rest = [s for s in session_ids if s not in top3]
    b_mean = statistics.fmean([baseline_ps[s]["f1"] for s in rest])
    c_mean = statistics.fmean([cand_ps[s]["f1"] for s in rest])
    return {
        "top_3_improved_sessions": top3,
        "mean_session_f1_excluding_top3_baseline": round(b_mean, 4),
        "mean_session_f1_excluding_top3_candidate": round(c_mean, 4),
        "gain_survives_removing_top3": bool(c_mean > b_mean),
        "pooled_f1_delta": round(pooled_delta, 4),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--baseline", required=True, type=Path)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    locked = _load_locked()
    ensemble = _load_ensemble()

    print("loading dataset...", file=sys.stderr)
    per_session = locked.load_dataset(args.dataset)
    session_ids = sorted(per_session)
    print(f"{len(session_ids)} sessions", file=sys.stderr)

    # ---- baseline: reproduce and verify ----------------------------------
    print("reproducing locked baseline (LOSO over V1/V2)...", file=sys.stderr)
    loso = locked.run_loso(per_session, session_ids)
    base_preds = ensemble.combined_predictions(per_session, session_ids, loso)
    base_eval = locked.evaluate_boundary_set(per_session, session_ids, base_preds)

    # The locked baseline is Strategy_Combined specifically -- naming it explicitly
    # rather than taking the first block with a "pooled" key, which is V1.
    artifact = json.loads(args.baseline.read_text(encoding="utf-8"))
    locked_pooled = artifact["systems"]["Strategy_Combined"]["pooled"]
    drift = abs(base_eval["pooled"]["f1"] - locked_pooled["f1"])
    if drift > 1e-9:
        print(f"CONTROL FAILED: baseline F1 drift {drift} "
              f"(reproduced {base_eval['pooled']['f1']}, locked {locked_pooled['f1']})",
              file=sys.stderr)
        return 1
    print(f"CONTROL OK: baseline reproduced exactly, drift {drift}", file=sys.stderr)

    arrays = {sid: build_arrays(per_session, sid) for sid in session_ids}
    labels = {sid: [lt.is_boundary for lt in per_session[sid]["is_boundary_labels"]]
              for sid in session_ids}
    base_ps = base_eval["per_session"]

    # ---- promotion criteria, registered BEFORE any candidate is scored ----
    bp = base_eval["pooled"]
    session_f1s = [base_ps[s]["f1"] for s in session_ids]
    gates = {
        "registered_before_candidates_were_scored": True,
        "baseline_session_f1_distribution": dist(session_f1s),
        "gates": {
            "min_f1_absolute_gain": 0.02,
            "min_recall": 0.55,
            "max_fragmentation_pct": round(bp["pct_gt_executions_fragmented"] + 2.0, 2),
            "max_under_segmentation": round(bp["under_segmentation_rate"] * 2.0, 4),
            "max_over_segmentation": round(bp["over_segmentation_rate"] * 1.25, 4),
            "max_sessions_degraded_fraction": 0.40,
            "gain_must_survive_removing_top3_sessions": True,
        },
        "justification": {
            "min_f1_absolute_gain": (
                "Per-session F1 has a standard deviation of "
                f"{dist(session_f1s)['stdev']}, so a pooled gain smaller than 0.02 is "
                "within the noise this dataset already shows between sessions."
            ),
            "min_recall": (
                "Day-2 measured that pushing fragmentation down requires recall to "
                "collapse to ~0.15-0.21. A floor of 0.55 keeps a detector that still "
                "finds more true boundaries than it misses."
            ),
            "max_fragmentation_pct": "Fragmentation is the metric that motivated the "
                                     "whole Day-2 pivot; it may not get materially worse.",
            "max_under_segmentation": "Doubling under-segmentation means merging "
                                      "genuinely distinct executions -- the failure "
                                      "mode the Day-2 success gate was built to catch.",
            "max_sessions_degraded_fraction": "An aggregate gain that degrades more "
                                              "than 40% of sessions is not robust.",
        },
    }

    results = {"baseline": {"method": "locked Combined (V1 u V2 + Rules 1-4 + "
                                      "Strategy Combined protection)",
                            "validation": "leave-one-session-out",
                            "pooled": bp,
                            "per_session_f1": dist(session_f1s)}}

    candidates: dict[str, dict] = {}

    # ---- C1: two-threshold rule ------------------------------------------
    print("C1: rule sweep...", file=sys.stderr)
    grid1 = [{"small_gap_ms": s, "large_gap_ms": l}
             for s in SMALL_GAPS for l in LARGE_GAPS if l > s]
    c1_preds, c1_chosen = loso_rule(
        arrays, labels, session_ids,
        lambda a, p, sid: predict_rule(a, **p), grid1,
    )
    candidates["C1_rule_two_threshold"] = {
        "method": "(context change AND gap > small) OR (gap > large)",
        "param_grid_size": len(grid1),
        "chosen_params": summarize_params(c1_chosen),
        "eval": locked.evaluate_boundary_set(per_session, session_ids, c1_preds),
    }

    # ---- C2: rule + continuity veto --------------------------------------
    print("C2: computing trajectory jaccard where it can matter...", file=sys.stderr)
    min_small, min_large = min(SMALL_GAPS), min(LARGE_GAPS)
    jaccard: dict[str, list[float | None]] = {}
    for sid in session_ids:
        a, canonical = arrays[sid], per_session[sid]["canonical"]
        j: list[float | None] = [None] * len(a)
        for i in range(len(a)):
            gap = a.delta_t_ms[i]
            ctx = a.application_changed[i] or a.browser_domain_changed[i]
            if (ctx and gap > min_small) or (gap > min_large):
                j[i] = extract_trajectory_features(canonical, i, 10).event_type_jaccard
        jaccard[sid] = j

    grid2 = [{"small_gap_ms": s, "large_gap_ms": l, "veto_above": v}
             for s in SMALL_GAPS for l in LARGE_GAPS if l > s for v in VETO_THRESHOLDS]
    c2_preds, c2_chosen = loso_rule(
        arrays, labels, session_ids,
        lambda a, p, sid: predict_rule_with_continuity_veto(a, jaccard=jaccard[sid], **p),
        grid2,
    )
    candidates["C2_rule_plus_continuity_veto"] = {
        "method": "C1, then demote a flagged boundary when N=10 event-type jaccard "
                  ">= veto threshold (demote-only)",
        "param_grid_size": len(grid2),
        "chosen_params": summarize_params(c2_chosen),
        "eval": locked.evaluate_boundary_set(per_session, session_ids, c2_preds),
    }

    # ---- C3: process-aware motif -----------------------------------------
    print("C3: motif sweep...", file=sys.stderr)
    pair_counts_by_session = {
        sid: Counter(a.app_pair[i] for i in range(len(a))
                     if a.application_changed[i])
        for sid, a in arrays.items()
    }

    def motif_predictor(a, p, sid):
        # common pairs fitted on TRAINING sessions only -- rebuilt per fold below
        return predict_rule_with_motif(a, common_pairs=p["_pairs"],
                                       small_gap_ms=p["small_gap_ms"],
                                       large_gap_ms=p["large_gap_ms"])

    c3_preds, c3_chosen = {}, {}
    grid3_params = [{"small_gap_ms": s, "large_gap_ms": l, "min_count": m}
                    for s in SMALL_GAPS for l in LARGE_GAPS if l > s
                    for m in MOTIF_MIN_COUNTS]
    for held in session_ids:
        train = [s for s in session_ids if s != held]
        total = Counter()
        for s in train:
            total.update(pair_counts_by_session[s])
        best, best_f1 = None, -1.0
        for params in grid3_params:
            pairs = frozenset(k for k, c in total.items() if c >= params["min_count"])
            tp = fp = fn = 0
            for s in train:
                pr = predict_rule_with_motif(
                    arrays[s], common_pairs=pairs,
                    small_gap_ms=params["small_gap_ms"],
                    large_gap_ms=params["large_gap_ms"])
                a_, b_, c_ = confusion(pr, labels[s])
                tp += a_; fp += b_; fn += c_
            f1 = f1_from_counts(tp, fp, fn)
            if f1 > best_f1:
                best_f1, best = f1, (params, pairs)
        params, pairs = best
        c3_preds[held] = predict_rule_with_motif(
            arrays[held], common_pairs=pairs,
            small_gap_ms=params["small_gap_ms"], large_gap_ms=params["large_gap_ms"])
        c3_chosen[held] = {k: v for k, v in params.items()}
    candidates["C3_rule_plus_motif"] = {
        "method": "C1, but an app hop that is frequent in the TRAINING sessions does "
                  "not count as a context change (motif = intra-process hop)",
        "param_grid_size": len(grid3_params),
        "chosen_params": summarize_params(c3_chosen),
        "eval": locked.evaluate_boundary_set(per_session, session_ids, c3_preds),
    }

    # ---- C4: instrumentation-aware ---------------------------------------
    print("C4: instrumentation-aware sweep...", file=sys.stderr)
    grid4 = [{"small_gap_ms": s, "large_gap_ms": l,
              "degraded_small_gap_ms": ds, "degraded_large_gap_ms": l,
              "coverage_floor": COVERAGE_FLOOR}
             for s in SMALL_GAPS for l in LARGE_GAPS if l > s
             for ds in SMALL_GAPS]
    c4_preds, c4_chosen = loso_rule(
        arrays, labels, session_ids,
        lambda a, p, sid: predict_rule_instrumentation_aware(a, **p), grid4,
    )
    n_degraded = sum(1 for a in arrays.values()
                     if a.browser_domain_coverage < COVERAGE_FLOOR)
    candidates["C4_instrumentation_aware"] = {
        "method": "C1 with a separate small-gap threshold in sessions whose "
                  f"browser-domain coverage is below {COVERAGE_FLOOR}",
        "n_sessions_treated_as_degraded": n_degraded,
        "param_grid_size": len(grid4),
        "chosen_params": summarize_params(c4_chosen),
        "eval": locked.evaluate_boundary_set(per_session, session_ids, c4_preds),
    }

    # ---- gate evaluation --------------------------------------------------
    g = gates["gates"]
    for name, c in candidates.items():
        p = c["eval"]["pooled"]
        ps = c["eval"]["per_session"]
        rob = robustness(base_ps, ps, session_ids)
        conc = concentration_check(base_ps, ps, session_ids, p["f1"] - bp["f1"])
        checks = {
            "f1_gain_at_least_0.02": (p["f1"] - bp["f1"]) >= g["min_f1_absolute_gain"],
            "recall_at_least_0.55": p["recall"] >= g["min_recall"],
            "fragmentation_within_cap": p["pct_gt_executions_fragmented"] <= g["max_fragmentation_pct"],
            "under_segmentation_within_cap": p["under_segmentation_rate"] <= g["max_under_segmentation"],
            "over_segmentation_within_cap": p["over_segmentation_rate"] <= g["max_over_segmentation"],
            "degraded_sessions_within_cap": (
                rob["sessions_degraded"] / len(session_ids) <= g["max_sessions_degraded_fraction"]
            ),
            "gain_survives_removing_top3": conc["gain_survives_removing_top3"],
        }
        c["per_session_f1"] = dist([ps[s]["f1"] for s in session_ids])
        c["robustness"] = rob
        c["concentration_check"] = conc
        c["gate_checks"] = checks
        c["passes_all_gates"] = all(checks.values())
        c["deltas_vs_baseline"] = {
            "f1": round(p["f1"] - bp["f1"], 4),
            "f1_relative_pct": round(100 * (p["f1"] - bp["f1"]) / bp["f1"], 2),
            "recall": round(p["recall"] - bp["recall"], 4),
            "precision": round(p["precision"] - bp["precision"], 4),
            "fragmentation_pct": round(
                p["pct_gt_executions_fragmented"] - bp["pct_gt_executions_fragmented"], 2),
            "under_segmentation": round(
                p["under_segmentation_rate"] - bp["under_segmentation_rate"], 4),
            "over_segmentation": round(
                p["over_segmentation_rate"] - bp["over_segmentation_rate"], 4),
        }

    winners = [n for n, c in candidates.items() if c["passes_all_gates"]]
    decision = "PROMOTE " + max(
        winners, key=lambda n: candidates[n]["eval"]["pooled"]["f1"]
    ) if winners else "RETAIN LOCKED BASELINE"

    out = {
        "experiment": "Day-7 segmentation improvement — rule-based and process-aware candidates",
        "question": "Can simpler, auditable evidence beat the locked segmentation?",
        "validation": "leave-one-session-out; parameters chosen on training sessions only",
        "no_leakage_note": "For every fold the parameters (and, for C3, the motif set) "
                           "are fitted on the 62 training sessions and applied to the "
                           "held-out session. No session's ground truth informs its own "
                           "prediction.",
        "baseline_control": {"reproduced": True, "max_abs_f1_drift": drift},
        "promotion_criteria": gates,
        "baseline": results["baseline"],
        "candidates": candidates,
        "decision": decision,
        "candidates_passing_all_gates": winners,
    }
    path = args.out / "segmentation_comparison.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n{'candidate':<34}{'F1':<9}{'dF1':<9}{'recall':<9}{'frag%':<9}{'under':<9}{'over':<9}gates")
    print(f"{'baseline (locked)':<34}{bp['f1']:<9.4f}{'--':<9}{bp['recall']:<9.4f}"
          f"{bp['pct_gt_executions_fragmented']:<9.2f}{bp['under_segmentation_rate']:<9.4f}"
          f"{bp['over_segmentation_rate']:<9.4f}--")
    for n, c in candidates.items():
        p, d = c["eval"]["pooled"], c["deltas_vs_baseline"]
        print(f"{n:<34}{p['f1']:<9.4f}{d['f1']:<+9.4f}{p['recall']:<9.4f}"
              f"{p['pct_gt_executions_fragmented']:<9.2f}{p['under_segmentation_rate']:<9.4f}"
              f"{p['over_segmentation_rate']:<9.4f}"
              f"{'PASS' if c['passes_all_gates'] else 'fail'}")
    print(f"\nDECISION: {decision}")
    print(f"Wrote {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
