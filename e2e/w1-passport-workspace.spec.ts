/**
 * Web batch W1 acceptance: review defects D-1..D-5, organisation switcher, part editing, R-L1..R-L3 capture with
 * completeness, versioned STEP/DWG/PDF documents, embedded 3D and multi-page PDF viewers, revision history, and
 * viewer access for each role. Synthetic files only. Requires the API, web dev server and seeded demo data.
 */
import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { fillNewClient, makePdf, openClient, PASSWORD, runWorker, SHOTS, signIn, signOut, STEP_FILE, uploadFile } from "./helpers";

const RUN = Date.now().toString(36);
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "passport-w1-"));
const file = (name: string, data: Buffer) => {
  const p = path.join(tmp, name);
  fs.writeFileSync(p, data);
  return p;
};
const SPEC = file(`spec-${RUN}.pdf`, makePdf(3, "Manufacturing specification"));
const SPEC_V2 = file(`spec-${RUN}-rev-b.pdf`, makePdf(3, "Manufacturing specification rev B"));
const DWG = file(`drawing-${RUN}.dwg`, Buffer.concat([Buffer.from("AC1032"), Buffer.alloc(2042)]));
const EVIDENCE: [string, string, string][] = [
  ["Inspection and test plan (ITP)", `itp-${RUN}.pdf`, "inspection"],
  ["Manufacturing machine details", `machine-${RUN}.pdf`, "other"],
  ["Print orientation document", `orientation-${RUN}.pdf`, "other"],
  ["Dimensional inspection report", `dimensional-${RUN}.pdf`, "inspection"],
  ["Material test certificate", `mtc-${RUN}.pdf`, "certificate"],
];
const OTHER = { slug: `w1-${RUN}`, name: `W1 Other Client ${RUN}`, admin: `admin@w1-${RUN}.test`, password: `W1-Other-${RUN}-Pass!` };
const state = { passportUrl: "", part: `W1-${RUN}` };

const pill = (page: Page, text: string) => page.locator(".state-strip .progress-pill", { hasText: text });

