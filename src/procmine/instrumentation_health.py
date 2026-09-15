"""Session-level instrumentation-health diagnostic (Day 4).

Upstream, additive, diagnostic-only. This module is deliberately NOT part
of the locked segmentation path: it does not import, call, or influence
V1/V2, Rules 1-4, or the Combined protection layer, and no segmentation
decision reads its output. Its only job is to answer, before segmentation
runs, "does this session actually carry the evidence the segmentation
pipeline depends on?" so a degraded session's output can be qualified
instead of silently presented as normal.

Why browser_domain specifically: Day-4 forensics on Dataset A measured
that 96.6% of ground-truth process boundaries on normally-instrumented
machines coincide with a browser-domain change, while on the one machine
whose browser instrumentation never captured (LAPTOP-R36BQBTE, 7 of 63
sessions) that figure is 0%, and the locked pipeline's mean F1 there is
0.14 versus 0.32-0.40 elsewhere. The window-title fallback that worked
for Dataset B was tested on these sessions and does not recover the
signal (median lift 1.10, i.e. at chance), so the limitation is upstream
data capture, not the algorithm.

Both criteria below are evaluated per session; failing either marks the
session degraded.

1. `MIN_DISTINCT_BROWSER_DOMAINS` -- structural, not fitted. A
   domain-*change* signal is mathematically unobservable with fewer than
   two distinct domains, whatever the coverage. Dataset A's distinct-domain
   distribution has an empty bin at exactly 2 (counts: 0->6 sessions,
   1->1, 3->32, 4->20, 5->1, 6->1, 7->1, 13->1), so no session sits on
   this boundary.

2. `MIN_BROWSER_DOMAIN_COVERAGE` -- chosen from the shape of Dataset A's
   coverage distribution alone. The 56 healthy sessions occupy a tight
   band (46.42%-69.46%, median 57.56%); below it the largest empty gap
   runs 26.00% -> 46.42%. 0.40 sits inside that gap with a 6.4pp margin
   to the nearest healthy session. Disclosure: Dataset B's coverage
   distribution had already been observed during weakness identification,
   but this threshold was derived from Dataset A's gap structure only and
   was not adjusted to produce any particular Dataset-B outcome.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

MIN_DISTINCT_BROWSER_DOMAINS = 2
MIN_BROWSER_DOMAIN_COVERAGE = 0.40

STATUS_HEALTHY = "healthy"
STATUS_DEGRADED = "degraded"


@dataclass(frozen=True)
class InstrumentationHealth:
    """Per-session instrumentation assessment. `status` is the single
    field a caller needs; the counts are kept so a warning can say *why*
    without recomputing anything."""

    session_id: str
    n_events: int
    n_events_with_browser_domain: int
    browser_domain_coverage: float
    n_distinct_browser_domains: int
    status: str
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_degraded(self) -> bool:
        return self.status == STATUS_DEGRADED

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "n_events": self.n_events,
            "n_events_with_browser_domain": self.n_events_with_browser_domain,
            "browser_domain_coverage": round(self.browser_domain_coverage, 6),
            "n_distinct_browser_domains": self.n_distinct_browser_domains,
            "status": self.status,
            "warnings": list(self.warnings),
        }


def assess_instrumentation_health(
    session_id: str,
    canonical_events: Sequence,
    *,
    min_distinct_domains: int = MIN_DISTINCT_BROWSER_DOMAINS,
    min_coverage: float = MIN_BROWSER_DOMAIN_COVERAGE,
) -> InstrumentationHealth:
    """Assess one session from its canonical event stream.

    Reads only `CanonicalEvent.browser_domain`, reusing the already-tested
    URL-parsing done in `CanonicalEvent.from_event` rather than re-deriving
    domains here. Raw data is never modified or written.

    An empty session is reported degraded: zero events carry zero
    evidence, and silently calling that healthy is the exact failure mode
    this diagnostic exists to prevent.
    """
    n_events = len(canonical_events)
    domains = {
        ev.browser_domain
        for ev in canonical_events
        if getattr(ev, "browser_domain", None)
    }
    n_with_domain = sum(
        1 for ev in canonical_events if getattr(ev, "browser_domain", None)
    )
    coverage = (n_with_domain / n_events) if n_events else 0.0

    warnings: list[str] = []
    if n_events == 0:
        warnings.append("session contains no events")
    if len(domains) < min_distinct_domains:
        warnings.append(
            f"browser_domain has {len(domains)} distinct value(s), "
            f"below the {min_distinct_domains} required for a domain-change "
            f"signal to be observable at all"
        )
    if coverage < min_coverage:
        warnings.append(
            f"browser_domain coverage is materially degraded "
            f"({coverage:.1%} of events, below the {min_coverage:.0%} threshold)"
        )

    status = STATUS_DEGRADED if warnings else STATUS_HEALTHY
    return InstrumentationHealth(
        session_id=session_id,
        n_events=n_events,
        n_events_with_browser_domain=n_with_domain,
        browser_domain_coverage=coverage,
        n_distinct_browser_domains=len(domains),
        status=status,
        warnings=tuple(warnings),
    )


def summarize_dataset_health(
    healths: Iterable[InstrumentationHealth],
) -> dict:
    """Aggregate per-session assessments into a dataset-level summary.

    Deterministic: degraded sessions are reported in sorted session-id
    order so repeated runs produce byte-identical output.
    """
    items = list(healths)
    degraded = sorted(
        (h for h in items if h.is_degraded), key=lambda h: h.session_id
    )
    return {
        "n_sessions": len(items),
        "n_healthy": len(items) - len(degraded),
        "n_degraded": len(degraded),
        "degraded_session_ids": [h.session_id for h in degraded],
        "thresholds": {
            "min_distinct_browser_domains": MIN_DISTINCT_BROWSER_DOMAINS,
            "min_browser_domain_coverage": MIN_BROWSER_DOMAIN_COVERAGE,
        },
    }
