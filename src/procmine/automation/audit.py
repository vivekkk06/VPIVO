"""Structured audit logging for automation actions.

WHY A SEPARATE MODULE
---------------------
Auditability is a governance requirement for anything touching payroll records, and
redaction is the part most easily got wrong. Keeping it here means the rule "note
content is never logged" is enforced in one place and can be tested directly, rather
than depending on every call site remembering it.

WHAT IS DELIBERATELY NOT RECORDED
---------------------------------
* **note content** — it is the operator's business text and has no place in an audit
  trail that may be shipped to a log aggregator;
* **anything resembling a credential** — Day 1 found 18 events carrying plaintext
  password-field content despite `redact_password_fields: true` in the capture
  settings, which is exactly why this module assumes nothing upstream is clean.

What IS recorded is everything needed to reconstruct *what the automation did*:
request id, execution id, route, action, result, error type, whether a human
checkpoint was passed, and a timestamp. Note **length** is kept because "was a note
supplied at all" is an auditable fact; its text is not.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

# Fields that must never reach the audit trail, whatever a caller passes.
REDACTED_KEYS = frozenset({
    "note", "note_text", "text", "final_text", "content", "value",
    "password", "passwd", "secret", "token", "checkpoint_token",
    "authorization", "api_key", "cookie",
})
_SECRETISH = re.compile(r"(password|secret|token|api[_-]?key|authorization)", re.I)

_LOCK = Lock()


def new_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:16]}"


def new_execution_id() -> str:
    return f"exec_{uuid.uuid4().hex[:16]}"


def redact(payload: dict) -> dict:
    """Drop anything sensitive, keeping only auditable shape.

    Unknown keys are kept, but a key that merely *looks* secret-ish is dropped too —
    on an audit path, failing closed is the right default.
    """
    out: dict = {}
    for k, v in payload.items():
        kl = k.lower()
        if kl in REDACTED_KEYS or _SECRETISH.search(kl):
            if kl in {"note", "note_text", "text", "content"} and isinstance(v, str):
                out[f"{k}_length"] = len(v)  # shape, never content
            else:
                out[f"{k}_redacted"] = True
            continue
        out[k] = v
    return out


@dataclass
class AuditEvent:
    request_id: str
    execution_id: str | None
    action: str
    result: str                      # "success" | "safe_stop" | "rejected" | "error"
    route: str | None = None
    error_type: str | None = None
    human_checkpoint: bool | None = None
    confirmation_status: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    detail: dict = field(default_factory=dict)

    def to_json(self) -> str:
        d = asdict(self)
        d["detail"] = redact(self.detail)
        return json.dumps(d, ensure_ascii=False, sort_keys=True)


class AuditLog:
    """Append-only JSONL audit trail.

    In-memory by default so tests and the demo need no filesystem; give it a path
    (or set `AUTOMATION_AUDIT_LOG`) to persist. Writes are locked because the demo
    API is threaded.
    """

    def __init__(self, path: str | Path | None = None, keep_in_memory: int = 500):
        env = os.environ.get("AUTOMATION_AUDIT_LOG")
        self.path = Path(path) if path else (Path(env) if env else None)
        self.keep_in_memory = keep_in_memory
        self.events: list[AuditEvent] = []

    def record(self, event: AuditEvent) -> AuditEvent:
        with _LOCK:
            self.events.append(event)
            if len(self.events) > self.keep_in_memory:
                del self.events[: -self.keep_in_memory]
            if self.path:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(event.to_json() + "\n")
        return event

    def recent(self, limit: int = 20) -> list[dict]:
        with _LOCK:
            return [json.loads(e.to_json()) for e in self.events[-limit:]]

    def clear(self) -> None:
        with _LOCK:
            self.events.clear()


# Error taxonomy. Every automation failure maps to exactly one of these, so a caller
# can branch on a stable string rather than parsing a message.
ERROR_TYPES = {
    # The automation prototype's own refusals.
    "INVALID_ROUTE",
    "INVALID_NOTE",
    "TARGET_NOT_FOUND",
    "AMBIGUOUS_TARGET",
    "PAGE_MISMATCH",
    "TARGET_CHANGED",
    "CHECKPOINT_REQUIRED",
    "CONFIRMATION_REJECTED",
    "REPLAYED_REQUEST",
    "AUTOMATION_TIMEOUT",
    "MALFORMED_REQUEST",
    # The API boundary: the *operator's* credential failed.
    "AUTHENTICATION_FAILED",
    "AUTHORIZATION_FAILED",
    # The integration: the *target service* refused or failed. Deliberately
    # distinct from the two above -- "our caller is not allowed" and "our service
    # account is not allowed" are different incidents with different owners.
    "INTEGRATION_UNAUTHORIZED",
    "INTEGRATION_FORBIDDEN",
    "INTEGRATION_CONFLICT",
    "INTEGRATION_TIMEOUT",
    "INTEGRATION_UNAVAILABLE",
    "INTEGRATION_SERVER_ERROR",
    "RATE_LIMITED",
    "DUPLICATE_REQUEST",
    # The outcome is genuinely not known -- resolved by status lookup, never by
    # retrying the mutation.
    "CONFIRMATION_UNKNOWN",
}

# Maps the prototype's exception classes onto that taxonomy.
EXCEPTION_TO_ERROR_TYPE = {
    "UnknownRouteError": "INVALID_ROUTE",
    "InvalidNoteError": "INVALID_NOTE",
    "ElementNotFoundError": "TARGET_NOT_FOUND",
    "DuplicateElementError": "AMBIGUOUS_TARGET",
    "NavigationError": "PAGE_MISMATCH",
    "BrowserNavigationError": "PAGE_MISMATCH",
    "ConfirmationFailedError": "CONFIRMATION_REJECTED",
    "NoteInsertionError": "TARGET_CHANGED",
}


def error_type_for(exc: BaseException) -> str:
    """Never raises: an unmapped failure still has to be auditable."""
    return EXCEPTION_TO_ERROR_TYPE.get(type(exc).__name__, "CONFIRMATION_REJECTED")
