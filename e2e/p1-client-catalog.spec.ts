/**
 * P1 visual client catalog: card grid with stored images, published / in-digitisation sections, grid/list toggle,
 * quick view (3D model and permitted previews), responsive layout, and no manufacturing or approval actions.
 * Uses the parts that earlier specs created in demo-client (photo, STEP converted to 3D, PDF specification).
 */
import { expect, test, type Page } from "@playwright/test";
import path from "node:path";

import { PASSWORD, SHOTS, signIn, signOut } from "./helpers";

const cards = (page: Page) => page.locator("ul.part-grid > li");
const NO_ACTIONS = /request manufacturing|place order|order now|approve|release/i;

async function openW2Parts(page: Page) {
  await page.goto("/parts?search=W2-&has_3d=true");
  await expect(page).toHaveURL(/catalog=in_digitisation/); // client default: nothing is published yet
  await expect(cards(page).first()).toBeVisible();
}

test.describe.serial("P1 visual client catalog", () => {
  test("client administrator: sections, cards, quick view with 3D and PDF preview, list view", async ({ page }) => {
    await signIn(page, "admin@client.demo");
    await page.getByRole("link", { name: "Digital inventory", exact: true }).click();
    await expect(page).toHaveURL(/catalog=in_digitisation/);
    await expect(page.getByRole("button", { name: "Grid" })).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByRole("button", { name: /All parts/ })).toHaveCount(0); // operator-only section

    // Published catalog: empty, with the honest reason
    await page.getByRole("button", { name: /Published catalog/ }).click();
    await expect(page.getByText(/No parts are published in your manufacturing catalog yet/)).toBeVisible();
    await page.getByRole("button", { name: /In digitisation/ }).click();

    await openW2Parts(page);
    const first = cards(page).first();
    await expect(first).toContainText("In digitisation · not manufacturing-ready");
    await expect(first).toContainText("Not eligible for manufacturing");
    await expect(first.locator("img.thumb")).toBeVisible(); // stored photograph
    await expect(page.getByRole("button", { name: NO_ACTIONS })).toHaveCount(0);
    await expect(page.locator("main")).not.toContainText(/price|lead time/i);
    await page.screenshot({ path: path.join(SHOTS, "p1-01-catalog-grid.png"), fullPage: true });

    // Quick view: 3D model and a permitted PDF preview
    await first.getByRole("button", { name: "Quick view", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByTestId("viewer-stats")).toBeVisible({ timeout: 60_000 });
    await expect(dialog).toContainText("Requests for this part are sent as enquiries"); // honest classification
    await expect(dialog.getByRole("button", { name: NO_ACTIONS })).toHaveCount(0);
    const pdf = dialog.locator(".doc-list li", { hasText: "PDF" }).first();
    await pdf.getByRole("button", { name: "Preview" }).click();
    await expect(dialog.getByText(/Page 1 of \d+/)).toBeVisible({ timeout: 30_000 });
    await page.locator(".quickview-backdrop").evaluate((e) => e.scrollTo(0, 0));
    await page.screenshot({ path: path.join(SHOTS, "p1-02-quick-view.png") });
    await dialog.getByRole("button", { name: "Back to 3D model" }).click(); // one media item at a time
    await expect(dialog.getByTestId("viewer-stats")).toBeVisible({ timeout: 60_000 });
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);

    // List view keeps the searchable table
    await page.getByRole("button", { name: "List" }).click();
    await expect(page).toHaveURL(/view=list/);
    await expect(page.locator("table.catalog-table tbody tr").first()).toContainText("not manufacturing-ready");
    await page.screenshot({ path: path.join(SHOTS, "p1-03-list-view.png"), fullPage: true });
    await signOut(page);
  });

  test("ordinary client user: browse and preview only, no downloads or actions in quick view", async ({ page }) => {
    await signIn(page, "user@client.demo");
    await openW2Parts(page);
    await cards(page).first().getByRole("button", { name: "Quick view", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByTestId("viewer-stats")).toBeVisible({ timeout: 60_000 });
    await expect(dialog.getByRole("button", { name: /download/i })).toHaveCount(0);
    await expect(dialog.getByRole("button", { name: "Preview" }).first()).toBeVisible();
    await expect(page.getByRole("button", { name: NO_ACTIONS })).toHaveCount(0);
    await dialog.getByRole("button", { name: "Close quick view" }).click();
    await signOut(page);
  });

  test("phone-sized screen: one card per row, full-screen quick view", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await signIn(page, "admin@client.demo");
    await openW2Parts(page);
    const [a, b] = [await cards(page).nth(0).boundingBox(), await cards(page).nth(1).boundingBox()];
    expect(a && b && Math.abs(a.x - b.x) < 2 && b.y > a.y).toBeTruthy(); // stacked, single column
    await page.screenshot({ path: path.join(SHOTS, "p1-04-mobile-grid.png") });
    await cards(page).first().getByRole("button", { name: "Quick view", exact: true }).click();
    const box = await page.getByRole("dialog").boundingBox();
    expect(box && box.width >= 380).toBeTruthy();
    await page.getByRole("dialog").getByRole("button", { name: "Close quick view" }).click();
  });

  test("operator staff keep the engineering table by default", async ({ page }) => {
    await signIn(page, "engineer@operator.demo", PASSWORD, "demo-client");
    await page.getByRole("link", { name: "Digital inventory", exact: true }).click();
    await expect(page.getByRole("button", { name: "All parts" })).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByRole("button", { name: "List" })).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator("table.catalog-table")).toBeVisible();
    await expect(page.getByRole("button", { name: "New spare part" })).toBeVisible();
  });
});
