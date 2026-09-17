"""The orchestrator: execution lifecycle, idempotency, and the lost response (Day-5).

THE DISTINCTION THIS FILE EXISTS TO DEFEND
------------------------------------------
Three things look alike from the outside and must not be treated alike:

1. **the same request repeated safely** — the target recognises the idempotency key
   and returns the first outcome instead of applying the change twice;
2. **a replayed consumed token** — refused outright, because the checkpoint is spent;
3. **an unknown outcome** — the confirmation may or may not have landed. This one is
   resolved by *asking*, never by retrying.

Collapsing (3) into (2) loses a real payroll change. Collapsing (3) into an automatic
retry duplicates one. Confirmation is never retried automatically, and a test below
counts the calls to prove it.
"""

from __future__ import annotations

import pytest

from procmine.automation.hr_payroll_automation import UnknownRouteError
from procmine.automation.mock_hr_app import MockHRApplication
from procmine.integrations import execution_state as st
from procmine.integrations import observability as obs
from procmine.integrations.api_hr_application import ApiHRApplication
from procmine.integrations.auth import (
    ROLE_ADMIN, ROLE_OPERATOR, ROLE_REVIEWER, Actor, AuthorizationError,
)
from procmine.integrations.hr_api_simulator import TIMEOUT, HRApiSimulator
from procmine.integrations.hr_application import MODE_API, MODE_MOCK
from procmine.integrations.orchestrator import Orchestrator, ReplayRejected
from procmine.integrations.repositories import (
    InMemoryExecutionRepository, SQLiteExecutionRepository,
)

ROUTE = "#/payroll-items"
NOTE = "Reviewed per standard process."

REVIEWER = Actor("u_reviewer", ROLE_REVIEWER)
OPERATOR = Actor("u_operator", ROLE_OPERATOR)
ADMIN = Actor("u_admin", ROLE_ADMIN)


@pytest.fixture
def orch() -> Orchestrator:
    return Orchestrator(repo=InMemoryExecutionRepository())


def _api_target(mode=None, **kw):
    sim = HRApiSimulator(mode=mode, **kw) if mode else HRApiSimulator()
    return ApiHRApplication(sim), sim


# --- the ordinary lifecycle ----------------------------------------------

def test_prepare_stops_at_the_review_checkpoint(orch):
    prepared = orch.prepare(REVIEWER, MockHRApplication(), ROUTE, NOTE)
    assert prepared.record.status == st.AWAITING_CONFIRMATION
    assert prepared.checkpoint.confirmed is False
    assert orch.repo.get(prepared.execution_id).status == st.AWAITING_CONFIRMATION


def test_confirm_completes_the_execution(orch):
    prepared = orch.prepare(REVIEWER, MockHRApplication(), ROUTE, NOTE)
    record = orch.confirm(REVIEWER, prepared.execution_id)
    assert record.status == st.CONFIRMED
    assert record.confirmed_at is not None


def test_the_execution_is_recorded_with_its_integration_mode(orch):
    app, _ = _api_target()
    prepared = orch.prepare(REVIEWER, app, ROUTE, NOTE, integration_mode=MODE_API)
    assert orch.repo.get(prepared.execution_id).integration_mode == MODE_API


def test_a_safe_stop_is_recorded_as_a_failed_execution(orch):
    with pytest.raises(UnknownRouteError) as exc:
        orch.prepare(REVIEWER, MockHRApplication(), "#/not-evidenced", NOTE)
    record = orch.repo.get(exc.value.execution_id)
    assert record.status == st.FAILED
    assert record.error_code == "INVALID_ROUTE"


def test_the_note_length_is_recorded_and_the_note_is_not(orch):
    prepared = orch.prepare(REVIEWER, MockHRApplication(), ROUTE, NOTE)
    record = orch.repo.get(prepared.execution_id)
    assert record.note_length == len(NOTE)
    assert NOTE not in str(record.to_dict())


