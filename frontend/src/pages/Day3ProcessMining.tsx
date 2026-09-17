import { useMemo, useState } from "react";
import type { EagerBundle } from "../services/dataService";
import type { Navigate } from "../navigation";
import { PageHeader } from "../components/PageHeader";
import { MetricCard, Notice, ProvenancePanel } from "../components/common";
import { DfgFlow } from "../components/DfgFlow";
import { BarList } from "../components/charts";
import { EvidenceBadge, EvidenceTrace } from "../components/evidence";
import { formatDuration, formatInt, formatNumber, formatPercent } from "../utils/format";

/**
 * Day 3 -- from "what is in the logs" to "what work is being done". Dataset B has no
 * ground truth, so everything here is comparative: which process concentrates recorded
 * effort, and which of those has a pattern bounded enough to automate.
 */

type Measure = "executions" | "time";

export default function Day3ProcessMining({ bundle, navigate }: { bundle: EagerBundle; navigate: Navigate }) {
  const { meta, processes, variants, executionsIndex, opportunities, hrPayroll, investigation, instrumentation } = bundle;
  const [measure, setMeasure] = useState<Measure>("executions");
  const doc = investigation.documented;
  const pm = investigation.day3.process_metrics;

  const ranked = useMemo(() => processes.filter((p) => !p.excluded_from_ranking), [processes]);
  const excluded = processes.length - ranked.length;
  const hrId = hrPayroll.dominant_path.hr_process_id;
  const hr = processes.find((p) => p.process_id === hrId) ?? null;
  const hrRank = opportunities.ranking.find((r) => r.process_id === hrId) ?? null;
  const split = hrPayroll.variant_split;
  const total = hrPayroll.dominant_path.n_hr_executions_total;

  const bars = useMemo(() => [...ranked]
    .sort((a, b) => measure === "executions"
      ? b.execution_count - a.execution_count
      : b.total_duration_ms - a.total_duration_ms)
    .map((p) => ({
      id: p.process_id,
      label: p.readable_name,
      value: measure === "executions" ? p.execution_count : p.total_duration_ms,
      highlight: p.process_id === hrId,
      note: p.process_id === hrId ? "· selected" : undefined,
    })), [ranked, measure, hrId]);

  const variantRows = useMemo(() => [...ranked]
    .sort((a, b) => b.execution_count - a.execution_count)
    .slice(0, 10), [ranked]);

  // Counts read from the HR forensic artifact's own click-target and input maps.
  const dva = hrPayroll.dominant_path.dominant_variant_analysis ?? {};
  const clicks = dva.click_target_frequency ?? {};
  const noteClicks = Object.entries(clicks).filter(([k]) => k.includes("-note|")).reduce((s, [, v]) => s + v, 0);
  const okClicks = Object.entries(clicks).filter(([k]) => k.startsWith("btn-")).reduce((s, [, v]) => s + v, 0);
  const pastes = dva.form_input_method_distribution?.paste ?? 0;
  const routes = Object.keys(hrPayroll.dominant_path.route_id_prefix_correspondence ?? {});
  const starts = Object.values(hrPayroll.dfg.start_activities).reduce((s, v) => s + v, 0);

  const pipeline: { step: string; what: string; count: string }[] = [
    { step: "Executions", what: "Dataset B segmented on system-identity changes, with short leave-and-return trips merged back", count: `${executionsIndex.length} executions` },
    { step: "Traces", what: "Each execution as its ordered sequence of systems and applications", count: `${executionsIndex.length} traces` },
    { step: "Variants", what: "Distinct trace signatures per process", count: `${variants.length} variant rows` },
    { step: "Directly-follows graph", what: "Which context follows which, with counts and probabilities", count: `HR: ${hrPayroll.dfg.n_edges} edges` },
    { step: "Operational metrics", what: "Frequency, recorded time, manual share, variant entropy, automation surface", count: `${processes.length} contexts` },
    { step: "Feasibility", what: "Determinism, low variability, automation surface, low complexity risk", count: "per process" },
    { step: "Impact", what: "Frequency, recorded time and manual involvement", count: "per process" },
    { step: "Opportunity", what: "Impact × Feasibility, plus Pareto and sensitivity checks", count: `${opportunities.ranking.length} ranked` },
  ];

  return (
    <>
      <PageHeader
        screen="process-mining"
        title="Day 3 · Process Mining"
        purpose="Turn recovered executions into processes, variants and flows, then ask where recorded effort concentrates and which process has a pattern bounded enough to automate."
        context={`Dataset B · ${instrumentation.dataset_b.summary.n_sessions} sessions · no ground truth · comparative evidence only`}
      />

      <section className="panel" aria-labelledby="d3-overview">
        <div className="panel-head">
          <h3 id="d3-overview">A · Dataset B overview</h3>
          <EvidenceBadge kind="observed" />
        </div>
        <div className="grid cols-4">
          <MetricCard label="Sessions" value={instrumentation.dataset_b.summary.n_sessions} hint="no ground truth" />
          <MetricCard label="Recovered executions" value={formatInt(executionsIndex.length)} hint="segments.jsonl, 1:1 with the bundle" />
          <MetricCard label="Ranked processes" value={opportunities.ranking.length}
            hint={`${processes.length} contexts found; ${excluded} excluded from ranking`} />
          <MetricCard label="Selected process"
            value={hrRank ? `#${hrRank.rank}` : "—"}
            hint={hr ? `${hr.readable_name} · Opportunity ${formatNumber(hrRank?.opportunity)}` : undefined} />
        </div>
        <Notice kind="info">
          Dataset A&rsquo;s classifiers were not reused here: they were fitted to Dataset A&rsquo;s
          ground truth, and Dataset B has none. Dataset B was segmented with its own
          system-identity signal, and the result is used only to compare processes with each other.
        </Notice>
      </section>

      <section className="panel" aria-labelledby="d3-pipeline">
        <h3 id="d3-pipeline">B · Process discovery pipeline</h3>
        <ol className="pipeline">
          {pipeline.map((p, i) => (
            <li key={p.step} className="pipeline-step">
              <span className="pipeline-n mono" aria-hidden="true">{String(i + 1).padStart(2, "0")}</span>
              <span className="pipeline-name">{p.step}</span>
              <span className="pipeline-what small muted">{p.what}</span>
              <span className="pipeline-count mono small">{p.count}</span>
            </li>
          ))}
        </ol>
        <EvidenceTrace
          source={[doc.impact_formula.source, "src/procmine/process_discovery/opportunity_scoring.py"]}
          metric={<>
            <span className="mono block">{doc.impact_formula.value}</span>
            <span className="mono block">{doc.feasibility_formula.value}</span>
            <span className="mono block">{doc.opportunity_formula.value}</span>
            <span className="mono block">{doc.surface_formula.value}</span>
          </>}
          method="Each component min-max normalised across the ranked processes, equal weights. Variant entropy enters Feasibility normalised as H/H_max, which is the entropy fix recorded on Day 3."
          limitations="Relative scores between these 21 processes only. They are not probabilities and not a monetary estimate."
          summary="View scoring method"
        />
      </section>

      <section className="panel" aria-labelledby="d3-distribution">
        <div className="panel-head">
          <h3 id="d3-distribution">C · Where recorded work concentrates</h3>
          <div className="controls" role="group" aria-label="Bar measure">
            <button className="btn small-btn" aria-pressed={measure === "executions"} onClick={() => setMeasure("executions")}>
              Executions
            </button>
            <button className="btn small-btn" aria-pressed={measure === "time"} onClick={() => setMeasure("time")}>
              Recorded time
            </button>
          </div>
        </div>
        <BarList
          ariaLabel={measure === "executions" ? "Executions per ranked process" : "Recorded time per ranked process"}
          rows={bars}
          format={(v) => (measure === "executions" ? formatInt(v) : formatDuration(v))}
        />
        <p className="small muted">
          Financial Accounting has slightly more executions than HR / Payroll, but HR carries the
          most recorded time. Recorded time is observed session time, not a validated production
          cycle time.
        </p>
      </section>

      <section className="panel" aria-labelledby="d3-variants">
        <h3 id="d3-variants">D · Variant analysis</h3>
        <p className="small muted">
          The ten most frequent ranked processes. A high dominant share and low entropy mean the
          work repeats in the same shape, which is what a deterministic automation needs.
        </p>
        <div className="table-scroll">
          <table aria-label="Variant concentration per process">
            <thead>
              <tr>
                <th scope="col">Process</th>
                <th scope="col" className="num">Executions</th>
                <th scope="col" className="num">Variants</th>
                <th scope="col" className="num">Dominant share</th>
                <th scope="col" className="num">Entropy (bits)</th>
                <th scope="col" className="num">Automation surface</th>
                <th scope="col" className="num">Time share</th>
              </tr>
            </thead>
            <tbody>
              {variantRows.map((p) => {
                const m = pm[p.process_id];
                return (
                  <tr key={p.process_id} className={p.process_id === hrId ? "row-highlight" : undefined}>
                    <th scope="row" className="wrap-any">{p.readable_name}</th>
                    <td className="num">{p.execution_count}</td>
                    <td className="num">{p.n_variants}</td>
                    <td className="num">{formatPercent(p.dominant_variant_share, 2)}</td>
                    <td className="num">{m ? formatNumber(m.variant_entropy) : "—"}</td>
                    <td className="num">{m ? formatNumber(m.automation_surface) : "—"}</td>
                    <td className="num">{m ? formatPercent(m.time_share, 1) : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="small muted">
          Entropy is shown raw, in bits. Processes with more variants can have more entropy, so
          Feasibility uses it normalised by its maximum; for HR / Payroll that is{" "}
          {doc.hr_normalized_entropy.value}.
        </p>
      </section>

      <section className="panel" aria-labelledby="d3-dfg">
        <div className="panel-head">
          <h3 id="d3-dfg">E · HR / Payroll: how the work flows</h3>
          <EvidenceBadge kind="observed" />
        </div>
        <div className="grid cols-2 dfg-grid">
          <div>
            <h4 className="subhead">Dominant path, inside the HR system</h4>
            <p className="small muted">
              The dominant path never leaves the HR system, so it does not appear as an edge
              between applications. Its steps come from the DOM-level forensics of the{" "}
              {split.dominant.n} dominant-path executions.
            </p>
            <ol className="path-flow">
              <li><span className="path-step">Open the HR system</span><span className="mono small">{starts} execution starts</span></li>
              <li><span className="path-step">Open one of {routes.length} evidenced routes</span><span className="mono small wrap-any">{routes.join(" · ")}</span></li>
              <li><span className="path-step">Click the note field</span><span className="mono small">{noteClicks} clicks</span></li>
              <li><span className="path-step">Paste the note</span><span className="mono small">{pastes} pastes, no typing</span></li>
              <li>
                <span className="path-step">Click OK <EvidenceBadge kind="inferred" label="INFERRED FROM DOM" /></span>
                <span className="mono small">{okClicks} clicks · treated as the confirmation</span>
              </li>
            </ol>
          </div>
          <div>
            <h4 className="subhead">
              Directly-follows graph across applications — top {hrPayroll.dfg.top_edges.length} of {hrPayroll.dfg.n_edges} edges
            </h4>
            <DfgFlow edges={hrPayroll.dfg.top_edges} shown={hrPayroll.dfg.top_edges.length} total={hrPayroll.dfg.n_edges} />
          </div>
        </div>
        <p className="small muted">
          The heaviest cross-application loop is HR → Word → HR: the Word detour, deliberately left
          outside the automation boundary.
        </p>
      </section>

      <section className="panel headline" aria-labelledby="d3-hr">
        <div className="panel-head">
          <h3 id="d3-hr">F · HR / Payroll evidence</h3>
          <EvidenceBadge kind="canonical" />
        </div>
        <div className="grid cols-4">
          <MetricCard label="Executions" value={total} hint={hr ? `${Object.keys(hr.frequency_by_operator).length} operators` : undefined} />
          <MetricCard label="Dominant deterministic path" value={split.dominant.n}
            hint={`${formatPercent(split.dominant.share, 2)} of ${total}`} />
          <MetricCard label="Word detours" value={split.word_detour.n}
            hint={`${formatPercent(split.word_detour.share, 2)} · outside the boundary`} />
          <MetricCard label="Rare multi-hop" value={split.rare_edge.n}
            hint={`${formatPercent(split.rare_edge.share, 2)} · outside the boundary`} />
        </div>
        <div className="grid cols-3" style={{ marginTop: 12 }}>
          <MetricCard label="Dominant-path share" value={formatPercent(split.dominant.share, 2)} />
          <MetricCard label="Time share" value={pm[hrId] ? formatPercent(pm[hrId].time_share, 1) : "—"}
            hint="largest of the 21 ranked processes" />
          <MetricCard label="Recorded time" value={hr ? formatDuration(hr.total_duration_ms) : "—"}
            hint={hr ? `${formatNumber(hr.total_human_hours, 4)} h in this sample` : undefined} />
        </div>
        <EvidenceTrace
          source={["reports/day3/hr_payroll_dominant_path_dataset_b.json → variant_split",
                   "reports/day3/process_profiles_dataset_b.json",
                   "reports/day3/problem2_process_mining_full_results.json → process_metrics"]}
          metric="Forensic split of every HR execution into dominant path, Word detour and rare multi-hop."
          method="DOM-level click, input and route evidence per execution; a different classification from the generic variant signatures."
          limitations="No ground truth for Dataset B. The note text itself is not observable."
        />
      </section>

      <section className="panel" aria-labelledby="d3-why">
        <h3 id="d3-why">G · Why this matters</h3>
        <p className="lede-strong">
          High volume alone is insufficient. The target also needs a bounded and repetitive
          interaction pattern.
        </p>
        <ul className="plain-list">
          <li>HR / Payroll is not the most frequent process, but it concentrates the most recorded time.</li>
          <li>Most of its executions follow one short path through a known set of routes, with the note pasted rather than typed.</li>
          <li>The exceptions (Word detours and rare multi-hop cases) are identifiable, so they can be left to a person instead of being partially automated.</li>
          <li>It is not the most feasible process: the Excel workbooks score higher on Feasibility but carry little recorded time.</li>
        </ul>
        <div className="controls">
          <button className="btn primary" onClick={() => navigate("decision")}>Open the decision record</button>
          <button className="btn" onClick={() => navigate("opportunities")}>See the full ranking</button>
          <button className="btn" onClick={() => navigate("processes", { processId: hrId })}>Explore HR in detail</button>
          <button className="btn" onClick={() => navigate("evidence-health")}>Continue to Day 4 · Evidence Health</button>
        </div>
      </section>

      <ProvenancePanel
        meta={meta}
        entries={[
          { value: "Executions", sourceKey: "executions" },
          { value: "Process profiles and variants", sourceKey: "profiles" },
          { value: "Operational metrics and HR DFG", sourceKey: "mining_full" },
          { value: "HR forensic split", sourceKey: "hr_dominant_path" },
          { value: "Ranking", sourceKey: "audit" },
        ]}
      />
    </>
  );
}
