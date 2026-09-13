"""Boundary-signal evaluation: does a candidate event-level signal align with
real GT process-transition boundaries?

This persists the methodology Day 1 used ad-hoc (in one-off terminal
commands, never saved) to measure app-switch/extracted-text/gap-size
alignment against 1,689 real GT boundaries, and extends it with metrics
Day 1 didn't compute: precision (not just boundary coverage), a base-rate
-controlled "lift" so a signal isn't called useful just because it's
common, distance-from-boundary distribution, resume-vs-normal-boundary
behavior, and per-session stability.

Nothing here is Dataset-A-specific: it operates on already-loaded `Event`
and `GTExecution` objects, generic session/boundary structures, and a
caller-supplied predicate function. Dataset A vs. B, session IDs, and
process labels never appear in this module.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any, Callable

from procmine.models import Event, GTExecution

EventPredicate = Callable[[Event], bool]


@dataclass
class Boundary:
    """One real process-to-process transition, derived from consecutive
    closed GT executions in a session (sorted by start time)."""

    session_id: str
    timestamp_ms: int
    is_resume: bool
    prev_process_code: str
    next_process_code: str


def extract_boundaries(session_id: str, executions: list[GTExecution]) -> list[Boundary]:
    """Consecutive-execution transitions. Only executions with a defined
    end_ts are used, matching Day 1's methodology. A transition is tagged
    `is_resume` when the next execution carries a `split_id` (it's
    continuing a suspended split) or shares the prior execution's
    `case_id` (the same case picking back up) — this lets evaluation
    separate "genuinely new process" boundaries from "interrupted work
    resuming," which is the central distinction this project's non-
    contiguous-work requirement cares about."""
    closed = sorted((e for e in executions if e.end_ts is not None), key=lambda e: e.start_ts)
    boundaries = []
    for prev, nxt in zip(closed, closed[1:]):
        is_resume = bool(nxt.split_id) or (
            nxt.case_id is not None and nxt.case_id == prev.case_id
        )
        boundaries.append(
            Boundary(
                session_id=session_id,
                timestamp_ms=int(prev.end_ts.timestamp() * 1000),
                is_resume=is_resume,
                prev_process_code=prev.process_code,
                next_process_code=nxt.process_code,
            )
        )
    return boundaries


def _nearest_distance_ms(t: int, boundary_times_sorted: list[int]) -> int | None:
    if not boundary_times_sorted:
        return None
    import bisect

    idx = bisect.bisect_left(boundary_times_sorted, t)
    candidates = []
    if idx < len(boundary_times_sorted):
        candidates.append(abs(boundary_times_sorted[idx] - t))
    if idx > 0:
        candidates.append(abs(t - boundary_times_sorted[idx - 1]))
    return min(candidates) if candidates else None


@dataclass
class SignalEvaluation:
    signal_name: str
    window_ms: int
    n_sessions: int
    n_boundaries: int
    n_resume_boundaries: int
    n_signal_events: int
    n_total_events: int

    boundary_coverage: float
    false_negative_rate: float
    resume_boundary_coverage: float | None
    normal_boundary_coverage: float | None

    precision: float
    n_aligned_signal_events: int
    n_unaligned_signal_events: int

    distance_ms_median: float | None
    distance_ms_mean: float | None

    boundary_window_rate: float
    interior_rate: float
    lift: float | None

    per_session_coverage_mean: float
    per_session_coverage_std: float
    per_session_coverage_min: float
    per_session_coverage_max: float
    n_sessions_with_boundaries: int

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


def evaluate_signal(
    signal_name: str,
    events_by_session: dict[str, list[Event]],
    boundaries_by_session: dict[str, list[Boundary]],
    signal_fn: EventPredicate,
    window_ms: int = 2000,
) -> SignalEvaluation:
    all_boundaries: list[Boundary] = [b for bs in boundaries_by_session.values() for b in bs]
    n_boundaries = len(all_boundaries)
    n_resume = sum(1 for b in all_boundaries if b.is_resume)

    covered = 0
    covered_resume = 0
    covered_normal = 0

    n_signal_events = 0
    n_total_events = 0
    n_aligned = 0
    distances_of_aligned: list[int] = []

    n_events_near_any_boundary = 0
    n_signal_events_near_any_boundary = 0
    n_events_interior = 0
    n_signal_events_interior = 0

    per_session_coverage: dict[str, float] = {}
    n_sessions_with_boundaries = 0

    for session_id, events in events_by_session.items():
        boundaries = boundaries_by_session.get(session_id, [])
        boundary_times = sorted(b.timestamp_ms for b in boundaries)
        signal_times = sorted(e.timestamp_ms for e in events if signal_fn(e))

        n_signal_events += len(signal_times)
        n_total_events += len(events)

        if boundaries:
            n_sessions_with_boundaries += 1
            session_covered = 0
            for b in boundaries:
                nearest = _nearest_distance_ms(b.timestamp_ms, signal_times)
                hit = nearest is not None and nearest <= window_ms
                if hit:
                    covered += 1
                    session_covered += 1
                    if b.is_resume:
                        covered_resume += 1
                    else:
                        covered_normal += 1
            per_session_coverage[session_id] = session_covered / len(boundaries)

        for st in signal_times:
            nearest = _nearest_distance_ms(st, boundary_times)
            if nearest is not None and nearest <= window_ms:
                n_aligned += 1
                distances_of_aligned.append(nearest)

        for e in events:
            near_boundary = False
            if boundary_times:
                d = _nearest_distance_ms(e.timestamp_ms, boundary_times)
                near_boundary = d is not None and d <= window_ms
            is_signal = signal_fn(e)
            if near_boundary:
                n_events_near_any_boundary += 1
                if is_signal:
                    n_signal_events_near_any_boundary += 1
            else:
                n_events_interior += 1
                if is_signal:
                    n_signal_events_interior += 1

    boundary_window_rate = (
        n_signal_events_near_any_boundary / n_events_near_any_boundary
        if n_events_near_any_boundary
        else 0.0
    )
    interior_rate = n_signal_events_interior / n_events_interior if n_events_interior else 0.0
    lift = (boundary_window_rate / interior_rate) if interior_rate > 0 else None

    coverages = list(per_session_coverage.values())

    return SignalEvaluation(
        signal_name=signal_name,
        window_ms=window_ms,
        n_sessions=len(events_by_session),
        n_boundaries=n_boundaries,
        n_resume_boundaries=n_resume,
        n_signal_events=n_signal_events,
        n_total_events=n_total_events,
        boundary_coverage=covered / n_boundaries if n_boundaries else 0.0,
        false_negative_rate=1 - (covered / n_boundaries) if n_boundaries else 1.0,
        resume_boundary_coverage=(covered_resume / n_resume) if n_resume else None,
        normal_boundary_coverage=(
            covered_normal / (n_boundaries - n_resume) if (n_boundaries - n_resume) else None
        ),
        precision=n_aligned / n_signal_events if n_signal_events else 0.0,
        n_aligned_signal_events=n_aligned,
        n_unaligned_signal_events=n_signal_events - n_aligned,
        distance_ms_median=(
            statistics.median(distances_of_aligned) if distances_of_aligned else None
        ),
        distance_ms_mean=(
            statistics.fmean(distances_of_aligned) if distances_of_aligned else None
        ),
        boundary_window_rate=boundary_window_rate,
        interior_rate=interior_rate,
        lift=lift,
        per_session_coverage_mean=statistics.fmean(coverages) if coverages else 0.0,
        per_session_coverage_std=statistics.pstdev(coverages) if len(coverages) > 1 else 0.0,
        per_session_coverage_min=min(coverages) if coverages else 0.0,
        per_session_coverage_max=max(coverages) if coverages else 0.0,
        n_sessions_with_boundaries=n_sessions_with_boundaries,
    )


def deduplicate_consecutive(
    events: list[Event], event_type: str, payload_key: Callable[[Event], Any]
) -> list[Event]:
    """Drop an event of `event_type` when it immediately follows (in
    chronological order) another event of the same type with an identical
    `payload_key` result. Generalizes the app_switch dedup Day 1 found it
    needed but deferred to this layer — usable for any event type that
    turns out to have the same double-firing instrumentation defect."""
    out: list[Event] = []
    prev_key: Any = object()
    prev_type: str | None = None
    for e in events:
        if e.event_type == event_type:
            key = payload_key(e)
            if prev_type == event_type and key == prev_key:
                continue
            prev_key = key
            prev_type = e.event_type
        else:
            prev_type = e.event_type
        out.append(e)
    return out


def app_switch_payload_key(e: Event) -> Any:
    payload = e.raw.get("payload") or {}
    new_app = (payload.get("new_app") or {}).get("app_name")
    prev_app = (payload.get("previous_app") or {}).get("app_name")
    return (new_app, prev_app)


# --- Signal predicates -----------------------------------------------------
# Each takes a single Event and returns whether it counts as a "signal
# firing." Kept as small, named functions rather than inline lambdas so
# each one is independently testable and documents its own definition.


def is_window_title_change(e: Event) -> bool:
    return e.event_type == "window_title_change"


def is_browser_navigation(e: Event) -> bool:
    return e.event_type == "browser_navigation"


def is_clipboard_change(e: Event) -> bool:
    return e.event_type == "clipboard_change"


def has_extracted_text(e: Event) -> bool:
    text_field = (e.raw.get("context") or {}).get("extracted_text")
    if not isinstance(text_field, dict):
        return False
    return bool(text_field.get("text"))
