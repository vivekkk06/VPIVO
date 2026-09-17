"""Structured events and counters for one automation execution.

Complements the existing `procmine.automation.audit` module rather than replacing it:
audit answers *what was done and by whom* for governance; this answers *what happened
and how often* for operations. Both redact through the same function, so neither can
leak note content or credentials.

Nothing heavier than a dict is used. Prometheus, OpenTelemetry and friends would be
infrastructure theatre for a local prototype — the counters below are enough to show
the shape, and a production deployment would export them rather than reinvent them.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

from procmine.automation.audit import redact

# Lifecycle events. One per meaningful decision point, so a single execution can be
# reconstructed end to end from request_id + execution_id.
REQUEST_RECEIVED = "REQUEST_RECEIVED"
AUTHENTICATED = "AUTHENTICATED"
AUTHORIZED = "AUTHORIZED"
PREPARED = "PREPARED"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
CONFIRM_REQUESTED = "CONFIRM_REQUESTED"
CONFIRM_STARTED = "CONFIRM_STARTED"
CONFIRMED = "CONFIRMED"
FAILED = "FAILED"
UNKNOWN = "UNKNOWN"
REPLAY_REJECTED = "REPLAY_REJECTED"
# Resolving an UNKNOWN outcome: the status source could not be reached, or reports
# the confirmation still in progress. Either way the execution stays UNKNOWN.
STATUS_LOOKUP_FAILED = "STATUS_LOOKUP_FAILED"
STILL_IN_PROGRESS = "STILL_IN_PROGRESS"

_LOCK = threading.Lock()


@dataclass
class TraceEvent:
    event: str
    request_id: str
    execution_id: str | None = None
    actor: str | None = None
    route: str | None = None
    integration_mode: str | None = None
    error_code: str | None = None
    duration_ms: float | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "detail" and v is not None}
        if self.detail:
            d["detail"] = redact(self.detail)
        return d


@dataclass
class Observability:
    events: list[TraceEvent] = field(default_factory=list)
    counters: dict[str, int] = field(default_factory=dict)
    durations_ms: list[float] = field(default_factory=list)
    keep: int = 500

    def record(self, event: TraceEvent) -> TraceEvent:
        with _LOCK:
            self.events.append(event)
            if len(self.events) > self.keep:
                del self.events[: -self.keep]
            if event.duration_ms is not None:
                self.durations_ms.append(event.duration_ms)
        return event

    def incr(self, name: str, by: int = 1) -> None:
        with _LOCK:
            self.counters[name] = self.counters.get(name, 0) + by

    def recent(self, limit: int = 30, execution_id: str | None = None) -> list[dict]:
        with _LOCK:
            evs = [e for e in self.events
                   if execution_id is None or e.execution_id == execution_id]
            return [e.to_dict() for e in evs[-limit:]]

    def metrics(self) -> dict:
        with _LOCK:
            d = dict(self.counters)
            if self.durations_ms:
                s = sorted(self.durations_ms)
                d["confirmation_duration_ms_p50"] = round(s[len(s) // 2], 2)
                d["confirmation_duration_ms_max"] = round(s[-1], 2)
            return d

    def reset(self) -> None:
        with _LOCK:
            self.events.clear(); self.counters.clear(); self.durations_ms.clear()


# Counter names, fixed so dashboards and tests agree.
REQUESTS_TOTAL = "automation_requests_total"
SUCCESS_TOTAL = "automation_success_total"
FAILURE_TOTAL = "automation_failure_total"
UNKNOWN_TOTAL = "automation_unknown_total"
REPLAY_TOTAL = "replay_attempts_total"