# --- (2) a replayed, consumed execution ----------------------------------

def test_a_confirmed_execution_cannot_be_confirmed_again(orch):
    prepared = orch.prepare(REVIEWER, MockHRApplication(), ROUTE, NOTE)
    orch.confirm(REVIEWER, prepared.execution_id)
    with pytest.raises(ReplayRejected):
        orch.confirm(REVIEWER, prepared.execution_id)


def test_a_replay_attempt_does_not_touch_the_target(orch):
    app, sim = _api_target()
    prepared = orch.prepare(REVIEWER, app, ROUTE, NOTE, integration_mode=MODE_API)
    orch.confirm(REVIEWER, prepared.execution_id)
    calls_after_first = list(sim.calls)
    with pytest.raises(ReplayRejected):
        orch.confirm(REVIEWER, prepared.execution_id)
    assert sim.calls == calls_after_first, "a replay must not reach the service"


def test_a_replay_is_counted_and_leaves_the_record_confirmed(orch):
    prepared = orch.prepare(REVIEWER, MockHRApplication(), ROUTE, NOTE)
    orch.confirm(REVIEWER, prepared.execution_id)
    with pytest.raises(ReplayRejected):
        orch.confirm(REVIEWER, prepared.execution_id)
    assert orch.metrics.counters[obs.REPLAY_TOTAL] == 1
    assert orch.repo.get(prepared.execution_id).status == st.CONFIRMED


def test_confirming_an_unknown_execution_id_raises(orch):
    with pytest.raises(KeyError):
        orch.confirm(REVIEWER, "exec_never_prepared")


# --- (1) the same business action, repeated safely -----------------------

def test_the_idempotency_key_is_recorded_against_the_execution(orch):
    app, _ = _api_target()
    prepared = orch.prepare(REVIEWER, app, ROUTE, NOTE, integration_mode=MODE_API)
    record = orch.repo.get(prepared.execution_id)
    assert record.idempotency_key == app.idempotency_key
    assert orch.repo.find_by_idempotency_key(app.idempotency_key) is not None


def test_repeating_the_same_key_at_the_target_does_not_apply_it_twice(orch):
    """Safe repeat: the service returns the first outcome rather than re-applying."""
    app, sim = _api_target()
    prepared = orch.prepare(REVIEWER, app, ROUTE, NOTE, integration_mode=MODE_API)
    orch.confirm(REVIEWER, prepared.execution_id)
    repeat = sim.confirm(app._token, ROUTE, app.idempotency_key)
    assert repeat["idempotent_replay"] is True


def test_two_executions_never_share_an_idempotency_key(orch):
    keys = set()
    for _ in range(3):
        app, _ = _api_target()
        prepared = orch.prepare(REVIEWER, app, ROUTE, NOTE, integration_mode=MODE_API)
        keys.add(orch.repo.get(prepared.execution_id).idempotency_key)
    assert len(keys) == 3


# --- (3) the unknown outcome: the case this upgrade exists for -----------

def test_a_lost_response_becomes_unknown_not_failed(orch):
    app, _ = _api_target(TIMEOUT, applied_despite_failure=True)
    prepared = orch.prepare(REVIEWER, app, ROUTE, NOTE, integration_mode=MODE_API)
    record = orch.confirm(REVIEWER, prepared.execution_id)
    assert record.status == st.UNKNOWN
    assert record.error_code == "CONFIRMATION_UNKNOWN"


def test_a_clean_failure_is_failed_not_unknown(orch):
    """If the service never committed, the outcome is known. Do not muddy it."""
    app, _ = _api_target(TIMEOUT)
    prepared = orch.prepare(REVIEWER, app, ROUTE, NOTE, integration_mode=MODE_API)
    record = orch.confirm(REVIEWER, prepared.execution_id)
    assert record.status == st.FAILED
    assert record.error_code == "INTEGRATION_TIMEOUT"


