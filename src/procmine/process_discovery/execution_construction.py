"""Section 3: turn the raw system-change segments (Section 2) into
coherent execution records, by merging short "leave and immediately
return to the same system" detours back into the surrounding work,
the same demote-only philosophy Design 2's Rule 2 used for Dataset A
(a candidate boundary can be removed, never invented) -- but designed
fresh from Dataset B's own evidence, not the fitted Dataset-A rule
itself, per the assignment's explicit instruction not to assume
Dataset A's approach transfers.

Reuses `interruption_forensics.detect_return_patterns` -- a generic,
GT-free utility built in Day 2 for exactly this "left context X, did Y,
came back to X" pattern on any categorical sequence. It has no
Dataset-A-specific logic; nothing about calling it here on
`system_identity` values instead of `application`/`browser_domain`
required changing it.

Merge threshold: measured directly on Dataset B (see
`reports/day3/process_discovery.md` section 3) -- immediate
(A -> B -> A) return patterns have a wide, continuous away-span
distribution (p25 = 5 events / ~3.3s, p50 = 11 events / ~4.4s, p90 =
36 events / ~14.8s), with no natural gap separating "brief glance"
from "genuine separate work." There is no ground truth to calibrate
this precisely. The p25 event-count value is used as the merge
threshold -- an explicit, evidence-grounded but acknowledged-imperfect
choice, not a claim of a validated cutoff. Only IMMEDIATE (single
intervening system) patterns are merged; longer A -> B -> C -> A
detours are left alone as a documented simplification.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from procmine.segmentation.canonical import CanonicalEvent
from procmine.segmentation.interruption_forensics import detect_return_patterns
from procmine.process_discovery.document_identity import document_key
from procmine.process_discovery.system_identity import fill_forward, system_identity

NOISE_APPLICATIONS = frozenset({"procmine-desktop-agent", "prl_cc"})


def merge_leave_and_return(
    canonical: list[CanonicalEvent], boundary: list[bool], max_away_events: int
) -> list[bool]:
    """Demotes (never adds) a boundary pair that forms an immediate
    leave-and-return pattern whose away span is short enough
    (`<= max_away_events`). `boundary` must be the raw
    `system_change_boundaries`-style array (one entry per transition,
    `len(canonical) - 1` entries) this function is refining -- not
    recomputed here, so callers control exactly which base segmentation
    is being merged."""
    n = len(canonical)
    if n == 0:
        if boundary:
            raise ValueError("boundary must be empty when canonical is empty")
        return []
    if len(boundary) != n - 1:
        raise ValueError("boundary must have exactly len(canonical) - 1 entries")

    ids_full = fill_forward([system_identity(e) for e in canonical])
    first_real = next((i for i, v in enumerate(ids_full) if v is not None), n)
    ids = ids_full[first_real:]
    patterns = [p for p in detect_return_patterns(ids, field="system") if p.is_immediate]

    result = list(boundary)
    for p in patterns:
        away_start, away_end = p.away_event_span
        away_events = away_end - away_start + 1
        if away_events > max_away_events:
            continue
        leave_idx = p.left_run_end_index + first_real  # last event of the run being left
        return_idx = p.returned_run_start_index + first_real - 1  # event just before the return run starts
        # the transition indices are the same as these event indices
        # (transition i sits between canonical[i] and canonical[i+1])
        if 0 <= leave_idx < len(result):
            result[leave_idx] = False
        if 0 <= return_idx < len(result):
            result[return_idx] = False
    return result


@dataclass
class Execution:
    execution_id: str
    session_id: str
    operator: str
    start_ms: int
    end_ms: int
    duration_ms: int
    event_count: int
    applications: list[str]
    dominant_context: str
    ordered_steps: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def _dominant_context(seg: list[CanonicalEvent]) -> str:
    """The single (system, document) context that accounts for the most
    events in this execution -- the grounding signal Section 4 uses to
    group executions into underlying processes. Refined with a document
    name for Word/Excel, where the system-level identity alone
    ("app:Microsoft Word") would conflate genuinely different documents/
    procedures into one bucket."""
    ids = fill_forward([system_identity(e) for e in seg])
    counts = Counter(v for v in ids if v is not None)
    if not counts:
        return "unknown"
    dominant_system, _ = counts.most_common(1)[0]

    if dominant_system.startswith("app:"):
        app_name = dominant_system[len("app:"):]
        doc_counts = Counter()
        for e in seg:
            if e.application == app_name:
                dk = document_key(e.application, e.window_title)
                if dk:
                    doc_counts[dk] += 1
        if doc_counts:
            doc, _ = doc_counts.most_common(1)[0]
            return f"{dominant_system}::{doc}"
    return dominant_system


def _step_runs(events: list[CanonicalEvent]) -> list[dict]:
    """Collapses a segment's own events into ordered steps: maximal runs
    of the same (system identity, interaction category) pair. This is
    the automated, data-derived stand-in for a human-labeled step list
    (e.g. "Open application" / "Enter data" / "Search") -- each run's
    dominant event types are reported so the label can be read directly
    from what the agent actually recorded, not guessed."""
    if not events:
        return []
    ids = fill_forward([system_identity(e) for e in events])
    keys = [(ids[i], events[i].interaction_category) for i in range(len(events))]

    steps = []
    start = 0
    for i in range(1, len(keys) + 1):
        if i == len(keys) or keys[i] != keys[start]:
            seg = events[start:i]
            sys_id, category = keys[start]
            type_counts = Counter(e.event_type for e in seg)
            steps.append({
                "system": sys_id, "interaction_category": category,
                "n_events": len(seg),
                "start_ms": seg[0].timestamp_ms, "end_ms": seg[-1].timestamp_ms,
                "dominant_event_types": type_counts.most_common(3),
            })
            start = i
    return steps


def build_executions(
    session_id: str, operator: str, canonical: list[CanonicalEvent], boundary: list[bool]
) -> list[Execution]:
    """One `Execution` per segment implied by `boundary` (the merged
    system-change boundary array). `execution_id` is
    `{session_id}::exec{n}`, 0-indexed in session order -- not a
    business identifier, since Dataset B has none, only a stable,
    reproducible label for this analysis."""
    n = len(canonical)
    if n == 0:
        if boundary:
            raise ValueError("boundary must be empty when canonical is empty")
        return []
    if len(boundary) != n - 1:
        raise ValueError("boundary must have exactly len(canonical) - 1 entries")

    bounds, start = [], 0
    for i, b in enumerate(boundary):
        if b:
            bounds.append((start, i))
            start = i + 1
    bounds.append((start, n - 1))

    executions = []
    for idx, (s, e) in enumerate(bounds):
        seg = canonical[s : e + 1]
        apps = sorted({ev.application for ev in seg if ev.application and ev.application not in NOISE_APPLICATIONS})
        executions.append(Execution(
            execution_id=f"{session_id}::exec{idx}",
            session_id=session_id, operator=operator,
            start_ms=seg[0].timestamp_ms, end_ms=seg[-1].timestamp_ms,
            duration_ms=seg[-1].timestamp_ms - seg[0].timestamp_ms,
            event_count=len(seg), applications=apps,
            dominant_context=_dominant_context(seg),
            ordered_steps=_step_runs(seg),
        ))
    return executions
