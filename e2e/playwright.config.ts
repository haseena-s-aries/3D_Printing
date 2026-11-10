import { defineConfig } from "@playwright/test";

/**
 * End-to-end tests against locally running servers:
 *   API  http://127.0.0.1:8000 (Django, PostgreSQL)   web  http://127.0.0.1:5173 (Vite, proxies /api)
 * Start them first (see docs/local-setup.md). Headless Chromium uses software WebGL (SwiftShader);
 * results say nothing about mobile-device or GPU performance.
 */
export default defineConfig({
  testDir: ".",
  testIgnore: ["showcase/**"], // demonstration walkthrough: run with showcase/playwright.config.ts on the demo database
  timeout: 180_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"], ["json", { outputFile: "results/e2e-results.json" }]],
  outputDir: "results/artifacts",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:5173",
    headless: true,
    viewport: { width: 1360, height: 860 },
    acceptDownloads: true,
    trace: "retain-on-failure",
    launchOptions: { args: ["--enable-unsafe-swiftshader", "--use-angle=swiftshader"] },
  },
});
