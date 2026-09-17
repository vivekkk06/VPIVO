"""Execution persistence (Day-5 integration upgrade).

WHY THIS MATTERS MORE THAN IT LOOKS
-----------------------------------
The prototype kept executions in a process-local dict. The one execution you cannot
afford to lose is precisely the one whose outcome is `UNKNOWN` — a restart would
strand it forever, with no way to ask the target what happened.

So the point of these tests is not "SQLite works". It is that the *abstraction* is
real: the same orchestrator behaviour holds against either backend, and a durable
backend genuinely survives a restart. The restart is simulated the only honest way —
by discarding the repository object and opening the file again.

Note content, credentials and tokens must never reach storage.
"""

from __future__ import annotations

import pytest

from procmine.integrations.execution_state import (
    AWAITING_CONFIRMATION, CONFIRMED, CONFIRMING, ExecutionRecord, new_execution_id,
)
from procmine.integrations.repositories import (
    ExecutionRepository, InMemoryExecutionRepository, SQLiteExecutionRepository,
)

SECRET_NOTE = "Rachel approved the March payroll adjustment"


def _record(**kw) -> ExecutionRecord:
    base = dict(execution_id=new_execution_id(), request_id="req_abc", actor="u_reviewer",
                process="HR / Payroll System", route="#/payroll-items",
                integration_mode="api_simulator", note_length=len(SECRET_NOTE),
                idempotency_key="idem_fixed_key")
    base.update(kw)
    return ExecutionRecord(**base)


@pytest.fixture(params=["memory", "sqlite"])
def repo(request, tmp_path):
    """Both backends run the identical suite -- that is what proves the abstraction."""
    if request.param == "memory":
        return InMemoryExecutionRepository()
    return SQLiteExecutionRepository(tmp_path / "executions.db")


# --- the contract both backends must honour -------------------------------

def test_both_backends_satisfy_the_repository_interface(repo):
    assert isinstance(repo, ExecutionRepository)


def test_save_then_retrieve_round_trips_every_field(repo):
    original = _record()
    repo.save(original)
    loaded = repo.get(original.execution_id)
    assert loaded is not None
    assert loaded.to_dict() == original.to_dict()


def test_an_unknown_execution_id_returns_none_rather_than_raising(repo):
    assert repo.get("exec_does_not_exist") is None


def test_a_status_update_overwrites_rather_than_duplicating(repo):
    record = _record()
    repo.save(record)
    record.transition(AWAITING_CONFIRMATION)
    repo.save(record)
    record.transition(CONFIRMING).transition(CONFIRMED)
    repo.save(record)

    loaded = repo.get(record.execution_id)
    assert loaded.status == CONFIRMED
    assert loaded.confirmed_at is not None
    assert len(repo.list_recent(50)) == 1, "the same execution must not be stored twice"


def test_history_survives_the_round_trip(repo):
    record = _record()
    record.transition(AWAITING_CONFIRMATION).transition(CONFIRMING).transition(CONFIRMED)
    repo.save(record)
    loaded = repo.get(record.execution_id)
    assert [h["to"] for h in loaded.history] == [
        AWAITING_CONFIRMATION, CONFIRMING, CONFIRMED]


def test_an_execution_can_be_found_by_its_idempotency_key(repo):
    record = _record(idempotency_key="idem_lookup_me")
    repo.save(record)
    found = repo.find_by_idempotency_key("idem_lookup_me")
    assert found is not None and found.execution_id == record.execution_id


def test_an_unmatched_idempotency_key_returns_none(repo):
    repo.save(_record())
    assert repo.find_by_idempotency_key("idem_never_issued") is None


def test_list_recent_is_bounded_and_ordered_oldest_last_written(repo):
    made = []
    for i in range(5):
        r = _record(execution_id=f"exec_{i:016d}", idempotency_key=f"idem_{i}")
        r.created_at = f"2026-09-18T10:0{i}:00+00:00"
        repo.save(r)
        made.append(r.execution_id)
    recent = repo.list_recent(3)
    assert [r.execution_id for r in recent] == made[-3:]


# --- durability: the property the abstraction exists for ------------------

def test_sqlite_state_survives_a_process_restart(tmp_path):
    """The whole point. An UNKNOWN execution must outlive the process that made it."""
    path = tmp_path / "executions.db"
    record = _record()
    record.transition(AWAITING_CONFIRMATION).transition(CONFIRMING)
    SQLiteExecutionRepository(path).save(record)

    # Simulate a restart: the object is gone, only the file remains.
    reopened = SQLiteExecutionRepository(path)
    loaded = reopened.get(record.execution_id)
    assert loaded is not None, "execution did not survive the restart"
    assert loaded.status == CONFIRMING
    assert loaded.idempotency_key == "idem_fixed_key"


def test_an_unknown_execution_is_still_resolvable_after_a_restart(tmp_path):
    from procmine.integrations.execution_state import UNKNOWN

    path = tmp_path / "executions.db"
    record = _record()
    record.transition(AWAITING_CONFIRMATION).transition(CONFIRMING)
    record.transition(UNKNOWN, error_code="CONFIRMATION_UNKNOWN")
    SQLiteExecutionRepository(path).save(record)

    reopened = SQLiteExecutionRepository(path).get(record.execution_id)
    assert reopened.status == UNKNOWN
    assert reopened.error_code == "CONFIRMATION_UNKNOWN"
    # Still not terminal, so it can still be settled.
    reopened.transition(CONFIRMED)
    assert reopened.status == CONFIRMED


def test_in_memory_state_does_not_survive_a_restart_and_says_so(tmp_path):
    """Stated as a test so the difference between the backends is not folklore."""
    record = _record()
    InMemoryExecutionRepository().save(record)
    assert InMemoryExecutionRepository().get(record.execution_id) is None


# --- what must never be stored -------------------------------------------

def test_the_schema_has_no_column_for_note_content():
    from procmine.integrations.repositories import _SCHEMA

    lowered = _SCHEMA.lower()
    for forbidden in ("note_text", "note_content", "token", "password", "secret",
                      "credential"):
        assert forbidden not in lowered, forbidden


def test_note_content_never_reaches_the_database_file(tmp_path):
    path = tmp_path / "executions.db"
    repo = SQLiteExecutionRepository(path)
    repo.save(_record())
    raw = path.read_bytes()
    assert SECRET_NOTE.encode() not in raw
    assert b"idem_fixed_key" in raw, "sanity: the file really did get written"


def test_note_length_is_kept_because_it_is_auditable(repo):
    record = _record()
    repo.save(record)
    assert repo.get(record.execution_id).note_length == len(SECRET_NOTE)
