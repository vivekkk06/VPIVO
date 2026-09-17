/**
 * The Day-5 integration boundary as the operator sees it.
 *
 * `screens.test.tsx` covers the original prepare → review → confirm flow and must keep
 * passing unchanged. This file covers what the integration upgrade added to the HR
 * Automation Demo: execution identity, execution status, the integration-mode
 * selector, the deterministic failure demo, and the lost-response path.
 *
 * The property that matters most here is the last one. When a confirmation's outcome
 * is unknown, the UI must **not** offer a retry — it must offer a status lookup. A
 * test below counts the POSTs to prove no second confirmation is ever sent.
 */

import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App";
import { __clearSessionCache } from "../services/dataService";
import { installFetchStub } from "./helpers";

const EXEC_ID = "exec_a1b2c3d4e5f60718";

const ROUTES = { status: 200, payload: { routes: ["#/payroll-items", "#/onboarding"] } };

const MODES = {
  status: 200,
  payload: {
    modes: [
      { id: "mock", label: "LOCAL MOCK — deterministic in-memory target" },
      { id: "browser", label: "LOCAL BROWSER — Playwright against the local HR prototype page" },
      { id: "api_simulator", label: "LOCAL API SIMULATOR — simulated external REST service, in-process" },
    ],
    default: "mock",
    failure_modes: ["SUCCESS", "TIMEOUT", "CONFLICT", "SERVER_ERROR"],
    note: "Every target is local. No real HR system is contacted by any of these modes.",
  },
};

const ACTION_LOG = [
  { step: "route_check", detail: "'#/payroll-items' is an evidenced route", timestamp: "t" },
  { step: "note_check", detail: "note text is non-empty", timestamp: "t" },
  { step: "navigate", detail: "navigated to '#/payroll-items'", timestamp: "t" },
  { step: "find_note_field", detail: "found 'pi-note'", timestamp: "t" },
  { step: "insert_note", detail: "inserted note into 'pi-note'", timestamp: "t" },
  { step: "find_confirm_button", detail: "found 'btn-pi-ok'", timestamp: "t" },
  { step: "checkpoint", detail: "prepared -- awaiting human review", timestamp: "t" },
];

const CHECKPOINT = {
  checkpoint_token: "tok",
  execution_id: EXEC_ID,
  status: "AWAITING_CONFIRMATION",
  integration_mode: "api_simulator",
  integration_mode_label: "LOCAL API SIMULATOR — simulated external REST service, in-process",
  route: "#/payroll-items",
  note_field_id: "pi-note",
  note_text: "Reviewed.",
  confirm_button_id: "btn-pi-ok",
  confirmed: false,
  action_log: ACTION_LOG,
};

const CONFIRM_UNKNOWN = {
  status: 202,
  payload: {
    execution_id: EXEC_ID,
    status: "UNKNOWN",
    integration_mode: "api_simulator",
    route: "#/payroll-items",
    confirmed: false,
    error_type: "CONFIRMATION_UNKNOWN",
    status_url: `/api/executions/${EXEC_ID}/status`,
    message:
      "the confirmation outcome is unknown -- query the execution status endpoint; " +
      "the confirmation is never retried automatically",
    action_log: ACTION_LOG,
  },
};

const CONFIRM_OK = {
  status: 200,
  payload: {
    execution_id: EXEC_ID,
    status: "CONFIRMED",
    integration_mode: "mock",
    route: "#/payroll-items",
    confirmed: true,
    action_log: [...ACTION_LOG,
      { step: "confirm", detail: "human-approved: clicked 'btn-pi-ok'", timestamp: "t" }],
  },
};

function statusPayload(over: Record<string, unknown> = {}) {
  return {
    status: 200,
    payload: {
      execution_id: EXEC_ID,
      request_id: "req_1",
      actor: "u_local_dev",
      process: "HR / Payroll System",
      route: "#/payroll-items",
      integration_mode: "api_simulator",
      status: "CONFIRMED",
      note_length: 9,
      idempotency_key: "idem_1",
      error_code: null,
      created_at: "t", updated_at: "t", confirmed_at: "t",
      history: [],
      resolved_from_unknown: true,
      terminal: true,
      ...over,
    },
  };
}

