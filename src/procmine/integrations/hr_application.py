"""The integration interface the automation service depends on.

WHY THIS EXISTS
---------------
`prepare_note_submission` and `confirm_submission` were annotated with the concrete
`MockHRApplication`. They already worked against the browser adapter by duck typing,
but the *declared* dependency pointed at a concrete implementation, so nothing stopped
mock-specific behaviour leaking into the service.

This protocol makes the dependency explicit and inverts it: the automation service
depends on an abstraction, and the adapters depend on that same abstraction. Adding a
third target (the REST API adapter) then requires **no change to the automation
service at all** -- which is the property the architecture is claiming, so it is worth
making structural rather than incidental.

WHAT AN ADAPTER MAY AND MAY NOT DO
----------------------------------
An adapter drives a target. It may translate calls, locate elements, and raise on
transport failure. It must **not** decide whether a route is allowed, whether a note
is valid, or whether a confirmation may proceed -- those are policy, they live above
this line, and a test asserts each adapter has not grown a copy.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class HRElement(Protocol):
    """The shape every adapter returns for a located element."""

    element_id: str
    element_type: str
    css_class: str


@runtime_checkable
class HRApplication(Protocol):
    """A target the automation service can drive.

    Deliberately small. Every method maps to one observable step in the Dataset-B
    dominant path: navigate to a route, find the note field, set it, find the confirm
    button, click it. Nothing in this interface is browser-specific or HTTP-specific.
    """

    @property
    def current_route(self) -> str | None:
        """The route the target is currently on, or None before any navigation."""

    def navigate(self, route: str) -> None:
        """Go to `route`. Raises on transport or navigation failure."""

    def find_note_field(self) -> list:
        """Every note field visible on the current route.

        Returns a list rather than one element so the caller can refuse when the
        count is not exactly one. Ambiguity is the service's decision to reject, not
        the adapter's to resolve.
        """

    def find_confirm_button(self) -> list:
        """Every confirm button visible on the current route. Same contract as above."""

    def set_note_value(self, element_id: str, value: str) -> None:
        """Write `value` into the identified field."""

    def click(self, element_id: str) -> None:
        """Click the identified element."""


# Integration modes, as surfaced to the API and the UI. Every one of these is local.
MODE_MOCK = "mock"
MODE_BROWSER = "browser"
MODE_API = "api_simulator"
MODE_HTTP = "http"

INTEGRATION_MODES = {
    MODE_MOCK: "LOCAL MOCK — deterministic in-memory target",
    MODE_BROWSER: "LOCAL BROWSER — Playwright against the local HR prototype page",
    MODE_API: "LOCAL API SIMULATOR — simulated external REST service, in-process",
    # Real HTTP over a socket to a separate local server with SQLite state. Still a
    # simulator of an HR system: nothing here is a real or production HR target.
    MODE_HTTP: "LOCAL HTTP INTEGRATION — real HTTP to the local HR API server (SQLite)",
}
