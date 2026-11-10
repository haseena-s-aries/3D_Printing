/** Regression tests for defects found in the Phase 1 web review (docs/web-review). */
import { describe, expect, it } from "vitest";

import { postLoginTarget } from "../auth/AuthContext";
import { compactBody } from "../pages/ClientsPage";

describe("D-1: member form omits empty optional fields", () => {
  it("drops empty password and names so existing operator staff can be assigned", () => {
    expect(compactBody({ email: "eng@op.test", role: "operator_engineer", first_name: "", last_name: "", password: "" })).toEqual({
      email: "eng@op.test",
      role: "operator_engineer",
    });
  });
  it("keeps values that were entered", () => {
    expect(compactBody({ email: "a@b.test", password: "Long-Enough-Pass-1" })).toEqual({ email: "a@b.test", password: "Long-Enough-Pass-1" });
  });
});

describe("D-4: post-login destination", () => {
  it("returns the same user to the page they were on", () => {
    expect(postLoginTarget({ from: "/passports/p1", user: "u1" }, "u1")).toBe("/passports/p1");
  });
  it("sends a different user to the dashboard instead of the previous user's page", () => {
    expect(postLoginTarget({ from: "/clients", user: "admin" }, "engineer")).toBe("/");
  });
  it("keeps a deep link opened without a previous session", () => {
    expect(postLoginTarget({ from: "/passports/p1", user: null }, "u1")).toBe("/passports/p1");
  });
  it("defaults to the dashboard", () => {
    expect(postLoginTarget(null, "u1")).toBe("/");
  });
});
