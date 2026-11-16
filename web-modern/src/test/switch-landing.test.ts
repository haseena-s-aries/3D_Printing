import { describe, expect, it } from "vitest";

import { landingAfterSwitch } from "../components/Layout";

const engineerInClient = { capabilities: ["requests.handle", "parts.view", "passports.view", "projects.view"], tenant: { kind: "client" }, membership: { role: "operator_engineer" } };
const engineerInAries = { capabilities: ["requests.handle"], tenant: { kind: "operator" }, membership: { role: "operator_engineer" } };

describe("changing client keeps the tab", () => {
  it("stays on Incoming requests and keeps its filters, but not the previous company filter", () => {
    expect(landingAfterSwitch("/incoming", "", engineerInClient)).toBe("/incoming");
    expect(landingAfterSwitch("/incoming", "?kind=manufacturing_request&client=abc", engineerInClient)).toBe("/incoming?kind=manufacturing_request");
  });
  it("goes from a record of the previous company to the same tab's list", () => {
    expect(landingAfterSwitch("/incoming/123", "", engineerInClient)).toBe("/incoming");
    expect(landingAfterSwitch("/passports/9aa", "", engineerInClient)).toBe("/passports");
  });
  it("goes to the dashboard when the tab does not exist in the new organisation", () => {
    expect(landingAfterSwitch("/parts", "", engineerInAries)).toBe("/");
    expect(landingAfterSwitch("/", "", engineerInClient)).toBe("/");
  });
});
