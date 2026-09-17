import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App";
import { __clearSessionCache } from "../services/dataService";
import { dataRequests, installFetchStub, readBundleFile } from "./helpers";
import type {
  EngineeringUpgradeFile, HrPayrollFile, InstrumentationFile, OpportunitiesFile,
  ProcessRow, SessionRow,
} from "../types";

/** The app syncs the screen to location.hash so back/refresh work. jsdom keeps
 *  one document per file, so the hash must be reset or each test would resume
 *  on whichever screen the previous test left. */
async function renderApp(stubOptions = {}) {
  window.location.hash = "";
  __clearSessionCache();
  const stub = installFetchStub(stubOptions);
  render(<App />);
  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "Executive Dashboard" })).toBeInTheDocument());
  return stub;
}

async function goTo(name: string) {
  const nav = screen.getByRole("navigation", { name: "Main" });
  await userEvent.click(within(nav).getByRole("button", { name: new RegExp(name) }));
}

const okRoutes = { status: 200, payload: { routes: ["#/payroll-items", "#/onboarding"] } };
const CHECKPOINT = {
  checkpoint_token: "tok",
  route: "#/payroll-items",
  note_field_id: "pi-note",
  note_text: "Reviewed.",
  confirm_button_id: "btn-pi-ok",
  confirmed: false,
  action_log: [
    { step: "route_check", detail: "'#/payroll-items' is an evidenced route", timestamp: "t" },
    { step: "note_check", detail: "note text is non-empty", timestamp: "t" },
    { step: "navigate", detail: "navigated to '#/payroll-items'", timestamp: "t" },
    { step: "find_note_field", detail: "found 'pi-note'", timestamp: "t" },
    { step: "insert_note", detail: "inserted note into 'pi-note'", timestamp: "t" },
    { step: "find_confirm_button", detail: "found 'btn-pi-ok'", timestamp: "t" },
    { step: "checkpoint", detail: "prepared -- awaiting human review", timestamp: "t" },
  ],
};

afterEach(() => {
  vi.unstubAllGlobals();
  window.location.hash = "";
});

// ===================== DASHBOARD =====================

