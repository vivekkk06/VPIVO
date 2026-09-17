/**
 * Day-6 Approach Comparison screen — Module 1 vs Module 2.
 *
 * Every assertion reads its expected value from the REAL generated bundle rather than
 * a literal, so a stale or drifting artifact fails the test instead of passing
 * silently. The two properties that matter most here are that the screen shows Module 2
 * was **not** promoted, and that it never lets the two coverage numbers (0.7705 and
 * 0.5082) be read as the same quantity.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App";
import { __clearSessionCache } from "../services/dataService";
import { installFetchStub, readBundleFile } from "./helpers";
import type { ModuleComparisonFile } from "../types";

const mc = () => readBundleFile<ModuleComparisonFile>("module-comparison.json");

async function openModules() {
  window.location.hash = "";
  __clearSessionCache();
  installFetchStub();
  render(<App />);
  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "Executive Dashboard" })).toBeInTheDocument());
  const nav = screen.getByRole("navigation", { name: "Main" });
  await userEvent.click(within(nav).getByRole("button", { name: /Approach Comparison/ }));
  await screen.findByRole("heading", { name: "Approach Comparison" });
}

async function showView(name: RegExp) {
  await userEvent.click(screen.getByRole("button", { name }));
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.location.hash = "";
});

// ===================== NAVIGATION =====================

describe("Approach Comparison — navigation", () => {
  it("is reachable from the main navigation", async () => {
    await openModules();
    expect(screen.getByRole("heading", { name: "Approach Comparison" })).toBeInTheDocument();
  });

  it("offers a switcher for both approaches", async () => {
    await openModules();
    const group = screen.getByRole("group", { name: "Approach" });
    expect(within(group).getByRole("button", { name: /Module 1 — Continuity/ })).toBeInTheDocument();
    expect(within(group).getByRole("button", { name: /Module 2 — Adaptive Evidence/ })).toBeInTheDocument();
    expect(within(group).getByRole("button", { name: /Comparison/ })).toBeInTheDocument();
  });

  it("opens on the comparison view", async () => {
    await openModules();
    expect(screen.getByRole("button", { name: /^Comparison$/ }))
      .toHaveAttribute("aria-pressed", "true");
  });
});

// ===================== MODULE 1 VIEW =====================

describe("Module 1 view", () => {
  it("presents Module 1 as the locked baseline", async () => {
    await openModules();
    await showView(/Module 1 — Continuity/);
    expect(screen.getByText(/LOCKED BASELINE/)).toBeInTheDocument();
    expect(screen.getByText(/does not modify it/i)).toBeInTheDocument();
  });

  it("renders the canonical Dataset-A metrics from the bundle", async () => {
    const p = mc().module1.canonical_pooled;
    await openModules();
    await showView(/Module 1 — Continuity/);
    const panel = document.querySelector('[aria-labelledby="mc-m1"]') as HTMLElement;
    expect(within(panel).getByText(p.f1.toFixed(4))).toBeInTheDocument();
    expect(within(panel).getByText(p.recall.toFixed(4))).toBeInTheDocument();
    expect(within(panel).getByText(`${p.pct_gt_executions_fragmented.toFixed(2)}%`))
      .toBeInTheDocument();
  });

  it("keeps the canonical F1 at the locked value", async () => {
    expect(mc().module1.canonical_pooled.f1).toBe(0.3440233236151604);
    await openModules();
    await showView(/Module 1 — Continuity/);
    expect(screen.getAllByText("0.3440").length).toBeGreaterThan(0);
  });

  it("never relabels the segmentation score as accuracy", async () => {
    await openModules();
    await showView(/Module 1 — Continuity/);
    expect(document.body.textContent).not.toContain("segmentation accuracy");
  });
});

// ===================== MODULE 2 VIEW =====================

describe("Module 2 view", () => {
  it("states that Module 2 was not promoted", async () => {
    const m2 = mc().module2;
    expect(m2.decision).toContain("NOT PROMOTED");
    await openModules();
    await showView(/Module 2 — Adaptive Evidence/);
    expect(screen.getByText(new RegExp(m2.decision))).toBeInTheDocument();
  });

  it("does not call the approach an AI model", async () => {
    await openModules();
    await showView(/Module 2 — Adaptive Evidence/);
    expect(screen.getByText(/not an AI model/i)).toBeInTheDocument();
  });

  it("lists every feature set including the control", async () => {
    const keys = Object.keys(mc().module2.feature_sets);
    await openModules();
    await showView(/Module 2 — Adaptive Evidence/);
    const table = screen.getByRole("table", { name: /Module 2 feature sets/i });
    for (const key of keys) {
      expect(within(table).getByText(key)).toBeInTheDocument();
    }
    expect(within(table).getByText(/control/)).toBeInTheDocument();
  });

  it("reports the content-drift coverage rather than hiding it", async () => {
    const cov = mc().module2.content_drift_coverage;
    await openModules();
    await showView(/Module 2 — Adaptive Evidence/);
    expect(screen.getByText(`${(cov.fraction * 100).toFixed(2)}%`)).toBeInTheDocument();
    expect(document.body.textContent).toContain("0.03%");
  });

  it("shows the pre-registered gate with its failing check", async () => {
    const gate = mc().gate;
    expect(gate.failed_gates.length).toBeGreaterThan(0);
    await openModules();
    await showView(/Module 2 — Adaptive Evidence/);
    const table = screen.getByRole("table", { name: /Promotion gate checks/i });
    expect(within(table).getAllByText("FAIL").length).toBe(gate.failed_gates.length);
    expect(within(table).getAllByText("PASS").length).toBeGreaterThan(0);
  });

  it("says the gate was registered before candidates were scored", async () => {
    expect(mc().gate.registered_before_candidates_were_scored).toBe(true);
    await openModules();
    await showView(/Module 2 — Adaptive Evidence/);
    expect(document.body.textContent).toMatch(/not adjusted after seeing results/i);
  });
});

// ===================== DATASET B AND AUTOMATION =====================

describe("Dataset-B and automation evidence", () => {
  it("states the Dataset-B rule and never shows a Dataset-B accuracy", async () => {
    await openModules();
    await showView(/Module 2 — Adaptive Evidence/);
    const text = document.body.textContent ?? "";
    expect(text).toContain("not supervised segmentation evaluation");
    expect(text).not.toMatch(/Dataset.B\s+(accuracy|F1|precision|recall)/i);
  });

  it("reports the human review as not performed rather than filling it in", async () => {
    // The surrogate visual review is separate: it never writes into the human sheet.
    expect(mc().dataset_b_review.review_status).toContain("NOT REVIEWED");
    await openModules();
    await showView(/Module 2 — Adaptive Evidence/);
    const panel = document.querySelector('[aria-labelledby="mc-db"]') as HTMLElement;
    expect(within(panel).getByText("NOT REVIEWED")).toBeInTheDocument();
    expect(within(panel).getByText("Human review status")).toBeInTheDocument();
    expect(panel.textContent).toContain("judgments ship empty by design");
  });

  it("surfaces the missing screenshot files as a limitation", async () => {
    const missing = mc().dataset_b_review.screenshot_availability
      .nearest_screenshot_file_missing_on_disk;
    await openModules();
    await showView(/Module 2 — Adaptive Evidence/);
    const panel = document.querySelector('[aria-labelledby="mc-db"]') as HTMLElement;
    expect(within(panel).getByText(String(missing))).toBeInTheDocument();
  });

  it("keeps routing coverage and the canonical dominant share distinct", async () => {
    const a = mc().automation;
    expect(a.coverage.observed_dominant_path_coverage)
      .not.toBe(a.canonical_dominant_share);
    await openModules();
    await showView(/Module 2 — Adaptive Evidence/);
    const panel = document.querySelector('[aria-labelledby="mc-auto"]') as HTMLElement;
    expect(within(panel).getByText(a.coverage.observed_dominant_path_coverage.toFixed(4)))
      .toBeInTheDocument();
    expect(within(panel).getByText(a.canonical_dominant_share.toFixed(4)))
      .toBeInTheDocument();
    expect(panel.textContent).toContain("two different quantities");
  });

  it("never calls routing coverage automation accuracy", async () => {
    await openModules();
    await showView(/Module 2 — Adaptive Evidence/);
    expect(document.body.textContent).toContain("not automation accuracy");
  });

  it("reports that no non-dominant execution was admitted", async () => {
    const byVariant = mc().automation.by_canonical_variant;
    expect(byVariant.word_detour.eligible ?? 0).toBe(0);
    expect(byVariant.rare_edge.eligible ?? 0).toBe(0);
    await openModules();
    await showView(/Module 2 — Adaptive Evidence/);
    expect(screen.getByText(/of 28 detour \+ rare-edge executions/)).toBeInTheDocument();
  });

  it("states that monetary ROI cannot be estimated", async () => {
    await openModules();
    await showView(/Module 2 — Adaptive Evidence/);
    expect(screen.getByText(new RegExp(mc().process_analysis.monetary_roi_statement.slice(0, 60))))
      .toBeInTheDocument();
  });

  it("reports the operator variation as indistinguishable from noise", async () => {
    const d = mc().process_analysis.operator_dispersion;
    expect(d.differs_beyond_chance_at_0_05).toBe(false);
    await openModules();
    await showView(/Module 2 — Adaptive Evidence/);
    const panel = document.querySelector('[aria-labelledby="mc-proc"]') as HTMLElement;
    expect(panel.textContent).toContain("not distinguishable");
    expect(within(panel).getByRole("table", { name: /Operator variant analysis/i }))
      .toBeInTheDocument();
  });

  it("confirms the Pareto frontier reproduces the canonical one", async () => {
    expect(mc().process_analysis.pareto_matches_canonical).toBe(true);
    await openModules();
    await showView(/Module 2 — Adaptive Evidence/);
    expect(document.body.textContent).toContain("matches the canonical frontier exactly");
  });
});

// ===================== DATASET-B VISUAL REVIEW =====================

const visual = () => mc().dataset_b_visual_review!;

function visualPanel() {
  return document.querySelector('[aria-labelledby="mc-dbv"]') as HTMLElement;
}

/** The value shown under a metric tile's label, read from the rendered tile. */
function tileValue(panel: HTMLElement, label: string) {
  const labelEl = within(panel).getByText(label, { selector: ".label" });
  return labelEl.parentElement?.querySelector(".value")?.textContent;
}

