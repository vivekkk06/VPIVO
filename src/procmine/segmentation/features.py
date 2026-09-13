"""Per-transition feature extraction.

Operates on a `CanonicalEvent` stream and produces one `TransitionFeatures`
row per adjacent event pair (i, i+1) — this is the X_i feature vector the
boundary model (Stage 5/6) will consume. Deliberately GT-agnostic: nothing
here requires ground truth, so the same function runs unchanged on Dataset
B or any future dataset. Labeling (joining against GT boundaries, for
Dataset A only) is a separate step (`label_transitions`) so the core
extractor never depends on labels existing.

Feature set, and why each one is here (not an exhaustive list — the
project's own instruction is not to implement every possible feature
blindly; each of these has a concrete, stated reason, and each is
evaluated against GT in `reports/day2/time_gap_analysis.md` before any
claim is made about which ones matter):

- delta_t_ms / log1p_delta_t_ms: the temporal-gap hypothesis, recomputed
  from timestamp_ms (never `ms_since_last_event` — established unsafe in
  Day 1). Both raw and log-transformed are kept because gap distributions
  are extremely right-skewed (Day 1: median 44ms, max ~2.4 hours) — a
  model given only the raw value would have that skew dominate it.
- density_before_ms / density_after_ms: event count in a fixed 5s window
  before/after the transition — a continuous proxy for "is activity
  bursty or sparse here," independent of any single gap value.
- application_changed / window_title_changed / browser_domain_changed /
  interaction_category_changed: the contextual-continuity signals your
  spec's formulation calls A_i/W_i/B_i/I_i, as binary indicators.
- extracted_text_at_transition: whether either event of the pair carries
  screen text — Day 1/Stage 2 found this concentrates near boundaries.
- chunk_boundary: whether the pair crosses a chunk file boundary.
  Included deliberately, not omitted — the project's own finding is that
  chunk boundaries are NOT process boundaries, and the only way to let a
  later model learn (or confirm) that is to give it the feature and let
  the evidence show it's non-predictive, rather than assuming that and
  leaving it out.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass

from procmine.segmentation.canonical import CanonicalEvent

DENSITY_WINDOW_MS = 5000


@dataclass
class TransitionFeatures:
    session_id: str
    event_i_id: str
    event_next_id: str
    timestamp_ms: int  # timestamp of event_i; the transition "happens" between this and the next
    next_timestamp_ms: int  # timestamp of the next event — the interval's exclusive upper bound

    delta_t_ms: int
    log1p_delta_t_ms: float
    density_before: int
    density_after: int

    application_changed: bool
    window_title_changed: bool
    browser_domain_changed: bool
    interaction_category_changed: bool
    extracted_text_at_transition: bool
    chunk_boundary: bool

    def to_dict(self) -> dict:
        return {**self.__dict__, "log1p_delta_t_ms": round(self.log1p_delta_t_ms, 4)}


def extract_transition_features(events: list[CanonicalEvent]) -> list[TransitionFeatures]:
    if len(events) < 2:
        return []

    timestamps = [e.timestamp_ms for e in events]
    features: list[TransitionFeatures] = []

    for i in range(len(events) - 1):
        cur, nxt = events[i], events[i + 1]
        delta_t = nxt.timestamp_ms - cur.timestamp_ms

        # density_before: events in (cur.ts - WINDOW, cur.ts]
        lo = bisect.bisect_right(timestamps, cur.timestamp_ms - DENSITY_WINDOW_MS)
        hi = bisect.bisect_right(timestamps, cur.timestamp_ms)
        density_before = hi - lo

        # density_after: events in [nxt.ts, nxt.ts + WINDOW)
        lo2 = bisect.bisect_left(timestamps, nxt.timestamp_ms)
        hi2 = bisect.bisect_left(timestamps, nxt.timestamp_ms + DENSITY_WINDOW_MS)
        density_after = hi2 - lo2

        features.append(
            TransitionFeatures(
                session_id=cur.session_id,
                event_i_id=cur.event_id,
                event_next_id=nxt.event_id,
                timestamp_ms=cur.timestamp_ms,
                next_timestamp_ms=nxt.timestamp_ms,
                delta_t_ms=delta_t,
                log1p_delta_t_ms=math.log1p(max(delta_t, 0)),
                density_before=density_before,
                density_after=density_after,
                application_changed=(cur.application != nxt.application),
                window_title_changed=(cur.window_title != nxt.window_title),
                browser_domain_changed=(cur.browser_domain != nxt.browser_domain),
                interaction_category_changed=(
                    cur.interaction_category != nxt.interaction_category
                ),
                extracted_text_at_transition=(cur.has_extracted_text or nxt.has_extracted_text),
                chunk_boundary=(cur.chunk_id != nxt.chunk_id),
            )
        )
    return features


@dataclass
class LabeledTransition:
    features: TransitionFeatures
    is_boundary: bool
    is_resume: bool | None  # only meaningful when is_boundary is True


def label_transitions(
    features: list[TransitionFeatures], boundaries: list[tuple[int, bool]]
) -> list[LabeledTransition]:
    """`boundaries` is a list of (timestamp_ms, is_resume) pairs. Labels
    exactly the ONE transition whose interval [event_i.timestamp_ms,
    event_next.timestamp_ms) contains each boundary timestamp — a
    containment join, not an exact-match or tolerance-window one. A GT
    boundary timestamp (from the scenario generator) generally does not
    equal any raw event's own timestamp, so an exact match would silently
    label almost nothing; a boundary conceptually falls *between* two
    specific consecutive raw events regardless of how far apart their
    timestamps are, which is what this looks up. `features` must already
    be in chronological order (it is, by construction from
    `extract_transition_features`). GT-only; never available for Dataset B."""
    is_boundary = [False] * len(features)
    is_resume: list[bool | None] = [None] * len(features)
    ts = [f.timestamp_ms for f in features]

    for b_ts, resume in boundaries:
        idx = bisect.bisect_right(ts, b_ts) - 1
        # bisect only bounds from below (the transition starting at or
        # before b_ts) — must also check b_ts hasn't run past that
        # transition's own end, e.g. a boundary after the last recorded
        # event in the session would otherwise wrongly match the last
        # transition (caught by
        # test_label_transitions_boundary_outside_any_interval_labels_nothing).
        if 0 <= idx < len(features) and b_ts < features[idx].next_timestamp_ms:
            is_boundary[idx] = True
            is_resume[idx] = resume

    return [
        LabeledTransition(features=f, is_boundary=ib, is_resume=ir)
        for f, ib, ir in zip(features, is_boundary, is_resume)
    ]
