"""Evaluation framework: boundary-level and execution-level metrics.

Deliberately built once, generically, before any baseline exists, so
Stage 5's baselines, Stage 6's learned model, and Stage 8's ablation study
all score against the exact same code — a metric that changes meaning
between comparisons would make the comparisons worthless.

Two levels, per the project's own instruction not to trust boundary F1
alone: a system can score well on boundary classification and still
produce badly fragmented or merged executions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from procmine.models import GTExecution
from procmine.segmentation.features import LabeledTransition


@dataclass
class BoundaryMetrics:
    n_transitions: int
    n_gt_boundaries: int
    n_predicted: int
    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def boundary_metrics(
    labeled: list[LabeledTransition], predictions: list[bool]
) -> BoundaryMetrics:
    """Transition-level classification metrics. `predictions[i]` must
    correspond to `labeled[i]` — same length, same order. Exact-match at
    the transition level (not a tolerance window): Stage 4's containment
    join already anchors each GT boundary to exactly one transition, so
    there is nothing to be tolerant about here — a transition either is
    that boundary or it isn't."""
    if len(labeled) != len(predictions):
        raise ValueError("labeled and predictions must be the same length")

    tp = fp = fn = 0
    n_gt = 0
    n_pred = 0
    for lt, pred in zip(labeled, predictions):
        if lt.is_boundary:
            n_gt += 1
        if pred:
            n_pred += 1
        if pred and lt.is_boundary:
            tp += 1
        elif pred and not lt.is_boundary:
            fp += 1
        elif not pred and lt.is_boundary:
            fn += 1

    precision = tp / n_pred if n_pred else 0.0
    recall = tp / n_gt if n_gt else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    return BoundaryMetrics(
        n_transitions=len(labeled),
        n_gt_boundaries=n_gt,
        n_predicted=n_pred,
        tp=tp,
        fp=fp,
        fn=fn,
        precision=precision,
        recall=recall,
        f1=f1,
    )


@dataclass
class PredictedSegment:
    session_id: str
    start_ms: int
    end_ms: int


def segments_from_boundaries(
    session_id: str, event_timestamps_ms: list[int], predictions: list[bool]
) -> list[PredictedSegment]:
    """Naive contiguous segmentation: cut the session at every predicted
    boundary. This is deliberately the simplest possible reconstruction —
    it does NOT attempt to reconnect an interrupted-then-resumed process
    into one segment (e.g. A -> B -> A stays three segments here). That's
    Stage 7's job. Scoring this naive version is what will make Stage 7's
    improvement over it measurable, rather than assumed."""
    if len(event_timestamps_ms) < 2:
        if event_timestamps_ms:
            return [PredictedSegment(session_id, event_timestamps_ms[0], event_timestamps_ms[0])]
        return []

    segments = []
    seg_start = event_timestamps_ms[0]
    # predictions[i] is the transition between event i and event i+1
    for i, pred in enumerate(predictions):
        if pred:
            segments.append(PredictedSegment(session_id, seg_start, event_timestamps_ms[i]))
            seg_start = event_timestamps_ms[i + 1]
    segments.append(PredictedSegment(session_id, seg_start, event_timestamps_ms[-1]))
    return segments


@dataclass
class ExecutionMetrics:
    n_gt_executions: int
    n_predicted_segments: int
    n_gt_executions_missed: int  # zero overlapping predicted segments
    over_segmentation_rate: float  # mean(overlapping_segments - 1) across GT executions, clipped at 0
    under_segmentation_rate: float  # mean(overlapping_executions - 1) across predicted segments that overlap >=1 execution
    n_pure_noise_segments: int  # predicted segments overlapping zero GT executions
    n_fragmented: int  # GT executions with >1 overlapping predicted segment
    pct_fragmented: float  # 0-100
    fragmented_case_ids: frozenset  # case_id of each fragmented execution, for cross-model diffing

    def to_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        d["fragmented_case_ids"] = sorted(d["fragmented_case_ids"])
        return d


def _overlap_ms(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    return max(0, min(a_end, b_end) - max(a_start, b_start))


def execution_metrics(
    executions: list[GTExecution], segments: list[PredictedSegment]
) -> ExecutionMetrics:
    """Only scores time that falls within a GT execution's own
    [start_ts, end_ts] — the gaps between GT executions are unlabeled
    "noise" per the assignment's own description (random unrelated
    activity mixed in), not something this metric claims a right answer
    for. A predicted segment that falls entirely in such a gap is counted
    separately (n_pure_noise_segments), not penalized as a merge error."""
    closed = [e for e in executions if e.end_ts is not None]
    exec_intervals = [
        (int(e.start_ts.timestamp() * 1000), int(e.end_ts.timestamp() * 1000), e.case_id)
        for e in closed
    ]

    overlaps_per_execution = [0] * len(exec_intervals)
    overlaps_per_segment = [0] * len(segments)

    for si, seg in enumerate(segments):
        for ei, (e_start, e_end, _case_id) in enumerate(exec_intervals):
            if _overlap_ms(seg.start_ms, seg.end_ms, e_start, e_end) > 0:
                overlaps_per_execution[ei] += 1
                overlaps_per_segment[si] += 1

    n_missed = sum(1 for c in overlaps_per_execution if c == 0)
    over_seg_contributions = [max(c - 1, 0) for c in overlaps_per_execution]
    n_pure_noise = sum(1 for c in overlaps_per_segment if c == 0)
    under_seg_contributions = [max(c - 1, 0) for c in overlaps_per_segment if c > 0]
    fragmented_case_ids = frozenset(
        exec_intervals[ei][2] for ei, c in enumerate(overlaps_per_execution) if c > 1
    )

    return ExecutionMetrics(
        n_gt_executions=len(exec_intervals),
        n_predicted_segments=len(segments),
        n_gt_executions_missed=n_missed,
        over_segmentation_rate=(
            sum(over_seg_contributions) / len(exec_intervals) if exec_intervals else 0.0
        ),
        under_segmentation_rate=(
            sum(under_seg_contributions) / len(under_seg_contributions)
            if under_seg_contributions
            else 0.0
        ),
        n_pure_noise_segments=n_pure_noise,
        n_fragmented=len(fragmented_case_ids),
        pct_fragmented=(100 * len(fragmented_case_ids) / len(exec_intervals)) if exec_intervals else 0.0,
        fragmented_case_ids=fragmented_case_ids,
    )
