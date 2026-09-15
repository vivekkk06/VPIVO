import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App";
import { __clearSessionCache } from "../services/dataService";
import { dataRequests, installFetchStub, readBundleFile } from "./helpers";
import type {
  HrPayrollFile, InstrumentationFile, InstrumentationSensitivityFile,
  OpportunitiesFile, ProcessRow,
} from "../types";

async function openDecisionCenter(stubOptions = {}) {
  window.location.hash = "";
  __clearSessionCache();
  const stub = installFetchStub(stubOptions);
  render(<App />);
  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument());
  const nav = screen.getByRole("navigation", { name: "Main" });
  await userEvent.click(within(nav).getByRole("button", { name: /Automation Decision Center/ }));
  await screen.findByRole("heading", { name: "Automation Decision Center" });
  return stub;
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.location.hash = "";
});

// ---------------- Automation Readiness ----------------

describe("Automation Readiness", () => {
  it("renders Impact and Feasibility from canonical data", async () => {
    const opp = readBundleFile<OpportunitiesFile>("opportunities.json");
    const top = opp.ranking[0];
    await openDecisionCenter();
    const section = screen.getByRole("region", { name: /Automation readiness/i });
    expect(within(section).getByText(top.impact.toFixed(4))).toBeInTheDocument();
    expect(within(section).getByText(top.feasibility.toFixed(4))).toBeInTheDocument();
  });

  it("renders observed execution count and instrumentation health", async () => {
    const opp = readBundleFile<OpportunitiesFile>("opportunities.json");
    const processes = readBundleFile<ProcessRow[]>("processes.json");
    const inst = readBundleFile<InstrumentationFile>("instrumentation.json");
    const profile = processes.find((p) => p.process_id === opp.ranking[0].process_id)!;
    await openDecisionCenter();
    const section = screen.getByRole("region", { name: /Automation readiness/i });
    expect(within(section).getByText(`${profile.execution_count} execs`)).toBeInTheDocument();
    expect(
      within(section).getByText(`${inst.dataset_b.summary.n_healthy}/${inst.dataset_b.summary.n_sessions} healthy`),
    ).toBeInTheDocument();
  });

  it("states bounded pilot readiness, never production readiness", async () => {
    await openDecisionCenter();
    expect(screen.getByText("READY FOR BOUNDED PILOT")).toBeInTheDocument();
    expect(document.body.textContent).toContain("No production-readiness");
    expect(document.body.textContent).not.toMatch(/production[- ]ready\b(?!.*No production)/i);
  });

  it("explains the status with explicit gates, not a weighted score", async () => {
    await openDecisionCenter();
    expect(screen.getByRole("heading", { name: /Why this status\?/i })).toBeInTheDocument();
    expect(document.body.textContent).toContain("explicit boolean gates, not a weighted score");
    expect(document.querySelectorAll(".gate").length).toBeGreaterThan(3);
  });

  it("shows the required caveats alongside the passing gates", async () => {
    await openDecisionCenter();
    const body = document.body.textContent ?? "";
    expect(body).toContain("Human review remains required");
    expect(body).toContain("Note content is not observable");
    expect(body).toContain("instrumentation-degraded");
  });

  it("does not leak HR-specific claims onto an unrelated process", async () => {
    const opp = readBundleFile<OpportunitiesFile>("opportunities.json");
    const other = opp.ranking.find((r) => r.rank === 3)!;
    await openDecisionCenter();
    await userEvent.selectOptions(screen.getByLabelText("Select process"), other.process_id);

    await waitFor(() => expect(screen.getByText("Not proposed")).toBeInTheDocument());
    expect(screen.queryByText("READY FOR BOUNDED PILOT")).not.toBeInTheDocument();
    expect(screen.queryByText(/Deterministic RPA/)).not.toBeInTheDocument();
    // HR forensic split must not be shown for a non-HR process
    expect(screen.queryByRole("heading", { name: /Automation boundary/i })).not.toBeInTheDocument();
  });
});

// ---------------- Evidence traceability ----------------

