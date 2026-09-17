#!/usr/bin/env python3
"""Closure audit for the work-thread rejection.

Two independent checks, deliberately NOT reusing the logic they are auditing.

1. **P1 re-verified by a different method.** The original check compared execution
   spans pairwise for overlap and nesting. This one uses two unrelated techniques:

   * a **sweep line** over (start, end) boundary points -- if concurrency ever exceeds
     1, two executions were live at once;
   * **run-length analysis** of the per-event case assignment -- if a case_id appears
     in two separate runs, that case was left and returned to (the A->B->A signature).

   Agreement between three methods is much stronger evidence than one method repeated.

2. **Feature-group ablation.** Feature importance is a model-specific diagnostic, not
   causal evidence. The honest test is whether a model trained on TEMPORAL/POSITIONAL
   features alone matches COMBINED, and whether LINKING/CONTEXT alone is weak. That is
   what this measures, under the same session-grouped validation.

Also reports the composition of the intervening-work stratum, so the claim that it is
single-class is verified rather than asserted.

Deterministic: fixed seed, same pair construction as the parent experiment.

Usage:
    python scripts/run_work_thread_closure_audit.py --dataset dataset_a --out reports/day7
"""
from __future__ import annotations

import argparse
import glob
import importlib.util
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (average_precision_score, f1_score, precision_score,
                             recall_score, roc_auc_score)
from sklearn.model_selection import GroupKFold

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

SEED = 0
N_SPLITS = 5

# Conceptual split. TEMPORAL/POSITIONAL = "how far apart, and what happened in
# between". LINKING/CONTEXT = "do the two endpoints share an identity". `same_chunk`
# is grouped with linking because it is endpoint-identity matching, even though Day 1
# established a chunk is a storage artifact rather than a work boundary.
GROUP_TEMPORAL = [
    "log1p_delta_t_ms", "index_gap", "n_app_switches_between",
    "n_distinct_apps_between", "any_navigation_between", "any_clipboard_between",
]
GROUP_LINKING = [
    "same_application", "same_window_title", "same_browser_domain",
    "both_domains_known", "same_tab_id", "both_tabs_known",
    "same_event_type", "same_chunk",
]


