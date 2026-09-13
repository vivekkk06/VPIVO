"""Candidate execution-boundary methods for Dataset B, tested against
each other rather than assumed -- Dataset B has no ground truth, so
"testing" here means comparing each method's own descriptive behavior
(segment count, length distribution, qualitative alignment with the
named systems from the profile), not F1 against a label that doesn't
exist. See `scripts/discover_executions_dataset_b.py` for the
comparison and `reports/day3/process_discovery.md` for the evidence
and decision.

None of Dataset A's fitted architecture (V1/V2/Design 2/Combined,
their thresholds, or their training) is imported or reused here --
those were fit against Dataset A's ground truth and have no meaning
without it. Only the generic, dataset-agnostic `CanonicalEvent`/
`TransitionFeatures` representations are reused, exactly as their own
docstrings describe them being built for.
"""

from __future__ import annotations

from procmine.segmentation.canonical import CanonicalEvent
from procmine.segmentation.features import TransitionFeatures
from procmine.process_discovery.system_identity import fill_forward, system_identity, system_identity_changed


def gap_threshold_boundaries(features: list[TransitionFeatures], threshold_ms: float) -> list[bool]:
    """Boundary wherever the raw inter-event gap is at or above
    `threshold_ms`. `threshold_ms` must be chosen from Dataset B's own
    gap distribution (see the profile's percentile table) -- never a
    constant carried over from Dataset A's very different gap regime."""
    return [f.delta_t_ms >= threshold_ms for f in features]


def application_change_boundaries(features: list[TransitionFeatures]) -> list[bool]:
    """Boundary wherever `active_app.app_name` changes -- the coarsest
    context signal already computed by `extract_transition_features`."""
    return [f.application_changed for f in features]


def system_change_boundaries(canonical: list[CanonicalEvent]) -> list[bool]:
    """Boundary wherever the resolved system identity (browser domain
    with port, or non-browser application name; recording/VM noise
    apps excluded) changes between two consecutive events. Finer than
    `application_change_boundaries` when the application is a browser
    (splits by which of the three localhost systems is active), and
    coarser when it isn't (a `None` on either side -- no system
    evidence -- is never treated as a change)."""
    ids = fill_forward([system_identity(e) for e in canonical])
    return [system_identity_changed(ids[i], ids[i + 1]) for i in range(len(canonical) - 1)]


def debounced_system_change_boundaries(canonical: list[CanonicalEvent], min_persist: int) -> list[bool]:
    """Same system-identity change as `system_change_boundaries`, but a
    candidate boundary is only kept if the new system identity persists
    for at least `min_persist` consecutive events afterward (including
    the triggering event itself). Filters out a single-event flicker
    (e.g. a stray one-event window-focus blip) that a raw system-change
    check would otherwise count as a real execution switch.
    `min_persist` must be >= 1; `min_persist=1` is identical to
    `system_change_boundaries`."""
    if min_persist < 1:
        raise ValueError("min_persist must be >= 1")
    ids = fill_forward([system_identity(e) for e in canonical])
    n = len(canonical)
    raw = [system_identity_changed(ids[i], ids[i + 1]) for i in range(n - 1)]

    kept = [False] * (n - 1)
    for i in range(n - 1):
        if not raw[i]:
            continue
        new_id = ids[i + 1]
        run_end = i + 1
        while run_end < n and ids[run_end] == new_id:
            run_end += 1
        run_length = run_end - (i + 1)
        if run_length >= min_persist:
            kept[i] = True
    return kept
