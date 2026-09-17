#!/usr/bin/env python3
"""Day 6 · Module 2 — does adaptive evidence add information to the locked segmentation?

THE QUESTION
------------
Module 1 segments using absolute timing and contextual-change signals. Module 2 asks
whether two *different* kinds of evidence add information on top of that:

  H1  operator-normalized timing — the same pause means different things for operators
      who work at different speeds, so normalize each gap by that operator's own
      distribution.
  H2  content drift — Module 1 knows only whether screen text was *present*; it never
      asks whether the content *changed*.

WHAT IS AND IS NOT VARIED (this is the fairness control, Rule 24)
----------------------------------------------------------------
Only the classifier feature matrices change. The entire downstream is the LOCKED code,
called unmodified: candidate union, reconstruction Rules 1-4, the Strategy_Combined
protection layer, and the evaluator. An `M1_compatible` control runs through the exact
same harness as the Module 2 candidates, so any difference is attributable to the added
columns rather than to a difference in protocol.

Two threshold protocols are reported, because either one alone invites a fair objection:

  * `matched`  every feature set — including the M1 control — selects its V1/V2
               thresholds by the same rule (max pooled F1 over leave-one-session-out
               probabilities). This is the locked project's own model-selection method,
               applied uniformly. Reusing Module 1's thresholds for a model whose
               probability scale has shifted would handicap Module 2.
  * `locked`   every feature set reuses Module 1's thresholds (0.9078 / 0.8860).
               Reported because re-selecting thresholds is itself a degree of freedom.

LEAKAGE CONTROL
---------------
Operator baselines are fitted on TRAINING SESSIONS ONLY, refitted inside every fold.
The held-out session's own timing distribution never contributes to the feature used to
predict it. No ground truth is used as a feature anywhere: not process_code, case_id,
GT spans, GT boundaries, nor `dwell_scale` (which lives in the GT manifest).

Nothing canonical is written. Output goes to reports/day6/module2/.

Usage:
    python scripts/run_module2_segmentation_experiment.py \
        --dataset dataset_a --out reports/day6/module2 \
        --baseline reports/day2/protected_boundary_experiment_dataset_a.json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from procmine.module2.features import (  # noqa: E402
    FEATURE_SET_M1, FEATURE_SET_M2A, FEATURE_SET_M2B, FEATURE_SET_M2C, FEATURE_SETS,
    baseline_for, compute_operator_baselines, content_drift, extra_feature_names,
    operator_of,
)
from procmine.segmentation.model import make_pipeline  # noqa: E402

LOCKED_V1_THRESHOLD = 0.9078
LOCKED_V2_THRESHOLD = 0.8860
_MAD_FLOOR = 1e-6
# Threshold grid for the matched protocol. Dense enough to find a real optimum,
# coarse enough that the sweep is not itself a fitting procedure.
THRESHOLD_GRID = [round(x, 4) for x in np.arange(0.50, 0.995, 0.005)]


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def dist(values) -> dict:
    values = [v for v in values if v is not None]
    if not values:
        return {"n": 0}
    return {"n": len(values), "mean": round(statistics.fmean(values), 4),
            "median": round(statistics.median(values), 4),
            "min": round(min(values), 4), "max": round(max(values), 4),
            "stdev": round(statistics.pstdev(values), 4) if len(values) > 1 else 0.0}


def f1_from_counts(tp: int, fp: int, fn: int) -> float:
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    return 2 * p * r / (p + r) if (p + r) else 0.0


# --- Module 2 feature assembly ---------------------------------------------

def precompute_m2_inputs(per_session: dict, session_ids: list[str]) -> tuple[dict, dict, dict]:
    """Per-transition raw quantities that do not depend on the fold.

    Content drift is fold-independent (it reads only raw events). The operator
    z-score is NOT — it depends on training-fold baselines — so only its input
    (the log gap) is precomputed here.
    """
    drift_by_session, log_gaps, avail_counts = {}, {}, Counter()
    for sid in session_ids:
        d = per_session[sid]
        canonical, feats = d["canonical"], d["feats"]
        drift = np.zeros(len(feats), dtype=float)
        avail = np.zeros(len(feats), dtype=float)
        for i in range(len(feats)):
            v, ok = content_drift(canonical, i)
            drift[i] = v
            avail[i] = 1.0 if ok else 0.0
        drift_by_session[sid] = (drift, avail)
        log_gaps[sid] = [f.log1p_delta_t_ms for f in feats]
        avail_counts["available"] += int(avail.sum())
        avail_counts["total"] += len(feats)
    return drift_by_session, log_gaps, avail_counts


def build_matrices(per_session, sid, feature_set, baselines, drift_by_session):
    """Locked Module 1 columns, with Module 2 columns APPENDED (never reordered)."""
    d = per_session[sid]
    if feature_set == FEATURE_SET_M1:
        return d["X_v1"], d["X_v2"]

    cols = []
    if feature_set in (FEATURE_SET_M2A, FEATURE_SET_M2C):
        b = baseline_for(baselines, sid)
        lg = np.asarray([f.log1p_delta_t_ms for f in d["feats"]], dtype=float)
        cols.append((lg - b.median_log_gap) / max(b.mad_log_gap, _MAD_FLOOR))
    if feature_set in (FEATURE_SET_M2B, FEATURE_SET_M2C):
        drift, avail = drift_by_session[sid]
        cols.append(drift)
        cols.append(avail)
    extra = np.column_stack(cols)
    return np.hstack([d["X_v1"], extra]), np.hstack([d["X_v2"], extra])


def run_loso_featureset(per_session, session_ids, feature_set, drift_by_session, log_gaps):
    """Leave-one-session-out probabilities for V1 and V2 under one feature set.

    Operator baselines are recomputed from the training sessions inside every fold.
    """
    v1_prob, v2_score = {}, {}
    baseline_sources = Counter()

    y_v1_by_sid = {sid: np.array([1 if lt.is_boundary else 0
                                  for lt in per_session[sid]["is_boundary_labels"]])
                   for sid in session_ids}

    for held in session_ids:
        train = [s for s in session_ids if s != held]
        baselines = compute_operator_baselines(log_gaps, train)  # FOLD-SAFE
        for b in baselines.values():
            baseline_sources[b.source] += 1

        mats = {s: build_matrices(per_session, s, feature_set, baselines, drift_by_session)
                for s in session_ids}

        # --- V1: boundary-first ---
        X_tr = np.vstack([mats[s][0] for s in train])
        y_tr = np.concatenate([y_v1_by_sid[s] for s in train])
        pipe = make_pipeline()
        pipe.fit(X_tr, y_tr)
        v1_prob[held] = pipe.predict_proba(mats[held][0])[:, 1]

        # --- V2: continuity, excluded rows dropped exactly as the locked run does ---
        X2_tr, y2_tr = [], []
        for s in train:
            X2 = mats[s][1]
            for x, cl in zip(X2, per_session[s]["clabels"]):
                if cl.excluded:
                    continue
                X2_tr.append(x)
                y2_tr.append(cl.continuity_label)
        pipe2 = make_pipeline()
        pipe2.fit(np.asarray(X2_tr), np.asarray(y2_tr))
        v2_score[held] = 1.0 - pipe2.predict_proba(mats[held][1])[:, 1]

    return v1_prob, v2_score, baseline_sources


def select_threshold(prob_by_session, labels_by_session, session_ids) -> tuple[float, float]:
    """Max pooled boundary-F1 over the LOSO probabilities.

    This is the locked project's own model-selection method (a global analytical
    threshold over out-of-fold evidence), applied identically to every feature set so
    no candidate gets a protocol advantage.
    """
    best_t, best_f1 = THRESHOLD_GRID[0], -1.0
    for t in THRESHOLD_GRID:
        tp = fp = fn = 0
        for sid in session_ids:
            pred = prob_by_session[sid] >= t
            lab = labels_by_session[sid]
            tp += int(np.sum(pred & lab))
            fp += int(np.sum(pred & ~lab))
            fn += int(np.sum(~pred & lab))
        f1 = f1_from_counts(tp, fp, fn)
        if f1 > best_f1:
            best_f1, best_t = f1, t
    return best_t, round(best_f1, 6)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--baseline", required=True, type=Path)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    locked = _load("locked_experiment", "run_protected_boundary_experiment.py")
    ensemble = _load("ensemble_experiment", "run_boundary_ensemble_experiment.py")

    t0 = time.time()
    print("loading dataset (locked loader, unmodified)...", file=sys.stderr)
    per_session = locked.load_dataset(args.dataset)
    session_ids = sorted(per_session)
    print(f"{len(session_ids)} sessions in {time.time() - t0:.0f}s", file=sys.stderr)

    # ---- CONTROL: reproduce the canonical baseline exactly -----------------
    print("reproducing locked canonical baseline...", file=sys.stderr)
    loso_locked = locked.run_loso(per_session, session_ids)
    base_preds = ensemble.combined_predictions(per_session, session_ids, loso_locked)
    base_eval = locked.evaluate_boundary_set(per_session, session_ids, base_preds)
    artifact = json.loads(args.baseline.read_text(encoding="utf-8"))
    # Named explicitly: taking the first block with a "pooled" key yields V1 (F1 0.2534).
    canonical_pooled = artifact["systems"]["Strategy_Combined"]["pooled"]
    drift_f1 = abs(base_eval["pooled"]["f1"] - canonical_pooled["f1"])
    if drift_f1 > 1e-9:
        print(f"CONTROL FAILED: canonical F1 drift {drift_f1}", file=sys.stderr)
        return 1
    print(f"CONTROL OK: canonical baseline reproduced, drift {drift_f1}", file=sys.stderr)

    # ---- Module 2 feature inputs ------------------------------------------
    print("precomputing Module 2 feature inputs...", file=sys.stderr)
    drift_by_session, log_gaps, avail_counts = precompute_m2_inputs(per_session, session_ids)
    coverage = avail_counts["available"] / avail_counts["total"]
    print(f"content-drift availability: {avail_counts['available']}/{avail_counts['total']} "
          f"({coverage * 100:.2f}%)", file=sys.stderr)

    labels_by_session = {sid: np.array([lt.is_boundary for lt in
                                        per_session[sid]["is_boundary_labels"]])
                         for sid in session_ids}

    # ---- pre-registered promotion gate, written BEFORE candidates are scored ----
    bp = base_eval["pooled"]
    base_ps = base_eval["per_session"]
    session_f1s = [base_ps[s]["f1"] for s in session_ids]
    gates = {
        "registered_before_candidates_were_scored": True,
        "baseline_session_f1_distribution": dist(session_f1s),
        "thresholds": {
            "min_f1_absolute_gain": 0.02,
            "min_recall": 0.55,
            "max_fragmentation_pct": round(bp["pct_gt_executions_fragmented"] + 2.0, 2),
            "max_under_segmentation": round(bp["under_segmentation_rate"] * 2.0, 4),
            "max_over_segmentation": round(bp["over_segmentation_rate"] * 1.25, 4),
            "max_sessions_degraded_fraction": 0.40,
            "gain_must_survive_removing_top3_sessions": True,
        },
        "justification": (
            "Identical to the Day-7 segmentation-challenge gate, reused rather than "
            "re-derived so Module 2 is held to exactly the standard the previous "
            "challenge was held to. A pooled F1 gain below 0.02 sits inside the "
            "between-session spread this dataset already shows."
        ),
    }

    results = {}
    for feature_set in FEATURE_SETS:
        t1 = time.time()
        print(f"\n--- {feature_set} ---", file=sys.stderr)
        v1_prob, v2_score, baseline_sources = run_loso_featureset(
            per_session, session_ids, feature_set, drift_by_session, log_gaps)

        entry = {"extra_features": extra_feature_names(feature_set),
                 "operator_baseline_sources": dict(baseline_sources),
                 "runtime_seconds": None, "protocols": {}}

        for protocol in ("matched", "locked"):
            if protocol == "matched":
                v1_t, v1_sel_f1 = select_threshold(v1_prob, labels_by_session, session_ids)
                v2_t, v2_sel_f1 = select_threshold(v2_score, labels_by_session, session_ids)
            else:
                v1_t, v2_t = LOCKED_V1_THRESHOLD, LOCKED_V2_THRESHOLD
                v1_sel_f1 = v2_sel_f1 = None

            loso_fs = {
                "v1_preds": {s: (v1_prob[s] >= v1_t) for s in session_ids},
                "v2_preds": {s: (v2_score[s] >= v2_t) for s in session_ids},
            }
            preds = ensemble.combined_predictions(per_session, session_ids, loso_fs)
            ev = locked.evaluate_boundary_set(per_session, session_ids, preds)
            entry["protocols"][protocol] = {
                "v1_threshold": v1_t, "v2_threshold": v2_t,
                "v1_selection_f1": v1_sel_f1, "v2_selection_f1": v2_sel_f1,
                "eval": ev,
            }
            p = ev["pooled"]
            print(f"  {protocol:8s} v1={v1_t:.4f} v2={v2_t:.4f}  F1={p['f1']:.4f} "
                  f"R={p['recall']:.4f} frag={p['pct_gt_executions_fragmented']:.2f} "
                  f"under={p['under_segmentation_rate']:.4f} "
                  f"over={p['over_segmentation_rate']:.4f}", file=sys.stderr)

        entry["runtime_seconds"] = round(time.time() - t1, 1)
        results[feature_set] = entry

    out = {
        "module": "Module 2 — Adaptive Evidence-Guided Reconstruction & Automation",
        "experiment": "Dataset-A segmentation: does adaptive evidence add information?",
        "hypotheses_tested": {
            "H1": "operator-normalized timing reduces false distinctions from operator speed",
            "H2": "content drift adds evidence beyond text presence",
        },
        "validation": "leave-one-session-out; operator baselines refitted per fold on "
                      "training sessions only",
        "fairness_control": "only the classifier feature matrices vary; candidate union, "
                            "Rules 1-4, Strategy_Combined protection and the evaluator are "
                            "the locked Module 1 code, called unmodified",
        "leakage_note": "No GT field is used as a feature (no process_code, case_id, GT "
                        "spans, GT boundaries, or gt_manifest dwell_scale). Operator "
                        "baselines never see the held-out session.",
        "canonical_baseline_control": {
            "reproduced": True,
            "max_abs_f1_drift": drift_f1,
            "canonical_pooled": canonical_pooled,
        },
        "content_drift_coverage": {
            "transitions_with_drift_available": avail_counts["available"],
            "transitions_total": avail_counts["total"],
            "fraction": round(coverage, 6),
            "note": "window form (N=10). The adjacent-event-pair formulation was "
                    "measured first and rejected: 48 of 162,705 transitions (0.03%).",
        },
        "promotion_gate": gates,
        "feature_sets": results,
    }
    path = args.out / "module2_segmentation_experiment.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str),
                    encoding="utf-8")
    print(f"\nWrote {path}", file=sys.stderr)
    print(f"total runtime {time.time() - t0:.0f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
