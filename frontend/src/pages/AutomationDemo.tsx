import { useEffect, useState } from "react";
import { PageHeader } from "../components/PageHeader";
import {
  confirm, fetchExecutionStatus, fetchIntegrationModes, fetchRoutes, prepare,
} from "../services/automationService";
import type { EagerBundle } from "../services/dataService";
import { Notice, ProvenancePanel } from "../components/common";
import { EvidenceBadge } from "../components/evidence";
import type {
  ApiSafeStop, AutomationResultPayload, CheckpointPayload, ExecutionStatus,
  ExecutionStatusPayload, IntegrationMode, IntegrationModesPayload, TargetStatusView,
} from "../types";

type LogEntry = { step: string; detail: string; timestamp: string };

type Phase =
  | { kind: "idle" }
  | { kind: "preparing" }
  | { kind: "review"; checkpoint: CheckpointPayload }
  | { kind: "confirming"; checkpoint: CheckpointPayload }
  | { kind: "done"; result: AutomationResultPayload }
  /** The confirmation may or may not have landed. Not a success, not a failure.
   *  `transportLost` marks the case where no usable response arrived at all, as
   *  opposed to the server explicitly reporting an uncertain outcome (HTTP 202). */
  | { kind: "unknown"; result: AutomationResultPayload; transportLost?: boolean }
  | { kind: "safe_stop"; stop: ApiSafeStop }
  | { kind: "validation_error"; message: string }
  | { kind: "api_error"; message: string };

/** Human-readable names for the steps the backend actually emits. Any step the
 *  backend reports that is not in this map is shown under its raw name rather
 *  than dropped, so the timeline can never diverge from the real action log. */
const STEP_LABELS: Record<string, string> = {
  route_check: "Validate route",
  note_check: "Validate note text",
  navigate: "Navigate to route",
  find_note_field: "Verify note field",
  insert_note: "Insert note",
  find_confirm_button: "Verify confirm button",
  checkpoint: "Human review checkpoint",
  confirm: "Confirm submission",
};

/** Rendered as the machine state, underscores softened. The vocabulary is the
 *  server's state machine; the UI does not invent a friendlier one that could
 *  drift from it. */
function statusLabel(status: ExecutionStatus): string {
  return status.replace(/_/g, " ");
}

function statusTone(status: ExecutionStatus): "ok" | "bad" | "neutral" {
  if (status === "CONFIRMED") return "ok";
  if (status === "FAILED" || status === "REPLAYED") return "bad";
  return "neutral";
}

/** Whether the confirmation was applied. The target's own record wins when the server
 *  reports one (local HTTP integration); otherwise it follows from the execution state,
 *  which only reads FAILED once the change is known not to have been applied. */
function confirmationState(status: ExecutionStatus | undefined,
                           target: TargetStatusView | null | undefined): string {
  if (target?.confirmation_state) {
    return `${target.confirmation_state.replace(/_/g, " ")} (HR system)`;
  }
  switch (status) {
    case "AWAITING_CONFIRMATION": return "not submitted";
    case "CONFIRMING": return "submitting";
    case "CONFIRMED": return "confirmed";
    case "FAILED": return "not applied";
    case "UNKNOWN": return "unknown — check status";
    default: return "—";
  }
}

/** The targets that accept a deterministic, selected failure. */
function failureOptions(mode: IntegrationMode, modes: IntegrationModesPayload): string[] {
  if (mode === "api_simulator") return modes.failure_modes;
  if (mode === "http") return modes.http_failure_modes ?? [];
  return [];
}

function entryState(e: LogEntry): "ok" | "bad" | "hold" {
  const d = e.detail.toUpperCase();
  if (d.includes("REJECTED") || d.includes("FAILED")) return "bad";
  if (e.step === "checkpoint") return "hold";
  return "ok";
}

