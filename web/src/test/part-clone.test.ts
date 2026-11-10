/** Clone Part (BR-033, CN-003): who sees the action, and inherited values stay marked as references. */
import { describe, expect, it } from "vitest";

import { prefillSources, rl1Prefill } from "../components/passport/ReadinessForms";
import { canClone } from "../pages/PartClonePage";

const caps = (list: string[]) => (c: string) => list.includes(c);

describe("clone action", () => {
  it("is offered to submitters for accepted or Aries parts only", () => {
    expect(canClone({ review_state: "not_required" }, caps(["parts.submit"]))).toBe(true);
    expect(canClone({ review_state: "accepted" }, caps(["parts.submit"]))).toBe(true);
    expect(canClone({ review_state: "pending_review" }, caps(["parts.submit"]))).toBe(false);
    expect(canClone({ review_state: "declined" }, caps(["parts.submit"]))).toBe(false);
    expect(canClone({ review_state: "not_required" }, caps(["parts.view"]))).toBe(false);
  });
});

describe("passport pre-fill of a clone", () => {
  const entry = (source: "client" | "inherited", verified = false) =>
    ({ source, entered_by: "x", entered_at: null, verified_by: verified ? "e" : null, verified_at: null });
  const clone = {
    origin: "client" as const, original_material: "AISI 316L", dimensions: "Ø200 x 60 mm", application: "Pump",
    proposed_material: "AlSi10Mg", material_change_reason: "Lighter",
    field_provenance: { original_material: entry("inherited"), dimensions: entry("inherited", true), application: entry("client"),
      proposed_material: entry("client"), material_change_reason: entry("client") },
  };
  it("fills the proposed material and reason, and marks inherited values as references", () => {
    const { values, filled } = rl1Prefill({}, clone);
    expect(values).toMatchObject({ proposed_material: "AlSi10Mg", proposed_material_reason: "Lighter", original_material_grade: "AISI 316L" });
    expect(prefillSources(filled, clone)).toEqual({
      original_material_grade: "inherited_reference", part_size: "aries_verified", application: "client_submitted",
      proposed_material: "client_submitted", proposed_material_reason: "client_submitted",
    });
  });
});

describe("structured part fields", () => {
  it("offers the company's own values first, without duplicates, and keeps list entries", async () => {
    const { mergeOptions } = await import("../components/PartFieldInput");
    const out = mergeOptions(["KSB", "Bespoke Works Ltd"], [{ value: "ksb" }, { value: "Sulzer" }]);
    expect(out.map((o) => o.value)).toEqual(["KSB", "Bespoke Works Ltd", "Sulzer"]);
    expect(out[0].group).toBe("Used in your company");
  });
});
