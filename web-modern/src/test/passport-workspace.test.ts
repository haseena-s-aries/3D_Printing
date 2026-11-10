/** W1 passport workspace: pure logic behind pre-fill, revision comparison, viewer states, paging and branding. */
import { describe, expect, it } from "vitest";

import { portalLabel } from "../components/Layout";
import { rl1Prefill } from "../components/passport/ReadinessForms";
import { diffContent } from "../components/passport/revisionDiff";
import { clampPage } from "../components/pdfUtils";
import { viewerState } from "../components/viewerState";

describe("R-L1 pre-fill from the part record (UX-3)", () => {
  const part = { original_material: "AISI 316", dimensions: "Ø45 x 40.5 mm", application: "Pump P-12" };
  it("fills only empty fields and reports which", () => {
    const { values, filled } = rl1Prefill({ part_size: "Ø46 x 40 mm" }, part);
    expect(values).toMatchObject({ original_material_grade: "AISI 316", part_size: "Ø46 x 40 mm", application: "Pump P-12" });
    expect(filled).toEqual(["original_material_grade", "application"]);
  });
  it("does nothing without a part", () => {
    expect(rl1Prefill({}, null)).toEqual({ values: {}, filled: [] });
  });
});

describe("revision comparison (BR-034)", () => {
  it("lists changed, added and removed fields across levels", () => {
    const before = { rl1: { part_size: "Ø45", motion: "static", cad_3d_available: true }, rl2: { mechanical_acceptance: [{ property: "tensile", requirement: "485" }] } };
    const after = { rl1: { part_size: "Ø46", motion: "static", cad_3d_available: false }, rl3: { evidence: { itp: "f1" } } };
    expect(diffContent(before, after)).toEqual([
      { key: "rl1.cad_3d_available", before: "Yes", after: "No" },
      { key: "rl1.part_size", before: "Ø45", after: "Ø46" },
      { key: "rl2.mechanical_acceptance", before: "tensile 485", after: "" },
      { key: "rl3.evidence.itp", before: "", after: "f1" },
    ]);
  });
  it("finds no change between identical contents", () => {
    expect(diffContent({ rl1: { a: "1" } }, { rl1: { a: "1" } })).toEqual([]);
  });
});

describe("3D viewer panel states (VWR-009)", () => {
  const v = (status: string | null, glb = false, extra = {}) =>
    ({ derivatives: glb ? [{ kind: "glb" }] : [], conversion: status ? { status, ...extra } : null }) as never;
  it("is ready once a GLB derivative exists", () => expect(viewerState(v("succeeded", true))).toEqual({ kind: "ready" }));
  it("explains each non-viewable state with a distinct message", () => {
    const texts = [v("queued"), v("failed", false, { error_code: "STEP_READ_FAILED" }), v("not_available", false, { reason: "DWG (OQ-27)" }), v(null), null].map(
      (x) => (viewerState(x) as { text: string }).text,
    );
    expect(new Set(texts).size).toBe(5);
    expect(texts[1]).toContain("STEP_READ_FAILED");
  });
});

describe("PDF page entry (DRW-003)", () => {
  it("keeps the page within the document", () => {
    expect(clampPage(0, 5)).toBe(1);
    expect(clampPage(9, 5)).toBe(5);
    expect(clampPage(Number("abc"), 5)).toBe(1);
    expect(clampPage(3, 5)).toBe(3);
  });
});

describe("portal branding (UX-2)", () => {
  it("keeps the operator identity for operator staff inside a client organisation", () => {
    expect(portalLabel("client", "operator_engineer")).toBe("Aries portal · client workspace");
    expect(portalLabel("client", "client_user")).toBe("Client portal");
    expect(portalLabel("operator", "operator_admin")).toBe("Aries portal");
  });
});
