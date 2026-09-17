import { useMemo, useState } from "react";
import { PageHeader } from "../components/PageHeader";
import type { EagerBundle } from "../services/dataService";
import { MetricCard, Notice, ProvenancePanel } from "../components/common";
import { EvidenceBadge, type EvidenceKind } from "../components/evidence";
import { formatDuration, formatNumber, formatPercent } from "../utils/format";
import type { Navigate } from "../navigation";

/**
 * Automation Decision Center.
 *
 * Presentation layer only. Every value shown is read from the generated
 * bundle; nothing is scored, weighted, or recomputed here. The readiness
 * state is NOT a classifier and NOT a weighted score -- it is a small set of
 * explicit boolean gates, each naming the artifact it reads, rendered so a
 * reviewer can see exactly which gate produced the status.
 */

type GateState = "pass" | "warn" | "unavailable";

interface Gate {
  id: string;
  label: string;
  state: GateState;
  detail: string;
  source: string;
}

interface EvidenceItem {
  id: string;
  headline: string;
  observed: string;
  why: string;
  sourceFile: string;
  sourceField?: string;
  available: boolean;
  /** What kind of claim this item is, shown as a badge next to the headline. */
  kind: EvidenceKind;
  kindLabel?: string;
  action?: { label: string; run: () => void };
}

/** Presentation threshold, stated in the UI: a path followed by more than
 *  half of observed executions is described as the "dominant" path. This is
 *  a display rule for this screen, not an analytical threshold. */
const MAJORITY = 0.5;

