/** CN-007 Phase 5 recommendation panel: deterministic outcome, separate statuses, preliminary vs reviewed, review rules. */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const auth = { userId: "u1" };
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ can: () => true, session: { user: { id: auth.userId }, membership: { role: "operator_engineer" } } }), useSessionKey: () => "s",
}));

import { RecommendationPanel } from "../components/Recommendation";
import results from "./fixtures/recommendation.json";

afterEach(() => vi.restoreAllMocks());

const ai = { enabled: true, reason: "", provider: "gemini", models: { lite: "gemini-3.1-flash-lite" }, sent_fields: [],
  limits: { calls_per_minute: 10, calls_per_day: 200, daily_budget_usd: 1 } };
const rec = (over = {}) => ({ id: "r1", version: 1, outcome: "no_qualified_recommendation", recommended_option: "", results, feasibility_version: 5,
  cost_comparison_version: 2, passport_number: "", passport_revision_number: null, ai_status: "none", ai_status_label: "No AI explanation", ai: {},
  ai_consistency: [], created_at: "2026-10-28T09:00:00Z", created_by_name: "Engineer One", created_by_id: "u1", reviews: [],
  review_state: { code: "preliminary", label: "Preliminary: not reviewed", reviewed: false }, stale: [], engineering_approved: false,
  authorisation: "Engineering approval is not available.", ...over });
const view = (recs: object[]) => ({ ai, feasibility: { version: 5 }, cost_comparisons: [{ id: "c2", version: 2, name: "SYNTHETIC", quantity: 3, currency: "USD", synthetic: true }],
  default_weights: { cost: "0.5", lead_time: "0.3", evidence: "0.2" }, recommendations: recs, decisions: {},
  statement: "Preliminary until reviewed. Not an engineering approval, manufacturing authorisation, passport publication or production release (OQ-35, OQ-36)." });

function mockFetch(v: object) {
  const posts: [string, unknown][] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    if (init?.method === "POST") {
      posts.push([String(input), JSON.parse(String(init.body))]);
      if (String(input).includes("/reviews/")) return new Response(JSON.stringify(v), { status: 201 });
      return new Response(JSON.stringify({ reused: false, recommendation: rec({ version: 2 }) }), { status: 201 });
    }
    return new Response(JSON.stringify(v), { status: 200 });
  });
  return posts;
}

describe("recommendation panel", () => {
  it("shows the deterministic outcome, separate statuses and the preliminary state", async () => {
    mockFetch(view([rec()]));
    render(<RecommendationPanel partId="p1" />);
    const outcome = await screen.findByTestId("rec-outcome");
    expect(outcome).toHaveTextContent("No qualified recommendation — additional engineering review required");
    expect(outcome).toHaveTextContent("Preliminary: not reviewed");
    expect(screen.getByTestId("status-cheapest")).toHaveTextContent("not definitive because Conventional manufacturing is incomplete");
    expect(screen.getByTestId("status-suitable")).toHaveTextContent("None: no option meets the mandatory requirements");
    expect(screen.getByTestId("status-approved")).toHaveTextContent("OQ-35, OQ-36");
    const am = screen.getByTestId("rec-additive");
    expect(am).toHaveTextContent("Not technically qualified");
    expect(within(am).getByLabelText(/requirements/)).toHaveTextContent("not met");
    expect(within(screen.getByTestId("rec-conventional")).getByTestId("rec-total-conventional")).toHaveTextContent("Incomplete");
    expect(screen.getByRole("note")).toHaveTextContent("Not an engineering approval");
    expect(screen.queryByRole("button", { name: /approve for manufacture|release|publish|authoris/i })).toBeNull();
  });

  it("generates with the chosen weights and cost comparison, and the generator cannot approve its own version", async () => {
    const posts = mockFetch(view([rec()]));
    render(<RecommendationPanel partId="p1" />);
    fireEvent.change(await screen.findByLabelText("cost weight"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("Cost comparison version"), { target: { value: "c2" } });
    fireEvent.click(screen.getByRole("button", { name: "Generate recommendation" }));
    await waitFor(() => expect(posts.length).toBe(1));
    expect(posts[0][1]).toEqual({ tier: null, weights: { cost: "1", lead_time: "0.3", evidence: "0.2" }, cost_comparison: "c2" });
    expect((screen.getByRole("option", { name: /Approve for further study \(not for your own version\)/ }) as HTMLOptionElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Review findings"), { target: { value: "Need a drawing." } });
    fireEvent.click(screen.getByRole("button", { name: "Record decision" }));
    await waitFor(() => expect(posts.length).toBe(2));
    expect(posts[1][0]).toMatch(/\/parts\/p1\/recommendations\/r1\/reviews\/$/);
    expect(posts[1][1]).toEqual({ decision: "information_requested", option: "", findings: "Need a drawing.", evidence_references: [] });
  });

  it("shows reviewed recommendations as reviewed, and an independent reviewer may approve for further study", async () => {
    auth.userId = "u2";
    const reviewed = rec({ reviews: [{ id: "x", decision: "approved_for_further_study", decision_label: "Approved for further study", option: "conventional",
      option_label: "Conventional manufacturing", findings: "Obtain a drawing.", independent: true, option_eligible: false, reviewer: "Engineer Two",
      created_at: "2026-10-28T10:00:00Z", evidence_references: [] }],
      review_state: { code: "approved_for_further_study", label: "Reviewed: Approved for further study (Conventional manufacturing), Engineer Two (independent)", reviewed: true } });
    mockFetch(view([reviewed]));
    render(<RecommendationPanel partId="p1" />);
    expect(await screen.findByTestId("rec-outcome")).toHaveTextContent("Reviewed: Approved for further study (Conventional manufacturing), Engineer Two (independent)");
    expect(screen.getByLabelText("Review history")).toHaveTextContent("(not technically qualified)");
    fireEvent.change(screen.getByLabelText("Recommendation decision"), { target: { value: "approved_for_further_study" } });
    const opts = within(screen.getByLabelText("Review option")).getAllByRole("option") as HTMLOptionElement[];
    expect(opts.map((o) => o.textContent)).toContain("C. Conventional manufacturing");
    auth.userId = "u1";
  });
});
