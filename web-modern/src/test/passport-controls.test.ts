/** Requirement update 2026-10: structured passport controls read and write the existing string fields without
 *  reinterpreting stored engineering values; client submissions are labelled and their provenance is shown. */
import { describe, expect, it } from "vitest";

import { formatHeat, formatNumberUnit, formatSize, inList, joinMulti, parseHeat, parseMulti, parseNumberUnit, parseSize } from "../components/passport/controls";
import { prefillSources, rl1Prefill } from "../components/passport/ReadinessForms";
import { isOpenReview, REVIEW_LABEL } from "../components/PartSubmission";
import { visibleNav } from "../components/Layout";

const LEN = ["mm", "cm", "m", "in"];

describe("multi-select values", () => {
  it("round-trips listed and custom items", () => {
    const v = joinMulti(["Visual", "Dye penetrant (PT)", "Helium leak"]);
    expect(v).toBe("Visual; Dye penetrant (PT); Helium leak");
    expect(parseMulti(v)).toEqual(["Visual", "Dye penetrant (PT)", "Helium leak"]);
  });
  it("keeps legacy free text as one custom item, unchanged", () => {
    expect(parseMulti("Visual + dye penetrant (sample)")).toEqual(["Visual + dye penetrant (sample)"]);
    expect(joinMulti(parseMulti("Visual + dye penetrant (sample)"))).toBe("Visual + dye penetrant (sample)");
  });
  it("matches list entries case-insensitively", () => {
    expect(inList("aisi 316l", [{ value: "AISI 316L" }])).toBe(true);
    expect(inList("AISI 316 (sample)", [{ value: "AISI 316" }])).toBe(false);
  });
});

describe("numbers with units", () => {
  it("parses and formats the canonical form", () => {
    expect(parseNumberUnit("40 µm", ["µm", "mm"])).toEqual({ n: "40", unit: "µm" });
    expect(formatNumberUnit("40", "µm")).toBe("40 µm");
    expect(parseNumberUnit("1450", [""])).toEqual({ n: "1450", unit: "" }); // RPM stored as a bare number
    expect(formatNumberUnit("1450", "")).toBe("1450");
  });
  it("leaves anything else as a custom value", () => {
    expect(parseNumberUnit("approx. 1500", [""])).toBeNull();
    expect(parseNumberUnit("1450 rpm", [""])).toBeNull();
    expect(parseNumberUnit("40 microns", ["µm", "mm"])).toBeNull();
  });
});

describe("part size", () => {
  it("parses box and cylinder forms and formats them back identically", () => {
    expect(parseSize("100 x 50 x 120 mm", LEN)).toEqual({ shape: "box", dims: ["100", "50", "120"], unit: "mm" });
    expect(formatSize(parseSize("100 x 50 x 120 mm", LEN)!)).toBe("100 x 50 x 120 mm");
    expect(formatSize(parseSize("Ø45 x 40.5 mm", LEN)!)).toBe("Ø45 x 40.5 mm");
  });
  it("does not reinterpret other stored formats", () => {
    expect(parseSize("120.0 x 34.0 mm (Ø x H)", LEN)).toBeNull();
    expect(parseSize("approx 4 inch", LEN)).toBeNull();
  });
});

describe("heat treatment", () => {
  const P = [{ value: "Stress relief" }, { value: "None" }, { value: "HIP" }];
  it("parses process, temperature and time", () => {
    expect(parseHeat("Stress relief 650 °C / 2 h", P)).toEqual({ process: "Stress relief", temp: "650", hours: "2" });
    expect(formatHeat({ process: "Stress relief", temp: "650", hours: "2" })).toBe("Stress relief 650 °C / 2 h");
    expect(parseHeat("None", P)).toEqual({ process: "None", temp: "", hours: "" });
  });
  it("keeps other descriptions custom", () => {
    expect(parseHeat("SR 650 °C 2 h", P)).toBeNull();
    expect(parseHeat("Stress relief 650 °C / 2 h (sample)", P)).toBeNull();
  });
});

describe("R-L1 pre-fill provenance", () => {
  const prov = (verified: boolean) => ({ source: "client" as const, entered_by: "c", entered_at: null, verified_by: verified ? "e" : null, verified_at: null });
  it("marks values taken from an unverified client submission", () => {
    const part = { origin: "client" as const, original_material: "CF8M", dimensions: "", application: "Pump",
      field_provenance: { original_material: prov(false), application: prov(true) } };
    const { filled } = rl1Prefill({}, part);
    expect(prefillSources(filled, part)).toEqual({ original_material_grade: "client_submitted", application: "aries_verified" });
  });
  it("adds nothing for Aries-maintained parts", () => {
    const part = { origin: "aries" as const, original_material: "CF8M", dimensions: "", application: "", field_provenance: {} };
    expect(prefillSources(rl1Prefill({}, part).filled, part)).toEqual({});
  });
});

describe("client submissions", () => {
  it("labels review states and recognises open reviews", () => {
    expect(REVIEW_LABEL.pending_review).toBe("Waiting for approval");
    expect(REVIEW_LABEL.info_requested).toBe("Sent back for changes");
    expect(isOpenReview({ review_state: "info_requested" })).toBe(true);
    expect(isOpenReview({ review_state: "accepted" })).toBe(false);
  });
  it("keeps the inventory visible to submitters", () => {
    const labels = visibleNav((c) => ["parts.view", "parts.submit"].includes(c), false).map((n) => n.label);
    expect(labels).toContain("Digital inventory");
  });
});
