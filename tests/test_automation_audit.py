"""Tests for the automation audit trail.

The security-relevant property is negative: certain things must **never** appear in
the log. Negative properties do not fail loudly on their own, so they are tested
explicitly rather than left to code review.
"""
from __future__ import annotations

import json

from procmine.automation.audit import (
    ERROR_TYPES, AuditEvent, AuditLog, error_type_for, new_execution_id,
    new_request_id, redact,
)


# --------------------------------------------------------------------------
# redaction -- the part most easily got wrong
# --------------------------------------------------------------------------
def test_note_content_is_never_logged_but_its_length_is():
    note = "Payroll verified against source record."
    out = redact({"note_text": note, "route": "#/x"})
    assert "note_text" not in out
    assert out["note_text_length"] == len(note)
    assert note not in str(out)
    assert out["route"] == "#/x"


def test_credentials_are_dropped_entirely():
    out = redact({"password": "hunter2", "api_key": "k", "authorization": "Bearer x"})
    assert "hunter2" not in json.dumps(out)
    assert "Bearer x" not in json.dumps(out)
    assert out == {"password_redacted": True, "api_key_redacted": True,
                   "authorization_redacted": True}


def test_secret_looking_keys_fail_closed():
    """An unknown key that merely looks secret-ish is dropped, not kept."""
    out = redact({"customer_access_token": "abc", "refresh_secret": "def"})
    assert "abc" not in json.dumps(out)
    assert "def" not in json.dumps(out)


def test_ordinary_fields_survive():
    out = redact({"route": "#/payroll-items", "attempt": 2, "confirmed": True})
    assert out == {"route": "#/payroll-items", "attempt": 2, "confirmed": True}


def test_serialised_event_never_contains_note_text():
    ev = AuditEvent(request_id="r", execution_id="e", action="prepare",
                    result="success", route="#/payroll-items",
                    detail={"note_text": "SENSITIVE BUSINESS TEXT"})
    blob = ev.to_json()
    assert "SENSITIVE BUSINESS TEXT" not in blob
    assert "note_text_length" in blob


# --------------------------------------------------------------------------
# the log itself
# --------------------------------------------------------------------------
def test_events_are_recorded_and_readable_back():
    log = AuditLog()
    log.record(AuditEvent(request_id="r1", execution_id="e1", action="prepare",
                          result="success", route="#/onboarding"))
    recent = log.recent()
    assert len(recent) == 1
    assert recent[0]["request_id"] == "r1"
    assert recent[0]["result"] == "success"


def test_log_persists_as_jsonl_when_given_a_path(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path=path)
    log.record(AuditEvent(request_id="r", execution_id="e", action="confirm",
                          result="success", detail={"note_text": "secret note"}))
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert "secret note" not in lines[0]
    assert json.loads(lines[0])["action"] == "confirm"


def test_in_memory_log_is_bounded():
    log = AuditLog(keep_in_memory=5)
    for i in range(20):
        log.record(AuditEvent(request_id=f"r{i}", execution_id=None,
                              action="prepare", result="success"))
    assert len(log.events) == 5
    assert log.events[-1].request_id == "r19"


# --------------------------------------------------------------------------
# ids and the error taxonomy
# --------------------------------------------------------------------------
def test_ids_are_unique_and_prefixed():
    assert new_request_id().startswith("req_")
    assert new_execution_id().startswith("exec_")
    assert len({new_request_id() for _ in range(200)}) == 200


def test_every_mapped_error_type_is_in_the_taxonomy():
    from procmine.automation.audit import EXCEPTION_TO_ERROR_TYPE

    for value in EXCEPTION_TO_ERROR_TYPE.values():
        assert value in ERROR_TYPES


def test_error_type_for_known_exceptions():
    from procmine.automation.hr_payroll_automation import (
        InvalidNoteError, UnknownRouteError,
    )

    assert error_type_for(UnknownRouteError("x", [])) == "INVALID_ROUTE"
    assert error_type_for(InvalidNoteError("x", [])) == "INVALID_NOTE"


def test_unmapped_exception_still_gets_an_auditable_type():
    """An unknown failure must never crash the audit path."""
    assert error_type_for(ValueError("boom")) in ERROR_TYPES
