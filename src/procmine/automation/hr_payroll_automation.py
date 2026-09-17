"""RPA/UI automation layer for the HR/Payroll dominant workflow
(Step 3 prototype).

Automates ONLY the well-evidenced dominant path from
`reports/day3/hr_payroll_dominant_path_analysis.md`: navigate to one of
the four confirmed routes, locate its note field, insert a supplied
note, locate its confirm button, and STOP for mandatory human review --
the final confirm click is a separate, deliberate call
(`confirm_submission`), never automatic. This mirrors the analysis's
own finding that no event type in the observed schema is explicitly
labeled "submit"; treating the OK-button click as a DOM-structure
inference rather than a certainty is exactly why this layer never
performs it without an explicit second call.

Every failure mode below corresponds to a condition the forensic
analysis said must not be guessed through: an unevidenced route, an
empty/invalid note, navigation failure, a note field or confirm button
that is missing/duplicated/differently-shaped, or the confirm button no
longer matching what was reviewed by the time confirmation is actually
requested (the DOM is re-checked immediately before the click, never
clicked from a stale reference). Each raises immediately with the
partial action log attached, rather than falling back to a coordinate
click, a screenshot-based guess, or any other non-deterministic
recovery.

Depends on the `HRApplication` protocol (`procmine.integrations.hr_application`),
not on any concrete target. Satisfied by MockHRApplication, BrowserHRApplication,
ApiHRApplication and HTTPHRApplication; this module needs no change to gain a new
target.
Originally written against `procmine.automation.mock_hr_app.MockHRApplication`
(injected as a parameter, never hard-coded) purely by element `id` --
no pixel coordinates, no computer vision, matching the analysis's own
"selectors are sufficient" finding. A production version would swap
this same call sequence to a real browser driver (Selenium/Playwright)
using the identical `id`-based selectors already validated here -- see
`reports/day3/hr_payroll_automation_prototype.md` section 16.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field

from procmine.automation.mock_hr_app import MockHRApplication  # noqa: F401  (re-exported for callers)
from procmine.integrations.hr_application import HRApplication
from procmine.process_discovery.dom_evidence import KNOWN_ROUTE_PREFIXES


@dataclass
class ActionLogEntry:
    step: str
    detail: str
    timestamp: str


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class AutomationSafetyError(Exception):
    """Base class for every safe-failure condition. Carries the
    partial `action_log` so a caller can see exactly how far the
    pipeline got before stopping -- 'record what actions were
    performed' applies to failed runs too, not only successful ones."""

    def __init__(self, message: str, action_log: list[ActionLogEntry]):
        super().__init__(message)
        self.action_log = action_log


class UnknownRouteError(AutomationSafetyError):
    pass


class NavigationError(AutomationSafetyError):
    pass


class ElementNotFoundError(AutomationSafetyError):
    pass


class DuplicateElementError(AutomationSafetyError):
    pass


class InvalidNoteError(AutomationSafetyError):
    pass


class ConfirmationFailedError(AutomationSafetyError):
    pass


class NoteInsertionError(AutomationSafetyError):
    """The verified note field could not be written -- the target refused or failed."""


@dataclass
class ReviewCheckpoint:
    """Returned once navigation, note insertion, and confirm-button
    verification have all succeeded -- and BEFORE the confirm button
    has ever been clicked. This is the mandatory human-review boundary
    (Step 3, section 5): only `confirm_submission`, passed this exact
    object, can proceed past it, and only once."""

    route: str
    note_field_id: str
    note_text: str
    confirm_button_id: str
    action_log: list[ActionLogEntry] = field(default_factory=list)
    confirmed: bool = False


@dataclass
class AutomationResult:
    route: str
    confirmed: bool
    action_log: list[ActionLogEntry]


def _log(entries: list[ActionLogEntry], step: str, detail: str) -> None:
    entries.append(ActionLogEntry(step=step, detail=detail, timestamp=_now()))


