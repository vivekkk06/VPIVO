#!/usr/bin/env python3
"""Day 6, Phase 2-3: evaluate an unsupervised HMM boundary detector against
the locked Dataset-A baseline.

Isolated experiment. It does NOT modify the locked segmentation pipeline —
`reconstruction.py` and `protected_boundary.py` are neither imported nor
re-run here. The locked baseline numbers are *read* from the Day-2 artifact
for comparison and are never recomputed or overwritten.

Evaluation reuses `segmentation.evaluation.boundary_metrics` and
`execution_metrics` exactly as the locked pipeline does, so the comparison is
against the same metric definitions rather than a redefined target.

The state count is swept rather than tuned to a favourable value, and every
swept value is reported.

Usage:
    python scripts/run_hmm_boundary_experiment.py \
        --dataset dataset_a --out reports/day6 \
        --baseline reports/day2/protected_boundary_experiment_dataset_a.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from procmine.experiments.hmm_boundary import (  # noqa: E402
    boundaries_from_states, fit_hmm, standardize,
)
from procmine.loaders.events import load_session_events  # noqa: E402
from procmine.loaders.ground_truth import (  # noqa: E402
    load_gt_manifest, parse_gt_manifest_executions,
)
from procmine.paths import discover_dataset  # noqa: E402
from procmine.segmentation.canonical import to_canonical_stream  # noqa: E402
from procmine.segmentation.evaluation import (  # noqa: E402
    boundary_metrics, execution_metrics, segments_from_boundaries,
)
from procmine.segmentation.features import (  # noqa: E402
    extract_transition_features, label_transitions,
)
from procmine.segmentation.model import feature_vector  # noqa: E402
from procmine.segmentation.signals import extract_boundaries  # noqa: E402
from procmine.validation import ValidationReport  # noqa: E402

STATE_SWEEP = [2, 3, 4, 5, 6, 8]


def load_sessions(dataset_dir: Path) -> dict:
    per_session = {}
    for session in discover_dataset(dataset_dir):
        if session.gt_manifest_path is None:
            continue
        report = ValidationReport(scope=session.session_id)
        events = load_session_events(session, report)
        gt_manifest = load_gt_manifest(session.gt_manifest_path, report)
        if gt_manifest is None or not events:
            continue
        executions_all = parse_gt_manifest_executions(gt_manifest)
        boundaries = extract_boundaries(session.session_id, executions_all)
        canonical = to_canonical_stream(events)
        feats = extract_transition_features(canonical)
        if len(feats) < 10:
            continue
        labels = label_transitions(
            feats, [(b.timestamp_ms, b.is_resume) for b in boundaries]
        )
        per_session[session.session_id] = {
            "feats": feats,
            "labels": labels,
            "executions": [e for e in executions_all if e.end_ts is not None],
            "x": np.array([feature_vector(f) for f in feats], dtype=float),
            "ts": [e.timestamp_ms for e in events],
        }
    return per_session


def evaluate(per_session: dict, preds: dict) -> dict:
    """Score with the locked metric definitions AND the locked pooling
    methodology, replicated exactly from run_protected_boundary_experiment.py
    so the comparison is apples-to-apples rather than a redefined target."""
    all_lt, all_preds = [], []
    per_rows = {}
    total_gt_exec = total_fragmented = 0
    over_num = over_den = 0.0
    under_num = under_den = 0.0

    for sid, d in per_session.items():
        lt = d["labels"]
        p = list(preds[sid])[: len(lt)]
        all_lt.extend(lt)
        all_preds.extend(p)

        bm = boundary_metrics(lt, p)
        segs = segments_from_boundaries(sid, d["ts"], p)
        em = execution_metrics(d["executions"], segs)

        per_rows[sid] = {
            "precision": bm.precision, "recall": bm.recall, "f1": bm.f1,
            "over_segmentation_rate": em.over_segmentation_rate,
            "under_segmentation_rate": em.under_segmentation_rate,
            "n_gt_executions": em.n_gt_executions, "n_fragmented": em.n_fragmented,
            "pct_fragmented": em.pct_fragmented,
            "n_predicted": int(sum(p)),
        }
        total_gt_exec += em.n_gt_executions
        total_fragmented += em.n_fragmented
        over_num += em.over_segmentation_rate * em.n_gt_executions
        over_den += em.n_gt_executions
        n_overlap = em.n_predicted_segments - em.n_pure_noise_segments
        under_num += em.under_segmentation_rate * n_overlap
        under_den += n_overlap

    pooled_bm = boundary_metrics(all_lt, all_preds)
    f1s = [r["f1"] for r in per_rows.values()]
    return {
        "pooled": {
            "precision": pooled_bm.precision, "recall": pooled_bm.recall,
            "f1": pooled_bm.f1,
            "n_gt_boundaries": pooled_bm.n_gt_boundaries,
            "n_predicted": pooled_bm.n_predicted,
            "over_segmentation_rate": over_num / over_den if over_den else None,
            "under_segmentation_rate": under_num / under_den if under_den else None,
            "n_gt_executions_total": total_gt_exec,
            "n_gt_executions_fragmented": total_fragmented,
            "pct_gt_executions_fragmented": (
                100.0 * total_fragmented / total_gt_exec if total_gt_exec else None
            ),
            "pct_transitions_flagged": round(
                100.0 * sum(all_preds) / max(1, len(all_preds)), 4
            ),
        },
        "per_session_f1": {
            "median": round(statistics.median(f1s), 6),
            "mean": round(statistics.fmean(f1s), 6),
            "min": round(min(f1s), 6), "max": round(max(f1s), 6),
        },
        "per_session": per_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    print("Loading Dataset A ...", file=sys.stderr)
    per_session = load_sessions(args.dataset)
    print(f"  {len(per_session)} sessions with ground truth", file=sys.stderr)

    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    locked = baseline["systems"]["Strategy_Combined"]["pooled"]

    results = {}
    for k in STATE_SWEEP:
        t0 = time.perf_counter()
        preds, diag = {}, []
        for sid, d in per_session.items():
            fit = fit_hmm(standardize(d["x"]), k, seed=args.seed)
            preds[sid] = boundaries_from_states(fit.states)
            diag.append({
                "n_iter": fit.n_iter, "converged": fit.converged,
                "n_states_used": int(len(np.unique(fit.states))),
            })
        elapsed = time.perf_counter() - t0
        ev = evaluate(per_session, preds)
        ev["runtime_seconds"] = round(elapsed, 2)
        ev["convergence"] = {
            "n_converged": sum(1 for x in diag if x["converged"]),
            "n_sessions": len(diag),
            "mean_iterations": round(statistics.fmean(x["n_iter"] for x in diag), 2),
            "mean_states_actually_used": round(
                statistics.fmean(x["n_states_used"] for x in diag), 2
            ),
        }
        results[f"K={k}"] = ev
        p = ev["pooled"]
        print(
            f"  K={k}: P={p['precision']:.4f} R={p['recall']:.4f} F1={p['f1']:.4f} "
            f"flagged={p['pct_transitions_flagged']:.1f}% "
            f"over={p['over_segmentation_rate']:.3f} under={p['under_segmentation_rate']:.3f} "
            f"({elapsed:.1f}s)",
            file=sys.stderr,
        )

    best_k = max(results, key=lambda kk: results[kk]["pooled"]["f1"])
    out = {
        "experiment": "Day-6 Phase 2/3 — unsupervised Gaussian HMM boundary detection",
        "method": "Diagonal-covariance Gaussian HMM fitted per session by Baum-Welch on the "
                  "same 9-dimensional per-transition feature vector the locked V1 model uses; "
                  "Viterbi state path decoded; a change of latent state is taken as a candidate "
                  "boundary. Unsupervised: no ground-truth label is used during fitting.",
        "isolation_note": "The locked pipeline was not modified, imported, or re-run. Baseline "
                          "figures below are read verbatim from the Day-2 artifact.",
        "evaluation_note": "Scored with segmentation.evaluation.boundary_metrics and "
                           "execution_metrics, unchanged.",
        "seed": args.seed,
        "state_sweep": STATE_SWEEP,
        "locked_baseline_pooled": locked,
        "results": results,
        "best_k_by_f1": best_k,
    }
    path = args.out / "hmm_boundary_experiment_dataset_a.json"
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")

    print(f"\nLocked baseline: P={locked['precision']:.4f} R={locked['recall']:.4f} "
          f"F1={locked['f1']:.4f}", file=sys.stderr)
    bp = results[best_k]["pooled"]
    print(f"Best HMM ({best_k}):  P={bp['precision']:.4f} R={bp['recall']:.4f} "
          f"F1={bp['f1']:.4f}", file=sys.stderr)
    print(f"Wrote {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
