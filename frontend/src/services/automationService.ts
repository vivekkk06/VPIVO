/**
 * Client for the local HR automation API.
 *
 * The frontend deliberately holds NO automation state. MockHRApplication
 * and ReviewCheckpoint live server-side; this client only carries an
 * opaque checkpoint token between the two calls. Route validation, note
 * validation, and confirm-time button re-verification are performed by
 * the existing Python prototype and are never reimplemented here.
 */

import type {
  ApiSafeStop, AutomationResultPayload, CheckpointPayload, ExecutionStatusPayload,
  IntegrationMode, IntegrationModesPayload,
} from "../types";

export const API_ROOT = "/api";

export type ApiOutcome<T> =
  | { kind: "ok"; data: T }
  | { kind: "safe_stop"; data: ApiSafeStop }
  | { kind: "validation_error"; message: string }
  | { kind: "api_error"; message: string };

async function post<T>(path: string, body: unknown): Promise<ApiOutcome<T>> {
  let res: Response;
  try {
    res = await fetch(`${API_ROOT}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    return {
      kind: "api_error",
      message:
        "Automation API is not running. Start it with: python scripts/serve_hr_demo_api.py",
    };
  }

  let payload: unknown;
  try {
    payload = await res.json();
  } catch {
    return { kind: "api_error", message: `API returned a non-JSON response (HTTP ${res.status}).` };
  }

  if (res.ok) return { kind: "ok", data: payload as T };

  const p = payload as Partial<ApiSafeStop> & { message?: string };
  // 422 = the prototype refused on its own safety rules. That is a
  // meaningful outcome, not a generic failure, so it is surfaced as such.
  if (res.status === 422 && p.error_type) {
    return { kind: "safe_stop", data: payload as ApiSafeStop };
  }
  if (res.status === 400) {
    return { kind: "validation_error", message: p.message ?? "Invalid request." };
  }
  return { kind: "api_error", message: p.message ?? `API error (HTTP ${res.status}).` };
}

/** Options for the Day-5 integration boundary. All optional: omitting them keeps
 *  the original behaviour (the in-memory mock, no injected failure). */
export interface PrepareOptions {
  integrationMode?: IntegrationMode;
  /** Deterministic, never random -- a demo that fails randomly cannot be re-run. */
  failureMode?: string;
  /** Model "the service applied the change and the response was lost". */
  loseResponse?: boolean;
}

export function prepare(route: string, noteText: string, options: PrepareOptions = {}) {
  return post<CheckpointPayload>("/prepare", {
    route,
    note_text: noteText,
    ...(options.integrationMode ? { integration_mode: options.integrationMode } : {}),
    ...(options.failureMode ? { failure_mode: options.failureMode } : {}),
    ...(options.loseResponse ? { lose_response: true } : {}),
  });
}

/** Note that a 202 is `res.ok`, so an UNKNOWN outcome arrives as `kind: "ok"` with
 *  `status: "UNKNOWN"`. That is deliberate: it is not an error, it is an outcome the
 *  caller must resolve by asking, never by retrying. */
export function confirm(checkpointToken: string) {
  return post<AutomationResultPayload>("/confirm", { checkpoint_token: checkpointToken });
}

/** The answer to a lost confirmation response: ask what actually happened. This
 *  never re-submits the mutation. */
export async function fetchExecutionStatus(
  executionId: string,
): Promise<ApiOutcome<ExecutionStatusPayload>> {
  let res: Response;
  try {
    res = await fetch(`${API_ROOT}/executions/${encodeURIComponent(executionId)}/status`);
  } catch {
    return {
      kind: "api_error",
      message:
        "Automation API is not running. Start it with: python scripts/serve_hr_demo_api.py",
    };
  }
  let payload: unknown;
  try {
    payload = await res.json();
  } catch {
    return { kind: "api_error", message: `API returned a non-JSON response (HTTP ${res.status}).` };
  }
  if (res.ok) return { kind: "ok", data: payload as ExecutionStatusPayload };
  const p = payload as { message?: string };
  return { kind: "api_error", message: p.message ?? `API error (HTTP ${res.status}).` };
}

export async function fetchRoutes(): Promise<string[]> {
  try {
    const res = await fetch(`${API_ROOT}/routes`);
    if (!res.ok) return [];
    const data = (await res.json()) as { routes?: string[] };
    return data.routes ?? [];
  } catch {
    return [];
  }
}

/** Returns null when the API is unreachable, so the screen can fall back to the
 *  mock-only view rather than rendering an empty selector. */
export async function fetchIntegrationModes(): Promise<IntegrationModesPayload | null> {
  try {
    const res = await fetch(`${API_ROOT}/integration-modes`);
    if (!res.ok) return null;
    const data = (await res.json()) as Partial<IntegrationModesPayload>;
    // Shape-checked rather than trusted: an API that does not advertise modes
    // must leave the selector hidden, not render an empty or malformed one.
    return Array.isArray(data?.modes) && data.modes.length
      ? (data as IntegrationModesPayload)
      : null;
  } catch {
    return null;
  }
}
