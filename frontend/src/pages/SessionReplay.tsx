import { useEffect, useMemo, useRef, useState } from "react";
import type { EagerBundle } from "../services/dataService";
import { loadSessionExecutions } from "../services/dataService";
import type { Execution } from "../types";
import { EmptyState, HealthBadge, Notice, ProvenancePanel } from "../components/common";
import { formatDuration, formatOffset, formatTimestamp } from "../utils/format";
import type { NavParams } from "../navigation";

const SPEEDS = [0.5, 1, 2, 4];

export default function SessionReplay({
  bundle,
  navParams,
  navNonce,
}: {
  bundle: EagerBundle;
  navParams: NavParams;
  navNonce: number;
}) {
  const { meta, sessions, executionsIndex } = bundle;

  const datasetBSessions = useMemo(
    () => sessions.filter((s) => s.dataset === "dataset_b"),
    [sessions],
  );

  const [sessionQuery, setSessionQuery] = useState("");
  const [degradedOnly, setDegradedOnly] = useState(false);
  const [processFilter, setProcessFilter] = useState("");
  const [sessionId, setSessionId] = useState<string>("");
  const [executions, setExecutions] = useState<Execution[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [executionId, setExecutionId] = useState<string>("");

  // Cross-screen intents: preselect a session, or open filtered to degraded.
  useEffect(() => {
    if (navParams.degradedOnly) {
      setDegradedOnly(true);
      setSessionQuery("");
    }
    if (navParams.sessionId) {
      setSessionId(navParams.sessionId);
      setSessionQuery("");
      setDegradedOnly(false);
    }
  }, [navParams.sessionId, navParams.degradedOnly, navNonce]);

  // A deep-linked execution is applied once its session file has loaded.
  useEffect(() => {
    if (!navParams.executionId || !executions) return;
    if (executions.some((e) => e.execution_id === navParams.executionId)) {
      setExecutionId(navParams.executionId);
    }
  }, [navParams.executionId, executions, navNonce]);

  const visibleSessions = useMemo(() => {
    const q = sessionQuery.trim().toLowerCase();
    return datasetBSessions.filter((s) => {
      if (degradedOnly && s.status !== "degraded") return false;
      if (!q) return true;
      return (
        s.session_id.toLowerCase().includes(q) || s.operator.toLowerCase().includes(q)
      );
    });
  }, [datasetBSessions, sessionQuery, degradedOnly]);

  // Lazy load: only when a session is actually selected.
  useEffect(() => {
    if (!sessionId) {
      setExecutions(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    setExecutionId("");
    loadSessionExecutions(sessionId)
      .then((rows) => { if (!cancelled) setExecutions(rows); })
      .catch((err: Error) => { if (!cancelled) setLoadError(err.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [sessionId]);

  const sessionRow = datasetBSessions.find((s) => s.session_id === sessionId);
  const sessionRows = useMemo(
    () => executionsIndex.filter((r) => r.session_id === sessionId),
    [executionsIndex, sessionId],
  );
  const processOptions = useMemo(
    () => [...new Set(sessionRows.map((r) => r.process_readable_name ?? r.dominant_context))].sort(),
    [sessionRows],
  );
  const indexRows = useMemo(
    () => sessionRows.filter((r) =>
      !processFilter || (r.process_readable_name ?? r.dominant_context) === processFilter),
    [sessionRows, processFilter],
  );

  const execution = useMemo(
    () => executions?.find((e) => e.execution_id === executionId) ?? null,
    [executions, executionId],
  );
  const steps = execution?.ordered_steps ?? [];

  // --- step-level playback ------------------------------------------------
  const [cursor, setCursor] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const timer = useRef<number | null>(null);

  useEffect(() => { setCursor(0); setPlaying(false); }, [executionId]);
  useEffect(() => { setProcessFilter(""); }, [sessionId]);

  useEffect(() => {
    if (!playing || steps.length === 0) return;
    if (cursor >= steps.length - 1) { setPlaying(false); return; }
    const current = steps[cursor];
    const next = steps[cursor + 1];
    const realGap = Math.max(0, next.start_ms - current.start_ms);
    const delay = Math.min(2000, Math.max(120, realGap)) / speed;
    timer.current = window.setTimeout(() => setCursor((c) => c + 1), delay);
    return () => { if (timer.current) window.clearTimeout(timer.current); };
  }, [playing, cursor, steps, speed]);

  return (
    <>
      <header>
        <h2>Execution Step Replay</h2>
        <p className="lede">
          Step-level replay of recovered Dataset-B executions. Each row below is a persisted{" "}
          <span className="mono">ordered_steps</span> entry covering one or more raw events — this
          is <strong>not</strong> an individual-event replay, and no raw event stream exists in the
          data bundle.
        </p>
      </header>

      <Notice kind="info">
        <strong>Data availability.</strong> Dataset A has no replay view. Its locked segmentation
        pipeline is evaluated but never serialises predicted boundaries, so replaying it would
        require changing that pipeline. Dataset A appears on the Dashboard as aggregate metrics
        and instrumentation health only.
      </Notice>

      <section className="panel" aria-labelledby="sr-select">
        <h3 id="sr-select">Select a session</h3>
        <div className="controls" style={{ marginBottom: 12 }}>
          <input
            type="text"
            value={sessionQuery}
            onChange={(e) => setSessionQuery(e.target.value)}
            placeholder="Search session id or operator…"
            aria-label="Search sessions"
            style={{ maxWidth: 320 }}
          />
          <button
            className="btn"
            aria-pressed={degradedOnly}
            onClick={() => setDegradedOnly((v) => !v)}
            style={degradedOnly ? { borderColor: "var(--bad)" } : undefined}
          >
            Degraded instrumentation only
          </button>
          <span className="small muted">
            Showing {visibleSessions.length} of {datasetBSessions.length} Dataset-B sessions
          </span>
        </div>

        <div className="grid cols-2">
          <label className="field">
            <span>Session</span>
            <select value={sessionId} onChange={(e) => setSessionId(e.target.value)} aria-label="Session">
              <option value="">— choose a session —</option>
              {visibleSessions.map((s) => (
                <option key={s.session_id} value={s.session_id}>
                  {s.session_id} ({s.n_executions ?? 0} executions)
                  {s.status === "degraded" ? " — degraded" : ""}
                </option>
              ))}
            </select>
            {visibleSessions.length === 0 ? (
              <span className="small muted">No session matches this filter.</span>
            ) : null}
          </label>

          {sessionRow ? (
            <div>
              <div className="small muted">Operator</div>
              <div className="mono">{sessionRow.operator}</div>
              <div style={{ marginTop: 8 }}>
                <HealthBadge status={sessionRow.status} />
              </div>
              {sessionRow.status === "degraded" ? (
                <>
                  <ul className="small muted" style={{ margin: "8px 0 4px", paddingLeft: 18 }}>
                    {sessionRow.warnings.map((w) => <li key={w}>{w}</li>)}
                  </ul>
                  <p className="small muted" style={{ margin: 0 }}>
                    Some segmentation evidence is unavailable in this session. That does not by
                    itself prove the segmentation below is wrong.
                  </p>
                </>
              ) : null}
            </div>
          ) : null}
        </div>

        {loading ? <p className="muted small">Loading session executions…</p> : null}
        {loadError ? <Notice kind="error">Data error: {loadError}</Notice> : null}
      </section>

      {sessionId && !loading && !loadError ? (
        <section className="panel" aria-labelledby="sr-execs">
          <h3 id="sr-execs">Executions in this session</h3>
          <div className="controls" style={{ marginBottom: 12 }}>
            <label className="inline-field">
              <span className="small muted">Process</span>
              <select value={processFilter} onChange={(e) => setProcessFilter(e.target.value)}
                      aria-label="Filter executions by process">
                <option value="">All processes</option>
                {processOptions.map((p) => <option key={p} value={p}>{p}</option>)}
              </select>
            </label>
            <span className="small muted">
              Showing {indexRows.length} of {sessionRows.length} executions
            </span>
          </div>

          {indexRows.length === 0 ? (
            <EmptyState>
              {sessionRows.length === 0
                ? "This session contains no recovered executions."
                : "No execution matches this process filter."}
            </EmptyState>
          ) : (
            <div className="table-scroll">
              <table>
                <caption className="small muted" style={{ captionSide: "bottom", paddingTop: 8 }}>
                  Select a row to replay its steps.
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Execution</th>
                    <th scope="col">Process</th>
                    <th scope="col" className="num">Duration</th>
                    <th scope="col" className="num">Events</th>
                  </tr>
                </thead>
                <tbody>
                  {indexRows.map((r) => (
                    <tr key={r.execution_id} className="selectable"
                        aria-selected={r.execution_id === executionId}
                        onClick={() => setExecutionId(r.execution_id)}>
                      <td>
                        <button className="navbtn" style={{ padding: 0 }}
                          onClick={(e) => { e.stopPropagation(); setExecutionId(r.execution_id); }}>
                          <span className="mono small">{r.execution_id.split("::").pop()}</span>
                        </button>
                      </td>
                      <td className="wrap-any">{r.process_readable_name ?? r.dominant_context}</td>
                      <td className="num">{formatDuration(r.duration_ms)}</td>
                      <td className="num">{r.event_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ) : null}

      {execution ? (
        <section className="panel" aria-labelledby="sr-replay">
          <h3 id="sr-replay">Step replay — {execution.execution_id}</h3>

          <div className="grid cols-4" style={{ marginBottom: 14 }}>
            <div className="metric">
              <div className="label">Process</div>
              <div className="value" style={{ fontSize: 14 }}>
                {execution.process_readable_name ?? execution.dominant_context}
              </div>
            </div>
            <div className="metric">
              <div className="label">Duration</div>
              <div className="value" style={{ fontSize: 16 }}>{formatDuration(execution.duration_ms)}</div>
            </div>
            <div className="metric">
              <div className="label">Raw events covered</div>
              <div className="value" style={{ fontSize: 16 }}>{execution.event_count}</div>
              <div className="hint">across {steps.length} persisted steps</div>
            </div>
            <div className="metric">
              <div className="label">Applications</div>
              <div className="value" style={{ fontSize: 13 }}>
                {execution.applications?.length ? execution.applications.join(", ") : "Not available"}
              </div>
            </div>
          </div>

          <p className="small muted">
            Start {formatTimestamp(execution.start_ms)} · End {formatTimestamp(execution.end_ms)}
          </p>

          {steps.length === 0 ? (
            <EmptyState>This execution has no persisted steps.</EmptyState>
          ) : (
            <>
              <div className="controls" style={{ margin: "12px 0" }}>
                <button className="btn primary" onClick={() => setPlaying((p) => !p)}
                  disabled={steps.length < 2}
                  aria-label={playing ? "Pause replay" : "Play replay"}>
                  {playing ? "Pause" : "Play"}
                </button>
                <button className="btn" onClick={() => { setPlaying(false); setCursor(0); }}>
                  Restart
                </button>
                <span className="small muted">Speed</span>
                {SPEEDS.map((s) => (
                  <button key={s} className="btn" aria-pressed={speed === s}
                    onClick={() => setSpeed(s)}
                    style={speed === s ? { borderColor: "var(--accent)" } : undefined}>
                    {s}x
                  </button>
                ))}
                <span className="step-counter mono" aria-live="polite">
                  Step {Math.min(cursor + 1, steps.length)} of {steps.length}
                </span>
              </div>

              <ol className="steps">
                {steps.map((step, i) => {
                  const offset = step.start_ms - execution.start_ms;
                  const state = i === cursor ? "active" : i < cursor ? "past" : "";
                  return (
                    <li key={`${step.start_ms}-${i}`} className={`step ${state}`}>
                      <span className="off">{formatOffset(offset)}</span>
                      <span>
                        <span className="sys">{step.system ?? "(no system attributed)"}</span>
                        <br />
                        <span className="cat">{step.interaction_category}</span>
                        {step.dominant_event_types?.length ? (
                          <>
                            {" · "}
                            <span className="cat mono">
                              {step.dominant_event_types.map(([t, n]) => `${t}×${n}`).join(", ")}
                            </span>
                          </>
                        ) : null}
                      </span>
                      <span className="meta">
                        {formatDuration(step.end_ms - step.start_ms)}
                        <br />
                        {step.n_events} {step.n_events === 1 ? "event" : "events"}
                      </span>
                    </li>
                  );
                })}
              </ol>
            </>
          )}
        </section>
      ) : null}

      <ProvenancePanel
        meta={meta}
        entries={[
          { value: "Executions and ordered_steps", sourceKey: "executions" },
          { value: "Process names", sourceKey: "profiles" },
          { value: "Session health", sourceKey: "health_b" },
        ]}
      />
    </>
  );
}
