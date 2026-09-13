from datetime import datetime, timezone

import numpy as np

from procmine.models import GTExecution
from procmine.segmentation.features import LabeledTransition, TransitionFeatures
from procmine.segmentation.threshold_analysis import build_threshold_grid, evaluate_at_threshold


def _lt(is_boundary: bool) -> LabeledTransition:
    return LabeledTransition(features=None, is_boundary=is_boundary, is_resume=None)


def _exec(start_s, end_s, case_id="c") -> GTExecution:
    return GTExecution(
        process_code="A", process_name=None, case_id=case_id,
        start_ts=datetime.fromtimestamp(start_s, tz=timezone.utc),
        end_ts=datetime.fromtimestamp(end_s, tz=timezone.utc),
        variant=None,
    )


def test_build_threshold_grid_is_sorted_deduplicated_and_bounded():
    scores = np.concatenate([np.random.uniform(0.9, 1.0, 1000), np.random.uniform(0.0, 0.5, 50)])
    grid = build_threshold_grid(scores)
    assert grid == sorted(grid)
    assert len(grid) == len(set(grid))
    assert all(0.0 <= t <= 1.0 for t in grid)


def test_build_threshold_grid_concentrates_density_where_scores_concentrate():
    # scores tightly packed in [0.95, 1.0] -> grid should have many more
    # distinct points in that band than in a same-width band with no data
    scores = np.random.uniform(0.95, 1.0, 5000)
    grid = build_threshold_grid(scores)
    dense_band = [t for t in grid if 0.95 <= t <= 1.0]
    empty_band = [t for t in grid if 0.05 <= t <= 0.10]
    assert len(dense_band) > len(empty_band)


def test_build_threshold_grid_includes_low_range_context_points():
    scores = np.random.uniform(0.9, 1.0, 200)
    grid = build_threshold_grid(scores)
    assert 0.10 in grid and 0.50 in grid


def test_evaluate_at_threshold_recovers_known_precision_recall():
    # one session, 4 transitions: boundary at idx0 and idx2 (ground truth)
    labeled = [_lt(True), _lt(False), _lt(True), _lt(False)]
    scores = np.array([0.9, 0.1, 0.9, 0.1])
    per_session = {
        "s1": {
            "labeled_lt": labeled,
            "labeled_mask": [True, True, True, True],
            "scores": scores,
            "ts": [0, 1000, 2000, 3000, 4000],
            "executions": [_exec(0, 2, case_id="a"), _exec(2, 4, case_id="b")],
        }
    }
    row = evaluate_at_threshold(0.5, labeled, scores, per_session, "scores")
    assert row["precision"] == 1.0
    assert row["recall"] == 1.0
    assert row["f1"] == 1.0


def test_evaluate_at_threshold_same_threshold_applied_identically_across_sessions():
    # No per-session parameter exists on the function signature, so the
    # only way threshold selection could leak is if this function itself
    # varied behavior by session. Confirm two sessions with identical
    # score arrays produce identical predictions/metrics contributions.
    labeled = [_lt(True), _lt(False)]
    scores = np.array([0.9, 0.1])
    per_session = {
        "s1": {
            "labeled_lt": labeled, "labeled_mask": [True, True], "scores": scores,
            "ts": [0, 1000, 2000], "executions": [_exec(0, 2, case_id="a")],
        },
        "s2": {
            "labeled_lt": labeled, "labeled_mask": [True, True], "scores": scores,
            "ts": [0, 1000, 2000], "executions": [_exec(0, 2, case_id="b")],
        },
    }
    row = evaluate_at_threshold(0.5, labeled + labeled, np.concatenate([scores, scores]), per_session, "scores")
    f1_values = list(row["_per_session_f1"].values())
    assert f1_values[0] == f1_values[1]


def test_evaluate_at_threshold_respects_labeled_mask_for_v2_style_excluded_rows():
    # V2-style: session has 3 transitions but the middle one is excluded
    # (no continuity label). labeled_lt only contains the 2 labeled rows;
    # labeled_mask marks positions [True, False, True] against the full
    # 3-row score array. This guards the exact bug fixed in this stage:
    # zipping a pre-filtered labeled_lt against a full-length mask would
    # silently misalign via truncation.
    labeled_only = [_lt(True), _lt(False)]  # rows 0 and 2 of the full session
    full_scores = np.array([0.9, 0.5, 0.1])  # row 1 (excluded) has a score too
    per_session = {
        "s1": {
            "labeled_lt": labeled_only,
            "labeled_mask": [True, False, True],
            "scores": full_scores,
            "ts": [0, 1000, 2000, 3000],
            "executions": [_exec(0, 3, case_id="a")],
        }
    }
    row = evaluate_at_threshold(0.5, labeled_only, np.array([0.9, 0.1]), per_session, "scores")
    # session-restricted predictions must be [row0>=0.5, row2>=0.5] = [True, False],
    # correctly matching labeled_only = [is_boundary=True, is_boundary=False] -> perfect
    assert row["_per_session_f1"]["s1"] == 1.0


def test_evaluate_at_threshold_fragmentation_matches_execution_metrics():
    # exec "a" (0-30s) split into two segments by a threshold that fires
    # at both transitions -> fragmented; mirrors the execution_metrics
    # fragmentation test in test_segmentation_evaluation.py so the two
    # stay consistent.
    labeled = [_lt(False), _lt(True), _lt(False), _lt(True), _lt(False)]
    scores = np.array([0.1, 0.9, 0.1, 0.9, 0.1])
    per_session = {
        "s1": {
            "labeled_lt": labeled,
            "labeled_mask": [True] * 5,
            "scores": scores,
            "ts": [0, 10_000, 20_000, 30_000, 40_000, 70_000],
            "executions": [_exec(0, 30, case_id="a"), _exec(40, 70, case_id="b")],
        }
    }
    row = evaluate_at_threshold(0.5, labeled, scores, per_session, "scores")
    assert row["n_gt_executions_fragmented"] == 1
    assert row["pct_gt_executions_fragmented"] == 50.0
    assert row["_fragmented_by_session"]["s1"] == frozenset({"a"})


def test_evaluate_at_threshold_no_labeled_transitions_in_a_session_is_skipped_safely():
    # a session where every row is excluded (labeled_mask all False) must
    # not crash and must not contribute to per_session_f1
    per_session = {
        "s1": {
            "labeled_lt": [],
            "labeled_mask": [False, False],
            "scores": np.array([0.9, 0.1]),
            "ts": [0, 1000, 2000],
            "executions": [_exec(0, 2, case_id="a")],
        }
    }
    row = evaluate_at_threshold(0.5, [], np.array([]), per_session, "scores")
    assert "s1" not in row["_per_session_f1"]