describe("Dataset-B visual review", () => {
  it("ships in the bundle as a surrogate review, not ground truth", () => {
    const v = visual();
    expect(v).not.toBeNull();
    expect(v.label).toContain("not ground truth");
    expect(v.human_review).toContain("NOT PERFORMED");
    expect(v.hash_verified_at_reveal).toBe(true);
  });

  it("is labelled as a surrogate visual review, not ground truth", async () => {
    await openModules();
    await showView(/Module 2 — Adaptive Evidence/);
    const panel = visualPanel();
    expect(within(panel).getByRole("heading", { name: "Dataset-B Visual Review" }))
      .toBeInTheDocument();
    expect(panel.textContent).toContain("Surrogate visual review — not ground truth.");
    expect(panel.textContent).toContain("Human review: not performed.");
  });

  it("renders every count from the bundle", async () => {
    const v = visual();
    await openModules();
    await showView(/Module 2 — Adaptive Evidence/);
    const panel = visualPanel();
    expect(tileValue(panel, "Sample size")).toBe(String(v.sample_size));
    expect(tileValue(panel, "Screenshots available")).toBe(String(v.screenshots_available));
    expect(tileValue(panel, "Screenshots unavailable")).toBe(String(v.screenshots_unavailable));
    expect(tileValue(panel, "Clear boundary")).toBe(String(v.counts.B_CLEAR_BOUNDARY));
    expect(tileValue(panel, "Clear continuity")).toBe(String(v.counts.A_CLEAR_CONTINUITY));
    expect(tileValue(panel, "Ambiguous")).toBe(String(v.counts.C_AMBIGUOUS));
    expect(tileValue(panel, "Review status")).toBe(v.status.split("—")[0].trim());
  });

  it("never counts an unavailable screenshot as judged", () => {
    const v = visual();
    expect(v.screenshots_available + v.screenshots_unavailable).toBe(v.sample_size);
    expect(v.counts.D_UNAVAILABLE).toBe(v.screenshots_unavailable);
    const judged = v.counts.A_CLEAR_CONTINUITY + v.counts.B_CLEAR_BOUNDARY + v.counts.C_AMBIGUOUS;
    expect(judged).toBe(v.screenshots_available);
    expect(v.boundary_samples_judgeable + v.control_samples_judgeable).toBe(judged);
  });

  it("shows the labels by sample type only as revealed counts", async () => {
    const v = visual();
    await openModules();
    await showView(/Module 2 — Adaptive Evidence/);
    const table = within(visualPanel()).getByRole("table", { name: /Visual labels by sample type/i });
    const rows = within(table).getAllByRole("row");
    const cells = (name: string) => rows.find((r) => r.textContent?.startsWith(name))!
      .querySelectorAll("td");
    for (const [name, c] of [["Predicted boundaries", v.counts_by_sample_type.boundary_sample],
                             ["Mid-execution controls", v.counts_by_sample_type.control_sample]] as const) {
      const td = cells(name);
      expect([...td].slice(1).map((t) => t.textContent)).toEqual(
        [c.A_CLEAR_CONTINUITY, c.B_CLEAR_BOUNDARY, c.C_AMBIGUOUS, c.D_UNAVAILABLE].map(String));
    }
    expect(table.textContent).toContain("revealed after judging");
  });

  it("states the decision as descriptive, never as a metric", async () => {
    const v = visual();
    await openModules();
    await showView(/Module 2 — Adaptive Evidence/);
    const text = visualPanel().textContent ?? "";
    expect(text).toContain(`Decision: ${v.decision.outcome}.`);
    expect(text).toContain(v.decision.statement);
    expect(text).toContain("not segmentation metrics");
    expect(text).not.toMatch(/\b(accuracy|precision|recall|F1)\b/i);
    expect(text).not.toMatch(/segmentation is accurate/i);
  });

  it("does not use the review to promote Module 2", async () => {
    await openModules();
    await showView(/Module 2 — Adaptive Evidence/);
    expect(visualPanel().textContent).toContain("NOT PROMOTED");
    expect(visual().decision.module2_promotion).toContain("not a basis for promotion");
  });

  it("says so, rather than showing numbers, when the review artifact is absent", async () => {
    window.location.hash = "";
    __clearSessionCache();
    const base = installFetchStub();
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.endsWith("module-comparison.json")) {
        return new Response(JSON.stringify({ ...mc(), dataset_b_visual_review: null }),
          { status: 200, headers: { "Content-Type": "application/json" } });
      }
      return base(input, init);
    }));
    render(<App />);
    await waitFor(() =>
      expect(screen.getByRole("heading", { name: "Executive Dashboard" })).toBeInTheDocument());
    const nav = screen.getByRole("navigation", { name: "Main" });
    await userEvent.click(within(nav).getByRole("button", { name: /Approach Comparison/ }));
    await screen.findByRole("heading", { name: "Approach Comparison" });
    await showView(/Module 2 — Adaptive Evidence/);
    const panel = visualPanel();
    expect(panel.textContent).toContain("has not been run in this bundle");
    expect(within(panel).queryByText("Clear boundary")).toBeNull();
    await showView(/^Comparison$/);
    expect(document.body.textContent).toContain("Framework prepared; review not completed");
  });
});

