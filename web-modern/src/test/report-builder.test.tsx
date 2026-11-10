/** CN-005 Report Builder: template choice, client-visibility rules, attachment order and the preview request. */
import type { EngineeringFile } from "@passport/api-types";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ can: () => true, session: { membership: { role: "operator_engineer" } } }), useSessionKey: () => "s",
}));

import ReportsTab, { eligible, insertByClass, move } from "../components/passport/ReportsTab";

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

const pdf = (id: string, title: string, category: string, visible: boolean, versions = 1) => ({
  id, title, kind: "pdf", category, client_visible: visible, latest_version: { version_number: versions, page_count: 2 },
}) as unknown as EngineeringFile;
const FILES = [pdf("a", "Synthetic drawing", "drawing", true), pdf("b", "Synthetic QC report", "inspection", false, 2),
  pdf("c", "Synthetic lab report", "lab_test", false)];

describe("builder rules", () => {
  it("lets client-facing reports use only documents released to the client", () => {
    expect(eligible(FILES, "client").map((d) => d.allowed)).toEqual([true, false, false]);
    expect(eligible(FILES, "client")[1].reason).toBe("Not released to the client");
    expect(eligible(FILES, "internal").every((d) => d.allowed)).toBe(true);
  });
  it("puts the drawing first, then the QA / inspection report, then other documents", () => {
    const cat: Record<string, string> = { lab: "lab_test", qa: "inspection", dwg: "drawing", mtc: "mat_cert" };
    let picks: { file: string }[] = [];
    for (const file of ["lab", "qa", "mtc", "dwg"]) picks = insertByClass(picks, { file }, (id) => cat[id]);
    expect(picks.map((p) => p.file)).toEqual(["dwg", "qa", "lab", "mtc"]);
  });

  it("reorders attachments", () => {
    expect(move([1, 2, 3], 2, -1)).toEqual([1, 3, 2]);
    expect(move([1, 2, 3], 0, -1)).toEqual([1, 2, 3]);
  });
});

describe("report builder", () => {
  it("previews the complete PDF with the chosen template, order and pinned versions", async () => {
    const posts: [string, unknown][] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (init?.method === "POST") {
        posts.push([String(input), JSON.parse(String(init.body))]);
        return new Response(new Blob(["%PDF-1.4"], { type: "application/pdf" }), { status: 200 });
      }
      return new Response("[]", { status: 200 });
    });
    URL.createObjectURL = vi.fn(() => "blob:preview");
    URL.revokeObjectURL = vi.fn();
    render(<ReportsTab passportId="p1" partId="part1" revisions={[{ revision_number: 1, status: "draft" }] as never} files={FILES} />);
    expect(screen.getByLabelText(/Manufacturing & Test Specification/)).toBeChecked();
    // Standard (client-facing): unreleased documents cannot be selected
    fireEvent.click(screen.getByLabelText(/Standard Digital Passport/));
    expect(screen.getByLabelText("Include Synthetic QC report")).toBeDisabled();
    fireEvent.click(screen.getByLabelText(/Manufacturing & Test Specification/));
    fireEvent.click(screen.getByLabelText("Include Synthetic drawing"));
    fireEvent.click(screen.getByLabelText("Include Synthetic QC report"));
    fireEvent.click(screen.getByLabelText("Include Synthetic lab report"));
    const order = screen.getByRole("list", { name: "Attachment order" });
    const items = within(order).getAllByRole("listitem").map((li) => li.textContent ?? "");
    expect(items[0]).toContain("1. Synthetic drawing");
    expect(items[1]).toContain("2. Synthetic QC report");
    expect(items[2]).toContain("3. Synthetic lab report");
    fireEvent.click(screen.getByLabelText("Move Synthetic lab report up"));
    fireEvent.change(screen.getByLabelText("Version of Synthetic QC report"), { target: { value: "1" } });
    fireEvent.click(screen.getByLabelText("Exclude Synthetic drawing"));
    fireEvent.click(screen.getByRole("button", { name: "Preview complete PDF" }));
    await waitFor(() => expect(screen.getByTitle("Assembled report preview")).toBeInTheDocument());
    expect(posts[0][0]).toMatch(/\/passports\/p1\/reports\/preview\/$/);
    expect(posts[0][1]).toEqual({ template: "mts", revision: 1, attachments: [{ file: "c", version: 1 }, { file: "b", version: 1 }] });
  });

  it("clears the upload form after a supporting document is uploaded", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () => new Response("[]", { status: 200 }));
    const sent: FormData[] = [];
    class FakeXhr {
      status = 201; responseText = '{"id":"new"}'; upload = {}; onload: () => void = () => {};
      open() {} setRequestHeader() {}
      send(form: FormData) { sent.push(form); queueMicrotask(() => this.onload()); }
    }
    vi.stubGlobal("XMLHttpRequest", FakeXhr);
    const onFilesChanged = vi.fn();
    render(<ReportsTab passportId="p1" partId="part1" revisions={[{ revision_number: 1, status: "draft" }] as never} files={FILES}
      onFilesChanged={onFilesChanged} />);
    const group = screen.getByRole("group", { name: "Upload supporting document" });
    const fileInput = within(group).getByLabelText("PDF document") as HTMLInputElement;
    fireEvent.change(fileInput, { target: { files: [new File(["%PDF-1.4"], "qa.pdf", { type: "application/pdf" })] } });
    fireEvent.change(within(group).getByLabelText("Document class"), { target: { value: "inspection" } });
    fireEvent.change(within(group).getByLabelText("Title (optional)"), { target: { value: "Final QA" } });
    fireEvent.click(within(group).getByRole("button", { name: "Upload document" }));
    await waitFor(() => expect(onFilesChanged).toHaveBeenCalled());
    expect(sent[0].get("category")).toBe("inspection");
    expect(within(group).getByRole("status")).toHaveTextContent("Final QA uploaded (Aries only).");
    expect((within(group).getByLabelText("PDF document") as HTMLInputElement).files?.length ?? 0).toBe(0);
    expect(within(group).getByLabelText("Document class")).toHaveValue("lab_test");
    expect(within(group).getByLabelText("Title (optional)")).toHaveValue("");
    expect(within(group).getByRole("button", { name: "Upload document" })).toBeDisabled();
  });
});
