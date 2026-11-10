/** Shared end-to-end helpers: sign-in, uploads, the CAD worker and synthetic test documents. */
import { expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";

export const ROOT = path.resolve(__dirname, "..");
export const BACKEND = path.join(ROOT, "backend");
// Portable venv path (Windows developer machines and Linux CI)
export const PYTHON = path.join(BACKEND, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
export const PASSWORD = process.env.DEMO_PASSWORD ?? "Demo-Passport-2026!";
export const STEP_FILE = path.join(BACKEND, "tests", "fixtures", "sleeve_d45_h40_5_synthetic.stp");
export const SHOTS = path.join(__dirname, "results", "screenshots");
fs.mkdirSync(SHOTS, { recursive: true });

export async function signIn(page: Page, email: string, password = PASSWORD, tenant?: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  if (tenant) {
    await page.getByLabel(/Organisation/).selectOption(tenant);
    await page.getByRole("button", { name: "Sign in" }).click();
  }
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}

export async function signOut(page: Page) {
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("button", { name: "Sign in" })).toBeVisible();
}

export async function uploadFile(page: Page, file: string, section: string) {
  const form = page.getByRole("form", { name: "Upload engineering file" });
  await form.locator('input[type="file"]').setInputFiles(file);
  await form.getByLabel("Section").selectOption(section);
  await form.getByRole("button", { name: "Upload" }).click();
}

/** Open a client organisation by name on the operator's Clients page. The shared demo database keeps every run's
 *  clients, so the list can span several pages: wait for it to settle, then page forward until the name appears. */
export async function openClient(page: Page, name: string) {
  const button = page.getByRole("button", { name, exact: true });
  // A client that was just created opens automatically; only otherwise look it up in the paged list.
  const opened = page.getByRole("heading", { name: `Members of ${name}` });
  if (await opened.waitFor({ timeout: 5000 }).then(() => true, () => false)) return;
  const pager = page.getByText(/Page \d+ of \d+/);
  await page.reload(); // the list must include the client created a moment ago
  await page.waitForLoadState("networkidle");
  await expect(pager.or(button).first()).toBeVisible();
  for (let i = 0; i < 50 && !(await button.isVisible()); i++) {
    const text = (await pager.textContent()) ?? "";
    const [, current, last] = text.match(/Page (\d+) of (\d+)/) ?? [];
    if (!current || Number(current) >= Number(last)) break;
    await page.getByRole("button", { name: "Next" }).click();
    await expect(pager).not.toHaveText(text);
    await page.waitForLoadState("networkidle");
  }
  await button.click();
}

export function runWorker() {
  // The worker logs in as the app_worker role (cross-tenant queue policy, tenant-scoped data access).
  const env = fs.readFileSync(path.join(BACKEND, ".env"), "utf8");
  const url = /^DATABASE_URL=(.*)$/m.exec(env)![1].replace("app_user:app_user@", "app_worker:app_worker@");
  return execFileSync(PYTHON, [path.join(BACKEND, "manage.py"), "run_worker", "--drain"], {
    env: { ...process.env, DATABASE_URL: url, WORKER_DB_ROLE: "" },
    encoding: "utf8",
  });
}

/** A real PNG (RGB gradient with a simple part outline) encoded with zlib; synthetic test photograph. */
export function makePng(width = 320, height = 240): Buffer {
  const crcTable = Array.from({ length: 256 }, (_, n) => {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    return c >>> 0;
  });
  const crc = (buf: Buffer) => {
    let c = 0xffffffff;
    for (const b of buf) c = crcTable[(c ^ b) & 0xff] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  };
  const chunk = (type: string, data: Buffer) => {
    const len = Buffer.alloc(4);
    len.writeUInt32BE(data.length);
    const td = Buffer.concat([Buffer.from(type, "ascii"), data]);
    const c = Buffer.alloc(4);
    c.writeUInt32BE(crc(td));
    return Buffer.concat([len, td, c]);
  };
  const rows: Buffer[] = [];
  const cx = width / 2, cy = height / 2;
  for (let y = 0; y < height; y++) {
    const row = Buffer.alloc(1 + width * 3);
    for (let x = 0; x < width; x++) {
      const r = Math.hypot(x - cx, y - cy);
      const ring = r > 40 && r < 90; // a ring, like a sleeve seen from above
      row[1 + x * 3] = ring ? 150 : 225 - Math.round((y / height) * 40);
      row[2 + x * 3] = ring ? 160 : 230 - Math.round((x / width) * 30);
      row[3 + x * 3] = ring ? 175 : 238;
    }
    rows.push(row);
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8; ihdr[9] = 2; // 8-bit RGB
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr), chunk("IDAT", zlib.deflateSync(Buffer.concat(rows))), chunk("IEND", Buffer.alloc(0)),
  ]);
}

/** A valid multi-page PDF (correct xref table) with "Page N" on each page; synthetic, no customer data. */
export function makePdf(pages: number, label = "Test document"): Buffer {
  const objects: string[] = [];
  const kids = Array.from({ length: pages }, (_, i) => `${4 + i * 2} 0 R`).join(" ");
  objects.push("<</Type/Catalog/Pages 2 0 R>>");
  objects.push(`<</Type/Pages/Kids[${kids}]/Count ${pages}>>`);
  objects.push("<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>");
  for (let i = 0; i < pages; i++) {
    const text = `BT /F1 18 Tf 40 700 Td (${label} - Page ${i + 1}) Tj ET`;
    objects.push(`<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Resources<</Font<</F1 3 0 R>>>>/Contents ${5 + i * 2} 0 R>>`);
    objects.push(`<</Length ${text.length}>>stream\n${text}\nendstream`);
  }
  let out = "%PDF-1.4\n";
  const offsets: number[] = [];
  objects.forEach((body, i) => {
    offsets.push(Buffer.byteLength(out));
    out += `${i + 1} 0 obj\n${body}\nendobj\n`;
  });
  const xref = Buffer.byteLength(out);
  out += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  out += offsets.map((o) => `${String(o).padStart(10, "0")} 00000 n \n`).join("");
  out += `trailer\n<</Size ${objects.length + 1}/Root 1 0 R>>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(out, "latin1");
}

/** Fill the shared company profile on Clients -> New client organisation with synthetic values (the specs add the
 * Client Administrator themselves, so the contact invitation is switched off). */
export async function fillNewClient(page: Page, name: string, slug: string) {
  const form = page.getByRole("form", { name: "New client organisation" });
  const values: [string, string][] = [
    ["Registered company name", name], ["Trade licence number", `TL-${slug}`], ["Trade licence issuing authority", "Synthetic Authority"],
    ["Country", "United Arab Emirates"], ["Emirate / state", "Dubai"], ["Location / address", "Synthetic address 1"],
    ["Primary contact name", "Synthetic Contact"], ["Contact designation", "Manager"], ["Email address", `contact@${slug}.test`],
    ["Phone number", "+971 4 000 0000"],
  ];
  for (const [label, value] of values) await form.getByLabel(label, { exact: true }).fill(value);
  await form.getByLabel("Short identifier").fill(slug);
  await form.getByLabel(/Email the primary contact an invitation/).uncheck();
}
