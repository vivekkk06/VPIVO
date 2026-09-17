import { useState } from "react";
import { PageHeader } from "../components/PageHeader";
import { Notice, ProvenancePanel } from "../components/common";
import { EvidenceBadge, EvidenceTrace, StatusTag } from "../components/evidence";
import type { EagerBundle } from "../services/dataService";
import type { Navigate } from "../navigation";
import type { PooledMetrics } from "../types";
import { formatNumber, formatPct100 } from "../utils/format";

type View = "comparison" | "module1" | "module2";

/** A table that may exceed a phone's width scrolls inside its own box rather than
 *  pushing the page sideways. */
function Scroll({ children }: { children: React.ReactNode }) {
  return <div style={{ overflowX: "auto" }}>{children}</div>;
}

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="metric">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {hint ? <div className="hint">{hint}</div> : null}
    </div>
  );
}

function f4(n: number) {
  return n.toFixed(4);
}

function signed(n: number) {
  return n > 0 ? `+${f4(n)}` : f4(n);
}

function pooledRow(label: string, p: PooledMetrics) {
  return (
    <tr key={label}>
      <td>{label}</td>
      <td className="mono">{f4(p.f1)}</td>
      <td className="mono">{f4(p.precision)}</td>
      <td className="mono">{f4(p.recall)}</td>
      <td className="mono">{p.pct_gt_executions_fragmented.toFixed(2)}</td>
      <td className="mono">{f4(p.under_segmentation_rate)}</td>
      <td className="mono">{f4(p.over_segmentation_rate)}</td>
    </tr>
  );
}