def prepare_note_submission(app: HRApplication, route: str, note_text: str) -> ReviewCheckpoint:
    """Steps 1-5 of Step 3's automation boundary: accept the route,
    navigate, verify the note field, insert the note, verify the
    confirm button. Never clicks the confirm button. Raises a specific
    `AutomationSafetyError` subclass and stops immediately at the first
    condition that doesn't match what was evidenced -- it does not
    retry, guess, or fall back to a different selector."""
    log: list[ActionLogEntry] = []

    if route not in KNOWN_ROUTE_PREFIXES:
        _log(log, "route_check", f"REJECTED: {route!r} is not one of the four evidenced routes")
        raise UnknownRouteError(f"unknown or unevidenced route: {route!r}", log)
    _log(log, "route_check", f"{route!r} is an evidenced route")

    if note_text is None or not note_text.strip():
        _log(log, "note_check", f"REJECTED: note text is empty or whitespace-only ({note_text!r})")
        raise InvalidNoteError(f"note text must be non-empty, got {note_text!r}", log)
    _log(log, "note_check", "note text is non-empty")

    try:
        app.navigate(route)
    except Exception as exc:
        _log(log, "navigate", f"FAILED: {exc}")
        raise NavigationError(f"navigation to {route!r} failed: {exc}", log) from exc
    _log(log, "navigate", f"navigated to {route!r}")

    expected_prefix = KNOWN_ROUTE_PREFIXES[route]
    expected_note_id = f"{expected_prefix}-note"
    # Every adapter call can fail on a real target (a driver timeout, an HTTP error).
    # Each failure is a safe stop carrying the partial log, never a raw exception.
    try:
        note_fields = app.find_note_field()
    except Exception as exc:
        _log(log, "find_note_field", f"FAILED: could not read the target: {exc}")
        raise ElementNotFoundError(f"could not read the note field for {route!r}: {exc}", log) from exc
    if len(note_fields) == 0:
        _log(log, "find_note_field", "FAILED: no note field found")
        raise ElementNotFoundError(f"no note field found for {route!r}", log)
    if len(note_fields) > 1:
        _log(log, "find_note_field", f"FAILED: {len(note_fields)} matching note fields found, ambiguous")
        raise DuplicateElementError(f"{len(note_fields)} note fields found for {route!r}", log)
    note_field = note_fields[0]
    if note_field.element_id != expected_note_id:
        _log(log, "find_note_field", f"FAILED: found {note_field.element_id!r}, expected {expected_note_id!r}")
        raise ElementNotFoundError(
            f"note field id {note_field.element_id!r} does not match the evidenced pattern {expected_note_id!r}", log
        )
    _log(log, "find_note_field", f"found {note_field.element_id!r}")

    try:
        app.set_note_value(note_field.element_id, note_text)
    except Exception as exc:
        _log(log, "insert_note", f"FAILED: could not write {note_field.element_id!r}: {exc}")
        raise NoteInsertionError(f"could not insert the note into {note_field.element_id!r}: {exc}", log) from exc
    _log(log, "insert_note", f"inserted note into {note_field.element_id!r}")

    expected_confirm_id = f"btn-{expected_prefix}-ok"
    try:
        confirm_buttons = app.find_confirm_button()
    except Exception as exc:
        _log(log, "find_confirm_button", f"FAILED: could not read the target: {exc}")
        raise ElementNotFoundError(f"could not read the confirm button for {route!r}: {exc}", log) from exc
    if len(confirm_buttons) == 0:
        _log(log, "find_confirm_button", "FAILED: no confirm button found")
        raise ElementNotFoundError(f"no confirm button found for {route!r}", log)
    if len(confirm_buttons) > 1:
        _log(log, "find_confirm_button", f"FAILED: {len(confirm_buttons)} matching confirm buttons found, ambiguous")
        raise DuplicateElementError(f"{len(confirm_buttons)} confirm buttons found for {route!r}", log)
    confirm_button = confirm_buttons[0]
    if confirm_button.element_id != expected_confirm_id:
        _log(log, "find_confirm_button", f"FAILED: found {confirm_button.element_id!r}, expected {expected_confirm_id!r}")
        raise ElementNotFoundError(
            f"confirm button id {confirm_button.element_id!r} does not match the evidenced pattern {expected_confirm_id!r}",
            log,
        )
    _log(log, "find_confirm_button", f"found {confirm_button.element_id!r}")

    _log(log, "checkpoint", "prepared -- awaiting human review before the confirmation click")
    return ReviewCheckpoint(
        route=route, note_field_id=note_field.element_id, note_text=note_text,
        confirm_button_id=confirm_button.element_id, action_log=log,
    )


def confirm_submission(app: HRApplication, checkpoint: ReviewCheckpoint) -> AutomationResult:
    """The deliberate, separate step representing human approval. Only
    callable once per checkpoint, and only while the application is
    still on the route the checkpoint was prepared for. Before
    clicking, the confirm button is RE-LOCATED rather than clicked from
    a cached reference -- the DOM may have changed during the human
    review pause (the button could have disappeared, moved, or
    duplicated), and this treats that "unexpected page state" the same
    way `prepare_note_submission` treats it the first time: stop and
    report, never click a different element than the one reviewed."""
    if checkpoint.confirmed:
        raise RuntimeError("this checkpoint has already been confirmed -- confirm_submission is not re-entrant")
    if app.current_route != checkpoint.route:
        raise RuntimeError(
            f"application is on {app.current_route!r}, not the reviewed route {checkpoint.route!r} -- "
            "re-run prepare_note_submission before confirming"
        )

    try:
        confirm_buttons = app.find_confirm_button()
    except Exception as exc:
        _log(checkpoint.action_log, "confirm", f"FAILED: could not re-locate confirm button: {exc}")
        raise ConfirmationFailedError(f"could not re-locate confirm button on {checkpoint.route!r}: {exc}", checkpoint.action_log) from exc
    matching = [b for b in confirm_buttons if b.element_id == checkpoint.confirm_button_id]
    if len(confirm_buttons) != 1 or len(matching) != 1:
        found_ids = [b.element_id for b in confirm_buttons]
        _log(checkpoint.action_log, "confirm",
             f"FAILED: page state changed since review -- expected exactly one {checkpoint.confirm_button_id!r}, found {found_ids}")
        raise ConfirmationFailedError(
            f"unexpected page state at confirmation time: expected {checkpoint.confirm_button_id!r}, found {found_ids}",
            checkpoint.action_log,
        )

    try:
        app.click(checkpoint.confirm_button_id)
    except Exception as exc:
        _log(checkpoint.action_log, "confirm", f"FAILED: click on {checkpoint.confirm_button_id!r} raised: {exc}")
        raise ConfirmationFailedError(f"click on {checkpoint.confirm_button_id!r} failed: {exc}", checkpoint.action_log) from exc

    checkpoint.confirmed = True
    _log(checkpoint.action_log, "confirm", f"human-approved: clicked {checkpoint.confirm_button_id!r}")
    return AutomationResult(route=checkpoint.route, confirmed=True, action_log=checkpoint.action_log)
