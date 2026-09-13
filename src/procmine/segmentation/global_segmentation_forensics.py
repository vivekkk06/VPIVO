"""Global-segmentation feasibility study (`scripts/analyze_global_segmentation.py`).

Diagnostic/exploratory only -- nothing here is wired into
`reconstruction.py` or `protected_boundary.py`, and nothing here changes
the locked Design 2 + Strategy Combined architecture. This module tests
a different question than `segment_coherence.py` did:
`segment_coherence.py` compares two already-adjacent fragments to each
other (a *cross-segment* similarity); this module measures how
internally incoherent a *single* candidate segment is on its own (an
*intra-segment* cost), which is the building block a global "minimize
total incoherence + boundary-count penalty" objective needs.

Every component reuses fields Stage 4/5 already computed
(`CanonicalEvent.event_type` / `interaction_category`,
`TransitionFeatures.application_changed` / `browser_domain_changed` /
`log1p_delta_t_ms`) aggregated a new way (within one candidate segment)
rather than introducing a new feature family. No field here is
GT-derived (no process_code, case_id, process_variant, GT execution
span, continuity label, or boundary label) -- every input is either a
raw `CanonicalEvent` slice or a `TransitionFeatures` slice the caller
already produced.

Segment definition, stated explicitly because it drives everything
downstream: segments here are NOT bounded by the locked Combined
output. They are bounded by the raw candidate set C' = (V1 UNION V2)
with Rule 1's hard chunk/duplicate-noise override already applied (the
one sub-problem this project has already solved and validated,
reused rather than re-litigated) -- i.e. every remaining candidate is
provisionally treated as a cut point, exactly the same self-referential
convention `segment_coherence.segment_index_bounds` already
established, just applied to the candidate set instead of Combined's
final decisions. This keeps the feasibility study from being
circularly defined in terms of the architecture it might end up
replacing.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter
from dataclasses import dataclass

from procmine.segmentation.canonical import CanonicalEvent
from procmine.segmentation.features import TransitionFeatures


def entropy_bits(counts: list[int]) -> float:
    """Shannon entropy in bits of a categorical count vector. 0.0 for a
    single-category (or empty) vector -- a perfectly homogeneous segment
    is defined as zero-incoherence by this measure, not undefined."""
    total = sum(counts)
    if total == 0:
        return 0.0
    h = 0.0
    for c in counts:
        if c == 0:
            continue
        p = c / total
        h -= p * math.log2(p)
    return h


@dataclass
class SegmentCost:
    n_events: int
    n_internal_transitions: int
    event_type_entropy_bits: float
    interaction_category_entropy_bits: float
    context_switch_rate: float | None  # None (not 0.0) if n_internal_transitions == 0 -- no evidence either way
    temporal_irregularity_cv: float | None  # None if n_internal_transitions < 2 (variance undefined) or mean == 0

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def compute_segment_cost(
    events: list[CanonicalEvent],
    internal_features: list[TransitionFeatures],
) -> SegmentCost:
    """`events` is the segment's own contiguous `CanonicalEvent` slice;
    `internal_features` are the `TransitionFeatures` for every
    transition strictly inside this segment (never a transition to a
    neighboring segment) -- the caller resolves that slicing (see
    `internal_feature_slice` below), matching the event-index-bounds
    convention `segment_coherence.segment_index_bounds` already
    established."""
    type_counts = Counter(e.event_type for e in events)
    cat_counts = Counter(e.interaction_category for e in events)

    n_internal = len(internal_features)
    if n_internal == 0:
        switch_rate = None
    else:
        n_switch = sum(
            1 for f in internal_features if f.application_changed or f.browser_domain_changed
        )
        switch_rate = n_switch / n_internal

    if n_internal < 2:
        cv = None
    else:
        vals = [f.log1p_delta_t_ms for f in internal_features]
        mean = statistics.fmean(vals)
        cv = (statistics.pstdev(vals) / mean) if mean > 0 else None

    return SegmentCost(
        n_events=len(events),
        n_internal_transitions=n_internal,
        event_type_entropy_bits=entropy_bits(list(type_counts.values())),
        interaction_category_entropy_bits=entropy_bits(list(cat_counts.values())),
        context_switch_rate=switch_rate,
        temporal_irregularity_cv=cv,
    )


def internal_feature_slice(
    feats: list[TransitionFeatures], start_idx: int, end_idx: int
) -> list[TransitionFeatures]:
    """`(start_idx, end_idx)` are inclusive event-index bounds (the same
    convention `segment_coherence.segment_index_bounds` returns).
    Transition `j` (between canonical[j] and canonical[j+1]) is strictly
    internal to this segment iff `start_idx <= j < end_idx` -- that is
    exactly `feats[start_idx:end_idx]`."""
    return feats[start_idx:end_idx]
