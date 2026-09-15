import type { EagerBundle } from "../services/dataService";
import { MetricCard, Notice, ProvenancePanel } from "../components/common";
import { formatDuration, formatNumber, formatPercent } from "../utils/format";
import type { Navigate } from "../navigation";

export default function Dashboard({
  bundle,
  navigate,
}: {
  bundle: EagerBundle;
  navigate: Navigate;
}) {
  const {
    meta, sessions, executionsIndex, processes, opportunities, instrumentation,
    datasetAMetrics, hrPayroll,
  } = bundle;

  const datasetB = sessions.filter((s) => s.dataset === "dataset_b");
  const rankedProcesses = processes.filter((p) => !p.excluded_from_ranking);
  const excludedCount = processes.length - rankedProcesses.length;
  const totalProcessMs = rankedProcesses.reduce((acc, p) => acc + p.total_duration_ms, 0);

  const top = opportunities.ranking[0];
  const topProfile = top ? processes.find((p) => p.process_id === top.process_id) ?? null : null;

  // The deterministic-RPA prototype exists for exactly one process: the one the
  // Day-3 HR forensics identified. Gate the recommendation on that identity
  // rather than on rank, so it cannot leak onto a different top candidate.
  const hrProcessId = hrPayroll.dominant_path?.hr_process_id;
  const evidencedRoutes = Object.keys(hrPayroll.dominant_path?.route_id_prefix_correspondence ?? {});
  const prototypeApplies = !!top && top.process_id === hrProcessId && evidencedRoutes.length > 0;

  const a = instrumentation.dataset_a.summary;
  const b = instrumentation.dataset_b.summary;
  const pooled = datasetAMetrics.pooled;

  return (
    <>
      <header>
        <h2>Dashboard</h2>
        <p className="lede">
          What the Day-1–Day-4 analysis found across the production logs. Every figure is read
          from the generated data bundle; none of it is recalculated here.
        </p>
      </header>

      {/* ---------- headline recommendation ---------- */}
      {top ? (
        <section className="panel headline" aria-labelledby="db-top">
          <div className="headline-head">
            <div>
              <h3 id="db-top" style={{ marginBottom: 6 }}>Top automation opportunity</h3>
              <p className="headline-name">{top.readable_name}</p>
              <p className="small muted" style={{ margin: "2px 0 0" }}>
                Rank {top.rank} of {opportunities.ranking.length}
                {top.pareto_status === "frontier" ? " · Pareto non-dominated" : ""}
                {typeof top.worst_rank === "number"
                  ? ` · never worse than rank ${top.worst_rank} under tested perturbations`
                  : ""}
              </p>
            </div>
            {prototypeApplies ? (
              <div className="rec">
                <span className="badge ok">Deterministic RPA</span>
                <p className="small muted" style={{ margin: "6px 0 0", maxWidth: 260 }}>
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
          </div>

          <p className="small muted" style={{ marginTop: 12 }}>
            Canonical source: <span className="mono">{opportunities.canonical_source}</span>.{" "}
            {opportunities.canonical_note}
          </p>
        </section>
      ) : (
        <Notice kind="warn">No ranking rows in the bundle.</Notice>
      )}

      {/* ---------- scope ---------- */}
      <section className="panel" aria-labelledby="db-scope">
        <h3 id="db-scope">Dataset B — production data analysed</h3>
        <div className="grid cols-4">
          <MetricCard label="Sessions" value={datasetB.length} hint="Dataset B, no ground truth" />
          <MetricCard label="Executions recovered" value={executionsIndex.length} />
          <MetricCard label="Ranked processes" value={rankedProcesses.length}
            hint={`${excludedCount} further processes excluded from ranking`} />
          <MetricCard label="Total recorded process time" value={formatDuration(totalProcessMs)}
            hint="Sum of ranked processes' measured durations" />
        </div>
      </section>

      {/* ---------- instrumentation ---------- */}
      <section className="panel" aria-labelledby="db-health">
        <h3 id="db-health">Instrumentation health (Day-4 diagnostic)</h3>
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
                    {key === "dataset_b" && summary.n_degraded > 0 ? " — click to inspect" : ""}
                  </div>
                </div>
              </div>
              {summary.degraded_session_ids.length ? (
                <p className="small muted wrap-any" style={{ marginBottom: 0 }}>
                  {summary.degraded_session_ids.slice(0, 2).join(", ")}
                  {summary.degraded_session_ids.length > 2
                    ? ` +${summary.degraded_session_ids.length - 2} more`
                    : ""}
                </p>
              ) : null}
            </div>
          ))}
        </div>

        <div className="grid cols-2" style={{ marginTop: 12 }}>
          <MetricCard label="Min distinct domains" value={a.thresholds.min_distinct_browser_domains}
            hint="Threshold owned by procmine.instrumentation_health" />
          <MetricCard label="Min domain coverage"
            value={formatPercent(a.thresholds.min_browser_domain_coverage, 0)}
            hint="Threshold owned by procmine.instrumentation_health" />
        </div>

        <Notice kind="info">
          <strong>Instrumentation quality is not segmentation quality.</strong> Degraded
          instrumentation means some segmentation evidence is unavailable in that session; it does
          not by itself prove segmentation failure. Day 4 established the diagnostic detects
          missing instrumentation, not every possible cause of poor segmentation.
        </Notice>
      </section>

      {/* ---------- Dataset A quality ---------- */}
      <section className="panel" aria-labelledby="db-quality">
        <h3 id="db-quality">Dataset A — segmentation quality (locked Day-2 architecture)</h3>
        <div className="grid cols-3">
          <MetricCard label="Precision" value={formatNumber(pooled.precision)} />
          <MetricCard label="Recall" value={formatNumber(pooled.recall)} />
          <MetricCard label="Boundary F1" value={formatNumber(pooled.f1)}
            hint="Transition-level F1, not 'accuracy'" />
          <MetricCard label="Executions fragmented"
            value={formatPercent(pooled.pct_gt_executions_fragmented / 100)}
            hint={`${pooled.n_gt_executions_fragmented} of ${pooled.n_gt_executions_total}`} />
          <MetricCard label="Under-segmentation" value={formatNumber(pooled.under_segmentation_rate)} />
          <MetricCard label="Over-segmentation" value={formatNumber(pooled.over_segmentation_rate)} />
        </div>
        <Notice kind="info">
          Dataset A is shown as aggregate quality only. It has no replay view: the locked pipeline
          is evaluated but never serialises its predicted boundaries, so there is nothing to
          replay without changing that pipeline.
        </Notice>
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
