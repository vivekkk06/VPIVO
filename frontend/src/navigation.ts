/**
 * Minimal in-app navigation. Deliberately not a router library: the app has
 * five fixed screens, so a `useState` union plus a hash sync is enough and
 * keeps the dependency list at react + react-dom.
 *
 * The hash carries the screen only. Cross-screen context (which process to
 * open, which session to preselect) is passed in memory, because it is a
 * transient UI intent rather than an addressable resource.
 */

export const SCREENS = [
  { id: "dashboard", label: "Dashboard" },
  { id: "decision", label: "Automation Decision Center" },
  { id: "replay", label: "Execution Step Replay" },
  { id: "processes", label: "Process Explorer" },
  { id: "opportunities", label: "Opportunities" },
  { id: "automation", label: "HR Automation Demo" },
] as const;

export type ScreenId = (typeof SCREENS)[number]["id"];

export interface NavParams {
  /** Preselect a process on Process Explorer. */
  processId?: string;
  /** Preselect a session on Execution Step Replay. */
  sessionId?: string;
  /** Start Execution Step Replay filtered to degraded-instrumentation sessions. */
  degradedOnly?: boolean;
  /** Preselect a specific execution on Execution Step Replay. */
  executionId?: string;
}

export interface NavState {
  screen: ScreenId;
  params: NavParams;
  /** Bumped on every navigate so pages can re-apply params deterministically. */
  nonce: number;
}

export type Navigate = (screen: ScreenId, params?: NavParams) => void;

const IDS = SCREENS.map((s) => s.id) as readonly string[];

export function screenFromHash(hash: string): ScreenId {
  const candidate = hash.replace(/^#/, "");
  return (IDS.includes(candidate) ? candidate : "dashboard") as ScreenId;
}

export function labelFor(id: ScreenId): string {
  return SCREENS.find((s) => s.id === id)?.label ?? id;
}
