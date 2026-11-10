/**
 * Material policy for CAD-derived GLB files (review defect D-5).
 *
 * OCCT writes STEP geometry without colours as a GLB with no `materials`. glTF then applies its default material,
 * which is fully metallic (metallicFactor 1). Without an environment to reflect, metal renders black wherever the
 * key light does not reach. Files with no materials therefore get a neutral, non-metallic engineering grey;
 * files that define their own materials are left as authored (and lit by the studio environment).
 */
export interface GltfJsonLike {
  materials?: unknown[];
}

export const NEUTRAL_MATERIAL = { color: 0x8c99aa, metalness: 0.15, roughness: 0.5 } as const;

export function usesDefaultMaterial(json: GltfJsonLike | undefined | null): boolean {
  return !json?.materials || json.materials.length === 0;
}
