import { useEffect, useMemo, useState } from "react";
import type { EagerBundle } from "../services/dataService";
import { EmptyState, MetricCard, Notice, ProvenancePanel } from "../components/common";
import { DfgFlow } from "../components/DfgFlow";
import { formatDuration, formatNumber, formatPercent } from "../utils/format";
import type { NavParams, Navigate } from "../navigation";

const SPLIT_LABELS: Record<string, string> = {
  dominant: "Dominant path",
  word_detour: "Word detour",
  rare_edge: "Rare multi-hop",
};

export default function ProcessExplorer({
  bundle,
  navigate,
  navParams,
  navNonce,
}: {
  bundle: EagerBundle;
  navigate: Navigate;
  navParams: NavParams;
  navNonce: number;
}) {
  const { meta, processes, variants, hrPayroll, opportunities, executionsIndex } = bundle;
  const [selectedId, setSelectedId] = useState<string>("");
  const [showExcluded, setShowExcluded] = useState(false);

  // Apply a cross-screen "open this process" intent.
  useEffect(() => {
    if (navParams.processId) {
      setSelectedId(navParams.processId);
      setShowExcluded(false);
    }
  }, [navParams.processId, navNonce]);

  const ranked = useMemo(
    () => processes.filter((p) => !p.excluded_from_ranking)
      .sort((a, b) => b.execution_count - a.execution_count),
    [processes],
  );
  const excluded = useMemo(() => processes.filter((p) => p.excluded_from_ranking), [processes]);

  const selected = processes.find((p) => p.process_id === selectedId) ?? null;
  const selectedVariants = useMemo(
    () => variants.filter((v) => v.process_id === selectedId)
      .sort((a, b) => b.frequency - a.frequency),
    [variants, selectedId],
  );
  const selectedOpportunity = opportunities.ranking.find((r) => r.process_id === selectedId) ?? null;

  const hrProcessId = hrPayroll.dominant_path?.hr_process_id;
  const isHr = selectedId !== "" && selectedId === hrProcessId;
  const split = hrPayroll.variant_split ?? {};
  const hrTotal = hrPayroll.dominant_path?.n_hr_executions_total;
  const evidencedRoutes = Object.keys(hrPayroll.dominant_path?.route_id_prefix_correspondence ?? {});
  const dfgShown = hrPayroll.dfg?.top_edges?.length ?? 0;
  const dfgTotal = hrPayroll.dfg?.n_edges ?? 0;

  // Highest Impact among the ranked candidates — a sort over values already in
  // the artifact, not a recomputation of Impact itself.
  const highestImpact = useMemo(
    () => opportunities.ranking.reduce<number>((m, r) => Math.max(m, r.impact), 0),
    [opportunities.ranking],
  );

  // A session that actually contains executions of this process, for replay.
  const replaySessionId = useMemo(() => {
    const row = executionsIndex.find((e) => e.dominant_context === selectedId);
    return row?.session_id ?? null;
  }, [executionsIndex, selectedId]);

  const rows = showExcluded ? excluded : ranked;

  return (
    <>
      <header>
        <h2>Process Explorer</h2>
        <p className="lede">
          Processes recovered from Dataset B, with their measured volume, duration and variant
          structure. All figures are read from the Day-3 profile and variant artifacts.
        </p>
      </header>

      <section className="panel" aria-labelledby="pe-list">
        <h3 id="pe-list">
          {showExcluded ? `Excluded from ranking (${excluded.length})` : `Ranked processes (${ranked.length})`}
        </h3>
        <div className="controls" style={{ marginBottom: 12 }}>
          <button className="btn" aria-pressed={!showExcluded} onClick={() => setShowExcluded(false)}>
            Ranked ({ranked.length})
          </button>
          <button className="btn" aria-pressed={showExcluded} onClick={() => setShowExcluded(true)}>
            Excluded ({excluded.length})
          </button>
          <span className="small muted">
            {processes.length} processes discovered in total; only ranked ones enter the
            opportunity scoring.
          </span>
        </div>

        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">Process</th>
                <th scope="col" className="num">Executions</th>
                <th scope="col" className="num">Total time</th>
                <th scope="col" className="num">Variants</th>
                <th scope="col" className="num">Dominant share</th>
                <th scope="col" className="num">Manual share</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.process_id} className="selectable"
                    aria-selected={p.process_id === selectedId}
                    onClick={() => setSelectedId(p.process_id)}>
                  <td className="wrap-any">
                    <button className="navbtn" style={{ padding: 0 }}
                      onClick={(e) => { e.stopPropagation(); setSelectedId(p.process_id); }}>
                      {p.readable_name}
                    </button>
                  </td>
                  <td className="num">{p.execution_count}</td>
                  <td className="num">{formatDuration(p.total_duration_ms)}</td>
                  <td className="num">{p.n_variants}</td>
                  <td className="num">{formatPercent(p.dominant_variant_share, 2)}</td>
                  <td className="num">{formatPercent(p.avg_manual_event_share, 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {selected ? (
        <section className="panel" aria-labelledby="pe-detail">
          <div className="headline-head">
            <div>
              <h3 id="pe-detail" style={{ marginBottom: 4 }}>{selected.readable_name}</h3>
              <p className="mono small muted wrap-any" style={{ margin: 0 }}>{selected.process_id}</p>
            </div>
            <div className="controls">
              {replaySessionId ? (
                <button className="btn"
                  onClick={() => navigate("replay", { sessionId: replaySessionId })}>
                  Replay a session with this process
                </button>
              ) : null}
              {isHr ? (
                <button className="btn primary" onClick={() => navigate("automation")}>
                  Try automation
                </button>
              ) : null}
            </div>
          </div>

          {/* ---------- why it matters ---------- */}
          {selectedOpportunity ? (
            <div className="why" style={{ marginTop: 14 }}>
              <h4>Why this process matters</h4>
              <ul>
                <li>
                  <strong>{selected.execution_count} executions</strong> recovered across{" "}
                  {Object.keys(selected.frequency_by_operator ?? {}).length} operators.
                </li>
                <li>
                  <strong>{formatPercent(selected.dominant_variant_share, 2)}</strong> of them follow
                  a single dominant path ({selected.n_variants} variants in total) — the
                  repeatability an automation would depend on.
                </li>
                <li>
                  <strong>{formatDuration(selected.total_duration_ms)}</strong> of recorded activity
                  ({formatNumber(selected.total_human_hours, 4)} human hours in this sample), with{" "}
                  {formatPercent(selected.avg_manual_event_share, 1)} of events manual.
                </li>
                <li>
                  Impact <strong>{formatNumber(selectedOpportunity.impact)}</strong>
                  {selectedOpportunity.impact === highestImpact
                    ? " — the highest of the ranked candidates"
                    : ""}
                  , Feasibility <strong>{formatNumber(selectedOpportunity.feasibility)}</strong>,
                  Opportunity <strong>{formatNumber(selectedOpportunity.opportunity)}</strong>{" "}
                  (rank {selectedOpportunity.rank}
                  {selectedOpportunity.pareto_status === "frontier" ? ", Pareto non-dominated" : ""}).
                </li>
                {isHr && evidencedRoutes.length ? (
                  <li>
                    Bounded automation surface: <strong>{evidencedRoutes.length} evidenced routes</strong>{" "}
                    (<span className="mono small">{evidencedRoutes.join(", ")}</span>), which is what
                    makes a deterministic prototype possible for this process.
                  </li>
                ) : null}
              </ul>
              <p className="small muted" style={{ marginBottom: 0 }}>
                All figures above are read from the Day-3 artifacts. No monetary saving is claimed —
                the logs carry no cost or production-volume data.
              </p>
            </div>
          ) : null}

          <div className="grid cols-4" style={{ marginTop: 14 }}>
            <MetricCard label="Executions" value={selected.execution_count} />
            <MetricCard label="Total time" value={formatDuration(selected.total_duration_ms)}
              hint={`${formatNumber(selected.total_human_hours, 4)} human hours`} />
            <MetricCard label="Average duration"
              value={formatDuration(selected.duration_ms_distribution?.mean)}
              hint={`median ${formatDuration(selected.duration_ms_distribution?.median)}`} />
            <MetricCard label="Operators"
              value={Object.keys(selected.frequency_by_operator ?? {}).length}
              hint={Object.entries(selected.frequency_by_operator ?? {})
                .map(([op, n]) => `${op}: ${n}`).join(" · ") || "Not available"} />
          </div>

          {/* ---------- HR forensic split, made prominent ---------- */}
          {isHr ? (
            <>
              <h3 style={{ marginTop: 22 }}>HR forensic variant split</h3>
              <Notice kind="info">
                A <strong>different classification</strong> from the generic variant table below.
                It comes from the Day-3 HR dominant-path forensics and is read directly from{" "}
                <span className="mono">hr-payroll.json::variant_split</span> — it is not derived
                from the variant signatures.
              </Notice>
              <div className="split-cards">
                {(["dominant", "word_detour", "rare_edge"] as const).map((key) =>
                  split[key] ? (
                    <div className={`split-card ${key}`} key={key}>
                      <div className="split-n">{split[key].n}</div>
                      <div className="split-label">{SPLIT_LABELS[key]}</div>
                      <div className="split-share">
                        {formatPercent(split[key].share, 2)}
                        {hrTotal ? <span className="muted"> of {hrTotal}</span> : null}
                      </div>
                      <div className="split-bar" aria-hidden="true">
                        <span style={{ width: `${Math.round(split[key].share * 100)}%` }} />
                      </div>
                    </div>
                  ) : null,
                )}
              </div>
              <p className="small muted">
                Only the dominant path is in scope for the prototype. The Word detour and rare
                multi-hop cases were deliberately excluded, not partially automated.
              </p>

              <h3 style={{ marginTop: 22 }}>
                Directly-follows graph — top {dfgShown} of {dfgTotal} edges
              </h3>
              <p className="small muted">
                Edge counts and transition probabilities are copied from the Day-3 process-mining
                artifact. Available for HR/Payroll only — the other processes&rsquo; graphs were not
                persisted by that script.
              </p>

              {hrPayroll.dfg?.top_edges?.length ? (
                <>
                  <DfgFlow edges={hrPayroll.dfg.top_edges} shown={dfgShown} total={dfgTotal} />
                  <div className="table-scroll" style={{ marginTop: 12 }}>
                    <table>
                      <thead>
                        <tr>
                          <th scope="col">From</th>
                          <th scope="col">To</th>
                          <th scope="col" className="num">Count</th>
                          <th scope="col" className="num">P(to | from)</th>
                        </tr>
                      </thead>
                      <tbody>
                        {hrPayroll.dfg.top_edges.map((e, i) => (
                          <tr key={`${e.source}-${e.target}-${i}`}>
                            <td className="mono small wrap-any">{e.source}</td>
                            <td className="mono small wrap-any">{e.target}</td>
                            <td className="num">{e.count}</td>
                            <td className="num">{formatNumber(e.probability, 3)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              ) : (
                <EmptyState>No directly-follows edges in the bundle.</EmptyState>
              )}
            </>
          ) : (
            <Notice kind="info">
              Forensic variant split and directly-follows graph are available for HR/Payroll only.
              The Day-3 pipeline persisted them for the selected automation candidate; for the
              other processes those structures were computed in memory and not written to disk.
            </Notice>
          )}

          <h3 style={{ marginTop: 22 }}>Variants ({selectedVariants.length})</h3>
          <p className="small muted">
            Generic per-signature variants as discovered by the Day-3 pipeline.
          </p>
          {selectedVariants.length === 0 ? (
            <EmptyState>No variant rows for this process.</EmptyState>
          ) : (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Signature</th>
                    <th scope="col" className="num">Frequency</th>
                    <th scope="col" className="num">Avg duration</th>
                  </tr>
                </thead>
                <tbody>
                  {selectedVariants.map((v, i) => (
                    <tr key={`${v.process_id}-${i}`}>
                      <td className="mono small wrap-any">{v.signature.join(" → ")}</td>
                      <td className="num">{v.frequency}</td>
                      <td className="num">{formatDuration(v.avg_duration_ms)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ) : (
        <section className="panel">
          <EmptyState>Select a process to see its detail, variants and evidence.</EmptyState>
        </section>
      )}

      <ProvenancePanel
        meta={meta}
        entries={[
          { value: "Process profiles", sourceKey: "profiles" },
          { value: "Variants", sourceKey: "variants" },
          { value: "HR variant split / dominant path", sourceKey: "hr_dominant_path" },
          { value: "HR directly-follows graph", sourceKey: "mining_full" },
          { value: "Impact / Feasibility / Opportunity", sourceKey: "audit" },
        ]}
      />
    </>
  );
}
