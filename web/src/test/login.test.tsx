import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "../auth/AuthContext";
import LoginPage from "../pages/LoginPage";

const session = {
  user: { id: "u1", email: "e@x.test", first_name: "E", last_name: "X" },
  tenant: { id: "t1", name: "Demo Client", slug: "demo-client", kind: "client", hosting_model: "shared" },
  membership: { id: "m1", role: "operator_engineer" },
  capabilities: ["parts.view"],
};

afterEach(() => vi.restoreAllMocks());

function renderLogin() {
  return render(
    <MemoryRouter initialEntries={["/login"]}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/" element={<div>Home page</div>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe("login", () => {
  it("asks for an organisation when the account has several, then signs in", async () => {
    const bodies: unknown[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("/auth/refresh/")) return new Response("{}", { status: 401 });
      const body = JSON.parse(String(init?.body ?? "{}"));
      bodies.push(body);
      if (!body.tenant) {
        return new Response(JSON.stringify({ error: { code: "tenant_selection_required", message: "Select an organisation.", request_id: "r",
          details: { tenants: [{ slug: "operator", name: "Operator" }, { slug: "demo-client", name: "Demo Client" }] } } }), { status: 400 });
      }
      return new Response(JSON.stringify({ access: "a", refresh: "r", session }), { status: 200 });
    });
    renderLogin();
    await screen.findByRole("button", { name: "Sign in" });
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "e@x.test" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "secret-password" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    const select = await screen.findByLabelText(/Organisation/);
    fireEvent.change(select, { target: { value: "demo-client" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(screen.getByText("Home page")).toBeInTheDocument());
    expect(bodies.at(-1)).toMatchObject({ email: "e@x.test", tenant: "demo-client" });
  });

  it("shows the server message on wrong credentials", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) =>
      String(input).includes("/auth/refresh/")
        ? new Response("{}", { status: 401 })
        : new Response(JSON.stringify({ error: { code: "invalid_credentials", message: "Email or password is incorrect.", details: {}, request_id: "r1" } }), { status: 401 }),
    );
    renderLogin();
    await screen.findByRole("button", { name: "Sign in" });
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "e@x.test" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "nope" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Email or password is incorrect.");
  });
});
