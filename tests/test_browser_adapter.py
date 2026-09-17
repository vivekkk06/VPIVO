"""Real-browser tests for the automation, against the local HR prototype.

These run a live Chromium via Playwright. They are skipped (not failed) when
Playwright or its browser binary is unavailable, so the suite still passes on a
machine that has not run `playwright install chromium`.

The property under test is architectural: `hr_payroll_automation.py` is **unmodified**
and drives a real DOM purely because `BrowserHRApplication` implements the same
interface as `MockHRApplication`. Every safety control must therefore still hold when
the target is a real browser — that is the whole claim, so it is tested rather than
asserted in prose.

Fault cases (missing / duplicated elements, wrong page) are produced by writing
modified copies of the prototype page to a tmp dir. The committed page is never
touched.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

pytest.importorskip("playwright", reason="playwright not installed")

from procmine.automation.browser_adapter import (  # noqa: E402
    BrowserHRApplication, BrowserNavigationError,
)
from procmine.automation.hr_payroll_automation import (  # noqa: E402
    ConfirmationFailedError, DuplicateElementError, ElementNotFoundError,
    InvalidNoteError, UnknownRouteError, confirm_submission, prepare_note_submission,
)

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "reports" / "day3" / "hr_payroll_mock_app.html"
ROUTE = "#/payroll-items"
NOTE = "Verified against the source record."


def _browser_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            b = pw.chromium.launch(headless=True)
            b.close()
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(
    not _browser_available(), reason="chromium not installed (run: playwright install chromium)"
)


@pytest.fixture
def app():
    with BrowserHRApplication(headless=True) as a:
        yield a


def _variant(tmp_path: Path, transform) -> str:
    """Write a modified copy of the prototype page and return its file:// URL."""
    html = transform(PAGE.read_text(encoding="utf-8"))
    p = tmp_path / "variant.html"
    p.write_text(html, encoding="utf-8")
    return f"file://{p}"


# --------------------------------------------------------------------------
# happy path
# --------------------------------------------------------------------------
def test_valid_route_reaches_the_checkpoint_without_submitting(app):
    cp = prepare_note_submission(app, ROUTE, NOTE)
    assert cp.route == ROUTE
    assert cp.note_field_id == "pi-note"
    assert cp.confirm_button_id == "btn-pi-ok"
    assert cp.confirmed is False, "nothing may be submitted before human review"


def test_note_actually_reaches_the_live_dom(app):
    cp = prepare_note_submission(app, ROUTE, NOTE)
    assert app._page.locator(f"#{cp.note_field_id}").input_value() == NOTE


def test_successful_confirmation(app):
    cp = prepare_note_submission(app, ROUTE, NOTE)
    result = confirm_submission(app, cp)
    assert result.confirmed is True
    assert result.route == ROUTE


@pytest.mark.parametrize("route", ["#/payroll-items", "#/leave-applications",
                                   "#/onboarding", "#/social-insurance"])
def test_all_four_evidenced_routes_work(app, route):
    cp = prepare_note_submission(app, route, NOTE)
    assert confirm_submission(app, cp).confirmed is True


# --------------------------------------------------------------------------
# safe stops
# --------------------------------------------------------------------------
def test_invalid_route_is_refused_before_the_browser_is_touched(app):
    with pytest.raises(UnknownRouteError):
        prepare_note_submission(app, "#/unknown-route", NOTE)
    assert app.current_route is None, "browser must not have navigated"


@pytest.mark.parametrize("note", ["", "   ", "\n\t "])
def test_empty_note_is_refused_before_any_ui_contact(app, note):
    with pytest.raises(InvalidNoteError):
        prepare_note_submission(app, ROUTE, note)
    assert app.current_route is None


def test_navigation_to_the_wrong_page_is_detected(tmp_path):
    """A page whose router ignores the hash must not be accepted as the route."""
    url = _variant(tmp_path, lambda h: h.replace('panel.dataset.route !== route',
                                                 'panel.dataset.route !== "#/never"'))
    with BrowserHRApplication(base_url=url, headless=True) as a:
        with pytest.raises(BrowserNavigationError, match="not visible"):
            a.navigate(ROUTE)


def test_missing_note_field_refuses_rather_than_guessing(tmp_path):
    url = _variant(tmp_path, lambda h: h.replace('id="pi-note"', 'id="pi-note-removed"'))
    with BrowserHRApplication(base_url=url, headless=True) as a:
        with pytest.raises(ElementNotFoundError):
            prepare_note_submission(a, ROUTE, NOTE)


def test_duplicate_note_field_refuses_rather_than_guessing(tmp_path):
    def dupe(h: str) -> str:
        m = re.search(r'<textarea id="pi-note".*?</textarea>', h, re.S)
        return h.replace(m.group(0), m.group(0) + m.group(0).replace("pi-note", "pi-note-2"))

    url = _variant(tmp_path, dupe)
    with BrowserHRApplication(base_url=url, headless=True) as a:
        with pytest.raises(DuplicateElementError):
            prepare_note_submission(a, ROUTE, NOTE)


def test_missing_confirm_button_refuses_rather_than_guessing(tmp_path):
    url = _variant(tmp_path, lambda h: h.replace('id="btn-pi-ok"', 'id="btn-pi-gone"'))
    with BrowserHRApplication(base_url=url, headless=True) as a:
        with pytest.raises(ElementNotFoundError):
            prepare_note_submission(a, ROUTE, NOTE)


# --------------------------------------------------------------------------
# the two controls that matter most
# --------------------------------------------------------------------------
def test_confirm_time_reverification_catches_a_dom_change_during_review(app):
    """The confirm target is re-located after the human pause, never cached.

    This is the control that protects against the page changing while a person is
    reading the checkpoint, so it is tested by actually changing the page.
    """
    cp = prepare_note_submission(app, ROUTE, NOTE)
    app._page.evaluate("document.getElementById('btn-pi-ok').remove()")
    with pytest.raises(ConfirmationFailedError):
        confirm_submission(app, cp)


def test_a_checkpoint_cannot_be_confirmed_twice(app):
    cp = prepare_note_submission(app, ROUTE, NOTE)
    assert confirm_submission(app, cp).confirmed is True
    with pytest.raises(RuntimeError, match="already been confirmed"):
        confirm_submission(app, cp)


def test_confirming_on_a_different_route_than_reviewed_is_refused(app):
    """Navigating away after review must invalidate the checkpoint.

    Note the exception type: route drift raises a plain `RuntimeError`, not an
    `AutomationSafetyError` subclass like the other refusals. That asymmetry is in the
    existing prototype, and the test records it as-is rather than changing locked
    behaviour to suit a tidier taxonomy. Both refuse; only the type differs.
    """
    cp = prepare_note_submission(app, ROUTE, NOTE)
    app.navigate("#/onboarding")
    with pytest.raises(RuntimeError, match="not the reviewed route"):
        confirm_submission(app, cp)


# --------------------------------------------------------------------------
# architectural claim
# --------------------------------------------------------------------------
def test_adapter_holds_no_safety_logic_of_its_own():
    """Safety lives in the automation layer; the adapter is only a driver.

    If the adapter grew its own route allowlist or note validation there would be two
    places to keep correct, and a caller could pick the weaker one.
    """
    src = (ROOT / "src/procmine/automation/browser_adapter.py").read_text(encoding="utf-8")
    body = src.split('"""', 2)[-1]  # skip the module docstring
    for forbidden in ("KNOWN_ROUTE_PREFIXES[", "raise UnknownRouteError",
                      "raise InvalidNoteError", "def validate"):
        assert forbidden not in body, f"adapter contains safety logic: {forbidden!r}"
