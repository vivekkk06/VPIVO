#!/usr/bin/env python3
"""Day 7 — a learned component where ML genuinely has a question to answer.

WHY THIS TASK, AND WHY IT IS NOT CIRCULAR
-----------------------------------------
The tempting ML task here is "predict whether a process is a good automation
candidate". That task is **circular and was rejected**: the only available labels
would come from the Opportunity score the model is meant to support, so the model
would learn my own scoring function and prove nothing.

This experiment uses genuinely independent labels instead. Dataset A's ground truth
carries a `process_code` for each of 2,009 executions across 15 well-balanced classes
(102-169 each). Those labels were produced by whoever recorded the dataset, not by any
analysis in this project.

The question is one Day 6 raised but could not settle. Unsupervised clustering found
that behavioural features agree only weakly with process identity (ARI 0.264) while
system identity recovers it much better (0.661), and concluded that "process identity
lives in system context, not behaviour". That was measured *without labels*. With
labels, the question sharpens:

    Can a supervised model recover process identity from BEHAVIOUR ALONE,
    or does it still need to be told which system the user is in?

The answer matters downstream. Dataset-B processes are labelled by exact-match
`dominant_context` (system identity). If behaviour alone were sufficient, that choice
would be leaving information on the table. If it is not, the Day-3 decision is
confirmed by a second, stronger method.

LEAKAGE CONTROL
---------------
Executions from one session are highly correlated. Splits are therefore
**GroupKFold grouped by session** — no session appears in both train and test. A
random split would inflate every number here.

Usage:
    python scripts/run_process_classifier_experiment.py \
        --dataset dataset_a --out reports/day7
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix, f1_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

N_SPLITS = 5
SEED = 0


def _load_locked():
    spec = importlib.util.spec_from_file_location(
        "locked_experiment", ROOT / "scripts" / "run_protected_boundary_experiment.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["locked_experiment"] = mod
    spec.loader.exec_module(mod)
    return mod


# Interaction categories and event types are enumerated from the data itself so the
# feature vector is stable and inspectable rather than implicit.
def collect_vocabularies(per_session: dict) -> dict:
    cats, types, apps, domains = Counter(), Counter(), Counter(), Counter()
    for d in per_session.values():
        for e in d["canonical"]:
            cats[e.interaction_category] += 1
            types[e.event_type] += 1
            if e.application:
                apps[e.application] += 1
            if e.browser_domain:
                domains[e.browser_domain] += 1
    return {
        "interaction_categories": [c for c, _ in cats.most_common(12)],
        "event_types": [t for t, _ in types.most_common(14)],
        "applications": [a for a, _ in apps.most_common(10)],
        "browser_domains": [d for d, _ in domains.most_common(10)],
    }


def execution_features(events: list, vocab: dict, with_identity: bool) -> tuple[list[float], list[str]]:
    """Behavioural features by default; system identity only when asked for.

    The split is the whole point of the experiment, so it is enforced structurally:
    `n_distinct_applications` is a COUNT (behavioural — how much switching), whereas
    which application it is lives behind the `with_identity` flag.
    """
    n = len(events)
    vals: list[float] = []
    names: list[str] = []

    def add(name: str, value: float) -> None:
        names.append(name)
        vals.append(float(value))

    duration = (events[-1].timestamp_ms - events[0].timestamp_ms) if n > 1 else 0
    add("n_events", n)
    add("duration_ms", duration)
    add("log1p_duration_ms", np.log1p(max(duration, 0)))
    add("events_per_second", n / (duration / 1000.0) if duration > 0 else 0.0)

    cats = Counter(e.interaction_category for e in events)
    for c in vocab["interaction_categories"]:
        add(f"cat_frac::{c}", cats.get(c, 0) / n if n else 0.0)
    add("n_distinct_interaction_categories", len(cats))

    types = Counter(e.event_type for e in events)
    for t in vocab["event_types"]:
        add(f"etype_frac::{t}", types.get(t, 0) / n if n else 0.0)
    add("n_distinct_event_types", len(types))

    manual = sum(1 for e in events if e.interaction_category in
                 {"input", "pointer", "clipboard"})
    add("manual_event_share", manual / n if n else 0.0)
    add("extracted_text_share",
        sum(1 for e in events if e.has_extracted_text) / n if n else 0.0)

    # counts, not identities -- behavioural
    add("n_distinct_applications", len({e.application for e in events if e.application}))
    add("n_app_switches", sum(
        1 for a, b in zip(events, events[1:]) if a.application != b.application))
    add("n_distinct_window_titles", len({e.window_title for e in events if e.window_title}))

    if with_identity:
        apps = Counter(e.application for e in events if e.application)
        for a in vocab["applications"]:
            add(f"app::{a}", apps.get(a, 0) / n if n else 0.0)
        doms = Counter(e.browser_domain for e in events if e.browser_domain)
        for d in vocab["browser_domains"]:
            add(f"domain::{d}", doms.get(d, 0) / n if n else 0.0)
    return vals, names


def build_dataset(per_session: dict, vocab: dict, with_identity: bool):
    X, y, groups = [], [], []
    names = None
    for sid, d in per_session.items():
        canonical = d["canonical"]
        ts = [e.timestamp_ms for e in canonical]
        for ex in d["executions"]:
            # GT timestamps are datetimes; convert with the same convention the
            # locked evaluator uses (evaluation.execution_metrics).
            start_ms = int(ex.start_ts.timestamp() * 1000)
            end_ms = int(ex.end_ts.timestamp() * 1000)
            lo = np.searchsorted(ts, start_ms, side="left")
            hi = np.searchsorted(ts, end_ms, side="right")
            events = canonical[lo:hi]
            if len(events) < 2:
                continue
            vals, names = execution_features(events, vocab, with_identity)
            X.append(vals)
            y.append(ex.process_code)
            groups.append(sid)
    return np.array(X), np.array(y), np.array(groups), names


def evaluate(X, y, groups, model_fn, label: str) -> dict:
    gkf = GroupKFold(n_splits=N_SPLITS)
    y_true_all, y_pred_all = [], []
    fit_times = []
    for train_idx, test_idx in gkf.split(X, y, groups):
        model = model_fn()
        t0 = time.perf_counter()
        model.fit(X[train_idx], y[train_idx])
        fit_times.append(time.perf_counter() - t0)
        y_pred_all.extend(model.predict(X[test_idx]))
        y_true_all.extend(y[test_idx])
    y_true_all = np.array(y_true_all)
    y_pred_all = np.array(y_pred_all)
    labels = sorted(set(y.tolist()))
    rep = classification_report(y_true_all, y_pred_all, labels=labels,
                                output_dict=True, zero_division=0)
    return {
        "model": label,
        "macro_f1": round(f1_score(y_true_all, y_pred_all, average="macro", zero_division=0), 4),
        "weighted_f1": round(f1_score(y_true_all, y_pred_all, average="weighted", zero_division=0), 4),
        "accuracy": round(float((y_true_all == y_pred_all).mean()), 4),
        "n_test_predictions": int(len(y_true_all)),
        "mean_fit_seconds": round(float(np.mean(fit_times)), 3),
        "per_class_f1": {k: round(v["f1-score"], 4) for k, v in rep.items()
                         if k in labels},
        "confusion_matrix_labels": labels,
        "confusion_matrix": confusion_matrix(y_true_all, y_pred_all, labels=labels).tolist(),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    locked = _load_locked()
    print("loading dataset...", file=sys.stderr)
    per_session = locked.load_dataset(args.dataset)
    vocab = collect_vocabularies(per_session)

    results = {}
    feature_counts = {}
    for variant, with_identity in (("behavioural_only", False), ("with_system_identity", True)):
        X, y, groups, names = build_dataset(per_session, vocab, with_identity)
        feature_counts[variant] = len(names)
        print(f"{variant}: X={X.shape}, classes={len(set(y.tolist()))}, "
              f"sessions={len(set(groups.tolist()))}", file=sys.stderr)

        runs = [
            evaluate(X, y, groups,
                     lambda: DummyClassifier(strategy="most_frequent"), "baseline_majority"),
            evaluate(X, y, groups,
                     lambda: DummyClassifier(strategy="stratified", random_state=SEED),
                     "baseline_stratified"),
            evaluate(X, y, groups,
                     lambda: make_pipeline(StandardScaler(),
                                           LogisticRegression(max_iter=2000, random_state=SEED)),
                     "logistic_regression"),
            evaluate(X, y, groups,
                     lambda: RandomForestClassifier(n_estimators=300, random_state=SEED, n_jobs=-1),
                     "random_forest"),
        ]
        results[variant] = {r["model"]: r for r in runs}

        # feature importance from the strongest simple model, for explainability
        rf = RandomForestClassifier(n_estimators=300, random_state=SEED, n_jobs=-1)
        rf.fit(X, y)
        order = np.argsort(rf.feature_importances_)[::-1][:12]
        results[variant]["top_features_random_forest"] = [
            {"feature": names[i], "importance": round(float(rf.feature_importances_[i]), 4)}
            for i in order
        ]

    beh = results["behavioural_only"]["random_forest"]["macro_f1"]
    ident = results["with_system_identity"]["random_forest"]["macro_f1"]
    maj = results["behavioural_only"]["baseline_majority"]["macro_f1"]

    out = {
        "experiment": "Day-7 supervised process classification (Dataset A)",
        "question": "Can a supervised model recover process identity from behaviour "
                    "alone, or does it still need system identity?",
        "why_not_circular": (
            "Labels are the ground-truth `process_code` recorded with Dataset A, not "
            "the Opportunity score this project computes. A classifier trained to "
            "predict the Opportunity score would have learned my own scoring function "
            "and proved nothing; that task was considered and rejected."
        ),
        "leakage_control": (
            f"GroupKFold(n_splits={N_SPLITS}) grouped by session. No session appears in "
            "both train and test. A random split would inflate these numbers because "
            "executions within a session are highly correlated."
        ),
        "n_executions": int(sum(len(v["executions"]) for v in per_session.values())),
        "n_classes": 15,
        "n_sessions": len(per_session),
        "n_features": feature_counts,
        "vocabularies": vocab,
        "results": results,
        "headline": {
            "behavioural_only_macro_f1": beh,
            "with_system_identity_macro_f1": ident,
            "majority_baseline_macro_f1": maj,
            "identity_uplift": round(ident - beh, 4),
        },
    }
    path = args.out / "process_classifier_experiment.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n{'variant':<24}{'model':<24}{'macroF1':<10}{'accuracy':<10}")
    for variant, runs in results.items():
        for name, r in runs.items():
            if name == "top_features_random_forest":
                continue
            print(f"{variant:<24}{name:<24}{r['macro_f1']:<10.4f}{r['accuracy']:<10.4f}")
    print(f"\nBehaviour only: {beh:.4f} | With system identity: {ident:.4f} "
          f"| uplift {ident - beh:+.4f}")
    print(f"Wrote {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
