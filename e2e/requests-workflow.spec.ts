/**
 * Demo workflow: client manufacturing ENQUIRY from the visual catalog and a 3D scanning request, operator intake,
 * acknowledgement and reply, in-app notifications and client tracking. Nothing here releases manufacturing.
 * Defaults use the development data (demo-client); the showcase run sets DEMO_ORG, DEMO_CLIENT_ADMIN,
 * DEMO_PART_SEARCH and DEMO_SHOT_PREFIX.
 */
import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { PASSWORD, SHOTS, makePng, signIn, signOut } from "./helpers";

const ORG = process.env.DEMO_ORG ?? "demo-client";
const CLIENT = process.env.DEMO_CLIENT_ADMIN ?? "admin@client.demo";
const SEARCH = process.env.DEMO_PART_SEARCH ?? "W2-";
const PREFIX = process.env.DEMO_SHOT_PREFIX ?? "";
const shot = async (page: Page, name: string, full = true) => {
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: path.join(SHOTS, `${PREFIX}req-${name}.png`), fullPage: full });
};
const PHOTO = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "passport-req-")), "worn-part.png");
fs.writeFileSync(PHOTO, makePng());
const state = { ref: "", requestUrl: "", scanRef: "", scanUrl: "" };

async function openNotification(page: Page, text: string | RegExp) {
  const bell = page.getByRole("button", { name: /Notifications, \d+ unread/ });
  await expect(bell).not.toHaveAccessibleName("Notifications, 0 unread", { timeout: 20_000 });
  await bell.click();
  await page.getByRole("dialog", { name: "Notifications" }).getByRole("button", { name: text }).first().click();
}

