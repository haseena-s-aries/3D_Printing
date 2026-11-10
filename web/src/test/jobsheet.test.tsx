/** CN-004: clients see only a non-confidential progress line on their enquiry (J6); the timeline names the event. */
import type { RequestEvent, ServiceRequest } from "@passport/api-types";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { FIELD_NAME } from "../components/JobSheetPanel";
import { Timeline } from "../components/requests";
import { RequestFacts } from "../pages/RequestDetailPage";

const req = (extra: Partial<ServiceRequest>) => ({
  id: "r1", reference: "MR-2026-00001", kind: "enquiry", status: "acknowledged", priority: "routine", part_number: "IMP-1", part_name: "Impeller",
  services: [], remarks: "", client_reference: "", created_at: "2026-10-26T10:00:00Z", requested_by_email: "c@x.test", events: [], attachments: [],
  material_option: "original", original_material: "CF8M", ...extra,
}) as unknown as ServiceRequest;

describe("client view of job preparation", () => {
  it("shows only the progress statement, never job data", () => {
    render(<MemoryRouter><RequestFacts r={req({ job_progress: "preparing" })} /></MemoryRouter>);
    expect(screen.getByTestId("job-progress").textContent).toMatch(/preparing the manufacturing documentation/);
    expect(screen.getByTestId("job-progress").textContent).toMatch(/not a production order or release/);
    expect(document.body.textContent).not.toMatch(/JS-DRAFT|job number|process parameter/i);
  });
  it("shows nothing when no preparation has started", () => {
    render(<MemoryRouter><RequestFacts r={req({ job_progress: undefined })} /></MemoryRouter>);
    expect(screen.queryByTestId("job-progress")).toBeNull();
  });
  it("labels the timeline event and the job-sheet fields", () => {
    const ev = { id: "e", event: "job_preparation", author_side: "operator", author_name: "Aries", created_at: "2026-10-26T10:00:00Z", message: "" } as unknown as RequestEvent;
    render(<Timeline events={[ev]} />);
    expect(screen.getByText("Manufacturing documentation in preparation")).toBeTruthy();
    expect(FIELD_NAME["quality.ndt"]).toBe("NDT");
  });
});
