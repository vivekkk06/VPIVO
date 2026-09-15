/**
 * Test helpers.
 *
 * These tests run against the REAL generated bundle in public/data rather
 * than hand-written fixtures. That is deliberate: the point of the Day-5
 * bridge is that the UI shows exactly what the analytical pipeline
 * produced, and a fixture-based test could pass while the real bundle
 * carried superseded numbers.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { vi } from "vitest";

const DATA_DIR = join(process.cwd(), "public", "data");

export function readBundleFile<T>(relative: string): T {
  return JSON.parse(readFileSync(join(DATA_DIR, relative), "utf-8")) as T;
}

export type ApiHandler = (path: string, body: unknown) => { status: number; payload: unknown };

export interface FetchStubOptions {
  /** Paths (relative to /data) that should fail, to exercise error states. */
  missing?: string[];
  api?: ApiHandler;
}

/**
 * Serves /data/* from the real bundle on disk and routes /api/* to an
 * optional handler. Returns the spy so tests can assert on lazy loading.
 */
export function installFetchStub(options: FetchStubOptions = {}) {
  const missing = new Set(options.missing ?? []);

  const stub = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();

    if (url.startsWith("/api")) {
      if (!options.api) {
        throw new TypeError("fetch failed"); // API not running
      }
      const body = init?.body ? JSON.parse(init.body as string) : undefined;
      const { status, payload } = options.api(url, body);
      return new Response(JSON.stringify(payload), {
        status,
        headers: { "Content-Type": "application/json" },
      });
    }

    if (url.startsWith("/data/")) {
      const rel = url.slice("/data/".length);
      if (missing.has(rel)) {
        return new Response("not found", { status: 404 });
      }
      try {
        const text = readFileSync(join(DATA_DIR, rel), "utf-8");
        return new Response(text, {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      } catch {
        return new Response("not found", { status: 404 });
      }
    }

    throw new TypeError(`unexpected fetch: ${url}`);
  });

  vi.stubGlobal("fetch", stub);
  return stub;
}

export function dataRequests(stub: ReturnType<typeof installFetchStub>): string[] {
  return stub.mock.calls
    .map((c) => (typeof c[0] === "string" ? c[0] : String(c[0])))
    .filter((u) => u.startsWith("/data/"));
}