function Timeline({ entries, pending }: { entries: LogEntry[]; pending: string[] }) {
  if (!entries.length && !pending.length) return null;
  return (
    <ol className="timeline" aria-label="Automation step timeline">
      {entries.map((e, i) => {
        const state = entryState(e);
        return (
          <li key={`${e.step}-${i}`} className={`tl ${state}`}>
            <span className="tl-mark" aria-hidden="true">
              {state === "ok" ? "✓" : state === "bad" ? "✕" : "⚠"}
            </span>
            <span className="tl-body">
              <span className="tl-name">{STEP_LABELS[e.step] ?? e.step}</span>
              <span className="tl-detail mono small">{e.detail}</span>
            </span>
          </li>
        );
      })}
      {pending.map((step) => (
        <li key={`pending-${step}`} className="tl pending">
          <span className="tl-mark" aria-hidden="true">○</span>
          <span className="tl-body">
            <span className="tl-name">{STEP_LABELS[step] ?? step}</span>
            <span className="tl-detail small muted">not yet performed</span>
          </span>
        </li>
      ))}
    </ol>
  );
}

/** How the confirmation row reads when its outcome was not known at confirm time. */
type ConfirmOutcome = "unknown" | "enforced" | "not applied";

function SafetyPanel({ entries, confirmed, confirmOutcome }: {
  entries: LogEntry[]; confirmed: boolean; confirmOutcome?: ConfirmOutcome;
}) {
  const has = (step: string) => entries.some((e) => e.step === step);
  const failed = (step: string) =>
    entries.some((e) => e.step === step && entryState(e) === "bad");

  const controls = [
    { name: "Route validation", done: has("route_check"), bad: failed("route_check"),
      note: "Only the evidenced routes are accepted" },
    { name: "Note validation", done: has("note_check"), bad: failed("note_check"),
      note: "Empty or whitespace-only notes are refused" },
    { name: "DOM verification", done: has("find_note_field") && has("find_confirm_button"),
      bad: failed("find_note_field") || failed("find_confirm_button"),
      note: "Exactly one note field and one confirm button must exist" },
    { name: "Human review checkpoint", done: has("checkpoint"), bad: false,
      note: "Prepared and held; the button is never clicked by prepare" },
    confirmOutcome
      // The click was attempted and its result was lost: "refused" would be a guess.
      ? { name: "Confirm-time re-verification", done: confirmOutcome === "enforced",
          bad: confirmOutcome === "not applied", label: confirmOutcome,
          note: confirmOutcome === "unknown"
            ? "The confirmation's outcome is unknown — settled by status lookup, never by a retry"
            : "Settled by status lookup against the target, without re-submitting" }
      : { name: "Confirm-time re-verification", done: confirmed, bad: failed("confirm"),
          note: "The button is re-located at confirm time, not clicked from a cached reference" },
  ];

  return (
    <div className="safety">
      {controls.map((c) => (
        <div className="safety-row" key={c.name}>
          <span className={`badge ${c.bad ? "bad" : c.done ? "ok" : "neutral"}`}>
            {"label" in c && c.label ? c.label
              : c.bad ? "refused" : c.done ? "enforced" : "pending"}
          </span>
          <span className="safety-name">{c.name}</span>
          <span className="small muted">{c.note}</span>
        </div>
      ))}
      <p className="small muted" style={{ marginBottom: 0 }}>
        Every control above is executed by <span className="mono">procmine.automation</span> on the
        server. The browser holds no automation state and cannot skip a control.
      </p>
    </div>
  );
}

type StepState = "done" | "current" | "pending" | "review" | "stopped" | "unknown";

const STEP_STATE_TEXT: Record<StepState, string> = {
  done: "done",
  current: "in progress",
  pending: "not started",
  review: "REVIEW REQUIRED",
  stopped: "SAFE STOP",
  unknown: "OUTCOME UNKNOWN",
};

/** Where the operator is in the five-step flow. Derived only from the UI phase and
 *  the action log the server returned; it never claims a step the server did not do. */
function stepStates(phase: Phase, entries: LogEntry[]): StepState[] {
  const held = entries.some((e) => e.step === "checkpoint");
  switch (phase.kind) {
    case "idle": return ["current", "current", "pending", "pending", "pending"];
    case "preparing": return ["done", "done", "current", "pending", "pending"];
    case "review": return ["done", "done", "review", "pending", "pending"];
    case "confirming": return ["done", "done", "done", "current", "pending"];
    case "done": return ["done", "done", "done", "done", "done"];
    case "unknown": return ["done", "done", "done", "unknown", "current"];
    case "safe_stop":
      return held
        ? ["done", "done", "done", "stopped", "pending"]
        : ["done", "done", "stopped", "pending", "pending"];
    default: return ["done", "done", "stopped", "pending", "pending"];
  }
}

