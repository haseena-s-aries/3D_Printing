/** D-13: engineering notes panel. The API decides who receives the notes; the panel shows them verbatim or a generic indicator. */
import type { Revision } from "@passport/api-types";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import EngineeringNotesPanel, { categoryOf, parseNotes } from "../components/passport/EngineeringNotesPanel";
import RevisionsTab from "../components/passport/RevisionsTab";

const NOTES = [
  "ENGINEERING VALIDATION DRAFT - not an approval.",
  "Assessment report: Reports/Example_Report.pdf sha256 0000000000000000",
  "C-01: Material conflict: Grade A feedstock vs Grade B (QC report QC-REF-01). Not resolved.",
  "C-02: Job number conflict: JOB-0001 vs JOB-0002.",
  "C-04: Lab test reports carry no part reference.",
  "C-11: <script>alert('x')</script> & <b>bold?</b>",
].join("\n");

const rev = (over: Partial<Revision> = {}): Revision =>
  ({
    id: "r1", revision_number: 1, status: "draft", content: { notes: NOTES }, change_summary: "Initial draft", editable: true,
    completeness: null, notes_restricted: false, engineering_review_pending: true, created_by_email: "e@x", updated_by_email: "",
    submitted_at: null, approved_at: null, created_at: "2026-10-23T10:00:00Z", updated_at: "2026-10-23T10:00:00Z", ...over,
  }) as unknown as Revision;

// What the API returns to a role without passports.view_engineering_notes: no notes key at all.
const restricted = rev({ content: {}, notes_restricted: true });

describe("engineering notes panel", () => {
  it("shows the detailed notes to roles that received them (authorised response)", () => {
    render(<EngineeringNotesPanel revision={rev()} />);
    const panel = screen.getByRole("region", { name: "Engineering notes" });
    const list = within(panel).getByRole("list");
    expect(within(list).getByText(/Grade A feedstock vs Grade B/)).toBeInTheDocument();
    expect(within(list).getByText(/JOB-0001 vs JOB-0002/)).toBeInTheDocument();
    expect(within(panel).getAllByText("Engineer verification: not recorded", { exact: false }).length).toBeGreaterThan(0);
    expect(panel).toHaveTextContent("Recorded in revision 1 (draft), shown exactly as stored");
  });

  it("shows only the generic indicator to restricted roles", () => {
    const { container } = render(<EngineeringNotesPanel revision={restricted} />);
    expect(screen.getByRole("heading", { name: "Engineering review pending" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Engineering notes" })).toBeNull();
    expect(container.textContent).not.toMatch(/Grade A|JOB-0002|C-01/);
  });

  it("renders nothing when no notes are recorded", () => {
    const { container } = render(<EngineeringNotesPanel revision={rev({ content: {}, engineering_review_pending: false })} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("keeps conflict IDs and text exactly as stored", () => {
    render(<EngineeringNotesPanel revision={rev()} />);
    const items = within(screen.getByRole("list")).getAllByRole("listitem");
    expect(items.map((li) => li.querySelector(".badge")?.textContent)).toEqual(["C-01", "C-02", "C-04", "C-11"]);
    expect(items[1]).toHaveTextContent("Job number conflict: JOB-0001 vs JOB-0002.");
    expect(parseNotes(NOTES).filter((p) => p.kind === "text").map((p) => p.text)).toEqual(NOTES.split("\n").slice(0, 2));
  });

  it("labels known categories only from the line's own leading label", () => {
    expect(categoryOf("Material conflict: Grade A vs Grade B")).toBe("Material");
    expect(categoryOf("Job number conflict: JOB-0001 vs JOB-0002")).toBe("Job reference");
    expect(categoryOf("Dimensional discrepancy: STEP 50.0 mm vs drawing 48 mm")).toBe("Dimensional");
    expect(categoryOf("Date inconsistency: ...")).toBe("Document traceability");
    expect(categoryOf("Lab test reports carry no part reference")).toBeNull(); // unknown: no guessing
    expect(categoryOf("drawings carry no tolerances/material")).toBeNull(); // keyword elsewhere is not a label
    render(<EngineeringNotesPanel revision={rev()} />);
    const items = within(screen.getByRole("list")).getAllByRole("listitem");
    expect(within(items[0]).getByText("Material")).toBeInTheDocument();
    expect(within(items[2]).queryByText(/Material|Job reference|Dimensional/)).toBeNull();
  });

  it("renders HTML and script-like content as plain text", () => {
    const { container } = render(<EngineeringNotesPanel revision={rev()} />);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector(".notes-panel b")).toBeNull();
    expect(screen.getByTestId("notes-verbatim").textContent).toContain("<script>alert('x')</script> & <b>bold?</b>");
  });

  it("retains line breaks in the verbatim notes", () => {
    render(<EngineeringNotesPanel revision={rev()} />);
    const pre = screen.getByTestId("notes-verbatim");
    expect(pre.tagName).toBe("PRE");
    expect(pre.textContent).toBe(NOTES);
  });
});

describe("revision history", () => {
  it("shows the notes field with its line breaks for authorised responses and omits it for restricted ones", () => {
    const { container, unmount } = render(<RevisionsTab revisions={[rev()]} />);
    const dd = [...container.querySelectorAll(".fact-row")].find((r) => r.querySelector("dt")?.textContent === "Notes")?.querySelector("dd");
    expect(dd?.textContent).toBe(NOTES);
    unmount();
    const { container: c2 } = render(<RevisionsTab revisions={[restricted]} />);
    expect(c2.textContent).not.toMatch(/Grade A|JOB-0002/);
  });
});
