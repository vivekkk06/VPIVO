"""The execution state machine (Day-5 integration upgrade).

Why this is tested this hard: the states are the vocabulary the whole integration
layer reasons in. If `CONFIRMED -> CONFIRMING` were quietly allowed, that is the
exact shape of a double-submission bug against a payroll record — so the machine
fails loudly instead, and these tests assert it does.

`UNKNOWN` gets particular attention because it is the state the upgrade exists for:
it is *not* terminal, and it must be resolvable to either outcome.
"""

from __future__ import annotations

import pytest

from procmine.integrations.execution_state import (
    AWAITING_CONFIRMATION, CONFIRMED, CONFIRMING, FAILED, PREPARED, REPLAYED,
    STATES, TERMINAL, TRANSITIONS, UNKNOWN,
    ExecutionRecord, IllegalTransition, new_execution_id,
)


def _record(**kw) -> ExecutionRecord:
    base = dict(execution_id=new_execution_id(), request_id="req_x", actor="u_test",
                process="HR / Payroll System", route="#/payroll-items",
                integration_mode="mock", note_length=9)
    base.update(kw)
    return ExecutionRecord(**base)


# --- identity -------------------------------------------------------------

def test_execution_ids_are_prefixed_and_unique():
    ids = {new_execution_id() for _ in range(200)}
    assert len(ids) == 200
    assert all(i.startswith("exec_") for i in ids)


def test_a_new_record_starts_prepared():
    assert _record().status == PREPARED


# --- the legal path -------------------------------------------------------

def test_the_happy_path_walks_prepared_to_confirmed():
    r = _record()
    r.transition(AWAITING_CONFIRMATION).transition(CONFIRMING).transition(CONFIRMED)
    assert r.status == CONFIRMED
    assert [h["to"] for h in r.history] == [AWAITING_CONFIRMATION, CONFIRMING, CONFIRMED]


def test_confirmed_at_is_set_only_when_confirmed():
    r = _record().transition(AWAITING_CONFIRMATION).transition(CONFIRMING)
    assert r.confirmed_at is None
    r.transition(CONFIRMED)
    assert r.confirmed_at is not None


def test_a_failure_records_its_error_code():
    r = _record().transition(AWAITING_CONFIRMATION).transition(CONFIRMING)
    r.transition(FAILED, error_code="INTEGRATION_TIMEOUT")
    assert r.status == FAILED
    assert r.error_code == "INTEGRATION_TIMEOUT"


def test_history_records_both_ends_of_every_move():
    r = _record().transition(AWAITING_CONFIRMATION)
    assert r.history[0]["from"] == PREPARED
    assert r.history[0]["to"] == AWAITING_CONFIRMATION
    assert r.history[0]["at"]


# --- the illegal paths ----------------------------------------------------

def test_confirmed_cannot_go_back_to_confirming():
    """The double-submission shape. This must never be silently permitted."""
    r = _record().transition(AWAITING_CONFIRMATION).transition(CONFIRMING).transition(CONFIRMED)
    with pytest.raises(IllegalTransition):
        r.transition(CONFIRMING)


def test_prepared_cannot_jump_straight_to_confirmed():
    """Skipping the review checkpoint is not expressible in the machine."""
    with pytest.raises(IllegalTransition):
        _record().transition(CONFIRMED)


def test_every_terminal_state_is_a_dead_end():
    for terminal in TERMINAL:
        assert TRANSITIONS[terminal] == set(), terminal


def test_an_unknown_state_name_is_rejected():
    with pytest.raises(IllegalTransition):
        _record().transition("MAYBE")


def test_an_illegal_transition_leaves_the_record_untouched():
    r = _record().transition(AWAITING_CONFIRMATION)
    with pytest.raises(IllegalTransition):
        r.transition(CONFIRMED)
    assert r.status == AWAITING_CONFIRMATION
    assert len(r.history) == 1


# --- UNKNOWN, the state this upgrade exists for ---------------------------

def test_unknown_is_not_terminal():
    assert UNKNOWN not in TERMINAL


def test_unknown_can_resolve_to_either_outcome():
    for outcome in (CONFIRMED, FAILED):
        r = _record().transition(AWAITING_CONFIRMATION).transition(CONFIRMING)
        r.transition(UNKNOWN, error_code="CONFIRMATION_UNKNOWN")
        r.transition(outcome)
        assert r.status == outcome


def test_unknown_is_only_reachable_from_confirming():
    """An outcome can only be in doubt if a confirmation was actually attempted."""
    sources = [s for s, targets in TRANSITIONS.items() if UNKNOWN in targets]
    assert sources == [CONFIRMING]


def test_replayed_is_reachable_only_before_confirming_starts():
    assert REPLAYED in TRANSITIONS[AWAITING_CONFIRMATION]
    assert REPLAYED not in TRANSITIONS[CONFIRMING]


# --- what the record is allowed to carry ----------------------------------

def test_the_record_carries_note_length_but_never_note_content():
    r = _record(note_length=len("Reviewed per standard process."))
    blob = str(r.to_dict())
    assert "Reviewed per standard process." not in blob
    assert r.to_dict()["note_length"] == 30


def test_to_dict_exposes_no_credential_shaped_field():
    keys = set(_record().to_dict())
    assert not {k for k in keys if any(
        s in k.lower() for s in ("token", "password", "secret", "credential", "authorization"))}


def test_to_dict_round_trips_the_fields_persistence_needs():
    r = _record().transition(AWAITING_CONFIRMATION)
    d = r.to_dict()
    for field in ("execution_id", "request_id", "actor", "process", "route",
                  "integration_mode", "status", "created_at", "updated_at"):
        assert d[field] is not None, field


def test_transitions_table_covers_every_declared_state():
    assert set(TRANSITIONS) == STATES
