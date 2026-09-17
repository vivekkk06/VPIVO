import type { EagerBundle } from "../services/dataService";
import { PageHeader } from "../components/PageHeader";
import { MetricCard, Notice, ProvenancePanel } from "../components/common";
import { InvestigationProgress } from "../components/InvestigationProgress";
import { EvidenceBadge, EvidenceTrace } from "../components/evidence";
import { formatNumber, formatPercent } from "../utils/format";
import type { Navigate } from "../navigation";

export default function Dashboard({
  bundle,
  navigate,
}: {
  bundle: EagerBundle;
  navigate: Navigate;
}) {
  const {
    meta, executionsIndex, processes, opportunities, instrumentation,
    datasetAMetrics, hrPayroll, engineeringUpgrade, investigation,
  } = bundle;

  const top = opportunities.ranking[0];
  const topProfile = top ? processes.find((p) => p.process_id === top.process_id) ?? null : null;

  // The deterministic-RPA prototype exists for exactly one process: the one the
  // Day-3 HR forensics identified. Gate the recommendation on that identity
  // rather than on rank, so it cannot leak onto a different top candidate.
  const hrProcessId = hrPayroll.dominant_path?.hr_process_id;
  const evidencedRoutes = Object.keys(hrPayroll.dominant_path?.route_id_prefix_correspondence ?? {});
  const prototypeApplies = !!top && top.process_id === hrProcessId && evidencedRoutes.length > 0;

  // Read verbatim from the bundle; nothing here is recomputed.
  const split = hrPayroll.variant_split ?? {};
  const hrTotal = hrPayroll.dominant_path?.n_hr_executions_total;
  const sens = opportunities.sensitivity_summary ?? null;
  const segChallenge = engineeringUpgrade.segmentation_challenge;
  const pareto = opportunities.pareto_frontier;

  const a = instrumentation.dataset_a.summary;
  const b = instrumentation.dataset_b.summary;
  const pooled = datasetAMetrics.pooled;

  // "Largest" and "highest" below are comparisons over values already in the bundle.
  const metrics = investigation.day3.process_metrics;
  const rankedIds = opportunities.ranking.map((r) => r.process_id);
  const topTimeShare = top ? metrics[top.process_id]?.time_share ?? null : null;
  const largestTimeShare = topTimeShare != null
    && rankedIds.every((id) => (metrics[id]?.time_share ?? 0) <= topTimeShare);
  const highestImpact = !!top && opportunities.ranking.every((r) => r.impact <= top.impact);
  const module2 = investigation.day2.module2;
  const localTarget = engineeringUpgrade.browser.not_connected_to_real_hr_system;

  return (
    <>
      <PageHeader
        screen="dashboard"
        title="Executive Dashboard"
        purpose="What was analysed, which process was selected and why, what actually runs, and what is still weak. Every figure is read from the generated data bundle; none of it is recalculated here."
        context={`Dataset A + Dataset B · ${opportunities.ranking.length} ranked processes`}
      />

      {/* ---------- what this is ---------- */}
      <section className="hero" aria-labelledby="db-hero">
        <h3 id="db-hero" className="hero-title">From operation logs to a bounded automation proposal</h3>
        <p className="hero-sub">
          An evidence-backed investigation across process reconstruction, process mining, and
          automation feasibility.
        </p>
        <ul className="kpis" aria-label="Scope of the analysis">
          <li className="kpi">
            <span className="kpi-value mono">{a.n_sessions}</span>
            <span className="kpi-label">sessions analysed</span>
            <span className="kpi-note">Dataset A · with ground truth</span>
          </li>
          <li className="kpi">
            <span className="kpi-value mono">{executionsIndex.length}</span>
            <span className="kpi-label">executions recovered</span>
            <span className="kpi-note">Dataset B · {b.n_sessions} sessions</span>
          </li>
          <li className="kpi">
            <span className="kpi-value mono">{opportunities.ranking.length}</span>
            <span className="kpi-label">processes ranked</span>
            <span className="kpi-note">Dataset B · Impact × Feasibility</span>
          </li>
          {topProfile ? (
            <li className="kpi kpi-accent">
              <span className="kpi-value mono">{formatPercent(topProfile.dominant_variant_share, 2)}</span>
              <span className="kpi-label">HR dominant path</span>
              <span className="kpi-note">{split.dominant?.n} of {hrTotal} HR executions</span>
            </li>
          ) : null}
        </ul>
      </section>

      <InvestigationProgress bundle={bundle} navigate={navigate} />

      <div className="glance-grid">
        {/* ---------- decision at a glance ---------- */}
        {top ? (
          <section className="panel headline" aria-labelledby="db-top">
            <div className="headline-head">
              <div>
                <h3 id="db-top" style={{ marginBottom: 6 }}>Decision at a glance</h3>
                <p className="headline-name">{top.readable_name}</p>
                {prototypeApplies ? (
                  <p style={{ margin: "8px 0 0" }}>
                    <span className="badge ok verdict">READY FOR BOUNDED PILOT</span>
                  </p>
                ) : null}
                <p className="small muted" style={{ margin: "8px 0 0" }}>
                  Rank {top.rank} of {opportunities.ranking.length}
                  {top.pareto_status === "frontier" ? " · Pareto non-dominated" : ""}
                  {typeof top.worst_rank === "number"
                    ? ` · never worse than rank ${top.worst_rank} under tested perturbations`
                    : ""}
                </p>
                {prototypeApplies && split.dominant && topProfile ? (
                  <p style={{ margin: "10px 0 0" }}>
                    <strong className="mono">{split.dominant.n} / {topProfile.execution_count}</strong> executions
                    follow the dominant deterministic path —{" "}
                    <strong>{formatPercent(topProfile.dominant_variant_share, 2)}</strong>{" "}
                    dominant-path share.
                  </p>
                ) : null}
              </div>
              {prototypeApplies ? (
                <div className="rec">
                  <span className="badge ok">Deterministic RPA</span>
                  <p className="small muted" style={{ margin: "6px 0 0" }}>
                    A deterministic prototype exists for this process, scoped to{" "}
                    {evidencedRoutes.length} evidenced routes. No API integration was evidenced in
                    the logs.
                  </p>
                </div>
              ) : null}
            </div>

            <div className="grid cols-4" style={{ marginTop: 14 }}>
              <MetricCard label="Opportunity" value={formatNumber(top.opportunity)}
                hint="Impact × Feasibility — not a monetary ROI" />
              <MetricCard label="Impact" value={formatNumber(top.impact)} />
              <MetricCard label="Feasibility" value={formatNumber(top.feasibility)} />
              {topProfile ? (
                <MetricCard
                  label="Observed volume"
                  value={`${topProfile.execution_count} executions`}
                  hint={`${formatPercent(topProfile.dominant_variant_share, 2)} follow the dominant path`}
                />
              ) : null}
            </div>

            <dl className="facts">
              <div>
                <dt>Pareto</dt>
                <dd>{top.pareto_status === "frontier" ? "Yes" : "No"}</dd>
                <dd className="fact-note">Non-dominated — needs no weighting</dd>
              </div>
              {sens ? (
                <div>
                  <dt>Sensitivity</dt>
                  <dd>{`#1 in ${sens.n_hr_first}/${sens.n_scenarios} scenarios`}</dd>
                  <dd className="fact-note">Weighting scenarios — not statistical confidence</dd>
                </div>
              ) : null}
              {typeof top.worst_rank === "number" ? (
                <div>
                  <dt>Worst rank</dt>
                  <dd>{`#${top.worst_rank}`}</dd>
                  <dd className="fact-note">Across every tested perturbation</dd>
                </div>
              ) : null}
            </dl>

            <div className="controls" style={{ marginTop: 14 }}>
              <button
                className="btn primary"
                onClick={() => navigate("processes", { processId: top.process_id })}
              >
                Explore process
              </button>
              {prototypeApplies ? (
                <button className="btn" onClick={() => navigate("automation")}>
                  Try automation
                </button>
              ) : null}
              <button className="btn" onClick={() => navigate("opportunities")}>
                See full ranking
              </button>
              <button className="btn" onClick={() => navigate("decision")}>
                Inspect decision →
              </button>
            </div>

            {prototypeApplies ? (
              <Notice kind="info">
                <strong>Bounded pilot</strong> means the dominant deterministic path only; human
                review remains required before every confirmation.
              </Notice>
            ) : null}

            <p className="small muted source-line">
              <EvidenceBadge kind="canonical" />{" "}
              Canonical source: <span className="mono">{opportunities.canonical_source}</span>.{" "}
              {opportunities.canonical_note}
            </p>
          </section>
        ) : (
          <Notice kind="warn">No ranking rows in the bundle.</Notice>
        )}

        {/* ---------- limitations, kept beside the decision ---------- */}
        <section className="panel limits" aria-labelledby="db-limits">
          <div className="panel-head">
            <h3 id="db-limits">Limitations</h3>
            <EvidenceBadge kind="limitation" />
          </div>
          <ul className="limit-list">
            <li>
              <strong>Segmentation is imperfect.</strong> Boundary F1{" "}
              <span className="mono">{formatNumber(pooled.f1)}</span> on Dataset A.{" "}
              <button className="linkish" onClick={() => navigate("reconstruction")}>Day 2</button>
            </li>
            <li>
              <strong>Dataset B has no ground truth.</strong> Its executions are compared with each
              other, never scored as right or wrong.{" "}
              <button className="linkish" onClick={() => navigate("process-mining")}>Day 3</button>
            </li>
            <li>
              <strong>The HR system is a local mock.</strong>{" "}
              {localTarget
                ? "The prototype drives a local prototype page; no real HR system is connected."
                : "See the Decision Center for the integration status."}{" "}
              <button className="linkish" onClick={() => navigate("automation")}>Demo</button>
            </li>
            {module2 ? (
              <li>
                <strong>Module 2 was not promoted.</strong> F1 gain{" "}
                <span className="mono">+{module2.f1_gain.toFixed(4)}</span> against{" "}
                <span className="mono">+{module2.required_gain.toFixed(4)}</span> required.{" "}
                <button className="linkish" onClick={() => navigate("modules")}>Comparison</button>
              </li>
            ) : null}
            <li>
              <strong>No dollar figure.</strong> The logs carry no cost or headcount data, so the
              score ranks processes and nothing more.
            </li>
          </ul>
        </section>
      </div>

      {/* ---------- why this process ---------- */}
      {top && prototypeApplies ? (
        <section className="panel" aria-labelledby="db-why">
          <h3 id="db-why">Why this process?</h3>
          <div className="why-cards">
            <article className="why-card">
              <span className="why-kicker">High time impact</span>
              <span className="why-value mono">{topTimeShare != null ? formatPercent(topTimeShare, 1) : "—"}</span>
              <p className="small">
                of recorded time across the {opportunities.ranking.length} ranked processes
                {largestTimeShare ? " — the largest share" : ""}. Impact{" "}
                <span className="mono">{formatNumber(top.impact)}</span>
                {highestImpact ? ", the highest of all candidates" : ""}.
              </p>
            </article>
            <article className="why-card">
              <span className="why-kicker">Bounded pattern</span>
              <span className="why-value mono">{formatPercent(split.dominant?.share, 2)}</span>
              <p className="small">
                of executions follow one path through {evidencedRoutes.length} known routes, with the
                note pasted rather than typed. The {(split.word_detour?.n ?? 0) + (split.rare_edge?.n ?? 0)} exceptions
                stay with a person.
              </p>
            </article>
            <article className="why-card">
              <span className="why-kicker">Robust decision</span>
              <span className="why-value mono">{sens ? `${sens.n_hr_first} of ${sens.n_scenarios}` : "—"}</span>
              <p className="small">
                weighting scenarios rank it first; worst observed rank {top.worst_rank ?? "—"}. One
                of {pareto.n_frontier} Pareto non-dominated processes out of {pareto.n_total}.
              </p>
            </article>
          </div>
        </section>
      ) : null}

      {/* ---------- what was built ---------- */}
      <section className="panel" aria-labelledby="db-built">
        <div className="panel-head">
          <h3 id="db-built">What I built</h3>
          <EvidenceBadge kind="prototype" label="LOCAL PROTOTYPE" />
        </div>
        <ul className="built-grid">
          <li>
            <strong>Deterministic UI automation</strong>
            <span className="small muted">Inserts the operator&rsquo;s note on an evidenced route, then stops. It never confirms on its own.</span>
          </li>
          <li>
            <strong>Human review</strong>
            <span className="small muted">A person approves every confirmation. Checkpoint tokens are single-use.</span>
          </li>
          <li>
            <strong>Browser adapter</strong>
            <span className="small muted">The same automation drives a real Chromium page through Playwright, on a local prototype page.</span>
          </li>
          <li>
            <strong>Audit and failure handling</strong>
            <span className="small muted">Execution ids, safe stops, a redacted audit trail, and a status lookup when a confirmation response is lost.</span>
          </li>
        </ul>
        <div className="controls">
          <button className="btn" onClick={() => navigate("automation")}>Open the HR demo</button>
          <button className="btn" onClick={() => navigate("decision")}>Read the decision record</button>
        </div>
      </section>

      {/* ---------- instrumentation ---------- */}
      <section className="panel" aria-labelledby="db-health">
        <div className="panel-head">
          <h3 id="db-health">Instrumentation health (Day-4 diagnostic)</h3>
          <button className="linkish small" onClick={() => navigate("evidence-health")}>Open Day 4</button>
        </div>
        <div className="grid cols-2">
          {([
            ["Dataset A", a, "dataset_a"] as const,
            ["Dataset B", b, "dataset_b"] as const,
          ]).map(([label, summary, key]) => (
            <div className="health-card" key={key}>
              <div className="health-head">
                <span className="label">{label}</span>
                <span className="muted small">{summary.n_sessions} sessions</span>
              </div>
              <div className="health-split">
                <div>
                  <div className="health-num ok">{summary.n_healthy}</div>
                  <div className="small muted">healthy</div>
                </div>
                <div>
                  {key === "dataset_b" && summary.n_degraded > 0 ? (
                    <button
                      className="health-num bad linkish"
                      onClick={() => navigate("replay", { degradedOnly: true })}
                      aria-label={`Show ${summary.n_degraded} degraded Dataset B sessions in Execution Step Replay`}
                    >
                      {summary.n_degraded}
                    </button>
                  ) : (
                    <div className="health-num bad">{summary.n_degraded}</div>
                  )}
                  <div className="small muted">
                    degraded
                    {key === "dataset_b" && summary.n_degraded > 0 ? " — select to inspect" : ""}
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>

        <p className="small muted" style={{ margin: "10px 0 0" }}>
          Thresholds: at least {a.thresholds.min_distinct_browser_domains} distinct browser domains
          and {formatPercent(a.thresholds.min_browser_domain_coverage, 0)} browser-domain coverage
          (owned by <span className="mono">procmine.instrumentation_health</span>).
        </p>

        <Notice kind="info">
          <strong>Instrumentation quality is not segmentation quality.</strong> Degraded
          instrumentation means some segmentation evidence is unavailable in that session; it does
          not by itself prove segmentation failure. Day 4 established the diagnostic detects
          missing instrumentation, not every possible cause of poor segmentation.
        </Notice>
      </section>

      {/* ---------- Dataset A quality ---------- */}
      <section className="panel" aria-labelledby="db-quality">
        <div className="panel-head">
          <h3 id="db-quality">Dataset A — segmentation quality (locked Day-2 architecture)</h3>
          <button className="linkish small" onClick={() => navigate("reconstruction")}>Open Day 2</button>
        </div>
        <div className="grid cols-3">
          <MetricCard label="Precision" value={formatNumber(pooled.precision)} />
          <MetricCard label="Recall" value={formatNumber(pooled.recall)} />
          <MetricCard label="Boundary F1" value={formatNumber(pooled.f1)}
            hint="Transition-level F1, not 'accuracy'" />
          <MetricCard label="Executions fragmented"
            value={formatPercent(pooled.pct_gt_executions_fragmented / 100, 2)}
            hint={`${pooled.n_gt_executions_fragmented} of ${pooled.n_gt_executions_total}`} />
          <MetricCard label="Under-segmentation" value={formatNumber(pooled.under_segmentation_rate)} />
          <MetricCard label="Over-segmentation" value={formatNumber(pooled.over_segmentation_rate)} />
        </div>
        <Notice kind="warn">
          <strong>Interpretation — this is a material limitation, not a good score.</strong>{" "}
          Exact event-boundary recovery remains weak: roughly 4 in 5 ground-truth executions
          still contain at least one spurious internal boundary. Ground-truth boundaries are
          only ~1.03% of transitions, which is why precision/recall/F1 are reported here and
          accuracy is not — a model that never predicted a boundary would score ~99% accuracy
          and be useless. That explains the choice of metric; it does not excuse the value.
        </Notice>
        <Notice kind="info">
          <strong>Dataset B is not validated by these numbers.</strong> Dataset A is measured
          against ground truth; Dataset B has none. Individual Dataset-B segments are not
          treated as ground truth anywhere — they are evidence for prioritising processes,
          which is a comparative question that survives this uncertainty.
        </Notice>
        <details className="evidence" style={{ marginTop: 12 }}>
          <summary>
            <strong>Why was the baseline retained?</strong>
          </summary>
          <div className="evidence-detail">
            <p>
              The weakness was attacked and measured, not assumed away: a continuity-first
              reformulation made fragmentation worse (94.7%), threshold re-selection needed recall
              to collapse to ~0.15–0.21 to help, an unsupervised HMM scored F1 0.0194 (~18× worse),
              and an ensemble cost ~225 false positives per additional true boundary. The strongest
              remaining lever is upstream instrumentation, not a bigger model.
            </p>
            <p>
              Day 7 tested <strong>{segChallenge.candidates_tested} alternative segmentation
              candidates</strong> using session-grouped validation
              ({segChallenge.validation}) and pre-registered promotion gates.{" "}
              <strong>None passed the required gates.</strong> The alternatives reduced
              fragmentation primarily by accepting substantially more under-segmentation, so the
              locked baseline was retained.
            </p>
            <div className="table-scroll">
              <table aria-label="Locked baseline versus the best rejected candidate">
                <thead>
                  <tr>
                    <th scope="col">System</th>
                    <th scope="col">F1</th>
                    <th scope="col">Fragmentation</th>
                    <th scope="col">Under-segmentation</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <th scope="row">Locked baseline</th>
                    <td>{formatNumber(segChallenge.baseline_f1)}</td>
                    <td>{segChallenge.baseline_fragmentation_pct.toFixed(2)}%</td>
                    <td>{formatNumber(segChallenge.baseline_under_segmentation)}</td>
                  </tr>
                  <tr>
                    <th scope="row">
                      Best rejected candidate ({segChallenge.best_candidate_label})
                    </th>
                    <td>{formatNumber(segChallenge.best_candidate_f1)}</td>
                    <td>{segChallenge.best_candidate_fragmentation_pct.toFixed(2)}%</td>
                    <td>{formatNumber(segChallenge.best_candidate_under_segmentation)}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p style={{ marginBottom: 0 }}>
              <strong>Interpretation:</strong> lower fragmentation alone was not sufficient; the
              alternatives moved the system along the fragmentation / under-segmentation trade-off
              without improving the overall decision objective.
            </p>
            <EvidenceTrace
              source={["engineering-upgrade.json → segmentation_challenge",
                       "reports/day7/segmentation_improvement_analysis.md",
                       "reports/final_report.md"]}
              method="Leave-one-session-out, gates registered before candidates were scored."
            />
          </div>
        </details>
      </section>

      <ProvenancePanel
        meta={meta}
        entries={[
          { value: "Executions, sessions", sourceKey: "executions" },
          { value: "Ranked processes", sourceKey: "profiles" },
          { value: "Opportunity ranking", sourceKey: "audit" },
          { value: "Dataset-A quality metrics", sourceKey: "dataset_a_metrics" },
          { value: "Instrumentation health", sourceKey: "health_b" },
          { value: "HR evidence / evidenced routes", sourceKey: "hr_dominant_path" },
        ]}
      />
    </>
  );
}
