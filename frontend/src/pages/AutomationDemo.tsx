import { useEffect, useState } from "react";
import { confirm, fetchRoutes, prepare } from "../services/automationService";
import type { EagerBundle } from "../services/dataService";
import { Notice, ProvenancePanel } from "../components/common";
import type { ApiSafeStop, AutomationResultPayload, CheckpointPayload } from "../types";

type LogEntry = { step: string; detail: string; timestamp: string };

type Phase =
  | { kind: "idle" }
  | { kind: "preparing" }
  | { kind: "review"; checkpoint: CheckpointPayload }
  | { kind: "confirming"; checkpoint: CheckpointPayload }
  | { kind: "done"; result: AutomationResultPayload }
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

function SafetyPanel({ entries, confirmed }: { entries: LogEntry[]; confirmed: boolean }) {
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
    { name: "Confirm-time re-verification", done: confirmed, bad: failed("confirm"),
      note: "The button is re-located at confirm time, not clicked from a cached reference" },
  ];

  return (
    <div className="safety">
      {controls.map((c) => (
        <div className="safety-row" key={c.name}>
          <span className={`badge ${c.bad ? "bad" : c.done ? "ok" : "neutral"}`}>
            {c.bad ? "refused" : c.done ? "enforced" : "pending"}
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

export default function AutomationDemo({ bundle }: { bundle: EagerBundle }) {
  const [routes, setRoutes] = useState<string[]>([]);
  const [route, setRoute] = useState("");
  const [noteText, setNoteText] = useState("");
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });

  useEffect(() => {
    fetchRoutes().then((r) => {
      setRoutes(r);
      if (r.length) setRoute(r[0]);
    });
  }, []);

  const busy = phase.kind === "preparing" || phase.kind === "confirming";
  const checkpoint =
    phase.kind === "review" || phase.kind === "confirming" ? phase.checkpoint : null;

  const entries: LogEntry[] =
    phase.kind === "done" ? phase.result.action_log
      : phase.kind === "safe_stop" ? phase.stop.action_log
        : checkpoint ? checkpoint.action_log
          : [];
  const confirmed = phase.kind === "done" && phase.result.confirmed;
  const pending = checkpoint && !confirmed ? ["confirm"] : [];

  async function onPrepare() {
    setPhase({ kind: "preparing" });
    const out = await prepare(route, noteText);
    if (out.kind === "ok") setPhase({ kind: "review", checkpoint: out.data });
    else if (out.kind === "safe_stop") setPhase({ kind: "safe_stop", stop: out.data });
    else if (out.kind === "validation_error") setPhase({ kind: "validation_error", message: out.message });
    else setPhase({ kind: "api_error", message: out.message });
  }

  async function onConfirm() {
    if (!checkpoint) return; // confirmation is impossible without a prepared checkpoint
    setPhase({ kind: "confirming", checkpoint });
    const out = await confirm(checkpoint.checkpoint_token);
    if (out.kind === "ok") setPhase({ kind: "done", result: out.data });
    else if (out.kind === "safe_stop") setPhase({ kind: "safe_stop", stop: out.data });
    else if (out.kind === "validation_error") setPhase({ kind: "validation_error", message: out.message });
    else setPhase({ kind: "api_error", message: out.message });
  }

  return (
    <>
      <header>
        <h2>HR / Payroll Automation Demo</h2>
        <p className="lede">
          Runs the existing Python prototype against its mock HR application. The browser holds no
          automation state: route validation, note validation, element checks and confirm-time
          re-verification all execute server-side in <span className="mono">procmine.automation</span>.
        </p>
      </header>

      <Notice kind="info">
        <strong>Prototype, not production.</strong> This drives a deterministic in-memory mock of
        the HR application, not a real system. No API integration was ever evidenced in the logs,
        and none is simulated here.
      </Notice>

      {routes.length === 0 ? (
        <Notice kind="warn">
          Automation API not reachable. Start it with{" "}
          <span className="mono">python scripts/serve_hr_demo_api.py</span>, then reload. The other
          four screens work without it.
        </Notice>
      ) : null}

      <section className="panel" aria-labelledby="ad-prepare">
        <h3 id="ad-prepare">1 · Prepare submission</h3>
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
        <div className="controls">
          <button className="btn primary" onClick={onPrepare} disabled={busy || routes.length === 0}>
            {phase.kind === "preparing" ? "Preparing…" : "Prepare"}
          </button>
          <button className="btn" onClick={() => setPhase({ kind: "idle" })} disabled={busy}>
            Reset
          </button>
          <span className="small muted">
            Prepare navigates, verifies the field and button, and inserts the note. It never clicks
            confirm.
          </span>
        </div>
      </section>

      <section className="panel" aria-labelledby="ad-steps">
        <h3 id="ad-steps">2 · What the prototype actually did</h3>
        {entries.length ? (
          <Timeline entries={entries} pending={pending} />
        ) : (
          <p className="muted small">No run yet. The timeline mirrors the backend action log exactly.</p>
        )}
      </section>

      <section className="panel" aria-labelledby="ad-safety">
        <h3 id="ad-safety">Automation safety</h3>
        <SafetyPanel entries={entries} confirmed={confirmed} />
      </section>

      <section className="panel" aria-labelledby="ad-review">
        <h3 id="ad-review">3 · Human review checkpoint</h3>
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
              <button className="btn danger" onClick={() => setPhase({ kind: "idle" })} disabled={busy}>
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
        <h3 id="ad-outcome">4 · Outcome</h3>
        {phase.kind === "done" ? (
          <>
            <div className="completed">
              <span className="badge ok">Automation completed</span>
              <div className="grid cols-3" style={{ marginTop: 12 }}>
                <div className="metric">
                  <div className="label">Route</div>
                  <div className="value mono" style={{ fontSize: 14 }}>{phase.result.route}</div>
                </div>
                <div className="metric">
                  <div className="label">Confirmed</div>
                  <div className="value">{String(phase.result.confirmed)}</div>
                </div>
                <div className="metric">
                  <div className="label">Actions recorded</div>
                  <div className="value">{phase.result.action_log.length}</div>
                  <div className="hint">entries in the backend action log</div>
                </div>
              </div>
            </div>
            <p className="small muted" style={{ marginTop: 12 }}>
              The action log above is the prototype&rsquo;s own record of what it did. It is shown
              verbatim; the frontend adds no claims about actions it cannot observe.
            </p>
          </>
        ) : phase.kind === "safe_stop" ? (
          <>
            <Notice kind="warn">
              <strong>Safe stop — {phase.stop.error_type}.</strong> {phase.stop.message}
            </Notice>
            <p className="small muted">
              The prototype refused to proceed rather than guessing or retrying. This is the
              designed behaviour, not a crash.
            </p>
          </>
        ) : phase.kind === "validation_error" ? (
          <Notice kind="error"><strong>Request rejected.</strong> {phase.message}</Notice>
        ) : phase.kind === "api_error" ? (
          <Notice kind="error"><strong>API error.</strong> {phase.message}</Notice>
        ) : (
          <p className="muted small">No run yet.</p>
        )}
      </section>

      <ProvenancePanel
        meta={bundle.meta}
        entries={[{ value: "Evidenced routes and dominant path", sourceKey: "hr_dominant_path" }]}
      />
    </>
  );
}
