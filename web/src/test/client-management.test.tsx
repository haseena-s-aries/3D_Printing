/** Aries Admin Client Management page: tabs in the URL, existing panels reused, empty states. */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import ClientManagementPage, { CLIENT_TABS } from "../pages/ClientManagementPage";

// Aries Admin session: may allow inventory import for Client Administrators (CN-007)
vi.mock("../auth/AuthContext", () => ({ useAuth: () => ({ can: () => true }), useSessionKey: () => "s" }));

afterEach(() => vi.restoreAllMocks());

const CLIENT = { id: "c1", name: "Synthetic Pumps LLC", slug: "synthetic-pumps", status: "active", hosting_model: "shared", region_code: "",
  member_count: 1, profile_complete: false, created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z" };
const DETAILS = {
  name: CLIENT.name, slug: CLIENT.slug, status: "active", hosting_model: "shared", region_code: "", origin: "aries_admin", created_at: CLIENT.created_at,
  profile: { values: { name: CLIENT.name }, missing: ["country"], complete: false },
  contact: { state: "none", email: "", email_verified: false, label: "No contact email recorded", verified_at: null },
  registration: null, people: [{ email: "admin@synthetic-pumps.test", role: "client_admin", is_active: true }],
  aries_staff: [{ membership_id: "m1", email: "eng@aries.test", name: "Eng One", role: "operator_engineer", is_active: true, scope: "projects",
    projects: [{ id: "p1", code: "SP-1", name: "Pump scan" }], edit_reviewer: true }],
  counts: { projects: 1, parts: 4, passports: 2 },
};
const MEMBERS = [{ id: "mm1", email: "admin@synthetic-pumps.test", first_name: "", last_name: "", role: "client_admin", is_active: true,
  created_at: CLIENT.created_at, managed_by: "organisation", can_manage: true, part_submission_allowed: false }];

function mockApi(projects: unknown[] = [{ id: "p1", code: "SP-1", name: "Pump scan", status: "active" }]) {
  const calls: string[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    calls.push(url);
    const body = url.includes("/details/") ? DETAILS : url.includes("/members/") ? MEMBERS : url.includes("/projects/") ? projects
      : url.includes("/audit-events/") ? { count: 0, results: [] } : CLIENT;
    return new Response(JSON.stringify(body), { status: 200 });
  });
  return calls;
}

function Where() {
  const l = useLocation();
  return <div data-testid="where">{l.pathname + l.search}</div>;
}
const renderAt = (url: string) => render(
  <MemoryRouter initialEntries={[url]}>
    <Routes><Route path="/clients/:id" element={<><ClientManagementPage /><Where /></>} /></Routes>
  </MemoryRouter>,
);

describe("client management page", () => {
  it("shows the company, status, breadcrumb and all six tabs", async () => {
    mockApi();
    renderAt("/clients/c1");
    expect(await screen.findByRole("heading", { level: 1, name: CLIENT.name })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Client breadcrumb" })).toHaveTextContent("Client organisations");
    expect(screen.getAllByText("active").length).toBeGreaterThan(0);
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(CLIENT_TABS.map(([, l]) => l));
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByTestId("client-counts")).toHaveTextContent("4Parts");
  });

  it("opens the tab named in the URL and keeps the tab in the URL", async () => {
    mockApi();
    renderAt("/clients/c1?tab=engineers");
    expect(await screen.findByTestId("staff-eng@aries.test")).toHaveTextContent("Projects: SP-1");
    expect(screen.getByText("Edit reviewer (provisional)")).toBeInTheDocument();
    expect(screen.getByLabelText(/Authorised edit reviewer/)).toBeChecked();  // existing access editor reused
    fireEvent.click(screen.getByRole("tab", { name: "Client Users" }));
    expect(await screen.findByRole("table", { name: `Members of ${CLIENT.name}` })).toBeInTheDocument();
    expect(screen.getByRole("form", { name: "Add member" })).toBeInTheDocument();
    expect(screen.getByLabelText("May import inventory")).not.toBeChecked();  // CN-007: off unless explicitly allowed
    expect(screen.getByTestId("where")).toHaveTextContent("/clients/c1?tab=users");
  });

  it("shows clear empty states", async () => {
    mockApi([]);
    renderAt("/clients/c1?tab=projects");
    expect(await screen.findByText(/has no projects yet/)).toBeInTheDocument();
  });

  it("asks the audit list only for this company, without record views by default", async () => {
    const calls = mockApi();
    renderAt("/clients/c1?tab=audit");
    await waitFor(() => expect(calls.some((u) => u.includes("/audit-events/"))).toBe(true));
    const url = calls.find((u) => u.includes("/audit-events/")) ?? "";
    expect(url).toContain("client=c1");
    expect(url).toContain("exclude_views=true");
    expect(await screen.findByText("No events match.")).toBeInTheDocument();
  });
});
