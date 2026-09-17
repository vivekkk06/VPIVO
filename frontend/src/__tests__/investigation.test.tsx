/**
 * The evaluator-facing layer: grouped navigation, page top bar, Day 1-4 investigation
 * pages, the dashboard story, the decision record, and the evidence vocabulary.
 *
 * As everywhere else, expected values are read from the real generated bundle, so a
 * page that drifted from the artifacts fails here instead of passing on a fixture.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App";
import { __clearSessionCache } from "../services/dataService";
import { EvidenceBadge, EvidenceTrace } from "../components/evidence";
import { installFetchStub, readBundleFile, type ApiHandler } from "./helpers";
import type {
  DatasetAMetrics, HrPayrollFile, InstrumentationFile, InstrumentationSensitivityFile,
  InvestigationFile, ModuleComparisonFile, OpportunitiesFile, ProcessRow, SessionRow,
} from "../types";

const inv = () => readBundleFile<InvestigationFile>("investigation.json");

async function renderApp(options: { hash?: string; api?: ApiHandler } = {}) {
  window.location.hash = options.hash ?? "";
  __clearSessionCache();
  installFetchStub({ api: options.api });
  render(<App />);
  await screen.findByRole("heading", { level: 2 });
}

function nav() {
  return screen.getByRole("navigation", { name: "Main" });
}

async function goTo(label: RegExp) {
  await userEvent.click(within(nav()).getByRole("button", { name: label }));
}

function region(name: RegExp) {
  return screen.getByRole("region", { name });
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.location.hash = "";
});

// ===================== NAVIGATION AND SHELL =====================

describe("grouped navigation", () => {
  it("groups the screens by investigation stage, in reading order", async () => {
    await renderApp();
    const groups = within(nav()).getAllByRole("list");
    const names = groups.map((g) => g.getAttribute("aria-labelledby"));
    expect(names).toEqual([
      "nav-group-Overview", "nav-group-Investigation", "nav-group-Decision",
      "nav-group-Evidence", "nav-group-Automation",
    ]);
    const labels = within(nav()).getAllByRole("button").map((b) => b.textContent);
    expect(labels).toEqual([
      "01Executive Dashboard",
      "02Day 1 · Data Audit",
      "03Day 2 · Reconstruction",
      "04Day 3 · Process Mining",
      "05Day 4 · Evidence Health",
      "06Automation Decision Center",
      "07Opportunities",
      "08Approach Comparison",
      "09Execution Replay",
      "10Process Explorer",
      "11HR Automation Demo",
    ]);
  });

  it("marks the active page and moves the marker on navigation", async () => {
    await renderApp();
    expect(within(nav()).getByRole("button", { name: /Executive Dashboard/ }))
      .toHaveAttribute("aria-current", "page");
    await goTo(/Day 1 · Data Audit/);
    expect(await screen.findByRole("heading", { level: 2, name: "Day 1 · Data Audit" })).toBeInTheDocument();
    expect(within(nav()).getByRole("button", { name: /Day 1 · Data Audit/ }))
      .toHaveAttribute("aria-current", "page");
    expect(within(nav()).getByRole("button", { name: /Executive Dashboard/ }))
      .not.toHaveAttribute("aria-current");
    expect(window.location.hash).toBe("#data-audit");
  });

  it.each([
    ["#data-audit", "Day 1 · Data Audit"],
    ["#reconstruction", "Day 2 · Reconstruction"],
    ["#process-mining", "Day 3 · Process Mining"],
    ["#evidence-health", "Day 4 · Evidence Health"],
  ])("restores %s from the hash", async (hash, title) => {
    await renderApp({ hash });
    expect(screen.getByRole("heading", { level: 2, name: title })).toBeInTheDocument();
  });

  it("moves keyboard focus to the new page title after navigating", async () => {
    await renderApp();
    await goTo(/Day 3 · Process Mining/);
    const title = await screen.findByRole("heading", { level: 2, name: "Day 3 · Process Mining" });
    await waitFor(() => expect(document.activeElement).toBe(title));
  });

  it("shows dataset status from the bundle and the read-only evidence mode", async () => {
    const health = readBundleFile<InstrumentationFile>("instrumentation.json");
    await renderApp();
    const status = document.querySelector("dl.dataset-status") as HTMLElement;
    expect(status).toHaveAttribute("aria-label", "Dataset status");
    const text = status.textContent ?? "";
    expect(text).toContain(`${health.dataset_a.summary.n_sessions} sessions · ground truth`);
    expect(text).toContain(`${health.dataset_b.summary.n_sessions} sessions · no ground truth`);
    expect(text).toContain("Read-only");
  });

  it("offers a menu toggle that reports its state", async () => {
    await renderApp();
    const toggle = screen.getByRole("button", { name: "Menu" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveAttribute("aria-controls", "main-nav");
    await userEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Close menu" })).toHaveAttribute("aria-expanded", "true");
  });

  it("puts the stage, the dataset and the evidence status in the top bar", async () => {
    const health = readBundleFile<InstrumentationFile>("instrumentation.json");
    const index = readBundleFile<unknown[]>("executions-index.json");
    await renderApp({ hash: "#process-mining" });
    const header = screen.getByRole("heading", { level: 2 }).closest("header") as HTMLElement;
    expect(header.querySelector(".eyebrow")?.textContent).toBe("04 · Investigation");
    const chips = header.querySelector("dl.topbar-status") as HTMLElement;
    expect(chips.textContent).toContain(
      `${health.dataset_b.summary.n_sessions} sessions · ${index.length} executions`);
    expect(chips.textContent).toContain("read-only");
  });
});

// ===================== DASHBOARD =====================

describe("Executive Dashboard story", () => {
  it("says what this is and what was analysed, from the bundle", async () => {
    const health = readBundleFile<InstrumentationFile>("instrumentation.json");
    const index = readBundleFile<unknown[]>("executions-index.json");
    const opp = readBundleFile<OpportunitiesFile>("opportunities.json");
    await renderApp();
    const hero = region(/From operation logs to a bounded automation proposal/);
    expect(hero.textContent).toContain(
      "An evidence-backed investigation across process reconstruction, process mining, and automation feasibility.");
    const kpis = within(hero).getByRole("list", { name: "Scope of the analysis" });
    const values = within(kpis).getAllByRole("listitem").map((li) => li.querySelector(".kpi-value")?.textContent);
    expect(values).toEqual([
      String(health.dataset_a.summary.n_sessions),
      String(index.length),
      String(opp.ranking.length),
      "77.05%",
    ]);
  });

  it("shows six clickable investigation stages that do not claim success", async () => {
    const metrics = readBundleFile<DatasetAMetrics>("dataset-a-metrics.json");
    await renderApp();
    const progress = region(/Investigation progress/);
    const stages = within(progress).getAllByRole("button");
    expect(stages).toHaveLength(6);
    expect(progress.textContent).toContain("A tick means the stage was carried out, not that it succeeded.");
    expect(progress.textContent).toContain(`Imperfect: boundary F1 ${metrics.pooled.f1.toFixed(4)}`);
    await userEvent.click(within(progress).getByRole("button", { name: /Reconstruction/ }));
    expect(await screen.findByRole("heading", { level: 2, name: "Day 2 · Reconstruction" })).toBeInTheDocument();
  });

  it("keeps the limitations next to the decision, with canonical numbers", async () => {
    const mc = readBundleFile<ModuleComparisonFile>("module-comparison.json");
    await renderApp();
    const limits = region(/^Limitations$/);
    const text = limits.textContent ?? "";
    expect(text).toContain("Boundary F1 0.3440");
    expect(text).toContain("Dataset B has no ground truth");
    expect(text).toContain("The HR system is a local mock");
    expect(text).toContain("Module 2 was not promoted");
    expect(text).toContain(`+${mc.gate.deltas.f1.toFixed(4)}`);
    expect(text).toContain(`+${Number(mc.gate.thresholds.min_f1_absolute_gain).toFixed(4)}`);
    // the decision and the limitations share one row at the top of the page
    expect(limits.parentElement).toBe(document.querySelector('[aria-labelledby="db-top"]')?.parentElement);
  });

  it("explains why this process with time share, bounded pattern and robustness", async () => {
    const opp = readBundleFile<OpportunitiesFile>("opportunities.json");
    const hr = readBundleFile<HrPayrollFile>("hr-payroll.json");
    const pm = inv().day3.process_metrics[hr.dominant_path.hr_process_id];
    await renderApp();
    const why = region(/Why this process\?/);
    const text = why.textContent ?? "";
    expect(text).toContain(`${(pm.time_share * 100).toFixed(1)}%`);
    expect(text).toContain("32.5%");
    expect(text).toContain("the largest share");
    expect(text).toContain("77.05%");
    expect(text).toContain(`${opp.sensitivity_summary!.n_hr_first} of ${opp.sensitivity_summary!.n_scenarios}`);
    expect(text).toContain(`worst observed rank ${opp.ranking[0].worst_rank}`);
  });

  it("lists what was built as a local prototype", async () => {
    await renderApp();
    const built = region(/What I built/);
    for (const item of ["Deterministic UI automation", "Human review", "Browser adapter", "Audit and failure handling"]) {
      expect(within(built).getByText(item)).toBeInTheDocument();
    }
    expect(within(built).getByText("LOCAL PROTOTYPE")).toBeInTheDocument();
  });
});

// ===================== DAY 1 =====================

describe("Day 1 · Data Audit", () => {
  it("shows both datasets with the artifact totals", async () => {
    const d = inv().day1.datasets;
    await renderApp({ hash: "#data-audit" });
    const overview = region(/Dataset overview/);
    const text = overview.textContent ?? "";
    expect(d.dataset_a.sessions).toBe(63);
    expect(d.dataset_a.chunks).toBe(117);
    expect(d.dataset_b.sessions).toBe(15);
    expect(d.dataset_b.chunks).toBe(20);
    expect(text).toContain(d.dataset_a.events.toLocaleString("en-US"));
    expect(text).toContain(d.dataset_b.events.toLocaleString("en-US"));
    expect(text).toContain("Ground truth available");
    expect(text).toContain("No ground truth");
    expect(text).toContain(`${d.dataset_a.multi_chunk_sessions} of ${d.dataset_a.sessions} sessions span 2+ files`);
  });

  it("lists the data-quality findings, each with expandable evidence", async () => {
    await renderApp({ hash: "#data-audit" });
    const findings = region(/Data quality findings/);
    const cards = within(findings).getAllByRole("listitem");
    expect(cards.length).toBeGreaterThanOrEqual(8);
    for (const title of [
      "Raw event order is not chronological",
      "Sessions are split across chunk files",
      "Most app_switch records are repeats",
      "browser_error is double-logged",
      "Screenshot availability differs by dataset",
      "Typed and pasted text is not reliably recorded",
      "Ground truth is consistent, with one gap",
      "Password fields were not redacted",
    ]) {
      expect(within(findings).getByRole("heading", { name: title })).toBeInTheDocument();
    }
    for (const card of cards) {
      expect(within(card).getByText("View evidence")).toBeInTheDocument();
    }
  });

  it("reports the password finding as a count and never carries a value", async () => {
    const investigation = inv();
    const checks = investigation.day1.checks.dataset_a.text_input_complete;
    expect(checks.password_fields_with_plaintext).toBe(18);
    // the bundle carries counts only: no text field of any kind
    expect(JSON.stringify(investigation)).not.toMatch(/final_text"|"password"|extracted_text"/);
    await renderApp({ hash: "#data-audit" });
    const card = screen.getByRole("heading", { name: "Password fields were not redacted" }).closest("li") as HTMLElement;
    expect(card.textContent).toContain(`${checks.password_fields_with_plaintext} Dataset-A text-input events`);
    expect(card.textContent).toContain("None is shown, copied or stored");
  });

  it("states what changed because of the findings", async () => {
    await renderApp({ hash: "#data-audit" });
    const changed = region(/What changed because of this/);
    const text = changed.textContent ?? "";
    expect(text).toContain("Chunk boundary→Not treated as a process boundary");
    expect(text).toContain("Screenshots→Dataset-specific, optional evidence");
    expect(text).toContain("Text input→Reconstructed cautiously");
    expect(text).toContain("Ground truth→Evidence, not an unquestionable oracle");
  });

  it("walks from observation to engineering decision", async () => {
    await renderApp({ hash: "#data-audit" });
    const table = screen.getByRole("table", { name: /Observation, test, finding and decision/ });
    const headers = within(table).getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual(["Observation", "Test", "Finding", "Engineering decision"]);
    expect(within(table).getAllByRole("row").length).toBe(6);
  });
});

// ===================== DAY 2 =====================

describe("Day 2 · Reconstruction", () => {
  it("shows the locked baseline as boundary / transition F1, never as accuracy", async () => {
    const pooled = readBundleFile<DatasetAMetrics>("dataset-a-metrics.json").pooled;
    await renderApp({ hash: "#reconstruction" });
    const panel = region(/Locked baseline \(Module 1\)/);
    expect(within(panel).getByText("Boundary / transition F1")).toBeInTheDocument();
    for (const v of [pooled.precision, pooled.recall, pooled.f1, pooled.under_segmentation_rate,
                     pooled.over_segmentation_rate]) {
      expect(within(panel).getAllByText(v.toFixed(4)).length).toBeGreaterThan(0);
    }
    expect(panel.textContent).toContain(`${pooled.pct_gt_executions_fragmented.toFixed(2)}%`);
    expect(pooled.f1.toFixed(4)).toBe("0.3440");
    expect(document.body.textContent).not.toMatch(/segmentation accuracy/i);
  });

  it("records every experiment with its result, failure mode and decision", async () => {
    const experiments = inv().day2.experiments;
    await renderApp({ hash: "#reconstruction" });
    const timeline = screen.getByRole("list", { name: "Day 2 experiments" });
    const later = screen.getByRole("list", { name: "Later challenges" });
    const cards = [...within(timeline).getAllByRole("listitem"), ...within(later).getAllByRole("listitem")];
    expect(cards).toHaveLength(experiments.length);
    const status = (id: string) => experiments.find((e) => e.id === id)!.status;
    expect(status("v1")).toBe("FAILED");
    expect(status("v2")).toBe("FAILED");
    expect(status("design2")).toBe("PROMISING");
    expect(status("agreement")).toBe("REJECTED");
    expect(status("tempo")).toBe("NOT SELECTED");
    expect(status("combined")).toBe("LOCKED");
    expect(status("module2")).toBe("NOT PROMOTED");
    expect(experiments.filter((e) => e.day === "Day 7").every((e) => e.status === "REJECTED")).toBe(true);
    for (const card of cards) {
      expect(card.textContent).toContain("Result");
      expect(card.textContent).toContain("Key failure mode");
      expect(card.textContent).toContain("Decision");
    }
  });

  it("copies experiment metrics from the canonical Day-2 comparison", async () => {
    const d2 = inv().day2;
    const combined = d2.experiments.find((e) => e.id === "combined")!;
    expect(combined.metrics).toEqual(d2.systems.Strategy_Combined);
    expect(d2.systems.Strategy_Combined.f1).toBe(0.3440233236151604);
    expect(d2.systems.V2.f1!.toFixed(4)).toBe("0.2397");
  });

  it("plots the trade-off with the locked baseline marked, and switches to recall", async () => {
    await renderApp({ hash: "#reconstruction" });
    const panel = region(/Trade-off: fragmentation against boundary quality/);
    const locked = within(panel).getByRole("img", { name: /^Locked baseline\./ });
    expect(locked.getAttribute("aria-label")).toContain("Fragmented executions 79%");
    expect(locked.getAttribute("aria-label")).toContain("Boundary F1 0.34");
    expect(within(panel).getByText("Locked baseline", { selector: "text" })).toBeInTheDocument();
    await userEvent.click(within(panel).getByRole("button", { name: "Recall vs fragmentation" }));
    expect(within(panel).getByRole("img", { name: /^Locked baseline\./ }).getAttribute("aria-label"))
      .toContain("Boundary recall 0.64");
  });

  it("shows a tooltip for a hovered point and keeps points keyboard-reachable", async () => {
    await renderApp({ hash: "#reconstruction" });
    const panel = region(/Trade-off: fragmentation against boundary quality/);
    const point = within(panel).getByRole("img", { name: /^C2\./ });
    expect(point).toHaveAttribute("tabindex", "0");
    await userEvent.hover(point);
    await waitFor(() => expect(panel.querySelector(".chart-tip")?.textContent).toContain("C2"));
  });

  it("explains why the baseline was retained with the C2 trade-off", async () => {
    await renderApp({ hash: "#reconstruction" });
    const panel = region(/Why the baseline was retained/);
    const text = panel.textContent ?? "";
    expect(text).toContain(
      "The final segmentation baseline was retained because later alternatives did not satisfy the pre-registered promotion criteria.");
    const pair = within(panel).getByLabelText(/Locked baseline compared with the rejected candidate C2/);
    expect(pair.textContent).toContain("0.3440");
    expect(pair.textContent).toContain("0.2822");
    expect(pair.textContent).toContain("40.87%");
    expect(pair.textContent).toContain("0.6606");
    expect(text).toContain("RETAIN LOCKED BASELINE");
  });
});

// ===================== DAY 3 =====================

describe("Day 3 · Process Mining", () => {
  it("summarises Dataset B from the bundle", async () => {
    const index = readBundleFile<unknown[]>("executions-index.json");
    const opp = readBundleFile<OpportunitiesFile>("opportunities.json");
    await renderApp({ hash: "#process-mining" });
    const overview = region(/Dataset B overview/);
    expect(within(overview).getByText(index.length.toLocaleString("en-US"))).toBeInTheDocument();
    expect(within(overview).getByText(String(opp.ranking.length))).toBeInTheDocument();
    expect(within(overview).getByText("15")).toBeInTheDocument();
  });

  it("shows the discovery pipeline in order", async () => {
    await renderApp({ hash: "#process-mining" });
    const steps = within(region(/Process discovery pipeline/)).getAllByRole("listitem")
      .map((li) => li.querySelector(".pipeline-name")?.textContent);
    expect(steps).toEqual(["Executions", "Traces", "Variants", "Directly-follows graph",
      "Operational metrics", "Feasibility", "Impact", "Opportunity"]);
  });

  it("charts every ranked process and can switch to recorded time", async () => {
    const processes = readBundleFile<ProcessRow[]>("processes.json");
    const ranked = processes.filter((p) => !p.excluded_from_ranking);
    await renderApp({ hash: "#process-mining" });
    const bars = screen.getByRole("list", { name: "Executions per ranked process" });
    expect(within(bars).getAllByRole("listitem")).toHaveLength(ranked.length);
    await userEvent.click(screen.getByRole("button", { name: "Recorded time" }));
    const byTime = screen.getByRole("list", { name: "Recorded time per ranked process" });
    expect(within(byTime).getAllByRole("listitem")[0].textContent).toContain("HR / Payroll System");
  });

  it("shows the canonical HR evidence card", async () => {
    const hr = readBundleFile<HrPayrollFile>("hr-payroll.json");
    await renderApp({ hash: "#process-mining" });
    const card = region(/HR \/ Payroll evidence/);
    const text = card.textContent ?? "";
    expect(hr.dominant_path.n_hr_executions_total).toBe(122);
    expect(hr.variant_split.dominant.n).toBe(94);
    expect(hr.variant_split.word_detour.n).toBe(24);
    expect(hr.variant_split.rare_edge.n).toBe(4);
    for (const v of ["122", "94", "24", "4", "77.05%"]) expect(text).toContain(v);
  });

  it("makes the HR flow prominent and labels the confirmation as inferred", async () => {
    const hr = readBundleFile<HrPayrollFile>("hr-payroll.json");
    await renderApp({ hash: "#process-mining" });
    const flow = region(/HR \/ Payroll: how the work flows/);
    expect(flow.textContent).toContain(
      `top ${hr.dfg.top_edges.length} of ${hr.dfg.n_edges} edges`);
    expect(within(flow).getByText("INFERRED FROM DOM")).toBeInTheDocument();
    expect(flow.textContent).toContain("139 clicks");
    expect(flow.textContent).toContain("138 clicks");
    expect(flow.textContent).toContain("134 pastes");
    expect(document.body.textContent).toContain(
      "High volume alone is insufficient. The target also needs a bounded and repetitive interaction pattern.");
  });
});

// ===================== DAY 4 =====================

describe("Day 4 · Evidence Health", () => {
  it("states the hypothesis and the flagged counts per dataset", async () => {
    const health = readBundleFile<InstrumentationFile>("instrumentation.json");
    expect(health.dataset_a.summary.n_degraded).toBe(8);
    expect(health.dataset_b.summary.n_degraded).toBe(2);
    await renderApp({ hash: "#evidence-health" });
    expect(document.body.textContent).toContain("Can instrumentation health be detected before segmentation?");
    const coverage = region(/Signal coverage/);
    expect(coverage.textContent).toContain("8/63 flagged");
    expect(coverage.textContent).toContain("2/15 flagged");
    expect(within(coverage).getAllByRole("img")).toHaveLength(2);
  });

  it("uses anonymous machine labels and never shows host names", async () => {
    const health = readBundleFile<InstrumentationFile>("instrumentation.json");
    const hosts = [...Object.keys(health.dataset_a.by_machine), ...Object.keys(health.dataset_b.by_machine)];
    await renderApp({ hash: "#evidence-health" });
    const machines = region(/Machine-level evidence/);
    const text = machines.textContent ?? "";
    for (const host of hosts) expect(text).not.toContain(host);
    expect(text).toContain("Machine A");
    const row = within(machines).getByRole("table", { name: "Dataset A sessions per machine" })
      .querySelector("tr.row-highlight") as HTMLElement;
    expect(row.textContent).toContain("7 (all)");
    expect(JSON.stringify(inv().day4)).not.toMatch(new RegExp(hosts.map((h) => h.replace(/[-]/g, "\\-")).join("|")));
  });

  it("shows that missing evidence merges work rather than splitting it", async () => {
    const ag = inv().day4.agreement;
    await renderApp({ hash: "#evidence-health" });
    const panel = region(/Key discovery/);
    expect(panel.textContent).toContain(
      "Degraded instrumentation was associated with merged work (under-segmentation), not with more splitting.");
    const table = within(panel).getByRole("table", { name: /Flagged versus healthy/ });
    for (const v of [ag.flagged_f1.median, ag.healthy_f1.median,
                     ag.flagged_under_segmentation.median, ag.healthy_under_segmentation.median]) {
      expect(table.textContent).toContain(v.toFixed(4));
    }
    expect(ag.confusion).toEqual({ tp: 8, fp: 0, fn: 2, tn: 53 });
  });

  it("shows the decision is unchanged when flagged sessions are removed", async () => {
    const sens = readBundleFile<InstrumentationSensitivityFile>("instrumentation-sensitivity.json");
    await renderApp({ hash: "#evidence-health" });
    const panel = region(/Does it change the decision\?/);
    expect(panel.textContent).toContain(`${sens.executions_total} → ${sens.executions_kept} executions`);
    expect(sens.executions_kept).toBe(571);
    expect(panel.textContent).toContain("0.4401");
    expect(panel.textContent).toContain("0.4180");
  });

  it("lists the diagnostic's limitations", async () => {
    await renderApp({ hash: "#evidence-health" });
    const text = region(/Diagnostic limitations/).textContent ?? "";
    expect(text).toContain("Diagnostic only");
    expect(text).toContain("derived on Dataset A");
    expect(text).toContain("Dataset B has no ground truth");
    expect(text).toContain("well instrumented");
  });
});

// ===================== DECISION CENTER / OPPORTUNITIES / COMPARISON =====================

describe("decision record", () => {
  it("reads as an engineering record", async () => {
    await renderApp({ hash: "#decision" });
    const record = region(/Decision record/);
    const keys = within(record).getAllByRole("term").map((t) => t.textContent);
    expect(keys).toEqual(["Decision", "Evidence", "Robustness", "Scope", "Boundary", "Risks"]);
    const items = document.querySelectorAll(".evidence-list > .evidence").length;
    expect(record.textContent).toContain(`${items} evidence items`);
    expect(record.textContent).toContain("4 routes, dominant path only");
    expect(record.textContent).toContain("Human review before every confirmation");
    expect(document.body.textContent).toContain(
      "Only the dominant deterministic HR path is inside the initial automation boundary.");
  });

  it("labels the OK-button reading as inferred from the DOM", async () => {
    await renderApp({ hash: "#decision" });
    const item = screen.getByRole("button", { name: /Confirmation is read from DOM structure/ });
    expect(within(item).getByText("INFERRED FROM DOM")).toBeInTheDocument();
  });
});

describe("Opportunities table and views", () => {
  it("shows the evaluator columns with executions, time share and sensitivity", async () => {
    const opp = readBundleFile<OpportunitiesFile>("opportunities.json");
    await renderApp({ hash: "#opportunities" });
    const table = screen.getByRole("table", { name: "Opportunity ranking" });
    const headers = within(table).getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual(["Rank", "Process", "Executions", "Time share", "Impact",
      "Feasibility", "Opportunity", "Pareto", "Sensitivity", "Evidence"]);
    const hrRow = within(table).getAllByRole("row")[1];
    const cells = within(hrRow).getAllByRole("cell").map((c) => c.textContent);
    expect(cells.slice(0, 9)).toEqual([
      "1", opp.ranking[0].readable_name, "122", "32.5%", "0.9236", "0.4765", "0.4401", "frontier", "#1–#3",
    ]);
    expect(document.body.textContent).toContain(
      "Opportunity score is a prioritization model, not monetary ROI.");
  });

  it("switches to a Pareto view without weights", async () => {
    const opp = readBundleFile<OpportunitiesFile>("opportunities.json");
    await renderApp({ hash: "#opportunities" });
    await userEvent.click(screen.getByRole("button", { name: "Pareto view" }));
    expect(screen.getByRole("button", { name: "Pareto view" })).toHaveAttribute("aria-pressed", "true");
    const frontier = screen.getByRole("table", { name: "Pareto frontier" });
    expect(within(frontier).getAllByRole("row")).toHaveLength(opp.pareto_frontier.n_frontier + 1);
    expect(screen.getAllByRole("img", { name: /Pareto frontier|Rank \d+/ }).length).toBeGreaterThan(0);
    expect(screen.queryByRole("table", { name: "Opportunity ranking" })).not.toBeInTheDocument();
  });
});

describe("Approach Comparison validation and rejection log", () => {
  it("summarises Module 2 as an experimental extension that was not promoted", async () => {
    const mc = readBundleFile<ModuleComparisonFile>("module-comparison.json");
    await renderApp({ hash: "#modules" });
    const panel = region(/Validation summary/);
    const text = panel.textContent ?? "";
    expect(text).toContain("Experimental extension — not promoted.");
    expect(text).toContain(`F1 ${mc.module1.canonical_pooled.f1.toFixed(4)}`);
    expect(text).toContain(`F1 ${mc.module2.best_matched.f1.toFixed(4)}`);
    expect(mc.module2.best_matched.f1.toFixed(4)).toBe("0.3519");
    expect(text).toContain("+0.0200");
    expect(text).toContain("+0.0102");
    expect(within(panel).getAllByText("NOT PROMOTED").length).toBeGreaterThan(0);
  });

  it("separates screenshot references from files that exist", async () => {
    const mc = readBundleFile<ModuleComparisonFile>("module-comparison.json");
    const v = mc.dataset_b_visual_review!;
    await renderApp({ hash: "#modules" });
    const panel = region(/Validation summary/);
    const value = (label: string) =>
      within(panel).getByText(label, { selector: "dt" }).parentElement?.querySelector(".record-main")?.textContent;
    expect(value("Sampled points")).toBe("40");
    expect(value("With a screenshot reference")).toBe("40/40");
    expect(value("Screenshots physically available")).toBe(`${v.screenshots_available}/${v.sample_size}`);
    expect(value("Screenshots physically available")).toBe("26/40");
    expect(value("Unavailable")).toBe("14");
    expect(panel.textContent).toContain("Vision-model surrogate review — not ground truth.");
    expect(document.body.textContent).not.toMatch(/40\/40 screenshots|40 screenshots available/i);
  });

  it("logs every approach with a result, a reason and a status", async () => {
    const experiments = inv().day2.experiments;
    await renderApp({ hash: "#modules" });
    const table = screen.getByRole("table", { name: "Experiment and rejection log" });
    const headers = within(table).getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual(["Approach", "Result", "Why", "Status"]);
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(experiments.length);
    const m2 = rows.find((r) => r.textContent?.includes("Module 2"))!;
    expect(m2.textContent).toContain("gain +0.0102 · required +0.0200");
    expect(m2.textContent).toContain("NOT PROMOTED");
    const locked = rows.find((r) => r.textContent?.includes("LOCKED"))!;
    expect(locked.textContent).toContain("F1 0.3440");
  });
});

// ===================== REPLAY AND DEMO =====================

describe("Execution Replay evidence labels", () => {
  it("shows execution metadata, evidence sources and screenshot availability", async () => {
    const sessions = readBundleFile<SessionRow[]>("sessions.json");
    const s = sessions.filter((x) => x.dataset === "dataset_b")[0];
    await renderApp({ hash: "#replay" });
    await userEvent.selectOptions(screen.getByLabelText("Session", { exact: true }), s.session_id);
    await userEvent.click((await screen.findAllByRole("button", { name: /exec\d+/ }))[0]);
    const panel = await screen.findByRole("region", { name: /Step replay —/ });
    expect(within(panel).getByText("Execution ID")).toBeInTheDocument();
    expect(within(panel).getByText("INFERRED · DOMINANT CONTEXT")).toBeInTheDocument();
    expect(within(panel).getByText("Not included in this bundle.", { exact: false })).toBeInTheDocument();
    expect(panel.textContent).toContain("81.2%");
    const labels = panel.querySelector('[aria-label="Evidence sources for this execution"]') as HTMLElement;
    expect(within(labels).getByText("OBSERVED")).toBeInTheDocument();
    expect(within(labels).getByText("CANONICAL")).toBeInTheDocument();
  });

  it("keeps event-type detail behind a toggle", async () => {
    const sessions = readBundleFile<SessionRow[]>("sessions.json");
    const s = sessions.filter((x) => x.dataset === "dataset_b")[0];
    await renderApp({ hash: "#replay" });
    await userEvent.selectOptions(screen.getByLabelText("Session", { exact: true }), s.session_id);
    await userEvent.click((await screen.findAllByRole("button", { name: /exec\d+/ }))[0]);
    const panel = await screen.findByRole("region", { name: /Step replay —/ });
    expect(panel.querySelector(".cat.mono")).toBeNull();
    await userEvent.click(within(panel).getByRole("button", { name: "Show event types" }));
    await waitFor(() => expect(panel.querySelector(".cat.mono")).not.toBeNull());
  });
});

const ROUTES = { status: 200, payload: { routes: ["#/payroll-items", "#/onboarding"] } };
const LOG = [
  { step: "route_check", detail: "'#/payroll-items' is an evidenced route", timestamp: "t" },
  { step: "note_check", detail: "note text is non-empty", timestamp: "t" },
  { step: "navigate", detail: "navigated to '#/payroll-items'", timestamp: "t" },
  { step: "find_note_field", detail: "found 'pi-note'", timestamp: "t" },
  { step: "insert_note", detail: "inserted note into 'pi-note'", timestamp: "t" },
  { step: "find_confirm_button", detail: "found 'btn-pi-ok'", timestamp: "t" },
  { step: "checkpoint", detail: "prepared -- awaiting human review", timestamp: "t" },
];
const CHECKPOINT = {
  checkpoint_token: "tok", execution_id: "exec_0123456789abcdef", status: "AWAITING_CONFIRMATION",
  integration_mode: "mock", route: "#/payroll-items", note_field_id: "pi-note",
  note_text: "Reviewed.", confirm_button_id: "btn-pi-ok", confirmed: false, action_log: LOG,
};
const CONFIRMED = {
  execution_id: "exec_0123456789abcdef", status: "CONFIRMED", integration_mode: "mock",
  route: "#/payroll-items", confirmed: true,
  action_log: [...LOG, { step: "confirm", detail: "human-approved: clicked 'btn-pi-ok'", timestamp: "t" }],
};

function demoApi(prepare: { status: number; payload: unknown } = { status: 200, payload: CHECKPOINT }): ApiHandler {
  return (path) => {
    if (path.endsWith("/routes")) return ROUTES;
    if (path.endsWith("/prepare")) return prepare;
    if (path.endsWith("/confirm")) return { status: 200, payload: CONFIRMED };
    return { status: 404, payload: {} };
  };
}

describe("HR Automation Demo flow", () => {
  it("states the target, the scope and the local-only boundary", async () => {
    const hr = readBundleFile<HrPayrollFile>("hr-payroll.json");
    await renderApp({ hash: "#automation", api: demoApi() });
    const scope = region(/Target and scope/);
    const nRoutes = Object.keys(hr.dominant_path.route_id_prefix_correspondence!).length;
    expect(scope.textContent).toContain("HR / Payroll System");
    expect(scope.textContent).toContain(`${nRoutes} evidenced routes`);
    expect(scope.textContent).toContain(`${hr.variant_split.dominant.n} of ${hr.dominant_path.n_hr_executions_total} executions`);
    expect(scope.textContent).toContain("not a real HR system");
    const steps = within(screen.getByRole("list", { name: "Demo steps" })).getAllByRole("listitem");
    expect(steps.map((s) => s.querySelector(".stepper-label")?.textContent))
      .toEqual(["Select route", "Enter note", "Review", "Confirm", "Audit result"]);
  });

  it("makes the review checkpoint impossible to miss", async () => {
    await renderApp({ hash: "#automation", api: demoApi() });
    await screen.findByRole("option", { name: "#/payroll-items" });
    await userEvent.type(screen.getByLabelText("Note text"), "Reviewed.");
    await userEvent.click(screen.getByRole("button", { name: "Prepare" }));
    await screen.findByText(/Nothing has been confirmed yet/i);
    const review = region(/Human review, then confirm/);
    expect(within(review).getByText("REVIEW REQUIRED")).toBeInTheDocument();
    const stepper = screen.getByRole("list", { name: "Demo steps" });
    expect(within(stepper).getByText("REVIEW REQUIRED").closest("li")).toHaveAttribute("aria-current", "step");
  });

  it("reports the audit result after confirmation", async () => {
    await renderApp({ hash: "#automation", api: demoApi() });
    await screen.findByRole("option", { name: "#/payroll-items" });
    await userEvent.click(screen.getByRole("button", { name: "Prepare" }));
    await userEvent.click(await screen.findByRole("button", { name: /Approve and confirm/ }));
    const outcome = region(/Audit result/);
    await within(outcome).findByText(/Automation completed/);
    const value = (label: string) =>
      within(outcome).getByText(label, { selector: "dt" }).parentElement?.querySelector("dd")?.textContent;
    expect(value("Execution ID")).toBe("exec_0123456789abcdef");
    expect(value("Status")).toBe("CONFIRMED");
    expect(value("Route")).toBe("#/payroll-items");
    expect(value("Audit event")).toBe("confirm: human-approved: clicked 'btn-pi-ok'");
    const states = within(screen.getByRole("list", { name: "Demo steps" })).getAllByRole("listitem")
      .map((s) => s.querySelector(".stepper-state")?.textContent);
    expect(states).toEqual(["done", "done", "done", "done", "done"]);
  });

  it("shows an invalid route as a safe stop, not an error wall", async () => {
    await renderApp({
      hash: "#automation",
      api: demoApi({
        status: 422,
        payload: {
          error_type: "UnknownRouteError",
          message: "unknown or unevidenced route: '#/nope'",
          action_log: [{ step: "route_check", detail: "REJECTED: not evidenced", timestamp: "t" }],
        },
      }),
    });
    await screen.findByRole("option", { name: "#/payroll-items" });
    await userEvent.click(screen.getByRole("button", { name: "Prepare" }));
    const outcome = region(/Audit result/);
    expect(await within(outcome).findByText("SAFE STOP")).toBeInTheDocument();
    expect(within(outcome).queryByRole("alert")).not.toBeInTheDocument();
    const stepper = screen.getByRole("list", { name: "Demo steps" });
    expect(within(stepper).getByText("SAFE STOP")).toBeInTheDocument();
  });
});

// ===================== EVIDENCE VOCABULARY =====================

describe("evidence vocabulary", () => {
  it("renders every evidence kind as readable text", () => {
    const kinds = ["canonical", "observed", "inferred", "experimental", "not-promoted", "prototype", "limitation"] as const;
    render(<div>{kinds.map((k) => <EvidenceBadge key={k} kind={k} />)}</div>);
    for (const label of ["CANONICAL", "OBSERVED", "INFERRED", "EXPERIMENTAL", "NOT PROMOTED", "PROTOTYPE", "LIMITATION"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("keeps the source collapsed until View evidence is opened", async () => {
    render(
      <EvidenceTrace source="reports/day3/problem2_audit_results.json" metric="Opportunity"
        method="Impact × Feasibility" limitations="Not a monetary estimate" />,
    );
    const details = screen.getByText("View evidence").closest("details") as HTMLDetailsElement;
    expect(details.open).toBe(false);
    await userEvent.click(screen.getByText("View evidence"));
    expect(details.open).toBe(true);
    expect(screen.getByText("Canonical source")).toBeInTheDocument();
    expect(screen.getByText("reports/day3/problem2_audit_results.json")).toBeInTheDocument();
    expect(screen.getByText("Limitations")).toBeInTheDocument();
  });
});

// ===================== INTEGRITY ACROSS THE NEW SCREENS =====================

describe("integrity of the investigation screens", () => {
  it.each(["#data-audit", "#reconstruction", "#process-mining", "#evidence-health", ""])(
    "%s never shows superseded or overclaiming text",
    async (hash) => {
      await renderApp({ hash });
      const text = document.body.textContent ?? "";
      expect(text).not.toContain("0.4186");
      expect(text).not.toMatch(/segmentation accuracy/i);
      expect(text).not.toContain("production-ready");
      expect(text).not.toContain("fully automated");
      expect(text).not.toMatch(/AI-powered/i);
    },
  );
});
