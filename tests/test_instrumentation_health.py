"""Tests for the Day-4 instrumentation-health diagnostic.

Built from real `CanonicalEvent` objects (via `CanonicalEvent.from_event`)
rather than stubs, so these exercise the same `browser_domain` derivation
the diagnostic relies on in production rather than a parallel fake.
"""

from __future__ import annotations

from procmine.instrumentation_health import (
    MIN_BROWSER_DOMAIN_COVERAGE,
    MIN_DISTINCT_BROWSER_DOMAINS,
    STATUS_DEGRADED,
    STATUS_HEALTHY,
    assess_instrumentation_health,
    summarize_dataset_health,
)
from procmine.models import Event
from procmine.segmentation.canonical import CanonicalEvent


def _ce(event_id: str, ts_ms: int, url: str | None = None) -> CanonicalEvent:
    raw = {
        "event_id": event_id,
        "session_id": "s1",
        "timestamp_ms": ts_ms,
        "timestamp_iso": "2026-01-01T00:00:01.000Z",
        "layer": "L2",
        "event_type": "mouse_click",
        "correlation": {},
        "context": {
            "active_app": {"app_name": "Google Chrome", "window_title": "t"},
            **({"active_browser_tab": {"url": url}} if url else {}),
        },
        "payload": {},
    }
    return CanonicalEvent.from_event(Event.from_dict(raw))


def _stream(urls: list[str | None]):
    return [_ce(f"e{i}", i * 100, url=u) for i, u in enumerate(urls)]


def test_full_coverage_multiple_domains_is_healthy():
    events = _stream(
        ["http://127.0.0.1:5122/a", "http://127.0.0.1:5123/b"] * 5
    )
    h = assess_instrumentation_health("s1", events)
    assert h.status == STATUS_HEALTHY
    assert h.browser_domain_coverage == 1.0
    assert h.n_distinct_browser_domains == 2
    assert h.warnings == ()


def test_zero_coverage_is_degraded():
    events = _stream([None] * 10)
    h = assess_instrumentation_health("s1", events)
    assert h.status == STATUS_DEGRADED
    assert h.browser_domain_coverage == 0.0
    assert h.n_events_with_browser_domain == 0
    # both criteria fire: no domains at all, and coverage below threshold
    assert len(h.warnings) == 2


def test_no_distinct_domains_at_all_reports_zero():
    h = assess_instrumentation_health("s1", _stream([None] * 4))
    assert h.n_distinct_browser_domains == 0


def test_single_domain_is_degraded_even_at_full_coverage():
    # the LAPTOP-R36BQBTE ses_20260630-121953 case: plenty of coverage,
    # but one domain means a domain-CHANGE can never be observed
    events = _stream(["http://127.0.0.1:5122/a"] * 20)
    h = assess_instrumentation_health("s1", events)
    assert h.browser_domain_coverage == 1.0
    assert h.n_distinct_browser_domains == 1
    assert h.status == STATUS_DEGRADED
    assert any("distinct value" in w for w in h.warnings)


def test_partial_coverage_above_threshold_stays_healthy():
    # 6/10 = 60% coverage, two domains -> healthy
    urls = ["http://127.0.0.1:5122/a", "http://127.0.0.1:5123/b"] * 3 + [None] * 4
    h = assess_instrumentation_health("s1", _stream(urls))
    assert h.browser_domain_coverage == 0.6
    assert h.status == STATUS_HEALTHY


def test_partial_coverage_below_threshold_is_degraded():
    # 3/10 = 30% coverage, still two domains -> degraded on coverage only
    urls = ["http://127.0.0.1:5122/a", "http://127.0.0.1:5123/b", "http://127.0.0.1:5122/c"] + [None] * 7
    h = assess_instrumentation_health("s1", _stream(urls))
    assert h.browser_domain_coverage == 0.3
    assert h.n_distinct_browser_domains == 2
    assert h.status == STATUS_DEGRADED
    assert any("coverage is materially degraded" in w for w in h.warnings)


def test_threshold_boundary_is_inclusive_of_the_threshold_value():
    # exactly at the threshold counts as healthy (strictly-below fails)
    urls = ["http://127.0.0.1:5122/a", "http://127.0.0.1:5123/b"] * 2 + [None] * 6
    h = assess_instrumentation_health("s1", _stream(urls))
    assert h.browser_domain_coverage == MIN_BROWSER_DOMAIN_COVERAGE
    assert h.status == STATUS_HEALTHY


def test_thresholds_are_overridable_without_editing_the_module():
    events = _stream(["http://127.0.0.1:5122/a"] * 10)
    strict = assess_instrumentation_health("s1", events, min_distinct_domains=1)
    assert strict.status == STATUS_HEALTHY  # 1 domain now acceptable


def test_empty_session_is_degraded_not_silently_healthy():
    h = assess_instrumentation_health("s1", [])
    assert h.status == STATUS_DEGRADED
    assert h.n_events == 0
    assert h.browser_domain_coverage == 0.0
    assert any("no events" in w for w in h.warnings)


def test_repeated_execution_is_deterministic():
    events = _stream(["http://127.0.0.1:5122/a", None, "http://127.0.0.1:5123/b"] * 4)
    a = assess_instrumentation_health("s1", events)
    b = assess_instrumentation_health("s1", events)
    assert a == b
    assert a.to_dict() == b.to_dict()


def test_session_level_aggregation_counts_and_sorts():
    healthy = assess_instrumentation_health(
        "ses_b", _stream(["http://h/1", "http://i/2"] * 5)
    )
    bad1 = assess_instrumentation_health("ses_z", _stream([None] * 5))
    bad2 = assess_instrumentation_health("ses_a", _stream([None] * 5))
    summary = summarize_dataset_health([healthy, bad1, bad2])
    assert summary["n_sessions"] == 3
    assert summary["n_healthy"] == 1
    assert summary["n_degraded"] == 2
    # deterministic ordering regardless of input order
    assert summary["degraded_session_ids"] == ["ses_a", "ses_z"]
    assert summary["thresholds"]["min_distinct_browser_domains"] == MIN_DISTINCT_BROWSER_DOMAINS


def test_to_dict_round_trips_the_status_and_warnings():
    h = assess_instrumentation_health("s1", _stream([None] * 3))
    d = h.to_dict()
    assert d["status"] == STATUS_DEGRADED
    assert isinstance(d["warnings"], list)
    assert d["n_events"] == 3
