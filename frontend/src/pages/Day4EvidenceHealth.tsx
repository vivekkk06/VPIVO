import type { EagerBundle } from "../services/dataService";
import type { Navigate } from "../navigation";
import type { Distribution5 } from "../types";
import { PageHeader } from "../components/PageHeader";
import { MetricCard, Notice, ProvenancePanel } from "../components/common";
import { CoverageStrip } from "../components/charts";
import { EvidenceBadge, EvidenceTrace } from "../components/evidence";
import { formatInt, formatNumber, formatPct100, formatPercent } from "../utils/format";

/**
 * Day 4 -- was poor segmentation caused by the algorithm, or by missing evidence in
 * the logs? A two-signal diagnostic, evaluated against Dataset A's ground truth and
 * then carried to Dataset B as a sensitivity check. Machine host names are replaced by
 * letters: they add nothing to the evidence.
 */

function CompareRow({ label, flagged, healthy, format, note }: {
  label: string; flagged: Distribution5; healthy: Distribution5;
  format: (v: number) => string; note: string;
}) {
  return (
    <tr>
      <th scope="row">{label}</th>
      <td className="num">{format(flagged.median)}</td>
      <td className="num small muted">{format(flagged.min)} – {format(flagged.max)}</td>
      <td className="num">{format(healthy.median)}</td>
      <td className="num small muted">{format(healthy.min)} – {format(healthy.max)}</td>
      <td className="small">{note}</td>
    </tr>
  );
}