describe("Dashboard", () => {
  it("renders the top automation opportunity card from canonical data", async () => {
    const opp = readBundleFile<OpportunitiesFile>("opportunities.json");
    const top = opp.ranking[0];
    await renderApp();

    expect(screen.getByRole("heading", { name: /Decision at a glance/i })).toBeInTheDocument();
    expect(screen.getByText(top.readable_name)).toBeInTheDocument();
    expect(screen.getAllByText(top.opportunity.toFixed(4)).length).toBeGreaterThan(0);
    expect(screen.getAllByText(top.impact.toFixed(4)).length).toBeGreaterThan(0);
    expect(screen.getAllByText(top.feasibility.toFixed(4)).length).toBeGreaterThan(0);
  });

  it("presents the segmentation score as a limitation, never as a good result", async () => {
    await renderApp();
    const text = document.body.textContent ?? "";
    // The honest framing must survive: weak result, imbalance as context not excuse,
    // and an explicit statement that Dataset B is not validated by these numbers.
    expect(text).toContain("material limitation");
    expect(text).toContain("1.03%");
    expect(text).toContain("does not excuse the value");
    expect(text).toContain("Dataset B is not validated by these numbers");
    // And it must never be relabelled as accuracy.
    expect(text).not.toContain("segmentation accuracy");
  });

  it("shows the rejected alternatives that justify keeping the architecture", async () => {
    await renderApp();
    const text = document.body.textContent ?? "";
    expect(text).toContain("0.0194");
    expect(text).toContain("225 false");
  });

  it("shows observed HR volume from the process profile, not hardcoded", async () => {
    const opp = readBundleFile<OpportunitiesFile>("opportunities.json");
    const processes = readBundleFile<ProcessRow[]>("processes.json");
    const profile = processes.find((p) => p.process_id === opp.ranking[0].process_id)!;
    await renderApp();
    expect(screen.getByText(`${profile.execution_count} executions`)).toBeInTheDocument();
  });

  it("labels the recommendation as deterministic RPA only for the prototyped process", async () => {
    const hr = readBundleFile<HrPayrollFile>("hr-payroll.json");
    const opp = readBundleFile<OpportunitiesFile>("opportunities.json");
    await renderApp();
    if (opp.ranking[0].process_id === hr.dominant_path.hr_process_id) {
      expect(screen.getByText("Deterministic RPA")).toBeInTheDocument();
      const nRoutes = Object.keys(hr.dominant_path.route_id_prefix_correspondence as object).length;
      expect(screen.getByText(new RegExp(`${nRoutes} evidenced routes`))).toBeInTheDocument();
    }
  });

  it("states the opportunity score is not a monetary ROI", async () => {
    await renderApp();
    expect(screen.getByText(/not a monetary ROI/i)).toBeInTheDocument();
  });

  it("Explore process navigates to Process Explorer with that process open", async () => {
    const opp = readBundleFile<OpportunitiesFile>("opportunities.json");
    await renderApp();
    await userEvent.click(screen.getByRole("button", { name: /Explore process/i }));
    expect(await screen.findByRole("heading", { name: "Process Explorer" })).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { name: opp.ranking[0].readable_name }),
    ).toBeInTheDocument();
  });

  it("Try automation navigates to the HR Automation Demo", async () => {
    await renderApp();
    await userEvent.click(screen.getByRole("button", { name: /Try automation/i }));
    expect(
      await screen.findByRole("heading", { name: "HR / Payroll Automation Demo" }),
    ).toBeInTheDocument();
  });

  it("renders healthy and degraded counts per dataset from the Day-4 artifact", async () => {
    const inst = readBundleFile<InstrumentationFile>("instrumentation.json");
    await renderApp();
    const health = screen.getByRole("region", { name: /Instrumentation health/i });
    expect(within(health).getAllByText(String(inst.dataset_a.summary.n_healthy)).length).toBeGreaterThan(0);
    expect(within(health).getAllByText(String(inst.dataset_b.summary.n_healthy)).length).toBeGreaterThan(0);
    expect(within(health).getAllByText(String(inst.dataset_b.summary.n_degraded)).length).toBeGreaterThan(0);
  });

  it("degraded Dataset-B count navigates to Replay filtered to degraded sessions", async () => {
    const sessions = readBundleFile<SessionRow[]>("sessions.json");
    const degradedB = sessions.filter((s) => s.dataset === "dataset_b" && s.status === "degraded");
    await renderApp();

    await userEvent.click(screen.getByRole("button", { name: /degraded Dataset B sessions/i }));
    expect(await screen.findByRole("heading", { name: "Execution Step Replay" })).toBeInTheDocument();
    const toggle = screen.getByRole("button", { name: /Degraded instrumentation only/i });
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByText(new RegExp(`Showing ${degradedB.length} of`)),
    ).toBeInTheDocument();
  });

  it("distinguishes instrumentation quality from segmentation quality", async () => {
    await renderApp();
    expect(document.body.textContent).toContain("Instrumentation quality is not segmentation quality");
    expect(document.body.textContent).toContain("does not by itself prove segmentation failure");
  });

  it("keeps the Dataset-A quality metrics and the F1 wording", async () => {
    await renderApp();
    // F1 now appears twice: the metric card and the baseline-retention table.
    // Scope to the quality panel so the assertion stays unambiguous.
    const quality = document.querySelector('[aria-labelledby="db-quality"]') as HTMLElement;
    expect(quality).toBeTruthy();
    expect(within(quality).getAllByText("0.3440").length).toBeGreaterThan(0);
    expect(within(quality).getByText("0.2358")).toBeInTheDocument();
    expect(within(quality).getByText("0.6355")).toBeInTheDocument();
    expect(screen.getByText(/Transition-level F1, not/i)).toBeInTheDocument();
    expect(screen.queryByText(/segmentation accuracy/i)).not.toBeInTheDocument();
  });
});

// ===================== OPPORTUNITIES =====================