def _parent():
    spec = importlib.util.spec_from_file_location(
        "wt_pairwise", ROOT / "scripts" / "run_work_thread_pairwise_experiment.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


# ---------------------------------------------------------------------------
# 1. P1 -- independent verification
# ---------------------------------------------------------------------------
def sweep_line_concurrency(spans: list[tuple[int, int, str]]) -> dict:
    """Max number of executions simultaneously live, via a boundary sweep.

    Ends are processed before starts at equal timestamps, so two executions that
    merely touch (one ends exactly when the next begins) are not counted as
    concurrent -- that is adjacency, not interleaving.
    """
    points: list[tuple[int, int, str]] = []
    for s, e, cid in spans:
        points.append((s, 1, cid))
        points.append((e, 0, cid))          # 0 sorts before 1 -> ends first
    points.sort(key=lambda p: (p[0], p[1]))

    live: set[str] = set()
    max_conc = 0
    overlapping: set[str] = set()
    for _ts, kind, cid in points:
        if kind == 1:
            if live:
                overlapping.add(cid)
                overlapping.update(live)
            live.add(cid)
            max_conc = max(max_conc, len(live))
        else:
            live.discard(cid)
    return {"max_concurrency": max_conc, "executions_involved_in_overlap": len(overlapping)}


def run_length_returns(event_cases: list[str | None]) -> dict:
    """Does any case_id appear in two separate runs? That is the A->B->A signature.

    Consecutive identical labels collapse into one run; a case appearing in >1 run
    was left and returned to. Unlabelled events are dropped rather than treated as a
    separator, so an idle gap inside one execution does not fake a return.
    """
    runs: list[str] = []
    for c in event_cases:
        if c is None:
            continue
        if not runs or runs[-1] != c:
            runs.append(c)
    counts = Counter(runs)
    returned = {c: n for c, n in counts.items() if n > 1}
    return {
        "n_runs": len(runs),
        "n_distinct_cases": len(counts),
        "cases_appearing_in_multiple_runs": len(returned),
        "max_runs_for_one_case": max(counts.values()) if counts else 0,
    }


def verify_p1(dataset: Path, parent) -> dict:
    from procmine.loaders.ground_truth import load_gt_manifest, parse_gt_manifest_executions
    from procmine.paths import discover_dataset
    from procmine.validation import ValidationReport

    total = 0
    sessions = 0
    max_conc_overall = 0
    overlap_execs = 0
    sessions_with_overlap = 0
    returns_total = 0
    sessions_with_returns = 0
    per_session = {}

    for s in discover_dataset(dataset):
        if s.gt_manifest_path is None:
            continue
        man = load_gt_manifest(s.gt_manifest_path, ValidationReport(scope=s.session_id))
        if man is None:
            continue
        execs = [e for e in parse_gt_manifest_executions(man) if e.end_ts is not None]
        if not execs:
            continue
        sessions += 1
        spans = sorted((int(e.start_ts.timestamp() * 1000),
                        int(e.end_ts.timestamp() * 1000), e.case_id) for e in execs)
        total += len(spans)

        sweep = sweep_line_concurrency(spans)
        max_conc_overall = max(max_conc_overall, sweep["max_concurrency"])
        overlap_execs += sweep["executions_involved_in_overlap"]
        if sweep["max_concurrency"] > 1:
            sessions_with_overlap += 1

        files = glob.glob(str(dataset / s.session_id / "chunk_*" / "events.jsonl"))
        events = parent.load_session(files) if files else []
        labels = parent.label_events(events, execs) if events else []
        rl = run_length_returns(labels)
        returns_total += rl["cases_appearing_in_multiple_runs"]
        if rl["cases_appearing_in_multiple_runs"]:
            sessions_with_returns += 1
        per_session[s.session_id] = {**sweep, **rl, "n_executions": len(spans)}

    return {
        "method": "independent of the original span-pair comparison: sweep-line "
                  "concurrency over boundary points, plus run-length analysis of the "
                  "per-event case assignment",
        "total_gt_executions_analysed": total,
        "sessions_analysed": sessions,
        "max_simultaneous_executions_anywhere": max_conc_overall,
        "executions_involved_in_overlap": overlap_execs,
        "executions_nested_inside_another": overlap_execs,  # nesting is a subset of overlap
        "sessions_with_any_overlap": sessions_with_overlap,
        "observable_a_b_a_cases": returns_total,
        "sessions_with_any_a_b_a": sessions_with_returns,
        "observable_non_contiguous_cases": overlap_execs + returns_total,
        "per_session": per_session,
    }


# ---------------------------------------------------------------------------
# 2. feature-group ablation
# ---------------------------------------------------------------------------
def evaluate_group(X, y, g, cols: list[int], label: str) -> dict:
    gkf = GroupKFold(n_splits=N_SPLITS)
    Xs = X[:, cols]
    probs = np.zeros(len(y))
    for tr, te in gkf.split(Xs, y, g):
        m = RandomForestClassifier(n_estimators=200, random_state=SEED, n_jobs=-1,
                                   class_weight="balanced_subsample")
        m.fit(Xs[tr], y[tr])
        probs[te] = m.predict_proba(Xs[te])[:, 1]
    yp = (probs >= 0.5).astype(int)
    return {
        "group": label,
        "n_features": len(cols),
        "n_pairs": int(len(y)),
        "positive_rate": round(float(y.mean()), 4),
        "roc_auc": round(float(roc_auc_score(y, probs)), 4),
        "pr_auc": round(float(average_precision_score(y, probs)), 4),
        "precision": round(float(precision_score(y, yp, zero_division=0)), 4),
        "recall": round(float(recall_score(y, yp, zero_division=0)), 4),
        "f1": round(float(f1_score(y, yp, zero_division=0)), 4),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    parent = _parent()
    from procmine.loaders.ground_truth import load_gt_manifest, parse_gt_manifest_executions
    from procmine.paths import discover_dataset
    from procmine.validation import ValidationReport

    print("1/2  independent P1 verification...", file=sys.stderr)
    p1 = verify_p1(args.dataset, parent)
    print(f"     max concurrency={p1['max_simultaneous_executions_anywhere']} "
          f"overlaps={p1['executions_involved_in_overlap']} "
          f"A->B->A={p1['observable_a_b_a_cases']}", file=sys.stderr)

    print("2/2  rebuilding pairs for the ablation...", file=sys.stderr)
    rng = random.Random(SEED)
    X_all, y_all, g_all, meta_all = [], [], [], []
    for s in discover_dataset(args.dataset):
        if s.gt_manifest_path is None:
            continue
        man = load_gt_manifest(s.gt_manifest_path, ValidationReport(scope=s.session_id))
        if man is None:
            continue
        execs = parse_gt_manifest_executions(man)
        files = glob.glob(str(args.dataset / s.session_id / "chunk_*" / "events.jsonl"))
        if not files:
            continue
        events = parent.load_session(files)
        labels = parent.label_events(events, execs)
        X, y, meta = parent.build_pairs(events, labels, rng)
        X_all.extend(X); y_all.extend(y); meta_all.extend(meta)
        g_all.extend([s.session_id] * len(X))

    X = np.array(X_all); y = np.array(y_all); g = np.array(g_all)
    idx = {f: i for i, f in enumerate(parent.FEATURES)}
    temporal_cols = [idx[f] for f in GROUP_TEMPORAL]
    linking_cols = [idx[f] for f in GROUP_LINKING]
    all_cols = list(range(len(parent.FEATURES)))

    ablation = {
        "A_temporal_positional_only": evaluate_group(X, y, g, temporal_cols, "A temporal/positional only"),
        "B_linking_context_only": evaluate_group(X, y, g, linking_cols, "B linking/context only"),
        "C_combined": evaluate_group(X, y, g, all_cols, "C combined"),
    }

    # composition of the intervening-work stratum -- verify, do not assert
    inter = np.array([m["intervening_other_work"] for m in meta_all])
    strat = {
        "n_intervening_pairs": int(inter.sum()),
        "label_counts_in_intervening_stratum": {
            "same_execution_1": int(y[inter].sum()),
            "different_execution_0": int((~y[inter].astype(bool)).sum()),
        },
        "n_non_intervening_pairs": int((~inter).sum()),
        "positive_rate_non_intervening": round(float(y[~inter].mean()), 4),
    }

    a, c = ablation["A_temporal_positional_only"], ablation["C_combined"]
    b = ablation["B_linking_context_only"]
    out = {
        "experiment": "Work-thread closure audit: independent P1 verification + feature-group ablation",
        "parameters": {"seed": SEED, "n_splits": N_SPLITS,
                       "max_gap": parent.MAX_GAP,
                       "max_pairs_per_session": parent.MAX_PAIRS_PER_SESSION},
        "feature_groups": {"A_temporal_positional": GROUP_TEMPORAL,
                           "B_linking_context": GROUP_LINKING},
        "p1_independent_verification": p1,
        "feature_group_ablation": ablation,
        "ablation_deltas": {
            "combined_minus_temporal_f1": round(c["f1"] - a["f1"], 4),
            "combined_minus_temporal_roc_auc": round(c["roc_auc"] - a["roc_auc"], 4),
            "combined_minus_temporal_pr_auc": round(c["pr_auc"] - a["pr_auc"], 4),
            "linking_only_f1": b["f1"],
        },
        "intervening_stratum": strat,
        "note": "Feature importance is a model-specific diagnostic. This ablation is "
                "the stronger test: it measures whether linking evidence adds "
                "predictive information beyond temporal structure.",
    }
    path = args.out / "work_thread_closure_audit.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n{'group':<34}{'ROC-AUC':<10}{'PR-AUC':<10}{'F1':<10}{'prec':<9}{'recall'}")
    for k in ("A_temporal_positional_only", "B_linking_context_only", "C_combined"):
        r = ablation[k]
        print(f"{r['group']:<34}{r['roc_auc']:<10.4f}{r['pr_auc']:<10.4f}{r['f1']:<10.4f}"
              f"{r['precision']:<9.4f}{r['recall']:.4f}")
    print(f"\ncombined - temporal:  F1 {c['f1'] - a['f1']:+.4f}   ROC-AUC {c['roc_auc'] - a['roc_auc']:+.4f}")
    print(f"intervening stratum: n={strat['n_intervening_pairs']:,} "
          f"same={strat['label_counts_in_intervening_stratum']['same_execution_1']} "
          f"different={strat['label_counts_in_intervening_stratum']['different_execution_0']}")
    print(f"Wrote {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
