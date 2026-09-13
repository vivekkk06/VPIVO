"""Section 4: variant signature for an already-built execution record.

A variant is the ordered sequence of DISTINCT systems the execution
touches, collapsing consecutive steps that share a system (an
execution's `ordered_steps` already splits further by interaction
category, which is finer than a variant needs). Two executions with
the same signature took the same "shape" of path through the systems
involved, even if their step counts/durations differ -- exactly the
"Standard -> Excel -> Submit" vs. "Excel -> Email -> Submit" kind of
distinction the assignment's own example describes, derived here from
the actual recorded steps rather than authored by hand.
"""

from __future__ import annotations


def variant_signature(ordered_steps: list[dict]) -> tuple[str, ...]:
    seq: list[str] = []
    for step in ordered_steps:
        sysid = step.get("system")
        if sysid is None:
            continue
        if not seq or seq[-1] != sysid:
            seq.append(sysid)
    return tuple(seq)
