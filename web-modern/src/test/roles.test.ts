import type { Session } from "@passport/api-types";
import { describe, expect, it } from "vitest";

import { assignableRoles, roleOptionLabel } from "../components/roles";

const session = (role_model?: "four_roles" | "legacy") => ({ role_model }) as Session;

describe("role selection (four-role model)", () => {
  it("offers only the four core roles when the model is on", () => {
    expect(assignableRoles(session("four_roles"), "client")).toEqual(["client_admin", "client_user"]);
    expect(assignableRoles(session("four_roles"), "operator")).toEqual(["operator_admin", "operator_engineer"]);
    expect(assignableRoles(session("four_roles"), "operator_in_client")).toEqual(["operator_engineer"]);
  });

  it("keeps the earlier roles while the model is off", () => {
    expect(assignableRoles(session("legacy"), "client")).toContain("procurement");
    expect(assignableRoles(undefined, "operator_in_client")).toContain("operator_qa");
  });

  it("marks legacy roles in lists", () => {
    expect(roleOptionLabel("operator_qa")).toBe("Aries QA (legacy)");
    expect(roleOptionLabel("client_user")).toBe("Client User");
  });
});