// ===================== COMPARISON VIEW =====================

describe("Comparison view", () => {
  it("shows both module statuses side by side", async () => {
    const m = mc();
    await openModules();
    const panel = document.querySelector('[aria-labelledby="mc-verdict"]') as HTMLElement;
    expect(within(panel).getByText(m.module1.status)).toBeInTheDocument();
    expect(within(panel).getByText(m.module2.status)).toBeInTheDocument();
  });

  it("refuses to rank the modules with a composite score", async () => {
    await openModules();
    expect(document.body.textContent).toContain("not ranked by a composite score");
  });

  it("renders the dimension-by-dimension table", async () => {
    await openModules();
    const table = screen.getByRole("table", { name: /Module comparison by dimension/i });
    const text = table.textContent ?? "";
    for (const dimension of ["Status", "F1 — Module 1 thresholds",
                             "F1 — thresholds re-selected", "Fragmentation %",
                             "Promotion gate", "Robustness", "Final decision",
                             "Automation coverage", "Safety controls", "Dataset-B review"]) {
      expect(text).toContain(dimension);
    }
    const review = within(table).getAllByRole("row")
      .find((r) => r.textContent?.startsWith("Dataset-B review"))!;
    const outcome = mc().dataset_b_visual_review!.decision.outcome.toLowerCase();
    expect(review.textContent).toContain(`Surrogate visual review, not ground truth: ${outcome}`);
    expect(review.textContent).toContain("human review not completed");
  });

  it("never puts unlike quantities side by side in the dimension table", async () => {
    // The original table showed canonical recall beside M2C's recall under different
    // thresholds and labelled a control-relative delta as the difference. Every
    // numeric row must now carry both values under the same thresholds.
    const m = mc();
    await openModules();
    const table = screen.getByRole("table", { name: /Module comparison by dimension/i });
    const header = within(table).getAllByRole("columnheader").map((h) => h.textContent);
    expect(header).toEqual(["Dimension", "Module 1", "Module 2"]);

    const rows = within(table).getAllByRole("row");
    const locked = rows.find((r) => r.textContent?.startsWith("F1 — Module 1 thresholds"))!;
    expect(locked.textContent).toContain(m.module1.canonical_pooled.f1.toFixed(4));
    expect(locked.textContent).toContain(m.module2.best_locked.f1.toFixed(4));

    const reselected = rows.find((r) => r.textContent?.startsWith("F1 — thresholds re-selected"))!;
    expect(reselected.textContent).toContain(m.module1.control_matched.f1.toFixed(4));
    expect(reselected.textContent).toContain(m.module2.best_matched.f1.toFixed(4));
  });

  it("measures the promotion gain from the control, and says so", async () => {
    const m = mc();
    await openModules();
    const panel = document.querySelector('[aria-labelledby="mc-seg"]') as HTMLElement;
    expect(panel.textContent).toContain(
      `gain is measured from ${m.module1.control_matched.f1.toFixed(4)}`);
    expect(panel.textContent).toContain(
      `not from the canonical ${m.module1.canonical_pooled.f1.toFixed(4)}`);
  });

  it("states the promotion outcome in precise, non-promotional wording", async () => {
    await openModules();
    expect(document.body.textContent).toContain(
      "Module 2 reduced fragmentation in the best experimental configuration, but the F1 "
      + "gain did not meet the pre-registered promotion gate, so Module 1 remains canonical.");
  });

  it("shows the gate requirement beside the achieved gain", async () => {
    const gate = mc().gate;
    await openModules();
    const panel = document.querySelector('[aria-labelledby="mc-seg"]') as HTMLElement;
    expect(within(panel).getByText(
      `+${Number(gate.thresholds.min_f1_absolute_gain).toFixed(4)}`)).toBeInTheDocument();
    expect(within(panel).getByText(`+${gate.deltas.f1.toFixed(4)}`)).toBeInTheDocument();
  });
});

