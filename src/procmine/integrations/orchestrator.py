"""Automation orchestrator: the layer that owns execution lifecycle.

POSITION IN THE ARCHITECTURE

    API  ->  auth  ->  policy  ->  ORCHESTRATOR  ->  HRApplication adapter
                                        |
                                        +--> execution state -> repository
                                        +--> audit / observability

The orchestrator decides *when* an automation step may run and records what happened.
It does not know whether the target is a mock, a browser or an HTTP service, and it
does not re-implement the safety rules: `prepare_note_submission` and
`confirm_submission` remain the single place route/note/element checks live.

THE CASE THIS EXISTS FOR
------------------------
`confirm` can fail in a way that leaves the outcome genuinely unknown — the service
applied the change and the response was lost. The orchestrator moves such an execution
to `UNKNOWN` rather than `FAILED`, because those demand different operator action, and
`resolve_unknown` asks the target what actually happened. Confirmation itself is
**never retried automatically**.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from procmine.automation.audit import AuditEvent, AuditLog, error_type_for, new_request_id
from procmine.automation.hr_payroll_automation import (
    AutomationSafetyError, ReviewCheckpoint, confirm_submission, prepare_note_submission,
)
from procmine.integrations import execution_state as st
from procmine.integrations import observability as obs
from procmine.integrations.auth import Actor, CONFIRM_AUTOMATION, PREPARE_AUTOMATION, authorize
from procmine.integrations.hr_application import MODE_MOCK
from procmine.integrations.repositories import (
    ExecutionRepository, InMemoryExecutionRepository,
)

HR_PROCESS = "HR / Payroll System"


def integration_error_code(app, exc: BaseException) -> str:
    """Prefer the adapter's own integration code over the generic taxonomy.

    A timeout from the target service is an `INTEGRATION_TIMEOUT`, not a generic
    `CONFIRMATION_REJECTED`: the two demand different operator action, so collapsing
    them would discard the distinction the taxonomy exists for. Falls back to the
    existing exception mapping for targets that report nothing of their own — the
    mock and the browser — so their behaviour is unchanged.
    """
    err = getattr(app, "last_error", None)
    code = getattr(err, "code", None)
    return code if isinstance(code, str) and code else error_type_for(exc)


class ReplayRejected(RuntimeError):
    """A consumed execution was confirmed again."""


# A durable status source for one integration mode: given the persisted record, ask the
# target what it recorded. Needs nothing from the process that ran the confirmation,
# which is what lets an UNKNOWN outcome be settled after a restart.
StatusResolver = Callable[[st.ExecutionRecord], dict]


def _bind_request(app, request_id: str) -> None:
    """Let an adapter that correlates calls carry this request id. Optional."""
    bind = getattr(app, "bind_request_id", None)
    if callable(bind):
        bind(request_id)


@dataclass
class PreparedExecution:
    execution_id: str
    request_id: str
    checkpoint: ReviewCheckpoint
    app: object
    record: st.ExecutionRecord


@dataclass
class Orchestrator:
    repo: ExecutionRepository = field(default_factory=InMemoryExecutionRepository)
    audit: AuditLog = field(default_factory=AuditLog)
    metrics: obs.Observability = field(default_factory=obs.Observability)
    # integration mode -> durable status source (see `StatusResolver`)
    resolvers: dict[str, StatusResolver] = field(default_factory=dict)
    # live adapters for executions awaiting confirmation, keyed by execution_id
    _live: dict[str, PreparedExecution] = field(default_factory=dict)

    # -- prepare -----------------------------------------------------------
    def prepare(self, actor: Actor, app, route: str, note_text: str, *,
                integration_mode: str = MODE_MOCK,
                request_id: str | None = None,
                execution_id: str | None = None) -> PreparedExecution:
        """`execution_id` may be supplied, or adopted from an adapter that already carries
        one (the HTTP adapter's execution id *is* its idempotency key). Two different
        ids for one execution would break idempotency, so that is refused."""
        request_id = request_id or new_request_id()
        adapter_id = getattr(app, "execution_id", None)
        if execution_id and adapter_id and execution_id != adapter_id:
            raise ValueError("the adapter carries a different execution id")
        execution_id = execution_id or adapter_id or st.new_execution_id()
        _bind_request(app, request_id)
        self.metrics.incr(obs.REQUESTS_TOTAL)
        self.metrics.record(obs.TraceEvent(event=obs.REQUEST_RECEIVED, request_id=request_id,
                                           actor=actor.user_id, route=route,
                                           integration_mode=integration_mode))
        authorize(actor, PREPARE_AUTOMATION)
        self.metrics.record(obs.TraceEvent(event=obs.AUTHORIZED, request_id=request_id,
                                           actor=actor.user_id))

        record = st.ExecutionRecord(
            execution_id=execution_id, request_id=request_id, actor=actor.user_id,
            process=HR_PROCESS, route=route, integration_mode=integration_mode,
            note_length=len(note_text or ""),
            idempotency_key=getattr(app, "idempotency_key", None),
        )
        try:
            checkpoint = prepare_note_submission(app, route, note_text)
        except AutomationSafetyError as exc:
            code = integration_error_code(app, exc)
            # The API layer reports the failed execution by id, so the id has to
            # survive the raise.
            exc.execution_id = execution_id
            record.transition(st.FAILED, error_code=code)
            self.repo.save(record)
            self.metrics.incr(obs.FAILURE_TOTAL)
            self.metrics.record(obs.TraceEvent(event=obs.FAILED, request_id=request_id,
                                               execution_id=execution_id, actor=actor.user_id,
                                               route=route, error_code=code))
            self.audit.record(AuditEvent(request_id=request_id, execution_id=execution_id,
                                         action="prepare", result="safe_stop", route=route,
                                         error_type=code, human_checkpoint=False,
                                         detail={"note_length": record.note_length}))
            raise

        record.transition(st.AWAITING_CONFIRMATION)
        self.repo.save(record)
        prepared = PreparedExecution(execution_id, request_id, checkpoint, app, record)
        self._live[execution_id] = prepared

        self.metrics.record(obs.TraceEvent(event=obs.PREPARED, request_id=request_id,
                                           execution_id=execution_id, actor=actor.user_id,
                                           route=route, integration_mode=integration_mode))
        self.metrics.record(obs.TraceEvent(event=obs.REVIEW_REQUIRED, request_id=request_id,
                                           execution_id=execution_id))
        # The note's length, never its text -- not even in the in-memory buffer.
        self.audit.record(AuditEvent(request_id=request_id, execution_id=execution_id,
                                     action="prepare", result="success", route=route,
                                     human_checkpoint=True,
                                     confirmation_status="awaiting_human_review",
                                     detail={"note_length": record.note_length}))
        return prepared

    # -- confirm -----------------------------------------------------------
    def confirm(self, actor: Actor, execution_id: str, *,
                request_id: str | None = None) -> st.ExecutionRecord:
        """Apply the reviewed action. Never retried automatically."""
        request_id = request_id or new_request_id()
        self.metrics.record(obs.TraceEvent(event=obs.CONFIRM_REQUESTED, request_id=request_id,
                                           execution_id=execution_id, actor=actor.user_id))
        authorize(actor, CONFIRM_AUTOMATION)

        record = self.repo.get(execution_id)
        if record is None:
            raise KeyError(execution_id)

        if record.status in st.TERMINAL or execution_id not in self._live:
            # Already consumed. Distinguish a replay from an unknown-outcome retry:
            # only the former is safe to reject outright.
            self.metrics.incr(obs.REPLAY_TOTAL)
            self.metrics.record(obs.TraceEvent(event=obs.REPLAY_REJECTED, request_id=request_id,
                                               execution_id=execution_id,
                                               error_code="REPLAYED_REQUEST"))
            self.audit.record(AuditEvent(request_id=request_id, execution_id=execution_id,
                                         action="confirm", result="rejected",
                                         route=record.route, error_type="REPLAYED_REQUEST",
                                         human_checkpoint=True))
            raise ReplayRejected(
                f"execution {execution_id} is already {record.status}; not re-confirmed")

        prepared = self._live[execution_id]
        _bind_request(prepared.app, request_id)
        record.transition(st.CONFIRMING)
        self.repo.save(record)
        self.metrics.record(obs.TraceEvent(event=obs.CONFIRM_STARTED, request_id=request_id,
                                           execution_id=execution_id))

        t0 = time.perf_counter()
        try:
            confirm_submission(prepared.app, prepared.checkpoint)
        except Exception as exc:  # noqa: BLE001 - every failure must be classified
            unknown = bool(getattr(prepared.app, "outcome_is_unknown", False))
            if not unknown:
                self._live.pop(execution_id, None)
            # An UNKNOWN execution KEEPS its adapter: resolving it means asking that
            # same target what actually happened. Dropping it here would strand the
            # execution in UNKNOWN forever, which is the bug this whole path exists
            # to avoid.
            code = ("CONFIRMATION_UNKNOWN" if unknown
                    else integration_error_code(prepared.app, exc))
            record.transition(st.UNKNOWN if unknown else st.FAILED, error_code=code)
            self.repo.save(record)
            self.metrics.incr(obs.UNKNOWN_TOTAL if unknown else obs.FAILURE_TOTAL)
            self.metrics.record(obs.TraceEvent(
                event=obs.UNKNOWN if unknown else obs.FAILED, request_id=request_id,
                execution_id=execution_id, error_code=code,
                duration_ms=(time.perf_counter() - t0) * 1000))
            self.audit.record(AuditEvent(request_id=request_id, execution_id=execution_id,
                                         action="confirm",
                                         result="unknown" if unknown else "safe_stop",
                                         route=record.route,
                                         error_type=code, human_checkpoint=True,
                                         confirmation_status=record.status))
            return record

        self._live.pop(execution_id, None)
        record.transition(st.CONFIRMED)
        self.repo.save(record)
        self.metrics.incr(obs.SUCCESS_TOTAL)
        self.metrics.record(obs.TraceEvent(event=obs.CONFIRMED, request_id=request_id,
                                           execution_id=execution_id, route=record.route,
                                           duration_ms=(time.perf_counter() - t0) * 1000))
        self.audit.record(AuditEvent(request_id=request_id, execution_id=execution_id,
                                     action="confirm", result="success", route=record.route,
                                     human_checkpoint=True, confirmation_status="confirmed"))
        return record

    # -- status ------------------------------------------------------------
    def status(self, actor: Actor, execution_id: str) -> st.ExecutionRecord | None:
        from procmine.integrations.auth import INSPECT_EXECUTIONS
        authorize(actor, INSPECT_EXECUTIONS)
        return self.repo.get(execution_id)

    def _status_query(self, record: st.ExecutionRecord):
        """The live adapter's status check if it is still held, else a durable resolver."""
        prepared = self._live.get(record.execution_id)
        query = getattr(prepared.app if prepared else None, "query_remote_status", None)
        if query is not None:
            return query
        resolver = self.resolvers.get(record.integration_mode)
        if resolver is None:
            return None
        return lambda: resolver(record)

    def resolve_unknown(self, actor: Actor, execution_id: str) -> st.ExecutionRecord | None:
        """Ask the target what actually happened, and settle an UNKNOWN execution.

        This is the answer to the lost-response problem: rather than retrying a
        mutation, query the authoritative outcome and move to CONFIRMED or FAILED.
        Only possible where a status source exists: the live adapter's own check, or a
        durable resolver registered for the integration mode (which also works after a
        restart). The mock and browser targets have neither, so an UNKNOWN there stays
        UNKNOWN, which is the honest result. So does one whose status source cannot be
        reached, or reports the confirmation still in progress.
        """
        from procmine.integrations.auth import INSPECT_EXECUTIONS
        authorize(actor, INSPECT_EXECUTIONS)
        record = self.repo.get(execution_id)
        if record is None or record.status != st.UNKNOWN:
            return record
        query = self._status_query(record)
        if query is None:
            return record          # cannot be resolved; stays UNKNOWN
        try:
            remote = query()
        except Exception as exc:  # noqa: BLE001 - an unreachable status source settles nothing
            code = getattr(exc, "code", None) or type(exc).__name__
            self.metrics.record(obs.TraceEvent(
                event=obs.STATUS_LOOKUP_FAILED, request_id=record.request_id,
                execution_id=execution_id, error_code=code))
            self.audit.record(AuditEvent(request_id=new_request_id(), execution_id=execution_id,
                                         action="status_lookup", result="lookup_failed",
                                         route=record.route, error_type=code,
                                         confirmation_status=st.UNKNOWN))
            return record
        if remote.get("in_progress"):
            # The target has not finished. Settling now could record FAILED for a
            # confirmation that is about to commit.
            self.metrics.record(obs.TraceEvent(
                event=obs.STILL_IN_PROGRESS, request_id=record.request_id,
                execution_id=execution_id))
            self.audit.record(AuditEvent(request_id=new_request_id(), execution_id=execution_id,
                                         action="status_lookup", result="still_in_progress",
                                         route=record.route, confirmation_status=st.UNKNOWN))
            return record
        confirmed = bool(remote.get("confirmed"))
        record.transition(st.CONFIRMED if confirmed else st.FAILED,
                          error_code=None if confirmed
                          else (remote.get("error_code") or "INTEGRATION_UNAVAILABLE"))
        self.repo.save(record)
        # Settled, so the adapter can be released. Holding it past this point
        # would leak a browser or a session for every resolved execution.
        self._live.pop(execution_id, None)
        self.metrics.incr(obs.SUCCESS_TOTAL if confirmed else obs.FAILURE_TOTAL)
        self.metrics.record(obs.TraceEvent(
            event=obs.CONFIRMED if confirmed else obs.FAILED,
            request_id=record.request_id, execution_id=execution_id,
            detail={"resolved_from": "UNKNOWN"}))
        self.audit.record(AuditEvent(request_id=new_request_id(), execution_id=execution_id,
                                     action="status_lookup",
                                     result="resolved_confirmed" if confirmed
                                     else "resolved_not_applied",
                                     route=record.route,
                                     error_type=None if confirmed else record.error_code,
                                     confirmation_status=record.status))
        return record

    def target_status(self, actor: Actor, execution_id: str) -> dict | None:
        """Read-only: what the target itself recorded, for modes with a durable resolver.

        Never changes the execution and never re-submits anything. Returns None when
        the mode has no such source, and `{"lookup_error": code}` when it cannot be read.
        """
        from procmine.integrations.auth import INSPECT_EXECUTIONS
        authorize(actor, INSPECT_EXECUTIONS)
        record = self.repo.get(execution_id)
        resolver = self.resolvers.get(record.integration_mode) if record else None
        if resolver is None:
            return None
        try:
            return resolver(record)
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            return {"lookup_error": getattr(exc, "code", None) or type(exc).__name__}

    def keep_adapter_for_resolution(self, execution_id: str, prepared: PreparedExecution) -> None:
        """Retain the adapter after an UNKNOWN so its status can still be queried."""
        self._live[execution_id] = prepared
