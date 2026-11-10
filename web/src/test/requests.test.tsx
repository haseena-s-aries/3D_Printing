/** Request UI rules: enquiry classification shown before submission, consistent status labels, history. */
import type { Part, RequestEvent } from "@passport/api-types";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatusBadge, Timeline, classification } from "../components/requests";

const part = (p: Partial<Part>) => ({ passport_id: "pp", publication_state: "draft", manufacturing_eligibility: "not_eligible", ...p }) as Part;

describe("request classification", () => {
  it("sends parts that are not published and eligible as enquiries, with the reason", () => {
    expect(classification(part({})).kind).toBe("enquiry");
    expect(classification(part({})).text).toMatch(/still being digitised/);
    expect(classification(part({ passport_id: null } as Partial<Part>)).text).toMatch(/does not have a digital passport/);
    expect(classification(part({ publication_state: "published" })).text).toMatch(/not currently eligible/);
    expect(classification(part({ manufacturing_eligibility: "eligible" })).kind).toBe("enquiry"); // eligible but unpublished
    for (const c of [classification(part({})), classification(part({ publication_state: "published" }))]) {
      expect(c.text).toMatch(/not as a manufacturing order/);
      expect(c.text).not.toMatch(/OQ-\d+/); // no internal decision codes for clients
    }
  });

  it("treats only published and eligible parts as manufacturing requests", () => {
    for (const e of ["eligible", "eligible_subject_to_authorisation"]) {
      const c = classification(part({ publication_state: "published", manufacturing_eligibility: e }));
      expect(c.kind).toBe("manufacturing_request");
      expect(c.text).toMatch(/review every request before anything is produced/);
    }
    expect(classification(part({ publication_state: "published", manufacturing_eligibility: "suspended" })).kind).toBe("enquiry");
  });
});

describe("status and history", () => {
  it("labels statuses consistently", () => {
    render(<StatusBadge status="submitted" />);
    expect(screen.getByText("Submitted · awaiting acknowledgement")).toBeInTheDocument();
  });

  it("renders the request history with authors and messages", () => {
    const events = [
      { id: "1", event: "submitted", from_status: "", to_status: "submitted", message: "Need two", author_side: "client", author_name: "Chloe", created_at: "2026-10-16T10:00:00Z" },
      { id: "2", event: "answered", from_status: "acknowledged", to_status: "answered", message: "We will confirm", author_side: "operator", author_name: "Operator team", created_at: "2026-10-16T11:00:00Z" },
    ] as RequestEvent[];
    render(<Timeline events={events} />);
    expect(screen.getByText("Request submitted")).toBeInTheDocument();
    expect(screen.getByText("Reply from the operator team")).toBeInTheDocument();
    expect(screen.getByText("We will confirm")).toBeInTheDocument();
  });
});