// ===================== INTEGRITY =====================

describe("Approach Comparison — integrity", () => {
  it("never introduces the superseded 0.4186 value", async () => {
    await openModules();
    for (const view of [/Module 1 — Continuity/, /Module 2 — Adaptive Evidence/, /^Comparison$/]) {
      await showView(view);
      expect(document.body.textContent).not.toContain("0.4186");
    }
  });

  it("never claims production readiness or full automation", async () => {
    await openModules();
    for (const view of [/Module 1 — Continuity/, /Module 2 — Adaptive Evidence/, /^Comparison$/]) {
      await showView(view);
      const text = document.body.textContent ?? "";
      expect(text).not.toContain("production-ready");
      expect(text).not.toContain("fully automated");
    }
  });

  it("never uses wording that implies Module 2 was promoted or won", async () => {
    await openModules();
    for (const view of [/Module 1 — Continuity/, /Module 2 — Adaptive Evidence/, /^Comparison$/]) {
      await showView(view);
      const text = (document.body.textContent ?? "").toLowerCase();
      for (const phrase of ["winner", "improved segmentation", "better segmentation",
                            "module 2 is better", "module 2 improved"]) {
        expect(text).not.toContain(phrase);
      }
    }
  });

  it("discloses that the human review of the Dataset-B sheet was not completed", async () => {
    await openModules();
    await showView(/Module 2 — Adaptive Evidence/);
    const panel = document.querySelector('[aria-labelledby="mc-db"]') as HTMLElement;
    expect(panel.textContent).toContain("Human review not completed.");
    expect(panel.textContent).toContain(
      "no Dataset-B segmentation quality claim is made from it");
    expect(panel.textContent?.toLowerCase()).not.toContain("validated");
    for (const view of [/Module 2 — Adaptive Evidence/, /^Comparison$/]) {
      await showView(view);
      expect((document.body.textContent ?? "").toLowerCase()).not.toContain("validated");
    }
  });

  it("carries a provenance panel like every other screen", async () => {
    await openModules();
    expect(screen.getByText(/Data source/i)).toBeInTheDocument();
  });
});
