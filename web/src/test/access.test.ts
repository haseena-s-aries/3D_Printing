/** CN-002 web: role display names and navigation for Aries Admin, Aries Engineer and client users. */
import { describe, expect, it } from "vitest";

import { portalLabel, visibleNav } from "../components/Layout";
import { roleLabel } from "../components/roles";

describe("role names", () => {
  it("shows the Aries and client role names", () => {
    expect(roleLabel("operator_admin")).toBe("Aries Admin");
    expect(roleLabel("operator_engineer")).toBe("Aries Engineer");
    expect(roleLabel("client_admin")).toBe("Client Administrator");
    expect(roleLabel("unknown_role")).toBe("unknown role");
  });
  it("labels the portal by organisation and role", () => {
    expect(portalLabel("operator", "operator_admin")).toBe("Aries portal");
    expect(portalLabel("client", "operator_engineer")).toBe("Aries portal · client workspace");
    expect(portalLabel("client", "client_admin")).toBe("Client portal");
  });
});

describe("navigation", () => {
  const caps = (list: string[]) => (c: string) => list.includes(c);
  it("Aries Admins see Registrations, Clients and the administrative Digital inventory", () => {
    const nav = visibleNav(caps(["registrations.review", "clients.view", "parts.view", "users.view", "inventory.admin_overview"]), true);
    expect(nav.map((n) => n.label)).toEqual(expect.arrayContaining(["Registrations", "Clients", "Users", "Digital inventory"]));
    expect(nav.find((n) => n.label === "Digital inventory")?.to).toBe("/admin/inventory"); // summaries, not the client catalog
    expect(nav.filter((n) => n.label === "Digital inventory")).toHaveLength(1);
  });
  it("Aries Engineers and clients keep the normal inventory", () => {
    expect(visibleNav(caps(["parts.view"]), false).find((n) => n.label === "Digital inventory")?.to).toBe("/parts");
    expect(visibleNav(caps(["parts.view", "requests.handle"]), true).map((n) => n.label)).not.toContain("Digital inventory");
  });
  it("client users never see Registrations or Clients", () => {
    const labels = visibleNav(caps(["parts.view", "passports.view", "requests.view"]), false).map((n) => n.label);
    expect(labels).not.toContain("Registrations");
    expect(labels).not.toContain("Clients");
    expect(labels).toContain("Digital inventory");
  });
});

describe("inventory stage wording", () => {
  it("uses role-specific labels for the same derived stages", async () => {
    const { STAGE_TEXT, STAGES } = await import("../components/inventoryStages");
    expect(STAGES.map((s) => STAGE_TEXT.engineer[s][0])).toEqual(["All parts", "Awaiting Review", "In Digitisation", "Published"]);
    expect(STAGES.map((s) => STAGE_TEXT.client[s][0])).toEqual(["All parts", "Submitted for Review", "Being Digitised", "Published"]);
    expect(STAGES.map((s) => STAGE_TEXT.admin[s][0])).toEqual(["All parts", "Review Backlog", "Digitisation Progress", "Published"]);
    for (const a of ["engineer", "client", "admin"] as const) for (const s of STAGES) expect(STAGE_TEXT[a][s][1].length).toBeGreaterThan(20);
  });
});
