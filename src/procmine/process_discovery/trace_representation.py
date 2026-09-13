"""Problem 2 investigation: trace abstraction for process-mining
analysis (Directly-Follows Graph, sequence similarity, variant
discovery).

An execution's raw event stream (up to 204 events for a single
HR/Payroll dominant-path execution, most of it `screenshot_smart` --
an automatic side-effect, not a deliberate action) is far too noisy to
use as a process-mining "trace" directly. Two abstraction levels are
built here and compared in
`reports/day3/problem2_process_mining_analysis.md` section 7:

- SYSTEM_LEVEL: the sequence of distinct systems/applications touched,
  deduplicating consecutive repeats. This is exactly
  `variant_analysis.variant_signature` -- reused, not duplicated, since
  it is already the coarsest trace abstraction the existing Day-3
  pipeline computes.
- ACTIVITY_LEVEL: the sequence of (system, interaction_category) pairs
  from an execution's own `ordered_steps` -- finer than SYSTEM_LEVEL
  (distinguishes "typing within the HR system" from "clicking within
  the HR system"), coarser than raw `event_type` (collapses automatic/
  system-layer noise into the interaction-category taxonomy already
  established in `canonical.py`, e.g. `screenshot_smart` -> "capture").
"""

from __future__ import annotations

from procmine.process_discovery.variant_analysis import variant_signature


def system_level_trace(ordered_steps: list[dict]) -> tuple[str, ...]:
    """The coarsest trace abstraction -- an alias for
    `variant_signature`, kept as its own name in this module so callers
    reasoning about trace *representations* don't need to know it reuses
    the existing variant-analysis function."""
    return variant_signature(ordered_steps)


def activity_level_trace(ordered_steps: list[dict]) -> tuple[str, ...]:
    """(system, interaction_category) pairs, in order, deduplicating
    consecutive identical pairs. `ordered_steps` already splits by both
    system AND category changes (see `execution_construction._step_runs`),
    so consecutive entries are already distinct by construction in the
    normal case -- the dedup here is a defensive guard, not something
    expected to fire on well-formed input. Steps with no resolved
    system (`None`, e.g. a recording-agent window) are skipped, the
    same way `variant_signature` skips them."""
    trace: list[str] = []
    for step in ordered_steps:
        system = step.get("system")
        if system is None:
            continue
        label = f"{system}|{step.get('interaction_category')}"
        if not trace or trace[-1] != label:
            trace.append(label)
    return tuple(trace)