type Reply = { status: number; payload: unknown };

function apiHandler(over: {
  modes?: Reply | null; prepare?: Reply; confirm?: () => Reply; status?: () => Reply;
} = {}) {
  return (path: string): Reply => {
    if (path.endsWith("/routes")) return ROUTES;
    if (path.endsWith("/integration-modes")) {
      return over.modes === null ? { status: 404, payload: {} } : (over.modes ?? MODES);
    }
    if (path.includes("/executions/")) return over.status ? over.status() : statusPayload();
    if (path.endsWith("/prepare")) return over.prepare ?? { status: 200, payload: CHECKPOINT };
    if (path.endsWith("/confirm")) return over.confirm ? over.confirm() : CONFIRM_OK;
    return { status: 404, payload: {} };
  };
}

async function openDemo(api = apiHandler()) {
  window.location.hash = "";
  __clearSessionCache();
  const stub = installFetchStub({ api });
  render(<App />);
  await waitFor(() =>
    expect(screen.getByRole("heading", { name: "Executive Dashboard" })).toBeInTheDocument());
  const nav = screen.getByRole("navigation", { name: "Main" });
  await userEvent.click(within(nav).getByRole("button", { name: /HR Automation Demo/ }));
  await screen.findByRole("heading", { name: "HR / Payroll Automation Demo" });
  return stub;
}

function posts(stub: ReturnType<typeof installFetchStub>, suffix: string) {
  return stub.mock.calls.filter(
    (c) => typeof c[0] === "string" && (c[0] as string).endsWith(suffix)
      && (c[1] as RequestInit | undefined)?.method === "POST");
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.location.hash = "";
});

// ===================== INTEGRATION MODE SELECTOR =====================

describe("integration mode selector", () => {
  it("offers the three local targets the API advertises", async () => {
    await openDemo();
    const select = await screen.findByLabelText("Integration mode");
    const options = Array.from(select.querySelectorAll("option")).map((o) => o.value);
    expect(options).toEqual(["mock", "browser", "api_simulator"]);
  });

  it("labels every target LOCAL, so the UI cannot imply a real HR system", async () => {
    await openDemo();
    const select = await screen.findByLabelText("Integration mode");
    for (const option of Array.from(select.querySelectorAll("option"))) {
      expect(option.textContent).toMatch(/^LOCAL /);
    }
  });

  it("defaults to the mock target", async () => {
    await openDemo();
    expect(await screen.findByLabelText("Integration mode")).toHaveValue("mock");
  });

  it("states that no real HR system is contacted", async () => {
    await openDemo();
    await screen.findByLabelText("Integration mode");
    expect(document.body.textContent).toContain("No real HR system is contacted");
  });

  it("hides the selector when the API advertises no modes", async () => {
    await openDemo(apiHandler({ modes: null }));
    expect(screen.queryByLabelText("Integration mode")).not.toBeInTheDocument();
  });

  it("offers injected failures only for the API simulator", async () => {
    await openDemo();
    expect(screen.queryByLabelText("Failure mode")).not.toBeInTheDocument();
    await userEvent.selectOptions(
      await screen.findByLabelText("Integration mode"), "api_simulator");
    expect(await screen.findByLabelText("Failure mode")).toBeInTheDocument();
  });

  it("says failures are selected rather than random, so a demo is reproducible", async () => {
    await openDemo();
    await screen.findByLabelText("Integration mode");
    expect(document.body.textContent).toContain("selected, never random");
  });

  it("sends the chosen target to the API", async () => {
    const stub = await openDemo();
    await userEvent.selectOptions(
      await screen.findByLabelText("Integration mode"), "api_simulator");
    await userEvent.click(screen.getByRole("button", { name: "Prepare" }));
    await screen.findByText(/Nothing has been confirmed yet/i);

    const body = JSON.parse((posts(stub, "/prepare")[0][1] as RequestInit).body as string);
    expect(body.integration_mode).toBe("api_simulator");
  });
});

// ===================== EXECUTION IDENTITY AND STATUS =====================

