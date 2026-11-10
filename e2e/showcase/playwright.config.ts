import { defineConfig } from "@playwright/test";

import base from "../playwright.config";

/**
 * Showcase walkthrough only. Needs the API running on the demonstration database
 * (backend/scripts/run_demo.py api) and the web dev server. Not part of the regular E2E suite.
 */
export default defineConfig({
  ...base,
  testDir: ".",
  testIgnore: [],
  reporter: [["list"]],
  outputDir: "../results/artifacts-showcase",
});
