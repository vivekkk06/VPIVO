"""Security properties of the integration layer (Day-5 integration upgrade).

These are all *negative* properties — "X never appears in Y". A negative property
does not fail loudly on its own: if redaction silently stopped working, every other
test in the suite would still pass and the note text would quietly start flowing into
the audit trail. That is exactly why they are asserted explicitly here.

The rule being defended: note content, credentials and tokens never reach the audit
trail, the trace log, the execution record or persistent storage. Note *length* is
kept, because "was a note supplied at all" is an auditable fact and its text is not.
"""

from __future__ import annotations

import json

from procmine.automation.audit import AuditEvent, AuditLog, redact
from procmine.integrations import observability as obs
from procmine.integrations.auth import DEV_TOKENS
from procmine.integrations.execution_state import ExecutionRecord, new_execution_id

NOTE = "Approved the March payroll adjustment for employee 4471"
TOKEN = "dev-admin-token"
BEARER = "Bearer eyJhbGciOiJIUzI1NiJ9.super.secret"


# --- redaction ------------------------------------------------------------

def test_note_content_is_replaced_by_its_length():
    out = redact({"note_text": NOTE})
    assert out == {"note_text_length": len(NOTE)}
    assert NOTE not in json.dumps(out)


def test_every_content_bearing_key_is_reduced_to_a_length():
    for key in ("note", "note_text", "text", "content"):
        out = redact({key: NOTE})
        assert out == {f"{key}_length": len(NOTE)}


def test_credentials_are_dropped_entirely_not_shortened():
    """A length is fine for prose and is itself a leak for a secret."""
    for key in ("password", "secret", "token", "checkpoint_token", "api_key",
                "authorization", "cookie"):
        out = redact({key: "s3cr3t-value"})
        assert out == {f"{key}_redacted": True}
        assert "s3cr3t-value" not in json.dumps(out)


def test_a_key_that_merely_looks_secretish_is_also_dropped():
    """Fail closed: an unrecognised secret-shaped field is still a secret."""
    for key in ("refresh_token", "ACCESS_TOKEN", "customerApiKey", "db_password",
                "Authorization_Header"):
        out = redact({key: "value"})
        assert list(out) == [f"{key}_redacted"], key


def test_ordinary_fields_survive_redaction():
    out = redact({"route": "#/payroll-items", "status": "CONFIRMED", "attempts": 1})
    assert out == {"route": "#/payroll-items", "status": "CONFIRMED", "attempts": 1}


def test_redaction_does_not_mutate_its_input():
    payload = {"note_text": NOTE}
    redact(payload)
    assert payload == {"note_text": NOTE}


# --- the audit trail ------------------------------------------------------

def test_an_audit_event_carrying_a_note_never_serialises_it():
    event = AuditEvent(request_id="req_1", execution_id="exec_1", action="prepare",
                       result="success", route="#/payroll-items",
                       detail={"note_text": NOTE})
    blob = event.to_json()
    assert NOTE not in blob
    assert f'"note_text_length": {len(NOTE)}' in blob


def test_an_audit_log_never_stores_a_credential():
    log = AuditLog()
    log.record(AuditEvent(request_id="req_1", execution_id="exec_1", action="confirm",
                          result="success",
                          detail={"authorization": BEARER, "checkpoint_token": TOKEN,
                                  "note_text": NOTE}))
    blob = json.dumps(log.recent(10))
    for leak in (NOTE, TOKEN, BEARER, "eyJhbGciOiJIUzI1NiJ9"):
        assert leak not in blob, leak


def test_a_persisted_audit_file_contains_no_note_or_credential(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    log.record(AuditEvent(request_id="req_1", execution_id="exec_1", action="prepare",
                          result="success", detail={"note_text": NOTE, "token": TOKEN}))
    raw = path.read_text(encoding="utf-8")
    assert NOTE not in raw and TOKEN not in raw
    assert "note_text_length" in raw, "sanity: the event really was written"


def test_no_development_token_ever_appears_in_an_audit_record():
    log = AuditLog()
    for token in DEV_TOKENS:
        log.record(AuditEvent(request_id="req", execution_id="exec", action="confirm",
                              result="success", detail={"token": token}))
    assert not any(t in json.dumps(log.recent(50)) for t in DEV_TOKENS)


# --- the trace / observability log ---------------------------------------

def test_a_trace_event_redacts_through_the_same_function():
    """Two log paths with two redaction rules is how one of them gets it wrong."""
    event = obs.TraceEvent(event=obs.PREPARED, request_id="req_1",
                           execution_id="exec_1", detail={"note_text": NOTE,
                                                          "token": TOKEN})
    blob = json.dumps(event.to_dict())
    assert NOTE not in blob and TOKEN not in blob
    assert "note_text_length" in blob


def test_the_metrics_snapshot_exposes_counters_only():
    metrics = obs.Observability()
    metrics.incr(obs.REQUESTS_TOTAL)
    metrics.record(obs.TraceEvent(event=obs.CONFIRMED, request_id="req_1",
                                  detail={"note_text": NOTE}))
    blob = json.dumps(metrics.metrics())
    assert NOTE not in blob
    assert all(isinstance(v, (int, float)) for v in metrics.metrics().values())


def test_recent_trace_events_are_redacted_too():
    metrics = obs.Observability()
    metrics.record(obs.TraceEvent(event=obs.PREPARED, request_id="req_1",
                                  detail={"password": "hunter2"}))
    assert "hunter2" not in json.dumps(metrics.recent(10))


# --- the execution record -------------------------------------------------

def test_the_execution_record_has_no_field_that_could_hold_a_note():
    fields = set(ExecutionRecord.__dataclass_fields__)
    assert "note_length" in fields
    for forbidden in ("note", "note_text", "content", "token", "credential",
                      "password", "authorization"):
        assert forbidden not in fields, forbidden


def test_a_serialised_execution_record_carries_no_secret_shaped_key():
    record = ExecutionRecord(
        execution_id=new_execution_id(), request_id="req_1", actor="u_reviewer",
        process="HR / Payroll System", route="#/payroll-items",
        integration_mode="api_simulator", note_length=len(NOTE))
    blob = json.dumps(record.to_dict())
    assert NOTE not in blob
    for key in record.to_dict():
        assert not any(s in key.lower() for s in
                       ("token", "password", "secret", "authorization")), key


# --- the source itself ----------------------------------------------------

def test_no_integration_module_hardcodes_a_credential_shaped_literal():
    """The simulator's constant is a local development value and is named as such."""
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent / "src" / "procmine" / "integrations"
    for path in src.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for pattern in ("password =", "passwd =", "api_key =", "aws_", "BEGIN PRIVATE KEY"):
            assert pattern not in text, f"{path.name}: {pattern}"