export default function DecisionCenter({
  bundle,
  navigate,
}: {
  bundle: EagerBundle;
  navigate: Navigate;
}) {
  const {
    meta, opportunities, processes, hrPayroll, instrumentation,
    instrumentationSensitivity, executionsIndex,
    engineeringUpgrade: upgrade,
  } = bundle;

  const ranking = opportunities.ranking;
  const defaultProcessId = ranking[0]?.process_id ?? "";
  const [processId, setProcessId] = useState<string>(defaultProcessId);
  const [openEvidence, setOpenEvidence] = useState<string>("");

  const opp = ranking.find((r) => r.process_id === processId) ?? ranking[0] ?? null;
  const profile = processes.find((p) => p.process_id === processId) ?? null;

  const hrProcessId = hrPayroll.dominant_path?.hr_process_id;
  const isHr = !!hrProcessId && processId === hrProcessId;

  const split = hrPayroll.variant_split ?? {};
  const hrTotal = hrPayroll.dominant_path?.n_hr_executions_total;
  const routes = Object.keys(hrPayroll.dominant_path?.route_id_prefix_correspondence ?? {});
  const dva = hrPayroll.dominant_path?.dominant_variant_analysis;
  const inputMethods = dva?.form_input_method_distribution ?? {};
  const inputMethodNames = Object.keys(inputMethods);
  const totalInputObs = Object.values(inputMethods).reduce((a, b) => a + b, 0);
  const clickTargets = dva?.click_target_frequency ?? {};
  const noteClicks = Object.entries(clickTargets)
    .filter(([k]) => k.includes("note")).reduce((a, [, v]) => a + v, 0);
  const confirmClicks = Object.entries(clickTargets)
    .filter(([k]) => k.startsWith("btn-")).reduce((a, [, v]) => a + v, 0);
  const routesPerExec = dva?.n_distinct_routes_per_execution;

  // Locate which route carries the note-click / confirm-click mismatch, by
  // counting the artifact's own click targets per route prefix. The pairing
  // is near-1:1, never asserted as exactly 1:1.
  const routePairing = Object.entries(hrPayroll.dominant_path?.route_id_prefix_correspondence ?? {})
    .map(([route, prefix]) => {
      const notes = clickTargets[`${prefix}-note|input`] ?? 0;
      const confirms = clickTargets[`btn-${prefix}-ok|btn success`] ?? 0;
      return { route, prefix, notes, confirms, matched: notes === confirms };
    });
  const mismatched = routePairing.filter((r) => !r.matched);

  const b = instrumentation.dataset_b.summary;

  // An actual execution of this process, for deep-linking into Replay.
  const sampleExecution = useMemo(
    () => executionsIndex.find((e) => e.dominant_context === processId) ?? null,
    [executionsIndex, processId],
  );

  // ---------------- readiness gates ----------------
  const gates: Gate[] = [];
  if (opp) {
    gates.push({
      id: "rank",
      label: "Ranked first by canonical Opportunity",
      state: opp.rank === 1 ? "pass" : "warn",
      detail: `Rank ${opp.rank} of ${ranking.length}, Opportunity ${formatNumber(opp.opportunity)}`,
      source: "opportunities.json → ranking",
    });
    gates.push({
      id: "pareto",
      label: "Pareto non-dominated on (Impact, Feasibility)",
      state: opp.pareto_status === "frontier" ? "pass" : "warn",
      detail: `pareto_status = ${opp.pareto_status ?? "not available"}`,
      source: "opportunities.json → ranking[].pareto_status",
    });
  }
  if (profile) {
    gates.push({
      id: "dominant",
      label: "A single path covers most observed executions",
      state: profile.dominant_variant_share > MAJORITY ? "pass" : "warn",
      detail: `${formatPercent(profile.dominant_variant_share, 2)} of ${profile.execution_count} executions, across ${profile.n_variants} variants`,
      source: "processes.json → dominant_variant_share",
    });
  }
  gates.push({
    id: "bounded",
    label: "Automation surface is bounded to evidenced routes",
    state: isHr && routes.length > 0 ? "pass" : "unavailable",
    detail: isHr && routes.length
      ? `${routes.length} evidenced routes; ${routesPerExec?.mean ?? "?"} distinct routes per execution on average (max ${routesPerExec?.max ?? "?"})`
      : "Route-level forensic evidence exists only for the HR/Payroll candidate",
    source: "hr-payroll.json → dominant_path.route_id_prefix_correspondence",
  });
  gates.push({
    id: "deterministic",
    label: "Form input observed as a single deterministic method",
    state: isHr && inputMethodNames.length === 1 ? "pass" : "unavailable",
    detail: isHr && inputMethodNames.length
      ? `${totalInputObs} observations, all "${inputMethodNames[0]}"`
      : "Interaction-level forensic evidence exists only for the HR/Payroll candidate",
    source: "hr-payroll.json → dominant_path.dominant_variant_analysis.form_input_method_distribution",
  });
  gates.push({
    id: "prototype",
    label: "A working prototype exists for this process",
    state: isHr ? "pass" : "unavailable",
    detail: isHr
      ? "Deterministic RPA prototype with validation, human review and confirm-time re-verification"
      : "No prototype was built for this process",
    source: "procmine.automation (Problem-3 prototype / local API)",
  });

  const corePass = gates.filter((g) => g.state === "pass").length;
  const readiness =
    isHr && gates.every((g) => g.state === "pass")
      ? { label: "READY FOR BOUNDED PILOT", tone: "ok" as const }
      : opp?.rank === 1 && profile && profile.dominant_variant_share > MAJORITY
        ? { label: "NEEDS MORE EVIDENCE", tone: "warn" as const }
        : { label: "NOT READY", tone: "bad" as const };

  // ---------------- caveats (always shown where applicable) ----------------
  const caveats: { text: string; source: string }[] = [];
  if (isHr) {
    caveats.push({
      text: "Human review remains required before every confirmation — the prototype prepares and holds, it never auto-confirms.",
      source: "procmine.automation → ReviewCheckpoint",
    });
    caveats.push({
      text: "Note content is not observable in the logs; the operator must supply it.",
      source: "Day-1 finding: clipboard payload text is not captured (analytical report, not in frontend bundle)",
    });
    caveats.push({
      text: "No “submit” event exists in the schema — treating the OK button as the confirmation step is a DOM-structure inference, which is why a human checkpoint precedes every confirm.",
      source: "hr-payroll.json → dominant_variant_analysis.click_target_frequency (inference stated in the Day-3 prototype report)",
    });
    if (mismatched.length) {
      caveats.push({
        text: `Note/confirm click pairing is near-1:1, not exact: ${noteClicks} vs ${confirmClicks} overall, with the single unexplained discrepancy on ${mismatched.map((r) => r.route).join(", ")}.`,
        source: "hr-payroll.json → dominant_variant_analysis.click_target_frequency",
      });
    }
    if (split.word_detour || split.rare_edge) {
      const excluded = (split.word_detour?.n ?? 0) + (split.rare_edge?.n ?? 0);
      caveats.push({
        text: `${excluded} of ${hrTotal} executions follow non-dominant paths (Word detour, rare multi-hop) and are deliberately out of scope.`,
        source: "hr-payroll.json → variant_split",
      });
    }
  }
  if (b.n_degraded > 0) {
    caveats.push({
      text: `${b.n_degraded} of ${b.n_sessions} Dataset-B sessions are instrumentation-degraded. Instrumentation health affects evidence availability; it does not by itself prove segmentation failure.`,
      source: "instrumentation.json → dataset_b.summary",
    });
  }

  // ---------------- evidence chain ----------------
  const evidence: EvidenceItem[] = [];
  if (profile) {
    evidence.push({
      id: "e1",
      kind: "observed",
      headline: `${profile.execution_count} ${profile.readable_name} executions observed`,
      observed: `${profile.execution_count} executions, ${formatDuration(profile.total_duration_ms)} of recorded activity, ${formatPercent(profile.avg_manual_event_share, 1)} manual events`,
      why: "Volume is what makes a repeated workflow worth automating at all; a one-off would not justify the build.",
      sourceFile: "processes.json",
      sourceField: `process record for ${profile.process_id}`,
      available: true,
      action: { label: "Inspect process", run: () => navigate("processes", { processId }) },
    });
  }
  if (isHr && split.dominant) {
    evidence.push({
      id: "e2",
      kind: "canonical",
      headline: `${split.dominant.n} executions follow the dominant path`,
      observed: `${split.dominant.n} of ${hrTotal} executions classified as dominant path by the Day-3 forensics`,
      why: "A deterministic script can only be written against a path that actually repeats. This is the population the prototype targets.",
      sourceFile: "hr-payroll.json",
      sourceField: "variant_split.dominant.n",
      available: true,
      action: { label: "Inspect process", run: () => navigate("processes", { processId }) },
    });
    evidence.push({
      id: "e3",
      kind: "canonical",
      headline: `Dominant path is ${formatPercent(split.dominant.share, 2)} of executions`,
      observed: `share = ${split.dominant.share}; remaining: ${split.word_detour?.n ?? 0} Word detour, ${split.rare_edge?.n ?? 0} rare multi-hop`,
      why: "Sets the realistic coverage ceiling for a bounded automation — and names exactly what is left for a human.",
      sourceFile: "hr-payroll.json",
      sourceField: "variant_split",
      available: true,
    });
  }
  if (isHr && routes.length) {
    evidence.push({
      id: "e4",
      kind: "observed",
      headline: `${routes.length} evidenced routes were observed`,
      observed: routes.join(", "),
      why: "A bounded, enumerable surface is what makes the automation safe to scope; the prototype refuses any route outside this set.",
      sourceFile: "hr-payroll.json",
      sourceField: "dominant_path.route_id_prefix_correspondence",
      available: true,
      action: { label: "Try prototype", run: () => navigate("automation") },
    });
  }
  if (isHr && inputMethodNames.length) {
    evidence.push({
      id: "e5",
      kind: "observed",
      headline: `Note entry observed as a single interaction method (${inputMethodNames[0]})`,
      observed: `${totalInputObs} form-input observations, all "${inputMethodNames[0]}" — no live typing observed. Click pairing: ${noteClicks} note-field clicks against ${confirmClicks} confirm-button clicks.`,
      why: "Deterministic, non-judgemental interactions are the ones a script can reproduce safely. The pairing is described as near-1:1 and is never asserted as exactly 1:1.",
      sourceFile: "hr-payroll.json",
      sourceField: "dominant_path.dominant_variant_analysis.form_input_method_distribution / click_target_frequency",
      available: true,
    });
    if (mismatched.length) {
      evidence.push({
        id: "e5b",
      kind: "limitation",
      kindLabel: "UNEXPLAINED",
        headline: `Note/confirm click counts do not match exactly (${noteClicks} vs ${confirmClicks}) — unexplained`,
        observed: mismatched
          .map((r) => `${r.route}: ${r.notes} note clicks vs ${r.confirms} confirm clicks`)
          .join("; ") +
          ". Every other evidenced route pairs exactly. The cause of this single discrepancy is not established.",
        why: "Recorded rather than smoothed over: it is the one place the otherwise exact pairing breaks, and it is why the pattern is only ever claimed as near-1:1. It does not change the automation scope, but it should not disappear from the evidence.",
        sourceFile: "hr-payroll.json",
        sourceField: "dominant_path.dominant_variant_analysis.click_target_frequency",
        available: true,
      });
    }
    evidence.push({
      id: "e5c",
      kind: "inferred",
      kindLabel: "INFERRED FROM DOM",
      headline: "Confirmation is read from DOM structure — no “submit” event exists in the schema",
      observed: `Clicks on btn-<route>-ok are treated as the confirmation step; no event type named "submit" is recorded anywhere in the logs.`,
      why: "This is a DOM-structure inference, not a directly-labelled fact. It is precisely why the prototype requires a human review checkpoint before every confirm click rather than trusting the inference on its own.",
      sourceFile: "hr-payroll.json",
      sourceField: "dominant_path.dominant_variant_analysis.click_target_frequency (interpretation stated in reports/day3/hr_payroll_automation_prototype.md)",
      available: true,
    });
  }
  if (sampleExecution) {
    evidence.push({
      id: "e6",
      kind: "observed",
      headline: "Individual executions can be inspected step by step",
      observed: `e.g. ${sampleExecution.execution_id} — ${sampleExecution.event_count} raw events, ${formatDuration(sampleExecution.duration_ms)}`,
      why: "The recommendation is traceable down to a concrete recorded execution, not just an aggregate.",
      sourceFile: "executions-index.json + selected session execution file",
      sourceField: `execution_id ${sampleExecution.execution_id}`,
      available: true,
      action: {
        label: "Replay this execution",
        run: () => navigate("replay", {
          sessionId: sampleExecution.session_id,
          executionId: sampleExecution.execution_id,
        }),
      },
    });
  }
  if (isHr) {
    evidence.push({
      id: "e7",
      kind: "prototype",
      kindLabel: "LOCAL PROTOTYPE",
      headline: "Prototype enforces validation, human review and confirm-time re-verification",
      observed: "Route validation, note validation, single-element DOM checks, a held ReviewCheckpoint, and re-location of the confirm button at confirm time",
      why: "Demonstrates the workflow is not only describable but executable under safety controls — the difference between a proposal and a pilot.",
      sourceFile: "existing automation API result (procmine.automation)",
      sourceField: "action_log returned by /api/prepare and /api/confirm",
      available: true,
      action: { label: "Try prototype", run: () => navigate("automation") },
    });
    evidence.push({
      id: "e8",
      kind: "limitation",
      kindLabel: "NOT OBSERVABLE",
      headline: "Note content itself is not observable",
      observed: "Not available in the frontend bundle",
      why: "Bounds the claim: the automation can place a note the operator supplies, but cannot author or verify its content.",
      sourceFile: "Evidence available in analytical report, not currently exposed in frontend bundle",
      available: false,
    });
  }

  // ---------------- sensitivity ----------------
  const scenarios = opportunities.sensitivity_scenarios ?? {};
  const scenarioRows = Object.entries(scenarios);
  const nTop = scenarioRows.filter(([, v]) => v.hr_rank === 1).length;
  const worstRank = scenarioRows.length ? Math.max(...scenarioRows.map(([, v]) => v.hr_rank)) : null;
  const robustness =
    !scenarioRows.length ? "NOT AVAILABLE"
      : nTop === scenarioRows.length ? "INVARIANT ACROSS TESTED SCENARIOS"
        : nTop * 2 >= scenarioRows.length ? "STRONG BUT ASSUMPTION-SENSITIVE"
          : "ASSUMPTION-DEPENDENT";

  const sens = instrumentationSensitivity;
  const hrCompare = sens.ranking_comparison.find((r) => r.process_id === processId) ?? null;

  return (
    <>
      <PageHeader
        screen="decision"
        title="Automation Decision Center"
        purpose="The decision, written as an engineering record: what was decided, on which evidence, how robust it is, where its boundary sits, and what is still open. Every figure is read from the generated bundle; nothing here is scored or recomputed."
        context={`Dataset B · ${executionsIndex.length} executions · ${ranking.length} ranked processes`}
      />

      {/* ---------- decision record ---------- */}
      <section className="panel headline record" aria-labelledby="dc-summary">
        <div className="headline-head">
          <div>
            <h3 id="dc-summary" style={{ marginBottom: 6 }}>Decision record</h3>
            <p className="headline-name">{opp?.readable_name ?? "No process"}</p>
            <p className="small muted" style={{ margin: "2px 0 0" }}>
              Rank {opp?.rank ?? "—"} of {ranking.length}
              {opp?.pareto_status === "frontier" ? " · Pareto non-dominated" : ""}
            </p>
          </div>
          <label className="field" style={{ minWidth: 240, marginBottom: 0 }}>
            <span>Process</span>
            <select value={processId} onChange={(e) => { setProcessId(e.target.value); setOpenEvidence(""); }}
              aria-label="Select process">
              {ranking.map((r) => (
                <option key={r.process_id} value={r.process_id}>#{r.rank} {r.readable_name}</option>
              ))}
            </select>
          </label>
        </div>

        <dl className="record-grid">
          <div className="record-cell record-decision">
            <dt>Decision</dt>
            <dd><span className={`badge ${readiness.tone} verdict`}>{readiness.label}</span></dd>
            <dd className="record-main">{isHr ? "Deterministic RPA" : "Not proposed"}</dd>
            <dd className="record-note">
              {isHr ? "Bounded to evidenced routes" : "No prototype or route evidence for this process"}
              {" · "}{corePass} of {gates.length} evidence gates passed
            </dd>
          </div>
          <div className="record-cell">
            <dt>Evidence</dt>
            <dd className="record-main">{evidence.length} evidence items</dd>
            <dd className="record-note">
              {isHr
                ? "Process and interaction level: profile, variants, forensic split, routes, DFG, prototype. Listed under B."
                : "Process level only: profile and variants, no DOM-level forensics persisted."}
            </dd>
          </div>
          <div className="record-cell">
            <dt>Robustness</dt>
            <dd className="record-main">{isHr ? robustness : "Not available"}</dd>
            <dd className="record-note">
              {isHr && scenarioRows.length
                ? `top candidate in ${nTop} of ${scenarioRows.length} tested scenarios; worst tested rank ${worstRank}`
                : "Per-scenario data in the artifact is specific to the HR/Payroll candidate"}
            </dd>
          </div>
          <div className="record-cell">
            <dt>Scope</dt>
            <dd className="record-main">{isHr ? `${routes.length} routes, dominant path only` : "No route-level scope"}</dd>
            <dd className="record-note">
              {isHr && split.dominant
                ? `${split.dominant.n} of ${hrTotal} executions are inside the boundary`
                : "Scope is defined only where route evidence exists"}
            </dd>
          </div>
          <div className="record-cell">
            <dt>Boundary</dt>
            <dd className="record-main">{isHr ? "Human review before every confirmation" : "Not defined"}</dd>
            <dd className="record-note">
              {isHr ? "Prepare stops at a held checkpoint; confirm needs a single-use token." : "No automation is proposed."}
            </dd>
          </div>
          <div className="record-cell">
            <dt>Risks</dt>
            <dd className="record-main">
              {upgrade.production_boundary.requires_production_integration.length} open before any real deployment
            </dd>
            <dd className="record-note">
              Listed under G, with {caveats.length} evidence caveats under A.
            </dd>
          </div>
        </dl>
        <p className="small muted" style={{ marginTop: 12 }}>
          “Pilot readiness” describes a bounded trial under human review. No production-readiness
          claim is made anywhere on this screen, and no monetary ROI is derivable from these logs.
        </p>
      </section>

      {/* ---------- A. readiness ---------- */}
      <section className="panel" aria-labelledby="dc-readiness">
        <h3 id="dc-readiness">A · Automation readiness</h3>
        <div className="grid cols-4">
          <div className="metric">
            <div className="label">Impact</div>
            <div className="value">{opp ? formatNumber(opp.impact) : "—"}</div>
          </div>
          <div className="metric">
            <div className="label">Feasibility</div>
            <div className="value">{opp ? formatNumber(opp.feasibility) : "—"}</div>
          </div>
          <div className="metric">
            <div className="label">Evidence</div>
            <div className="value" style={{ fontSize: 18 }}>
              {profile ? `${profile.execution_count} execs` : "—"}
            </div>
            <div className="hint">
              {profile ? `${formatPercent(profile.dominant_variant_share, 2)} dominant path` : ""}
            </div>
          </div>
          <div className="metric">
            <div className="label">Instrumentation</div>
            <div className="value" style={{ fontSize: 18 }}>
              {b.n_healthy}/{b.n_sessions} healthy
            </div>
            <div className="hint">{b.n_degraded} degraded Dataset-B sessions</div>
          </div>
        </div>

        <h4 style={{ marginTop: 18, marginBottom: 8 }}>Why this status?</h4>
        <ul className="gates">
          {gates.map((g) => (
            <li key={g.id} className={`gate ${g.state}`}>
              <span className="gate-mark" aria-hidden="true">
                {g.state === "pass" ? "✓" : g.state === "warn" ? "⚠" : "○"}
              </span>
              <span className="gate-body">
                <span className="gate-label">{g.label}</span>
                <span className="small muted">{g.detail}</span>
                <span className="small mono src">{g.source}</span>
              </span>
            </li>
          ))}
          {caveats.map((c, i) => (
            <li key={`caveat-${i}`} className="gate warn">
              <span className="gate-mark" aria-hidden="true">⚠</span>
              <span className="gate-body">
                <span className="gate-label">{c.text}</span>
                <span className="small mono src">{c.source}</span>
              </span>
            </li>
          ))}
        </ul>
        <p className="small muted">
          These are explicit boolean gates, not a weighted score. “Most executions” means a share
          above {formatPercent(MAJORITY, 0)} — a display rule for this screen, not an analytical
          threshold. A gate marked ○ means the supporting artifact does not exist for this process.
        </p>
      </section>

      {/* ---------- B. evidence chain ---------- */}
      <section className="panel" aria-labelledby="dc-evidence">
        <h3 id="dc-evidence">B · Evidence → claim traceability</h3>
        <div className="claim-block">
          <div className="claim-label">Claim</div>
          <p className="claim-text">
            {isHr
              ? "Deterministic RPA is appropriate for the dominant workflow of this process."
              : `No automation approach is recommended for ${opp?.readable_name ?? "this process"} — the supporting interaction-level evidence was not produced.`}
          </p>
          <div className="claim-arrow" aria-hidden="true">↓</div>
          <div className="claim-label">Evidence ({evidence.length})</div>
        </div>

        <ul className="evidence-list">
          {evidence.map((e) => {
            const open = openEvidence === e.id;
            return (
              <li key={e.id} className={`evidence ${e.available ? "" : "missing"}`}>
                <button
                  className="evidence-head"
                  aria-expanded={open}
                  aria-controls={`ev-${e.id}`}
                  onClick={() => setOpenEvidence(open ? "" : e.id)}
                >
                  <span className="ev-mark" aria-hidden="true">{e.available ? "▸" : "○"}</span>
                  <span className="ev-headline">
                    {e.headline}{" "}
                    <EvidenceBadge kind={e.kind} label={e.kindLabel} />
                  </span>
                  <span className="badge neutral ev-src">{e.sourceFile}</span>
                </button>
                {open ? (
                  <div className="evidence-detail" id={`ev-${e.id}`}>
                    <dl>
                      <dt>Observed evidence</dt>
                      <dd className="wrap-any">{e.observed}</dd>
                      <dt>Why it matters</dt>
                      <dd>{e.why}</dd>
                      <dt>Source artifact</dt>
                      <dd className="mono small wrap-any">{e.sourceFile}</dd>
                      {e.sourceField ? (
                        <>
                          <dt>Source field</dt>
                          <dd className="mono small wrap-any">{e.sourceField}</dd>
                        </>
                      ) : null}
                    </dl>
                    {e.action ? (
                      <div className="controls">
                        <button className="btn" onClick={e.action.run}>{e.action.label}</button>
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
        <div className="claim-block" style={{ marginTop: 12 }}>
          <div className="claim-arrow" aria-hidden="true">↓</div>
          <div className="claim-label">Decision</div>
          <p className="claim-text">
            {isHr
              ? `Automate the dominant path only, under human review — readiness: ${readiness.label}.`
              : "No automation decision is taken for this process."}
          </p>
        </div>
      </section>

      {/* ---------- C. sensitivity ---------- */}
      <section className="panel" aria-labelledby="dc-sens">
        <h3 id="dc-sens">C · Decision sensitivity</h3>

        {isHr && scenarioRows.length ? (
          <>
            <p className="small muted">
              Weighting scenarios from the Day-3 audit, shown verbatim. The ranking is not re-run
              here.
            </p>
            <div className="table-scroll">
              <table aria-label="Sensitivity scenarios">
                <thead>
                  <tr>
                    <th scope="col">Scenario</th>
                    <th scope="col" className="num">HR rank</th>
                    <th scope="col">Top candidate changed</th>
                    <th scope="col" className="num">Spearman vs default</th>
                  </tr>
                </thead>
                <tbody>
                  {scenarioRows.map(([name, v]) => (
                    <tr key={name}>
                      <td className="mono small">{name}</td>
                      <td className="num">
                        <span className={`badge ${v.hr_rank === 1 ? "ok" : "neutral"}`}>#{v.hr_rank}</span>
                      </td>
                      <td className="small">{v.top_candidate_changed ? "yes" : "no"}</td>
                      <td className="num">{formatNumber(v.spearman_vs_default, 4)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="why" style={{ marginTop: 12 }}>
              <h4>Interpretation</h4>
              <p style={{ margin: 0 }}>
                {opp?.readable_name} is the top candidate in <strong>{nTop} of {scenarioRows.length}</strong>{" "}
                tested weighting scenarios. Under the remaining {scenarioRows.length - nTop} it moves
                to rank <strong>{worstRank}</strong> — the worst rank observed in any tested scenario.
                That makes this a <strong>strong but assumption-sensitive</strong> recommendation
                rather than an unconditional conclusion. This is sensitivity to assumptions, not
                statistical confidence: no confidence interval is computed anywhere in this project.
              </p>
            </div>
          </>
        ) : (
          <Notice kind="info">
            Per-scenario sensitivity in the canonical artifact is recorded specifically for the
            HR/Payroll candidate (<span className="mono">hr_rank</span> per scenario), so it is not
            shown for other processes rather than being reinterpreted.
          </Notice>
        )}

        {/* instrumentation sensitivity */}
        <h4 style={{ marginTop: 20, marginBottom: 8 }}>Instrumentation sensitivity (Day 4)</h4>
        <div className="grid cols-3">
          <div className="metric">
            <div className="label">Dataset B sessions</div>
            <div className="value" style={{ fontSize: 18 }}>
              {b.n_healthy} healthy · {b.n_degraded} degraded
            </div>
            <div className="hint">{sens.executions_removed} of {sens.executions_total} executions excluded in Case B</div>
          </div>
          <div className="metric">
            <div className="label">All Dataset B</div>
            <div className="value" style={{ fontSize: 16 }}>
              {hrCompare ? `Rank #${hrCompare.rank_case_a} · ${formatNumber(hrCompare.opportunity_a)}` : "—"}
            </div>
            <div className="hint">canonical result</div>
          </div>
          <div className="metric">
            <div className="label">Excluding degraded sessions</div>
            <div className="value" style={{ fontSize: 16 }}>
              {hrCompare && hrCompare.rank_case_b !== null
                ? `Rank #${hrCompare.rank_case_b} · ${formatNumber(hrCompare.opportunity_b)}`
                : "—"}
            </div>
            <div className="hint">Day-4 sensitivity case</div>
          </div>
        </div>
        <Notice kind="info">
          Removing the degraded sessions does not change the selected process
          {sens.top_candidate_unchanged ? "" : " (top candidate did change)"}, but it does change
          the exact Opportunity score. <strong>Instrumentation health affects evidence
          availability; it does not by itself prove segmentation failure.</strong>
        </Notice>
      </section>

      {/* ---------- J. automation boundary ---------- */}
      {isHr ? (
        <section className="panel" aria-labelledby="dc-boundary">
          <h3 id="dc-boundary">D · Automation boundary</h3>
          <div className="grid cols-2">
            <div className="boundary automate">
              <h4>Automate</h4>
              <ul>
                <li>Navigate to the HR system</li>
                <li>Select an evidenced route ({routes.length} known)</li>
                <li>Locate the note field</li>
                <li>Insert the note the operator provided</li>
                <li>Confirm — only after the human checkpoint</li>
              </ul>
              <p className="small mono src">
                hr-payroll.json → route_id_prefix_correspondence, dominant_variant_analysis;
                procmine.automation
              </p>
            </div>
            <div className="boundary human">
              <h4>Keep human / out of scope</h4>
              <ul>
                <li>Reviewing and approving the note content</li>
                <li>Authoring note content (not observable in the logs)</li>
                <li>Word detour variant ({split.word_detour?.n ?? 0} executions)</li>
                <li>Rare multi-hop cases ({split.rare_edge?.n ?? 0} executions)</li>
                <li>Any judgment-dependent decision</li>
              </ul>
              <p className="small mono src">hr-payroll.json → variant_split</p>
            </div>
          </div>
          <div className="why" style={{ marginTop: 12 }}>
            <h4>Why not automate everything?</h4>
            <p style={{ margin: "0 0 8px" }}>
              Only the dominant deterministic HR path is inside the initial automation boundary.
            </p>
            <p style={{ margin: 0 }}>
              Because the evidence supports a bounded deterministic path, while the remaining
              variants and the unobservable, judgment-dependent work do not have sufficient
              evidence for safe automation. {split.dominant?.n ?? 0} of {hrTotal} executions follow
              the dominant path; the other{" "}
              {(split.word_detour?.n ?? 0) + (split.rare_edge?.n ?? 0)} were deliberately excluded
              rather than partially automated.
            </p>
          </div>
          <div className="controls" style={{ marginTop: 12 }}>
            <button className="btn primary" onClick={() => navigate("automation")}>Try prototype</button>
            <button className="btn" onClick={() => navigate("processes", { processId })}>Inspect process</button>
            <button className="btn" onClick={() => navigate("opportunities")}>See full ranking</button>
            {sampleExecution ? (
              <button className="btn" onClick={() => navigate("replay", {
                sessionId: sampleExecution.session_id,
                executionId: sampleExecution.execution_id,
              })}>
                Replay an execution
              </button>
            ) : null}
          </div>
        </section>
      ) : null}

      {/* ---------- E. model support (Day 7) ---------- */}
      <section className="panel" aria-labelledby="dc-model">
        <h3 id="dc-model">E · Model support</h3>
        <Notice kind="warn">
          <strong>This is a supporting signal, not the reason for the recommendation.</strong>{" "}
          {upgrade.model.prohibited_use} The HR/Payroll selection comes from the analytical
          framework — handling time, operator coverage, Pareto and sensitivity — and is
          unchanged by this model.
        </Notice>
        <p><strong>Task:</strong> {upgrade.model.task}</p>
        <div className="grid cols-3">
          <MetricCard label="Behaviour only" value={upgrade.model.behavioural_only_macro_f1.toFixed(4)}
            hint="macro F1, GroupKFold by session" />
          <MetricCard label="With system identity" value={upgrade.model.with_system_identity_macro_f1.toFixed(4)}
            hint={`uplift +${upgrade.model.identity_uplift.toFixed(4)}`} />
          <MetricCard label="Stratified baseline" value={upgrade.model.stratified_baseline_macro_f1.toFixed(4)}
            hint={`${upgrade.model.n_classes} balanced classes`} />
        </div>
        <p><strong>Finding.</strong> {upgrade.model.finding}</p>
        <p className="small"><strong>Top contributing features:</strong>{" "}
          {upgrade.model.top_features.map((f) => f.feature).join(" · ")}</p>
        <Notice kind="info">
          <strong>Leakage control.</strong> {upgrade.model.leakage_control}
        </Notice>
        <Notice kind="info">
          <strong>Why this task and not "is it automatable?"</strong> {upgrade.model.why_not_circular}
        </Notice>
        <p className="small mono src">
          engineering-upgrade.json → model; reports/day7/model_card.md
        </p>
      </section>

      {/* ---------- F. browser automation status (Day 7) ---------- */}
      <section className="panel" aria-labelledby="dc-browser">
        <h3 id="dc-browser">F · Browser automation</h3>
        <p>
          <EvidenceBadge kind="prototype" label={upgrade.browser.status} />{" "}
          {upgrade.browser.status_detail}
        </p>
        <ul>
          <li>Confirmed through a real DOM: <strong>{String(upgrade.browser.confirmed)}</strong></li>
          <li>Note verified in the live DOM: <strong>{String(upgrade.browser.note_reached_dom)}</strong></li>
          <li>Replayed checkpoint refused: <strong>{String(upgrade.browser.replay_refused)}</strong></li>
          <li>Unevidenced route refused: <strong>{String(upgrade.browser.invalid_route_refused)}</strong></li>
          <li>Empty note refused: <strong>{String(upgrade.browser.empty_note_refused)}</strong></li>
        </ul>
        <Notice kind="info">
          The automation logic was <strong>not modified</strong> for the browser. The same
          functions that drive the in-memory mock drive a real Chromium DOM, because the
          adapter implements the same interface — so every safety control still applies.
        </Notice>
        <p className="small mono src">engineering-upgrade.json → browser</p>
      </section>

      {/* ---------- G. production boundary (Day 7) ---------- */}
      <section className="panel" aria-labelledby="dc-prod">
        <h3 id="dc-prod">G · Production boundary</h3>
        <div className="grid cols-2">
          <div className="boundary automate">
            <h4>Implemented and tested</h4>
            <ul>
              {upgrade.production_boundary.implemented.map((x) => <li key={x}>{x}</li>)}
            </ul>
          </div>
          <div className="boundary human">
            <h4>Requires production integration</h4>
            <ul>
              {upgrade.production_boundary.requires_production_integration.map(
                (x) => <li key={x}>{x}</li>)}
            </ul>
          </div>
        </div>
        <Notice kind="warn">
          <strong>This is not a production deployment.</strong> The automation targets a
          local prototype page. Readiness here means a bounded pilot under human review.
        </Notice>
        <p className="small mono src">engineering-upgrade.json → production_boundary</p>
      </section>

      <ProvenancePanel
        meta={meta}
        entries={[
          { value: "Ranking, Pareto, sensitivity scenarios", sourceKey: "audit" },
          { value: "Process volume and variants", sourceKey: "profiles" },
          { value: "HR forensic evidence and routes", sourceKey: "hr_dominant_path" },
          { value: "Instrumentation health", sourceKey: "health_b" },
          { value: "Instrumentation sensitivity (Day 4)", sourceKey: "day4_sensitivity" },
        ]}
      />
    </>
  );
}