describe("Opportunities", () => {
  it("renders the canonical HR opportunity 0.4401", async () => {
    const opp = readBundleFile<OpportunitiesFile>("opportunities.json");
    expect(opp.ranking[0].opportunity).toBe(0.4401);
    await renderApp();
    await goTo("Opportunities");
    expect(await screen.findAllByText("0.4401")).not.toHaveLength(0);
  });

  it("never shows the superseded pre-entropy-fix value", async () => {
    await renderApp();
    await goTo("Opportunities");
    await screen.findAllByText("0.4401");
    expect(screen.queryByText("0.4186")).not.toBeInTheDocument();
  });

  it("shows Impact, Feasibility and Opportunity as separate columns", async () => {
    await renderApp();
    await goTo("Opportunities");
    const table = await screen.findByRole("table", { name: "Opportunity ranking" });
    expect(within(table).getByRole("columnheader", { name: "Impact" })).toBeInTheDocument();
    expect(within(table).getByRole("columnheader", { name: "Feasibility" })).toBeInTheDocument();
    expect(within(table).getByRole("columnheader", { name: "Opportunity" })).toBeInTheDocument();
  });

  it("explains that Opportunity is not a monetary ROI", async () => {
    await renderApp();
    await goTo("Opportunities");
    expect(document.body.textContent).toContain("Not a monetary ROI estimate");
  });

  it("orders rank 4 as Financial Accounting and rank 5 as Expense Calculation", async () => {
    await renderApp();
    await goTo("Opportunities");
    const table = await screen.findByRole("table", { name: "Opportunity ranking" });
    const rows = within(table).getAllByRole("row");
    expect(within(rows[4]).getByText(/Financial Accounting/)).toBeInTheDocument();
    expect(within(rows[5]).getByText(/Expense Calculation/)).toBeInTheDocument();
  });

  it("takes Pareto status from the artifact rather than inferring it from rank", async () => {
    const opp = readBundleFile<OpportunitiesFile>("opportunities.json");
    await renderApp();
    await goTo("Opportunities");
    const table = await screen.findByRole("table", { name: "Opportunity ranking" });
    const rows = within(table).getAllByRole("row");
    // a dominated row exists below the frontier rows, proving status != rank
    opp.ranking.slice(0, 6).forEach((r, i) => {
      expect(within(rows[i + 1]).getByText(r.pareto_status!)).toBeInTheDocument();
    });
  });

  it("expands a Why? panel with evidence drawn from the artifacts", async () => {
    const hr = readBundleFile<HrPayrollFile>("hr-payroll.json");
    await renderApp();
    await goTo("Opportunities");
    const whyButtons = await screen.findAllByRole("button", { name: "Why?" });
    await userEvent.click(whyButtons[0]);

    expect(await screen.findByRole("heading", { name: /Why HR \/ Payroll System ranks 1/ }))
      .toBeInTheDocument();
    expect(whyButtons[0]).toHaveAttribute("aria-expanded", "true");
    // forensic split numbers come from hr-payroll.json
    expect(document.body.textContent).toContain(`${hr.variant_split.dominant.n} dominant-path`);
    expect(document.body.textContent).toContain(`${hr.variant_split.word_detour.n} Word-detour`);
  });

  it("Why? panel can navigate into Process Explorer", async () => {
    await renderApp();
    await goTo("Opportunities");
    await userEvent.click((await screen.findAllByRole("button", { name: "Why?" }))[0]);
    await userEvent.click(await screen.findByRole("button", { name: /Open in Process Explorer/ }));
    expect(await screen.findByRole("heading", { name: "Process Explorer" })).toBeInTheDocument();
  });

  it("shows the canonical-source note", async () => {
    await renderApp();
    await goTo("Opportunities");
    expect((await screen.findAllByText(/problem2_audit_results\.json/)).length).toBeGreaterThan(0);
  });
});

// ===================== PROCESS EXPLORER =====================

