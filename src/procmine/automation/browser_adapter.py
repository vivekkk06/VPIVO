"""Playwright-backed adapter that drives a real browser DOM.

WHY THIS EXISTS, AND WHY IT IS SHAPED THIS WAY
----------------------------------------------
The Day-3 prototype report stated a productionization claim: implement the same
five-method interface against a real browser driver, and `hr_payroll_automation.py`
itself needs no change. That was an architectural assertion with nothing behind it.

This module tests it. `BrowserHRApplication` implements exactly the interface
`MockHRApplication` exposes — `navigate`, `find_note_field`, `find_confirm_button`,
`set_note_value`, `click`, and a `current_route` property — so
`prepare_note_submission` and `confirm_submission` operate on it **unmodified**.

The safety boundary therefore lives where it always did: in the automation logic
above this adapter, not in the adapter. This class deliberately has **no** route
allowlist, no note validation and no confirmation policy of its own. It is a driver,
not a decision-maker. Anything that bypassed the automation layer to click directly
would be bypassing every safety control, which is why nothing here is public beyond
the five interface methods.

The target is the local `hr_payroll_mock_app.html` prototype. **This is not connected
to any real HR system.**

Requires the `playwright` extra (see README); the import is deferred so the rest of
the package works without it installed.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from procmine.process_discovery.dom_evidence import KNOWN_ROUTE_PREFIXES, url_route

DEFAULT_TIMEOUT_MS = int(os.environ.get("AUTOMATION_TIMEOUT_MS", "5000"))
DEFAULT_HEADLESS = os.environ.get("BROWSER_HEADLESS", "1") not in {"0", "false", "False"}


@dataclass
class BrowserElement:
    """Mirrors `mock_hr_app.MockElement` so callers cannot tell the two apart."""

    element_id: str
    element_type: str
    css_class: str
    value: str | None = None
    clicked: bool = False


class BrowserNavigationError(RuntimeError):
    """Raised when the browser could not reach the requested route.

    Deliberately a plain error: the automation layer above converts driver failures
    into its own `AutomationSafetyError` taxonomy, so the safe-stop behaviour is
    decided in one place rather than two.
    """


class BrowserHRApplication:
    """Drives the local HR prototype through a real Chromium DOM.

    Use as a context manager so the browser is always closed, including on a
    safe-stop path:

        with BrowserHRApplication(base_url) as app:
            checkpoint = prepare_note_submission(app, route, note)
            ...
    """

    def __init__(
        self,
        base_url: str | None = None,
        *,
        headless: bool | None = None,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ):
        self.base_url = base_url or os.environ.get("HR_BASE_URL") or _default_file_url()
        self.headless = DEFAULT_HEADLESS if headless is None else headless
        self.timeout_ms = timeout_ms
        self._current_route: str | None = None
        self._pw = None
        self._browser = None
        self._page = None

    # -- lifecycle ---------------------------------------------------------
    def __enter__(self) -> "BrowserHRApplication":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def start(self) -> None:
        from playwright.sync_api import sync_playwright  # deferred import

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        self._page = self._browser.new_page()
        self._page.set_default_timeout(self.timeout_ms)

    def close(self) -> None:
        for obj, meth in ((self._browser, "close"), (self._pw, "stop")):
            if obj is not None:
                try:
                    getattr(obj, meth)()
                except Exception:  # noqa: BLE001 - teardown must never mask a real error
                    pass
        self._browser = self._pw = self._page = None

    # -- the five-method interface ----------------------------------------
    @property
    def current_route(self) -> str | None:
        return self._current_route

    def navigate(self, route: str) -> None:
        """Go to `route` and verify the page actually got there.

        Navigation is a non-mutating operation, so verifying it is safe and cheap.
        A URL that does not end up on the requested route raises rather than letting
        the automation continue against the wrong page.
        """
        self._require_started()
        self._page.goto(f"{self.base_url}{route}", wait_until="load")
        # The prototype is a hash-router; give it a beat to swap panels.
        self._page.wait_for_timeout(50)
        landed = url_route(self._page.url)
        if landed != route:
            raise BrowserNavigationError(
                f"navigated to {self._page.url!r}, which resolves to route {landed!r}, "
                f"not {route!r}"
            )
        prefix = KNOWN_ROUTE_PREFIXES.get(route)
        if prefix and not self._page.locator(f"#panel-{prefix}").is_visible():
            raise BrowserNavigationError(
                f"route {route!r} loaded but its panel #panel-{prefix} is not visible"
            )
        self._current_route = route

    def find_note_field(self) -> list[BrowserElement]:
        """Every visible note field on the current route.

        Returns a list, not a single element, precisely so the automation layer can
        refuse when the count is not exactly one. Ambiguity is the caller's decision
        to reject, not this adapter's to resolve.
        """
        return self._find("textarea", "input")

    def find_confirm_button(self) -> list[BrowserElement]:
        return self._find("button", "btn success")

    def set_note_value(self, element_id: str, value: str) -> None:
        self._require_started()
        self._page.locator(f"#{element_id}").fill(value)

    def click(self, element_id: str) -> None:
        self._require_started()
        self._page.locator(f"#{element_id}").click()

    # -- internals ---------------------------------------------------------
    def _find(self, tag: str, css_class: str) -> list[BrowserElement]:
        self._require_started()
        prefix = KNOWN_ROUTE_PREFIXES.get(self._current_route or "")
        if not prefix:
            return []
        # Scope to the active panel so hidden panels of other routes cannot be
        # matched -- a whole-page query would find four note fields, not one.
        loc = self._page.locator(f"#panel-{prefix} {tag}")
        out: list[BrowserElement] = []
        for i in range(loc.count()):
            el = loc.nth(i)
            if not el.is_visible():
                continue
            out.append(
                BrowserElement(
                    element_id=el.get_attribute("id") or "",
                    element_type=tag,
                    css_class=el.get_attribute("class") or css_class,
                    value=el.input_value() if tag == "textarea" else None,
                )
            )
        return out

    def _require_started(self) -> None:
        if self._page is None:
            raise RuntimeError("browser not started -- use BrowserHRApplication as a context manager")


def _default_file_url() -> str:
    """The committed local prototype, as a file:// URL."""
    page = Path(__file__).resolve().parents[3] / "reports" / "day3" / "hr_payroll_mock_app.html"
    return f"file://{page}"
