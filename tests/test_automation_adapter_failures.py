"""An adapter that fails during prepare is a safe stop -- for every target.

Before the local HTTP integration, `prepare_note_submission` guarded only `navigate`.
A target that failed while its note field was being read or written, or while its
confirm button was being read, escaped the service as a raw exception: no safe stop, no
execution record, no audit event, and through the API a dropped request. A real HTTP
target makes that failure ordinary, so the service now converts it like every other
refusal, with the partial action log attached.

The happy path is unchanged; the first test pins it.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from procmine.automation.audit import ERROR_TYPES, error_type_for
from procmine.automation.hr_payroll_automation import (
    AutomationSafetyError, ElementNotFoundError, NoteInsertionError, confirm_submission,
    prepare_note_submission,
)
from procmine.automation.mock_hr_app import MockHRApplication
from procmine.integrations import execution_state as st
from procmine.integrations.auth import ROLE_REVIEWER, Actor
from procmine.integrations.orchestrator import Orchestrator

ROUTE = "#/payroll-items"
NOTE = "Reviewed per standard process."
REVIEWER = Actor("u_reviewer", ROLE_REVIEWER)


class FailingTarget(MockHRApplication):
    """The mock, with one adapter call failing the way a driver or a network can."""

    def __init__(self, fail_on: str):
        super().__init__()
        self.fail_on = fail_on

    def _maybe_fail(self, name: str) -> None:
        if self.fail_on == name:
            raise RuntimeError(f"target failure during {name}")

    def find_note_field(self):
        self._maybe_fail("find_note_field")
        return super().find_note_field()

    def set_note_value(self, element_id, value):
        self._maybe_fail("set_note_value")
        super().set_note_value(element_id, value)

    def find_confirm_button(self):
        self._maybe_fail("find_confirm_button")
        return super().find_confirm_button()


CASES = [
    ("find_note_field", ElementNotFoundError, "find_note_field", "TARGET_NOT_FOUND"),
    ("set_note_value", NoteInsertionError, "insert_note", "TARGET_CHANGED"),
    ("find_confirm_button", ElementNotFoundError, "find_confirm_button", "TARGET_NOT_FOUND"),
]


def test_the_happy_path_log_is_unchanged():
    app = MockHRApplication()
    checkpoint = prepare_note_submission(app, ROUTE, NOTE)
    assert [e.step for e in checkpoint.action_log] == [
        "route_check", "note_check", "navigate", "find_note_field", "insert_note",
        "find_confirm_button", "checkpoint"]
    assert confirm_submission(app, checkpoint).confirmed is True


@pytest.mark.parametrize("fail_on,exc_type,step,_code", CASES)
def test_an_adapter_failure_during_prepare_is_a_safe_stop(fail_on, exc_type, step, _code):
    app = FailingTarget(fail_on)
    with pytest.raises(exc_type) as exc:
        prepare_note_submission(app, ROUTE, NOTE)
    assert isinstance(exc.value, AutomationSafetyError)
    last = exc.value.action_log[-1]
    assert last.step == step
    assert last.detail.startswith("FAILED")
    assert "checkpoint" not in [e.step for e in exc.value.action_log]
    assert not any(el.clicked for el in MockHRApplication.find_confirm_button(app))


@pytest.mark.parametrize("fail_on,exc_type,_step,code", CASES)
def test_the_orchestrator_records_a_failed_execution(fail_on, exc_type, _step, code):
    orch = Orchestrator()
    with pytest.raises(exc_type) as exc:
        orch.prepare(REVIEWER, FailingTarget(fail_on), ROUTE, NOTE)
    record = orch.repo.get(exc.value.execution_id)
    assert (record.status, record.error_code) == (st.FAILED, code)
    stops = [e for e in orch.audit.recent(10) if e["result"] == "safe_stop"]
    assert stops and stops[-1]["error_type"] == code


def test_note_insertion_maps_into_the_taxonomy():
    assert error_type_for(NoteInsertionError("x", [])) == "TARGET_CHANGED"
    assert "TARGET_CHANGED" in ERROR_TYPES


def test_the_api_answers_422_instead_of_dropping_the_request(monkeypatch):
    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("serve_hr_demo_api_failures",
                                                  root / "scripts" / "serve_hr_demo_api.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["serve_hr_demo_api_failures"] = module
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_build_adapter",
                        lambda *_a, **_k: FailingTarget("set_note_value"))
    server = module.build_server("127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{server.server_address[1]}/api/prepare", method="POST",
            data=json.dumps({"route": ROUTE, "note_text": NOTE}).encode(),
            headers={"Content-Type": "application/json"})
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=10)
        payload = json.loads(exc.value.read())
    finally:
        server.shutdown()
        server.server_close()
    assert exc.value.code == 422
    assert payload["error_type"] == "TARGET_CHANGED"
    assert payload["status"] == "FAILED"
    assert payload["action_log"][-1]["step"] == "insert_note"
    assert "Traceback" not in json.dumps(payload)
