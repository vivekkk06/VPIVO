"""REST-style adapter satisfying `HRApplication`, backed by the local simulator.

THE POINT OF THIS ADAPTER
-------------------------
It proves the interface actually inverts the dependency. The automation service is
unchanged; the target is now an HTTP-shaped service rather than a DOM, and the same
`prepare_note_submission` / `confirm_submission` drive it.

Like the browser adapter, this holds **no** policy: no route allowlist, no note
validation, no confirmation rule. It translates interface calls into service calls and
translates service failures into the project's error taxonomy. A test asserts it has
not grown a copy of the safety logic.

**Not connected to any real HR system.** The transport is an in-process simulator.
A production adapter would swap `HRApiSimulator` for a real HTTP client against a real
contract, and nothing above this file would change -- which is the claim being made.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from procmine.integrations.hr_api_simulator import HRApiError, HRApiSimulator, SIMULATOR_TOKEN


@dataclass
class ApiElement:
    """Mirrors the mock/browser element shape so callers cannot tell adapters apart."""

    element_id: str
    element_type: str
    css_class: str
    value: str | None = None
    clicked: bool = False


class ApiHRApplication:
    """Drives the simulated HR service through the `HRApplication` interface.

    `idempotency_key` is supplied by the caller (the orchestrator derives it from the
    execution id) so a retry of the *same* business action is recognisable as such by
    the service. The adapter never invents one per call, which would defeat the point.
    """

    def __init__(self, simulator: HRApiSimulator | None = None, *,
                 token: str | None = SIMULATOR_TOKEN, idempotency_key: str | None = None):
        self._api = simulator if simulator is not None else HRApiSimulator()
        self._token = token
        self.idempotency_key = idempotency_key or f"idem_{uuid.uuid4().hex[:16]}"
        self._current_route: str | None = None
        self._fields: dict[str, str] = {}
        self._confirm_id: str | None = None
        self.last_error: HRApiError | None = None

    # -- HRApplication -----------------------------------------------------
    @property
    def current_route(self) -> str | None:
        return self._current_route

    def navigate(self, route: str) -> None:
        try:
            r = self._api.open_route(self._token, route)
        except HRApiError as exc:
            self.last_error = exc
            # Surface as a plain error; the automation layer above owns the taxonomy
            # decision, exactly as it does for the browser adapter.
            raise RuntimeError(f"integration navigate failed [{exc.code}]: {exc}") from exc
        self._current_route = route
        self._fields = {r["note_field_id"]: ""}
        self._confirm_id = r["confirm_button_id"]

    def find_note_field(self) -> list[ApiElement]:
        if self._current_route is None:
            return []
        return [ApiElement(element_id=fid, element_type="textarea", css_class="input",
                           value=val) for fid, val in self._fields.items()]

    def find_confirm_button(self) -> list[ApiElement]:
        if self._current_route is None or self._confirm_id is None:
            return []
        return [ApiElement(element_id=self._confirm_id, element_type="button",
                           css_class="btn success")]

    def set_note_value(self, element_id: str, value: str) -> None:
        try:
            self._api.set_note(self._token, self._current_route or "", value)
        except HRApiError as exc:
            self.last_error = exc
            raise RuntimeError(f"integration set_note failed [{exc.code}]: {exc}") from exc
        self._fields[element_id] = value

    def click(self, element_id: str) -> None:
        """Clicking the confirm button is the mutation, so it carries the key."""
        if element_id != self._confirm_id:
            raise RuntimeError(f"unknown element {element_id!r}")
        try:
            self._api.confirm(self._token, self._current_route or "", self.idempotency_key)
        except HRApiError as exc:
            self.last_error = exc
            raise RuntimeError(f"integration confirm failed [{exc.code}]: {exc}") from exc

    # -- integration-specific, outside the interface -----------------------
    def query_remote_status(self) -> dict:
        """Ask the service what actually happened for this idempotency key.

        This is how a lost confirmation response is resolved, and it is deliberately
        NOT part of `HRApplication`: the mock and browser targets have no equivalent,
        and putting it in the interface would force them to fake one.
        """
        return self._api.get_status(self._token, self.idempotency_key)

    @property
    def outcome_is_unknown(self) -> bool:
        """True when the service may have applied the change but did not say so."""
        return bool(self.last_error and self.last_error.submitted_unknown)
