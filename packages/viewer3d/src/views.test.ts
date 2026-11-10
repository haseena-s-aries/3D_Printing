import { describe, expect, it } from "vitest";

import { VIEW_DIRECTIONS, VIEW_NAMES, cameraPosition, fitDistance, normalise, upVector } from "./views";

describe("standard views", () => {
  it("defines all seven views with unit directions", () => {
    expect(VIEW_NAMES).toHaveLength(7);
    for (const v of VIEW_NAMES) {
      const n = normalise(VIEW_DIRECTIONS[v]);
      expect(Math.hypot(...n)).toBeCloseTo(1, 10);
    }
  });

  it("isometric looks from the +X +Y +Z octant", () => {
    const [x, y, z] = normalise(VIEW_DIRECTIONS.iso);
    expect(x).toBeCloseTo(0.577, 3);
    expect(y).toBeCloseTo(0.577, 3);
    expect(z).toBeCloseTo(0.577, 3);
  });

  it("top and bottom use a horizontal up vector", () => {
    expect(upVector("top")).toEqual([0, 0, -1]);
    expect(upVector("bottom")).toEqual([0, 0, 1]);
    expect(upVector("front")).toEqual([0, 1, 0]);
  });
});

describe("fit to view", () => {
  it("places the camera far enough for the bounding sphere", () => {
    const d = fitDistance(1, 40, 1, 1);
    expect(d).toBeCloseTo(1 / Math.sin((20 * Math.PI) / 180), 6);
  });

  it("uses the narrower horizontal field of view on portrait screens", () => {
    expect(fitDistance(1, 40, 0.5)).toBeGreaterThan(fitDistance(1, 40, 1));
  });

  it("puts the front camera on +Z from the centre", () => {
    const { position, distance } = cameraPosition("front", [1, 2, 3], 0.5, 40, 1.5);
    expect(position[0]).toBeCloseTo(1, 10);
    expect(position[1]).toBeCloseTo(2, 10);
    expect(position[2]).toBeCloseTo(3 + distance, 10);
  });

  it("handles an empty model without NaN", () => {
    expect(fitDistance(0, 40, 1)).toBe(1);
  });
});
