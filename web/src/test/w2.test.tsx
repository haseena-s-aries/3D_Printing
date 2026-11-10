/** W2 web: conversion polling trigger, catalog badges, thumbnail placeholder and invitation acceptance. */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DataLevel, Thumbnail } from "../components/catalog";
import { conversionPending } from "../components/FilesPanel";
import AcceptInvitationPage from "../pages/AcceptInvitationPage";

afterEach(() => vi.restoreAllMocks());

const file = (status: string | null) => ({ latest_version: status ? { conversion: { status } } : null }) as never;

describe("conversion polling trigger", () => {
  it("is on only while a conversion is queued or running", () => {
    expect(conversionPending([file("queued")])).toBe(true);
    expect(conversionPending([file("succeeded"), file("running")])).toBe(true);
    expect(conversionPending([file("succeeded"), file("failed"), file(null)])).toBe(false);
  });
});

describe("catalog badges", () => {
  it("labels data completeness as guidance, separately from the evidence level", () => {
    render(<DataLevel level="rl2" />);
    const pill = screen.getByText("R-L1–R-L2 data complete");
    expect(pill).toHaveClass("is-complete");
    expect(pill.getAttribute("title")).toMatch(/evidence level is set separately/);
  });
  it("says when there is no passport", () => {
    render(<DataLevel level={null} />);
    expect(screen.getByText("No passport")).toBeInTheDocument();
  });
  it("shows a placeholder without fetching when there is no photograph", () => {
    const spy = vi.spyOn(globalThis, "fetch");
    render(<Thumbnail thumb={null} alt="PMP-100" />);
    expect(screen.getByRole("img", { name: "PMP-100: no photograph" })).toHaveTextContent("PM");
    expect(spy).not.toHaveBeenCalled();
  });
});

describe("invitation acceptance page", () => {
  function renderAt(token: string) {
    return render(
      <MemoryRouter initialEntries={[`/invite/${token}`]}>
        <Routes>
          <Route path="/invite/:token" element={<AcceptInvitationPage />} />
        </Routes>
      </MemoryRouter>,
    );
  }

  it("shows the invitation, checks the confirmation locally, then accepts", async () => {
    const posts: unknown[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
      if (init?.method === "POST") {
        posts.push(JSON.parse(String(init.body)));
        return new Response(JSON.stringify({ status: "accepted", organisation: "Client A" }), { status: 200 });
      }
      return new Response(JSON.stringify({ organisation: "Client A", role: "client_user", email: "new@x.test", expires_at: "2026-10-23T00:00:00Z" }), { status: 200 });
    });
    renderAt("tok123");
    expect(await screen.findByText("Client A")).toBeInTheDocument();
    expect(screen.queryByText(/already have an account with this address\?/)).toBeNull(); // no account-existence hint
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "Long-Enough-Pass-1" } });
    fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: "different" } });
    fireEvent.click(screen.getByRole("button", { name: "Accept invitation" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The passwords do not match.");
    expect(posts).toHaveLength(0);
    fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: "Long-Enough-Pass-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Accept invitation" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("You have joined Client A."));
    expect(posts[0]).toMatchObject({ password: "Long-Enough-Pass-1" });
  });

  it("shows a clear error for an invalid or expired link", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ error: { code: "invitation_invalid", message: "This invitation cannot be accepted with these details.", details: {}, request_id: "r" } }), { status: 400 }),
    );
    renderAt("bad");
    expect(await screen.findByRole("alert")).toHaveTextContent("This invitation cannot be accepted");
  });
});

describe("useApi", () => {
  it("ignores a slow response for an earlier query once a newer query has answered", async () => {
    const client = await import("../api/client");
    const { useApi } = await import("../api/useApi");
    const { renderHook } = await import("@testing-library/react");
    const pending: Record<string, (v: unknown) => void> = {};
    vi.spyOn(client, "api").mockImplementation(((_p: string, o?: { query?: { ordering?: string } }) =>
      new Promise((resolve) => { pending[o?.query?.ordering ?? ""] = resolve; })) as never);
    const { result, rerender } = renderHook(({ ordering }) => useApi<string>("/parts/", { query: { ordering } }), {
      initialProps: { ordering: "old" },
    });
    rerender({ ordering: "new" });
    pending.new("new result");
    await waitFor(() => expect(result.current.data).toBe("new result"));
    pending.old("stale result"); // arrives last
    await new Promise((r) => setTimeout(r, 10));
    expect(result.current.data).toBe("new result");
    expect(result.current.loading).toBe(false);
  });
});
