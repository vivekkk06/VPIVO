import type { EagerBundle } from "../services/dataService";
import type { Navigate, ScreenId } from "../navigation";
import { formatNumber } from "../utils/format";

/**
 * The six stages of the investigation, each linking to the screen that holds its
 * evidence. A tick means "this stage was carried out", never "this stage worked":
 * the outcome line says what was actually found, weak results included.
 */
export function InvestigationProgress({
  bundle,
  navigate,
}: {
  bundle: EagerBundle;
  navigate: Navigate;
}) {
  const { investigation, datasetAMetrics, opportunities, executionsIndex, moduleComparison } = bundle;
  const a = investigation.day1.datasets.dataset_a;
  const aChecks = investigation.day1.checks.dataset_a;
  const top = opportunities.ranking[0];
  const challengers = investigation.day2.day7.candidates.filter((c) => !c.passes_all_gates).length;
  const module2 = moduleComparison?.module2.status ?? null;

  const stages: { key: string; label: string; verb: string; outcome: string; target: ScreenId }[] = [
    {
      key: "audit", label: "Data audit", verb: "Investigated", target: "data-audit",
      outcome: `${aChecks.sessions_with_out_of_order_pairs}/${a.sessions} sessions needed re-sorting; redaction gap found`,
    },
    {
      key: "reconstruction", label: "Reconstruction", verb: "Tested", target: "reconstruction",
      outcome: `Imperfect: boundary F1 ${formatNumber(datasetAMetrics.pooled.f1)}`,
    },
    {
      key: "discovery", label: "Process discovery", verb: "Measured", target: "process-mining",
      outcome: `${opportunities.ranking.length} processes ranked from ${executionsIndex.length} executions`,
    },
    {
      key: "opportunity", label: "Opportunity", verb: "Decided", target: "opportunities",
      outcome: top ? `${top.readable_name} · ${formatNumber(top.opportunity)}` : "No ranking in bundle",
    },
    {
      key: "automation", label: "Automation", verb: "Built", target: "automation",
      outcome: "Local prototype with human review",
    },
    {
      key: "validation", label: "Validation", verb: "Challenged", target: "modules",
      outcome: `${module2 ? "Module 2 not promoted; " : ""}${challengers} Day-7 challengers rejected`,
    },
  ];

  return (
    <section className="panel progress-panel" aria-labelledby="db-progress">
      <div className="panel-head">
        <h3 id="db-progress">Investigation progress</h3>
        <p className="small muted">
          A tick means the stage was carried out, not that it succeeded. Each outcome is stated
          as found. Select a stage to open its evidence.
        </p>
      </div>
      <ol className="progress">
        {stages.map((s, i) => (
          <li key={s.key}>
            <button className="progress-btn" onClick={() => navigate(s.target)}>
              <span className="progress-top">
                <span className="progress-index mono" aria-hidden="true">{i + 1}</span>
                <span className="progress-label">{s.label}</span>
              </span>
              <span className="progress-verb"><span aria-hidden="true">✓ </span>{s.verb}</span>
              <span className="progress-outcome">{s.outcome}</span>
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}
