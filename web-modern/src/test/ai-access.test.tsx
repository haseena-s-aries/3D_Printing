/** CN-007 client-safe result view: suitability is never shown as approval (never green), prices appear only when released
 *  to the role, and the disclosure statement is always present. */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SharedResultView, type Snapshot } from "../components/ClientSharing";

const snap: Snapshot = {
  part_number: "990100000104", part_name: "RING,WEAR", summary: "No qualified route yet; a drawing is needed.",
  outcome: { code: "no_qualified_recommendation", label: "No qualified recommendation — additional engineering review required" },
  options: {
    oem: { title: "OEM procurement", technical_status: "Identification / availability not verified", suitability: "not_qualified",
      suitability_label: "Not technically qualified at present", requirements: [{ label: "OEM identity and part number verified", met: false }] },
    additive: { title: "Additive manufacturing", technical_status: "Potentially suitable", suitability: "potentially_suitable",
      suitability_label: "Potentially suitable — requires engineering qualification", requirements: [{ label: "No verified disqualifying constraint", met: true }] },
    conventional: { title: "Conventional manufacturing", technical_status: "Not suitable", suitability: "excluded",
      suitability_label: "Excluded by a verified technical constraint", requirements: [] },
  },
  evidence_gaps: ["Engineering drawing"], recommendation_version: 6, feasibility_version: 6, cost_comparison_version: 5,
  assessed_on: "2026-10-28", statement: "Information shared by Aries Engineering for your planning. It is not an engineering approval.",
};
const price = { option: "oem", option_title: "OEM procurement", amount: "1450.50", currency: "USD", lead_time_days: 28, valid_until: null,
  quote_reference: "SYN-QUOTE-001" };

describe("client-safe shared result", () => {
  it("never shows a suitability or requirement as approved (no green badges)", () => {
    const { container } = render(<SharedResultView snapshot={snap} />);
    expect(container.querySelector(".badge-success")).toBeNull();
    const additive = screen.getByRole("region", { name: "Additive manufacturing" });
    expect(within(additive).getByText("Potentially suitable — requires engineering qualification")).toHaveClass("badge-info");
    expect(within(screen.getByRole("list", { name: "OEM procurement: mandatory requirements" })).getByText("not met")).toBeInTheDocument();
    expect(screen.getByText(/not an engineering approval/)).toBeInTheDocument();
  });

  it("shows released prices only when given, and says when the role hides them", () => {
    const { rerender } = render(<SharedResultView snapshot={snap} prices={[price]} />);
    expect(screen.getByRole("table", { name: "Released quoted prices" })).toHaveTextContent("SYN-QUOTE-001");
    rerender(<SharedResultView snapshot={snap} pricesHidden />);
    expect(screen.queryByRole("table", { name: "Released quoted prices" })).toBeNull();
    expect(screen.getByText(/your role does not show prices/)).toBeInTheDocument();
  });
});
