import { Fragment, useMemo, useState } from "react";
import type { EagerBundle } from "../services/dataService";
import { EmptyState, Notice, ProvenancePanel } from "../components/common";
import { formatDuration, formatNumber, formatPercent } from "../utils/format";
import type { Navigate } from "../navigation";

type SortKey = "rank" | "impact" | "feasibility" | "opportunity";

const SPLIT_LABELS: Record<string, string> = {
  dominant: "dominant-path",
  word_detour: "Word-detour",
  rare_edge: "rare/multi-hop",
};

export default function Opportunities({
  bundle,
  navigate,
}: {
  bundle: EagerBundle;
  navigate: Navigate;
}) {
  const { meta, opportunities, processes, hrPayroll } = bundle;
  const [sortKey, setSortKey] = useState<SortKey>("rank");
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<string>("");

  const rows = useMemo(() => {
    const filtered = opportunities.ranking.filter((r) =>
      r.readable_name.toLowerCase().includes(query.trim().toLowerCase()));
    return [...filtered].sort((a, b) =>
      sortKey === "rank" ? a.rank - b.rank : (b[sortKey] as number) - (a[sortKey] as number));
  }, [opportunities.ranking, query, sortKey]);

  const pareto = opportunities.pareto_frontier;
  const sens = opportunities.sensitivity_summary;
  const hrProcessId = hrPayroll.dominant_path?.hr_process_id;
  const split = hrPayroll.variant_split ?? {};
  const hrTotal = hrPayroll.dominant_path?.n_hr_executions_total;

  return (
    <>
      <header>
        <h2>Opportunities</h2>
        <p className="lede">
          How the automation candidate was selected. Impact, Feasibility and Opportunity are read
          verbatim from the canonical Day-3 audit artifact; no score is computed in the browser.
        </p>
      </header>

      <Notice kind="ok">
        <strong>Canonical post-entropy-fix ranking.</strong> Source:{" "}
        <span className="mono">{opportunities.canonical_source}</span>. {opportunities.canonical_note}
      </Notice>

      <section className="panel" aria-labelledby="op-defs">
        <h3 id="op-defs">What these three numbers mean</h3>
        <div className="grid cols-3">
          <div className="def">
            <h4>Impact</h4>
            <p className="small muted">
              How much this process is worth changing — volume, recorded time and manual
              involvement. High Impact alone does not mean it can be automated.
            </p>
          </div>
          <div className="def">
            <h4>Feasibility</h4>
            <p className="small muted">
              How amenable it is to automation — determinism, variant concentration, automation
              surface and risk. High Feasibility alone does not mean it is worth doing.
            </p>
          </div>
          <div className="def">
            <h4>Opportunity</h4>
            <p className="small muted">
              Impact × Feasibility. <strong>Not a monetary ROI estimate</strong> — the logs contain
              no cost or production-volume data, so no financial figure is derivable from them.
            </p>
          </div>
        </div>
      </section>

      <section className="panel" aria-labelledby="op-context">
        <h3 id="op-context">Weighting-independent checks</h3>
        <div className="grid cols-3">
          <div className="metric">
            <div className="label">Pareto frontier</div>
            <div className="value">{pareto?.n_frontier ?? "—"} / {pareto?.n_total ?? "—"}</div>
            <div className="hint">
              {pareto?.processes?.length ? pareto.processes.join(" · ") : "Not available"}
            </div>
          </div>
          <div className="metric">
            <div className="label">HR on frontier</div>
            <div className="value">{pareto?.hr_on_frontier ? "Yes" : "No"}</div>
            <div className="hint">Non-dominated on (Impact, Feasibility)</div>
          </div>
          <div className="metric">
            <div className="label">HR ranked #1 in</div>
            <div className="value">
              {sens ? `${sens.n_hr_first} / ${sens.n_scenarios}` : "Not available"}
            </div>
            <div className="hint">weighting sensitivity scenarios</div>
          </div>
        </div>
      </section>

      <section className="panel" aria-labelledby="op-table">
        <h3 id="op-table">Ranking ({opportunities.ranking.length} candidate processes)</h3>
        <div className="controls" style={{ marginBottom: 12 }}>
          <input type="text" value={query} onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter by process name…" aria-label="Filter processes by name"
            style={{ maxWidth: 280 }} />
          <span className="small muted">Sort</span>
          {(["rank", "impact", "feasibility", "opportunity"] as SortKey[]).map((k) => (
            <button key={k} className="btn" aria-pressed={sortKey === k} onClick={() => setSortKey(k)}
              style={sortKey === k ? { borderColor: "var(--accent)" } : undefined}>
              {k[0].toUpperCase() + k.slice(1)}
            </button>
          ))}
        </div>

        {rows.length === 0 ? (
          <EmptyState>No processes match that filter.</EmptyState>
        ) : (
          <div className="table-scroll">
            <table aria-label="Opportunity ranking">
              <thead>
                <tr>
                  <th scope="col" className="num">#</th>
                  <th scope="col">Process</th>
                  <th scope="col" className="num">Impact</th>
                  <th scope="col" className="num">Feasibility</th>
                  <th scope="col" className="num">Opportunity</th>
                  <th scope="col">Pareto</th>
                  <th scope="col" className="num">Best</th>
                  <th scope="col" className="num">Worst</th>
                  <th scope="col">Evidence</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const profile = processes.find((p) => p.process_id === r.process_id);
                  const isOpen = expanded === r.process_id;
                  const isHr = r.process_id === hrProcessId;
                  return (
                    <Fragment key={r.process_id}>
                      <tr aria-selected={isOpen}>
                        <td className="num">{r.rank}</td>
                        <td className="wrap-any">{r.readable_name}</td>
                        <td className="num">{formatNumber(r.impact)}</td>
                        <td className="num">{formatNumber(r.feasibility)}</td>
                        <td className="num"><strong>{formatNumber(r.opportunity)}</strong></td>
                        <td>
                          <span className={`badge ${r.pareto_status === "frontier" ? "ok" : "neutral"}`}>
                            {r.pareto_status ?? "—"}
                          </span>
                        </td>
                        <td className="num">{r.best_rank ?? "—"}</td>
                        <td className="num">{r.worst_rank ?? "—"}</td>
                        <td>
                          <button className="btn small-btn"
                            aria-expanded={isOpen}
                            aria-controls={`why-${r.rank}`}
                            onClick={() => setExpanded(isOpen ? "" : r.process_id)}>
                            {isOpen ? "Hide why" : "Why?"}
                          </button>
                        </td>
                      </tr>
                      {isOpen ? (
                        <tr>
                          <td colSpan={9} id={`why-${r.rank}`} className="why-cell">
                            <div className="why">
                              <h4>Why {r.readable_name} ranks {r.rank}</h4>
                              <ul>
                                <li>
                                  Impact <strong>{formatNumber(r.impact)}</strong> ·
                                  Feasibility <strong>{formatNumber(r.feasibility)}</strong> ·
                                  Opportunity <strong>{formatNumber(r.opportunity)}</strong>{" "}
                                  (Impact × Feasibility).
                                </li>
                                <li>
                                  Pareto status <strong>{r.pareto_status ?? "not available"}</strong>
                                  {" "}— taken from the artifact&rsquo;s own{" "}
                                  <span className="mono">pareto_status</span> field, not inferred
                                  from rank.
                                </li>
                                <li>
                                  Rank stability: best {r.best_rank ?? "—"}, median{" "}
                                  {r.median_rank ?? "—"}, worst {r.worst_rank ?? "—"} across tested
                                  perturbations.
                                </li>
                                {profile ? (
                                  <li>
                                    Observed: <strong>{profile.execution_count} executions</strong>,{" "}
                                    {formatDuration(profile.total_duration_ms)} recorded,{" "}
                                    {profile.n_variants} variants,{" "}
                                    {formatPercent(profile.dominant_variant_share, 2)} on the
                                    dominant path,{" "}
                                    {formatPercent(profile.avg_manual_event_share, 1)} manual events.
                                  </li>
                                ) : null}
                                {isHr ? (
                                  <li>
                                    Forensic split of {hrTotal ?? "—"} executions:{" "}
                                    {(["dominant", "word_detour", "rare_edge"] as const)
                                      .filter((k) => split[k])
                                      .map((k) => `${split[k].n} ${SPLIT_LABELS[k]}`)
                                      .join(", ")}
                                    {" "}— from{" "}
                                    <span className="mono">hr-payroll.json::variant_split</span>.
                                  </li>
                                ) : null}
                              </ul>
                              <div className="controls">
                                <button className="btn"
                                  onClick={() => navigate("processes", { processId: r.process_id })}>
                                  Open in Process Explorer
                                </button>
                                {isHr ? (
                                  <button className="btn primary" onClick={() => navigate("automation")}>
                                    Try automation
                                  </button>
                                ) : null}
                              </div>
                            </div>
                          </td>
                        </tr>
                      ) : null}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <ProvenancePanel
        meta={meta}
        entries={[
          { value: "Ranking, Pareto, sensitivity", sourceKey: "audit" },
          { value: "Underlying process volume", sourceKey: "profiles" },
          { value: "HR forensic split", sourceKey: "hr_dominant_path" },
        ]}
      />
    </>
  );
}