describe("Process Explorer", () => {
  async function openHr() {
    await renderApp();
    await goTo("Process Explorer");
    await userEvent.click(await screen.findByRole("button", { name: /^HR \/ Payroll System$/ }));
  }

  it("renders the HR forensic variant split 94 / 24 / 4 from the source artifact", async () => {
    const hr = readBundleFile<HrPayrollFile>("hr-payroll.json");
    await openHr();
    const cards = await screen.findByText("Dominant path");
    expect(cards).toBeInTheDocument();

    for (const [key, label] of [
      ["dominant", "Dominant path"],
      ["word_detour", "Word detour"],
      ["rare_edge", "Rare multi-hop"],
    ] as const) {
      const card = screen.getByText(label).closest(".split-card") as HTMLElement;
      expect(within(card).getByText(String(hr.variant_split[key].n))).toBeInTheDocument();
    }
  });

  it("distinguishes the forensic split from generic variants", async () => {
    await openHr();
    expect(await screen.findByText(/different classification/i)).toBeInTheDocument();
  });

  it("keeps the DFG heading accurate as top X of Y edges", async () => {
    const hr = readBundleFile<HrPayrollFile>("hr-payroll.json");
    await openHr();
    expect(document.body.textContent).toContain(
      `Directly-follows graph — top ${hr.dfg.top_edges.length} of ${hr.dfg.n_edges} edges`,
    );
  });

  it("does not claim the shown edges are the complete graph", async () => {
    const hr = readBundleFile<HrPayrollFile>("hr-payroll.json");
    await openHr();
    expect(document.body.textContent).toContain("not the complete graph");
    expect(document.body.textContent).toContain(`of ${hr.dfg.n_edges}`);
  });

  it("draws only the edges the artifact persisted", async () => {
    const hr = readBundleFile<HrPayrollFile>("hr-payroll.json");
    await openHr();
    const flowRows = document.querySelectorAll(".flow-row");
    expect(flowRows.length).toBe(hr.dfg.top_edges.length);
  });

  it("keeps the DFG table alongside the flow", async () => {
    const hr = readBundleFile<HrPayrollFile>("hr-payroll.json");
    await openHr();
    const edge = hr.dfg.top_edges[0];
    expect(screen.getAllByText(edge.source).length).toBeGreaterThan(0);
    expect(screen.getAllByText(String(edge.count)).length).toBeGreaterThan(0);
  });

  it("renders why-this-process-matters evidence from the artifacts", async () => {
    const processes = readBundleFile<ProcessRow[]>("processes.json");
    const hr = readBundleFile<HrPayrollFile>("hr-payroll.json");
    const profile = processes.find((p) => p.process_id === hr.dominant_path.hr_process_id)!;
    await openHr();
    const why = await screen.findByRole("heading", { name: /Why this process matters/i });
    const block = why.closest(".why") as HTMLElement;
    expect(within(block).getByText(`${profile.execution_count} executions`)).toBeInTheDocument();
    expect(block.textContent).toContain("evidenced routes");
    expect(block.textContent).toContain("No monetary saving is claimed");
  });

  it("says DFG and forensic split are HR-only for other processes", async () => {
    await renderApp();
    await goTo("Process Explorer");
    await userEvent.click((await screen.findAllByRole("button", { name: /Order & Inventory/ }))[0]);
    expect(await screen.findByText(/available for HR\/Payroll only/i)).toBeInTheDocument();
    expect(document.querySelectorAll(".flow-row").length).toBe(0);
  });
});

// ===================== REPLAY =====================

