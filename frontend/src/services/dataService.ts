/**
 * Loads the static Day-5 data bundle. Presentation-level only: fetch,
 * cache, and surface errors. No analytical value is computed here.
 *
 * The bundle is split deliberately: everything below is eager (~595 KB
 * total) except per-session execution files (~4.4 MB combined), which are
 * fetched only when a session is opened for replay and then cached.
 */

import type {
  DatasetAMetrics,
  Execution,
  ExecutionIndexRow,
  HrPayrollFile,
  InstrumentationFile,
  InstrumentationSensitivityFile,
  InvestigationFile,
  EngineeringUpgradeFile,
  Meta,
  ModuleComparisonFile,
  OpportunitiesFile,
  ProcessRow,
  SessionRow,
  VariantRow,
} from "../types";

export const DATA_ROOT = "/data";

export class DataError extends Error {
  readonly path: string;
  constructor(path: string, message: string) {
    super(message);
    this.name = "DataError";
    this.path = path;
  }
}

async function loadJson<T>(file: string): Promise<T> {
  const path = `${DATA_ROOT}/${file}`;
  let res: Response;
  try {
    res = await fetch(path);
  } catch (cause) {
    throw new DataError(
      path,
      `Could not reach ${path}. Run: python scripts/build_frontend_data.py --out frontend/public/data`,
    );
  }
  if (!res.ok) {
    throw new DataError(path, `${path} returned HTTP ${res.status}.`);
  }
  try {
    return (await res.json()) as T;
  } catch {
    throw new DataError(path, `${path} is not valid JSON.`);
  }
}

export interface EagerBundle {
  meta: Meta;
  sessions: SessionRow[];
  executionsIndex: ExecutionIndexRow[];
  processes: ProcessRow[];
  variants: VariantRow[];
  opportunities: OpportunitiesFile;
  instrumentation: InstrumentationFile;
  hrPayroll: HrPayrollFile;
  datasetAMetrics: DatasetAMetrics;
  instrumentationSensitivity: InstrumentationSensitivityFile;
  engineeringUpgrade: EngineeringUpgradeFile;
  /** Day 1-4 investigation views (data audit, reconstruction record, evidence health). */
  investigation: InvestigationFile;
  /** Day-6 Module 1 vs Module 2. Null when the experimental module has not been run,
   *  so the app still works against a bundle built without it. */
  moduleComparison: ModuleComparisonFile | null;
}

export async function loadEagerBundle(): Promise<EagerBundle> {
  const [
    meta,
    sessions,
    executionsIndex,
    processes,
    variants,
    opportunities,
    instrumentation,
    hrPayroll,
    datasetAMetrics,
    instrumentationSensitivity,
    engineeringUpgrade,
    investigation,
  ] = await Promise.all([
    loadJson<Meta>("meta.json"),
    loadJson<SessionRow[]>("sessions.json"),
    loadJson<ExecutionIndexRow[]>("executions-index.json"),
    loadJson<ProcessRow[]>("processes.json"),
    loadJson<VariantRow[]>("variants.json"),
    loadJson<OpportunitiesFile>("opportunities.json"),
    loadJson<InstrumentationFile>("instrumentation.json"),
    loadJson<HrPayrollFile>("hr-payroll.json"),
    loadJson<DatasetAMetrics>("dataset-a-metrics.json"),
    loadJson<InstrumentationSensitivityFile>("instrumentation-sensitivity.json"),
    loadJson<EngineeringUpgradeFile>("engineering-upgrade.json"),
    loadJson<InvestigationFile>("investigation.json"),
  ]);
  // Optional: a bundle built without the Day-6 experimental module simply omits it.
  const moduleComparison = await loadJson<ModuleComparisonFile>("module-comparison.json")
    .catch(() => null);
  return {
    moduleComparison,
    meta,
    sessions,
    executionsIndex,
    processes,
    variants,
    opportunities,
    instrumentation,
    hrPayroll,
    datasetAMetrics,
    instrumentationSensitivity,
    engineeringUpgrade,
    investigation,
  };
}

const sessionCache = new Map<string, Execution[]>();

/** Lazy: fetched on session selection, then served from memory. */
export async function loadSessionExecutions(sessionId: string): Promise<Execution[]> {
  const cached = sessionCache.get(sessionId);
  if (cached) return cached;
  const rows = await loadJson<Execution[]>(`executions/${sessionId}.json`);
  sessionCache.set(sessionId, rows);
  return rows;
}

export function isSessionCached(sessionId: string): boolean {
  return sessionCache.has(sessionId);
}

/** Test seam only. */
export function __clearSessionCache(): void {
  sessionCache.clear();
}
