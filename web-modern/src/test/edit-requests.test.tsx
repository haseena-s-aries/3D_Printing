/** CN-006 web: status labels, the original-versus-proposed comparison and decision buttons driven by allowed_actions. */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { show } from "../components/EditRequestDialog";
import { EDIT_STATUS, EditRequestDetailPage } from "../pages/EditRequestsPage";

afterEach(() => vi.restoreAllMocks());

const er = (extra: Record<string, unknown> = {}) => ({
  id: "e1", reference: "ER-2026-00001", target_type: "part", part: "p1", part_number: "IMP-1", part_name: "Impeller", project: "EX-P1 · Pumps",
  passport: null, passport_number: "", base_revision_number: null, base_revision_status: "", data_class: "aries_master",
  data_class_label: "Aries-controlled master data", status: "submitted", status_label: "Submitted", reason: "Nameplate shows a different model.",
  evidence_files: [], requester: "Client Engineer", requester_role: "client_engineer", requester_role_label: "Client Engineer", requester_side: "client",
  created_at: "2026-10-26T10:00:00Z", submitted_at: "2026-10-26T10:00:00Z", reviewer_name: "", decision_reason: "", decided_at: null, applied_at: null,
  applied_revision_number: null, application_result: "",
  changes: [{ field: "equipment_model", label: "Equipment model", original: "P-100", proposed: "P-200", current: "P-150", drifted: true }],
  events: [{ action: "submitted", from_status: "draft", to_status: "submitted", note: "", side: "client", user: "Client Engineer", created_at: "2026-10-26T10:00:00Z" }],
  allowed_actions: ["start_review", "approve", "reject", "request_corrections"], ...extra,
});

const renderAt = () => render(
  <MemoryRouter initialEntries={["/edit-requests/e1"]}><Routes><Route path="/edit-requests/:id" element={<EditRequestDetailPage />} /></Routes></MemoryRouter>,
);

describe("edit request labels", () => {
  it("uses the agreed status names", () => {
    expect(Object.values(EDIT_STATUS).map(([t]) => t)).toEqual(expect.arrayContaining([
      "Draft", "Submitted", "Under Review", "Corrections Requested", "Approved", "Rejected", "Applied", "Conflict / Revalidation Required"]));
    expect(show(null)).toBe("—");
    expect(show(true)).toBe("Yes");
  });
});

describe("edit request detail", () => {
  it("compares original, proposed and current, flags drift and keeps edit approval separate from release", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(er()), { status: 200 }));
    renderAt();
    expect(await screen.findByText("P-200")).toBeInTheDocument();
    expect(screen.getByText("P-100")).toBeInTheDocument();
    expect(screen.getByText("Changed since request")).toBeInTheDocument();
    expect(document.body.textContent).toMatch(/not engineering verification/);
    expect(screen.getByRole("button", { name: "Reject with reason" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Withdraw" })).toBeNull();
  });

  it("requires a note to request corrections and posts it", async () => {
    const posts: [string, unknown][] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (init?.method === "POST") {
        posts.push([String(input), JSON.parse(String(init.body))]);
        return new Response(JSON.stringify(er({ status: "corrections_requested", decision_reason: "Attach the nameplate photo.", allowed_actions: [] })), { status: 200 });
      }
      return new Response(JSON.stringify(er()), { status: 200 });
    });
    renderAt();
    const btn = await screen.findByRole("button", { name: "Request corrections" });
    expect(btn).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Reviewer note"), { target: { value: "Attach the nameplate photo." } });
    fireEvent.click(btn);
    await waitFor(() => expect(screen.getByText("Corrections Requested")).toBeInTheDocument());
    expect(posts[0][0]).toMatch(/\/edit-requests\/e1\/request-corrections\/$/);
    expect(posts[0][1]).toEqual({ note: "Attach the nameplate photo." });
  });

  it("offers revalidation to the requester when the target changed", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(er({
      status: "conflict", application_result: "Equipment model changed since the request.", allowed_actions: ["withdraw", "rebase"] })), { status: 200 }));
    renderAt();
    expect(await screen.findByText("Conflict / Revalidation Required")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Revalidate and resubmit" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
  });
});
