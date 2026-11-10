/** What the 3D viewer panel shows for a file version (VWR-009). Kept free of Three.js so pages can import it eagerly. */
import type { FileVersion } from "@passport/api-types";

export type ViewerPanelState = { kind: "ready" } | { kind: "message"; tone: "info" | "warning" | "error"; text: string };

export function viewerState(v: Pick<FileVersion, "derivatives" | "conversion"> | null | undefined): ViewerPanelState {
  if (!v) return { kind: "message", tone: "info", text: "No 3D model uploaded. Upload a STEP file in the Interactive 3D model section." };
  if (v.derivatives.some((d) => d.kind === "glb")) return { kind: "ready" };
  const c = v.conversion;
  switch (c?.status) {
    case "queued":
    case "running":
      return { kind: "message", tone: "info", text: "The 3D view is being prepared from the STEP file. This usually takes under a minute — reload the page to check." };
    case "failed":
      return { kind: "message", tone: "error", text: `3D conversion failed (${c.error_code ?? "unknown error"}). The original STEP file is unchanged; upload a corrected version or contact support.` };
    case "not_available":
      return { kind: "message", tone: "warning", text: c.reason ?? "A 3D preview is not available for this file type." };
    default:
      return { kind: "message", tone: "warning", text: "No 3D derivative has been requested for this version. Upload the STEP file again as a new version to start conversion." };
  }
}
