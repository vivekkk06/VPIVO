"""Stage 7: threshold/operating-point sweep logic, factored out of
`scripts/analyze_threshold_tradeoff.py` so it can be unit-tested the same
way as every other metric in this package (`evaluation.py`'s functions),
rather than importing test logic out of a CLI script.

Reuses `boundary_metrics`, `execution_metrics`, and `segments_from_boundaries`
exactly as defined in `evaluation.py` — no metric is redefined here.
"""

from __future__ import annotations

import statistics
from typing import Any

import numpy as np

from procmine.segmentation.evaluation import (
    boundary_metrics,
    execution_metrics,
    segments_from_boundaries,
)


def build_threshold_grid(scores: np.ndarray) -> list[float]:
    """Justified from the observed score distribution, not a blind linear
    sweep: both V1 and V2 scores concentrate heavily near 1.0 (class
    imbalance forces high confidence before "boundary" is favored), so a
    plain 0.50-0.99 linear grid would waste most of its points in a flat,
    uninformative region. Uses percentiles of the upper half of the score
    distribution (75th-99.9th) to concentrate grid density exactly where
    the data has density, plus a few coarse low-range points for context
    on the flat/uninformative region."""
    coarse_low = [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70]
    percentiles = np.linspace(75, 99.9, 40)
    dense_upper = sorted(set(round(float(np.percentile(scores, p)), 4) for p in percentiles))
    grid = sorted(set(coarse_low + dense_upper + [0.80, 0.90, 0.95, 0.99, 0.999]))
    return grid


def evaluate_at_threshold(
    threshold: float,
    all_labeled_lt: list,
    all_scores_labeled: np.ndarray,
    per_session: dict,
    score_key: str,
) -> dict[str, Any]:
    """One global threshold applied identically to every session's scores
    (`full_scores >= threshold`) — by construction there is no per-session
    parameter here, so a threshold can only be evaluated globally, never
    calibrated to the session it will be scored against. That is what
    keeps this leakage-free: the caller must select `threshold` from
    pooled out-of-fold scores before calling this function, not from any
    individual held-out session.

    `per_session[sid]` must provide: "labeled_lt" (list[LabeledTransition]
    restricted to labeled-only rows, in session order), "labeled_mask"
    (full-session-length bool list marking which transitions are labeled),
    `score_key` (full-session-length array of continuous scores), "ts"
    (event timestamps), "executions" (GT executions for that session).
    """
    preds_labeled = (all_scores_labeled >= threshold).tolist()
    bm = boundary_metrics(all_labeled_lt, preds_labeled)

    over_seg_num, over_seg_den = 0.0, 0
    under_seg_num, under_seg_den = 0.0, 0
    n_gt_total, n_frag_total = 0, 0
    per_session_f1: dict[str, float] = {}
    fragmented_by_session: dict[str, frozenset] = {}

    for sid in sorted(per_session.keys()):
        d = per_session[sid]
        full_scores = d[score_key]
        full_preds = (full_scores >= threshold).tolist()

        segs = segments_from_boundaries(sid, d["ts"], full_preds)
        em = execution_metrics(d["executions"], segs)
        over_seg_num += em.over_segmentation_rate * em.n_gt_executions
        over_seg_den += em.n_gt_executions
        n_overlap_segs = em.n_predicted_segments - em.n_pure_noise_segments
        under_seg_num += em.under_segmentation_rate * n_overlap_segs
        under_seg_den += n_overlap_segs
        n_gt_total += em.n_gt_executions
        n_frag_total += em.n_fragmented
        fragmented_by_session[sid] = em.fragmented_case_ids

        # d["labeled_lt"] is already restricted to labeled-only rows (a
        # no-op restriction for V1, a real one for V2); d["labeled_mask"]
        # is full-session length and used only to pick the matching
        # predictions out of full_preds, in the same relative order.
        session_labeled_lt = d["labeled_lt"]
        session_preds_labeled = [
            p for p, m in zip(full_preds, d["labeled_mask"]) if m
        ]
        if session_labeled_lt:
            sbm = boundary_metrics(session_labeled_lt, session_preds_labeled)
            per_session_f1[sid] = sbm.f1

    f1_values = list(per_session_f1.values())
    return {
        "threshold": threshold,
        "precision": bm.precision,
        "recall": bm.recall,
        "f1": bm.f1,
        "tp": bm.tp,
        "fp": bm.fp,
        "fn": bm.fn,
        "tn": bm.n_transitions - bm.tp - bm.fp - bm.fn,
        "over_segmentation_rate": over_seg_num / over_seg_den if over_seg_den else None,
        "under_segmentation_rate": under_seg_num / under_seg_den if under_seg_den else None,
        "pct_gt_executions_fragmented": (100 * n_frag_total / n_gt_total) if n_gt_total else None,
        "n_gt_executions_fragmented": n_frag_total,
        "n_gt_executions_total": n_gt_total,
        "per_session_f1_median": statistics.median(f1_values) if f1_values else None,
        "per_session_f1_mean": statistics.fmean(f1_values) if f1_values else None,
        "per_session_f1_std": statistics.pstdev(f1_values) if len(f1_values) > 1 else 0.0,
        "per_session_f1_min": min(f1_values) if f1_values else None,
        "per_session_f1_max": max(f1_values) if f1_values else None,
        "_fragmented_by_session": fragmented_by_session,
        "_per_session_f1": per_session_f1,
    }
