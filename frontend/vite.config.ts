import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Where the local automation API listens. The default is the documented port and
// is what `python scripts/serve_hr_demo_api.py` uses; VITE_API_TARGET overrides it
// when another process already holds that port (for example during browser QA).
const API_TARGET =
  (globalThis as { process?: { env?: Record<string, string | undefined> } })
    .process?.env?.VITE_API_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // The HR automation demo is the only stateful feature. It is proxied to
    // the local Python API so the browser never holds MockHRApplication or
    // ReviewCheckpoint state -- those stay server-side, where the existing
    // safety model (route validation, note validation, confirm-time
    // re-verification) is authoritative.
    proxy: {
      "/api": {
        target: API_TARGET,
        changeOrigin: true,
      },
    },
  },
  // The same proxy for `vite preview`, so the *built* bundle can be exercised
  // against the local API during browser QA rather than only the dev server.
  preview: {
    port: 4173,
    proxy: {
      "/api": {
        target: API_TARGET,
        changeOrigin: true,
      },
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/__tests__/setup.ts"],
    css: false,
  },
});