export default function ModuleComparison({ bundle, navigate }: { bundle: EagerBundle; navigate?: Navigate }) {
  const [view, setView] = useState<View>("comparison");
  const mc = bundle.moduleComparison;

  if (!mc) {
    return (
      <>
        <PageHeader
          screen="modules"
          title="Approach Comparison"
          purpose={<>Module 1 (locked baseline) against Module 2, the independent Day-6
            experimental approach.</>}
          context="Dataset A + Dataset B · Module 2 artifacts not present"
        />
        <Notice kind="warn">
          Module 2 has not been run in this bundle. Generate it with{" "}
          <span className="mono">python scripts/run_module2_segmentation_experiment.py</span>,
          then rebuild the frontend data.
        </Notice>
      </>
    );
  }

  const { module1, module2, gate, automation, process_analysis, dataset_b_review } = mc;
  const visual = mc.dataset_b_visual_review ?? null;
  const canonical = module1.canonical_pooled;
  const control = module1.control_matched;
  const best = module2.best_matched;
  const cov = automation.coverage;
  const required = `+${Number(gate.thresholds.min_f1_absolute_gain).toFixed(4)}`;
  const dispersion = process_analysis.operator_dispersion;
  // Worded from data, never asserted: the sentence is only shown when the artifacts
  // actually say fragmentation fell and a gate failed.
  const notPromotedWithLowerFragmentation =
    gate.failed_gates.length > 0 && gate.deltas.fragmentation_pct < 0;
  const experiments = bundle.investigation.day2.experiments;
  const sampled = dataset_b_review.sampling.sampled;
  const withReference = dataset_b_review.screenshot_availability.points_with_a_nearest_screenshot;

  return (
    <>
      <PageHeader
        screen="modules"
        title="Approach Comparison"
        purpose={<>
          Two independently identifiable approaches, compared on measured evidence rather
          than on a composite score. Module 1 is the locked baseline every downstream
          number depends on; Module 2 is an independent Day-6 experiment.
        </>}
        context="Dataset A (supervised) + Dataset B (operational only) · Module 2 is experimental"
      />

      <div className="controls" role="group" aria-label="Approach">
        <button className="btn" aria-pressed={view === "comparison"}
          onClick={() => setView("comparison")}>Comparison</button>
        <button className="btn" aria-pressed={view === "module1"}
          onClick={() => setView("module1")}>Module 1 — Continuity</button>
        <button className="btn" aria-pressed={view === "module2"}
          onClick={() => setView("module2")}>Module 2 — Adaptive Evidence</button>
      </div>

      {/* ---------------- MODULE 1 ---------------- */}
      {view === "module1" ? (
        <section className="panel" aria-labelledby="mc-m1">
          <div className="panel-head">
            <h3 id="mc-m1">Module 1 — Continuity-Based Reconstruction</h3>
            <EvidenceBadge kind="canonical" />
          </div>
          <Notice kind="info">
            <strong>Status: LOCKED BASELINE.</strong> Used by the canonical downstream
            analysis. Module 2 does not modify it.
          </Notice>
          <div className="grid cols-4">
            <Metric label="F1" value={f4(canonical.f1)} hint="transition-level, not accuracy" />
            <Metric label="Recall" value={f4(canonical.recall)} />
            <Metric label="Fragmentation"
              value={`${canonical.pct_gt_executions_fragmented.toFixed(2)}%`} />
            <Metric label="Under-segmentation" value={f4(canonical.under_segmentation_rate)} />
          </div>
          <div className="grid cols-3" style={{ marginTop: 12 }}>
            <Metric label="Precision" value={f4(canonical.precision)} />
            <Metric label="Over-segmentation" value={f4(canonical.over_segmentation_rate)} />
            <Metric label="GT boundaries" value={String(canonical.n_gt_boundaries)}
              hint={`${canonical.n_predicted} predicted`} />
          </div>
          <p className="small muted" style={{ marginTop: 12 }}>
            Validated leave-one-session-out across 63 Dataset-A sessions. Every number here
            is read from the canonical Day-2 artifact, never recomputed. The F1 is modest and
            is reported as such.
          </p>
        </section>
      ) : null}

      {/* ---------------- MODULE 2 ---------------- */}
      {view === "module2" ? (
        <>
          <section className="panel" aria-labelledby="mc-m2">
            <div className="panel-head">
              <h3 id="mc-m2">Module 2 — Adaptive Evidence-Guided Reconstruction &amp; Automation</h3>
              <span className="badge-row">
                <EvidenceBadge kind="experimental" />
                <EvidenceBadge kind="not-promoted" />
              </span>
            </div>
            <Notice kind="warn">
              <strong>Status: {module2.status}.</strong> {module2.decision}
            </Notice>
            <p className="small muted">
              An engineering approach, not an AI model: deterministic features, rules and
              gates reusing Module 1&rsquo;s own classifiers.
            </p>
            <Scroll>
              <table aria-label="Module 2 feature sets">
                <thead>
                  <tr>
                    <th>Feature set</th><th>Added columns</th>
                    <th>F1 (re-selected thresholds)</th><th>F1 (Module 1 thresholds)</th>
                    <th>Fragmentation %</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(module2.feature_sets).map(([key, fs]) => (
                    <tr key={key}>
                      <td>{key}</td>
                      <td className="small">{fs.extra_features.length
                        ? fs.extra_features.join(", ") : "— (control)"}</td>
                      <td className="mono">{f4(fs.matched.f1)}</td>
                      <td className="mono">{f4(fs.locked.f1)}</td>
                      <td className="mono">{fs.matched.pct_gt_executions_fragmented.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Scroll>
            <p className="small muted" style={{ marginTop: 10 }}>
              Content drift is computable on{" "}
              <strong>{(module2.content_drift_coverage.fraction * 100).toFixed(2)}%</strong>{" "}
              of transitions ({module2.content_drift_coverage.transitions_with_drift_available}
              {" of "}{module2.content_drift_coverage.transitions_total}).{" "}
              {module2.content_drift_coverage.note}
            </p>
          </section>

          <section className="panel" aria-labelledby="mc-gate">
            <h3 id="mc-gate">Pre-registered promotion gate</h3>
            <p className="small muted">{gate.source}</p>
            <Scroll>
              <table aria-label="Promotion gate checks">
                <thead><tr><th>Gate</th><th>Result</th></tr></thead>
                <tbody>
                  {Object.entries(gate.checks).map(([name, passed]) => (
                    <tr key={name}>
                      <td className="small">{name}</td>
                      <td>
                        <span className={`badge ${passed ? "ok" : "bad"}`}>
                          {passed ? "PASS" : "FAIL"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Scroll>
            <div className="grid cols-3" style={{ marginTop: 12 }}>
              <Metric label="Sessions with higher F1" value={String(gate.robustness.sessions_improved)} />
              <Metric label="Sessions with lower F1" value={String(gate.robustness.sessions_degraded)} />
              <Metric label="Sessions effectively unchanged"
                value={String(gate.robustness.sessions_unchanged)} />
            </div>
            <p className="small muted" style={{ marginTop: 10 }}>
              Gain survives dropping the 3 sessions with the largest gain:{" "}
              <strong>{gate.concentration_check.gain_survives_removing_top3 ? "yes" : "no"}</strong>.
              {" "}Gain survives dropping the operator with the largest gain (
              {gate.machine_dominance_check.most_improved_operator}):{" "}
              <strong>{gate.machine_dominance_check
                .gain_survives_removing_most_improved_operator ? "yes" : "no"}</strong>.
              The gain is broad; it is not large enough.
            </p>
          </section>

          <section className="panel" aria-labelledby="mc-db">
            <h3 id="mc-db">Dataset-B blind review sheet — human review not completed</h3>
            <Notice kind="warn">
              <strong>Human review not completed.</strong> The prepared sheet still holds no
              human judgments, and no Dataset-B segmentation quality claim is made from it.
              It is a review instrument, not a validation result.
            </Notice>
            <Notice kind="info">{dataset_b_review.dataset_b_rule}</Notice>
            <div className="grid cols-4">
              <Metric label="Sampled points" value={String(dataset_b_review.sampling.sampled)}
                hint={`${dataset_b_review.sampling.sampled_boundaries} boundaries / ${dataset_b_review.sampling.sampled_controls} controls`} />
              <Metric label="With screenshot reference"
                value={String(dataset_b_review.screenshot_availability.points_with_a_nearest_screenshot)} />
              <Metric label="Files missing on disk"
                value={String(dataset_b_review.screenshot_availability.nearest_screenshot_file_missing_on_disk)} />
              <Metric label="Human review status" value={dataset_b_review.review_status.split("—")[0].trim()}
                hint="judgments ship empty by design" />
            </div>
            <p className="small muted" style={{ marginTop: 10 }}>
              {dataset_b_review.sampling.blinding_note} Deterministic, seed{" "}
              <span className="mono">{dataset_b_review.sampling.seed}</span>. No labels were
              generated to fill the sheet.
            </p>
          </section>

          <section className="panel" aria-labelledby="mc-dbv">
            <h3 id="mc-dbv">Dataset-B Visual Review</h3>
            {visual ? (
              <>
                <Notice kind="warn">
                  <strong>Surrogate visual review — not ground truth.</strong> Reviewer:{" "}
                  {visual.reviewer}. Judgments were made blind and frozen before the answer
                  key was read. Human review:{" "}
                  {visual.human_review.split("—")[0].trim().toLowerCase()}.
                </Notice>
                <div className="grid cols-4">
                  <Metric label="Sample size" value={String(visual.sample_size)}
                    hint={`same sample, seed ${visual.seed}`} />
                  <Metric label="Screenshots available" value={String(visual.screenshots_available)} />
                  <Metric label="Screenshots unavailable" value={String(visual.screenshots_unavailable)}
                    hint={`${visual.screenshots_recovered} recovered; never judged`} />
                  <Metric label="Review status" value={visual.status.split("—")[0].trim()}
                    hint={visual.status.split("—")[1]?.trim()} />
                </div>
                <div className="grid cols-3" style={{ marginTop: 12 }}>
                  <Metric label="Clear boundary" value={String(visual.counts.B_CLEAR_BOUNDARY)} />
                  <Metric label="Clear continuity" value={String(visual.counts.A_CLEAR_CONTINUITY)} />
                  <Metric label="Ambiguous" value={String(visual.counts.C_AMBIGUOUS)} />
                </div>
                <Scroll>
                  <table aria-label="Visual labels by sample type" style={{ marginTop: 12 }}>
                    <thead>
                      <tr>
                        <th>Sample type (revealed after judging)</th><th>Clear continuity</th>
                        <th>Clear boundary</th><th>Ambiguous</th><th>Unavailable</th>
                      </tr>
                    </thead>
                    <tbody>
                      {([["Predicted boundaries", visual.counts_by_sample_type.boundary_sample],
                         ["Mid-execution controls", visual.counts_by_sample_type.control_sample]] as const)
                        .map(([name, c]) => (
                          <tr key={name}>
                            <td>{name}</td>
                            <td className="mono">{c.A_CLEAR_CONTINUITY}</td>
                            <td className="mono">{c.B_CLEAR_BOUNDARY}</td>
                            <td className="mono">{c.C_AMBIGUOUS}</td>
                            <td className="mono">{c.D_UNAVAILABLE}</td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </Scroll>
                <Notice kind="info">
                  <strong>Decision: {visual.decision.outcome}.</strong> {visual.decision.statement}{" "}
                  {visual.decision.basis[0]}
                </Notice>
                <p className="small muted">
                  {visual.not_metrics_note} {visual.decision.module2_promotion}
                </p>
              </>
            ) : (
              <Notice kind="warn">
                The surrogate visual review has not been run in this bundle, so no visual
                judgment is shown.
              </Notice>
            )}
          </section>

          <section className="panel" aria-labelledby="mc-auto">
            <h3 id="mc-auto">Automation routing and post-action audit</h3>
            <div className="grid cols-3">
              <Metric label="Routing-eligible coverage"
                value={f4(cov.observed_dominant_path_coverage)}
                hint={`${cov.routing_eligible} of ${cov.total_executions} executions`} />
              <Metric label="Canonical dominant share"
                value={f4(automation.canonical_dominant_share)}
                hint={`${automation.canonical_dominant_n} of ${cov.total_executions}`} />
              <Metric label="Non-dominant admitted" value="0"
                hint="of 28 detour + rare-edge executions" />
            </div>
            <Notice kind="warn">
              These are two different quantities. {cov.metric_naming_note}
            </Notice>
            <p className="small muted">
              The gate is deliberately stricter than the forensic label:{" "}
              {automation.dominant_refused.n} dominant-path executions are refused.{" "}
              {automation.dominant_refused.explanation}
            </p>
            <p className="small muted">
              Post-action audit: expected end state{" "}
              <strong>{automation.post_action_expected_state_passed ? "passed" : "failed"}</strong>;
              injected route drift{" "}
              <strong>{automation.post_action_detects_route_drift ? "detected" : "missed"}</strong>.
              UI/state evidence does not prove backend persistence: a screenshot shows the UI
              reached a state, not that a record was written.
            </p>
          </section>

          <section className="panel" aria-labelledby="mc-proc">
            <h3 id="mc-proc">Decision views</h3>
            <Notice kind="info">{process_analysis.monetary_roi_statement}</Notice>
            <p className="small muted">
              Pareto frontier ({process_analysis.pareto_frontier.length} of{" "}
              {process_analysis.pareto_table.length}) recomputed independently and{" "}
              {process_analysis.pareto_matches_canonical
                ? "matches the canonical frontier exactly"
                : "DIFFERS from the canonical frontier"}:{" "}
              {process_analysis.pareto_frontier.join(" · ")}.
            </p>
            <Scroll>
              <table aria-label="Operator variant analysis">
                <thead>
                  <tr>
                    <th>Operator</th><th>n</th><th>Dominant share</th><th>95% CI</th>
                    <th>CI covers pooled</th>
                  </tr>
                </thead>
                <tbody>
                  {process_analysis.operator_table.map((r) => (
                    <tr key={r.operator}>
                      <td className="mono small">{r.operator}</td>
                      <td className="mono">{r.executions}</td>
                      <td className="mono">{f4(r.dominant_path_share)}</td>
                      <td className="mono small">
                        [{f4(r.dominant_share_95ci[0])}, {f4(r.dominant_share_95ci[1])}]
                      </td>
                      <td>{r.ci_contains_pooled_share ? "yes" : "no"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Scroll>
            <p className="small muted" style={{ marginTop: 10 }}>
              Operator spread {f4(dispersion.spread)}; χ² = {dispersion.chi_square} against a
              critical value of {dispersion.chi_square_0_05_critical} (dof {dispersion.dof}).
              Differs beyond chance:{" "}
              <strong>{dispersion.differs_beyond_chance_at_0_05 ? "yes" : "no"}</strong>.
              Variant concentration differs across operators and may indicate a training
              consideration; on this sample it is not distinguishable from noise.
            </p>
          </section>
        </>
      ) : null}

      {/* ---------------- COMPARISON ---------------- */}
      {view === "comparison" ? (
        <>
          <section className="panel" aria-labelledby="mc-verdict">
            <h3 id="mc-verdict">Verdict</h3>
            <div className="grid cols-2">
              <div className="metric">
                <div className="label">Module 1</div>
                <div className="value" style={{ fontSize: 16 }}>{module1.status}</div>
                <div className="hint">F1 {f4(canonical.f1)} · canonical downstream source</div>
              </div>
              <div className="metric">
                <div className="label">Module 2</div>
                <div className="value" style={{ fontSize: 16 }}>{module2.status}</div>
                <div className="hint">{module2.decision}</div>
              </div>
            </div>
            <Notice kind="info">
              {notPromotedWithLowerFragmentation
                ? "Module 2 reduced fragmentation in the best experimental configuration, but "
                  + "the F1 gain did not meet the pre-registered promotion gate, so Module 1 "
                  + "remains canonical."
                : module2.decision}
            </Notice>
            <p className="small muted" style={{ marginTop: 12 }}>
              The modules are not ranked by a composite score. Combining F1, coverage and
              interpretability into one number would be false precision.
            </p>
          </section>

          <section className="panel validation" aria-labelledby="mc-validation">
            <div className="panel-head">
              <h3 id="mc-validation">Validation summary</h3>
              <span className="badge-row">
                <EvidenceBadge kind="experimental" />
                <EvidenceBadge kind="not-promoted" />
              </span>
            </div>
            <p className="callout">Experimental extension — not promoted.</p>
            <dl className="record-grid compact">
              <div className="record-cell">
                <dt>Module 1 baseline</dt>
                <dd className="record-main mono">F1 {f4(canonical.f1)}</dd>
                <dd className="record-note">canonical, locked</dd>
              </div>
              <div className="record-cell">
                <dt>Module 2 best</dt>
                <dd className="record-main mono">F1 {f4(best.f1)}</dd>
                <dd className="record-note">{module2.best_candidate_key}, re-selected thresholds</dd>
              </div>
              <div className="record-cell">
                <dt>Required promotion gain</dt>
                <dd className="record-main mono">{required}</dd>
                <dd className="record-note">registered before scoring</dd>
              </div>
              <div className="record-cell">
                <dt>Observed gain</dt>
                <dd className="record-main mono">{signed(gate.deltas.f1)}</dd>
                <dd className="record-note">against the matched control, F1 {f4(control.f1)}</dd>
              </div>
              <div className="record-cell record-decision">
                <dt>Decision</dt>
                <dd className="record-main"><span className="status-tag st-rejected">NOT PROMOTED</span></dd>
                <dd className="record-note">Module 1 stays canonical; no downstream number changed.</dd>
              </div>
            </dl>
            {visual ? (
              <>
                <h4 className="subhead">Dataset-B visual review</h4>
                <dl className="record-grid compact">
                  <div className="record-cell">
                    <dt>Sampled points</dt>
                    <dd className="record-main mono">{sampled}</dd>
                    <dd className="record-note">{dataset_b_review.sampling.sampled_boundaries} boundaries · {dataset_b_review.sampling.sampled_controls} controls</dd>
                  </div>
                  <div className="record-cell">
                    <dt>With a screenshot reference</dt>
                    <dd className="record-main mono">{withReference}/{sampled}</dd>
                    <dd className="record-note">a reference in the log, not a file</dd>
                  </div>
                  <div className="record-cell">
                    <dt>Screenshots physically available</dt>
                    <dd className="record-main mono">{visual.screenshots_available}/{visual.sample_size}</dd>
                    <dd className="record-note">only these were judged</dd>
                  </div>
                  <div className="record-cell">
                    <dt>Unavailable</dt>
                    <dd className="record-main mono">{visual.screenshots_unavailable}</dd>
                    <dd className="record-note">file missing on disk</dd>
                  </div>
                </dl>
                <p className="callout">
                  <EvidenceBadge kind="limitation" label="NOT GROUND TRUTH" />{" "}
                  Vision-model surrogate review — not ground truth. Human review was not performed.
                </p>
              </>
            ) : null}
            <EvidenceTrace
              source={["reports/day6/module2/module2_promotion_gate.json",
                       "reports/day6/module2/dataset_b_visual_review_results.json"]}
              metric="Pooled boundary F1 on Dataset A; counts of sampled Dataset-B points and of screenshot files on disk."
              method="The gain is measured from the Module 1 feature control with thresholds re-selected by the same rule, not from the canonical figure."
              limitations="The visual review is a single surrogate reviewer and describes a sample; it is not a segmentation metric."
            />
          </section>

          <section className="panel" aria-labelledby="mc-log">
            <h3 id="mc-log">Experiment and rejection log</h3>
            <p className="small muted">
              Every approach tried against the Dataset-A ground truth, in order, with the reason it
              was kept or dropped. Numbers are copied from the Day-2, Day-6 and Day-7 artifacts.
            </p>
            <Scroll>
              <table aria-label="Experiment and rejection log" className="log-table">
                <thead>
                  <tr>
                    <th scope="col">Approach</th>
                    <th scope="col">Result</th>
                    <th scope="col">Why</th>
                    <th scope="col">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {experiments.map((e) => (
                    <tr key={e.id} className={e.status === "LOCKED" ? "row-locked" : undefined}>
                      <th scope="row">
                        <span className="small muted block">{e.day}</span>
                        {e.name}
                      </th>
                      <td className="small">
                        {e.metrics ? (
                          <span className="mono block">
                            F1 {formatNumber(e.metrics.f1)}
                            {e.metrics.pct_gt_executions_fragmented != null
                              ? ` · frag ${formatPct100(e.metrics.pct_gt_executions_fragmented)}` : ""}
                          </span>
                        ) : null}
                        {e.id === "module2" ? (
                          <span className="mono block">
                            gain {signed(gate.deltas.f1)} · required {required}
                          </span>
                        ) : null}
                        {e.result}
                      </td>
                      <td className="small">{e.failure_mode}</td>
                      <td><StatusTag status={e.status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Scroll>
            {navigate ? (
              <p className="small">
                <button className="linkish" onClick={() => navigate("reconstruction")}>
                  Open the full reconstruction record (Day 2)
                </button>
              </p>
            ) : null}
          </section>

          <section className="panel" aria-labelledby="mc-seg">
            <h3 id="mc-seg">Segmentation — Dataset A</h3>
            <Scroll>
              <table aria-label="Segmentation comparison">
                <thead>
                  <tr>
                    <th>System</th><th>F1</th><th>Precision</th><th>Recall</th>
                    <th>Frag %</th><th>Under</th><th>Over</th>
                  </tr>
                </thead>
                <tbody>
                  {pooledRow("Module 1 — canonical (Module 1 thresholds)", canonical)}
                  {pooledRow("Module 1 features — control (re-selected thresholds)", control)}
                  {pooledRow("Module 2 — M2C (re-selected thresholds)", best)}
                  {pooledRow("Module 2 — M2C (Module 1 thresholds)", module2.best_locked)}
                </tbody>
              </table>
            </Scroll>
            <p className="small muted" style={{ marginTop: 10 }}>
              The gate compares like with like: M2C against the Module 1 feature control, both
              with thresholds re-selected by the same rule. That is why the gain is measured
              from {f4(control.f1)}, not from the canonical {f4(canonical.f1)}.
            </p>
            <div className="grid cols-4" style={{ marginTop: 12 }}>
              <Metric label="Control F1" value={f4(control.f1)} hint="re-selected thresholds" />
              <Metric label="F1 gain vs control" value={signed(gate.deltas.f1)} />
              <Metric label="Gain required" value={required} hint="pre-registered, unchanged" />
              <Metric label="Failed gates" value={String(gate.failed_gates.length)}
                hint={gate.failed_gates.join(", ") || "none"} />
            </div>
          </section>

          <section className="panel" aria-labelledby="mc-dims">
            <h3 id="mc-dims">Dimension by dimension</h3>
            <p className="small muted">
              A factual side-by-side, not a ranking. Where both columns show a number, both
              use the same thresholds, so no row compares unlike quantities.
            </p>
            <Scroll>
              <table aria-label="Module comparison by dimension">
                <thead>
                  <tr><th>Dimension</th><th>Module 1</th><th>Module 2</th></tr>
                </thead>
                <tbody>
                  <tr><td>Status</td><td>{module1.status}</td><td>{module2.status}</td></tr>
                  <tr>
                    <td>Role</td>
                    <td>Produces the executions every downstream result uses</td>
                    <td>Not used downstream</td>
                  </tr>
                  <tr>
                    <td>Segmentation evidence</td>
                    <td>Timing and context-change features</td>
                    <td>Module 1 features plus operator-normalized timing and content drift</td>
                  </tr>
                  <tr>
                    <td>F1 — Module 1 thresholds</td>
                    <td className="mono">{f4(canonical.f1)}</td>
                    <td className="mono">{f4(module2.best_locked.f1)}</td>
                  </tr>
                  <tr>
                    <td>F1 — thresholds re-selected by one rule</td>
                    <td className="mono">{f4(control.f1)} (control)</td>
                    <td className="mono">{f4(best.f1)}</td>
                  </tr>
                  <tr>
                    <td>Fragmentation % — thresholds re-selected</td>
                    <td className="mono">{control.pct_gt_executions_fragmented.toFixed(2)} (control)</td>
                    <td className="mono">{best.pct_gt_executions_fragmented.toFixed(2)}</td>
                  </tr>
                  <tr>
                    <td>Promotion gate</td>
                    <td>—</td>
                    <td>
                      {gate.failed_gates.length ? "Failed" : "Passed"}: F1 gain{" "}
                      <span className="mono">{signed(gate.deltas.f1)}</span> against{" "}
                      <span className="mono">{required}</span> required
                    </td>
                  </tr>
                  <tr>
                    <td>Robustness</td>
                    <td>reference</td>
                    <td>
                      {gate.robustness.sessions_improved} sessions higher,{" "}
                      {gate.robustness.sessions_degraded} lower
                    </td>
                  </tr>
                  <tr>
                    <td>Final decision</td>
                    <td>Retained as canonical</td>
                    <td>{module2.decision}</td>
                  </tr>
                  <tr>
                    <td>Automation coverage</td>
                    <td>Not gated by variant</td>
                    <td>
                      <span className="mono">{f4(cov.observed_dominant_path_coverage)}</span>{" "}
                      routing-eligible ({cov.routing_eligible} of {cov.total_executions})
                    </td>
                  </tr>
                  <tr>
                    <td>Post-action audit</td>
                    <td>Pre-action safety controls only</td>
                    <td>Experimental structural/state audit</td>
                  </tr>
                  <tr>
                    <td>Safety controls</td>
                    <td>Human checkpoint, route allowlist, re-verification, replay protection</td>
                    <td>The same controls, plus pre-flight routing and post-action audit</td>
                  </tr>
                  <tr>
                    <td>Dataset-B review</td>
                    <td>—</td>
                    <td>
                      {visual
                        ? `Surrogate visual review, not ground truth: ${visual.decision.outcome
                          .toLowerCase()}; human review not completed`
                        : "Framework prepared; review not completed"}
                    </td>
                  </tr>
                  <tr>
                    <td>Operator variation</td>
                    <td>Not examined</td>
                    <td>
                      χ² <span className="mono">{dispersion.chi_square}</span> —{" "}
                      {dispersion.differs_beyond_chance_at_0_05
                        ? "differs beyond chance"
                        : "within sampling noise"}
                    </td>
                  </tr>
                </tbody>
              </table>
            </Scroll>
          </section>
        </>
      ) : null}

      <ProvenancePanel
        meta={bundle.meta}
        entries={[{ value: "Module 1 canonical metrics", sourceKey: "dataset_a_metrics" }]}
      />
    </>
  );
}
