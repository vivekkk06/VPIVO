#!/usr/bin/env python3
"""Work-thread hypothesis, Steps 3-5: can two events be linked as "same execution"?

THE QUESTION
------------
The work-thread hypothesis replaces per-transition boundary decisions with
relationships between events: if we can tell whether two events belong to the same
unit of work, threads fall out of the graph. Everything downstream (graph, thread
recovery, fragment merging) depends on that pairwise question being answerable.

So this experiment tests it directly, before any graph is built.

WHAT THE SIGNAL AUDIT PREDICTED
-------------------------------
`work_thread_signal_audit.md` found that every *linking* signal the hypothesis needs is
absent or too coarse: no entity identifiers, no clipboard content, text at 0.07%
coverage, browser domain effectively 3-valued, and `tab_id` alive 37.8x longer than a
median execution. It made a falsifiable prediction: a pairwise classifier should work
at short distances (where "same work" is nearly the same claim as "adjacent in time")
and **fail at exactly the distances where linking would add value** -- across gaps, and
across an intervening block of different work.

This script measures that, stratified by distance and by whether different work
intervenes. A single pooled AUC would hide the entire finding.

LEAKAGE CONTROLS
----------------
* Labels come from GT `case_id`; **no GT-derived value is ever a feature**. No
  process code, no execution id, no boundary position, no execution length or count.
* Splits are **GroupKFold grouped by session** -- no session in both train and test.
* The "does different work intervene" flag is GT-derived and used **only to stratify
  reported results**, never as an input. It is computed after prediction.

Deterministic: fixed seed, fixed neighbourhood, fixed sampling.

Usage:
    python scripts/run_work_thread_pairwise_experiment.py \
        --dataset dataset_a --out reports/day7
"""
from __future__ import annotations

import argparse
import glob
import json
import random
import re
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (average_precision_score, f1_score, precision_score,
                             recall_score, roc_auc_score)
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

SEED = 0
NEIGHBOURHOOD = 20          # short-range neighbourhood (kept for the near-field report)
MAX_GAP = 600               # long-range: how far ahead a pair may reach
LOG_SPACED_SAMPLES = 24     # gaps per anchor, log-spaced across 1..MAX_GAP
MAX_PAIRS_PER_SESSION = 6000
N_SPLITS = 5
_URL = re.compile(r"https?://([^/]+)")

FEATURES = [
    "log1p_delta_t_ms", "index_gap",
    "same_application", "same_window_title",
    "same_browser_domain", "both_domains_known",
    "same_tab_id", "both_tabs_known",
    "same_event_type", "same_chunk",
    "n_app_switches_between", "n_distinct_apps_between",
    "any_navigation_between", "any_clipboard_between",
]


def load_session(events_files: list[str]) -> list[dict]:
    """Minimal per-event projection, read straight from the raw log."""
    out = []
    for f in sorted(events_files):
        with open(f, encoding="utf-8") as fh:
            for ln in fh:
                e = json.loads(ln)
                ctx = e.get("context") or {}
                app = ctx.get("active_app") or {}
                tab = ctx.get("active_browser_tab") or {}
                url = tab.get("url")
                m = _URL.match(url) if url else None
                out.append({
                    "ts": e["timestamp_ms"],
                    "type": e.get("event_type"),
                    "app": app.get("name"),
                    "title": app.get("window_title"),
                    "domain": m.group(1) if m else None,
                    "tab": (e.get("payload") or {}).get("tab_id"),
                    "chunk": (e.get("correlation") or {}).get("chunk_id"),
                })
    out.sort(key=lambda r: r["ts"])
    return out


def label_events(events: list[dict], executions) -> list[str | None]:
    """GT case_id per event, by timestamp containment. Labels only -- never a feature."""
    spans = sorted(
        (int(x.start_ts.timestamp() * 1000), int(x.end_ts.timestamp() * 1000), x.case_id)
        for x in executions if x.end_ts is not None
    )
    starts = [s for s, _, _ in spans]
    labels: list[str | None] = []
    for e in events:
        i = np.searchsorted(starts, e["ts"], side="right") - 1
        lab = None
        if 0 <= i < len(spans) and spans[i][0] <= e["ts"] <= spans[i][1]:
            lab = spans[i][2]
        labels.append(lab)
    return labels


