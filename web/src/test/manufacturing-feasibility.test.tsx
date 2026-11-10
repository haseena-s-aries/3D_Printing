/** CN-007 Phase 3 manufacturing feasibility panel: three alternatives, preliminary AI view, no approval, review rules. */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const auth = { userId: "u1" };
vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ can: () => true, session: { user: { id: auth.userId }, membership: { role: "operator_engineer" } } }), useSessionKey: () => "s",
}));

import { FeasibilityPanel } from "../components/ManufacturingFeasibility";

afterEach(() => vi.restoreAllMocks());

const ai = (enabled: boolean) => ({ enabled, reason: enabled ? "" : "External AI is switched off.", provider: "gemini",
  models: { lite: "gemini-3.1-flash-lite", flash: "gemini-3.8-flash", pro: "gemini-3.1-pro-preview" }, sent_fields: ["material description"],
  limits: { calls_per_minute: 10, calls_per_day: 200, daily_budget_usd: 1 } });
const ev = (key: string, lbl: string, state: string, value = "", note = "") => ({ key, label: lbl, state,
  state_label: { verified: "Verified", recorded: "Recorded, not verified", mentioned: "Mentioned in description only", missing: "Not held" }[state], value, source: "", note });
const panel = (status: string, status_label: string, extra = {}) => ({ status, status_label, evidence: [ev("drawing", "Engineering drawing", "missing")],
  constraints: [], missing: ["Engineering drawing"], risks: [], next_actions: ["Obtain a drawing"], review: null, ...extra });
const assessment = {
  id: "f1", version: 2, methodology_version: "mf-1", rules_version: "r-1", project: "PILOT-A", passport_number: "", passport_revision_number: null,
  input_hash: "abcdef0123456789", inputs: {}, created_at: "2026-10-27T12:00:00Z", created_by_name: "Engineer One", created_by_id: "u1",
  oem: panel("not_verified", "Identification / availability not verified", { note: "A missing OEM record means availability is unknown." }),
  additive: panel("specialist_assessment", "Specialist engineering assessment required", { rule_status: "specialist_assessment",
    evidence: [ev("dimensions", "Dimensions", "mentioned", "90 mm, 130 mm, 30 mm", "Numbers as written; their roles are not stated.")],
    constraints: [{ code: "material_grey_cast_iron", kind: "review", text: "Grey cast iron is not produced like-for-like by common metal AM processes." }],
    candidate_processes: [], process_basis: "No common AM process produces the stated material like-for-like.",
    ai: { suggested_status: "potentially_suitable", considerations: ["Simple ring geometry."], information_needed: ["Drawing"], rationale: "Ring." } }),
  conventional: panel("insufficient_information", "Insufficient technical information", {
    candidate_methods: [{ method: "casting", label: "Casting", basis: "Grey cast iron is normally cast.", needs: "a pattern" }], method_basis: "From the material only." }),
  constraints: [{ code: "material_grey_cast_iron", kind: "review", text: "Grey cast iron.", applies_to: ["additive"] }],
  missing_information: ["Engineering drawing", "Dimensional tolerances"], next_actions: [], ai_status: "ok", ai_status_label: "AI explanation received",
  ai: { model: "gemini-3.1-flash-lite", model_version: "gemini-3.1-flash-lite", prompt_version: "mf-p", sent: { material_description: "RING" }, removed: [],
    adjustments: [{ alternative: "additive", kind: "rule_status_kept", text: "The rule-based status stands." }], confidence: 0.6, uncertainty: "x",
    usage: { prompt_tokens: 900, output_tokens: 700, thinking_tokens: 0, cost_usd: 0.0012, latency_ms: 2000, attempts: 1 } },
  reviews: [], overall_review: null, review_note: "Technical review only: not a formal engineering approval.", inputs_current: true,
  authorisation: { manufacturing_authorised: false, text: "Screening only. No manufacturing authorisation, passport approval, publication or manufacturing eligibility is given or changed (OQ-35, OQ-36)." },
};
const view = (enabled = true, assessments: object[] = [assessment]) => ({ ai: ai(enabled), assessments, inputs_changed: false, review_note: "Technical review only.",
  statuses: { oem: { not_verified: "Identification / availability not verified", identified_confirmation_required: "OEM part identified" },
    manufacturing: { insufficient_information: "Insufficient technical information", specialist_assessment: "Specialist engineering assessment required" } } });

