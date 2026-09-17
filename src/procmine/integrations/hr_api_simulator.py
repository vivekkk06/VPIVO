"""A local simulator standing in for an external HR REST service.

WHY A SIMULATOR AND NOT A REAL CLIENT
-------------------------------------
No real HR API contract, endpoint or credential exists for this project, and Dataset B
never evidenced an API call. Writing a client against an invented contract would be
fabricating the one thing the whole project has refused to fabricate.

So this simulates a service with the *properties* that matter for integration
engineering -- authentication, idempotency, conflict, timeouts, rate limiting -- and is
explicit that it is a simulator. It runs in-process; nothing leaves the machine.

DETERMINISM
-----------
Failures are **selected**, never random. A caller asks for `TIMEOUT` and gets exactly
one timeout at the point it configures. A demo that fails randomly cannot be
reproduced, and an assignment reviewer cannot re-run it.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from procmine.process_discovery.dom_evidence import KNOWN_ROUTE_PREFIXES

# Deterministic behaviour modes the simulator can be put into.
SUCCESS = "SUCCESS"
UNAUTHORIZED = "UNAUTHORIZED"
FORBIDDEN = "FORBIDDEN"
NOT_FOUND = "NOT_FOUND"
CONFLICT = "CONFLICT"
RATE_LIMITED = "RATE_LIMITED"
SERVER_ERROR = "SERVER_ERROR"
TIMEOUT = "TIMEOUT"
NETWORK_ERROR = "NETWORK_ERROR"
DUPLICATE_REQUEST = "DUPLICATE_REQUEST"

FAILURE_MODES = [SUCCESS, UNAUTHORIZED, FORBIDDEN, NOT_FOUND, CONFLICT,
                 RATE_LIMITED, SERVER_ERROR, TIMEOUT, NETWORK_ERROR, DUPLICATE_REQUEST]

# Valid simulator credential. A development constant, not a secret: it grants access
# to an in-process simulator with no real data behind it.
SIMULATOR_TOKEN = "local-simulator-token"


class HRApiError(Exception):
    """Transport/protocol failure from the simulated service.

    Carries an HTTP-like status and a stable code so the adapter can translate without
    parsing prose. `submitted_unknown` marks the case that matters most: the service
    may have applied the change but the caller cannot tell.
    """

    def __init__(self, code: str, status: int, message: str, *, submitted_unknown: bool = False):
        super().__init__(message)
        self.code = code
        self.status = status
        self.submitted_unknown = submitted_unknown


@dataclass
class _Record:
    route: str
    note_length: int
    confirmed: bool = False
    idempotency_key: str | None = None


@dataclass
class HRApiSimulator:
    """In-process stand-in for an external HR service.

    `mode` selects the failure; `fail_stage` selects *where* it strikes, and defaults
    to `confirm`. That default is not cosmetic: the interesting failures are the ones
    that happen after a human has already approved the action, so a mode that also
    broke `open_route` would make the review checkpoint unreachable and the
    lost-response demo impossible to stage. Tests that want an earlier failure set
    `fail_stage` explicitly.

    Credential failures are the exception -- `UNAUTHORIZED` and `FORBIDDEN` are
    checked on every call, because a service account that is rejected is rejected from
    the first request, not politely at confirm time.

    `applied_despite_failure` models the genuinely dangerous case -- the service
    commits the change and then the response is lost -- which is what makes status
    lookup necessary rather than nice.
    """

    mode: str = SUCCESS
    fail_stage: str = "confirm"
    applied_despite_failure: bool = False
    _records: dict[str, _Record] = field(default_factory=dict)
    _by_idempotency: dict[str, str] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    # -- session -----------------------------------------------------------
    def _check_auth(self, token: str | None) -> None:
        if self.mode == UNAUTHORIZED or not token:
            raise HRApiError("INTEGRATION_UNAUTHORIZED", 401,
                             "missing or invalid service credential")
        if token != SIMULATOR_TOKEN:
            raise HRApiError("INTEGRATION_UNAUTHORIZED", 401,
                             "missing or invalid service credential")
        if self.mode == FORBIDDEN:
            raise HRApiError("INTEGRATION_FORBIDDEN", 403,
                             "credential lacks permission for this route")

    def _maybe_fail(self, stage: str) -> None:
        """Raise the configured failure. Only `confirm` can leave an unknown outcome."""
        m = self.mode
        if m in (SUCCESS, UNAUTHORIZED, FORBIDDEN):
            return
        if stage != self.fail_stage:
            # This operation is not the one configured to fail. Navigation and note
            # writes stay healthy so the human checkpoint is still reached.
            return
        unknown = stage == "confirm" and self.applied_despite_failure
        if m == NOT_FOUND:
            raise HRApiError("TARGET_NOT_FOUND", 404, "route or record not found")
        if m == CONFLICT:
            raise HRApiError("INTEGRATION_CONFLICT", 409,
                             "record was modified by another actor")
        if m == RATE_LIMITED:
            raise HRApiError("RATE_LIMITED", 429, "too many requests")
        if m == SERVER_ERROR:
            raise HRApiError("INTEGRATION_SERVER_ERROR", 500, "upstream service error",
                             submitted_unknown=unknown)
        if m == TIMEOUT:
            raise HRApiError("INTEGRATION_TIMEOUT", 504, "upstream timed out",
                             submitted_unknown=unknown)
        if m == NETWORK_ERROR:
            raise HRApiError("INTEGRATION_UNAVAILABLE", 503, "connection reset",
                             submitted_unknown=unknown)

    # -- operations --------------------------------------------------------
    def open_route(self, token: str | None, route: str) -> dict:
        self.calls.append(f"open_route:{route}")
        self._check_auth(token)
        self._maybe_fail("open")
        if route not in KNOWN_ROUTE_PREFIXES:
            # The simulated service also does not know this route. This is NOT the
            # allowlist -- policy above still refuses first; this is the remote saying
            # the resource does not exist.
            raise HRApiError("TARGET_NOT_FOUND", 404, f"unknown route {route!r}")
        prefix = KNOWN_ROUTE_PREFIXES[route]
        self._records.setdefault(route, _Record(route=route, note_length=0))
        return {"route": route, "note_field_id": f"{prefix}-note",
                "confirm_button_id": f"btn-{prefix}-ok"}

    def set_note(self, token: str | None, route: str, note_text: str) -> dict:
        self.calls.append(f"set_note:{route}")
        self._check_auth(token)
        self._maybe_fail("set_note")
        rec = self._records.get(route)
        if rec is None:
            raise HRApiError("TARGET_NOT_FOUND", 404, "route not opened")
        rec.note_length = len(note_text)   # length only; content is never stored
        return {"route": route, "note_length": rec.note_length}

    def confirm(self, token: str | None, route: str, idempotency_key: str) -> dict:
        """Submit. Idempotent by key: the same key returns the first result."""
        self.calls.append(f"confirm:{route}")
        self._check_auth(token)

        prior = self._by_idempotency.get(idempotency_key)
        if prior is not None:
            # A safe repeat of the same request -- return the original outcome rather
            # than applying the change twice.
            return {"route": prior, "confirmed": True, "idempotent_replay": True}

        if self.mode == DUPLICATE_REQUEST:
            raise HRApiError("DUPLICATE_REQUEST", 409,
                             "a different request already confirmed this record")

        rec = self._records.get(route)
        if rec is None:
            raise HRApiError("TARGET_NOT_FOUND", 404, "route not opened")

        if self.applied_despite_failure and self.mode not in (SUCCESS, UNAUTHORIZED, FORBIDDEN):
            # THE CASE THAT MATTERS: the service applies the change and *then* the
            # response is lost. Commit first, then raise -- so the caller cannot tell
            # whether it happened, which is exactly what status lookup exists to fix.
            rec.confirmed = True
            rec.idempotency_key = idempotency_key
            self._by_idempotency[idempotency_key] = route

        self._maybe_fail("confirm")

        rec.confirmed = True
        rec.idempotency_key = idempotency_key
        self._by_idempotency[idempotency_key] = route
        return {"route": route, "confirmed": True, "idempotent_replay": False}

    def get_status(self, token: str | None, idempotency_key: str) -> dict:
        """Authoritative outcome for a key — how a lost response gets resolved.

        Deliberately never fails under the configured failure mode: a status endpoint
        that fails in the same way as the operation it reports on would be useless for
        exactly the case it exists to serve.
        """
        self.calls.append("get_status")
        self._check_auth(token)
        route = self._by_idempotency.get(idempotency_key)
        if route is None:
            return {"found": False, "confirmed": False}
        return {"found": True, "confirmed": True, "route": route}

    def commit_silently(self, route: str, idempotency_key: str) -> None:
        """Model 'the service applied the change but the caller never heard'.

        Used by the failure demo to set up the lost-response case; never called by the
        adapter itself.
        """
        rec = self._records.setdefault(route, _Record(route=route, note_length=0))
        rec.confirmed = True
        rec.idempotency_key = idempotency_key
        self._by_idempotency[idempotency_key] = route