def build_pairs(events: list[dict], labels: list[str | None], rng: random.Random):
    """Pairs within a bounded forward neighbourhood, with prefix sums for 'between' features."""
    n = len(events)
    # prefix counts so "what happened between i and j" is O(1)
    sw = [0] * (n + 1)   # app switches
    nav = [0] * (n + 1)  # browser navigations
    clip = [0] * (n + 1)
    for k, e in enumerate(events):
        sw[k + 1] = sw[k] + (1 if e["type"] == "app_switch" else 0)
        nav[k + 1] = nav[k] + (1 if e["type"] == "browser_navigation" else 0)
        clip[k + 1] = clip[k] + (1 if e["type"] == "clipboard_change" else 0)

    # Gaps are sampled LOG-SPACED across 1..MAX_GAP rather than taken from a dense
    # short window. The first run used a dense 20-event window and produced a 0.89
    # positive rate with 33 intervening-work pairs out of 378k -- a task so easy that
    # a high AUC said nothing about linking ability. Log spacing keeps the near field
    # while actually reaching the distances where the hypothesis would have to pay off.
    gap_grid = sorted({int(round(gv)) for gv in
                       np.geomspace(1, MAX_GAP, LOG_SPACED_SAMPLES)})
    candidates = []
    for i in range(n):
        if labels[i] is None:
            continue
        for gv in gap_grid:
            j = i + gv
            if j >= n or labels[j] is None:
                continue
            candidates.append((i, j))
    if len(candidates) > MAX_PAIRS_PER_SESSION:
        candidates = rng.sample(candidates, MAX_PAIRS_PER_SESSION)

    X, y, meta = [], [], []
    for i, j in candidates:
        a, b = events[i], events[j]
        dt = b["ts"] - a["ts"]
        apps_between = {events[k]["app"] for k in range(i, j + 1) if events[k]["app"]}
        X.append([
            float(np.log1p(max(dt, 0))),
            float(j - i),
            1.0 if (a["app"] and a["app"] == b["app"]) else 0.0,
            1.0 if (a["title"] and a["title"] == b["title"]) else 0.0,
            1.0 if (a["domain"] and b["domain"] and a["domain"] == b["domain"]) else 0.0,
            1.0 if (a["domain"] and b["domain"]) else 0.0,
            1.0 if (a["tab"] and b["tab"] and a["tab"] == b["tab"]) else 0.0,
            1.0 if (a["tab"] and b["tab"]) else 0.0,
            1.0 if a["type"] == b["type"] else 0.0,
            1.0 if (a["chunk"] and a["chunk"] == b["chunk"]) else 0.0,
            float(sw[j + 1] - sw[i]),
            float(len(apps_between)),
            1.0 if (nav[j + 1] - nav[i]) > 0 else 0.0,
            1.0 if (clip[j + 1] - clip[i]) > 0 else 0.0,
        ])
        y.append(1 if labels[i] == labels[j] else 0)
        # GT-derived, for STRATIFYING RESULTS ONLY -- never a feature
        between = {labels[k] for k in range(i + 1, j) if labels[k] is not None}
        intervening = bool(between - {labels[i], labels[j]})
        meta.append({"delta_t_ms": dt, "index_gap": j - i, "intervening_other_work": intervening})
    return X, y, meta


