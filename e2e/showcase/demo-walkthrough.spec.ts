/**
 * Demonstration walkthrough against the showcase dataset (passport_demo database, seed_showcase).
 * Run only with e2e/showcase/playwright.config.ts while the API runs on the demo database
 * (backend/scripts/run_demo.py api). Read-only: it creates and changes nothing in the demo data.
 */
import { expect, test, type Page } from "@playwright/test";
import path from "node:path";

import { PASSWORD, SHOTS, signIn, signOut } from "../helpers";

/** Full-page screenshot from the top (sticky header and sidebar otherwise repeat mid-page in the capture). */
async function shot(page: Page, name: string) {
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: path.join(SHOTS, `showcase-${name}.png`), fullPage: true });
}
const rows = (page: Page) => page.locator("table.catalog-table tbody tr");
const cards = (page: Page) => page.locator("ul.part-grid > li");
const state = { energyPartUrl: "" };

/** Thumbnails load as authenticated blobs; wait until at least n have decoded before a screenshot. */
async function thumbsLoaded(page: Page, n: number) {
  await expect.poll(() => page.evaluate(() => [...document.querySelectorAll<HTMLImageElement>("img.thumb")].filter((i) => i.complete && i.naturalWidth > 0).length), { timeout: 30_000 }).toBeGreaterThanOrEqual(n);
}

/** Authorization header of the page's own API calls (to check API permissions with the same session). */
async function authHeader(page: Page): Promise<string> {
  const [req] = await Promise.all([
    page.waitForRequest((r) => r.url().includes("/api/v1/") && !!r.headers().authorization),
    page.reload(),
  ]);
  return req.headers().authorization;
}

