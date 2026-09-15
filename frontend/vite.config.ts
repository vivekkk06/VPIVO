import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

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
        target: "http://127.0.0.1:8000",
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
