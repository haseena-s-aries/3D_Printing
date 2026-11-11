/** Public "Request an Aries staff account" page: roles come from the server; the request goes to /public/staff-requests/. */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import RequestStaffAccountPage from "../pages/RequestStaffAccountPage";

afterEach(() => vi.restoreAllMocks());

function serve(cfg: object) {
  const posts: [string, unknown][] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    if (init?.method === "POST") {
      posts.push([String(input), JSON.parse(String(init.body))]);
      return new Response(JSON.stringify({ status: "submitted" }), { status: 202, headers: { "Content-Type": "application/json" } });
    }
    return new Response(JSON.stringify(cfg), { status: 200, headers: { "Content-Type": "application/json" } });
  });
  return posts;
}

describe("staff account request", () => {
  it("is closed while registration is off", async () => {
    serve({ registration_enabled: false, dev_outbox: false, staff_roles: [] });
    render(<MemoryRouter><RequestStaffAccountPage /></MemoryRouter>);
    expect(await screen.findByText(/Account requests are not open yet/)).toBeInTheDocument();
  });

  it("offers the server's staff roles and submits the request", async () => {
    const posts = serve({ registration_enabled: true, dev_outbox: false,
      staff_roles: [{ value: "operator_engineer", label: "Aries Engineer" }, { value: "operator_qa", label: "Aries QA" }] });
    render(<MemoryRouter><RequestStaffAccountPage /></MemoryRouter>);
    const role = await screen.findByLabelText("Role requested");
    expect([...(role as HTMLSelectElement).options].map((o) => o.text)).toEqual(["Aries Engineer", "Aries QA"]);
    fireEvent.change(screen.getByLabelText("Full name"), { target: { value: "Nisha QA" } });
    fireEvent.change(role, { target: { value: "operator_qa" } });
    fireEvent.change(screen.getByLabelText("Work email"), { target: { value: "nisha@aries.test" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "Long-Enough-Pass-1" } });
    fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: "Long-Enough-Pass-1" } });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Request account" }));
    await waitFor(() => expect(screen.getByTestId("staff-request-submitted")).toBeInTheDocument());
    expect(posts[0][0]).toMatch(/\/public\/staff-requests\/$/);
    expect(posts[0][1]).toMatchObject({ full_name: "Nisha QA", requested_role: "operator_qa", email: "nisha@aries.test", accept_terms: true });
  });
});