test.describe.serial("Showcase demonstration walkthrough", () => {
  test("1-2 operator administrator: sign in and select a demo client organisation", async ({ page }) => {
    await signIn(page, "admin@operator.demo");
    await expect(page.getByRole("heading", { name: "Aries Admin Dashboard" })).toBeVisible();
    await expect(page.getByRole("table", { name: "Client overview" })).toContainText("Demo Maritime Engineering");
    await expect(page.getByRole("link", { name: "Digital inventory", exact: true })).toHaveCount(0); // no empty inventory menus
    await page.getByRole("link", { name: "Clients", exact: true }).click();
    await page.getByRole("button", { name: "Demo Maritime Engineering", exact: true }).click();
    await expect(page.getByRole("cell", { name: "admin@maritime.demo" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "engineer@operator.demo" })).toBeVisible(); // assigned operator staff
    await shot(page, "01-operator-admin-client");
    await signOut(page);
  });

  test("3-11 operator engineer: projects, inventory search, part, passport, 3D, PDF, versions", async ({ page }) => {
    test.setTimeout(240_000);
    await signIn(page, "engineer@operator.demo", PASSWORD, "demo-maritime");
    await expect(page.getByRole("heading", { name: "Demo Maritime Engineering" })).toBeVisible();
    await expect(page.locator(".stat", { hasText: "Spare parts" })).toContainText("11");
    await expect(page.getByRole("heading", { name: "My organisations" })).toBeVisible();
    await thumbsLoaded(page, 7);
    await shot(page, "02-dashboard-operator-engineer");

    // 3. projects
    await page.getByRole("link", { name: "Projects", exact: true }).click();
    await expect(page.getByText("DME-P01")).toBeVisible();
    await expect(page.getByText("Deck machinery spares (sample)")).toBeVisible();
    await shot(page, "03-projects");

    // 4. inventory search
    await page.getByRole("link", { name: "Digital inventory", exact: true }).click();
    await expect(rows(page)).toHaveCount(11);
    await thumbsLoaded(page, 10);
    await shot(page, "04-digital-inventory");
    await page.getByLabel("Search spare parts").fill("impeller");
    await page.getByLabel("Search spare parts").press("Enter");
    await expect(rows(page)).toHaveCount(1);
    await expect(rows(page).first()).toContainText("DME-1001");

    // 5. part
    await rows(page).first().getByRole("link", { name: "DME-1001" }).click();
    await expect(page.getByRole("heading", { name: /DME-1001/ })).toBeVisible();
    await expect(page.locator("img.thumb").first()).toBeVisible();
    await shot(page, "05-part");

    // 6-7. passport and R-L1 / R-L2 / R-L3 data
    await page.getByRole("link", { name: /DP-\d{4}-\d{5}/ }).first().click();
    await expect(page.getByRole("tab", { name: "Readiness data" })).toHaveAttribute("aria-selected", "true");
    for (const level of ["R-L1", "R-L2", "R-L3"]) {
      await page.getByRole("tablist", { name: "Readiness levels" }).getByRole("tab", { name: new RegExp(level) }).click();
      await expect(page.getByRole("tabpanel").last()).toBeVisible();
    }
    await expect(page.getByText(/Not QA-verified/).first()).toBeVisible(); // R-L3 notes
    await shot(page, "07-readiness-rl3");
    await page.getByRole("tab", { name: "Overview" }).click();
    await expect(page.getByRole("region", { name: "R-L2 summary" })).toBeVisible();
    await expect(page.locator(".state-strip")).toContainText("Not assessed");
    await shot(page, "06-passport-overview");

    // 8-9. converted STEP model: rotate, zoom, standard views
    await page.getByRole("tab", { name: "Interactive 3D model" }).click();
    await expect(page.getByTestId("viewer-stats")).toContainText("165.00", { timeout: 60_000 });
    const canvas = page.getByTestId("viewer-host").locator("canvas");
    await canvas.scrollIntoViewIfNeeded(); // the drag below uses page coordinates, so the canvas must be on screen
    const box = (await canvas.boundingBox())!;
    const before = await canvas.screenshot();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 + 140, box.y + box.height / 2 + 40, { steps: 10 });
    await page.mouse.up();
    await page.mouse.wheel(0, -400);
    await page.waitForTimeout(500);
    expect(Buffer.compare(before, await canvas.screenshot())).not.toBe(0); // rotated and zoomed
    for (const view of ["Front", "Top", "Isometric", "Fit"]) await page.getByRole("button", { name: view, exact: true }).click();
    await shot(page, "08-3d-viewer");

    // 10. multi-page PDF preview
    await page.getByRole("tab", { name: "Documents" }).click();
    const spec = page.getByTestId("file-DME-1001 manufacturing specification");
    await spec.getByRole("button", { name: "Preview" }).click();
    await expect(page.getByText(/Page 1 of 3/)).toBeVisible({ timeout: 30_000 });
    await page.getByRole("button", { name: "Next page" }).click();
    await expect(page.getByText(/Page 2 of 3/)).toBeVisible();
    await shot(page, "09-pdf-preview");
    await spec.getByRole("button", { name: "Close preview" }).click();

    // 11. version history (rev B of the specification)
    await spec.getByRole("button", { name: "Versions" }).click();
    const versions = page.getByRole("table", { name: "Versions of DME-1001 manufacturing specification" });
    await expect(versions.locator("tbody tr")).toHaveCount(2);
    await expect(versions).toContainText("Rev B");
    await shot(page, "10-documents-versions");
  });

  test("12 operator engineer: switch to another client organisation", async ({ page }) => {
    await signIn(page, "engineer@operator.demo", PASSWORD, "demo-maritime");
    await page.getByLabel("Switch organisation").selectOption("demo-energy");
    await expect(page.getByRole("heading", { name: "Demo Energy Systems" })).toBeVisible();
    await page.getByRole("link", { name: "Digital inventory", exact: true }).click();
    await expect(rows(page)).toHaveCount(10);
    await expect(rows(page).first()).toContainText("DES-");
    await rows(page).filter({ hasText: "DES-3001" }).getByRole("link", { name: "DES-3001" }).click();
    state.energyPartUrl = new URL(page.url()).pathname;
  });

  test("P1 visual client catalog: cards, sections, quick view, list and phone layouts", async ({ page }) => {
    test.setTimeout(180_000);
    await signIn(page, "admin@maritime.demo");
    await page.getByRole("link", { name: "Digital inventory", exact: true }).click();
    await expect(page).toHaveURL(/catalog=in_digitisation/);
    await expect(cards(page)).toHaveCount(11);
    await expect(page.getByRole("button", { name: /request manufacturing|order|approve|release/i })).toHaveCount(0);
    await thumbsLoaded(page, 10);
    await shot(page, "p1-01-catalog-grid");
    await page.getByRole("button", { name: /Published catalog/ }).click();
    await expect(page.getByText(/No parts are published in your manufacturing catalog yet/)).toBeVisible();
    await shot(page, "p1-02-published-empty");
    await page.getByRole("button", { name: /In digitisation/ }).click();
    const impeller = cards(page).filter({ hasText: "DME-1001" });
    await impeller.getByRole("button", { name: "Quick view", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByTestId("viewer-stats")).toContainText("165.00", { timeout: 60_000 });
    await dialog.locator(".doc-list li", { hasText: "manufacturing specification" }).getByRole("button", { name: "Preview" }).click();
    await expect(dialog.getByText(/Page 1 of 3/)).toBeVisible({ timeout: 30_000 });
    await page.locator(".quickview-backdrop").evaluate((e) => e.scrollTo(0, 0));
    await page.screenshot({ path: path.join(SHOTS, "showcase-p1-03-quick-view.png") });
    await dialog.getByRole("button", { name: "Close quick view" }).click();
    await page.getByRole("button", { name: "List", exact: true }).click();
    await expect(rows(page)).toHaveCount(11);
    await thumbsLoaded(page, 10);
    await shot(page, "p1-04-list-view");
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole("button", { name: "Grid", exact: true }).click();
    await thumbsLoaded(page, 2);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: path.join(SHOTS, "showcase-p1-05-mobile-grid.png") });
    await cards(page).first().getByRole("button", { name: "Quick view", exact: true }).click();
    await expect(page.getByRole("dialog").getByTestId("viewer-stats")).toBeVisible({ timeout: 60_000 });
    await page.screenshot({ path: path.join(SHOTS, "showcase-p1-06-mobile-quick-view.png") });
  });

  test("13 client administrator: own organisation only", async ({ page }) => {
    await signIn(page, "admin@energy.demo");
    await expect(page.getByRole("heading", { name: "Demo Energy Systems" })).toBeVisible();
    await expect(page.locator(".stat", { hasText: "Spare parts" })).toContainText("10");
    await expect(page.getByLabel("Switch organisation")).toHaveCount(0); // one organisation only
    await thumbsLoaded(page, 8);
    await shot(page, "11-dashboard-client-admin");
    await page.getByRole("link", { name: "Digital inventory", exact: true }).click();
    await page.getByLabel("Search spare parts").fill("DME-1001");
    await page.getByLabel("Search spare parts").press("Enter");
    await expect(page.getByText("No spare parts match these filters.")).toBeVisible();
    await expect(page.getByRole("button", { name: "New spare part" })).toHaveCount(0); // operator-only action
    await signOut(page);
  });

  test("14-15 client user: read-only, other tenants invisible, original downloads refused", async ({ page }) => {
    await signIn(page, "user@maritime.demo");
    await page.getByRole("link", { name: "Digital inventory", exact: true }).click();
    await expect(cards(page)).toHaveCount(11); // client users get the visual catalog (P1)
    await cards(page).filter({ hasText: "DME-1002" }).getByRole("link", { name: "DME-1002" }).click();
    await expect(page.getByRole("form", { name: "Upload engineering file" })).toHaveCount(0); // read-only
    await shot(page, "12-client-user-readonly");
    // another organisation's part, by URL: not found
    await page.goto(state.energyPartUrl);
    await expect(page.getByRole("alert")).toContainText(/not found/i);
    // the API refuses original downloads for client users, and hides other tenants' files
    const auth = await authHeader(page);
    const files = await page.request.get("/api/v1/files/?kind=pdf&page_size=1", { headers: { Authorization: auth } });
    const file = (await files.json()).results[0];
    const original = await page.request.post(`/api/v1/files/${file.id}/versions/1/download-link/`,
      { headers: { Authorization: auth }, data: { variant: "original" } });
    expect(original.status()).toBe(403);
    const preview = await page.request.post(`/api/v1/files/${file.id}/versions/1/download-link/`,
      { headers: { Authorization: auth }, data: { variant: "preview" } });
    expect(preview.status()).toBe(200); // viewing is allowed
    const search = await page.request.get("/api/v1/parts/?search=DES-3001", { headers: { Authorization: auth } });
    expect((await search.json()).count).toBe(0);
    await signOut(page);
  });
});
