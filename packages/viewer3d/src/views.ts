/** Pure camera maths for the standard views (VWR-006..VWR-008). No WebGL needed, so it is unit-testable. */
export type ViewName = "iso" | "front" | "back" | "top" | "bottom" | "left" | "right";

export const VIEW_NAMES: ViewName[] = ["iso", "front", "back", "top", "bottom", "left", "right"];

/** Camera direction (from target to camera) in glTF Y-up space. */
export const VIEW_DIRECTIONS: Record<ViewName, [number, number, number]> = {
  iso: [1, 1, 1],
  front: [0, 0, 1],
  back: [0, 0, -1],
  top: [0, 1, 0],
  bottom: [0, -1, 0],
  left: [-1, 0, 0],
  right: [1, 0, 0],
};

/** Camera "up" vector per view; top/bottom need a horizontal up to avoid a degenerate look-at. */
export function upVector(view: ViewName): [number, number, number] {
  if (view === "top") return [0, 0, -1];
  if (view === "bottom") return [0, 0, 1];
  return [0, 1, 0];
}

export function normalise(v: [number, number, number]): [number, number, number] {
  const len = Math.hypot(v[0], v[1], v[2]);
  if (len === 0) throw new Error("zero-length vector");
  return [v[0] / len, v[1] / len, v[2] / len];
}

/** Distance at which a bounding sphere of `radius` fits a perspective camera with vertical field of view `fovDeg`. */
export function fitDistance(radius: number, fovDeg: number, aspect: number, margin = 1.15): number {
  if (radius <= 0) return 1;
  const vfov = (fovDeg * Math.PI) / 180;
  const hfov = 2 * Math.atan(Math.tan(vfov / 2) * Math.max(aspect, 1e-6));
  const limiting = Math.min(vfov, hfov);
  return (radius / Math.sin(limiting / 2)) * margin;
}

/** Camera position for a view of a model centred at `center` with bounding-sphere `radius`. */
export function cameraPosition(view: ViewName, center: [number, number, number], radius: number, fovDeg: number, aspect: number) {
  const d = normalise(VIEW_DIRECTIONS[view]);
  const dist = fitDistance(radius, fovDeg, aspect);
  return { position: [center[0] + d[0] * dist, center[1] + d[1] * dist, center[2] + d[2] * dist] as [number, number, number], distance: dist };
}