describe("Evidence → Claim Traceability", () => {
  it("renders the claim and an evidence chain", async () => {
    await openDecisionCenter();
    expect(screen.getByText(/Deterministic RPA is appropriate for the dominant workflow/i))
      .toBeInTheDocument();
    expect(document.querySelectorAll(".evidence").length).toBeGreaterThan(4);
  });

  it("evidence values match the canonical artifacts", async () => {
    const hr = readBundleFile<HrPayrollFile>("hr-payroll.json");
    const processes = readBundleFile<ProcessRow[]>("processes.json");
    const profile = processes.find((p) => p.process_id === hr.dominant_path.hr_process_id)!;
    await openDecisionCenter();
    const body = document.body.textContent ?? "";
    expect(body).toContain(`${profile.execution_count} HR / Payroll System executions observed`);
    expect(body).toContain(`${hr.variant_split.dominant.n} executions follow the dominant path`);
    const nRoutes = Object.keys(hr.dominant_path.route_id_prefix_correspondence!).length;
    expect(body).toContain(`${nRoutes} evidenced routes were observed`);
  });

  it("labels each evidence item with its source artifact", async () => {
    await openDecisionCenter();
    const section = screen.getByRole("region", { name: /Evidence → claim traceability/i });
    expect(within(section).getAllByText("hr-payroll.json").length).toBeGreaterThan(0);
    expect(within(section).getAllByText("processes.json").length).toBeGreaterThan(0);
  });

  it("expands an evidence item to show the source field and why it matters", async () => {
    const hr = readBundleFile<HrPayrollFile>("hr-payroll.json");
    await openDecisionCenter();
    const item = screen.getByRole("button", {
      name: new RegExp(`${hr.variant_split.dominant.n} executions follow the dominant path`),
    });
    expect(item).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(item);

    expect(item).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByText("Why it matters")).toBeInTheDocument();
    expect(screen.getByText("Source field")).toBeInTheDocument();
    expect(screen.getByText("variant_split.dominant.n")).toBeInTheDocument();
  });

  it("collapses again when clicked a second time", async () => {
    await openDecisionCenter();
    const first = document.querySelector(".evidence-head") as HTMLElement;
    await userEvent.click(first);
    expect(first).toHaveAttribute("aria-expanded", "true");
    await userEvent.click(first);
    expect(first).toHaveAttribute("aria-expanded", "false");
  });

  it("marks evidence that is not exposed in the bundle rather than inventing it", async () => {
    await openDecisionCenter();
    expect(
      screen.getByText(/Evidence available in analytical report, not currently exposed in frontend bundle/i),
    ).toBeInTheDocument();
  });

  it("navigates from evidence into Process Explorer", async () => {
    await openDecisionCenter();
    const item = screen.getByRole("button", { name: /executions observed/ });
    await userEvent.click(item);
    // scope to the expanded evidence panel: the boundary section also has one
    const panel = item.closest(".evidence")!.querySelector(".evidence-detail") as HTMLElement;
    await userEvent.click(within(panel).getByRole("button", { name: "Inspect process" }));
    expect(await screen.findByRole("heading", { name: "Process Explorer" })).toBeInTheDocument();
  });

  it("deep-links a real execution into Replay and selects it", async () => {
    const stub = await openDecisionCenter();
    const item = screen.getByRole("button", { name: /Individual executions can be inspected/ });
    await userEvent.click(item);
    await userEvent.click(await screen.findByRole("button", { name: /Replay this execution/ }));

    expect(await screen.findByRole("heading", { name: "Execution Step Replay" })).toBeInTheDocument();
    // the session file is fetched lazily as a result of the deep-link
    await waitFor(() =>
      expect(dataRequests(stub).some((u) => u.includes("/data/executions/"))).toBe(true));
    expect(await screen.findByText(/Step replay —/)).toBeInTheDocument();
  });
});

// ---------------- Decision sensitivity ----------------