describe("Execution Step Replay", () => {
  it("is named as step replay and disclaims a raw event stream", async () => {
    await renderApp();
    await goTo("Execution Replay");
    expect(await screen.findByRole("heading", { name: "Execution Step Replay" })).toBeInTheDocument();
    expect(document.body.textContent).toContain("not an individual-event replay");
    expect(document.body.textContent).toContain("no raw event stream exists");
  });

  it("keeps Dataset A non-replayable and says why", async () => {
    const sessions = readBundleFile<SessionRow[]>("sessions.json");
    const nB = sessions.filter((s) => s.dataset === "dataset_b").length;
    await renderApp();
    await goTo("Execution Replay");
    expect(document.body.textContent).toContain("Dataset A has no replay view");
    const options = await screen.findByLabelText("Session", { exact: true });
    expect(options.querySelectorAll("option[value]:not([value=''])").length).toBe(nB);
  });

  it("filters the session list by search text", async () => {
    const sessions = readBundleFile<SessionRow[]>("sessions.json");
    const target = sessions.find((s) => s.dataset === "dataset_b")!;
    await renderApp();
    await goTo("Execution Replay");

    await userEvent.type(screen.getByLabelText("Search sessions"), target.operator);
    const expected = sessions.filter(
      (s) => s.dataset === "dataset_b" && s.operator.includes(target.operator)).length;
    await waitFor(() =>
      expect(screen.getByText(new RegExp(`Showing ${expected} of`))).toBeInTheDocument());
  });

  it("filters to degraded-instrumentation sessions", async () => {
    const sessions = readBundleFile<SessionRow[]>("sessions.json");
    const degraded = sessions.filter((s) => s.dataset === "dataset_b" && s.status === "degraded");
    await renderApp();
    await goTo("Execution Replay");
    await userEvent.click(screen.getByRole("button", { name: /Degraded instrumentation only/i }));
    await waitFor(() =>
      expect(screen.getByText(new RegExp(`Showing ${degraded.length} of`))).toBeInTheDocument());
  });

  it("lazy-loads a session's executions only on selection", async () => {
    const stub = await renderApp();
    await goTo("Execution Replay");
    expect(dataRequests(stub).filter((u) => u.includes("/executions/"))).toEqual([]);

    const sessions = readBundleFile<SessionRow[]>("sessions.json");
    const sessionId = sessions.filter((s) => s.dataset === "dataset_b")[0].session_id;
    await userEvent.selectOptions(screen.getByLabelText("Session", { exact: true }), sessionId);

    await waitFor(() =>
      expect(dataRequests(stub)).toContain(`/data/executions/${sessionId}.json`));
  });

  it("shows degraded instrumentation state for the selected session", async () => {
    const sessions = readBundleFile<SessionRow[]>("sessions.json");
    const degraded = sessions.find((s) => s.dataset === "dataset_b" && s.status === "degraded")!;
    await renderApp();
    await goTo("Execution Replay");
    await userEvent.selectOptions(
      screen.getByLabelText("Session", { exact: true }), degraded.session_id);
    expect(await screen.findByText("Instrumentation degraded")).toBeInTheDocument();
    expect(document.body.textContent).toContain("does not by itself prove");
  });

  it("counts executions and supports a process filter", async () => {
    const sessions = readBundleFile<SessionRow[]>("sessions.json");
    const s = sessions.filter((x) => x.dataset === "dataset_b")[0];
    await renderApp();
    await goTo("Execution Replay");
    await userEvent.selectOptions(screen.getByLabelText("Session", { exact: true }), s.session_id);

    expect(await screen.findByText(new RegExp(`Showing ${s.n_executions} of ${s.n_executions}`)))
      .toBeInTheDocument();
    const filter = screen.getByLabelText("Filter executions by process");
    const options = Array.from(filter.querySelectorAll("option")).map((o) => o.textContent);
    expect(options.length).toBeGreaterThan(1);
  });

  it("renders ordered_steps as steps and keeps the playback controls", async () => {
    const sessions = readBundleFile<SessionRow[]>("sessions.json");
    const sessionId = sessions.filter((s) => s.dataset === "dataset_b")[0].session_id;
    await renderApp();
    await goTo("Execution Replay");
    await userEvent.selectOptions(screen.getByLabelText("Session", { exact: true }), sessionId);
    await userEvent.click((await screen.findAllByRole("button", { name: /exec\d+/ }))[0]);

    expect(await screen.findByText(/persisted steps/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Play replay" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Restart/ })).toBeInTheDocument();
    expect(screen.getByText(/Step 1 of \d+/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "2x" }));
    expect(screen.getByRole("button", { name: "2x" })).toHaveAttribute("aria-pressed", "true");
  });
});

// ===================== AUTOMATION DEMO =====================

describe("HR Automation Demo", () => {
  it("cannot confirm without a prepared checkpoint", async () => {
    await renderApp({ api: () => okRoutes });
    await goTo("HR Automation Demo");
    expect(await screen.findByText(/Confirmation is impossible until Prepare succeeds/i))
      .toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Approve and confirm/ })).not.toBeInTheDocument();
  });

  it("warns when the automation API is unreachable", async () => {
    await renderApp();
    await goTo("HR Automation Demo");
    expect(await screen.findByText(/Automation API not reachable/i)).toBeInTheDocument();
  });

  it("renders a step timeline mirroring the backend action log", async () => {
    await renderApp({
      api: (path: string) => path.endsWith("/routes") ? okRoutes
        : { status: 200, payload: CHECKPOINT },
    });
    await goTo("HR Automation Demo");
    await userEvent.type(screen.getByLabelText("Note text"), "Reviewed.");
    await userEvent.click(screen.getByRole("button", { name: "Prepare" }));

    const timeline = await screen.findByRole("list", { name: /Automation step timeline/i });
    expect(within(timeline).getByText("Validate route")).toBeInTheDocument();
    expect(within(timeline).getByText("Human review checkpoint")).toBeInTheDocument();
    // confirm is shown as not-yet-performed, never as done
    expect(within(timeline).getByText("not yet performed")).toBeInTheDocument();
  });

  it("shows the review checkpoint before anything is confirmed", async () => {
    await renderApp({
      api: (path: string) => path.endsWith("/routes") ? okRoutes
        : { status: 200, payload: CHECKPOINT },
    });
    await goTo("HR Automation Demo");
    await userEvent.type(screen.getByLabelText("Note text"), "Reviewed.");
    await userEvent.click(screen.getByRole("button", { name: "Prepare" }));

    expect(await screen.findByText(/Nothing has been confirmed yet/i)).toBeInTheDocument();
    expect(screen.getByText("btn-pi-ok")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Approve and confirm/ })).toBeInTheDocument();
  });

  it("reports the safety controls as enforced by the backend", async () => {
    await renderApp({
      api: (path: string) => path.endsWith("/routes") ? okRoutes
        : { status: 200, payload: CHECKPOINT },
    });
    await goTo("HR Automation Demo");
    await userEvent.click(screen.getByRole("button", { name: "Prepare" }));
    await screen.findByText(/Nothing has been confirmed yet/i);

    const safety = screen.getByRole("region", { name: /Automation safety/i });
    expect(within(safety).getByText("Route validation")).toBeInTheDocument();
    expect(within(safety).getByText("Confirm-time re-verification")).toBeInTheDocument();
    // not yet confirmed -> that control is still pending, not claimed as done
    expect(within(safety).getAllByText("pending").length).toBeGreaterThan(0);
  });

  it("renders a completion summary from the API result after confirmation", async () => {
    const result = {
      route: "#/payroll-items",
      confirmed: true,
      action_log: [...CHECKPOINT.action_log,
        { step: "confirm", detail: "human-approved: clicked 'btn-pi-ok'", timestamp: "t" }],
    };
    await renderApp({
      api: (path: string) => path.endsWith("/routes") ? okRoutes
        : path.endsWith("/prepare") ? { status: 200, payload: CHECKPOINT }
          : { status: 200, payload: result },
    });
    await goTo("HR Automation Demo");
    await userEvent.click(screen.getByRole("button", { name: "Prepare" }));
    await userEvent.click(await screen.findByRole("button", { name: /Approve and confirm/ }));

    expect(await screen.findByText(/Automation completed/i)).toBeInTheDocument();
    // action count comes from the API payload, not a hardcoded claim
    expect(screen.getByText(String(result.action_log.length))).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("0 unsafe actions");
  });

  it("reports an invalid route as a safe stop", async () => {
    await renderApp({
      api: (path: string) => path.endsWith("/routes") ? okRoutes : {
        status: 422,
        payload: {
          error_type: "UnknownRouteError",
          message: "unknown or unevidenced route: '#/nope'",
          action_log: [{ step: "route_check", detail: "REJECTED: not evidenced", timestamp: "t" }],
        },
      },
    });
    await goTo("HR Automation Demo");
    await userEvent.click(screen.getByRole("button", { name: "Prepare" }));

    expect(await screen.findByText(/Safe stop — UnknownRouteError/)).toBeInTheDocument();
    expect(screen.getByText(/refused to proceed rather than guessing/i)).toBeInTheDocument();
    const timeline = screen.getByRole("list", { name: /Automation step timeline/i });
    expect(within(timeline).getByText(/REJECTED/)).toBeInTheDocument();
  });

  it("reports an empty note as a safe stop", async () => {
    await renderApp({
      api: (path: string) => path.endsWith("/routes") ? okRoutes : {
        status: 422,
        payload: {
          error_type: "InvalidNoteError",
          message: "note text must be non-empty",
          action_log: [{ step: "note_check", detail: "REJECTED: empty", timestamp: "t" }],
        },
      },
    });
    await goTo("HR Automation Demo");
    await userEvent.click(screen.getByRole("button", { name: "Prepare" }));
    expect(await screen.findByText(/Safe stop — InvalidNoteError/)).toBeInTheDocument();
  });

  it("fails safely when a consumed checkpoint token is replayed", async () => {
    let confirms = 0;
    await renderApp({
      api: (path: string) => {
        if (path.endsWith("/routes")) return okRoutes;
        if (path.endsWith("/prepare")) return { status: 200, payload: CHECKPOINT };
        // Count confirmations explicitly rather than treating every other call as
        // one. The screen also asks the API which integration targets it offers,
        // and that lookup is not a confirmation. The assertion below is unchanged
        // and now measures exactly what it claims to.
        if (!path.endsWith("/confirm")) return { status: 404, payload: {} };
        confirms += 1;
        return confirms === 1
          ? { status: 200, payload: { route: "#/payroll-items", confirmed: true, action_log: [] } }
          : { status: 400, payload: { message: "unknown or expired checkpoint token -- run prepare first" } };
      },
    });
    await goTo("HR Automation Demo");
    await userEvent.click(screen.getByRole("button", { name: "Prepare" }));
    await userEvent.click(await screen.findByRole("button", { name: /Approve and confirm/ }));
    await screen.findByText(/Automation completed/i);

    // the confirm control is gone once consumed, so the UI cannot replay a token
    expect(screen.queryByRole("button", { name: /Approve and confirm/ })).not.toBeInTheDocument();
    expect(confirms).toBe(1);
  });

  it("reports an API error as an API error", async () => {
    await renderApp({
      api: (path: string) => path.endsWith("/routes") ? okRoutes
        : { status: 500, payload: { message: "boom" } },
    });
    await goTo("HR Automation Demo");
    await userEvent.click(screen.getByRole("button", { name: "Prepare" }));
    expect(await screen.findByText(/API error/)).toBeInTheDocument();
  });
});

