import { useMemo, useState } from "react";
import type { EagerBundle } from "../services/dataService";
import { Notice, ProvenancePanel } from "../components/common";
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
      headline: `Note entry observed as a single interaction method (${inputMethodNames[0]})`,
      observed: `${totalInputObs} form-input observations, all "${inputMethodNames[0]}"; ${noteClicks} note-field clicks and ${confirmClicks} confirm-button clicks recorded`,
      why: "Deterministic, non-judgemental interactions are the ones a script can reproduce safely. The near 1:1 note/confirm pairing is what the prototype replicates.",
      sourceFile: "hr-payroll.json",
      sourceField: "dominant_path.dominant_variant_analysis.form_input_method_distribution / click_target_frequency",
      available: true,
    });
  }
  if (sampleExecution) {
    evidence.push({
      id: "e6",
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
      <header>
        <h2>Automation Decision Center</h2>
        <p className="lede">
          Are we ready to automate this process, why do we believe that, and how robust is that
          decision? Every figure below is read from the generated bundle — nothing on this screen
          is scored or recomputed.
        </p>
      </header>

      {/* ---------- decision summary ---------- */}
      <section className="panel headline" aria-labelledby="dc-summary">
        <div className="headline-head">
          <div>
            <h3 id="dc-summary" style={{ marginBottom: 6 }}>Decision</h3>
            <p className="headline-name">{opp?.readable_name ?? "No process"}</p>
            <p className="small muted" style={{ margin: "2px 0 0" }}>
              Rank {opp?.rank ?? "—"} of {ranking.length}
              {opp?.pareto_status === "frontier" ? " · Pareto non-dominated" : ""}
            </p>
          </div>
          <label className="field" style={{ minWidth: 260, marginBottom: 0 }}>
            <span>Process</span>
            <select value={processId} onChange={(e) => { setProcessId(e.target.value); setOpenEvidence(""); }}
              aria-label="Select process">
              {ranking.map((r) => (
                <option key={r.process_id} value={r.process_id}>#{r.rank} {r.readable_name}</option>
              ))}
            </select>
          </label>
        </div>

        <div className="grid cols-4" style={{ marginTop: 14 }}>
          <div className="metric">
            <div className="label">Recommendation</div>
            <div className="value" style={{ fontSize: 16 }}>
              {isHr ? "Deterministic RPA" : "Not proposed"}
            </div>
            <div className="hint">
              {isHr ? "Bounded to evidenced routes" : "No prototype or route evidence for this process"}
            </div>
          </div>
          <div className="metric">
            <div className="label">Readiness</div>
            <div className="value" style={{ fontSize: 15 }}>
              <span className={`badge ${readiness.tone}`}>{readiness.label}</span>
            </div>
            <div className="hint">{corePass} of {gates.length} evidence gates passed</div>
          </div>
          <div className="metric">
            <div className="label">Decision robustness</div>
            <div className="value" style={{ fontSize: 14 }}>{isHr ? robustness : "Not available"}</div>
            <div className="hint">
              {isHr && scenarioRows.length
                ? `top candidate in ${nTop} of ${scenarioRows.length} tested scenarios; worst tested rank ${worstRank}`
                : "Per-scenario data in the artifact is specific to the HR/Payroll candidate"}
            </div>
          </div>
          <div className="metric">
            <div className="label">Evidence depth</div>
            <div className="value" style={{ fontSize: 14 }}>
              {isHr ? "Process + interaction level" : "Process level only"}
            </div>
            <div className="hint">
              {isHr
                ? "profile, variants, forensic split, routes, DFG, prototype"
                : "profile and variants only — no DOM-level forensics persisted"}
            </div>
          </div>
        </div>
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
                  <span className="ev-headline">{e.headline}</span>
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
