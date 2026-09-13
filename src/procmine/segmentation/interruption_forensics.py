"""Stage 8: forensic characterization of interruption/return patterns
inside GT executions — pure, reusable building blocks the analysis
script needs but no prior stage built.

Investigation only. Builds on, and does not redefine, the existing
category scheme (`continuity_labels.SAME_EXECUTION` etc., Stage 4) and
the false-internal-boundary definition from
`reports/day2/false_boundary_forensics.md` §1 (model probability over
threshold, not a real GT boundary, both endpoints inside one GT
execution's span). Nothing here trains a model, selects a threshold, or
touches Dataset B.

Two building blocks, because no prior stage needed either:

- `internal_transition_indices` / `build_execution_profile`: which
  transitions fall entirely inside one GT execution's span, and a
  per-execution summary of their gap/context-change structure. The span-
  containment convention (both bounds inclusive) matches
  `continuity_labels._containing_execution_case_id` exactly, not a new
  convention.
- `collapse_to_runs` / `detect_return_patterns`: detects "left context X,
  did something else, came back to X" in a categorical event field
  (`application` or `browser_domain`) — the brief's named A -> B -> A
  pattern, generalized to A -> B -> C -> A per its own "more general
  context trajectories" request.
"""

from __future__ import annotations

from dataclasses import dataclass

from procmine.models import GTExecution
from procmine.segmentation.features import TransitionFeatures


def internal_transition_indices(
    features: list[TransitionFeatures], start_ms: int, end_ms: int
) -> list[int]:
    """Indices of transitions fully inside [start_ms, end_ms] (inclusive
    both ends — the same convention already used for GT-execution span
    membership elsewhere in this project). `features` must be
    chronologically ordered, which `extract_transition_features` already
    guarantees."""
    return [
        i
        for i, f in enumerate(features)
        if start_ms <= f.timestamp_ms and f.next_timestamp_ms <= end_ms
    ]


@dataclass
class ExecutionInterruptionProfile:
    session_id: str
    case_id: str
    process_code: str
    start_ms: int
    end_ms: int
    duration_ms: int
    n_internal_transitions: int

    max_internal_gap_ms: int | None
    argmax_gap_transition_index: int | None  # index into the session's `features` list
    n_gaps_ge_p90: int
    n_gaps_ge_p95: int
    n_gaps_ge_p99: int

    n_app_switches: int
    n_window_title_changes: int
    n_browser_domain_changes: int
    n_interaction_category_changes: int

    mean_density_before: float | None
    mean_density_after: float | None
    density_before_at_max_gap: int | None
    density_after_at_max_gap: int | None

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def build_execution_profile(
    session_id: str,
    execution: GTExecution,
    features: list[TransitionFeatures],
    p90: float,
    p95: float,
    p99: float,
) -> ExecutionInterruptionProfile:
    """`p90`/`p95`/`p99` are the global SAME_EXECUTION gap-distribution
    percentiles, computed once, dataset-wide, by the caller — "large gap"
    is data-driven from the observed distribution, not an arbitrary
    constant chosen in this function. `execution.end_ts` must not be
    None (caller filters closed executions first, matching every other
    module's convention)."""
    start_ms = int(execution.start_ts.timestamp() * 1000)
    end_ms = int(execution.end_ts.timestamp() * 1000)
    idx = internal_transition_indices(features, start_ms, end_ms)
    internal = [features[i] for i in idx]

    gaps = [f.delta_t_ms for f in internal]
    max_gap = max(gaps) if gaps else None
    argmax_i = idx[gaps.index(max_gap)] if gaps else None
    max_gap_f = features[argmax_i] if argmax_i is not None else None

    density_before_vals = [f.density_before for f in internal]
    density_after_vals = [f.density_after for f in internal]

    return ExecutionInterruptionProfile(
        session_id=session_id,
        case_id=execution.case_id,
        process_code=execution.process_code,
        start_ms=start_ms,
        end_ms=end_ms,
        duration_ms=end_ms - start_ms,
        n_internal_transitions=len(internal),
        max_internal_gap_ms=max_gap,
        argmax_gap_transition_index=argmax_i,
        n_gaps_ge_p90=sum(1 for g in gaps if g >= p90),
        n_gaps_ge_p95=sum(1 for g in gaps if g >= p95),
        n_gaps_ge_p99=sum(1 for g in gaps if g >= p99),
        n_app_switches=sum(1 for f in internal if f.application_changed),
        n_window_title_changes=sum(1 for f in internal if f.window_title_changed),
        n_browser_domain_changes=sum(1 for f in internal if f.browser_domain_changed),
        n_interaction_category_changes=sum(1 for f in internal if f.interaction_category_changed),
        mean_density_before=(
            sum(density_before_vals) / len(density_before_vals) if density_before_vals else None
        ),
        mean_density_after=(
            sum(density_after_vals) / len(density_after_vals) if density_after_vals else None
        ),
        density_before_at_max_gap=max_gap_f.density_before if max_gap_f else None,
        density_after_at_max_gap=max_gap_f.density_after if max_gap_f else None,
    )


def collapse_to_runs(values: list[str]) -> list[tuple[str, int, int]]:
    """Run-length-encodes a categorical sequence into (value, start_index,
    end_index) triples (indices into `values`). Callers should filter out
    `None` entries first — a `None` context value (e.g. an event with no
    active application recorded) is treated as a real, distinct value if
    passed in, which is almost never what a caller analyzing genuine
    context switches wants."""
    if not values:
        return []
    runs: list[tuple[str, int, int]] = []
    start = 0
    for i in range(1, len(values) + 1):
        if i == len(values) or values[i] != values[start]:
            runs.append((values[start], start, i - 1))
            start = i
    return runs


@dataclass
class ReturnPattern:
    field: str  # "application" or "browser_domain"
    value: str
    left_run_end_index: int  # index (into the original sequence) where value's run ended
    returned_run_start_index: int  # index where value's run resumes
    away_values: list[str]  # distinct intervening runs, in order
    away_event_span: tuple[int, int]  # (start_index, end_index) of the away period
    is_immediate: bool  # True <=> exactly one intervening run: the literal A -> B -> A case

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def detect_return_patterns(values: list[str], field: str) -> list[ReturnPattern]:
    """Detects "left context X, did something else, came back to X" in a
    categorical sequence (e.g. per-event `application` or `browser_domain`
    within one GT execution). `is_immediate=True` is the brief's literal
    A -> B -> A example (exactly one intervening run); `is_immediate=False`
    covers a longer detour (A -> B -> C -> A, ...) per its own "more
    general context trajectories" request.

    Every reappearance is reported relative to its MOST RECENT departure,
    not the first-ever occurrence — e.g. A B A B A yields two separate
    immediate return patterns (A at index 2, B at index 3, A at index 4),
    not one pattern spanning the whole sequence. `values` should already
    have `None`/missing entries filtered out by the caller."""
    runs = collapse_to_runs(values)
    last_seen_run_idx: dict[str, int] = {}
    patterns: list[ReturnPattern] = []

    for j, (value, start_idx, _end_idx) in enumerate(runs):
        if value in last_seen_run_idx:
            k = last_seen_run_idx[value]
            away_runs = runs[k + 1 : j]
            patterns.append(
                ReturnPattern(
                    field=field,
                    value=value,
                    left_run_end_index=runs[k][2],
                    returned_run_start_index=start_idx,
                    away_values=[r[0] for r in away_runs],
                    away_event_span=(runs[k][2] + 1, start_idx - 1),
                    is_immediate=(len(away_runs) == 1),
                )
            )
        last_seen_run_idx[value] = j

    return patterns