function mockFetch(v: object) {
  const posts: [string, unknown][] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    if (init?.method === "POST") {
      posts.push([String(input), JSON.parse(String(init.body))]);
      if (String(input).includes("/reviews/")) return new Response(JSON.stringify({ ...v, review: {} }), { status: 201 });
      return new Response(JSON.stringify({ reused: true, assessment }), { status: 200 });
    }
    return new Response(JSON.stringify(v), { status: 200 });
  });
  return posts;
}

describe("manufacturing feasibility panel", () => {
  it("shows three preliminary panels with evidence, gaps and the no-authorisation notice", async () => {
    mockFetch(view());
    render(<FeasibilityPanel partId="p1" />);
    const oem = await screen.findByTestId("feasibility-oem");
    expect(oem).toHaveTextContent("Identification / availability not verified");
    const am = screen.getByTestId("feasibility-additive");
    expect(am).toHaveTextContent("Specialist engineering assessment required");
    expect(am).toHaveTextContent("Mentioned in description only");
    expect(am).toHaveTextContent("90 mm, 130 mm, 30 mm");
    expect(within(am).getByText("AI view · preliminary, not verified")).toBeInTheDocument();
    expect(screen.getByTestId("feasibility-conventional")).toHaveTextContent("Casting: Grey cast iron is normally cast.");
    expect(screen.getByRole("note")).toHaveTextContent("No manufacturing authorisation");
    expect(screen.getByLabelText("Missing technical information")).toHaveTextContent("Dimensional tolerances");
    expect(screen.getAllByText("Not reviewed").length).toBeGreaterThanOrEqual(3);
    // no cost, saving or approval action anywhere
    expect(screen.queryByRole("button", { name: /approve|release|publish/i })).toBeNull();
    for (const alt of ["oem", "additive", "conventional"]) expect(screen.getByTestId(`feasibility-${alt}`).textContent).not.toMatch(/[$€£]|USD|AED|saving/i);
  });

  it("runs rules only without AI, and offers AI tiers only when permitted", async () => {
    const posts = mockFetch(view(false, []));
    render(<FeasibilityPanel partId="p1" />);
    await screen.findByText("No feasibility assessment yet.");
    expect(screen.queryByRole("button", { name: /With AI view/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Run assessment (rules)" }));
    await waitFor(() => expect(posts.length).toBe(1));
    expect(posts[0][0]).toMatch(/\/parts\/p1\/feasibility\/assess\/$/);
    expect(posts[0][1]).toEqual({ tier: null });
  });

  it("does not let the engineer who ran it confirm, and posts a technical review", async () => {
    const posts = mockFetch(view());
    render(<FeasibilityPanel partId="p1" />);
    await screen.findByLabelText("Review decision");
    const confirm = screen.getByRole("option", { name: /Confirm \(technical review\) \(not for your own run\)/ }) as HTMLOptionElement;
    expect(confirm.disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: /With AI view/ }));
    await waitFor(() => expect(posts.length).toBe(1));
    expect(posts[0][1]).toEqual({ tier: "lite" });
    fireEvent.change(screen.getByLabelText("Technical findings"), { target: { value: "Need drawing and roles of 90/130/30 mm." } });
    fireEvent.change(screen.getByLabelText("Evidence reference"), { target: { value: "Site visit note 1" } });
    fireEvent.click(screen.getByRole("button", { name: "Record review" }));
    await waitFor(() => expect(posts.length).toBe(2));
    expect(posts[1][0]).toMatch(/\/parts\/p1\/feasibility\/f1\/reviews\/$/);
    expect(posts[1][1]).toEqual({ alternative: "overall", decision: "more_information_required", corrected_status: "",
      findings: "Need drawing and roles of 90/130/30 mm.", evidence_references: [{ reference: "Site visit note 1" }] });
  });

  it("lets an independent engineer choose confirmation", async () => {
    auth.userId = "u2";
    mockFetch(view());
    render(<FeasibilityPanel partId="p1" />);
    await screen.findByLabelText("Review decision");
    expect((screen.getByRole("option", { name: "Confirm (technical review)" }) as HTMLOptionElement).disabled).toBe(false);
    auth.userId = "u1";
  });
});
