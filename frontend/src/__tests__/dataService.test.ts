import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  __clearSessionCache,
  isSessionCached,
  loadEagerBundle,
  loadSessionExecutions,
} from "../services/dataService";
import { dataRequests, installFetchStub, readBundleFile } from "./helpers";
import type { ExecutionIndexRow } from "../types";

describe("dataService", () => {
  beforeEach(() => __clearSessionCache());
  afterEach(() => vi.unstubAllGlobals());

  it("loads the eager bundle", async () => {
    installFetchStub();
    const bundle = await loadEagerBundle();
    expect(bundle.sessions.length).toBeGreaterThan(0);
    expect(bundle.executionsIndex.length).toBe(645);
    expect(bundle.opportunities.ranking.length).toBe(21);
  });

  it("does NOT fetch any per-session execution file during the eager load", async () => {
    const stub = installFetchStub();
    await loadEagerBundle();
    const perSession = dataRequests(stub).filter((u) => u.includes("/data/executions/"));
    expect(perSession).toEqual([]);
  });

  it("fetches a per-session file only when that session is requested", async () => {
    const stub = installFetchStub();
    const index = readBundleFile<ExecutionIndexRow[]>("executions-index.json");
    const sessionId = index[0].session_id;

    expect(isSessionCached(sessionId)).toBe(false);
    const rows = await loadSessionExecutions(sessionId);

    expect(rows.length).toBeGreaterThan(0);
    expect(dataRequests(stub)).toContain(`/data/executions/${sessionId}.json`);
  });

  it("serves a second request for the same session from cache", async () => {
    const stub = installFetchStub();
    const index = readBundleFile<ExecutionIndexRow[]>("executions-index.json");
    const sessionId = index[0].session_id;

    await loadSessionExecutions(sessionId);
    const afterFirst = dataRequests(stub).length;
    await loadSessionExecutions(sessionId);

    expect(dataRequests(stub).length).toBe(afterFirst);
    expect(isSessionCached(sessionId)).toBe(true);
  });

  it("surfaces a DataError naming the file when a bundle file is missing", async () => {
    installFetchStub({ missing: ["opportunities.json"] });
    await expect(loadEagerBundle()).rejects.toThrow(/opportunities\.json/);
  });

  it("explains how to regenerate the bundle when the fetch itself fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("fetch failed");
      }),
    );
    await expect(loadEagerBundle()).rejects.toThrow(/build_frontend_data\.py/);
  });
});
