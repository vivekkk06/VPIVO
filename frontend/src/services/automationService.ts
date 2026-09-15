/**
 * Client for the local HR automation API.
 *
 * The frontend deliberately holds NO automation state. MockHRApplication
 * and ReviewCheckpoint live server-side; this client only carries an
 * opaque checkpoint token between the two calls. Route validation, note
 * validation, and confirm-time button re-verification are performed by
 * the existing Python prototype and are never reimplemented here.
 */

import type { ApiSafeStop, AutomationResultPayload, CheckpointPayload } from "../types";

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

export function prepare(route: string, noteText: string) {
  return post<CheckpointPayload>("/prepare", { route, note_text: noteText });
}

export function confirm(checkpointToken: string) {
  return post<AutomationResultPayload>("/confirm", { checkpoint_token: checkpointToken });
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