def test_an_unknown_execution_is_resolved_by_asking_not_by_retrying(orch):
    app, sim = _api_target(TIMEOUT, applied_despite_failure=True)
    prepared = orch.prepare(REVIEWER, app, ROUTE, NOTE, integration_mode=MODE_API)
    orch.confirm(REVIEWER, prepared.execution_id)

    confirms_before = sim.calls.count(f"confirm:{ROUTE}")
    resolved = orch.resolve_unknown(REVIEWER, prepared.execution_id)

    assert resolved.status == st.CONFIRMED
    assert sim.calls.count(f"confirm:{ROUTE}") == confirms_before, (
        "resolving an unknown outcome must never re-submit the mutation")
    assert sim.calls[-1] == "get_status"


def test_the_whole_lost_response_journey_is_recorded_in_the_history(orch):
    app, _ = _api_target(TIMEOUT, applied_despite_failure=True)
    prepared = orch.prepare(REVIEWER, app, ROUTE, NOTE, integration_mode=MODE_API)
    orch.confirm(REVIEWER, prepared.execution_id)
    resolved = orch.resolve_unknown(REVIEWER, prepared.execution_id)
    assert [h["to"] for h in resolved.history] == [
        st.AWAITING_CONFIRMATION, st.CONFIRMING, st.UNKNOWN, st.CONFIRMED]


def test_an_unknown_execution_keeps_its_adapter_until_it_is_resolved(orch):
    """Dropping it would strand the execution in UNKNOWN forever."""
    app, _ = _api_target(TIMEOUT, applied_despite_failure=True)
    prepared = orch.prepare(REVIEWER, app, ROUTE, NOTE, integration_mode=MODE_API)
    orch.confirm(REVIEWER, prepared.execution_id)
    assert prepared.execution_id in orch._live
    orch.resolve_unknown(REVIEWER, prepared.execution_id)
    assert prepared.execution_id not in orch._live, "settled executions must be released"


def test_a_target_that_cannot_be_asked_stays_unknown_and_says_so(orch):
    """The mock has no status endpoint. UNKNOWN is then the honest answer."""
    class LosesTheResponse(MockHRApplication):
        outcome_is_unknown = True

        def click(self, element_id):
            super().click(element_id)
            raise RuntimeError("response lost")

    prepared = orch.prepare(REVIEWER, LosesTheResponse(), ROUTE, NOTE)
    assert orch.confirm(REVIEWER, prepared.execution_id).status == st.UNKNOWN
    still = orch.resolve_unknown(REVIEWER, prepared.execution_id)
    assert still.status == st.UNKNOWN


def test_resolving_a_settled_execution_is_a_no_op(orch):
    prepared = orch.prepare(REVIEWER, MockHRApplication(), ROUTE, NOTE)
    orch.confirm(REVIEWER, prepared.execution_id)
    assert orch.resolve_unknown(REVIEWER, prepared.execution_id).status == st.CONFIRMED


# --- authorisation is enforced by the orchestrator, not only the API -----

def test_an_operator_may_prepare_but_not_confirm(orch):
    prepared = orch.prepare(OPERATOR, MockHRApplication(), ROUTE, NOTE)
    assert prepared.record.status == st.AWAITING_CONFIRMATION
    with pytest.raises(AuthorizationError):
        orch.confirm(OPERATOR, prepared.execution_id)


def test_a_blocked_confirmation_leaves_the_execution_awaiting_review(orch):
    """Refusing must not consume the checkpoint -- a reviewer still needs it."""
    app, sim = _api_target()
    prepared = orch.prepare(OPERATOR, app, ROUTE, NOTE, integration_mode=MODE_API)
    with pytest.raises(AuthorizationError):
        orch.confirm(OPERATOR, prepared.execution_id)
    assert orch.repo.get(prepared.execution_id).status == st.AWAITING_CONFIRMATION
    assert "confirm:" not in " ".join(sim.calls)
    # and the reviewer can still complete it
    assert orch.confirm(REVIEWER, prepared.execution_id).status == st.CONFIRMED