export default function Day4EvidenceHealth({ bundle, navigate }: { bundle: EagerBundle; navigate: Navigate }) {
  const { meta, investigation, instrumentation, instrumentationSensitivity: sens } = bundle;
  const d4 = investigation.day4;
  const doc = investigation.documented;
  const ag = d4.agreement;
  const t = d4.thresholds;
  const sa = d4.summary.dataset_a;
  const sb = d4.summary.dataset_b;
  const worstMachine = [...d4.machines_a].sort((x, y) => y.flagged - x.flagged)[0];
  const hrCompare = sens.ranking_comparison.find((r) => r.rank_case_a === 1) ?? null;

  const strip = (rows: typeof instrumentation.dataset_a.per_session) => rows.map((s, i) => ({
    id: `s${i}`,
    value: s.browser_domain_coverage,
    flagged: s.status === "degraded",
    detail: `coverage ${(s.browser_domain_coverage * 100).toFixed(2)}% · ${s.n_distinct_browser_domains} domains · ${s.status}`,
  }));

  return (
    <>
      <PageHeader
        screen="evidence-health"
        title="Day 4 · Evidence Health"
        purpose="Check whether some segmentation failures come from the logs rather than the algorithm: sessions where the browser signal the method relies on was barely recorded."
        context="Dataset A (ground truth used only to evaluate) + Dataset B (sensitivity check) · diagnostic only"
      />

      <section className="panel problem" aria-labelledby="d4-hypothesis">
        <div className="panel-head">
          <h3 id="d4-hypothesis">A · Hypothesis</h3>
          <EvidenceBadge kind="observed" label="DIAGNOSTIC" />
        </div>
        <p className="problem-statement">{d4.question}</p>
        <p>
          On normally instrumented sessions, {doc.domain_change_share.value} of true boundaries coincide
          with a change of browser domain, so a session that barely records browser domains loses the
          strongest boundary cue. Two signals, computed without any ground truth, flag such sessions:
        </p>
        <div className="grid cols-2">
          <MetricCard label="Minimum browser-domain coverage" value={formatPercent(t.min_browser_domain_coverage, 0)}
            hint={`Sits in the ${doc.coverage_gap.value} gap of Dataset A, ${doc.coverage_margin.value} from the nearest healthy session`} />
          <MetricCard label="Minimum distinct browser domains" value={t.min_distinct_browser_domains}
            hint="Structural: normal sessions touch several internal systems" />
        </div>
        <EvidenceTrace
          source={[doc.domain_change_share.source, "src/procmine/instrumentation_health.py"]}
          metric="Share of events carrying a browser domain, and the number of distinct domains, per session."
          method="Thresholds chosen from gaps in the Dataset-A distribution, not fitted to segmentation scores."
          limitations="Both thresholds come from Dataset A."
        />
      </section>

      <section className="panel" aria-labelledby="d4-coverage">
        <h3 id="d4-coverage">B · Signal coverage</h3>
        <div className="grid cols-2">
          <div className="health-card">
            <div className="health-head">
              <span className="label">Dataset A</span>
              <span className="muted small">{sa.n_sessions} sessions</span>
            </div>
            <p className="flag-ratio"><span className="mono">{sa.n_degraded}/{sa.n_sessions}</span> flagged</p>
            <CoverageStrip ariaLabel={`Browser-domain coverage for ${sa.n_sessions} Dataset-A sessions; ${sa.n_degraded} flagged`}
              rows={strip(instrumentation.dataset_a.per_session)} threshold={t.min_browser_domain_coverage} />
          </div>
          <div className="health-card">
            <div className="health-head">
              <span className="label">Dataset B</span>
              <span className="muted small">{sb.n_sessions} sessions</span>
            </div>
            <p className="flag-ratio"><span className="mono">{sb.n_degraded}/{sb.n_sessions}</span> flagged</p>
            <CoverageStrip ariaLabel={`Browser-domain coverage for ${sb.n_sessions} Dataset-B sessions; ${sb.n_degraded} flagged`}
              rows={strip(instrumentation.dataset_b.per_session)} threshold={t.min_browser_domain_coverage} />
          </div>
        </div>
        <p className="legend-inline small muted">
          <span><svg width="12" height="12" aria-hidden="true"><circle cx="6" cy="6" r="4" className="dot-healthy" /></svg> healthy session</span>
          <span><svg width="12" height="12" aria-hidden="true"><path d="M6,1L11,10L1,10Z" className="dot-flagged" /></svg> flagged session</span>
          <span>A flagged session can sit above the coverage line when it records only one domain.</span>
        </p>
      </section>

      <section className="panel" aria-labelledby="d4-machines">
        <h3 id="d4-machines">C · Machine-level evidence</h3>
        <p className="small muted">
          Machines are shown as letters; host names are not needed for this evidence. The same
          letter means the same machine in both datasets.
        </p>
        <div className="grid cols-2">
          <div className="table-scroll">
            <table aria-label="Dataset A sessions per machine">
              <caption className="small muted">Dataset A</caption>
              <thead>
                <tr><th scope="col">Machine</th><th scope="col" className="num">Sessions</th><th scope="col" className="num">Flagged</th></tr>
              </thead>
              <tbody>
                {d4.machines_a.map((m) => (
                  <tr key={m.label} className={m.flagged && m.flagged === m.sessions ? "row-highlight" : undefined}>
                    <th scope="row">{m.label}</th>
                    <td className="num">{m.sessions}</td>
                    <td className="num">{m.flagged}{m.flagged && m.flagged === m.sessions ? " (all)" : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="table-scroll">
            <table aria-label="Dataset B sessions per machine">
              <caption className="small muted">Dataset B</caption>
              <thead>
                <tr><th scope="col">Machine</th><th scope="col" className="num">Sessions</th><th scope="col" className="num">Flagged</th></tr>
              </thead>
              <tbody>
                {d4.machines_b.map((m) => (
                  <tr key={m.label}>
                    <th scope="row">{m.label}</th>
                    <td className="num">{m.sessions}</td>
                    <td className="num">{m.flagged}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        {worstMachine ? (
          <p>
            <strong>{worstMachine.label}</strong> accounts for {worstMachine.flagged} of the {sa.n_degraded} flagged
            Dataset-A sessions: every session it recorded. That points at the capture setup on one
            machine rather than at the segmentation method.
          </p>
        ) : null}
      </section>

      <section className="panel" aria-labelledby="d4-discovery">
        <div className="panel-head">
          <h3 id="d4-discovery">D · Key discovery: missing evidence merges work</h3>
          <EvidenceBadge kind="observed" />
        </div>
        <p className="lede-strong">
          Degraded instrumentation was associated with merged work (under-segmentation), not with
          more splitting.
        </p>
        <div className="table-scroll">
          <table aria-label="Flagged versus healthy Dataset-A sessions">
            <thead>
              <tr>
                <th scope="col">Locked-baseline metric</th>
                <th scope="col" className="num">Flagged median ({ag.flagged_f1.n})</th>
                <th scope="col" className="num">Flagged range</th>
                <th scope="col" className="num">Healthy median ({ag.healthy_f1.n})</th>
                <th scope="col" className="num">Healthy range</th>
                <th scope="col">Reading</th>
              </tr>
            </thead>
            <tbody>
              <CompareRow label="Boundary F1" flagged={ag.flagged_f1} healthy={ag.healthy_f1}
                format={(v) => formatNumber(v)} note="Lower when the browser signal is missing." />
              <CompareRow label="Under-segmentation" flagged={ag.flagged_under_segmentation} healthy={ag.healthy_under_segmentation}
                format={(v) => formatNumber(v)} note="The only metric with no overlap at all: distinct executions are merged." />
              <CompareRow label="Over-segmentation" flagged={ag.flagged_over_segmentation} healthy={ag.healthy_over_segmentation}
                format={(v) => formatNumber(v)} note="Lower: with fewer cues, fewer boundaries are proposed at all." />
              <CompareRow label="Fragmented executions" flagged={ag.flagged_pct_fragmented} healthy={ag.healthy_pct_fragmented}
                format={(v) => formatPct100(v)} note="Also lower, for the same reason. Not a sign of better segmentation." />
            </tbody>
          </table>
        </div>
        <div className="grid cols-4" style={{ marginTop: 12 }}>
          <MetricCard label="Flagged and poor" value={ag.confusion.tp} hint="true positives" />
          <MetricCard label="Flagged but fine" value={ag.confusion.fp} hint="false positives" />
          <MetricCard label="Poor but not flagged" value={ag.confusion.fn} hint="well instrumented, still poor" />
          <MetricCard label="Sensitivity / specificity"
            value={`${formatNumber(ag.sensitivity, 2)} / ${formatNumber(ag.specificity, 2)}`}
            hint={`poor = F1 below ${formatNumber(ag.poor_performance_cut_f1)}`} />
        </div>
        <p className="small muted">
          &ldquo;Poor&rdquo; is defined as the {ag.poor_cut_derivation.toLowerCase()} ({formatNumber(ag.poor_performance_cut_f1)}). {ag.interpretation_caveat}
        </p>
        <EvidenceTrace
          source="reports/day4/instrumentation_health_dataset_a.json → baseline_agreement"
          metric="Per-session locked-baseline metrics, grouped by the diagnostic's flag."
          method={ag.note}
          limitations={ag.interpretation_caveat}
        />
      </section>

      <section className="panel" aria-labelledby="d4-downstream">
        <h3 id="d4-downstream">E · Does it change the decision?</h3>
        <p>
          The {sb.n_degraded} flagged Dataset-B sessions were removed and the whole Day-3 chain re-run on
          what remained ({formatInt(sens.executions_total)} → {formatInt(sens.executions_kept)} executions).
        </p>
        <div className="grid cols-3">
          <MetricCard label="Top candidate, all sessions" value={sens.top_candidate_case_a}
            hint={hrCompare ? `Opportunity ${formatNumber(hrCompare.opportunity_a)}` : undefined} />
          <MetricCard label="Top candidate, flagged removed" value={sens.top_candidate_case_b}
            hint={hrCompare && hrCompare.opportunity_b != null ? `Opportunity ${formatNumber(hrCompare.opportunity_b)}` : undefined} />
          <MetricCard label="Top candidate unchanged" value={sens.top_candidate_unchanged ? "Yes" : "No"}
            hint="the exact score moves; the selection does not" />
        </div>
        <div className="controls" style={{ marginTop: 12 }}>
          <button className="btn" onClick={() => navigate("replay", { degradedOnly: true })}>
            Inspect the flagged Dataset-B sessions
          </button>
        </div>
      </section>

      <section className="panel limits" aria-labelledby="d4-limits">
        <div className="panel-head">
          <h3 id="d4-limits">F · Diagnostic limitations</h3>
          <EvidenceBadge kind="limitation" />
        </div>
        <ul className="plain-list">
          {d4.limitations.map((l) => <li key={l}>{l}</li>)}
        </ul>
      </section>

      <Notice kind="info">
        <strong>Where this leads.</strong> With the evidence gaps understood, the decision can be
        made on the processes whose evidence holds up.{" "}
        <button className="linkish" onClick={() => navigate("decision")}>
          Open the Automation Decision Center
        </button>
      </Notice>

      <ProvenancePanel
        meta={meta}
        entries={[
          { value: "Diagnostic and agreement (Dataset A)", sourceKey: "health_a" },
          { value: "Diagnostic (Dataset B)", sourceKey: "health_b" },
          { value: "Decision sensitivity", sourceKey: "day4_sensitivity" },
        ]}
      />
    </>
  );
}