// ===================== NAVIGATION / RESILIENCE =====================

describe("navigation and resilience", () => {
  it("syncs the screen to the location hash so back/refresh work", async () => {
    await renderApp();
    await goTo("Opportunities");
    await screen.findByRole("heading", { name: "Opportunities" });
    expect(window.location.hash).toBe("#opportunities");
  });

  it("restores the screen from the hash on load", async () => {
    window.location.hash = "#processes";
    __clearSessionCache();
    installFetchStub();
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Process Explorer" })).toBeInTheDocument();
  });

  it("shows a data error instead of crashing when a bundle file is missing", async () => {
    window.location.hash = "";
    __clearSessionCache();
    installFetchStub({ missing: ["processes.json"] });
    render(<App />);
    expect(await screen.findByText(/Data error/i)).toBeInTheDocument();
    expect(screen.getByText(/processes\.json/)).toBeInTheDocument();
  });
});

// ===================== FINAL POLISH PASS =====================
// Page headers, "Decision at a glance", and the baseline-retention explainer.
// These assert against the real generated bundle, never hardcoded values.

describe("Page headers", () => {
  const screens: [string, string, RegExp][] = [
    ["Dashboard", "Dashboard", /Dataset A \+ Dataset B/],
    ["Execution Replay", "Execution Step Replay", /Dataset B/],
    ["Process Explorer", "Process Explorer", /ranked processes/],
    ["Opportunities", "Opportunities", /canonical ranking/],
    ["Automation Decision Center", "Automation Decision Center", /executions/],
    ["HR Automation Demo", "HR \\/ Payroll Automation Demo", /LOCAL VALIDATED/],
  ];

  it.each(screens)("%s has a title, purpose and dataset context", async (nav, heading, ctx) => {
    await renderApp();
    if (nav !== "Dashboard") await goTo(nav);
    const h = await screen.findByRole("heading", { name: new RegExp(heading) });
    const header = h.closest("header") as HTMLElement;
    expect(header).toBeTruthy();
    // purpose line
    expect(header.querySelector(".lede")?.textContent?.length ?? 0).toBeGreaterThan(20);
    // dataset / status context line
    expect(header.querySelector(".page-context")?.textContent ?? "").toMatch(ctx);
  });
});

