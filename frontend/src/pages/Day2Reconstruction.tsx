import { useState } from "react";
import type { EagerBundle } from "../services/dataService";
import type { Navigate } from "../navigation";
import type { BoundaryMetrics, ExperimentRecord } from "../types";
import { PageHeader } from "../components/PageHeader";
import { MetricCard, Notice, ProvenancePanel } from "../components/common";
import { EvidenceBadge, EvidenceTrace, StatusTag } from "../components/evidence";
import { ScatterChart, type PointTone, type ScatterPoint } from "../components/charts";
import { formatInt, formatNumber, formatPct100 } from "../utils/format";

/**
 * Day 2 -- recovering executions from a continuous event stream. The record below is
 * the order things were actually tried, including everything that failed. Metrics are
 * copied from the Day-2, Day-6 and Day-7 artifacts via investigation.json.
 */

type YMetric = "f1" | "recall";

const TONE: Record<ExperimentRecord["status"], PointTone> = {
  REFERENCE: "reference",
  FAILED: "rejected",
  REJECTED: "rejected",
  PROMISING: "promising",
  "NOT SELECTED": "neutral",
  LOCKED: "locked",
  "NOT PROMOTED": "experimental",
  PASSED: "neutral",
};

const CHART_LABELS: Record<string, string> = {
  combined: "Locked baseline",
  v1: "V1 boundary-first",
  v2: "V2 continuity-first",
  design2: "Design 2",
  C2_rule_plus_continuity_veto: "C2",
  hmm: "HMM",
  ensemble_and: "Ensemble AND",
};

/** Points whose label would collide with a neighbour's are labelled underneath. */
const LABEL_BELOW = new Set(["v2", "design2", "ensemble_and"]);

function MetricsLine({ m }: { m: BoundaryMetrics | null }) {
  if (!m) return <p className="small muted">No pooled metrics in the artifact.</p>;
  const cells: [string, string][] = [
    ["Precision", formatNumber(m.precision)],
    ["Recall", formatNumber(m.recall)],
    ["Boundary F1", formatNumber(m.f1)],
    ["Fragmented", m.pct_gt_executions_fragmented == null ? "not measured" : formatPct100(m.pct_gt_executions_fragmented)],
    ["Under-seg.", formatNumber(m.under_segmentation_rate)],
  ];
  return (
    <dl className="metrics-line">
      {cells.map(([k, v]) => (
        <div key={k}><dt>{k}</dt><dd className="mono">{v}</dd></div>
      ))}
    </dl>
  );
}

function ExperimentCard({ e }: { e: ExperimentRecord }) {
  return (
    <li className={`exp exp-${TONE[e.status]}`}>
      <div className="exp-rail" aria-hidden="true" />
      <div className="exp-body">
        <div className="exp-head">
          <span className="exp-stage small muted">{e.day} · {e.stage}</span>
          <StatusTag status={e.status} />
        </div>
        <h4 className="exp-name">{e.name}</h4>
        <p className="small exp-approach">{e.approach}</p>
        <MetricsLine m={e.metrics} />
        <dl className="exp-outcome">
          <div><dt>Result</dt><dd>{e.result}</dd></div>
          <div><dt>Key failure mode</dt><dd>{e.failure_mode}</dd></div>
          <div><dt>Decision</dt><dd>{e.decision}</dd></div>
        </dl>
      </div>
    </li>
  );
}

