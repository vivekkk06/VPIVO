"""Execution identity and its state machine.

WHY EXECUTIONS NEED IDENTITY AND STATE
--------------------------------------
The earlier prototype held a checkpoint in a dict keyed by an opaque token and
consumed it on confirm. That is enough to prevent replay, and not enough to answer the
question a real integration must answer:

    the confirmation succeeded upstream, and the response was lost --
    did it happen or not?

Without a durable record there is nothing to ask. `UNKNOWN` is therefore a first-class
state rather than an error: it says "the outcome exists but this process does not know
it", which is precisely the situation a status lookup resolves.

The states are deliberately few. Every one corresponds to something an operator would
act on differently.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

PREPARED = "PREPARED"
AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
CONFIRMING = "CONFIRMING"
CONFIRMED = "CONFIRMED"
FAILED = "FAILED"
UNKNOWN = "UNKNOWN"
REPLAYED = "REPLAYED"

STATES = {PREPARED, AWAITING_CONFIRMATION, CONFIRMING, CONFIRMED, FAILED, UNKNOWN, REPLAYED}
TERMINAL = {CONFIRMED, FAILED, REPLAYED}

# Allowed transitions. UNKNOWN is not terminal: a status lookup can resolve it to
# CONFIRMED or FAILED, which is the entire reason the state exists.
TRANSITIONS: dict[str, set[str]] = {
    PREPARED: {AWAITING_CONFIRMATION, FAILED},
    AWAITING_CONFIRMATION: {CONFIRMING, FAILED, REPLAYED},
    CONFIRMING: {CONFIRMED, FAILED, UNKNOWN},
    UNKNOWN: {CONFIRMED, FAILED},
    CONFIRMED: set(),
    FAILED: set(),
    REPLAYED: set(),
}


class IllegalTransition(RuntimeError):
    """Raised on a transition the machine does not allow.

    Failing loudly matters here: silently permitting CONFIRMED -> CONFIRMING would be
    the shape of a double-submission bug.
    """


def new_execution_id() -> str:
    return f"exec_{uuid.uuid4().hex[:16]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ExecutionRecord:
    """What is persisted about one automation attempt.

    Note **content** is deliberately absent -- only its length. Tokens and credentials
    are absent entirely. This record is designed to be safe to ship to a log store.
    """

    execution_id: str
    request_id: str
    actor: str
    process: str
    route: str
    integration_mode: str
    status: str = PREPARED
    note_length: int = 0
    idempotency_key: str | None = None
    error_code: str | None = None
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    confirmed_at: str | None = None
    history: list[dict] = field(default_factory=list)

    def transition(self, to: str, *, error_code: str | None = None) -> "ExecutionRecord":
        if to not in STATES:
            raise IllegalTransition(f"unknown state {to!r}")
        allowed = TRANSITIONS[self.status]
        if to not in allowed:
            raise IllegalTransition(
                f"illegal transition {self.status} -> {to} "
                f"(allowed: {sorted(allowed) or 'none, terminal'})")
        self.history.append({"from": self.status, "to": to, "at": _now()})
        self.status = to
        self.updated_at = _now()
        if error_code:
            self.error_code = error_code
        if to == CONFIRMED:
            self.confirmed_at = self.updated_at
        return self

    def to_dict(self) -> dict:
        return {
            "execution_id": self.execution_id, "request_id": self.request_id,
            "actor": self.actor, "process": self.process, "route": self.route,
            "integration_mode": self.integration_mode, "status": self.status,
            "note_length": self.note_length, "idempotency_key": self.idempotency_key,
            "error_code": self.error_code, "created_at": self.created_at,
            "updated_at": self.updated_at, "confirmed_at": self.confirmed_at,
            "history": list(self.history),
        }
