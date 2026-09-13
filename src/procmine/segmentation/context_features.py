"""Local context and before/after trajectory features.

Separate from `features.py`'s per-transition (event_i, event_next) view —
this module looks at an N-event window on each side of a transition and
asks whether the activity *trajectory* resumes after a gap, rather than
only comparing the two immediately-adjacent events. Built specifically to
test the Stage 5 hypothesis: a long pause shouldn't imply a boundary if
the surrounding activity forms a consistent trajectory.

Offline vs. online, stated explicitly per instruction: the "after" window
uses events that occur later in the recorded log. This is valid for the
assignment's actual task (reconstructing completed executions from a
finished log — offline), and invalid for a hypothetical real-time/online
segmenter, which could not see future events. Nothing here claims to
support an online implementation; this module belongs to the offline
reconstruction path only.

No feature in this module touches GT (process_code, case_id, variant,
labels, execution boundaries) — it operates purely on `CanonicalEvent`
sequences, the same input `features.py` uses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from procmine.segmentation.canonical import CanonicalEvent

_WORD_RE = re.compile(r"\w+")


@dataclass
class WindowSummary:
    applications: frozenset
    event_types: frozenset
    interaction_categories: frozenset
    browser_domains_with_port: frozenset  # existing CanonicalEvent.browser_domain (netloc)
    browser_domains_host_only: frozenset  # V2 hypothesis: hostname, port stripped
    window_title_tokens: frozenset
    duration_ms: int  # wall-clock span covered by this window's events
    has_extracted_text: bool
    n_events: int


def _hostname_only(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return urlparse(url).hostname
    except ValueError:
        return None


def summarize_window(events: list[CanonicalEvent]) -> WindowSummary:
    if not events:
        return WindowSummary(frozenset(), frozenset(), frozenset(), frozenset(), frozenset(), frozenset(), 0, False, 0)

    apps = frozenset(e.application for e in events if e.application)
    types = frozenset(e.event_type for e in events)
    categories = frozenset(e.interaction_category for e in events)
    domains_port = frozenset(e.browser_domain for e in events if e.browser_domain)
    domains_host = frozenset(
        h for e in events if (h := _hostname_only(e.browser_url)) is not None
    )
    title_tokens = frozenset(
        tok.lower()
        for e in events
        if e.window_title
        for tok in _WORD_RE.findall(e.window_title)
    )
    duration = events[-1].timestamp_ms - events[0].timestamp_ms
    has_text = any(e.has_extracted_text for e in events)

    return WindowSummary(
        applications=apps,
        event_types=types,
        interaction_categories=categories,
        browser_domains_with_port=domains_port,
        browser_domains_host_only=domains_host,
        window_title_tokens=title_tokens,
        duration_ms=duration,
        has_extracted_text=has_text,
        n_events=len(events),
    )


def before_window(canonical: list[CanonicalEvent], index_i: int, n: int) -> WindowSummary:
    """Events ending at and including index_i (the transition's first
    event), looking back up to n events."""
    start = max(0, index_i - n + 1)
    return summarize_window(canonical[start : index_i + 1])


def after_window(canonical: list[CanonicalEvent], index_next: int, n: int) -> WindowSummary:
    """Events starting at and including index_next (the transition's
    second event), looking forward up to n events."""
    end = min(len(canonical), index_next + n)
    return summarize_window(canonical[index_next:end])


def _jaccard(a: frozenset, b: frozenset) -> float | None:
    """None (not 0.0) when both sides are empty — no evidence either way,
    not evidence of dissimilarity. Callers must not silently treat this
    as 0."""
    if not a and not b:
        return None
    union = a | b
    if not union:
        return None
    return len(a & b) / len(union)


@dataclass
class TrajectoryFeatures:
    window_size: int
    application_jaccard: float | None
    event_type_jaccard: float | None
    interaction_category_jaccard: float | None
    browser_domain_jaccard_with_port: float | None
    browser_domain_jaccard_host_only: float | None
    window_title_jaccard: float | None
    before_window_duration_ms: int
    after_window_duration_ms: int
    before_has_text: bool
    after_has_text: bool

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def extract_trajectory_features(
    canonical: list[CanonicalEvent], index_i: int, n: int
) -> TrajectoryFeatures:
    """`index_i` is the transition's first event; `index_i + 1` is
    assumed to be its second event (matches `TransitionFeatures`'
    (event_i, event_next) convention)."""
    before = before_window(canonical, index_i, n)
    after = after_window(canonical, index_i + 1, n)

    return TrajectoryFeatures(
        window_size=n,
        application_jaccard=_jaccard(before.applications, after.applications),
        event_type_jaccard=_jaccard(before.event_types, after.event_types),
        interaction_category_jaccard=_jaccard(
            before.interaction_categories, after.interaction_categories
        ),
        browser_domain_jaccard_with_port=_jaccard(
            before.browser_domains_with_port, after.browser_domains_with_port
        ),
        browser_domain_jaccard_host_only=_jaccard(
            before.browser_domains_host_only, after.browser_domains_host_only
        ),
        window_title_jaccard=_jaccard(before.window_title_tokens, after.window_title_tokens),
        before_window_duration_ms=before.duration_ms,
        after_window_duration_ms=after.duration_ms,
        before_has_text=before.has_extracted_text,
        after_has_text=after.has_extracted_text,
    )