describe("execution identity", () => {
  it("shows no execution panel before anything has been prepared", async () => {
    await openDemo();
    expect(screen.queryByRole("region", { name: "Execution" })).not.toBeInTheDocument();
  });

  it("displays the server-issued execution ID after prepare", async () => {
    await openDemo();
    await userEvent.click(screen.getByRole("button", { name: "Prepare" }));
    const panel = await screen.findByRole("region", { name: "Execution" });
    expect(within(panel).getByText(EXEC_ID)).toBeInTheDocument();
  });

  it("displays the execution status as the server's own state name", async () => {
    await openDemo();
    await userEvent.click(screen.getByRole("button", { name: "Prepare" }));
    const panel = await screen.findByRole("region", { name: "Execution" });
    expect(within(panel).getByText("AWAITING CONFIRMATION")).toBeInTheDocument();
  });

  it("displays the integration mode the execution actually ran against", async () => {
    await openDemo();
    await userEvent.click(screen.getByRole("button", { name: "Prepare" }));
    const panel = await screen.findByRole("region", { name: "Execution" });
    expect(within(panel).getByText(/LOCAL API SIMULATOR/)).toBeInTheDocument();
  });

  it("shows CONFIRMED once the confirmation succeeds", async () => {
    await openDemo();
    await userEvent.click(screen.getByRole("button", { name: "Prepare" }));
    await userEvent.click(await screen.findByRole("button", { name: /Approve and confirm/ }));
    const panel = await screen.findByRole("region", { name: "Execution" });
    expect(within(panel).getByText("CONFIRMED")).toBeInTheDocument();
  });
});

// ===================== THE LOST-RESPONSE PATH =====================

describe("an unknown confirmation outcome", () => {
  const unknownApi = () => apiHandler({ confirm: () => CONFIRM_UNKNOWN });

  async function confirmIntoUnknown(api = unknownApi()) {
    const stub = await openDemo(api);
    await userEvent.click(screen.getByRole("button", { name: "Prepare" }));
    await userEvent.click(await screen.findByRole("button", { name: /Approve and confirm/ }));
    return stub;
  }

  it("renders the required wording rather than claiming success or failure", async () => {
    await confirmIntoUnknown();
    expect(
      await screen.findByText(/Confirmation status unknown — check execution status\./),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Automation completed/i)).not.toBeInTheDocument();
  });

  it("shows the execution status as UNKNOWN", async () => {
    await confirmIntoUnknown();
    const panel = await screen.findByRole("region", { name: "Execution" });
    expect(within(panel).getByText("UNKNOWN")).toBeInTheDocument();
  });

  it("states that the confirmation is not retried automatically", async () => {
    await confirmIntoUnknown();
    await screen.findByText(/Confirmation status unknown/);
    expect(document.body.textContent).toContain("not");
    expect(document.body.textContent).toContain("retried automatically");
  });

  it("offers a status lookup instead of a retry", async () => {
    await confirmIntoUnknown();
    expect(await screen.findByRole("button", { name: "Check status" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Approve and confirm/ })).not.toBeInTheDocument();
  });

  it("resolves the outcome by querying the execution status endpoint", async () => {
    const stub = await confirmIntoUnknown();
    await userEvent.click(await screen.findByRole("button", { name: "Check status" }));

    await waitFor(() =>
      expect(stub.mock.calls.some(
        (c) => typeof c[0] === "string" && (c[0] as string).includes(`/executions/${EXEC_ID}/status`),
      )).toBe(true));
    expect(await screen.findByText(/without re-submitting the confirmation/)).toBeInTheDocument();
  });

  it("never sends a second confirmation while resolving", async () => {
    const stub = await confirmIntoUnknown();
    await userEvent.click(await screen.findByRole("button", { name: "Check status" }));
    await screen.findByText(/without re-submitting the confirmation/);
    expect(posts(stub, "/confirm")).toHaveLength(1);
  });

  it("shows the resolved status once the lookup returns", async () => {
    await confirmIntoUnknown();
    await userEvent.click(await screen.findByRole("button", { name: "Check status" }));
    const panel = await screen.findByRole("region", { name: "Execution" });
    await waitFor(() => expect(within(panel).getByText("CONFIRMED")).toBeInTheDocument());
  });

  it("can resolve to FAILED as readily as to CONFIRMED", async () => {
    await confirmIntoUnknown(apiHandler({
      confirm: () => CONFIRM_UNKNOWN,
      status: () => statusPayload({ status: "FAILED", error_code: "INTEGRATION_UNAVAILABLE",
                                    confirmed_at: null }),
    }));
    await userEvent.click(await screen.findByRole("button", { name: "Check status" }));
    const panel = await screen.findByRole("region", { name: "Execution" });
    await waitFor(() => expect(within(panel).getByText("FAILED")).toBeInTheDocument());
  });

  it("reports the stored note length, never the note content", async () => {
    await confirmIntoUnknown();
    await userEvent.click(await screen.findByRole("button", { name: "Check status" }));
    expect(await screen.findByText(/stored the note length \(9 characters\)/)).toBeInTheDocument();
    expect(document.body.textContent).toContain("never");
  });

  it("stages the lost-response demo deterministically", async () => {
    await openDemo();
    await userEvent.click(await screen.findByRole("button", { name: /Stage lost-response demo/ }));
    expect(screen.getByLabelText("Integration mode")).toHaveValue("api_simulator");
    expect(screen.getByLabelText("Failure mode")).toHaveValue("TIMEOUT");
  });
});

