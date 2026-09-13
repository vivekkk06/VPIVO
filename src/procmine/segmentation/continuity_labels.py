"""Continuity-label construction — the Stage 4 approved policy.

This is a SEPARATE label formulation from `features.label_transitions`
(the boundary-first `is_boundary` label). Neither modifies the other;
both remain independently reproducible from the same underlying
event/GT data, per the explicit instruction not to alter the existing
boundary-first labels while building this one.

Approved policy:

    S = 1  only when both transition endpoints fall inside the SAME
           GT execution (SAME_EXECUTION).
    S = 0  when the transition crosses to a different GT execution with
           no gap (EXIT_TO_DIFFERENT_EXEC), or when it exits an
           execution into unlabeled time AND the existing boundary-first
           label already identifies it as a boundary
           (EXIT_TO_NOISE_BOUNDARY).
    EXCLUDED — no label assigned, not used in training:
        NOISE_TO_NOISE_EXCLUDED    neither endpoint has GT execution
                                    coverage; no supervision available.
        ENTRY_FROM_NOISE_EXCLUDED  enters an execution from unlabeled
                                    time; the boundary-first label never
                                    marks this transition, so there is no
                                    reliable answer for it either.
        EXIT_TO_NOISE_UNRELIABLE_EXCLUDED
                                    exits an execution into unlabeled
                                    time, but is NOT the transition the
                                    boundary-first label marks (i.e. it's
                                    the session's last recorded
                                    execution, with no following
                                    execution to pair a boundary
                                    against). Not one of the 5 originally
                                    named categories — this sub-case
                                    (62 transitions in Dataset A) was
                                    found while implementing full
                                    coverage of EXIT_TO_NOISE, and is
                                    excluded by applying the same
                                    governing principle ("do not
                                    manufacture supervision where GT
                                    does not provide reliable evidence")
                                    rather than assigning it S=0 or S=1
                                    without a matching boundary label to
                                    justify either. Flagged for review,
                                    not decided silently.

Ground-truth fields (process_code, case_id, process_variant) are used
here ONLY to construct labels. None of them appear in any model feature
vector — this module produces labels, not features.
"""

from __future__ import annotations

from dataclasses import dataclass

from procmine.models import GTExecution
from procmine.segmentation.features import TransitionFeatures, label_transitions
from procmine.segmentation.signals import Boundary

SAME_EXECUTION = "SAME_EXECUTION"
EXIT_TO_DIFFERENT_EXEC = "EXIT_TO_DIFFERENT_EXEC"
EXIT_TO_NOISE_BOUNDARY = "EXIT_TO_NOISE_BOUNDARY"
NOISE_TO_NOISE_EXCLUDED = "NOISE_TO_NOISE_EXCLUDED"
ENTRY_FROM_NOISE_EXCLUDED = "ENTRY_FROM_NOISE_EXCLUDED"
EXIT_TO_NOISE_UNRELIABLE_EXCLUDED = "EXIT_TO_NOISE_UNRELIABLE_EXCLUDED"

EXCLUDED_CATEGORIES = {
    NOISE_TO_NOISE_EXCLUDED,
    ENTRY_FROM_NOISE_EXCLUDED,
    EXIT_TO_NOISE_UNRELIABLE_EXCLUDED,
}


@dataclass
class ContinuityLabel:
    session_id: str
    event_i_id: str
    event_next_id: str
    continuity_label: int | None  # 1, 0, or None if excluded
    category: str
    excluded: bool
    excluded_reason: str | None

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def _containing_execution_case_id(ts_ms: int, exec_spans: list[tuple]) -> str | None:
    """Both span bounds are inclusive. Known, documented edge case: if two
    executions' spans shared an exact millisecond boundary
    (prev.end_ts == next.start_ts to the millisecond), this returns
    whichever span appears first in `exec_spans` rather than a defined
    tie-break rule. Not observed in real Dataset A — GT timestamps carry
    microsecond precision, and this module's own reconciliation against
    Stage 3's independently-computed category counts (162,705 exact match)
    confirms no such collision occurred there. Documented rather than
    silently relied upon."""
    for start, end, case_id in exec_spans:
        if start <= ts_ms <= end:
            return case_id
    return None


def label_continuity(
    session_id: str,
    features: list[TransitionFeatures],
    boundaries: list[Boundary],
    executions: list[GTExecution],
) -> list[ContinuityLabel]:
    """`executions` is used only to determine which GT execution (if any)
    each transition's endpoints fall inside — never exposed as a model
    feature. Reuses (does not modify) `label_transitions` for the
    existing boundary-first `is_boundary` signal, needed to distinguish
    EXIT_TO_NOISE_BOUNDARY from EXIT_TO_NOISE_UNRELIABLE_EXCLUDED."""
    is_boundary_labels = label_transitions(
        features, [(b.timestamp_ms, b.is_resume) for b in boundaries]
    )

    exec_spans = [
        (int(e.start_ts.timestamp() * 1000), int(e.end_ts.timestamp() * 1000), e.case_id)
        for e in executions
        if e.end_ts is not None
    ]

    out = []
    for lt in is_boundary_labels:
        f = lt.features
        span_i = _containing_execution_case_id(f.timestamp_ms, exec_spans)
        span_next = _containing_execution_case_id(f.next_timestamp_ms, exec_spans)

        if span_i is not None and span_next is not None and span_i == span_next:
            category, label, excluded, reason = SAME_EXECUTION, 1, False, None
        elif span_i is not None and span_next is not None and span_i != span_next:
            category, label, excluded, reason = EXIT_TO_DIFFERENT_EXEC, 0, False, None
        elif span_i is not None and span_next is None:
            if lt.is_boundary:
                category, label, excluded, reason = EXIT_TO_NOISE_BOUNDARY, 0, False, None
            else:
                category = EXIT_TO_NOISE_UNRELIABLE_EXCLUDED
                label, excluded = None, True
                reason = (
                    "exits into unlabeled time but is not paired with a following "
                    "execution by the boundary-first label (e.g. session's last "
                    "recorded execution) — no reliable GT evidence either way"
                )
        elif span_i is None and span_next is not None:
            category = ENTRY_FROM_NOISE_EXCLUDED
            label, excluded = None, True
            reason = (
                "enters an execution from unlabeled time; the boundary-first label "
                "never marks this transition, so there is no reliable GT-backed "
                "answer for it"
            )
        else:
            category = NOISE_TO_NOISE_EXCLUDED
            label, excluded = None, True
            reason = "neither endpoint has GT execution coverage"

        out.append(
            ContinuityLabel(
                session_id=session_id,
                event_i_id=f.event_i_id,
                event_next_id=f.event_next_id,
                continuity_label=label,
                category=category,
                excluded=excluded,
                excluded_reason=reason,
            )
        )
    return out