test.describe.serial("Client requests and operator intake", () => {
  test("client: catalog → quick view → request → enquiry with reference", async ({ page }) => {
    await signIn(page, CLIENT);
    await page.goto(`/parts?search=${encodeURIComponent(SEARCH)}&has_3d=true`);
    const card = page.locator("ul.part-grid > li").first();
    await expect(card).toBeVisible();
    await card.getByRole("button", { name: "Quick view", exact: true }).click();
    await expect(page.getByRole("dialog").getByTestId("viewer-stats")).toBeVisible({ timeout: 60_000 });
    await page.getByRole("dialog").getByRole("button", { name: "Request", exact: true }).click();

    const form = page.getByRole("form", { name: "Manufacturing request" });
    await expect(form).toContainText("This request will be sent as an enquiry"); // explained before submission
    await form.getByLabel("Quantity").fill("2");
    await form.getByLabel("Delivery location").fill("Main warehouse, bay 4");
    await form.getByLabel("Additive manufacturing").check();
    await form.getByLabel("Priority").selectOption("urgent");
    await form.getByLabel("Remarks").fill("Replacement needed for planned maintenance.");
    await form.getByLabel("Your reference (optional)").fill("PO-DEMO-001");
    await shot(page, "01-request-form", false);
    await form.getByRole("button", { name: "Send enquiry" }).click();

    const done = page.getByRole("status").filter({ hasText: /MR-\d{4}-\d{5}/ });
    await expect(done).toContainText("Submitted · awaiting acknowledgement");
    state.ref = (await done.locator(".request-ref").textContent())!.trim();
    await shot(page, "02-request-submitted", false);
    await page.getByRole("link", { name: "View request" }).click();
    state.requestUrl = new URL(page.url()).pathname;
    await expect(page.getByRole("heading", { name: state.ref })).toBeVisible();
    await expect(page.getByText("Manufacturing enquiry").first()).toBeVisible();
    await signOut(page);
  });

  test("operator: notification → incoming request → acknowledge → reply", async ({ page }) => {
    await signIn(page, "engineer@operator.demo", PASSWORD, ORG);
    await openNotification(page, new RegExp(`New enquiry ${state.ref}`));
    await expect(page.getByRole("heading", { name: new RegExp(state.ref) })).toBeVisible();
    await page.getByRole("link", { name: "Incoming requests" }).first().click();
    const row = page.getByRole("table", { name: "Incoming requests" }).getByRole("row", { name: new RegExp(state.ref) });
    await expect(row).toContainText("Submitted · awaiting acknowledgement");
    await shot(page, "03-incoming-queue");
    await row.getByRole("link", { name: state.ref }).click();
    await expect(page.getByRole("button", { name: /release|approve|production/i })).toHaveCount(0); // no production actions
    await page.getByRole("button", { name: "Acknowledge" }).click();
    await expect(page.getByText("Request acknowledged. The client has been notified.")).toBeVisible();
    await page.getByLabel("Message to the client").fill("Thank you. The part is still being digitised; we will confirm material and feasibility within two working days.");
    await page.getByRole("button", { name: "Send reply" }).click();
    await expect(page.getByText("Reply sent. The client has been notified.")).toBeVisible();
    await expect(page.getByLabel("Request history")).toContainText("Reply from the operator team");
    await shot(page, "04-operator-request");
    await signOut(page);
  });

  test("client: notification and tracking show the acknowledgement and reply", async ({ page }) => {
    await signIn(page, CLIENT);
    await openNotification(page, new RegExp(`Reply to ${state.ref}|${state.ref} acknowledged`));
    await expect(page.getByRole("heading", { name: state.ref })).toBeVisible();
    await expect(page.getByLabel("Request history")).toContainText("Acknowledged by the operator team");
    await expect(page.getByLabel("Request history")).toContainText("we will confirm material and feasibility");
    await shot(page, "05-client-tracking");
    await page.getByRole("link", { name: "My requests" }).first().click();
    await expect(page.getByRole("row", { name: new RegExp(state.ref) })).toContainText("Answered");
    await shot(page, "06-my-requests");
    await signOut(page);
  });

  test("3D scanning: client request with photo → operator acknowledges and creates the project → client tracks", async ({ page }) => {
    await signIn(page, CLIENT);
    await page.getByRole("link", { name: "Digital inventory", exact: true }).click();
    await page.getByRole("link", { name: "Request 3D scanning" }).click();
    const form = page.getByRole("form", { name: "3D scanning request" });
    await form.getByLabel("Site or location").fill("Pump house 2, north wing");
    await form.getByLabel("Equipment").fill("Cooling water pump P-12");
    await form.getByLabel("Part description").fill("Bronze impeller, approx. 180 mm diameter, worn vanes; no drawings available");
    await form.getByLabel("Reason for digitisation").selectOption("obsolete");
    await form.getByLabel("Contact phone").fill("+00 000 0000");
    await form.getByLabel("Photographs or supporting documents").setInputFiles(PHOTO);
    await shot(page, "07-scan-form");
    await form.getByRole("button", { name: "Submit scanning request" }).click();
    await expect(page.getByRole("heading", { name: /DR-\d{4}-\d{5}/ })).toBeVisible({ timeout: 20_000 });
    state.scanRef = (await page.getByRole("heading", { level: 1 }).textContent())!.trim();
    state.scanUrl = new URL(page.url()).pathname;
    await expect(page.getByText("worn-part.png")).toBeVisible();
    await signOut(page);

    await signIn(page, "engineer@operator.demo", PASSWORD, ORG);
    await page.getByRole("link", { name: "Incoming requests" }).first().click();
    await page.getByRole("row", { name: new RegExp(state.scanRef) }).getByRole("link", { name: state.scanRef }).click();
    await page.getByRole("button", { name: "Acknowledge" }).click();
    await expect(page.getByText("Request acknowledged. The client has been notified.")).toBeVisible();
    await page.getByRole("button", { name: "Create project and draft part" }).click();
    await expect(page.getByText(`Project ${state.scanRef} created`)).toBeVisible();
    await page.getByLabel("Message to the client").fill("Site visit planned for next week; our engineer will call the contact.");
    await page.getByRole("button", { name: "Mark scheduled" }).click();
    await expect(page.getByText(/Scheduled/).first()).toBeVisible();
    await shot(page, "08-operator-scan");
    await signOut(page);

    await signIn(page, CLIENT);
    await page.goto(state.scanUrl);
    await expect(page.getByText("Scheduled").first()).toBeVisible();
    await expect(page.getByLabel("Request history")).toContainText("Project created");
    await shot(page, "09-client-scan-tracking");
    await signOut(page);
  });
});
