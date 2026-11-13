import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, setTokens } from "../api/client";
import { breadcrumbs, visibleNav } from "../components/Layout";

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.restoreAllMocks();
  setTokens(null, null);
});

describe("api client", () => {
  it("raises ApiError with the server's code, message and request id", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      json(409, { error: { code: "policy_not_configured", message: "Disabled.", details: { decision: "OQ-35" }, request_id: "abc123" } }),
    );
    setTokens("tok");
    const err = (await api("/passports/x/revisions/1/approve/", { body: {} }).catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe("policy_not_configured");
    expect(err.details.decision).toBe("OQ-35");
    expect(err.requestId).toBe("abc123");
  });

  it("refreshes once on 401 and retries with the new token", async () => {
    setTokens("old", "refresh-1");
    const calls: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      const auth = (init?.headers as Record<string, string> | undefined)?.Authorization ?? "";
      calls.push(`${url} ${auth}`);
      if (url.includes("/auth/refresh/")) return json(200, { access: "new", refresh: "refresh-2" });
      return auth === "Bearer new" ? json(200, { ok: true }) : json(401, { error: { code: "authentication_failed", message: "expired", details: {}, request_id: "" } });
    });
    await expect(api<{ ok: boolean }>("/parts/")).resolves.toEqual({ ok: true });
    expect(calls).toEqual(["/api/v1/parts/ Bearer old", "/api/v1/auth/refresh/ ", "/api/v1/parts/ Bearer new"]);
    expect(sessionStorage.getItem("passport.refresh")).toBe("refresh-2");
  });

  it("does not loop when refresh fails", async () => {
    setTokens("old", "bad");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) =>
      String(input).includes("/auth/refresh/") ? json(401, {}) : json(401, { error: { code: "authentication_failed", message: "x", details: {}, request_id: "" } }),
    );
    await expect(api("/parts/")).rejects.toMatchObject({ status: 401 });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

describe("navigation by capability", () => {
  const caps = (list: string[]) => (c: string) => list.includes(c);

  it("client users do not see clients, users or audit", () => {
    const items = visibleNav(caps(["parts.view", "passports.view", "projects.view"]), false).map((n) => n.label);
    expect(items).toEqual(["Dashboard", "Digital inventory", "Projects", "Digital passports"]);
  });

  it("the Platform Operator organisation hides the empty client-inventory screens", () => {
    const all = caps(["clients.view", "parts.view", "projects.view", "passports.view", "requests.handle", "users.view", "audit.view"]);
    expect(visibleNav(all, true, "operator_admin").map((n) => n.label)).toEqual(["Dashboard", "Clients", "Digital passports", "Incoming requests", "Users", "Audit trail"]);
    expect(visibleNav(all, true, "operator_engineer").map((n) => n.label)).not.toContain("Digital passports");  // engineers use the company's list
  });

  it("shows the audit trail to the Aries Admin only, and approvals to the Admin and Manager", () => {
    const all = caps(["clients.view", "users.view", "audit.view", "passports.approve"]);
    expect(visibleNav(all, true, "operator_admin").map((n) => n.label)).toEqual(expect.arrayContaining(["Audit trail", "Approvals"]));
    expect(visibleNav(all, true, "operator_manager").map((n) => n.label)).toContain("Approvals");
    expect(visibleNav(all, true, "operator_manager").map((n) => n.label)).not.toContain("Audit trail");
    expect(visibleNav(all, false, "client_admin").map((n) => n.label)).not.toContain("Audit trail");
    expect(visibleNav(all, true, "operator_engineer").map((n) => n.label)).not.toContain("Approvals");
  });

  it("breadcrumbs start with the selected organisation", () => {
    expect(breadcrumbs("/parts", "Demo Energy Systems")).toEqual(["Demo Energy Systems", "Digital inventory"]);
    expect(breadcrumbs("/passports/abc", "Demo Energy Systems")).toEqual(["Demo Energy Systems", "Digital passports", "Passport"]);
    expect(breadcrumbs("/", "Demo Energy Systems")).toEqual(["Demo Energy Systems", "Dashboard"]);
    expect(breadcrumbs("/incoming/x", "Platform Operator")).toEqual(["Platform Operator", "Incoming requests", "Request"]);
  });

  it("clients page only appears in the operator portal", () => {
    expect(visibleNav(caps(["clients.view"]), false).map((n) => n.label)).not.toContain("Clients");
    expect(visibleNav(caps(["clients.view"]), true).map((n) => n.label)).toContain("Clients");
  });
});
