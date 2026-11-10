/** CN-007 Phase 4 cost & lead-time comparison panel: three options, source labels, technical labels, what-if previews. */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ can: () => true, session: { user: { id: "u1" }, membership: { role: "operator_engineer" } } }), useSessionKey: () => "s",
}));

import { CostComparisonPanel } from "../components/CostComparison";
import { ApiError } from "../api/client";
import fixture from "./fixtures/cost-comparison.json";

afterEach(() => vi.restoreAllMocks());

const ai = { enabled: false, reason: "External AI is switched off.", provider: "", models: { lite: "gemini-3.1-flash-lite" }, sent_fields: [],
  limits: { calls_per_minute: 10, calls_per_day: 200, daily_budget_usd: 1 } };
const comparison = { id: "c1", version: 1, name: "SYNTHETIC TEST", synthetic: true, method_version: "cost-method-1", quantity: 3, reporting_currency: "USD",
  as_of: "2026-10-27", feasibility_version: 2, feasibility_superseded: false, project: "PILOT-A", passport_number: "", derived_from_version: null,
  inputs: fixture.scenario, technical: fixture.technical, results: fixture.results, ai_status: "none", ai_status_label: "No AI notes", ai: {},
  created_at: "2026-10-27T12:00:00Z", created_by_name: "Engineer One", input_hash: "x" };
const labels = { sources: { quotation: "Verified supplier quotation", historical: "Historical purchase/manufacturing cost", engineering_estimate: "Engineering estimate",
  ai_estimate: "AI-assisted preliminary estimate", missing: "Missing / unavailable" },
  costs: { unit_cost: "Unit purchase / manufacturing cost", post_processing: "Post-processing", engineering_setup: "Engineering and setup", tooling: "Tooling",
    testing_qualification: "Testing and qualification", logistics: "Packaging and logistics" },
  lead: { supplier_days: "Supplier / manufacturer lead time", engineering_days: "Additional engineering / qualification time" }, categories: {}, alternatives: {} };
const view = (comparisons: object[] = [comparison], feasibility: object | null = { id: "f", version: 2, technical: fixture.technical }) => ({
  ai, feasibility, comparisons, template: fixture.scenario, labels, statement: "Comparison only. No procurement recommendation, manufacturing authorisation or release is made." });

function mockFetch(v: object, onPost?: (url: string, body: unknown) => Response) {
  const posts: [string, unknown][] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    if (init?.method === "POST") {
      const body = JSON.parse(String(init.body));
      posts.push([String(input), body]);
      if (onPost) return onPost(String(input), body);
      if (String(input).includes("/calculate/")) return new Response(JSON.stringify({ results: { ...fixture.results, quantity: Number(body.scenario.quantity) }, stored: false }), { status: 200 });
      return new Response(JSON.stringify({ reused: false, comparison: { ...comparison, version: 2 } }), { status: 201 });
    }
    return new Response(JSON.stringify(v), { status: 200 });
  });
  return posts;
}

describe("cost and lead-time comparison panel", () => {
  it("shows the three options with source labels, technical labels, totals, savings and missing inputs", async () => {
    mockFetch(view());
    render(<CostComparisonPanel partId="p1" />);
    const oem = await screen.findByTestId("cost-oem");
    expect(within(oem).getByTestId("total-oem")).toHaveTextContent("USD 635.25");
    expect(oem).toHaveTextContent("Verified supplier quotation");
    expect(oem).toHaveTextContent("Not verified: OEM identity / availability");
    expect(oem).toHaveTextContent("5 ordered (MOQ 5)");
    const am = screen.getByTestId("cost-additive");
    expect(am).toHaveTextContent("Not technically qualified: specialist engineering assessment required");
    expect(am).toHaveTextContent("Engineering estimate");
    expect(screen.getByTestId("savings-additive")).toHaveTextContent("Costs USD 704.75 (110.9% higher)");
    expect(screen.getByTestId("savings-additive")).toHaveTextContent("provisional: not technically qualified");
    expect(screen.getByTestId("lead-additive")).toHaveTextContent("28 days");
    const cv = screen.getByTestId("cost-conventional");
    expect(within(cv).getByTestId("total-conventional")).toHaveTextContent("Incomplete");
    expect(within(cv).getByLabelText(/missing inputs/)).toHaveTextContent("Testing and qualification");
    expect(screen.getByTestId("savings-conventional")).toHaveTextContent("Totals incomplete");
    expect(screen.getByText(/Synthetic test data: not real prices/)).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("No procurement recommendation");
    expect(screen.queryByRole("button", { name: /recommend|approve|release|order/i })).toBeNull();
  });

  it("recalculates a what-if quantity without saving, then saves it as a new linked version", async () => {
    const posts = mockFetch(view());
    render(<CostComparisonPanel partId="p1" />);
    fireEvent.change(await screen.findByLabelText("What-if quantity"), { target: { value: "12" } });
    fireEvent.click(screen.getByRole("button", { name: "Recalculate (not saved)" }));
    await screen.findByTestId("cost-preview");
    expect(posts[0][0]).toMatch(/\/parts\/p1\/cost-comparisons\/calculate\/$/);
    expect((posts[0][1] as { scenario: { quantity: string } }).scenario.quantity).toBe("12");
    expect(screen.getByTestId("cost-preview")).toHaveTextContent("Preview, not saved: 12 required");
    fireEvent.click(screen.getByRole("button", { name: "Save as new version" }));
    await waitFor(() => expect(posts.length).toBe(2));
    expect(posts[1][0]).toMatch(/\/parts\/p1\/cost-comparisons\/$/);
    expect(posts[1][1]).toMatchObject({ tier: null, derived_from: "c1" });
  });

  it("needs a feasibility assessment first", async () => {
    mockFetch(view([], null));
    render(<CostComparisonPanel partId="p1" />);
    expect(await screen.findByText(/Run the manufacturing feasibility assessment first/)).toBeInTheDocument();
  });

  it("shows field-level validation errors from the server", async () => {
    mockFetch(view([]), () => new Response(JSON.stringify({ error: { code: "invalid_cost_inputs", message: "Some inputs are invalid.",
      details: { errors: [{ field: "alternatives.oem.costs.unit_cost.amount", message: "Must be greater than zero." }] } } }), { status: 400 }));
    render(<CostComparisonPanel partId="p1" />);
    fireEvent.change(await screen.findByLabelText("A. OEM procurement Unit purchase / manufacturing cost amount"), { target: { value: "0" } });
    fireEvent.click(screen.getByRole("button", { name: "Save version" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("alternatives.oem.costs.unit_cost.amount: Must be greater than zero.");
    expect(ApiError).toBeDefined();
  });
});

describe("cost comparison: calculation steps and stored AI notes", () => {
  it("shows the arithmetic behind each total and flags a stored AI note that contradicts the technical status", async () => {
    const flagged = { ...comparison, ai_consistency: [{ alternative: "conventional", recorded: "insufficient_information", stated: "specialist_assessment",
      sentence: "Technical status for additive and conventional methods requires specialist engineering assessment." }] };
    mockFetch(view([flagged]));
    render(<CostComparisonPanel partId="p1" />);
    expect(within(await screen.findByTestId("cost-oem")).getByLabelText(/calculation/)).toHaveTextContent(
      "Total: 550.00 + 55.00 + 30.25 = 635.25 USD");
    expect(screen.getByTestId("ai-consistency")).toHaveTextContent("recorded insufficient information");
  });
});
