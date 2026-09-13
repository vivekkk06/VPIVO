from datetime import datetime, timezone

from procmine.models import GTExecution
from procmine.segmentation.evaluation import (
    boundary_metrics,
    execution_metrics,
    segments_from_boundaries,
)
from procmine.segmentation.features import LabeledTransition, TransitionFeatures


def _lt(is_boundary: bool) -> LabeledTransition:
    f = TransitionFeatures(
        session_id="s1", event_i_id="a", event_next_id="b", timestamp_ms=0,
        next_timestamp_ms=1000, delta_t_ms=1000, log1p_delta_t_ms=0.0,
        density_before=0, density_after=0, application_changed=False,
        window_title_changed=False, browser_domain_changed=False,
        interaction_category_changed=False, extracted_text_at_transition=False,
        chunk_boundary=False,
    )
    return LabeledTransition(features=f, is_boundary=is_boundary, is_resume=None)


def _exec(start_s, end_s, case_id="c") -> GTExecution:
    return GTExecution(
        process_code="A", process_name=None, case_id=case_id,
        start_ts=datetime.fromtimestamp(start_s, tz=timezone.utc),
        end_ts=datetime.fromtimestamp(end_s, tz=timezone.utc),
        variant=None,
    )


def test_perfect_prediction_scores_1_1_1():
    labeled = [_lt(True), _lt(False), _lt(True), _lt(False)]
    preds = [True, False, True, False]
    m = boundary_metrics(labeled, preds)
    assert m.precision == 1.0
    assert m.recall == 1.0
    assert m.f1 == 1.0


def test_predicting_nothing_gives_zero_recall_and_zero_precision():
    labeled = [_lt(True), _lt(False)]
    preds = [False, False]
    m = boundary_metrics(labeled, preds)
    assert m.recall == 0.0
    assert m.precision == 0.0  # n_predicted == 0, defined as 0 not divide-by-zero error


def test_over_predicting_hurts_precision_not_recall():
    labeled = [_lt(True), _lt(False), _lt(False)]
    preds = [True, True, True]
    m = boundary_metrics(labeled, preds)
    assert m.recall == 1.0
    assert m.precision == 1 / 3


def test_mismatched_lengths_raises():
    import pytest

    with pytest.raises(ValueError):
        boundary_metrics([_lt(True)], [True, False])


def test_segments_from_boundaries_cuts_at_every_predicted_true():
    ts = [0, 1000, 2000, 3000, 4000]
    preds = [False, True, False, True]  # boundary after idx1 and idx3
    segs = segments_from_boundaries("s1", ts, preds)
    assert [(s.start_ms, s.end_ms) for s in segs] == [(0, 1000), (2000, 3000), (4000, 4000)]


def test_segments_from_boundaries_no_predictions_is_one_segment():
    ts = [0, 1000, 2000]
    segs = segments_from_boundaries("s1", ts, [False, False])
    assert len(segs) == 1
    assert segs[0].start_ms == 0 and segs[0].end_ms == 2000


def test_execution_metrics_perfect_1to1_match():
    execs = [_exec(0, 10), _exec(20, 30)]
    segs = segments_from_boundaries("s1", [0, 10_000, 20_000, 30_000], [False, True, False])
    m = execution_metrics(execs, segs)
    assert m.over_segmentation_rate == 0.0
    assert m.under_segmentation_rate == 0.0
    assert m.n_gt_executions_missed == 0


def test_execution_metrics_detects_over_segmentation():
    # one GT execution [0,30] split into two predicted segments -> over-segmented
    execs = [_exec(0, 30)]
    segs = segments_from_boundaries("s1", [0, 10_000, 20_000, 30_000], [False, True, False])
    m = execution_metrics(execs, segs)
    assert m.over_segmentation_rate > 0


def test_execution_metrics_detects_under_segmentation():
    # two GT executions both fully inside one predicted segment -> merged/under-segmented
    execs = [_exec(0, 10), _exec(15, 25)]
    segs = segments_from_boundaries("s1", [0, 30_000], [False])
    m = execution_metrics(execs, segs)
    assert m.under_segmentation_rate > 0


def test_execution_metrics_counts_pure_noise_segment_separately_not_as_merge_error():
    # a predicted segment entirely outside any GT execution's interval
    execs = [_exec(0, 5)]
    segs = segments_from_boundaries("s1", [0, 5_000, 100_000, 200_000], [False, True, False])
    m = execution_metrics(execs, segs)
    assert m.n_pure_noise_segments >= 1
    assert m.under_segmentation_rate == 0.0  # the noise segment shouldn't count as a merge


def test_execution_metrics_flags_missed_execution():
    execs = [_exec(0, 10), _exec(1000, 1010)]  # second execution has no overlapping segment
    segs = segments_from_boundaries("s1", [0, 10_000], [False])
    m = execution_metrics(execs, segs)
    assert m.n_gt_executions_missed == 1


def test_execution_metrics_reports_pct_and_case_ids_of_fragmented_executions():
    # exec "a" (0-30s) gets cut into two segments -> fragmented;
    # exec "b" (40-70s) stays in one segment -> clean
    execs = [_exec(0, 30, case_id="a"), _exec(40, 70, case_id="b")]
    segs = segments_from_boundaries(
        "s1",
        [0, 10_000, 20_000, 30_000, 40_000, 70_000],
        [False, True, False, True, False],
    )
    m = execution_metrics(execs, segs)
    assert m.n_fragmented == 1
    assert m.pct_fragmented == 50.0
    assert m.fragmented_case_ids == frozenset({"a"})


def test_execution_metrics_pct_fragmented_zero_when_none_fragmented():
    execs = [_exec(0, 10, case_id="a")]
    segs = segments_from_boundaries("s1", [0, 10_000], [False])
    m = execution_metrics(execs, segs)
    assert m.n_fragmented == 0
    assert m.pct_fragmented == 0.0
    assert m.fragmented_case_ids == frozenset()
