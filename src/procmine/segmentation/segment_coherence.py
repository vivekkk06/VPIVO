"""Day-2-closing follow-up: segment-level coherence forensics
(`scripts/analyze_segment_coherence_forensics.py`).

Diagnostic-only building blocks, in the same spirit as
`rule4_forensics.py` (Stage 8.4) -- nothing here is wired into
`reconstruction.py` or `protected_boundary.py`. This module exists to
test one specific hypothesis: whether a *segment*-scoped (variable-
length, bounded by the current final-boundary set) coherence
measurement can discriminate remaining false boundaries from
correctly-kept ones any better than the existing fixed-N=10-event
window features Rule 4 and the Tempo/Combined protection strategies
already use.

Segment-scoped vs. N=10-scoped -- the actual difference under test:
Rule 4's `event_type_jaccard` and the protection layer's
`after_window_duration_ms` both look at a fixed 10-event window on
each side of a transition, regardless of where the *actual*
neighboring segment boundaries fall. This module instead uses the real
left/right fragment implied by the current final-boundary set -- "from
the previous kept boundary to here" and "from here to the next kept
boundary" -- which can be much shorter or much longer than 10 events.
That operationalizes the forensic question "if this candidate boundary
were removed, would the resulting merged segment look like one
coherent trajectory?": a high jaccard / matched activity-rate between
the two actual neighboring fragments is evidence the merge would look
coherent; a low one is evidence the split is real.

No field here is GT-derived (no process_code, case_id, process_variant,
GT execution span, continuity label, or boundary label) -- every input
is either the raw `CanonicalEvent` stream or a `final_boundary` array
the caller already produced through V1/V2 + Design 2 + protection.
"""

from __future__ import annotations

from dataclasses import dataclass

from procmine.segmentation.canonical import CanonicalEvent
from procmine.segmentation.context_features import summarize_window


def _jaccard(a: frozenset, b: frozenset) -> float | None:
    """Mirrors `context_features._jaccard`'s exact logic (None, not 0.0,
    when neither side has any evidence) -- duplicated rather than
    reaching into another module's private helper, the same precedent
    `rule4_forensics.hostname_only` set for `context_features._hostname_only`."""
    if not a and not b:
        return None
    union = a | b
    if not union:
        return None
    return len(a & b) / len(union)


def segment_index_bounds(n_events: int, final_boundary: list[bool]) -> list[tuple[int, int]]:
    """(start_idx, end_idx) inclusive event-index bounds for every
    segment implied by `final_boundary`, using the exact same cut
    convention as `evaluation.segments_from_boundaries` (transition i
    separates event i from event i+1). `len(final_boundary)` must equal
    `n_events - 1`, matching every other reconstruction function's
    (candidates, chunk_boundary, ...) convention."""
    if n_events == 0:
        if final_boundary:
            raise ValueError("final_boundary must be empty when n_events is 0")
        return []
    if len(final_boundary) != n_events - 1:
        raise ValueError("final_boundary must have exactly n_events - 1 entries")

    bounds: list[tuple[int, int]] = []
    start = 0
    for i, is_boundary in enumerate(final_boundary):
        if is_boundary:
            bounds.append((start, i))
            start = i + 1
    bounds.append((start, n_events - 1))
    return bounds


@dataclass
class SegmentCoherenceEvidence:
    left_n_events: int
    right_n_events: int
    left_duration_ms: int
    right_duration_ms: int
    left_event_rate_per_s: float | None  # None if left_duration_ms == 0 (no evidence, not zero rate)
    right_event_rate_per_s: float | None
    rate_continuity_ratio: float | None  # min(rate)/max(rate) in [0, 1]; None if either rate is undefined
    segment_event_type_jaccard: float | None
    segment_interaction_category_jaccard: float | None
    segment_application_jaccard: float | None
    segment_browser_domain_jaccard_host_only: float | None
    min_segment_n_events: int
    min_segment_duration_ms: int

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def compute_segment_coherence_evidence(
    canonical: list[CanonicalEvent],
    final_boundary: list[bool],
    index_i: int,
    segment_bounds: list[tuple[int, int]] | None = None,
) -> SegmentCoherenceEvidence:
    """`index_i` must satisfy `final_boundary[index_i] is True` -- the
    left segment is the one ending at event `index_i`, the right
    segment is the one starting at event `index_i + 1`. Callers scoring
    many candidates in the same session should precompute
    `segment_bounds = segment_index_bounds(len(canonical), final_boundary)`
    once and pass it in, rather than have every call recompute it."""
    if segment_bounds is None:
        segment_bounds = segment_index_bounds(len(canonical), final_boundary)

    left = next((b for b in segment_bounds if b[1] == index_i), None)
    right = next((b for b in segment_bounds if b[0] == index_i + 1), None)
    if left is None or right is None:
        raise ValueError(f"index_i={index_i} is not a final_boundary transition")

    left_summary = summarize_window(canonical[left[0] : left[1] + 1])
    right_summary = summarize_window(canonical[right[0] : right[1] + 1])

    left_rate = (
        1000.0 * left_summary.n_events / left_summary.duration_ms
        if left_summary.duration_ms > 0 else None
    )
    right_rate = (
        1000.0 * right_summary.n_events / right_summary.duration_ms
        if right_summary.duration_ms > 0 else None
    )
    if left_rate is not None and right_rate is not None and max(left_rate, right_rate) > 0:
        rate_ratio = min(left_rate, right_rate) / max(left_rate, right_rate)
    else:
        rate_ratio = None

    return SegmentCoherenceEvidence(
        left_n_events=left_summary.n_events,
        right_n_events=right_summary.n_events,
        left_duration_ms=left_summary.duration_ms,
        right_duration_ms=right_summary.duration_ms,
        left_event_rate_per_s=left_rate,
        right_event_rate_per_s=right_rate,
        rate_continuity_ratio=rate_ratio,
        segment_event_type_jaccard=_jaccard(left_summary.event_types, right_summary.event_types),
        segment_interaction_category_jaccard=_jaccard(
            left_summary.interaction_categories, right_summary.interaction_categories
        ),
        segment_application_jaccard=_jaccard(left_summary.applications, right_summary.applications),
        segment_browser_domain_jaccard_host_only=_jaccard(
            left_summary.browser_domains_host_only, right_summary.browser_domains_host_only
        ),
        min_segment_n_events=min(left_summary.n_events, right_summary.n_events),
        min_segment_duration_ms=min(left_summary.duration_ms, right_summary.duration_ms),
    )