def test_an_unauthorised_actor_cannot_prepare(orch):
    with pytest.raises(AuthorizationError):
        orch.prepare(Actor("u_stranger", "nobody"), MockHRApplication(), ROUTE, NOTE)


# --- observability --------------------------------------------------------

def test_counters_track_success_failure_and_unknown_separately(orch):
    orch.confirm(REVIEWER, orch.prepare(
        REVIEWER, MockHRApplication(), ROUTE, NOTE).execution_id)
    app, _ = _api_target(TIMEOUT)
    orch.confirm(REVIEWER, orch.prepare(
        REVIEWER, app, ROUTE, NOTE, integration_mode=MODE_API).execution_id)
    app2, _ = _api_target(TIMEOUT, applied_despite_failure=True)
    orch.confirm(REVIEWER, orch.prepare(
        REVIEWER, app2, ROUTE, NOTE, integration_mode=MODE_API).execution_id)

    counters = orch.metrics.counters
    assert counters[obs.SUCCESS_TOTAL] == 1
    assert counters[obs.FAILURE_TOTAL] == 1
    assert counters[obs.UNKNOWN_TOTAL] == 1
    assert counters[obs.REQUESTS_TOTAL] == 3


def test_one_execution_is_traceable_end_to_end_by_its_id(orch):
    prepared = orch.prepare(REVIEWER, MockHRApplication(), ROUTE, NOTE)
    orch.confirm(REVIEWER, prepared.execution_id)
    events = [e["event"] for e in orch.metrics.recent(50, prepared.execution_id)]
    for expected in (obs.PREPARED, obs.REVIEW_REQUIRED, obs.CONFIRM_REQUESTED,
                     obs.CONFIRM_STARTED, obs.CONFIRMED):
        assert expected in events, expected


def test_a_confirmation_duration_is_measured(orch):
    orch.confirm(REVIEWER, orch.prepare(
        REVIEWER, MockHRApplication(), ROUTE, NOTE).execution_id)
    assert orch.metrics.metrics()["confirmation_duration_ms_max"] >= 0


def test_the_audit_trail_records_both_ends_of_the_execution(orch):
    prepared = orch.prepare(REVIEWER, MockHRApplication(), ROUTE, NOTE)
    orch.confirm(REVIEWER, prepared.execution_id)
    actions = [(e["action"], e["result"]) for e in orch.audit.recent(50)
               if e["execution_id"] == prepared.execution_id]
    assert ("prepare", "success") in actions
    assert ("confirm", "success") in actions


# --- the abstraction holds against a durable backend ---------------------

def test_the_same_lifecycle_holds_against_sqlite(tmp_path):
    orch = Orchestrator(repo=SQLiteExecutionRepository(tmp_path / "exec.db"))
    app, _ = _api_target(TIMEOUT, applied_despite_failure=True)
    prepared = orch.prepare(REVIEWER, app, ROUTE, NOTE, integration_mode=MODE_API)
    assert orch.confirm(REVIEWER, prepared.execution_id).status == st.UNKNOWN
    assert orch.resolve_unknown(REVIEWER, prepared.execution_id).status == st.CONFIRMED
    # and it is durable
    reopened = SQLiteExecutionRepository(tmp_path / "exec.db")
    assert reopened.get(prepared.execution_id).status == st.CONFIRMED


def test_status_is_readable_by_any_role_that_may_inspect(orch):
    prepared = orch.prepare(REVIEWER, MockHRApplication(), ROUTE, NOTE)
    for actor in (OPERATOR, REVIEWER, ADMIN):
        assert orch.status(actor, prepared.execution_id).execution_id == prepared.execution_id


def test_status_of_an_unknown_id_is_none(orch):
    assert orch.status(REVIEWER, "exec_nope") is None
