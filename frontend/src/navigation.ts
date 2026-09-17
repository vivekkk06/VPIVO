/**
 * Minimal in-app navigation. Deliberately not a router library: the app has a
 * fixed set of screens, so a `useState` union plus a hash sync is enough and
 * keeps the dependency list at react + react-dom.
 *
 * The hash carries the screen only. Cross-screen context (which process to
 * open, which session to preselect) is passed in memory, because it is a
 * transient UI intent rather than an addressable resource.
 *
 * Screens are grouped by investigation stage, in the order an evaluator is
 * meant to read them: overview, the Day 1-4 investigation, the decision, the
 * evidence behind it, and the working prototype. Existing hash ids are kept so
 * old links still open the same screen.
 */

export const NAV_GROUPS = ["Overview", "Investigation", "Decision", "Evidence", "Automation"] as const;
export type NavGroup = (typeof NAV_GROUPS)[number];

/** Which data a screen shows, for the status chips in the page header. */
export type ScreenScope = "A" | "B" | "AB" | "API";

export const SCREENS = [
  { id: "dashboard", label: "Executive Dashboard", group: "Overview", scope: "AB",
    mode: "Canonical evidence" },
  { id: "data-audit", label: "Day 1 · Data Audit", group: "Investigation", scope: "AB",
    mode: "Canonical evidence" },
  { id: "reconstruction", label: "Day 2 · Reconstruction", group: "Investigation", scope: "A",
    mode: "Canonical evidence" },
  { id: "process-mining", label: "Day 3 · Process Mining", group: "Investigation", scope: "B",
    mode: "Canonical evidence" },
  { id: "evidence-health", label: "Day 4 · Evidence Health", group: "Investigation", scope: "AB",
    mode: "Diagnostic evidence" },
  { id: "decision", label: "Automation Decision Center", group: "Decision", scope: "B",
    mode: "Canonical evidence" },
  { id: "opportunities", label: "Opportunities", group: "Decision", scope: "B",
    mode: "Canonical evidence" },
  { id: "modules", label: "Approach Comparison", group: "Decision", scope: "AB",
    mode: "Canonical + experimental" },
  { id: "replay", label: "Execution Replay", group: "Evidence", scope: "B",
    mode: "Canonical evidence" },
  { id: "processes", label: "Process Explorer", group: "Evidence", scope: "B",
    mode: "Canonical evidence" },
  { id: "automation", label: "HR Automation Demo", group: "Automation", scope: "API",
    mode: "Local prototype" },
] as const satisfies readonly {
  id: string; label: string; group: NavGroup; scope: ScreenScope; mode: string;
}[];

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

export function screenMeta(id: ScreenId) {
  const index = SCREENS.findIndex((s) => s.id === id);
  const screen = SCREENS[Math.max(0, index)];
  return { ...screen, number: String(index + 1).padStart(2, "0") };
}

export function screensIn(group: NavGroup) {
  return SCREENS
    .map((s, i) => ({ ...s, number: String(i + 1).padStart(2, "0") }))
    .filter((s) => s.group === group);
}
