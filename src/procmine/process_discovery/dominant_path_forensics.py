"""Small, testable building blocks for the HR/Payroll dominant-path
forensic deep-dive (`scripts/analyze_hr_payroll_dominant_path.py`).
Diagnostic only -- not part of the Section 1-13 pipeline and not wired
into the Dataset-A locked architecture.
"""

from __future__ import annotations

from procmine.process_discovery.variant_analysis import variant_signature


def classify_variant(ordered_steps: list[dict], process_id: str) -> str:
    """Buckets an execution belonging to `process_id` into one of three
    groups, from its own `variant_signature`:

    - "dominant": stays entirely within `process_id` (a length-1
      signature equal to `process_id` itself).
    - "word_detour": touches `process_id` and `app:Microsoft Word`
      only, in any combination (a single dip, or several).
    - "other": anything else (a different system entirely, e.g. a
      Windows Explorer detour or a multi-hop pattern into another
      named system) -- the rare-edge-case bucket.
    """
    sig = variant_signature(ordered_steps)
    if sig == (process_id,):
        return "dominant"
    if (
        process_id in sig
        and "app:Microsoft Word" in sig
        and all(s in (process_id, "app:Microsoft Word") for s in sig)
    ):
        return "word_detour"
    return "other"


def surrounding_context(raw_events: list[dict], start_ms: int, end_ms: int) -> tuple[dict | None, dict | None]:
    """The raw event immediately before `start_ms` and immediately
    after `end_ms` in `raw_events` (a full session's sorted raw event
    list) -- characterizes how an execution was entered/exited, which
    the execution's own event slice can't show by itself. `(None,
    None)` if there is nothing before/after (the execution is the
    first/last thing in the session)."""
    before = [e for e in raw_events if e["timestamp_ms"] < start_ms]
    after = [e for e in raw_events if e["timestamp_ms"] > end_ms]
    return (before[-1] if before else None, after[0] if after else None)