test.describe.serial("W1 passport workspace", () => {
  test("D-1/D-2/D-3: operator admin creates a client, assigns existing operator staff without a password", async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
    await signIn(page, "admin@operator.demo");
    await page.getByRole("link", { name: "Clients", exact: true }).click();
    await fillNewClient(page, OTHER.name, OTHER.slug);
    await page.getByRole("button", { name: "Create client" }).click();
    await expect(page.getByRole("status")).toContainText(`"${OTHER.name}" created`);
    expect(errors.filter((e) => /pattern attribute/i.test(e))).toEqual([]); // D-3

    await openClient(page, OTHER.name);
    const memberForm = page.locator("form").filter({ has: page.getByRole("button", { name: "Add member" }) });
    await memberForm.getByLabel("Email").fill("engineer@operator.demo");
    await memberForm.getByLabel("Role").selectOption("operator_engineer");
    await expect(memberForm.getByLabel("Initial password")).toHaveCount(0); // not asked for existing operator staff
    await memberForm.getByRole("button", { name: "Add member" }).click();
    await expect(page.getByRole("status")).toContainText("engineer@operator.demo added as Aries Engineer"); // D-1
    await memberForm.getByLabel("Email").fill(OTHER.admin);
    await memberForm.getByLabel("Role").selectOption("client_admin");
    await memberForm.getByLabel("Initial password").fill(OTHER.password);
    await memberForm.getByRole("button", { name: "Add member" }).click();
    await expect(page.getByRole("cell", { name: OTHER.admin })).toBeVisible();
    // D-2: membership changes show immediately (the new client opens automatically; it may sort onto another page)
    await expect(page.locator("section.card", { hasText: `Members of ${OTHER.name}` }).locator("tbody tr")).toHaveCount(2);
    // Operator administrators manage operator staff assignments in client organisations
    await page.getByLabel("Role of engineer@operator.demo").selectOption("operator_qa");
    await expect(page.getByRole("status")).toContainText("engineer@operator.demo updated.");
    await expect(page.getByLabel("Role of engineer@operator.demo")).not.toContainText("operator admin"); // no operator admin inside a client
    await page.getByLabel("Role of engineer@operator.demo").selectOption("operator_engineer");
    await signOut(page); // signed out while on /clients
  });

  test("D-4 and organisation switcher: next user lands on the dashboard and can switch organisation", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Email").fill("engineer@operator.demo");
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByLabel(/Organisation/).locator("option", { hasText: "Demo Client Energy" })).toHaveCount(1); // picker shown
    const choices = await page.getByLabel(/Organisation/).locator("option").allTextContents();
    expect(choices).toContain("Demo Client Energy");
    expect(choices).toContain(OTHER.name);
    expect(choices.some((c) => /Platform Operator/.test(c))).toBe(false); // assigned engineers work inside clients
    await page.getByLabel(/Organisation/).selectOption("demo-client");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(/\/$/); // not the previous user's /clients page
    await expect(page.getByRole("heading", { name: "Not available" })).toHaveCount(0);
    await expect(page.getByTestId("working-in")).toContainText("Working in");
    await expect(page.getByTestId("working-in")).toContainText("Demo Client Energy");
    await expect(page.getByRole("navigation", { name: "Breadcrumb" })).toContainText("Demo Client Energy");
    const overview = page.locator("section.card", { hasText: "My organisations" });
    await expect(overview).toContainText(OTHER.name);
    await expect(overview).not.toContainText("Platform Operator");
    await expect(overview.getByRole("row", { name: /Demo Client Energy/ })).toContainText("Current");
    const parts = page.locator(".stat", { hasText: "Spare parts" }).locator(".stat-value");
    await expect(parts).toHaveText(/^[1-9]\d*$/); // the demo client has parts
    // switch while staying on the dashboard: every figure must reload for the new organisation (stale-data fix)
    await page.getByLabel("Switch organisation").selectOption(OTHER.slug);
    await expect(page.getByTestId("working-in")).toContainText(OTHER.name);
    await expect(page.getByRole("status").filter({ hasText: "Now working in" })).toContainText(OTHER.name);
    await expect(parts).toHaveText("0"); // the newly selected client's own figure, not the previous client's
    await expect(page.locator("section.card", { hasText: "Recently updated parts" })).not.toContainText("E2E-");
    await expect(page.locator(".brand-sub")).toHaveText("Aries portal · client workspace"); // UX-2
    await page.screenshot({ path: path.join(SHOTS, "w1-01-dashboard-switcher.png") });
  });

  test("operator engineer completes a passport workspace", async ({ page }) => {
    test.setTimeout(420_000);
    await signIn(page, "engineer@operator.demo", PASSWORD, "demo-client");

    // Part with master data, then edit it
    await page.getByRole("link", { name: "Digital inventory", exact: true }).click();
    await page.getByRole("button", { name: "New spare part" }).click();
    await page.getByLabel("Part number").fill(state.part);
    await page.getByLabel("Name", { exact: true }).fill("Pump impeller holder (W1)");
    await page.getByLabel("Original material").fill("AISI 316");
    // structured dimensions (CN-003): Ø × H in mm
    await page.getByLabel("Spare part master data").getByLabel("Shape").selectOption("cylinder");
    await page.getByLabel("Dimensions").fill("45");
    await page.getByLabel("Spare part master data").getByLabel("H", { exact: true }).fill("40.5");
    await page.getByLabel("Application").fill("Cooling water pump");
    await page.getByRole("button", { name: "Create spare part" }).click();
    await page.getByRole("button", { name: "Edit" }).click();
    await page.getByLabel("Application").fill("Cooling water pump P-12");
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByRole("status")).toHaveText("Part master data saved.");
    await expect(page.getByText("Cooling water pump P-12")).toBeVisible();

    // Passport: R-L1 pre-filled from the part (UX-3), N/A with reason (BR-006)
    await page.getByRole("button", { name: "Create passport draft" }).click();
    await expect(page.getByText("rev 1 (draft)")).toBeVisible();
    state.passportUrl = new URL(page.url()).pathname;
    await expect(page.getByLabel("Part size")).toHaveValue("45"); // "Ø45 x 40.5 mm" opens as Ø × H in mm
    await expect(page.getByLabel("Application of part")).toHaveValue("Cooling water pump P-12");
    await expect(page.getByText("Pre-filled from the spare-part record; save to keep.").first()).toBeVisible();
    await page.getByLabel("3D CAD file available").selectOption("true");
    await page.getByLabel("2D drawings available").selectOption("true");
    await page.getByLabel("Material identification").selectOption("pmi");
    await page.getByLabel("Atmosphere").selectOption("non_corrosive");
    await page.getByLabel("Static or rotating").selectOption("rotating");
    await page.getByLabel("IP consideration").selectOption("active");
    await page.getByLabel("Technical description").fill("Holder locating the impeller on the shaft.");
    await page.locator(".na-field", { has: page.getByLabel("RPM (rotating parts)") }).getByLabel("Not applicable").check();
    await page.getByLabel("RPM (rotating parts) — reason not applicable").fill("Speed governed by the pump OEM; not recorded on site");
    await page.getByRole("button", { name: "Save R-L1" }).click();
    await expect(page.getByText("R-L1 saved.")).toBeVisible();
    await expect(pill(page, "R-L1")).toHaveText("R-L1 11/11");

    // R-L2 (BR-007, BR-026, BR-041)
    await page.getByRole("tab", { name: /R-L2/ }).click();
    const rl2: [string, string][] = [
      ["Manufacturing solution", "L-PBF, stress relieved, bore machined"], ["Material selection", "SS 316L"], ["Criticality (AMSL)", "AMSL-2"],
      ["Feedstock", "316L powder 15-45 µm"], ["Dimensional tolerances", "ISO 2768-m"],
      ["Inspection and test plan", "ITP-W1"], ["Test coupon details", "3 tensile coupons per build"],
      ["Job number", "J-W1"], ["Spec: material", "316L"], ["Spec: feedstock", "Lot 22"], ["Machine", "EOS M290"], ["Layer thickness", "40"],
      ["Build orientation", "Axis vertical"], ["Machining", "Bore H7"], ["Printing hours", "11.5"], ["Post-processing hours", "3"],
    ];
    for (const [label, value] of rl2) await page.getByLabel(label, { exact: true }).fill(value);
    // structured controls (requirement update 2026-10)
    await page.getByRole("group", { name: "Applicable standards" }).getByLabel("ASTM F3184").check();
    await page.getByRole("group", { name: "NDT" }).getByLabel("Dye penetrant (PT)").check();
    await page.getByLabel("Inert gas").selectOption("Argon");
    await page.getByLabel("Support strategy").selectOption("Block supports");
    await page.getByLabel("Heat treatment").selectOption("Stress relief");
    await page.getByLabel("Temperature °C").fill("650");
    await page.getByLabel("Hold time h").fill("2");
    await page.getByRole("group", { name: "Post-processing" }).getByLabel("Bead blast").check();
    await page.getByLabel("Material category").selectOption("superior");
    await page.getByLabel("Material test certificate required").selectOption("true");
    await page.getByRole("button", { name: "Add acceptance row" }).click();
    await page.getByLabel("Requirement 1").fill(">= 485");
    await page.getByLabel("Unit 1", { exact: true }).fill("MPa");
    await page.getByLabel("Standard 1").fill("ISO 6892-1");
    await page.getByRole("button", { name: "Add parameter" }).click();
    await page.getByLabel("Parameter 1", { exact: true }).fill("Laser power");
    await page.getByLabel("Value 1").fill("195");
    await page.getByLabel("Parameter unit 1").fill("W");
    await page.getByRole("button", { name: "Save R-L2" }).click();
    await expect(page.getByText("R-L2 saved.")).toBeVisible();
    await expect(pill(page, "R-L2")).toHaveText("R-L2 25/25");
    await expect(pill(page, "R-L1")).toHaveText("R-L1 11/11"); // R-L1 kept: levels are merged, not replaced

    // Documents: every PSEC-001 section is present; upload STEP, DWG, a 3-page PDF and five evidence PDFs
    await page.getByRole("tab", { name: "Documents" }).click();
    await expect(page.getByRole("region", { name: "Certification" }).getByText("None uploaded.")).toBeVisible();
    for (const [f, section] of [[STEP_FILE, "3d_model"], [DWG, "drawing"], [SPEC, "specification"]] as const) {
      await uploadFile(page, f, section);
      await expect(page.getByText(new RegExp(`${path.basename(f).replace(/\./g, "\\.")} uploaded`))).toBeVisible();
    }
    for (const [, name, section] of EVIDENCE) {
      await uploadFile(page, file(name, makePdf(1, name)), section);
      await expect(page.getByText(new RegExp(`${name.replace(/\./g, "\\.")} uploaded`))).toBeVisible();
    }

    // New version of the specification: v1 is kept (CAD-005, CAD-009)
    const specRow = page.getByTestId(`file-spec-${RUN}.pdf`);
    await specRow.getByRole("button", { name: "New version" }).click();
    const vForm = page.getByRole("form", { name: `Upload new version of spec-${RUN}.pdf` });
    await vForm.getByLabel("New version file").setInputFiles(SPEC_V2);
    await vForm.getByLabel("Change note").fill("Rev B: heat treatment updated");
    await vForm.getByRole("button", { name: "Upload version" }).click();
    const versions = page.getByRole("table", { name: `Versions of spec-${RUN}.pdf` });
    await expect(versions.getByRole("row")).toHaveCount(3);
    await expect(versions.getByRole("row").nth(1)).toContainText("v2current");
    await expect(versions.getByRole("row").nth(1)).toContainText("engineer@operator.demo");
    await expect(versions.getByRole("row").nth(2)).toContainText("v1");

    // Embedded multi-page PDF viewer (DRW-003)
    await specRow.getByRole("button", { name: "Preview" }).click();
    const status = page.getByTestId("pdf-status");
    await expect(status).toContainText("Page 1 of 3", { timeout: 30_000 });
    await page.getByRole("button", { name: "Next page" }).click();
    await expect(status).toContainText("Page 2 of 3");
    await page.getByLabel("Page number").fill("3");
    await page.getByLabel("Page number").press("Enter");
    await expect(status).toContainText("Page 3 of 3");
    const zoomOf = async () => Number(/zoom (\d+)%/.exec((await status.textContent()) ?? "")![1]);
    const fitted = await zoomOf();
    await page.getByRole("button", { name: "Zoom in" }).click();
    await expect.poll(zoomOf).toBeGreaterThan(fitted);
    await page.getByRole("button", { name: "Zoom out" }).click();
    await page.getByRole("button", { name: "Zoom out" }).click();
    await expect.poll(zoomOf).toBeLessThan(fitted);
    await page.getByRole("button", { name: "Fit width" }).click();
    await expect.poll(zoomOf).toBe(fitted);
    await page.screenshot({ path: path.join(SHOTS, "w1-02-pdf-viewer.png") });

    // Embedded 3D viewer after conversion (VWR-001..011)
    expect(runWorker()).toContain("job finished: succeeded");
    await page.reload();
    await page.getByRole("tab", { name: "Interactive 3D model" }).click();
    await expect(page.getByTestId("viewer-stats")).toContainText("40.50", { timeout: 60_000 });
    await page.getByRole("button", { name: "Top", exact: true }).click();
    await expect(page.getByRole("button", { name: "Top", exact: true })).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByRole("button", { name: "Full screen" })).toBeVisible();
    await page.screenshot({ path: path.join(SHOTS, "w1-03-embedded-3d.png") });

    // R-L3 evidence linked to the passport's own files (BR-008); QA confirmation stays gated (OQ-35)
    await page.getByRole("tab", { name: "Readiness data" }).click();
    await page.getByRole("tab", { name: /R-L3/ }).click();
    for (const [label, name] of EVIDENCE) await page.getByLabel(label).selectOption({ label: `${name} (PDF, v1)` });
    await page.getByRole("button", { name: "Save R-L3 evidence" }).click();
    await expect(page.getByText("R-L3 evidence saved.")).toBeVisible();
    await expect(pill(page, "R-L3")).toHaveText("R-L3 5/5");
    await expect(page.getByRole("button", { name: "Confirm R-L3 (QA)" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Approve" })).toBeDisabled();

    // Revision summary starts empty and replaces the old one (UX-4); history shows who changed it (BR-034)
    await expect(page.getByPlaceholder(/Replace with a new summary/)).toHaveValue("");
    await page.getByPlaceholder(/Replace with a new summary/).fill("Data capture complete for review");
    await page.getByRole("button", { name: "Update summary" }).click();
    await expect(page.getByRole("form", { name: "Revision summary" })).toContainText("Data capture complete for review");
    await page.getByRole("tab", { name: "Revision history" }).click();
    await expect(page.getByText(/last changed .* by engineer@operator\.demo/)).toBeVisible();
    await expect(page.getByText("Data capture complete for review").first()).toBeVisible();
    await page.getByRole("tab", { name: "Manufacturing history" }).click();
    await expect(page.getByText(/None recorded/)).toBeVisible();
    await page.screenshot({ path: path.join(SHOTS, "w1-04-revision-history.png"), fullPage: true });
  });

  for (const role of [
    { who: "client admin", email: "admin@client.demo", originals: true },
    { who: "client user", email: "user@client.demo", originals: false },
  ]) {
    test(`${role.who}: views 3D and PDF in the passport; download rights follow the role`, async ({ page }) => {
      await signIn(page, role.email);
      await page.goto(state.passportUrl);
      await expect(page.getByRole("button", { name: "Save R-L1" })).toHaveCount(0);
      await expect(page.getByText("Drafts can be prepared now.")).toHaveCount(0); // UX-9
      await page.getByRole("tab", { name: "Interactive 3D model" }).click();
      await expect(page.getByTestId("viewer-stats")).toContainText("40.50", { timeout: 60_000 });
      await page.getByRole("tab", { name: "Documents" }).click();
      const specRow = page.getByTestId(`file-spec-${RUN}.pdf`);
      await specRow.getByRole("button", { name: "Preview" }).click();
      await expect(page.getByTestId("pdf-status")).toContainText("Page 1 of 3", { timeout: 30_000 });
      await expect(specRow.getByRole("button", { name: "Download original" })).toHaveCount(role.originals ? 1 : 0);
      await expect(specRow.getByRole("button", { name: "New version" })).toHaveCount(role.originals ? 1 : 0);
      if (!role.originals) await expect(page.getByRole("form", { name: "Upload engineering file" })).toHaveCount(0);
      await signOut(page);
    });
  }

  test("client admin cannot manage operator staff but manages own users", async ({ page }) => {
    await signIn(page, "admin@client.demo");
    await page.getByRole("link", { name: "Users", exact: true }).click();
    const staff = page.getByRole("row", { name: /engineer@operator\.demo/ });
    await expect(staff).toContainText("Platform operator staff · managed by the operator");
    await expect(page.getByLabel("Role of engineer@operator.demo")).toHaveCount(0);
    await expect(staff.getByRole("button", { name: /Deactivate|Reactivate/ })).toHaveCount(0);

    // Client admins invite (W2); the colleague accepts the link in their own browser session
    const email = `colleague-${RUN}@client.demo`;
    const form = page.getByRole("form", { name: "Invite user" });
    await form.getByLabel("Email").fill(email);
    await form.getByLabel("Role").selectOption("client_user");
    await form.getByRole("button", { name: "Send invitation" }).click();
    await expect(page.getByRole("status")).toContainText(`Invitation sent to ${email}`);
    const link = await page.getByLabel("Invitation link").inputValue();
    const invitee = await (await page.context().browser()!.newContext()).newPage();
    await invitee.goto(link);
    await invitee.getByLabel("Password", { exact: true }).fill(`Colleague-${RUN}-Pass!`);
    await invitee.getByLabel("Confirm password").fill(`Colleague-${RUN}-Pass!`);
    await invitee.getByRole("button", { name: "Accept invitation" }).click();
    await expect(invitee.getByRole("status")).toContainText("You have joined Demo Client Energy");
    await invitee.close();

    await page.reload();
    const members = page.locator("section.card", { has: page.getByRole("heading", { name: "Members" }) });
    await page.getByLabel(`Role of ${email}`).selectOption("client_engineer");
    await expect(page.getByLabel(`Role of ${email}`)).toHaveValue("client_engineer");
    await members.getByRole("row", { name: new RegExp(email) }).getByRole("button", { name: "Deactivate" }).click();
    await expect(members.getByRole("row", { name: new RegExp(email) })).toContainText("Inactive");

    // Inviting an operator staff address looks exactly like any other invitation (no account enumeration)
    await form.getByLabel("Email").fill("admin@operator.demo");
    await form.getByRole("button", { name: "Send invitation" }).click();
    await expect(page.getByRole("status")).toContainText("Invitation sent to admin@operator.demo");
    await page.screenshot({ path: path.join(SHOTS, "w1-05-client-admin-users.png"), fullPage: true });
    await signOut(page);
  });

  test("another client organisation cannot open the passport or its viewers", async ({ page }) => {
    await signIn(page, OTHER.admin, OTHER.password);
    await page.goto(state.passportUrl);
    await expect(page.getByRole("alert")).toContainText(/not found/i);
    await expect(page.getByTestId("viewer-stats")).toHaveCount(0);
    await expect(page.getByTestId("pdf-canvas")).toHaveCount(0);
  });
});