def stratified_report(y_true, y_prob, meta, thr=0.5) -> dict:
    y_true = np.asarray(y_true); y_prob = np.asarray(y_prob)
    dt = np.array([m["delta_t_ms"] for m in meta])
    inter = np.array([m["intervening_other_work"] for m in meta])
    gap = np.array([m["index_gap"] for m in meta])

    def block(mask: np.ndarray) -> dict:
        if mask.sum() < 50 or len(set(y_true[mask].tolist())) < 2:
            return {"n": int(mask.sum()), "note": "too few samples or single class"}
        yp = (y_prob[mask] >= thr).astype(int)
        return {
            "n": int(mask.sum()),
            "positive_rate": round(float(y_true[mask].mean()), 4),
            "roc_auc": round(float(roc_auc_score(y_true[mask], y_prob[mask])), 4),
            "pr_auc": round(float(average_precision_score(y_true[mask], y_prob[mask])), 4),
            "precision": round(float(precision_score(y_true[mask], yp, zero_division=0)), 4),
            "recall": round(float(recall_score(y_true[mask], yp, zero_division=0)), 4),
            "f1": round(float(f1_score(y_true[mask], yp, zero_division=0)), 4),
        }

    return {
        "overall": block(np.ones(len(y_true), bool)),
        "by_time_gap": {
            "under_1s": block(dt < 1000),
            "1s_to_5s": block((dt >= 1000) & (dt < 5000)),
            "5s_to_30s": block((dt >= 5000) & (dt < 30000)),
            "over_30s": block(dt >= 30000),
        },
        "by_index_gap": {
            "adjacent_1_to_3": block(gap <= 3),
            "near_4_to_20": block((gap > 3) & (gap <= 20)),
            "mid_21_to_100": block((gap > 20) & (gap <= 100)),
            "far_101_to_600": block(gap > 100),
        },
        "the_decisive_split": {
            "no_intervening_other_work": block(~inter),
            "intervening_other_work": block(inter),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    from procmine.loaders.ground_truth import load_gt_manifest, parse_gt_manifest_executions
    from procmine.paths import discover_dataset
    from procmine.validation import ValidationReport

    rng = random.Random(SEED)
    t0 = time.perf_counter()
    X_all, y_all, g_all, meta_all = [], [], [], []
    n_events_total = 0

    for s in discover_dataset(args.dataset):
        if s.gt_manifest_path is None:
            continue
        man = load_gt_manifest(s.gt_manifest_path, ValidationReport(scope=s.session_id))
        if man is None:
            continue
        execs = parse_gt_manifest_executions(man)
        files = glob.glob(str(Path(args.dataset) / s.session_id / "chunk_*" / "events.jsonl"))
        if not files:
            continue
        events = load_session(files)
        n_events_total += len(events)
        labels = label_events(events, execs)
        X, y, meta = build_pairs(events, labels, rng)
        X_all.extend(X); y_all.extend(y); meta_all.extend(meta)
        g_all.extend([s.session_id] * len(X))

    build_s = time.perf_counter() - t0
    X = np.array(X_all); y = np.array(y_all); g = np.array(g_all)
    print(f"events={n_events_total:,} pairs={len(y):,} positive_rate={y.mean():.4f} "
          f"sessions={len(set(g.tolist()))} build={build_s:.1f}s", file=sys.stderr)

    models = {
        "logistic_regression": lambda: make_pipeline(
            StandardScaler(), LogisticRegression(max_iter=2000, random_state=SEED,
                                                 class_weight="balanced")),
        "random_forest": lambda: RandomForestClassifier(
            n_estimators=200, random_state=SEED, n_jobs=-1, class_weight="balanced_subsample"),
    }
    results = {}
    gkf = GroupKFold(n_splits=N_SPLITS)
    for name, fn in models.items():
        probs = np.zeros(len(y)); fit_s = []
        for tr, te in gkf.split(X, y, g):
            m = fn(); t = time.perf_counter(); m.fit(X[tr], y[tr]); fit_s.append(time.perf_counter() - t)
            probs[te] = m.predict_proba(X[te])[:, 1]
        results[name] = stratified_report(y, probs, meta_all)
        results[name]["mean_fit_seconds"] = round(float(np.mean(fit_s)), 2)
        print(f"{name:<22} overall ROC-AUC={results[name]['overall']['roc_auc']} "
              f"PR-AUC={results[name]['overall']['pr_auc']}", file=sys.stderr)

    rf = RandomForestClassifier(n_estimators=200, random_state=SEED, n_jobs=-1,
                                class_weight="balanced_subsample")
    rf.fit(X, y)
    importances = sorted(
        ({"feature": FEATURES[i], "importance": round(float(v), 4)}
         for i, v in enumerate(rf.feature_importances_)),
        key=lambda d: -d["importance"])

    out = {
        "experiment": "Work-thread hypothesis, Steps 3-5: pairwise same-execution prediction",
        "question": "Can two events be linked as belonging to the same execution using "
                    "only signals the telemetry actually contains?",
        "prediction_under_test": (
            "The signal audit predicted this works at short distance (where 'same work' "
            "is nearly the same claim as 'adjacent in time') and fails across an "
            "intervening block of different work -- i.e. exactly where linking would add "
            "value over the existing per-transition model."
        ),
        "leakage_controls": {
            "labels": "GT case_id; never a feature",
            "features_used": FEATURES,
            "gt_derived_features": "none",
            "split": f"GroupKFold(n_splits={N_SPLITS}) grouped by session",
            "intervening_flag": "GT-derived; used only to stratify reported results",
        },
        "parameters": {"seed": SEED, "max_gap": MAX_GAP,
                       "log_spaced_samples": LOG_SPACED_SAMPLES,
                       "max_pairs_per_session": MAX_PAIRS_PER_SESSION},
        "scale": {"events": n_events_total, "pairs": int(len(y)),
                  "positive_rate": round(float(y.mean()), 4),
                  "sessions": len(set(g.tolist())),
                  "pair_build_seconds": round(build_s, 1)},
        "results": results,
        "random_forest_feature_importance": importances,
    }
    path = args.out / "work_thread_pairwise_experiment.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    best = "random_forest"
    d = results[best]["the_decisive_split"]
    print("\n--- the decisive split (random forest) ---")
    for k, v in d.items():
        if "roc_auc" in v:
            print(f"  {k:<32} n={v['n']:>7,}  pos={v['positive_rate']:.3f}  "
                  f"ROC-AUC={v['roc_auc']:.4f}  PR-AUC={v['pr_auc']:.4f}  F1={v['f1']:.4f}")
        else:
            print(f"  {k:<32} {v}")
    print(f"\nWrote {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
