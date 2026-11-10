/**
 * Phase 1 end-to-end flow (web portal + API + PostgreSQL + local storage + CAD worker).
 * Requires: API and web dev servers running, demo data seeded with DEMO_PASSWORD.
 */
import { expect, test } from "@playwright/test";
import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { fillNewClient, openClient, PASSWORD, runWorker, SHOTS, signIn, signOut, STEP_FILE, uploadFile } from "./helpers";

const RUN = Date.now().toString(36);
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "passport-e2e-"));
const PDF_BYTES = Buffer.from(
  "%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj " +
    "3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n",
);
const PDF_FILE = path.join(tmp, `specification-${RUN}.pdf`);
const DWG_FILE = path.join(tmp, `drawing-${RUN}.dwg`);
const FAKE_STEP = path.join(tmp, `fake-${RUN}.stp`);
const TXT_FILE = path.join(tmp, `notes-${RUN}.txt`);
fs.writeFileSync(PDF_FILE, PDF_BYTES);
fs.writeFileSync(DWG_FILE, Buffer.concat([Buffer.from("AC1032"), Buffer.alloc(2042)])); // header-only synthetic DWG
fs.writeFileSync(FAKE_STEP, PDF_BYTES); // PDF content with .stp extension
fs.writeFileSync(TXT_FILE, "not an engineering file");

const state: { partNumber: string; passportUrl: string; passportNumber: string } = { partNumber: `E2E-${RUN}`, passportUrl: "", passportNumber: "" };

