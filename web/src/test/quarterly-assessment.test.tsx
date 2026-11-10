/** CN-007 Phase 6 assessment dashboard: KPIs, estimated vs verified savings, changes, history, reports, run start/retry. */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../auth/AuthContext", () => ({
  useAuth: () => ({ can: () => true, session: { user: { id: "u1" }, membership: { role: "operator_engineer" } } }), useSessionKey: () => "s",
}));

import { AssessmentDashboard } from "../components/QuarterlyAssessment";
import live from "./fixtures/assessment-dashboard.json";

afterEach(() => vi.restoreAllMocks());

function mockFetch(v: object) {
  const calls: [string, string, unknown][] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push([String(input), init?.method ?? "GET", body]);
    if (init?.method === "POST") return new Response(JSON.stringify({ run: { ...live.runs[0], status: "queued" } }), { status: 201 });
    return new Response(JSON.stringify(v), { status: 200 });
  });
  return calls;
}
const renderDash = () => render(<MemoryRouter><AssessmentDashboard /></MemoryRouter>);

describe("quarterly assessment dashboard", () => {
  it("shows the dashboard of the latest completed run with estimated and verified savings kept apart", async () => {
    mockFetch(live);
    renderDash();
    const kpis = await screen.findByLabelText("Assessment dashboard");
    expect(within(kpis).getByTestId("kpi-total")).toHaveTextContent("5");
    expect(within(kpis).getByTestId("kpi-assessed")).toHaveTextContent("4 / 0");
    expect(within(kpis).getByTestId("kpi-insufficient")).toHaveTextContent("4");
    expect(within(kpis).getByTestId("kpi-am")).toHaveTextContent("0");
    expect(within(kpis).getByTestId("kpi-savings")).toHaveTextContent("USD 753.87 vs none");
    expect(screen.getByRole("note")).toHaveTextContent("never validated savings");
    const parts = screen.getByLabelText("Assessed parts");
    expect(within(parts).getAllByRole("row")).toHaveLength(5);
    expect(within(parts).getByText("not technically qualified")).toBeInTheDocument();
    expect(screen.getByTestId("changes")).toHaveTextContent("First run for this scope");
    const hist = screen.getByLabelText("Assessment run history");
    expect(within(hist).getByRole("button", { name: "Excel" })).toBeInTheDocument();
    expect(within(hist).getByRole("button", { name: "PDF" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /approve|publish|release/i })).toBeNull();
  });

  it("starts a run, and offers retry for a run completed with errors", async () => {
    const withErrors = { ...live, runs: [{ ...live.runs[0], status: "completed_with_errors", status_label: "Completed with errors", failed_count: 1 }] };
    const calls = mockFetch(withErrors);
    renderDash();
    fireEvent.click(await screen.findByRole("button", { name: "Start assessment run" }));
    await waitFor(() => expect(calls.some(([u, m]) => m === "POST" && u.endsWith("/intelligence/assessments/"))).toBe(true));
    expect(calls.find(([, m]) => m === "POST")![2]).toEqual({ ai_tier: "" });
    fireEvent.click(screen.getByRole("button", { name: "Retry failed parts" }));
    await waitFor(() => expect(calls.some(([u, m]) => m === "POST" && u.endsWith(`/intelligence/assessments/${live.runs[0].id}/retry/`))).toBe(true));
  });

  it("blocks a second start while a run is active and shows its progress", async () => {
    const active = { ...live.runs[0], status: "running", status_label: "Running", done_count: 1, reused_count: 1 };
    mockFetch({ ...live, active });
    renderDash();
    expect(await screen.findByTestId("active-run")).toHaveTextContent("2 of 4 parts processed");
    expect(screen.getByRole("button", { name: "Run in progress…" })).toBeDisabled();
  });
});
