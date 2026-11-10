/**
 * W2 acceptance: client dashboard, digital inventory catalog, part photographs, passport overview, live conversion
 * status, viewer pan, single-use links and tenant isolation of catalog and dashboard. Synthetic files only.
 */
import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { fillNewClient, makePdf, makePng, openClient, PASSWORD, runWorker, SHOTS, signIn, signOut, STEP_FILE, uploadFile } from "./helpers";

const RUN = Date.now().toString(36);
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "passport-w2-"));
const PHOTO = path.join(tmp, `photo-${RUN}.png`);
const SPEC = path.join(tmp, `spec-${RUN}.pdf`);
fs.writeFileSync(PHOTO, makePng());
fs.writeFileSync(SPEC, makePdf(2, "W2 specification"));
const state = { part: `W2-${RUN}`, project: `PRJ-${RUN}`, passportUrl: "", passportNumber: "", partUrl: "" };
const OTHER = { slug: `w2-other-${RUN}`, name: `W2 Other ${RUN}`, admin: `admin@w2-${RUN}.test`, password: `W2-Other-${RUN}-Pass!` };

const rows = (page: Page) => page.locator("table.catalog-table tbody tr");

test.describe.serial("W2 client portal and digital inventory", () => {
  test("operator engineer: project, part photo, passport, live conversion status, embedded viewer with pan", async ({ page }) => {
    test.setTimeout(300_000);
    await signIn(page, "engineer@operator.demo", PASSWORD, "demo-client");

    await page.getByRole("link", { name: "Projects", exact: true }).click();
    await page.getByLabel("Code").fill(state.project);
    await page.getByLabel("Project name").fill("Pump overhaul");
    await page.getByRole("button", { name: "Create project" }).click();
    await expect(page.getByRole("status")).toContainText(`Project ${state.project} created.`);

    await page.getByRole("link", { name: "Digital inventory", exact: true }).click();
    await page.getByRole("button", { name: "New spare part" }).click();
    await page.getByLabel("Part number").fill(state.part);
    await page.getByLabel("Name", { exact: true }).fill("Pump sleeve (W2)");
    // structured dimensions (CN-003): Ø × H in mm
    await page.getByLabel("Spare part master data").getByLabel("Shape").selectOption("cylinder");
    await page.getByLabel("Dimensions").fill("45");
    await page.getByLabel("Spare part master data").getByLabel("H", { exact: true }).fill("40.5");
    await page.getByLabel("Project", { exact: true }).selectOption({ label: `${state.project} · Pump overhaul` });
    await page.getByRole("button", { name: "Create spare part" }).click();
    await expect(page.getByRole("heading", { name: new RegExp(state.part) })).toBeVisible();
    state.partUrl = new URL(page.url()).pathname;

    // Photograph: section chosen automatically, thumbnail appears on the part
    const form = page.getByRole("form", { name: "Upload engineering file" });
    await form.locator('input[type="file"]').setInputFiles(PHOTO);
    await expect(form.getByLabel("Section")).toHaveValue("photo");
    await form.getByRole("button", { name: "Upload" }).click();
    await expect(page.getByText(/photo-.*\.png uploaded/)).toBeVisible();
    await page.reload();
    await expect(page.locator(`img.thumb[alt="${state.part}"]`)).toBeVisible();

    await page.getByRole("button", { name: "Create passport draft" }).click();
    await expect(page.getByText("rev 1 (draft)")).toBeVisible();
    state.passportUrl = new URL(page.url()).pathname;
    state.passportNumber = (await page.getByRole("heading", { level: 1 }).textContent())!.split(" · ")[0];
    await expect(page.getByRole("tab", { name: "Readiness data" })).toHaveAttribute("aria-selected", "true"); // editors land on the forms

    await page.getByRole("tab", { name: "Documents" }).click();
    await uploadFile(page, SPEC, "specification");
    await expect(page.getByText(new RegExp(`spec-${RUN}\\.pdf uploaded`))).toBeVisible();
    await uploadFile(page, STEP_FILE, "3d_model");
    await expect(page.getByText(/sleeve_d45_h40_5_synthetic\.stp uploaded/)).toBeVisible();
    await expect(page.getByText("Queued for 3D conversion")).toBeVisible();
    await expect(page.getByText(/being converted for the 3D view/)).toBeVisible();
    expect(runWorker()).toContain("job finished: succeeded");
    // No reload: the page polls while a conversion is pending
    await expect(page.getByText("3D view ready").first()).toBeVisible({ timeout: 20_000 });
    // File-revision association in the version history
    await page.getByTestId(`file-spec-${RUN}.pdf`).getByRole("button", { name: "Versions" }).click();
    await expect(page.getByRole("table", { name: `Versions of spec-${RUN}.pdf` })).toContainText("rev 1");

    // Overview -> open 3D view; loading state, then the model; pan with right-drag
    await page.getByRole("tab", { name: "Overview" }).click();
    await page.getByRole("region", { name: "3D model status" }).getByRole("button", { name: "Open 3D view" }).click();
    await expect(page.getByTestId("viewer-stats")).toContainText("40.50", { timeout: 60_000 });
    await expect(page.getByTestId("viewer-loading")).toHaveCount(0);
    const canvas = page.getByTestId("viewer-host").locator("canvas");
    const before = await canvas.screenshot();
    const box = (await canvas.boundingBox())!;
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down({ button: "right" });
    await page.mouse.move(box.x + box.width / 2 + 160, box.y + box.height / 2 + 60, { steps: 10 });
    await page.mouse.up({ button: "right" });
    await page.waitForTimeout(600);
    const panned = await canvas.screenshot();
    expect(Buffer.compare(before, panned)).not.toBe(0); // the view moved
    await page.getByRole("button", { name: "Reset" }).click();
    await page.screenshot({ path: path.join(SHOTS, "w2-04-viewer.png") });
    await signOut(page);
  });

  test("catalog: passport-number search, filters, sort, URL state and empty state", async ({ page }) => {
    await signIn(page, "admin@client.demo");
    await page.goto(`/parts?view=list&search=${encodeURIComponent(state.passportNumber)}`); // list view = the catalog table
    await expect(rows(page)).toHaveCount(1);
    await expect(rows(page).first()).toContainText(state.part);
    await expect(rows(page).first().locator("img.thumb")).toBeVisible(); // photograph thumbnail
    await expect(rows(page).first()).toContainText("3D view");

    await page.getByRole("button", { name: /Clear filters/ }).click();
    await page.getByLabel("Filter by project").selectOption({ label: `${state.project} · Pump overhaul` });
    await expect(page).toHaveURL(/project=/);
    await page.reload(); // filters survive a reload (kept in the URL)
    await expect(page.getByLabel("Filter by project")).not.toHaveValue("");
    await expect(rows(page)).toHaveCount(1);

    await page.getByLabel("Filter by data captured").selectOption("rl3");
    await expect(page.getByText("No spare parts match these filters.")).toBeVisible();
    await page.getByLabel("Filter by data captured").selectOption("none");
    await expect(rows(page)).toHaveCount(1);
    await page.getByRole("button", { name: /Clear filters/ }).click();

    // URL-driven controls settle after the router's transition, so click and wait for the state
    await page.getByLabel("Has 3D view").click();
    await expect(page.getByLabel("Has 3D view")).toBeChecked();
    await expect(page).toHaveURL(/has_3d=true/);
    await expect(rows(page).filter({ hasText: state.part })).toHaveCount(1);
    await page.getByLabel("Has 3D view").click();
    await expect(page.getByLabel("Has 3D view")).not.toBeChecked();
    // The server sorts (database collation). The UI must show the API's order for each sort, and page 1 of Z–A must be
    // the reverse of the full A–Z order (fetched with the page's own credentials; the catalog may span several pages).
    const partNumbers = () => rows(page).locator("td:nth-child(2) strong").allTextContents();
    const sortTo = async (value: string) => {
      const [res] = await Promise.all([
        page.waitForResponse((r) => r.url().includes("/api/v1/parts/") && r.url().includes(`ordering=${encodeURIComponent(value)}`)),
        page.getByLabel("Sort by").selectOption(value),
      ]);
      const api = ((await res.json()).results as { part_number: string }[]).map((p) => p.part_number);
      await expect.poll(partNumbers).toEqual(api);
      return { api, auth: (await res.request().allHeaders()).authorization };
    };
    const { auth } = await sortTo("part_number");
    const full = await page.request.get("/api/v1/parts/?ordering=part_number&page_size=200", { headers: { Authorization: auth } });
    const allAscending = ((await full.json()).results as { part_number: string }[]).map((p) => p.part_number);
    const { api: descendingPage } = await sortTo("-part_number");
    expect(descendingPage).toEqual([...allAscending].reverse().slice(0, descendingPage.length));
    await page.screenshot({ path: path.join(SHOTS, "w2-02-catalog.png"), fullPage: true });
    await signOut(page);
  });

  test("client dashboard: real summaries, recent parts and filter links", async ({ page }) => {
    await signIn(page, "user@client.demo");
    await expect(page.getByRole("heading", { name: "Passport data captured" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "3D conversion" })).toBeVisible();
    const recent = page.locator("section.card", { hasText: "Recently updated parts" });
    await expect(recent.getByRole("link", { name: state.part })).toBeVisible();
    await expect(page.locator("main")).not.toContainText(/orders?\b/i); // no fabricated production statistics
    await page.screenshot({ path: path.join(SHOTS, "w2-01-dashboard.png"), fullPage: true });
    await page.getByRole("link", { name: /Data incomplete/ }).click();
    await expect(page).toHaveURL(/\/parts\?data_level=none/);
    await expect(page.getByLabel("Filter by data captured")).toHaveValue("none");
    await signOut(page);
  });

  test("client admin: passport overview and single-use download links", async ({ page }) => {
    await signIn(page, "admin@client.demo");
    await page.goto(state.passportUrl);
    await expect(page.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true"); // read-only users
    await expect(page.getByRole("region", { name: "R-L1 summary" })).toBeVisible();
    await expect(page.getByRole("region", { name: "Document availability" })).toContainText("Photographs");
    await expect(page.getByRole("region", { name: "3D model status" })).toContainText("3D view ready");
    await page.screenshot({ path: path.join(SHOTS, "w2-03-passport-overview.png"), fullPage: true });

    await page.getByRole("tab", { name: "Documents" }).click();
    const row = page.getByTestId(`file-spec-${RUN}.pdf`);
    const [download] = await Promise.all([page.waitForEvent("download"), row.getByRole("button", { name: "Download original" }).click()]);
    expect(await download.failure()).toBeNull();
    const reuse = await page.request.get(download.url());
    expect(reuse.status()).toBe(410);
    expect((await reuse.json()).error.code).toBe("link_used");
    await signOut(page);
  });

  test("another client organisation: catalog and dashboard disclose nothing", async ({ page }) => {
    await signIn(page, "admin@operator.demo");
    await page.getByRole("link", { name: "Clients", exact: true }).click();
    await fillNewClient(page, OTHER.name, OTHER.slug);
    await page.getByRole("button", { name: "Create client" }).click();
    await expect(page.getByRole("status")).toContainText(`"${OTHER.name}" created`);
    await openClient(page, OTHER.name);
    const memberForm = page.locator("form").filter({ has: page.getByRole("button", { name: "Add member" }) });
    await memberForm.getByLabel("Email").fill(OTHER.admin);
    await memberForm.getByLabel("Initial password").fill(OTHER.password);
    await memberForm.getByRole("button", { name: "Add member" }).click();
    await expect(page.getByRole("cell", { name: OTHER.admin })).toBeVisible();
    await signOut(page);

    await signIn(page, OTHER.admin, OTHER.password);
    await expect(page.locator(".stat", { hasText: "Spare parts" })).toContainText("0");
    for (const q of [state.passportNumber, state.part, state.project]) {
      await page.goto(`/parts?search=${encodeURIComponent(q)}`);
      await expect(page.getByText("No spare parts match these filters.")).toBeVisible();
    }
    await page.goto(state.partUrl);
    await expect(page.getByRole("alert")).toContainText(/not found/i);
  });
});