const STEP_NAMES = ["Select route", "Enter note", "Review", "Confirm", "Audit result"];

export default function AutomationDemo({ bundle }: { bundle: EagerBundle }) {
  const [routes, setRoutes] = useState<string[]>([]);
  const [route, setRoute] = useState("");
  const [noteText, setNoteText] = useState("");
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });

  // --- Day-5 integration boundary -----------------------------------------
  const [modes, setModes] = useState<IntegrationModesPayload | null>(null);
  const [integrationMode, setIntegrationMode] = useState<IntegrationMode>("mock");
  const [failureMode, setFailureMode] = useState("SUCCESS");
  const [loseResponse, setLoseResponse] = useState(false);
  const [execStatus, setExecStatus] = useState<ExecutionStatusPayload | null>(null);
  const [checking, setChecking] = useState(false);

  useEffect(() => {
    fetchRoutes().then((r) => {
      setRoutes(r);
      if (r.length) setRoute(r[0]);
    });
    fetchIntegrationModes().then(setModes);
  }, []);

  const busy = phase.kind === "preparing" || phase.kind === "confirming";
  const checkpoint =
    phase.kind === "review" || phase.kind === "confirming" ? phase.checkpoint : null;

  const entries: LogEntry[] =
    phase.kind === "done" || phase.kind === "unknown" ? phase.result.action_log
      : phase.kind === "safe_stop" ? phase.stop.action_log
        : checkpoint ? checkpoint.action_log
          : [];
  const confirmed = phase.kind === "done" && phase.result.confirmed;
  const pending = checkpoint && !confirmed ? ["confirm"] : [];

  /** Whichever payload currently describes the execution. Every Day-5 field is
   *  optional, so this stays undefined against an API that does not send them. */
  const execution: { execution_id?: string; status?: ExecutionStatus;
                     integration_mode?: IntegrationMode } | null =
    checkpoint ? checkpoint
      : phase.kind === "done" || phase.kind === "unknown" ? phase.result
        : phase.kind === "safe_stop" ? phase.stop
          : null;
  const executionId = execution?.execution_id;
  // A status looked up from the server wins over the one carried by the response
  // that created the execution -- that is the whole point of looking it up.
  const currentStatus: ExecutionStatus | undefined =
    execStatus?.status ?? execution?.status;
  const activeMode = execution?.integration_mode ?? integrationMode;
  const modeLabel =
    modes?.modes.find((m) => m.id === activeMode)?.label ?? "LOCAL target";
  const lastAction = phase.kind === "done"
    ? phase.result.action_log[phase.result.action_log.length - 1] ?? null
    : null;

  const steps = stepStates(phase, entries);
  const hrProcessId = bundle.hrPayroll.dominant_path?.hr_process_id;
  const targetRank = bundle.opportunities.ranking.find((r) => r.process_id === hrProcessId) ?? null;
  const targetName = targetRank?.readable_name ?? "HR / Payroll";
  const scopeRoutes = Object.keys(bundle.hrPayroll.dominant_path?.route_id_prefix_correspondence ?? {});
  const hrSplit = bundle.hrPayroll.variant_split;
  const hrTotal = bundle.hrPayroll.dominant_path?.n_hr_executions_total;

  /** Bring the held checkpoint into view; the reviewer should not have to hunt for it. */
  function revealReview() {
    window.setTimeout(() => {
      const panel = document.getElementById("ad-review")?.closest("section");
      const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
      panel?.scrollIntoView?.({ behavior: reduce ? "auto" : "smooth", block: "nearest" });
    }, 0);
  }

  function reset() {
    setPhase({ kind: "idle" });
    setExecStatus(null);
  }

  async function onPrepare() {
    setPhase({ kind: "preparing" });
    setExecStatus(null);
    const usingSimulator = integrationMode === "api_simulator";
    const injectable = modes ? failureOptions(integrationMode, modes).length > 0 : false;
    const out = await prepare(route, noteText, {
      integrationMode,
      failureMode: injectable ? failureMode : undefined,
      loseResponse: usingSimulator ? loseResponse : false,
    });
    if (out.kind === "ok") {
      setPhase({ kind: "review", checkpoint: out.data });
      revealReview();
    }
    else if (out.kind === "safe_stop") setPhase({ kind: "safe_stop", stop: out.data });
    else if (out.kind === "validation_error") setPhase({ kind: "validation_error", message: out.message });
    else setPhase({ kind: "api_error", message: out.message });
  }

  async function onConfirm() {
    if (!checkpoint) return; // confirmation is impossible without a prepared checkpoint
    setPhase({ kind: "confirming", checkpoint });
    const out = await confirm(checkpoint.checkpoint_token);
    if (out.kind === "ok") {
      // HTTP 202 -- the server applied nothing it can vouch for. Not a failure.
      if (out.data.status === "UNKNOWN") setPhase({ kind: "unknown", result: out.data });
      else setPhase({ kind: "done", result: out.data });
    } else if (out.kind === "safe_stop") setPhase({ kind: "safe_stop", stop: out.data });
    else if (out.kind === "validation_error") setPhase({ kind: "validation_error", message: out.message });
    else if (checkpoint.execution_id) {
      // No usable response to a MUTATION is not a failure: the confirmation may have
      // been applied before the connection dropped. Keep the execution id the server
      // issued at prepare time so the outcome can be looked up rather than guessed.
      // Nothing here re-sends the confirmation, and the confirm control stays gone.
      setPhase({
        kind: "unknown",
        transportLost: true,
        result: {
          route: checkpoint.route,
          confirmed: false,
          action_log: checkpoint.action_log,
          execution_id: checkpoint.execution_id,
          status: "UNKNOWN",
          integration_mode: checkpoint.integration_mode,
          error_type: "CONFIRMATION_UNKNOWN",
          message: out.message,
        },
      });
    } else setPhase({ kind: "api_error", message: out.message });
  }

  /** Asks the server what actually happened. It never re-submits the confirmation. */
  async function onCheckStatus() {
    if (!executionId) return;
    setChecking(true);
    const out = await fetchExecutionStatus(executionId);
    setChecking(false);
    if (out.kind === "ok") setExecStatus(out.data);
    else if (out.kind === "api_error") setPhase({ kind: "api_error", message: out.message });
  }

  function stageLostResponseDemo() {
    setIntegrationMode("api_simulator");
    setFailureMode("TIMEOUT");
    setLoseResponse(true);
    reset();
  }

  /** The same journey over real HTTP: the local HR API commits, then drops the response. */
  function stageHttpLostResponseDemo() {
    setIntegrationMode("http");
    setFailureMode("CONFIRM_RESPONSE_LOST");
    setLoseResponse(false);
    reset();
  }

  /** A failure selected for one target means nothing to another, so switching resets it. */
  function changeMode(mode: IntegrationMode) {
    setIntegrationMode(mode);
    setFailureMode("SUCCESS");
    setLoseResponse(false);
  }

  const httpAdvertised = !!modes?.modes.some((m) => m.id === "http");
  const failureChoices = modes ? failureOptions(integrationMode, modes) : [];

  return (
    <>
      <PageHeader
        screen="automation"
        title="HR / Payroll Automation Demo"
        purpose={<>
          Validate a bounded automation flow with human confirmation. The browser holds no
          automation state: route validation, note validation, element checks and confirm-time
          re-verification all execute server-side in{" "}
          <span className="mono">procmine.automation</span>.
        </>}
        context="LOCAL VALIDATED · local target only — not a real HR system"
      />

      <Notice kind="info">
        <strong>Prototype, not production.</strong> Every target below is local: a deterministic
        in-memory mock, a browser driving the committed local prototype page, an in-process
        simulator of an external REST service, or a local HTTP integration with a separate local
        HR API simulator. No API integration was ever evidenced in the logs — the simulators exist
        to exercise integration failure handling, and are <strong>not</strong>{" "}
        a claim that the real HR system has an API.
      </Notice>

      <section className="panel scope-strip" aria-labelledby="ad-scope">
        <div className="panel-head">
          <h3 id="ad-scope">Target and scope</h3>
          <EvidenceBadge kind="prototype" label="LOCAL PROTOTYPE" />
        </div>
        <dl className="record-grid compact">
          <div className="record-cell">
            <dt>Target process</dt>
            <dd className="record-main">{targetName}</dd>
            <dd className="record-note">{targetRank ? `Rank ${targetRank.rank} · Opportunity ${targetRank.opportunity.toFixed(4)}` : "selected on Day 3"}</dd>
          </div>
          <div className="record-cell">
            <dt>Automation scope</dt>
            <dd className="record-main">{scopeRoutes.length} evidenced routes</dd>
            <dd className="record-note">
              dominant path only{hrSplit?.dominant ? ` · ${hrSplit.dominant.n} of ${hrTotal} executions` : ""}
            </dd>
          </div>
          <div className="record-cell">
            <dt>Human boundary</dt>
            <dd className="record-main">Review before every confirmation</dd>
            <dd className="record-note">Word detours and rare cases stay manual</dd>
          </div>
          <div className="record-cell">
            <dt>Target system</dt>
            <dd className="record-main">Local only</dd>
            <dd className="record-note">not a real HR system</dd>
          </div>
        </dl>
      </section>

      <ol className="stepper" aria-label="Demo steps">
        {STEP_NAMES.map((name, i) => {
          const state = steps[i];
          return (
            <li key={name} className={`stepper-item is-${state}`} aria-current={state === "current" || state === "review" ? "step" : undefined}>
              <span className="stepper-n mono">STEP {i + 1}</span>
              <span className="stepper-label">{name}</span>
              <span className="stepper-state">{STEP_STATE_TEXT[state]}</span>
            </li>
          );
        })}
      </ol>

      {routes.length === 0 ? (
        <Notice kind="warn">
          Automation API not reachable. Start it with{" "}
          <span className="mono">python scripts/serve_hr_demo_api.py</span>, then reload. The other
          four screens work without it.
        </Notice>
      ) : null}

      <section className="panel" aria-labelledby="ad-prepare">
        <h3 id="ad-prepare">Steps 1–2 · Select a route and enter the note</h3>
        <div className="grid cols-2">
          <label className="field">
            <span>Route (evidenced routes only)</span>
            <select value={route} onChange={(e) => setRoute(e.target.value)}
              disabled={busy || routes.length === 0} aria-label="Route">
              {routes.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </label>
          <label className="field">
            <span>Note text (you must supply this)</span>
            <textarea value={noteText} onChange={(e) => setNoteText(e.target.value)}
              disabled={busy} placeholder="Type the note to insert…" aria-label="Note text" />
          </label>
        </div>

        {modes ? (
          <div className="grid cols-2" style={{ marginTop: 12 }}>
            <label className="field">
              <span>Integration target</span>
              <select value={integrationMode} disabled={busy} aria-label="Integration mode"
                onChange={(e) => changeMode(e.target.value as IntegrationMode)}>
                {modes.modes.map((m) => (
                  <option key={m.id} value={m.id}>{m.label}</option>
                ))}
              </select>
              <span className="hint">
                The automation service is identical for every target. Only the adapter differs.
              </span>
            </label>
            {failureChoices.length ? (
              <label className="field">
                <span>
                  {integrationMode === "http" ? "Local HR API behaviour" : "Simulated service response"}
                </span>
                <select value={failureMode} disabled={busy} aria-label="Failure mode"
                  onChange={(e) => setFailureMode(e.target.value)}>
                  {failureChoices.map((f) => <option key={f} value={f}>{f}</option>)}
                </select>
                {integrationMode === "api_simulator" ? (
                  <label className="small" style={{ display: "block", marginTop: 6 }}>
                    <input type="checkbox" checked={loseResponse} disabled={busy}
                      onChange={(e) => setLoseResponse(e.target.checked)} />{" "}
                    Service applies the change, then the response is lost
                  </label>
                ) : null}
              </label>
            ) : null}
          </div>
        ) : null}

        {integrationMode === "http" ? (
          <p className="small" role="note" aria-label="Local HTTP integration" style={{ marginBottom: 0 }}>
            <span className="badge neutral">Local HTTP integration</span>{" "}
            Every call travels over HTTP to the separate local HR API server, which keeps its state
            in SQLite and treats the execution ID as the identity of the action. It is a local
            simulator of an HR system — not a real HR system, and not a deployed one.
          </p>
        ) : null}

        <div className="controls">
          <button className="btn primary" onClick={onPrepare} disabled={busy || routes.length === 0}>
            {phase.kind === "preparing" ? "Preparing…" : "Prepare"}
          </button>
          <button className="btn" onClick={reset} disabled={busy}>
            Reset
          </button>
          {modes ? (
            <button className="btn" onClick={stageLostResponseDemo} disabled={busy}>
              Stage lost-response demo
            </button>
          ) : null}
          {httpAdvertised ? (
            <button className="btn" onClick={stageHttpLostResponseDemo} disabled={busy}>
              Stage HTTP lost-response demo
            </button>
          ) : null}
          <span className="small muted">
            Prepare navigates, verifies the field and button, and inserts the note. It never clicks
            confirm.
          </span>
        </div>
        {modes ? (
          <p className="small muted" style={{ marginBottom: 0 }}>
            Failures are <strong>selected, never random</strong>, so every outcome on this screen is
            reproducible. {modes.note}
          </p>
        ) : null}
      </section>

      {executionId || currentStatus ? (
        <section className="panel" aria-labelledby="ad-execution">
          <h3 id="ad-execution">Execution</h3>
          <div className="grid cols-4">
            <div className="metric">
              <div className="label">Execution ID</div>
              <div className="value mono wrap-any" style={{ fontSize: 13 }}>{executionId ?? "—"}</div>
              <div className="hint">issued server-side; survives a lost response</div>
            </div>
            <div className="metric">
              <div className="label">Status</div>
              <div className="value">
                {currentStatus ? (
                  <span className={`badge ${statusTone(currentStatus)}`}>
                    {statusLabel(currentStatus)}
                  </span>
                ) : "—"}
              </div>
            </div>
            <div className="metric">
              <div className="label">Confirmation state</div>
              <div className="value" style={{ fontSize: 13 }}>
                {confirmationState(currentStatus, execStatus?.target)}
              </div>
              <div className="hint">
                {execStatus?.target?.confirmation_state
                  ? "as recorded by the local HR API"
                  : "from the execution state"}
              </div>
            </div>
            <div className="metric">
              <div className="label">Integration mode</div>
              <div className="value" style={{ fontSize: 13 }}>{modeLabel}</div>
            </div>
          </div>
          {execStatus?.target ? (
            <p className="small muted" style={{ marginTop: 10, marginBottom: 0 }}>
              {execStatus.target.lookup_error ? (
                <>
                  Status lookup: the local HR API could not be reached (
                  <span className="mono">{execStatus.target.lookup_error}</span>).
                </>
              ) : (
                <>
                  Status lookup: the local HR API holds{" "}
                  <span className="mono">{execStatus.target.state ?? "no record"}</span>
                  {typeof execStatus.target.commit_count === "number"
                    ? <> · commits applied <span className="mono">{execStatus.target.commit_count}</span></>
                    : null}
                  {execStatus.target.last_error_type
                    ? <> · last refusal <span className="mono">{execStatus.target.last_error_type}</span></>
                    : null}
                  .
                </>
              )}
            </p>
          ) : null}
        </section>
      ) : null}

      <section className={`panel${checkpoint ? " is-review" : ""}`} aria-labelledby="ad-review">
        <div className="panel-head">
          <h3 id="ad-review">Steps 3–4 · Human review, then confirm</h3>
          {checkpoint ? <span className="review-flag">REVIEW REQUIRED</span> : null}
        </div>
        {checkpoint ? (
          <>
            <Notice kind="warn">
              Nothing has been confirmed yet. The confirm button was located and verified but{" "}
              <strong>not clicked</strong>. Review below, then decide.
            </Notice>
            <div className="grid cols-4">
              <div className="metric">
                <div className="label">Route</div>
                <div className="value mono" style={{ fontSize: 14 }}>{checkpoint.route}</div>
              </div>
              <div className="metric">
                <div className="label">Note field</div>
                <div className="value mono" style={{ fontSize: 14 }}>{checkpoint.note_field_id}</div>
              </div>
              <div className="metric">
                <div className="label">Confirm target</div>
                <div className="value mono" style={{ fontSize: 14 }}>{checkpoint.confirm_button_id}</div>
                <div className="hint">re-verified at confirm time</div>
              </div>
              <div className="metric">
                <div className="label">Confirmed</div>
                <div className="value">{checkpoint.confirmed ? "Yes" : "No"}</div>
              </div>
            </div>
            <p className="small muted" style={{ marginTop: 10 }}>Note to be submitted:</p>
            <p className="mono wrap-any" style={{ margin: "4px 0 12px" }}>“{checkpoint.note_text}”</p>
            <div className="controls">
              <button className="btn primary" onClick={onConfirm} disabled={busy}>
                {phase.kind === "confirming" ? "Confirming…" : "Approve and confirm"}
              </button>
              <button className="btn danger" onClick={reset} disabled={busy}>
                Discard
              </button>
            </div>
          </>
        ) : (
          <p className="muted small">
            No checkpoint prepared. Confirmation is impossible until Prepare succeeds — the
            frontend has no path to confirm without a server-issued checkpoint token.
          </p>
        )}
      </section>

      <section className="panel" aria-labelledby="ad-outcome">
        <h3 id="ad-outcome">Step 5 · Audit result</h3>
        {phase.kind === "done" ? (
          <>
            <div className="completed">
              <span className="badge ok">Automation completed</span>
              <dl className="kv" style={{ marginTop: 12 }}>
                <div>
                  <dt>Execution ID</dt>
                  <dd className="mono wrap-any">{phase.result.execution_id ?? "not issued by this API version"}</dd>
                </div>
                <div>
                  <dt>Status</dt>
                  <dd className="mono">{phase.result.status ?? (phase.result.confirmed ? "confirmed" : "not confirmed")}</dd>
                </div>
                <div>
                  <dt>Route</dt>
                  <dd className="mono">{phase.result.route}</dd>
                </div>
                <div>
                  <dt>Confirmed</dt>
                  <dd className="mono">{String(phase.result.confirmed)}</dd>
                </div>
                <div>
                  <dt>Actions recorded</dt>
                  <dd className="mono">{phase.result.action_log.length}</dd>
                </div>
                <div>
                  <dt>Audit event</dt>
                  <dd className="mono wrap-any">
                    {lastAction ? `${lastAction.step}: ${lastAction.detail}` : "—"}
                  </dd>
                </div>
              </dl>
            </div>
            <p className="small muted" style={{ marginTop: 12 }}>
              The action log above is the prototype&rsquo;s own record of what it did. It is shown
              verbatim; the frontend adds no claims about actions it cannot observe. The server also
              keeps a redacted audit trail: the note length is stored, never the note itself.
            </p>
          </>
        ) : phase.kind === "unknown" ? (
          <>
            <Notice kind="warn">
              <strong>Confirmation status unknown — check execution status.</strong>{" "}
              {phase.transportLost
                ? "No response was received for the confirmation, so this client cannot tell "
                  + "whether it reached the server or was applied."
                : "The server reports that the outcome at the target was not confirmed, so this "
                  + "client cannot tell whether the change was applied."}
            </Notice>
            <p className="small muted">
              The confirmation is <strong>not</strong> retried automatically. Retrying a mutation
              whose outcome is unknown is how a duplicate payroll change happens. Instead, ask the
              server what actually occurred.
            </p>
            <div className="controls">
              <button className="btn primary" onClick={onCheckStatus} disabled={checking || !executionId}>
                {checking ? "Checking…" : "Check status"}
              </button>
              <button className="btn" onClick={reset} disabled={checking}>Reset</button>
            </div>
            {execStatus ? (
              <>
                <p className="small" style={{ marginTop: 12 }}>
                  {execStatus.status === "AWAITING_CONFIRMATION" ? (
                    <>
                      Server status{" "}
                      <span className={`badge ${statusTone(execStatus.status)}`}>
                        {statusLabel(execStatus.status)}
                      </span>{" "}
                      — the confirmation never reached the server, so nothing was applied. To
                      proceed, prepare a new submission; it goes through human review again.
                    </>
                  ) : execStatus.status === "UNKNOWN" && execStatus.target?.in_progress ? (
                    <>
                      Still{" "}
                      <span className={`badge ${statusTone(execStatus.status)}`}>
                        {statusLabel(execStatus.status)}
                      </span>{" "}
                      — the HR system reports this confirmation as still in progress, so it cannot
                      be settled yet. Check again shortly; nothing was re-submitted.
                    </>
                  ) : execStatus.status === "UNKNOWN" && execStatus.target?.lookup_error ? (
                    <>
                      Still{" "}
                      <span className={`badge ${statusTone(execStatus.status)}`}>
                        {statusLabel(execStatus.status)}
                      </span>{" "}
                      — the status source could not be reached, so the outcome remains unknown.
                      Nothing was re-submitted; check again once the HR system is reachable.
                    </>
                  ) : execStatus.status === "UNKNOWN" ? (
                    <>
                      Still{" "}
                      <span className={`badge ${statusTone(execStatus.status)}`}>
                        {statusLabel(execStatus.status)}
                      </span>{" "}
                      — this target exposes no status source, so the outcome cannot be
                      established from here. Check the target system directly before acting again.
                    </>
                  ) : (
                    <>
                      Resolved to{" "}
                      <span className={`badge ${statusTone(execStatus.status)}`}>
                        {statusLabel(execStatus.status)}
                      </span>{" "}
                      {execStatus.resolved_from_unknown
                        ? "by querying the target, without re-submitting the confirmation."
                        : "— the server had already recorded this outcome; nothing was re-submitted."}
                    </>
                  )}
                </p>
                <p className="small muted">
                  The server stored the note length ({execStatus.note_length} characters) and never
                  the note content.
                </p>
              </>
            ) : null}
          </>
        ) : phase.kind === "safe_stop" ? (
          <>
            <p style={{ margin: "0 0 8px" }}><span className="status-tag st-safe">SAFE STOP</span></p>
            <Notice kind="warn">
              <strong>Safe stop — {phase.stop.error_type}.</strong> {phase.stop.message}
            </Notice>
            <p className="small muted">
              The prototype refused to proceed rather than guessing or retrying. This is the
              designed behaviour, not a crash.
            </p>
          </>
        ) : phase.kind === "validation_error" ? (
          <>
            <p style={{ margin: "0 0 8px" }}><span className="status-tag st-safe">SAFE STOP</span></p>
            <Notice kind="warn"><strong>Request rejected.</strong> {phase.message}</Notice>
          </>
        ) : phase.kind === "api_error" ? (
          <Notice kind="error"><strong>API error.</strong> {phase.message}</Notice>
        ) : (
          <p className="muted small">No run yet.</p>
        )}

        {executionId && phase.kind !== "unknown" ? (
          <div className="controls" style={{ marginTop: 12 }}>
            <button className="btn" onClick={onCheckStatus} disabled={checking}>
              {checking ? "Checking…" : "Check status"}
            </button>
            <span className="small muted">
              Queries <span className="mono">GET /api/executions/{"{id}"}/status</span>. A lookup
              never re-submits the confirmation.
            </span>
          </div>
        ) : null}
        {execStatus && phase.kind !== "unknown" ? (
          <p className="small muted" style={{ marginTop: 8 }}>
            Server-reported status:{" "}
            <span className="mono">{execStatus.status}</span>
            {execStatus.error_code ? <> · <span className="mono">{execStatus.error_code}</span></> : null}
          </p>
        ) : null}
      </section>

      <section className="panel" aria-labelledby="ad-steps">
        <h3 id="ad-steps">Automated actions — the backend action log</h3>
        {entries.length ? (
          <Timeline entries={entries} pending={pending} />
        ) : (
          <p className="muted small">No run yet. The timeline mirrors the backend action log exactly.</p>
        )}
      </section>

      <section className="panel" aria-labelledby="ad-safety">
        <h3 id="ad-safety">Automation safety</h3>
        <SafetyPanel entries={entries} confirmed={confirmed}
          confirmOutcome={phase.kind !== "unknown" ? undefined
            : execStatus?.status === "CONFIRMED" ? "enforced"
              : execStatus?.status === "FAILED" ? "not applied"
                : "unknown"} />
      </section>

      <ProvenancePanel
        meta={bundle.meta}
        entries={[{ value: "Evidenced routes and dominant path", sourceKey: "hr_dominant_path" }]}
      />
    </>
  );
}