describe("Dashboard — decision at a glance", () => {
  it("shows the canonical Opportunity, rank and Pareto status from the bundle", async () => {
    const opp = readBundleFile<OpportunitiesFile>("opportunities.json");
    const top = opp.ranking[0];
    await renderApp();
    const panel = document.querySelector('[aria-labelledby="db-top"]') as HTMLElement;
    expect(panel).toBeTruthy();
    expect(within(panel).getAllByText(top.opportunity.toFixed(4)).length).toBeGreaterThan(0);
    expect(within(panel).getByText(new RegExp(`Rank ${top.rank} of`))).toBeInTheDocument();
    if (top.pareto_status === "frontier") {
      expect(within(panel).getAllByText("Yes").length).toBeGreaterThan(0);
    }
  });

  it("shows the dominant-path split and share from the HR forensic artifact", async () => {
    const hr = readBundleFile<HrPayrollFile>("hr-payroll.json");
    const processes = readBundleFile<ProcessRow[]>("processes.json");
    const profile = processes.find((p) => p.process_id === hr.dominant_path.hr_process_id)!;
    await renderApp();
    const panel = document.querySelector('[aria-labelledby="db-top"]') as HTMLElement;
    const text = panel.textContent ?? "";
    // 94 / 122 -- the forensic automation grouping, not the 7 variant signatures
    expect(text).toContain(`${hr.variant_split.dominant.n} / ${profile.execution_count}`);
    expect(text).toContain((profile.dominant_variant_share * 100).toFixed(2));
  });

  it("states READY FOR BOUNDED PILOT with its qualifier, not production readiness", async () => {
    await renderApp();
    const panel = document.querySelector('[aria-labelledby="db-top"]') as HTMLElement;
    const text = panel.textContent ?? "";
    expect(text).toContain("READY FOR BOUNDED PILOT");
    expect(text).toContain("human review remains required");
    expect(text).not.toContain("production-ready");
    expect(text).not.toContain("fully automated");
  });

  it("labels sensitivity as scenarios, never as statistical confidence", async () => {
    const opp = readBundleFile<OpportunitiesFile>("opportunities.json");
    await renderApp();
    const panel = document.querySelector('[aria-labelledby="db-top"]') as HTMLElement;
    const s = opp.sensitivity_summary!;
    expect(panel.textContent).toContain(`#1 in ${s.n_hr_first}/${s.n_scenarios} scenarios`);
    expect(panel.textContent).toContain("not statistical confidence");
  });

  it("offers a route into the Decision Center", async () => {
    await renderApp();
    await userEvent.click(screen.getByRole("button", { name: /Inspect decision/i }));
    expect(
      await screen.findByRole("heading", { name: "Automation Decision Center" }),
    ).toBeInTheDocument();
  });
});