// ===================== STATUS LOOKUP OUTSIDE THE UNKNOWN PATH =====================

describe("execution status lookup", () => {
  it("is available for a completed execution too", async () => {
    await openDemo();
    await userEvent.click(screen.getByRole("button", { name: "Prepare" }));
    await userEvent.click(await screen.findByRole("button", { name: /Approve and confirm/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Check status" }));
    expect(await screen.findByText(/Server-reported status:/)).toBeInTheDocument();
  });

  it("says a lookup never re-submits the confirmation", async () => {
    await openDemo();
    await userEvent.click(screen.getByRole("button", { name: "Prepare" }));
    expect(document.body.textContent).toContain("never re-submits the confirmation");
  });
});

// ===================== THE HUMAN CHECKPOINT IS UNCHANGED =====================

describe("the human review checkpoint survives the upgrade", () => {
  it("still refuses to expose a confirm control before prepare", async () => {
    await openDemo();
    expect(screen.queryByRole("button", { name: /Approve and confirm/ })).not.toBeInTheDocument();
    expect(screen.getByText(/Confirmation is impossible until Prepare succeeds/i))
      .toBeInTheDocument();
  });

  it("still holds the checkpoint before anything is confirmed", async () => {
    await openDemo();
    await userEvent.click(screen.getByRole("button", { name: "Prepare" }));
    expect(await screen.findByText(/Nothing has been confirmed yet/i)).toBeInTheDocument();
  });

  it("keeps the LOCAL VALIDATED boundary in the page header", async () => {
    await openDemo();
    const heading = screen.getByRole("heading", { name: "HR / Payroll Automation Demo" });
    const header = heading.closest("header") as HTMLElement;
    expect(header.querySelector(".page-context")?.textContent).toMatch(/LOCAL VALIDATED/);
    expect(header.textContent).not.toContain("production-ready");
  });

  it("never claims a real HR integration anywhere on the screen", async () => {
    await openDemo();
    await userEvent.click(screen.getByRole("button", { name: "Prepare" }));
    const text = document.body.textContent ?? "";
    expect(text).not.toContain("production-ready");
    expect(text).not.toContain("fully automated");
    expect(text).toContain("not a real HR system");
  });
});

// ===================== A CONFIRMATION RESPONSE THAT NEVER ARRIVES =====================
// The production edge case: the confirmation may have been applied, and the client
// received nothing at all. That is not a failure and must not be shown as one — and
// the execution id issued at prepare time must survive so the outcome can be asked for.

describe("a confirmation response that never arrives", () => {
  const lostApi = (status?: () => Reply) => apiHandler({
    confirm: () => { throw new TypeError("Failed to fetch"); },
    ...(status ? { status } : {}),
  });

  async function confirmWithLostResponse(api = lostApi()) {
    const stub = await openDemo(api);
    await userEvent.click(screen.getByRole("button", { name: "Prepare" }));
    await userEvent.click(await screen.findByRole("button", { name: /Approve and confirm/ }));
    await screen.findByText(/Confirmation status unknown — check execution status\./);
    return stub;
  }

  it("is treated as an unknown outcome, not as an API failure", async () => {
    await confirmWithLostResponse();
    expect(screen.getByText(/No response was received for the confirmation/)).toBeInTheDocument();
    expect(screen.queryByText(/^API error/)).not.toBeInTheDocument();
  });

  it("keeps the execution id issued at prepare time", async () => {
    await confirmWithLostResponse();
    const panel = screen.getByRole("region", { name: "Execution" });
    expect(within(panel).getByText(EXEC_ID)).toBeInTheDocument();
    expect(within(panel).getByText("UNKNOWN")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check status" })).toBeInTheDocument();
  });

  it("offers no way to re-send the confirmation", async () => {
    const stub = await confirmWithLostResponse();
    expect(screen.queryByRole("button", { name: /Approve and confirm/ })).not.toBeInTheDocument();
    expect(posts(stub, "/confirm")).toHaveLength(1);
  });

  it("resolves by asking the server, still without re-sending", async () => {
    const stub = await confirmWithLostResponse();
    await userEvent.click(screen.getByRole("button", { name: "Check status" }));
    expect(await screen.findByText(/without re-submitting the confirmation/)).toBeInTheDocument();
    expect(posts(stub, "/confirm")).toHaveLength(1);
  });

  it("says nothing was applied when the confirmation never reached the server", async () => {
    await confirmWithLostResponse(lostApi(() => statusPayload({
      status: "AWAITING_CONFIRMATION", resolved_from_unknown: false,
      terminal: false, confirmed_at: null,
    })));
    await userEvent.click(screen.getByRole("button", { name: "Check status" }));
    expect(await screen.findByText(/never reached the server, so nothing was applied/))
      .toBeInTheDocument();
  });

  it("says plainly when the target has no status source to ask", async () => {
    await confirmWithLostResponse(lostApi(() => statusPayload({
      status: "UNKNOWN", resolved_from_unknown: false, terminal: false, confirmed_at: null,
    })));
    await userEvent.click(screen.getByRole("button", { name: "Check status" }));
    expect(await screen.findByText(/exposes no status source/)).toBeInTheDocument();
  });

  it("falls back to an API error only when there is no execution id to keep", async () => {
    const legacyCheckpoint = { ...CHECKPOINT, execution_id: undefined, status: undefined };
    await openDemo(apiHandler({
      prepare: { status: 200, payload: legacyCheckpoint },
      confirm: () => { throw new TypeError("Failed to fetch"); },
    }));
    await userEvent.click(screen.getByRole("button", { name: "Prepare" }));
    await userEvent.click(await screen.findByRole("button", { name: /Approve and confirm/ }));
    expect(await screen.findByText(/API error/)).toBeInTheDocument();
  });
});

// ===================== LOCAL HTTP INTEGRATION (final extension) =====================
// Real HTTP to the separate local HR API simulator. The screen must name it for what it
// is -- a local HTTP integration -- and must never dress it up as a production target.

const HTTP_LABEL = "LOCAL HTTP INTEGRATION — real HTTP to the local HR API server (SQLite)";

const MODES_WITH_HTTP = {
  status: 200,
  payload: {
    ...MODES.payload,
    modes: [...MODES.payload.modes, { id: "http", label: HTTP_LABEL }],
    http_failure_modes: ["SUCCESS", "CONFIRM_RESPONSE_LOST", "TIMEOUT", "HTTP_500",
      "HTTP_500_AFTER_COMMIT", "MALFORMED_JSON", "CONNECTION_REFUSED"],
  },
};

const HTTP_CHECKPOINT = {
  ...CHECKPOINT, integration_mode: "http", integration_mode_label: HTTP_LABEL,
};

const HTTP_UNKNOWN = {
  status: 202,
  payload: { ...CONFIRM_UNKNOWN.payload, integration_mode: "http" },
};

function httpTarget(over: Record<string, unknown> = {}) {
  return {
    source: "local HR API (HTTP)", found: true, confirmation_state: "CONFIRMED",
    state: "COMMITTED", in_progress: false, commit_count: 1, audit_ref: "hraud_1",
    last_error_type: null, ...over,
  };
}

function httpApi(over: { confirm?: () => Reply; status?: () => Reply } = {}) {
  return apiHandler({
    modes: MODES_WITH_HTTP,
    prepare: { status: 200, payload: HTTP_CHECKPOINT },
    confirm: over.confirm ?? (() => HTTP_UNKNOWN),
    status: over.status ?? (() => statusPayload({ integration_mode: "http",
                                                   target: httpTarget() })),
  });
}

async function selectHttp() {
  await userEvent.selectOptions(await screen.findByLabelText("Integration mode"), "http");
}

describe("local HTTP integration", () => {
  it("is offered as a LOCAL target, never as production", async () => {
    await openDemo(httpApi());
    const select = await screen.findByLabelText("Integration mode");
    const option = Array.from(select.querySelectorAll("option")).find((o) => o.value === "http")!;
    expect(option.textContent).toBe(HTTP_LABEL);
    expect(option.textContent).toMatch(/^LOCAL /);
    expect(option.textContent?.toLowerCase()).not.toContain("production");
  });

  it("describes itself as a local HTTP integration and shows no production badge", async () => {
    await openDemo(httpApi());
    await selectHttp();
    const note = screen.getByRole("note", { name: "Local HTTP integration" });
    expect(note.textContent).toContain("separate local HR API server");
    expect(note.textContent).toContain("not a real HR system");
    for (const badge of Array.from(document.querySelectorAll(".badge"))) {
      expect(badge.textContent?.toLowerCase()).not.toContain("production");
    }
    expect(document.body.textContent).not.toContain("production-ready");
  });

  it("offers the HTTP failure set, not the simulator's", async () => {
    await openDemo(httpApi());
    await selectHttp();
    const failure = await screen.findByLabelText("Failure mode");
    const options = Array.from(failure.querySelectorAll("option")).map((o) => o.value);
    expect(options).toEqual(MODES_WITH_HTTP.payload.http_failure_modes);
    expect(screen.queryByText(/Service applies the change, then the response is lost/))
      .not.toBeInTheDocument();
  });

  it("resets the selected failure when the target changes", async () => {
    await openDemo(httpApi());
    await selectHttp();
    await userEvent.selectOptions(await screen.findByLabelText("Failure mode"), "HTTP_500");
    await userEvent.selectOptions(screen.getByLabelText("Integration mode"), "api_simulator");
    expect(screen.getByLabelText("Failure mode")).toHaveValue("SUCCESS");
  });

  it("sends the HTTP target and its selected failure to the API", async () => {
    const stub = await openDemo(httpApi());
    await selectHttp();
    await userEvent.selectOptions(await screen.findByLabelText("Failure mode"), "TIMEOUT");
    await userEvent.click(screen.getByRole("button", { name: "Prepare" }));
    await screen.findByText(/Nothing has been confirmed yet/i);
    const body = JSON.parse((posts(stub, "/prepare")[0][1] as RequestInit).body as string);
    expect(body).toMatchObject({ integration_mode: "http", failure_mode: "TIMEOUT" });
    expect(body.lose_response).toBeUndefined();
  });

  it("stages the HTTP lost-response demo deterministically", async () => {
    await openDemo(httpApi());
    await userEvent.click(await screen.findByRole("button", { name: /Stage HTTP lost-response demo/ }));
    expect(screen.getByLabelText("Integration mode")).toHaveValue("http");
    expect(screen.getByLabelText("Failure mode")).toHaveValue("CONFIRM_RESPONSE_LOST");
  });

  it("hides the HTTP demo when the API does not advertise the target", async () => {
    await openDemo();
    await screen.findByLabelText("Integration mode");
    expect(screen.queryByRole("button", { name: /Stage HTTP lost-response demo/ }))
      .not.toBeInTheDocument();
  });

  it("shows execution ID, state and confirmation state after prepare", async () => {
    await openDemo(httpApi());
    await selectHttp();
    await userEvent.click(screen.getByRole("button", { name: "Prepare" }));
    const panel = await screen.findByRole("region", { name: "Execution" });
    expect(within(panel).getByText(EXEC_ID)).toBeInTheDocument();
    expect(within(panel).getByText("AWAITING CONFIRMATION")).toBeInTheDocument();
    expect(within(panel).getByText("not submitted")).toBeInTheDocument();
    expect(within(panel).getByText(HTTP_LABEL)).toBeInTheDocument();
  });
});

describe("local HTTP integration: a lost confirmation response", () => {
  async function loseIt(api = httpApi()) {
    const stub = await openDemo(api);
    await selectHttp();
    await userEvent.click(screen.getByRole("button", { name: "Prepare" }));
    await userEvent.click(await screen.findByRole("button", { name: /Approve and confirm/ }));
    await screen.findByText(/Confirmation status unknown — check execution status\./);
    return stub;
  }

  it("shows UNKNOWN and keeps the execution ID visible", async () => {
    await loseIt();
    const panel = screen.getByRole("region", { name: "Execution" });
    expect(within(panel).getByText("UNKNOWN")).toBeInTheDocument();
    expect(within(panel).getByText(EXEC_ID)).toBeInTheDocument();
    expect(within(panel).getByText("unknown — check status")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check status" })).toBeInTheDocument();
  });

  it("goes UNKNOWN → Check status → CONFIRMED from the HR system's own record", async () => {
    const stub = await loseIt();
    await userEvent.click(screen.getByRole("button", { name: "Check status" }));
    const panel = screen.getByRole("region", { name: "Execution" });
    await waitFor(() => expect(within(panel).getByText("CONFIRMED")).toBeInTheDocument());
    expect(within(panel).getByText("CONFIRMED (HR system)")).toBeInTheDocument();
    expect(within(panel).getByText(/commits applied/)).toBeInTheDocument();
    expect(screen.getByText(/without re-submitting the confirmation/)).toBeInTheDocument();
    expect(stub.mock.calls.some((c) => String(c[0]).includes(`/executions/${EXEC_ID}/status`)))
      .toBe(true);
  });

  it("never sends a second confirmation, however often the status is checked", async () => {
    const stub = await loseIt();
    for (let i = 0; i < 3; i++) {
      await userEvent.click(screen.getByRole("button", { name: "Check status" }));
      await screen.findByText(/without re-submitting the confirmation/);
    }
    expect(posts(stub, "/confirm")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: /Approve and confirm/ })).not.toBeInTheDocument();
  });

  it("keeps UNKNOWN while the HR system reports the confirmation in progress", async () => {
    await loseIt(httpApi({
      status: () => statusPayload({
        integration_mode: "http", status: "UNKNOWN", resolved_from_unknown: false,
        terminal: false, confirmed_at: null,
        target: httpTarget({ confirmation_state: "IN_PROGRESS", in_progress: true,
                             state: "NOTE_RECEIVED", commit_count: 0 }),
      }),
    }));
    await userEvent.click(screen.getByRole("button", { name: "Check status" }));
    expect(await screen.findByText(/still in progress, so it cannot be settled yet/))
      .toBeInTheDocument();
    const panel = screen.getByRole("region", { name: "Execution" });
    expect(within(panel).getByText("IN PROGRESS (HR system)")).toBeInTheDocument();
    expect(within(panel).getByText("UNKNOWN")).toBeInTheDocument();
  });

  it("keeps UNKNOWN, and says why, when the status source cannot be reached", async () => {
    await loseIt(httpApi({
      status: () => statusPayload({
        integration_mode: "http", status: "UNKNOWN", resolved_from_unknown: false,
        terminal: false, confirmed_at: null,
        target: { source: "local HR API (HTTP)", lookup_error: "INTEGRATION_UNAVAILABLE" },
      }),
    }));
    await userEvent.click(screen.getByRole("button", { name: "Check status" }));
    expect(await screen.findByText(/status source could not be reached/)).toBeInTheDocument();
    expect(screen.getByText("INTEGRATION_UNAVAILABLE")).toBeInTheDocument();
    expect(screen.queryByText(/exposes no status source/)).not.toBeInTheDocument();
  });

  it("can settle to not applied when the HR system never committed", async () => {
    await loseIt(httpApi({
      status: () => statusPayload({
        integration_mode: "http", status: "FAILED", error_code: "INTEGRATION_TIMEOUT",
        confirmed_at: null,
        target: httpTarget({ confirmation_state: "PENDING", state: "NOTE_RECEIVED",
                             commit_count: 0, last_error_type: "TIMEOUT" }),
      }),
    }));
    await userEvent.click(screen.getByRole("button", { name: "Check status" }));
    const panel = screen.getByRole("region", { name: "Execution" });
    await waitFor(() => expect(within(panel).getByText("FAILED")).toBeInTheDocument());
    expect(within(panel).getByText("PENDING (HR system)")).toBeInTheDocument();
    expect(within(panel).getByText(/last refusal/)).toBeInTheDocument();
  });

  it("treats a response that never arrives the same way over HTTP", async () => {
    const stub = await loseIt(httpApi({ confirm: () => { throw new TypeError("Failed to fetch"); } }));
    expect(screen.getByText(/No response was received for the confirmation/)).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Execution" })).getByText(EXEC_ID))
      .toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Check status" }));
    await screen.findByText(/without re-submitting the confirmation/);
    expect(posts(stub, "/confirm")).toHaveLength(1);
  });
});

describe("local HTTP integration: the confirmed path", () => {
  it("shows CONFIRMED and the HR system's record after a status lookup", async () => {
    await openDemo(httpApi({
      confirm: () => ({ status: 200, payload: { ...CONFIRM_OK.payload, integration_mode: "http" } }),
    }));
    await selectHttp();
    await userEvent.click(screen.getByRole("button", { name: "Prepare" }));
    await userEvent.click(await screen.findByRole("button", { name: /Approve and confirm/ }));
    expect(await screen.findByText(/Automation completed/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Check status" }));
    const panel = screen.getByRole("region", { name: "Execution" });
    await waitFor(() =>
      expect(within(panel).getByText("CONFIRMED (HR system)")).toBeInTheDocument());
    expect(within(panel).getByText("COMMITTED")).toBeInTheDocument();
  });
});

describe("the safety panel after an unknown outcome", () => {
  function confirmRow() {
    const safety = screen.getByRole("region", { name: /Automation safety/i });
    return within(safety).getByText("Confirm-time re-verification").closest(".safety-row") as HTMLElement;
  }

  async function loseIt(status?: () => Reply) {
    await openDemo(httpApi(status ? { status } : {}));
    await selectHttp();
    await userEvent.click(screen.getByRole("button", { name: "Prepare" }));
    await userEvent.click(await screen.findByRole("button", { name: /Approve and confirm/ }));
    await screen.findByText(/Confirmation status unknown — check execution status\./);
  }

  it("says unknown rather than refused while the outcome is unknown", async () => {
    await loseIt();
    expect(within(confirmRow()).getByText("unknown")).toBeInTheDocument();
    expect(within(confirmRow()).queryByText("refused")).not.toBeInTheDocument();
    expect(confirmRow().textContent).toContain("never by a retry");
  });

  it("says enforced once a lookup shows the confirmation was applied", async () => {
    await loseIt();
    await userEvent.click(screen.getByRole("button", { name: "Check status" }));
    await waitFor(() => expect(within(confirmRow()).getByText("enforced")).toBeInTheDocument());
  });

  it("says not applied when the lookup settles the other way", async () => {
    await loseIt(() => statusPayload({
      integration_mode: "http", status: "FAILED", error_code: "INTEGRATION_SERVER_ERROR",
      confirmed_at: null, target: httpTarget({ confirmation_state: "PENDING", commit_count: 0 }),
    }));
    await userEvent.click(screen.getByRole("button", { name: "Check status" }));
    await waitFor(() => expect(within(confirmRow()).getByText("not applied")).toBeInTheDocument());
  });

  it("still says refused when the server really refused at confirm time", async () => {
    await openDemo(apiHandler({
      confirm: () => ({ status: 422, payload: {
        error_type: "CONFIRMATION_REJECTED", message: "page state changed",
        execution_id: EXEC_ID, status: "FAILED",
        action_log: [...ACTION_LOG, { step: "confirm", detail: "FAILED: page state changed", timestamp: "t" }],
      } }),
    }));
    await userEvent.click(screen.getByRole("button", { name: "Prepare" }));
    await userEvent.click(await screen.findByRole("button", { name: /Approve and confirm/ }));
    await screen.findByText(/Safe stop — CONFIRMATION_REJECTED/);
    expect(within(confirmRow()).getByText("refused")).toBeInTheDocument();
  });
});