export default function Day2Reconstruction({ bundle, navigate }: { bundle: EagerBundle; navigate: Navigate }) {
  const { investigation, datasetAMetrics, meta } = bundle;
  const d2 = investigation.day2;
  const locked = datasetAMetrics.pooled;
  const [yMetric, setYMetric] = useState<YMetric>("f1");

  const day2 = d2.experiments.filter((e) => e.day === "Day 2");
  const later = d2.experiments.filter((e) => e.day !== "Day 2");
  const c2 = d2.day7.candidates.find((c) => c.id === "C2_rule_plus_continuity_veto") ?? null;
  const module2 = d2.module2;

  const plotted = d2.experiments.filter(
    (e) => e.metrics && e.metrics.pct_gt_executions_fragmented != null && e.metrics[yMetric] != null);
  const notPlotted = d2.experiments.filter((e) => !plotted.includes(e));
  const points: ScatterPoint[] = plotted.map((e) => ({
    id: e.id,
    label: CHART_LABELS[e.id] ?? e.name,
    x: e.metrics!.pct_gt_executions_fragmented!,
    y: e.metrics![yMetric]!,
    tone: TONE[e.status],
    showLabel: e.id in CHART_LABELS,
    labelBelow: LABEL_BELOW.has(e.id),
    detail: `${e.name} · ${e.status}`,
  }));
  const yAxis = yMetric === "f1"
    ? { label: "Boundary F1", domain: [0, 0.4] as [number, number], ticks: [0, 0.1, 0.2, 0.3, 0.4], format: (v: number) => v.toFixed(2) }
    : { label: "Boundary recall", domain: [0, 1] as [number, number], ticks: [0, 0.25, 0.5, 0.75, 1], format: (v: number) => v.toFixed(2) };

  return (
    <>
      <PageHeader
        screen="reconstruction"
        title="Day 2 · Reconstruction"
        purpose="Recover coherent business executions from a continuous event stream, measure the result against Dataset A's ground truth, and keep every approach that was tried on the record, including the ones that failed."
        context={`Dataset A · ${d2.problem.n_sessions} sessions · leave-one-session-out`}
      />

      <section className="panel problem" aria-labelledby="d2-problem">
        <h3 id="d2-problem">A · Problem statement</h3>
        <p className="problem-statement">
          Recover coherent business executions from continuous operation logs.
        </p>
        <div className="grid cols-4">
          <MetricCard label="Sessions" value={formatInt(d2.problem.n_sessions)} hint="Dataset A, all with ground truth" />
          <MetricCard label="Transitions" value={formatInt(d2.problem.n_transitions)} hint="places a boundary could go" />
          <MetricCard label="True boundaries" value={formatInt(d2.problem.n_gt_boundaries)} hint="the rare class" />
          <MetricCard label="True executions" value={formatInt(d2.problem.n_gt_executions)} hint="closed ground-truth executions" />
        </div>
        <p className="small muted" style={{ marginTop: 12 }}>
          True boundaries are rare among transitions, so a model that never predicts one would
          look almost perfect on plain accuracy. Precision, recall and F1 on boundary transitions
          are reported instead, together with how many true executions get split or merged.
        </p>
      </section>

      <section className="panel" aria-labelledby="d2-baseline">
        <div className="panel-head">
          <h3 id="d2-baseline">B · Locked baseline (Module 1)</h3>
          <span className="badge-row">
            <EvidenceBadge kind="canonical" />
            <EvidenceBadge kind="limitation" label="IMPERFECT" />
          </span>
        </div>
        <div className="grid cols-3">
          <MetricCard label="Boundary precision" value={formatNumber(locked.precision)} />
          <MetricCard label="Boundary recall" value={formatNumber(locked.recall)} />
          <MetricCard label="Boundary / transition F1" value={formatNumber(locked.f1)}
            hint="Scored on boundary transitions, not overall correctness" />
          <MetricCard label="Fragmented executions" value={formatPct100(locked.pct_gt_executions_fragmented)}
            hint={`${formatInt(locked.n_gt_executions_fragmented)} of ${formatInt(locked.n_gt_executions_total)} contain a false split`} />
          <MetricCard label="Under-segmentation" value={formatNumber(locked.under_segmentation_rate)}
            hint="missed boundaries per true execution" />
          <MetricCard label="Over-segmentation" value={formatNumber(locked.over_segmentation_rate)}
            hint="false boundaries per true execution" />
        </div>
        <Notice kind="warn">
          <strong>Read this as a limitation.</strong> Roughly four in five true executions still
          contain at least one false boundary. The baseline was kept because every alternative
          below was worse on the registered criteria, not because this result is good.
        </Notice>
        <EvidenceTrace
          source={["reports/day2/protected_boundary_experiment_dataset_a.json → systems.Strategy_Combined.pooled",
                   "reports/day2/segmentation_architecture_final.md"]}
          metric="Boundary precision, recall and F1 over all transitions; fragmentation and under/over-segmentation per true execution."
          method="Candidate union of two classifiers, four demote-only rules, and combined protection. Thresholds selected once on Dataset A; evaluated leave-one-session-out."
          limitations="Dataset B has no ground truth, so none of these numbers describe Dataset B."
        />
      </section>

      <section className="panel" aria-labelledby="d2-timeline">
        <h3 id="d2-timeline">C · Experiment timeline</h3>
        <p className="small muted">
          In the order the approaches were tried. Each card states what the approach did, where it
          failed, and what was decided because of it.
        </p>
        <ol className="exp-timeline" aria-label="Day 2 experiments">
          {day2.map((e) => <ExperimentCard key={e.id} e={e} />)}
        </ol>
        <h4 className="subhead">Later challenges to the locked baseline (Day 6 and Day 7)</h4>
        <ol className="exp-timeline" aria-label="Later challenges">
          {later.map((e) => <ExperimentCard key={e.id} e={e} />)}
        </ol>
      </section>

      <section className="panel" aria-labelledby="d2-tradeoff">
        <div className="panel-head">
          <h3 id="d2-tradeoff">D · Trade-off: fragmentation against boundary quality</h3>
          <div className="controls" role="group" aria-label="Vertical axis">
            <button className="btn small-btn" aria-pressed={yMetric === "f1"} onClick={() => setYMetric("f1")}>
              F1 vs fragmentation
            </button>
            <button className="btn small-btn" aria-pressed={yMetric === "recall"} onClick={() => setYMetric("recall")}>
              Recall vs fragmentation
            </button>
          </div>
        </div>
        <p className="small muted">
          Up is better; left is better. Every approach that lowered fragmentation well below the
          locked baseline did it by merging work, which shows up as a drop in F1 and recall. The
          line is the boundary-first classifier&rsquo;s own threshold sweep.
        </p>
        <ScatterChart
          ariaLabel={`${yAxis.label} against fragmented executions for every tested approach`}
          points={points}
          lines={[{
            id: "v1-sweep",
            label: "V1 threshold sweep",
            points: d2.v1_threshold_curve
              .filter((p) => p.pct_gt_executions_fragmented != null && p[yMetric] != null)
              .map((p) => ({ x: p.pct_gt_executions_fragmented!, y: p[yMetric]! })),
          }]}
          x={{ label: "Fragmented executions", domain: [30, 100], ticks: [30, 40, 50, 60, 70, 80, 90, 100], format: (v) => `${v.toFixed(0)}%` }}
          y={yAxis}
          legend={[
            { tone: "locked", label: "Locked baseline" },
            { tone: "rejected", label: "Failed or rejected" },
            { tone: "promising", label: "Promising, superseded" },
            { tone: "neutral", label: "Passed gates, not selected" },
            { tone: "experimental", label: "Experimental, not promoted" },
            { tone: "line", label: "V1 threshold sweep" },
          ]}
        />
        <p className="small muted">
          Not plotted, because the artifact has no fragmentation figure for them:{" "}
          {notPlotted.map((e) => e.name).join(", ") || "none"}. The continuity-first threshold
          sweep is not drawn either: it was scored on labelled transitions only, a different basis
          from every point on this chart.
        </p>
        <details className="trace">
          <summary>Chart data</summary>
          <div className="table-scroll">
            <table aria-label="Trade-off chart data">
              <thead>
                <tr>
                  <th scope="col">Approach</th>
                  <th scope="col">Status</th>
                  <th scope="col" className="num">Fragmented</th>
                  <th scope="col" className="num">F1</th>
                  <th scope="col" className="num">Recall</th>
                </tr>
              </thead>
              <tbody>
                {plotted.map((e) => (
                  <tr key={e.id}>
                    <td>{e.name}</td>
                    <td><StatusTag status={e.status} /></td>
                    <td className="num">{formatPct100(e.metrics!.pct_gt_executions_fragmented)}</td>
                    <td className="num">{formatNumber(e.metrics!.f1)}</td>
                    <td className="num">{formatNumber(e.metrics!.recall)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      </section>

      <section className="panel retained" aria-labelledby="d2-retained">
        <div className="panel-head">
          <h3 id="d2-retained">E · Why the baseline was retained</h3>
          <EvidenceBadge kind="canonical" label={d2.day7.decision} />
        </div>
        <p className="retained-statement">
          The final segmentation baseline was retained because later alternatives did not satisfy
          the pre-registered promotion criteria.
        </p>
        {c2 ? (
          <div className="compare-pair" aria-label="Locked baseline compared with the rejected candidate C2">
            <div className="compare-side keep">
              <span className="compare-title">Locked baseline</span>
              <dl>
                <div><dt>F1</dt><dd className="mono">{formatNumber(locked.f1)}</dd></div>
                <div><dt>Fragmentation</dt><dd className="mono">{formatPct100(locked.pct_gt_executions_fragmented)}</dd></div>
                <div><dt>Under-segmentation</dt><dd className="mono">{formatNumber(locked.under_segmentation_rate)}</dd></div>
              </dl>
            </div>
            <div className="compare-side drop">
              <span className="compare-title">{c2.name} · rejected</span>
              <dl>
                <div><dt>F1</dt><dd className="mono">{formatNumber(c2.metrics.f1)}</dd></div>
                <div><dt>Fragmentation</dt><dd className="mono">{formatPct100(c2.metrics.pct_gt_executions_fragmented)}</dd></div>
                <div><dt>Under-segmentation</dt><dd className="mono">{formatNumber(c2.metrics.under_segmentation_rate)}</dd></div>
              </dl>
            </div>
          </div>
        ) : null}
        <p>
          C2 halves fragmentation, but only by merging distinct executions: under-segmentation is
          several times the baseline&rsquo;s and F1 falls. Lower fragmentation on its own was never
          the objective.
        </p>
        <div className="table-scroll">
          <table aria-label="Day 7 candidates against the pre-registered gates">
            <thead>
              <tr>
                <th scope="col">Candidate</th>
                <th scope="col" className="num">F1</th>
                <th scope="col" className="num">Fragmented</th>
                <th scope="col" className="num">Under-seg.</th>
                <th scope="col">Gates failed</th>
              </tr>
            </thead>
            <tbody>
              <tr className="row-locked">
                <th scope="row">Locked baseline</th>
                <td className="num">{formatNumber(locked.f1)}</td>
                <td className="num">{formatPct100(locked.pct_gt_executions_fragmented)}</td>
                <td className="num">{formatNumber(locked.under_segmentation_rate)}</td>
                <td>reference</td>
              </tr>
              {d2.day7.candidates.map((c) => (
                <tr key={c.id} className={c.id === c2?.id ? "row-highlight" : undefined}>
                  <th scope="row">{c.name}</th>
                  <td className="num">{formatNumber(c.metrics.f1)}</td>
                  <td className="num">{formatPct100(c.metrics.pct_gt_executions_fragmented)}</td>
                  <td className="num">{formatNumber(c.metrics.under_segmentation_rate)}</td>
                  <td className="small">
                    {c.failed_gates.length} of {Object.keys(d2.day7.gates).length}: {c.failed_gate_labels.join(", ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {module2 ? (
          <p className="small">
            <EvidenceBadge kind="not-promoted" /> Module 2 reached F1{" "}
            <span className="mono">{formatNumber(module2.metrics.f1)}</span> against a matched control of{" "}
            <span className="mono">{formatNumber(module2.control_f1)}</span>: a gain of{" "}
            <span className="mono">+{module2.f1_gain.toFixed(4)}</span> where{" "}
            <span className="mono">+{module2.required_gain.toFixed(4)}</span> was required.{" "}
            <button className="linkish" onClick={() => navigate("modules")}>See the Approach Comparison</button>
          </p>
        ) : null}
        <EvidenceTrace
          source={["reports/day7/segmentation_comparison.json", "reports/day7/segmentation_improvement_analysis.md"]}
          metric="Pooled boundary metrics per candidate, under the same evaluation as the baseline."
          method={`${d2.day7.validation}. Gates registered before any candidate was scored; the baseline was reproduced exactly (${d2.day7.baseline_reproduced ? "verified" : "not verified"}).`}
          limitations="Four simple, auditable candidates were tested. A different family of models might behave differently."
        />
      </section>

      <Notice kind="info">
        <strong>Where this leads.</strong> These classifiers were fitted to Dataset A&rsquo;s ground
        truth, so they are not carried over to Dataset B. Day 3 segments Dataset B with its own
        system-identity signal and asks only a comparative question: where does recorded effort
        concentrate?{" "}
        <button className="linkish" onClick={() => navigate("process-mining")}>
          Continue to Day 3 · Process Mining
        </button>
      </Notice>

      <ProvenancePanel
        meta={meta}
        entries={[
          { value: "Locked baseline and Day-2 systems", sourceKey: "dataset_a_metrics" },
          { value: "Temporal and contextual baselines", sourceKey: "day2_baselines" },
          { value: "Boundary-first threshold sweep", sourceKey: "day2_threshold_tradeoff" },
          { value: "HMM and ensemble (Day 6)", sourceKey: "day6_ensemble" },
          { value: "Day-7 candidates and gates", sourceKey: "day7_segmentation" },
        ]}
      />
    </>
  );
}