describe("Dashboard — why the baseline was retained", () => {
  it("keeps the weak F1 visible rather than hiding it behind the explainer", async () => {
    await renderApp();
    const quality = document.querySelector('[aria-labelledby="db-quality"]') as HTMLElement;
    expect(within(quality).getAllByText("0.3440").length).toBeGreaterThan(0);
    expect(quality.textContent).toContain("79.05%");
  });

  it("explains the retention decision with the canonical Day-7 trade-off", async () => {
    const up = readBundleFile<EngineeringUpgradeFile>("engineering-upgrade.json");
    const sc = up.segmentation_challenge;
    await renderApp();

    const summary = screen.getByText(/Why was the baseline retained\?/i);
    expect(summary).toBeInTheDocument();
    await userEvent.click(summary);

    const table = screen.getByRole("table", { name: /Locked baseline versus/i });
    const text = table.textContent ?? "";
    expect(text).toContain(sc.baseline_f1.toFixed(4));
    expect(text).toContain(sc.baseline_fragmentation_pct.toFixed(2));
    expect(text).toContain(sc.best_candidate_f1.toFixed(4));
    expect(text).toContain(sc.best_candidate_fragmentation_pct.toFixed(2));
    expect(text).toContain(sc.best_candidate_under_segmentation.toFixed(4));
    expect(text).toContain(sc.best_candidate_label);
  });

  it("states that no candidate passed the pre-registered gates", async () => {
    await renderApp();
    await userEvent.click(screen.getByText(/Why was the baseline retained\?/i));
    const body = document.body.textContent ?? "";
    expect(body).toContain("None passed the required gates");
    expect(body).toContain("pre-registered promotion gates");
    expect(body).toContain("without improving the overall decision objective");
  });

  it("introduces no stale 0.4186 anywhere on the Dashboard", async () => {
    await renderApp();
    expect(document.body.textContent).not.toContain("0.4186");
  });
});