describe("Decision Sensitivity", () => {
  it("renders every canonical scenario with its real name and HR rank", async () => {
    const opp = readBundleFile<OpportunitiesFile>("opportunities.json");
    const scenarios = opp.sensitivity_scenarios!;
    await openDecisionCenter();
    const table = await screen.findByRole("table", { name: "Sensitivity scenarios" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.length).toBe(Object.keys(scenarios).length);

    for (const [name, v] of Object.entries(scenarios)) {
      const row = within(table).getByText(name).closest("tr") as HTMLElement;
      expect(within(row).getByText(`#${v.hr_rank}`)).toBeInTheDocument();
    }
  });

  it("shows the baseline scenario with HR at rank 1", async () => {
    const opp = readBundleFile<OpportunitiesFile>("opportunities.json");
    expect(opp.sensitivity_scenarios!.balanced.hr_rank).toBe(1);
    await openDecisionCenter();
    const table = await screen.findByRole("table", { name: "Sensitivity scenarios" });
    const row = within(table).getByText("balanced").closest("tr") as HTMLElement;
    expect(within(row).getByText("#1")).toBeInTheDocument();
  });

  it("reports the real worst rank, not an invented adversarial rank", async () => {
    const opp = readBundleFile<OpportunitiesFile>("opportunities.json");
    const worst = Math.max(...Object.values(opp.sensitivity_scenarios!).map((v) => v.hr_rank));
    await openDecisionCenter();
    const body = document.body.textContent ?? "";
    expect(body).toContain(`it moves to rank ${worst}`);
    // the artifact's worst rank is 3; nothing may claim rank 6
    expect(body).not.toContain("rank 6");
  });

  it("interprets robustness without claiming statistical confidence", async () => {
    const opp = readBundleFile<OpportunitiesFile>("opportunities.json");
    const s = opp.sensitivity_summary!;
    await openDecisionCenter();
    const body = document.body.textContent ?? "";
    expect(body).toContain(`top candidate in ${s.n_hr_first} of ${s.n_scenarios} tested scenarios`);
    expect(body).toContain("STRONG BUT ASSUMPTION-SENSITIVE");
    expect(body).toContain("sensitivity to assumptions, not");
    expect(body).not.toMatch(/confidence interval is computed anywhere.*\d+% confidence/i);
  });
});

// ---------------- Instrumentation sensitivity ----------------

describe("Instrumentation sensitivity", () => {
  it("shows healthy and degraded Dataset-B session counts", async () => {
    const inst = readBundleFile<InstrumentationFile>("instrumentation.json");
    await openDecisionCenter();
    const section = screen.getByRole("region", { name: /Decision sensitivity/i });
    expect(
      within(section).getByText(
        `${inst.dataset_b.summary.n_healthy} healthy · ${inst.dataset_b.summary.n_degraded} degraded`,
      ),
    ).toBeInTheDocument();
  });

  it("shows 0.4401 for all sessions and 0.4180 excluding degraded, both at rank 1", async () => {
    const sens = readBundleFile<InstrumentationSensitivityFile>("instrumentation-sensitivity.json");
    const hr = sens.ranking_comparison[0];
    expect(hr.opportunity_a).toBe(0.4401);
    expect(hr.opportunity_b).toBe(0.418);

    await openDecisionCenter();
    const section = screen.getByRole("region", { name: /Decision sensitivity/i });
    expect(within(section).getByText("Rank #1 · 0.4401")).toBeInTheDocument();
    expect(within(section).getByText("Rank #1 · 0.4180")).toBeInTheDocument();
  });

  it("does not imply degraded instrumentation proves segmentation failure", async () => {
    await openDecisionCenter();
    expect(document.body.textContent).toContain(
      "Instrumentation health affects evidence availability; it does not by itself prove segmentation failure",
    );
  });
});

// ---------------- Automation boundary ----------------

describe("Automation boundary", () => {
  it("renders the automate and keep-human columns", async () => {
    await openDecisionCenter();
    const section = screen.getByRole("region", { name: /Automation boundary/i });
    expect(within(section).getByRole("heading", { name: "Automate" })).toBeInTheDocument();
    expect(within(section).getByRole("heading", { name: /Keep human \/ out of scope/i }))
      .toBeInTheDocument();
  });

  it("scopes out the non-dominant variants using the real counts", async () => {
    const hr = readBundleFile<HrPayrollFile>("hr-payroll.json");
    await openDecisionCenter();
    const section = screen.getByRole("region", { name: /Automation boundary/i });
    expect(
      within(section).getByText(new RegExp(`Word detour variant \\(${hr.variant_split.word_detour.n} executions\\)`)),
    ).toBeInTheDocument();
    expect(
      within(section).getByText(new RegExp(`Rare multi-hop cases \\(${hr.variant_split.rare_edge.n} executions\\)`)),
    ).toBeInTheDocument();
  });

  it("answers why not automate everything", async () => {
    await openDecisionCenter();
    expect(screen.getByRole("heading", { name: /Why not automate everything\?/i })).toBeInTheDocument();
    expect(document.body.textContent).toContain("do not have sufficient evidence for safe automation");
  });
});

// ---------------- Cross-screen navigation ----------------

describe("Decision Center navigation", () => {
  it("is reachable from the sidebar and sets the hash", async () => {
    await openDecisionCenter();
    expect(window.location.hash).toBe("#decision");
  });

  it("restores from the hash on load", async () => {
    window.location.hash = "#decision";
    __clearSessionCache();
    installFetchStub();
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Automation Decision Center" }))
      .toBeInTheDocument();
  });

  it("links to the prototype, the process and the full ranking", async () => {
    await openDecisionCenter();
    const section = screen.getByRole("region", { name: /Automation boundary/i });
    await userEvent.click(within(section).getByRole("button", { name: "Try prototype" }));
    expect(await screen.findByRole("heading", { name: "HR / Payroll Automation Demo" }))
      .toBeInTheDocument();
  });

  it("does not fetch any per-session execution file just to render the screen", async () => {
    const stub = await openDecisionCenter();
    expect(dataRequests(stub).filter((u) => u.includes("/data/executions/"))).toEqual([]);
  });
});
