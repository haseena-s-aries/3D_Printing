/** CN-007 web: import preview, mapping notes, explicit confirmation and data-quality flags. */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { FlagChips, InventoryImportDetailPage } from "../pages/InventoryImportPage";

afterEach(() => vi.restoreAllMocks());

const OPTIONS = {
  targets: [
    { field: "part_number", label: "Customer material number", required: true, max_length: 80, note: "Identity" },
    { field: "manufacturer_reference", label: "Manufacturer reference", required: false, max_length: 60, note: "Customer/ERP manufacturer code. Never treated as an OEM part number." },
    { field: "oem_part_number", label: "OEM part number", required: false, max_length: 80, note: "" },
    { field: "customer_abc_class", label: "Customer ABC indicator", required: false, max_length: 20, note: "never sets engineering criticality" },
  ],
  presets: [], max_rows: 20000, max_bytes: 10485760,
  flags: { possible_duplicate: { label: "Same description and manufacturer as another material number", level: "warning" },
    mentions_dimensions: { label: "Description mentions dimensions", level: "info" } },
};
const BATCH = {
  id: "b1", reference: "IMP-2026-00001", status: "preview", status_label: "Preview (nothing imported yet)", file_name: "pilot.xlsx", file_kind: "xlsx",
  file_size: 100, file_sha256: "a".repeat(64), sheet_name: "573 Spare Parts", header_row: 1, headers: ["Material", "Manufacturer Number", "ABC indicator"],
  preset: "sap_material_list", mapping: { part_number: "Material", manufacturer_reference: "Manufacturer Number", customer_abc_class: "ABC indicator" },
  project: null, project_name: "", importer_side: "aries", row_count: 2, counts: { outcomes: { new: 1, unchanged: 1, update: 0, conflict: 0, error: 0 }, flags: {} },
  analysed_at: "2026-10-27T10:00:00Z", apply_updates: false, result: {}, created_at: "2026-10-27T10:00:00Z", created_by_name: "Eng One", committed_at: null, committed_by_name: "",
};
const ROWS = { count: 2, results: [
  { id: "r1", row_number: 2, source: { Material: "990100000103", "Manufacturer Number": "29990103", "ABC indicator": "D" },
    values: { part_number: "990100000103", name: "INSERT,CTNGTL,CRBDE", manufacturer: "SYNTHETIC TOOLING GMBH", manufacturer_reference: "29990103" },
    outcome: "new", outcome_label: "New part", messages: [{ level: "warning", code: "possible_duplicate", text: "Same description as 990100000099." }],
    flags: ["possible_duplicate"], part: null, part_number: "", changes: {}, conflicts: {}, applied: "" },
  { id: "r2", row_number: 3, source: {}, values: { part_number: "990100000104", name: "RING,WEAR,90MM" }, outcome: "unchanged",
    outcome_label: "Already up to date", messages: [], flags: ["mentions_dimensions"], part: "p4", part_number: "990100000104", changes: {}, conflicts: {}, applied: "" },
] };

function mock() {
  const posts: [string, unknown][] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (init?.method === "POST") {
      posts.push([url, JSON.parse(String(init.body))]);
      return new Response(JSON.stringify({ ...BATCH, status: "committed", status_label: "Imported", result: { created: 1, updated: 0, unchanged: 1, skipped: 0 },
        committed_at: "2026-10-27T10:05:00Z", committed_by_name: "Eng One" }), { status: 200 });
    }
    const body = url.includes("/options/") ? OPTIONS : url.includes("/rows/") ? ROWS : url.includes("/projects/") ? { count: 0, results: [] } : BATCH;
    return new Response(JSON.stringify(body), { status: 200 });
  });
  return posts;
}

const renderAt = () => render(
  <MemoryRouter initialEntries={["/inventory-import/b1"]}><Routes><Route path="/inventory-import/:id" element={<InventoryImportDetailPage />} /></Routes></MemoryRouter>,
);

describe("inventory import preview", () => {
  it("states that nothing is imported yet and explains the sensitive mappings", async () => {
    mock();
    renderAt();
    expect(await screen.findByText(/Preview: nothing has been imported yet/)).toBeInTheDocument();
    const mapping = await screen.findByRole("table", { name: "Column mapping" });
    expect(within(mapping).getByText(/Never treated as an OEM part number/)).toBeInTheDocument();
    expect(within(mapping).getByText(/never sets engineering criticality/)).toBeInTheDocument();
    expect(within(mapping).getByLabelText("Column for OEM part number")).toHaveValue("");  // not guessed
    expect(await screen.findByTestId("row-2")).toHaveTextContent("Same description as 990100000099.");
    expect(screen.getByTestId("row-2")).toHaveTextContent("Same description and manufacturer as another material number");
  });

  it("imports only after explicit confirmation", async () => {
    const posts = mock();
    renderAt();
    const button = await screen.findByRole("button", { name: "Import 1 new part" });
    expect(button).toBeDisabled();
    fireEvent.click(screen.getByLabelText(/I reviewed the preview/));
    fireEvent.click(button);
    await waitFor(() => expect(screen.getByText(/1 created/)).toBeInTheDocument());
    expect(posts[0][0]).toMatch(/\/inventory-imports\/b1\/commit\/$/);
    expect(posts[0][1]).toEqual({ confirm: true, apply_updates: false });
  });
});

describe("flag chips", () => {
  it("can show warnings only", () => {
    render(<FlagChips flags={["possible_duplicate", "mentions_dimensions"]} info={OPTIONS.flags} onlyWarnings />);
    expect(screen.getByText(/Same description/)).toBeInTheDocument();
    expect(screen.queryByText(/mentions dimensions/)).toBeNull();
  });
});