test.describe.serial("Phase 1 web portal", () => {
  test("operator engineer: spare part, passport draft, uploads, conversion, viewer, download", async ({ page }) => {
    await signIn(page, "engineer@operator.demo", PASSWORD, "demo-client");
    await page.screenshot({ path: path.join(SHOTS, "01-client-portal-dashboard.png"), fullPage: true });

    // Spare-part draft
    await page.getByRole("link", { name: "Digital inventory", exact: true }).click();
    await page.getByRole("button", { name: "New spare part" }).click();
    await page.getByLabel("Part number").fill(state.partNumber);
    await page.getByLabel("Name", { exact: true }).fill("Distance sleeve Ø45 (E2E)");
    // structured dimensions (CN-003): Ø × H in mm
    await page.getByLabel("Spare part master data").getByLabel("Shape").selectOption("cylinder");
    await page.getByLabel("Dimensions").fill("45");
    await page.getByLabel("Spare part master data").getByLabel("H", { exact: true }).fill("40.50");
    await page.getByRole("button", { name: "Create spare part" }).click();
    await expect(page.getByRole("heading", { name: new RegExp(state.partNumber) })).toBeVisible();

    // Passport draft
    await page.getByRole("button", { name: "Create passport draft" }).click();
    await expect(page.getByText("rev 1 (draft)")).toBeVisible();
    state.passportUrl = new URL(page.url()).pathname;
    state.passportNumber = (await page.getByRole("heading", { level: 1 }).textContent())!.split(" · ")[0];
    await page.getByLabel("Shape").selectOption("cylinder");
    await page.getByLabel("Part size").fill("45");
    await page.getByLabel("H", { exact: true }).fill("40.5");
    await page.getByLabel("Static or rotating").selectOption("rotating");
    await page.getByLabel("Original material grade").fill("Stainless Steel");
    await page.getByRole("button", { name: "Save R-L1" }).click();
    await expect(page.getByText("R-L1 saved.")).toBeVisible();
    // Gated actions are disabled, not working placeholders
    await expect(page.getByRole("button", { name: "Submit for approval" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Approve" })).toBeDisabled();

    // Uploads: STEP, PDF, DWG (Documents section of the passport)
    await page.getByRole("tab", { name: "Documents" }).click();
    await uploadFile(page, STEP_FILE, "3d_model");
    await expect(page.getByText(/uploaded \(SHA-256/)).toBeVisible();
    await uploadFile(page, PDF_FILE, "specification");
    await expect(page.getByText(new RegExp(`specification-${RUN}.pdf uploaded`))).toBeVisible();
    await uploadFile(page, DWG_FILE, "drawing");
    await expect(page.getByText(new RegExp(`drawing-${RUN}.dwg uploaded`))).toBeVisible();

    // Clear errors for invalid uploads
    const form = page.getByRole("form", { name: "Upload engineering file" });
    await form.locator('input[type="file"]').setInputFiles(TXT_FILE);
    await form.getByRole("button", { name: "Upload" }).click();
    await expect(page.getByRole("alert")).toContainText("Only STEP (.stp, .step), DWG (.dwg), PDF (.pdf) and part photographs (.jpg, .jpeg, .png) can be uploaded.");
    await form.locator('input[type="file"]').setInputFiles(FAKE_STEP);
    await form.getByRole("button", { name: "Upload" }).click();
    await expect(page.getByRole("alert")).toContainText("not a valid STEP file");
    await expect(page.getByText("Preview not available")).toBeVisible(); // DWG converter pending (OQ-27)
    await page.screenshot({ path: path.join(SHOTS, "02-passport-detail-files.png"), fullPage: true });

    // CAD worker converts the STEP original to GLB
    const out = runWorker();
    expect(out).toContain("job finished: succeeded");
    await page.reload();
    await expect(page.getByText("3D view ready")).toBeVisible();

    // Authorised download of the preserved original
    const pdfRow = page.getByRole("row", { name: new RegExp(`specification-${RUN}`) });
    const [download] = await Promise.all([page.waitForEvent("download"), pdfRow.getByRole("button", { name: "Download original" }).click()]);
    const saved = path.join(tmp, "downloaded.pdf");
    await download.saveAs(saved);
    expect(createHash("sha256").update(fs.readFileSync(saved)).digest("hex")).toBe(createHash("sha256").update(PDF_BYTES).digest("hex"));

    // 3D viewer, embedded in the passport
    await page.getByRole("button", { name: "View 3D" }).click();
    await expect(page.getByRole("tab", { name: "Interactive 3D model" })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("viewer-stats")).toContainText("triangles", { timeout: 60_000 });
    await expect(page.getByTestId("viewer-stats")).toContainText("40.50");
    for (const view of ["Front", "Top", "Isometric", "Fit", "Reset"]) await page.getByRole("button", { name: view, exact: true }).click();
    await page.screenshot({ path: path.join(SHOTS, "03-3d-viewer.png") });
    await signOut(page);
  });

  test("client user: read-only catalog, derivative viewing, no original download", async ({ page }) => {
    await signIn(page, "user@client.demo");
    await expect(page.getByRole("link", { name: "Clients", exact: true })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Users", exact: true })).toHaveCount(0);
    await page.goto(state.passportUrl);
    await expect(page.getByRole("heading", { name: new RegExp(state.passportNumber) })).toBeVisible();
    await expect(page.getByRole("button", { name: "Save R-L1" })).toHaveCount(0);
    await page.getByRole("tab", { name: "Documents" }).click();
    await expect(page.getByRole("button", { name: "View 3D" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Download original" })).toHaveCount(0);
    await expect(page.getByRole("form", { name: "Upload engineering file" })).toHaveCount(0);
    await page.screenshot({ path: path.join(SHOTS, "04-client-user-passport.png"), fullPage: true });
    await signOut(page);
  });

  test("operator admin creates a second client; its admin cannot see the first client's data", async ({ page }) => {
    const slug = `e2e-other-${RUN}`;
    const adminEmail = `admin@${slug}.test`;
    const adminPassword = `Other-Client-${RUN}-Pass!`;
    await signIn(page, "admin@operator.demo");
    await page.getByRole("link", { name: "Clients", exact: true }).click();
    await fillNewClient(page, `E2E Other Client ${RUN}`, slug);
    await page.getByRole("button", { name: "Create client" }).click();
    await expect(page.getByRole("status")).toContainText("created");
    await openClient(page, `E2E Other Client ${RUN}`);
    const memberForm = page.locator("form").filter({ has: page.getByRole("button", { name: "Add member" }) });
    await memberForm.getByLabel("Email").fill(adminEmail);
    await memberForm.getByLabel("Role").selectOption("client_admin");
    await memberForm.getByLabel("Initial password").fill(adminPassword);
    await memberForm.getByRole("button", { name: "Add member" }).click();
    await expect(page.getByRole("cell", { name: adminEmail })).toBeVisible();
    await page.screenshot({ path: path.join(SHOTS, "05-operator-clients.png"), fullPage: true });
    await signOut(page);

    await signIn(page, adminEmail, adminPassword);
    await page.getByRole("link", { name: "Digital inventory", exact: true }).click();
    await expect(page.getByText("No spare parts yet.")).toBeVisible();
    await page.goto(state.passportUrl);
    await expect(page.getByRole("alert")).toContainText(/not found/i);
    await signOut(page);
  });
});
