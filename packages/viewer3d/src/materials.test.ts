import { describe, expect, it } from "vitest";

import { NEUTRAL_MATERIAL, usesDefaultMaterial } from "./materials";

describe("material policy (D-5)", () => {
  it("treats a GLB without materials as using the metallic glTF default", () => {
    expect(usesDefaultMaterial({})).toBe(true);
    expect(usesDefaultMaterial({ materials: [] })).toBe(true);
    expect(usesDefaultMaterial(null)).toBe(true);
  });
  it("keeps materials authored in the file", () => {
    expect(usesDefaultMaterial({ materials: [{ name: "Steel" }] })).toBe(false);
  });
  it("uses a mostly non-metallic neutral so unlit faces stay visible", () => {
    expect(NEUTRAL_MATERIAL.metalness).toBeLessThan(0.3);
  });
});
