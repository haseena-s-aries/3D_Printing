/** CN-007 Phase 2 part intelligence panel: AI optional, suggestions labelled unverified, requests and classification. */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ can: () => true, session: { membership: { role: "operator_engineer" } } }), useSessionKey: () => "s",
}));

import { PartIntelligencePanel } from "../components/PartIntelligence";

afterEach(() => vi.restoreAllMocks());

const analysis = {
  rules_version: "rules-test", description: { as_supplied: "RING,WEAR,95MM", expanded: ["ring", "wear", "95MM"], unknown_tokens: [] },
  classification: { family: "Wear ring", category: "mechanical", assembly: false, basis: "noun and qualifiers", recorded_category: "unknown" },
  mentions: { dimensions: [{ value: 95, unit: "mm", mm: 95 }], materials: [] },
  manufacturer: { as_supplied: "X", cleaned: "X", match_key: "X", placeholder: false, possibly_truncated: false, alias_candidates: [] },
  duplicates: { same_description_and_manufacturer: [], similar_description: [] },
  completeness: { score: 40, items: [], missing: ["Drawing, CAD or photograph on file"] },
  constraints: [{ code: "insufficient_data", kind: "insufficient", text: "Feasibility cannot be assessed without: material." }],
  screening: "insufficient_information",
};
const ai = (enabled: boolean) => ({ enabled, reason: enabled ? "" : "External AI is not permitted for this company.", provider: "gemini",
  models: { lite: "gemini-3.1-flash-lite", flash: "gemini-3.8-flash", pro: "gemini-3.1-pro-preview" }, sent_fields: ["material description"],
  limits: { calls_per_minute: 10, calls_per_day: 200, daily_budget_usd: 1 } });
const suggestion = {
  id: "a1", status: "ok", status_label: "Suggestion received", tier: "lite", model: "gemini-3.1-flash-lite", model_version: "gemini-3.1-flash-lite",
  prompt_version: "p", input_hash: "abcdef0123456789", inputs: { material_description: "RING,WEAR,95MM" }, confidence: 0.9, removed: [],
  error_code: "", error_message: "", current: true, created_at: "2026-10-27T12:00:00Z", created_by_name: "Engineer",
  usage: { prompt_tokens: 390, output_tokens: 300, thinking_tokens: 0, cost_usd: 0.0005, latency_ms: 1500, attempts: 1 },
  result: { expanded_description: "Ring, wear, 95 mm", part_family: "wear ring", category: "mechanical", function: "Wear surface", is_assembly: "no",
    material: { value: "not determinable", basis: "not_determinable" }, am_screening: "insufficient_information", am_process_options: ["none"],
    rationale: "Material unknown.", risks: [], information_needed: ["Drawing"], confidence: 0.9, uncertainty: "Material not stated." },
};

function mockFetch(view: object) {
  const posts: [string, unknown][] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    if (init?.method === "POST") {
      posts.push([String(input), JSON.parse(String(init.body))]);
      if (String(input).includes("/classification/")) return new Response(JSON.stringify(view), { status: 200 });
      return new Response(JSON.stringify({ reused: false, assessment: suggestion }), { status: 201 });
    }
    return new Response(JSON.stringify(view), { status: 200 });
  });
  return posts;
}

describe("part intelligence panel", () => {
  it("shows the rule-based analysis and no AI buttons when external AI is not permitted", async () => {
    mockFetch({ analysis, ai: ai(false), assessments: [], classification: { category: "unknown" } });
    render(<PartIntelligencePanel partId="p1" />);
    await screen.findByLabelText("Rule-based analysis");
    expect(screen.getByLabelText("Rule-based analysis")).toHaveTextContent("Wear ring · Mechanical");
    expect(screen.getByText(/External AI not used: External AI is not permitted/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Get AI suggestion" })).toBeNull();
  });

  it("labels suggestions as unverified, requests the default tier and records the engineer's classification", async () => {
    const posts = mockFetch({ analysis, ai: ai(true), assessments: [suggestion], classification: { category: "unknown" } });
    render(<PartIntelligencePanel partId="p1" />);
    await screen.findByText("AI suggestion · not verified");
    expect(screen.getByText(/Suggestion only: not a feasibility approval/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Get AI suggestion" }));
    await waitFor(() => expect(posts.length).toBe(1));
    expect(posts[0][0]).toMatch(/\/parts\/p1\/intelligence\/assess\/$/);
    expect(posts[0][1]).toEqual({ tier: "lite" });
    fireEvent.change(screen.getByLabelText("Verified category"), { target: { value: "mechanical" } });
    fireEvent.click(screen.getByRole("button", { name: "Record classification" }));
    await waitFor(() => expect(posts.length).toBe(2));
    expect(posts[1][1]).toEqual({ category: "mechanical", note: "", assessment: "a1" });
  });
});
