/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the API is proxied, so the browser talks to one origin (no CORS needed).
const API = process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: { host: "127.0.0.1", port: 5173, strictPort: true, proxy: { "/api": { target: API, changeOrigin: false } } },
  preview: { host: "127.0.0.1", proxy: { "/api": { target: API, changeOrigin: false } } },
  build: { sourcemap: true, chunkSizeWarningLimit: 900 },
  test: { environment: "jsdom", globals: true, setupFiles: ["src/test/setup.ts"] },
});
