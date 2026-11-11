/**
 * Readiness-level data capture (BRD v0.4): R-L1 BR-006/BR-009, R-L2 BR-007/BR-026/BR-041, R-L3 BR-008.
 * Each level saves only its own part of the revision content; the server merges levels. Drafts may be saved incomplete.
 * Completeness is shown for guidance only: evidence-level transitions and QA verification are gated (OQ-35).
 *
 * Requirement update 2026-10: fields are grouped in sections and use structured controls (./controls) that read and
 * write the same stored strings, so existing values and revisions stay as they are. The field-by-field mapping is in
 * docs/passport-field-control-mapping.md.
 */
import type { AcceptanceRow, EngineeringFile, LevelCompleteness, ManufacturingSpec, Part, ProcessParameter, Revision, RL1, RL2, RL3 } from "@passport/api-types";
import { cloneElement, createContext, useContext, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type FormEvent, type MouseEvent, type ReactElement, type ReactNode } from "react";
import { flushSync } from "react-dom";

import { api } from "../../api/client";
import { Icon } from "../icons";
import { DisabledAction, ErrorNotice } from "../ui";
import { ComboText, HeatTreatmentInput, MultiSelect, NumberUnit, SelectOther, SizeInput, useFieldOptions } from "./controls";

export const FIELD_LABELS: Record<string, string> = {
  cad_3d_available: "3D CAD file available", drawings_2d_available: "2D drawings available", original_material_grade: "Original material grade",
  proposed_material: "Proposed material", proposed_material_reason: "Reason for the proposed material", material_identification_method: "Material identification",
  technical_description: "Technical description", part_size: "Part size", application: "Application of part", atmosphere: "Atmosphere",
  operating_environment: "Operating environment",
  motion: "Static or rotating", rpm: "RPM (rotating parts)", ip_status: "IP consideration",
  manufacturing_process: "Manufacturing process",
  manufacturing_solution: "Manufacturing solution", material_selection: "Material selection", material_category: "Material category",
  criticality_amsl: "Criticality (AMSL)", feedstock: "Feedstock", applicable_standards: "Applicable standards",
  mechanical_acceptance: "Mechanical acceptance table", dimensional_tolerances: "Dimensional tolerances", ndt: "NDT",
  inspection_test_plan: "Inspection and test plan", mtc_required: "Material test certificate required", test_coupons: "Test coupon details",
  "manufacturing_spec.job_number": "Job number", "manufacturing_spec.material": "Spec: material", "manufacturing_spec.feedstock": "Spec: feedstock",
  "manufacturing_spec.machine": "Machine", "manufacturing_spec.layer_thickness": "Layer thickness", "manufacturing_spec.support_strategy": "Support strategy",
  "manufacturing_spec.build_orientation": "Build orientation", "manufacturing_spec.inert_gas": "Inert gas", "manufacturing_spec.heat_treatment": "Heat treatment",
  "manufacturing_spec.post_processing": "Post-processing", "manufacturing_spec.machining": "Machining", "manufacturing_spec.printing_hours": "Printing hours",
  "manufacturing_spec.post_processing_hours": "Post-processing hours",
  itp: "Inspection and test plan (ITP)", machine_details: "Manufacturing machine details", print_orientation: "Print orientation document",
  dimensional_inspection: "Dimensional inspection report", material_test_certificate: "Material test certificate",
};
export const RL3_EVIDENCE = ["itp", "machine_details", "print_orientation", "dimensional_inspection", "material_test_certificate"] as const;

// Mirrors apps/passports/content.py (the server's completeness is authoritative; these only label the fields).
const RL1_REQUIRED = new Set(["cad_3d_available", "drawings_2d_available", "original_material_grade", "material_identification_method",
  "technical_description", "part_size", "application", "atmosphere", "motion", "ip_status"]);
const RL2_REQUIRED = new Set(["manufacturing_solution", "material_selection", "material_category", "criticality_amsl", "feedstock",
  "applicable_standards", "mechanical_acceptance", "dimensional_tolerances", "ndt", "inspection_test_plan", "mtc_required", "test_coupons",
  ...["job_number", "material", "feedstock", "machine", "layer_thickness", "support_strategy", "build_orientation", "inert_gas",
    "heat_treatment", "post_processing", "machining", "printing_hours", "post_processing_hours"].map((k) => `manufacturing_spec.${k}`)]);

type PrefillFrom = "original_material" | "dimensions" | "application" | "proposed_material" | "material_change_reason";
const PREFILL: [keyof RL1, PrefillFrom][] = [
  ["original_material_grade", "original_material"], ["part_size", "dimensions"], ["application", "application"],
  // clones (CN-003): the client's proposed material and reason, marked as client-submitted until Aries verifies them
  ["proposed_material", "proposed_material"], ["proposed_material_reason", "material_change_reason"],
];

/** Values an empty R-L1 takes from the spare-part record (UX-3). Only empty fields are filled. */
export function rl1Prefill(rl1: RL1, part: (Pick<Part, "original_material" | "dimensions" | "application"> & Partial<Pick<Part, "proposed_material" | "material_change_reason">>) | null): { values: RL1; filled: string[] } {
  if (!part) return { values: rl1, filled: [] };
  const values = { ...rl1 };
  const filled: string[] = [];
  for (const [key, from] of PREFILL) {
    const v = part[from] ?? undefined;
    if (!values[key] && v) {
      (values as Record<string, unknown>)[key] = v;
      filled.push(key);
    }
  }
  return { values, filled };
}

/** Provenance of pre-filled values that come from a client-submitted part record (requirement update 2026-10). */
type Source = "client_submitted" | "aries_verified" | "inherited_reference";
export function prefillSources(filled: string[], part: Pick<Part, "origin" | "field_provenance"> | null): Record<string, Source> {
  const out: Record<string, Source> = {};
  if (!part || part.origin !== "client") return out;
  for (const [key, from] of PREFILL) {
    const p = part.field_provenance?.[from];
    if (!filled.includes(key) || !p) continue;
    if (p.verified_by) out[key] = "aries_verified";
    else if (p.source === "client") out[key] = "client_submitted";
    else if (p.source === "inherited") out[key] = "inherited_reference";  // copied from the original part of a clone
  }
  return out;
}

export function Progress({ level, c }: { level: string; c: LevelCompleteness | undefined }) {
  if (!c) return null;
  return (
    <span className={`progress-pill ${c.complete ? "is-complete" : ""}`} title={c.missing.map((m) => FIELD_LABELS[m] ?? m).join(", ")}>
      {level} {c.done}/{c.total}
    </span>
  );
}

/* ---- expandable sections: open/closed state lives above the forms, so saving (which remounts a form) keeps it */
type SectionsState = { isOpen: (t: string) => boolean; set: (t: string, v: boolean) => void; all: (v: boolean) => void; register: (t: string) => void };
const SectionsCtx = createContext<SectionsState | null>(null);
const EditableCtx = createContext(true);

/** Wraps the level forms: sections start collapsed (an overview of counts) and stay as the user left them. */
export function ReadinessSections({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState<Set<string>>(() => new Set());
  const titles = useRef(new Set<string>());
  const value = useMemo<SectionsState>(() => ({
    isOpen: (t) => open.has(t),
    set: (t, v) => setOpen((prev) => { const n = new Set(prev); if (v) n.add(t); else n.delete(t); return n; }),
    all: (v) => setOpen(v ? new Set(titles.current) : new Set()),
    register: (t) => { titles.current.add(t); },
  }), [open]);
  return <SectionsCtx.Provider value={value}>{children}</SectionsCtx.Provider>;
}

function Missing({ c }: { c: LevelCompleteness | undefined }) {
  const ctx = useContext(SectionsCtx);
  return (
    <div className="readiness-bar">
      {!c ? <span /> : c.complete ? <p className="readiness-bar-text is-complete"><Icon name="check" size="sm" />All required fields for this level are captured.</p> : (
        <details className="missing">
          <summary>
            <Icon name="alert" size="sm" />{c.total - c.done} of {c.total} required still missing
          </summary>
          <ul className="missing-list">{c.missing.map((m) => <li key={m}>{FIELD_LABELS[m] ?? m}</li>)}</ul>
        </details>
      )}
      {ctx && (
        <span className="readiness-bar-actions">
          <button type="button" className="btn btn-small btn-ghost" onClick={() => ctx.all(true)}>Expand all sections</button>
          <button type="button" className="btn btn-small btn-ghost" onClick={() => ctx.all(false)}>Collapse all</button>
        </span>
      )}
    </div>
  );
}

function useSave(passportId: string, revision: Revision, onSaved: (r: Revision) => void) {
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  async function save(content: Record<string, unknown>) {
    setError(null);
    setSaved(false);
    setBusy(true);
    try {
      const r = await api<Revision>(`/passports/${passportId}/revisions/${revision.revision_number}/`, { method: "PATCH", body: { content } });
      setSaved(true);
      onSaved(r);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  return { error, saved, busy, save };
}

function Footer({ editable, busy, revision, label }: { editable: boolean; busy: boolean; revision: Revision; label: string }) {
  const ctx = useContext(SectionsCtx);
  // a required "not applicable" reason inside a collapsed section must be reachable when the browser reports it
  const revealInvalid = (e: MouseEvent<HTMLButtonElement>) => {
    const invalid = [...(e.currentTarget.form?.querySelectorAll<HTMLElement>("input:invalid, select:invalid, textarea:invalid") ?? [])];
    const titles = new Set(invalid.map((el) => el.closest<HTMLElement>("[data-section]")?.dataset.section).filter((t): t is string => !!t));
    if (ctx && titles.size) flushSync(() => titles.forEach((t) => ctx.set(t, true)));
  };
  return editable ? (
    <div className="form-actions sticky-actions">
      <span className="muted small">You can save an incomplete draft at any time.</span>
      <button className="btn btn-primary" disabled={busy} onClick={revealInvalid}>
        {label}
      </button>
    </div>
  ) : (
    <p className="muted small span-2">{revision.editable ? "Your role can view this draft but not edit it." : "This revision is not a draft and cannot be edited."}</p>
  );
}

const yesNo = (v: boolean | null | undefined) => (v == null ? "" : String(v));
const fromYesNo = (s: string) => (s === "" ? null : s === "true");
const filledValue = (v: unknown) => (typeof v === "string" ? v.trim() !== "" : Array.isArray(v) ? v.length > 0 : v !== null && v !== undefined);

/** Labelled field with Required/Optional and Missing tags kept outside the <label>, so the accessible name is just the label. */
function PField({ label, hint, required, missing, tags, children }: {
  label: string; hint?: ReactNode; required?: boolean; missing?: boolean; tags?: ReactNode; children: ReactElement<{ id?: string }>;
}) {
  const id = useId();
  return (
    <div className={`field pfield ${missing ? "is-missing" : ""}`}>
      <div className="field-head">
        <label className="field-label" htmlFor={id}>{label}</label>
        <span className={`req-tag ${required ? "is-required" : ""}`}>{required ? "Required" : "Optional"}</span>
        {missing && <span className="missing-tag">Missing</span>}
        {tags}
      </div>
      {cloneElement(children, { id })}
      {hint && <span className="field-hint">{hint}</span>}
    </div>
  );
}

/** A collapsible group of fields. The header shows how many required fields are still missing (counted from the
 *  rendered fields, so it follows edits before saving); the body keeps its fields mounted while collapsed. */
function Section({ title, children, note, grid = true, required, missing: missingOverride }: {
  title: string; children: ReactNode; note?: ReactNode; grid?: boolean; required?: boolean; missing?: boolean;
}) {
  const ctx = useContext(SectionsCtx);
  const editable = useContext(EditableCtx);
  ctx?.register(title);
  const open = ctx ? ctx.isOpen(title) : true;
  const body = useRef<HTMLDivElement>(null);
  const id = useId();
  const [counts, setCounts] = useState({ req: 0, miss: 0 });
  useLayoutEffect(() => {
    const el = body.current;
    if (!el) return;
    const req = required != null ? (required ? 1 : 0) : el.querySelectorAll(".pfield .req-tag.is-required").length;
    const miss = missingOverride != null ? (missingOverride ? 1 : 0) : el.querySelectorAll(".pfield.is-missing").length;
    if (req !== counts.req || miss !== counts.miss) setCounts({ req, miss });
  });
  const state = counts.miss ? `${counts.miss} missing` : counts.req ? "Complete" : "Optional";
  return (
    <section className={`rsection ${open ? "is-open" : ""} ${counts.miss ? "has-missing" : ""}`} data-section={title}>
      <h4 className="rsection-head">
        <button type="button" aria-expanded={open} aria-controls={id} onClick={() => ctx?.set(title, !open)} disabled={!ctx}>
          <Icon name="chevron" size="sm" className="rsection-chevron" />
          <span className="rsection-title">{title}</span>
          <span className={`rsection-state ${counts.miss ? "is-missing" : counts.req ? "is-complete" : ""}`}>{state}</span>
          {counts.req > 0 && <span className="rsection-count">{counts.req - counts.miss}/{counts.req} required</span>}
        </button>
      </h4>
      <div id={id} ref={body} className="rsection-body" hidden={!open}>
        <fieldset disabled={!editable} className="rsection-fields">
          <legend className="sr-only">{title}</legend>
          {note && <p className="muted small">{note}</p>}
          {grid ? <div className="form-grid">{children}</div> : children}
        </fieldset>
      </div>
    </section>
  );
}

function SourceTag({ source, editable, onVerify }: { source?: string; editable: boolean; onVerify: () => void }) {
  if (source === "client_submitted") {
    return (
      <span className="prov prov-client">
        Client-submitted · not verified
        {editable && <button type="button" className="link-btn small" onClick={onVerify}>Mark verified</button>}
      </span>
    );
  }
  if (source === "aries_verified") return <span className="prov prov-verified">Client value · verified by Aries</span>;
  if (source === "inherited_reference") {
    return (
      <span className="prov prov-unknown">
        Inherited from original part · reference, not verified
        {editable && <button type="button" className="link-btn small" onClick={onVerify}>Mark verified</button>}
      </span>
    );
  }
  return null;
}

const PROVISIONAL = "Provisional list (OQ-16): choose an entry or type another value.";

export function RL1Form({ passportId, revision, part, editable, onSaved }: { passportId: string; revision: Revision; part: Part | null; editable: boolean; onSaved: (r: Revision) => void }) {
  const opts = useFieldOptions();
  const initial = () => {
    if (!editable) return { values: revision.content?.rl1 ?? {}, filled: [] as string[] };
    const p = rl1Prefill(revision.content?.rl1 ?? {}, part);
    const sources = prefillSources(p.filled, part);
    if (Object.keys(sources).length) p.values = { ...p.values, value_sources: { ...(p.values.value_sources ?? {}), ...sources } };
    return p;
  };
  const [rl1, setRl1] = useState<RL1>(() => initial().values);
  const [prefilled, setPrefilled] = useState<string[]>(() => initial().filled);
  const { error, saved, busy, save } = useSave(passportId, revision, onSaved);
  useEffect(() => {
    const i = initial();
    setRl1(i.values);
    setPrefilled(i.filled);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [revision.id, revision.updated_at, part?.id]);

  const na = rl1.not_applicable ?? {};
  const sources = rl1.value_sources ?? {};
  const setNa = (n: Record<string, string>) => setRl1({ ...rl1, not_applicable: n });
  const set = (k: keyof RL1, v: unknown) => {
    // re-entering a value replaces the client-submitted one: it is now an Aries entry
    const nextSources = { ...sources };
    delete (nextSources as Record<string, string>)[k];
    setRl1({ ...rl1, [k]: v, value_sources: nextSources });
  };
  const required = (k: string) => RL1_REQUIRED.has(k) || (k === "rpm" && rl1.motion === "rotating");
  const str = (k: keyof RL1) => (rl1[k] as string | undefined) ?? "";

  const sourceTag = (k: keyof RL1) => (
    <SourceTag source={(sources as Record<string, string>)[k]} editable={editable}
      onVerify={() => setRl1({ ...rl1, value_sources: { ...sources, [k]: "aries_verified" } })} />
  );
  /** A field that can be marked "not applicable" with a reason (BR-006). */
  const field = (k: keyof RL1, control: ReactElement<{ id?: string }>, hint?: ReactNode, canNa = true) => {
    const marked = k in na;
    const prefillHint = prefilled.includes(k) ? "Pre-filled from the spare-part record; save to keep." : undefined;
    return (
      <div className="na-field" key={k}>
        {marked ? (
          <PField label={`${FIELD_LABELS[k]} — reason not applicable`} required>
            <input required value={na[k]} disabled={!editable} onChange={(e) => setNa({ ...na, [k]: e.target.value })} />
          </PField>
        ) : (
          <PField label={FIELD_LABELS[k]} hint={hint ?? prefillHint} required={required(k)} missing={required(k) && !filledValue(rl1[k])}
            tags={<SourceTag source={(sources as Record<string, string>)[k]} editable={editable}
              onVerify={() => setRl1({ ...rl1, value_sources: { ...sources, [k]: "aries_verified" } })} />}>
            {control}
          </PField>
        )}
        {editable && canNa && (
          <label className="na-toggle small">
            <input
              type="checkbox"
              checked={marked}
              onChange={(e) => {
                const next = { ...na };
                if (e.target.checked) next[k] = "";
                else delete next[k];
                setNa(next);
              }}
            />{" "}
            Not applicable
          </label>
        )}
      </div>
    );
  };
  const choice = (k: keyof RL1, options: [string, string][]) => (
    <select value={str(k)} onChange={(e) => set(k, e.target.value)}>
      <option value="">—</option>
      {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select>
  );
  const bool = (k: "cad_3d_available" | "drawings_2d_available") => (
    <select value={yesNo(rl1[k])} onChange={(e) => set(k, fromYesNo(e.target.value))}>
      <option value="">—</option>
      <option value="true">Yes</option>
      <option value="false">No</option>
    </select>
  );

  function submit(e: FormEvent) {
    e.preventDefault();
    void save({ rl1 });
  }

  return (
    <form className="form-grid passport-form" onSubmit={submit} aria-label="Readiness level 1 data">
      <ErrorNotice error={error} />
      {saved && <div className="notice notice-success" role="status">R-L1 saved.</div>}
      <EditableCtx.Provider value={editable}>
      <div className="form-sections span-2" key={`${revision.id}-${revision.updated_at}`} role="group" aria-label="R-L1 — identification and operating context">
        <Missing c={revision.completeness?.rl1} />
        <Section title="Design data available">
          {field("cad_3d_available", bool("cad_3d_available"))}
          {field("drawings_2d_available", bool("drawings_2d_available"))}
        </Section>
        <Section title="Material">
          {field("original_material_grade", <ComboText value={str("original_material_grade")} onChange={(v) => set("original_material_grade", v)} options={opts.list("material_grades")} />, PROVISIONAL)}
          {field("material_identification_method", choice("material_identification_method", [["pmi", "PMI"], ["destructive", "Destructive"], ["oem", "OEM datasheet"]]))}
          <PField label={FIELD_LABELS.proposed_material} hint="BR-009: replacement material, if one is proposed." tags={sourceTag("proposed_material")}>
            <ComboText value={str("proposed_material")} onChange={(v) => set("proposed_material", v)} options={opts.list("material_grades")} />
          </PField>
          <PField label={FIELD_LABELS.proposed_material_reason} hint="BR-009: engineering reason. Not shown as approved until approval exists (OQ-35)."
            tags={sourceTag("proposed_material_reason")}>
            <ComboText value={str("proposed_material_reason")} onChange={(v) => set("proposed_material_reason", v)} options={opts.list("proposed_material_reasons")}
              placeholder="Pick a common reason or write the engineering reason" />
          </PField>
        </Section>
        <Section title="Geometry and use">
          {field("part_size", <SizeInput value={str("part_size")} onChange={(v) => set("part_size", v)} units={opts.units("length")} />,
            prefilled.includes("part_size") ? "Pre-filled from the spare-part record; save to keep." : "Overall envelope. Other formats are kept as entered.")}
          {field("application", <ComboText value={str("application")} onChange={(v) => set("application", v)} options={opts.list("applications")} />)}
          <div className="span-2">
            {field("technical_description", <textarea rows={3} value={str("technical_description")} onChange={(e) => set("technical_description", e.target.value)} />,
              "Engineering description: function, features, condition.")}
          </div>
        </Section>
        <Section title="Operating context">
          {field("atmosphere", choice("atmosphere", [["corrosive", "Corrosive"], ["non_corrosive", "Non-corrosive"]]))}
          <PField label={FIELD_LABELS.operating_environment} hint="Optional detail beside the BR-006 atmosphere.">
            <SelectOther value={str("operating_environment")} onChange={(v) => set("operating_environment", v)} options={opts.list("operating_environments")} />
          </PField>
          {field("motion", choice("motion", [["static", "Static"], ["rotating", "Rotating"]]))}
          {field("rpm", <NumberUnit value={str("rpm")} onChange={(v) => set("rpm", v)} units={[]} fixedUnit="rpm" step="1" />,
            rl1.motion === "rotating" ? "Required for rotating parts." : "Only needed for rotating parts.")}
          {field("ip_status", choice("ip_status", [["obsolete", "Obsolete"], ["active", "Active"]]))}
        </Section>
      </div>
      </EditableCtx.Provider>
      <Footer editable={editable} busy={busy} revision={revision} label="Save R-L1 draft" />
    </form>
  );
}

const PROPERTIES: [AcceptanceRow["property"], string][] = [
  ["tensile", "Tensile strength"], ["yield", "Yield strength"], ["elongation", "Elongation"], ["hardness", "Hardness"], ["impact", "Impact"], ["other", "Other"],
];

export function RL2Form({ passportId, revision, editable, onSaved, files = [] }: {
  passportId: string; revision: Revision; editable: boolean; onSaved: (r: Revision) => void; files?: EngineeringFile[];
}) {
  const opts = useFieldOptions();
  const [rl2, setRl2] = useState<RL2>(revision.content?.rl2 ?? {});
  const { error, saved, busy, save } = useSave(passportId, revision, onSaved);
  useEffect(() => setRl2(revision.content?.rl2 ?? {}), [revision.id, revision.updated_at]);
  const set = (k: keyof RL2, v: unknown) => setRl2({ ...rl2, [k]: v });
  const spec: ManufacturingSpec = rl2.manufacturing_spec ?? {};
  const setSpec = (k: keyof ManufacturingSpec, v: unknown) => setRl2({ ...rl2, manufacturing_spec: { ...spec, [k]: v } });
  const rows = rl2.mechanical_acceptance ?? [];
  const params = spec.process_parameters ?? [];
  const s2 = (k: keyof RL2) => (rl2[k] as string | undefined) ?? "";
  const ss = (k: keyof ManufacturingSpec) => (spec[k] as string | undefined) ?? "";
  const f = (key: string, control: ReactElement<{ id?: string }>, hint?: ReactNode, value?: unknown) => (
    <PField key={key} label={FIELD_LABELS[key]} hint={hint} required={RL2_REQUIRED.has(key)} missing={RL2_REQUIRED.has(key) && !filledValue(value)}>
      {control}
    </PField>
  );
  const hours = (k: "printing_hours" | "post_processing_hours") =>
    f(`manufacturing_spec.${k}`, (
      <span className="ctl ctl-number">
        <input type="number" min={0} step="0.25" inputMode="decimal" value={spec[k] ?? ""} onChange={(e) => setSpec(k, e.target.value === "" ? null : Number(e.target.value))} />
        <span className="unit">h</span>
      </span>
    ), undefined, spec[k]);
  const docList = "rl2-doc-titles";

  return (
    <form className="form-grid passport-form" onSubmit={(e) => { e.preventDefault(); void save({ rl2 }); }} aria-label="Readiness level 2 data">
      <ErrorNotice error={error} />
      {saved && <div className="notice notice-success" role="status">R-L2 saved.</div>}
      <EditableCtx.Provider value={editable}>
      <div className="form-sections span-2" key={`${revision.id}-${revision.updated_at}`} role="group" aria-label="R-L2 — manufacturing solution and acceptance">
        <Missing c={revision.completeness?.rl2} />
        <Section title="Manufacturing solution">
          <PField label={FIELD_LABELS.manufacturing_process} hint="Optional controlled selection; describe the full solution below.">
            <SelectOther value={s2("manufacturing_process")} onChange={(v) => set("manufacturing_process", v)} options={opts.list("manufacturing_processes")} />
          </PField>
          {f("material_selection", <ComboText value={s2("material_selection")} onChange={(v) => set("material_selection", v)} options={opts.list("material_grades")} />, PROVISIONAL, rl2.material_selection)}
          {f("material_category", (
            <select value={rl2.material_category ?? ""} onChange={(e) => set("material_category", e.target.value)}>
              <option value="">—</option>
              <option value="equivalent">Equivalent</option>
              <option value="superior">Superior</option>
            </select>
          ), undefined, rl2.material_category)}
          {f("feedstock", <ComboText value={s2("feedstock")} onChange={(v) => set("feedstock", v)} options={opts.list("feedstocks")} />, PROVISIONAL, rl2.feedstock)}
          <div className="span-2">
            {f("manufacturing_solution", <textarea rows={2} value={s2("manufacturing_solution")} onChange={(e) => set("manufacturing_solution", e.target.value)} />,
              "Engineering judgement: process route, heat treatment, machining of functional faces.", rl2.manufacturing_solution)}
          </div>
        </Section>
        <Section title="Criticality and standards">
          {f("criticality_amsl", <input value={s2("criticality_amsl")} onChange={(e) => set("criticality_amsl", e.target.value)} />,
            "Free text: approved AMSL classes are not defined yet (OQ-36). Recorded as entered; never used for eligibility or approval.", rl2.criticality_amsl)}
          <div className="span-2">
            {f("applicable_standards", <MultiSelect label={FIELD_LABELS.applicable_standards} value={s2("applicable_standards")} onChange={(v) => set("applicable_standards", v)}
              options={opts.list("applicable_standards")} />, "Provisional list; which standards are mandatory is open (OQ-21).", rl2.applicable_standards)}
          </div>
        </Section>
        <Section title="Quality and acceptance">
          {f("dimensional_tolerances", <ComboText value={s2("dimensional_tolerances")} onChange={(v) => set("dimensional_tolerances", v)} options={opts.list("dimensional_tolerances")} />,
            "General tolerance class; add specific fits after a semicolon (e.g. ISO 2768-mK; bores H7).", rl2.dimensional_tolerances)}
          {f("mtc_required", (
            <select value={yesNo(rl2.mtc_required)} onChange={(e) => set("mtc_required", fromYesNo(e.target.value))}>
              <option value="">—</option>
              <option value="true">Yes</option>
              <option value="false">No</option>
            </select>
          ), undefined, rl2.mtc_required)}
          <div className="span-2">
            {f("ndt", <MultiSelect label={FIELD_LABELS.ndt} value={s2("ndt")} onChange={(v) => set("ndt", v)} options={opts.list("inspection_methods")} />, undefined, rl2.ndt)}
          </div>
          {f("inspection_test_plan", (
            <span className="ctl">
              <input list={docList} value={s2("inspection_test_plan")} onChange={(e) => set("inspection_test_plan", e.target.value)} />
              <datalist id={docList}>{files.map((x) => <option key={x.id} value={x.title} />)}</datalist>
            </span>
          ), "Document reference; pick from this passport's documents or type a reference. Link the ITP file itself under R-L3.", rl2.inspection_test_plan)}
          {f("test_coupons", <textarea rows={2} value={s2("test_coupons")} onChange={(e) => set("test_coupons", e.target.value)} />, undefined, rl2.test_coupons)}
        </Section>
        <Section title="Mechanical acceptance" grid={false} required missing={rows.length === 0}>
          <div className="table-scroll">
            <table className="table table-edit" aria-label="Mechanical acceptance table">
              <thead><tr><th>Property</th><th>Requirement</th><th>Unit</th><th>Standard</th><th>Inspection frequency</th><th /></tr></thead>
              <tbody>
                {rows.map((r, i) => {
                  const upd = (patch: Partial<AcceptanceRow>) => set("mechanical_acceptance", rows.map((x, j) => (j === i ? { ...x, ...patch } : x)));
                  return (
                    <tr key={i}>
                      <td><select aria-label={`Property ${i + 1}`} value={r.property} onChange={(e) => upd({ property: e.target.value as AcceptanceRow["property"] })}>{PROPERTIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></td>
                      <td><input aria-label={`Requirement ${i + 1}`} value={r.requirement ?? ""} placeholder="≥ 485" onChange={(e) => upd({ requirement: e.target.value })} /></td>
                      <td><ComboText id={`acc-unit-${i}`} ariaLabel={`Unit ${i + 1}`} value={r.unit ?? ""} placeholder="MPa" options={opts.units("mechanical").map((v) => ({ value: v }))} onChange={(v) => upd({ unit: v })} /></td>
                      <td><ComboText id={`acc-std-${i}`} ariaLabel={`Standard ${i + 1}`} value={r.standard ?? ""} placeholder="ISO 6892-1" options={opts.list("acceptance_standards")} onChange={(v) => upd({ standard: v })} /></td>
                      <td><ComboText id={`acc-freq-${i}`} ariaLabel={`Inspection frequency ${i + 1}`} value={r.frequency ?? ""} placeholder="Per build" options={opts.list("inspection_frequencies")} onChange={(v) => upd({ frequency: v })} /></td>
                      <td>{editable && <button type="button" className="btn btn-small" onClick={() => set("mechanical_acceptance", rows.filter((_, j) => j !== i))}>Remove</button>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {editable && <button type="button" className="btn btn-small" onClick={() => set("mechanical_acceptance", [...rows, { property: "tensile", requirement: "", unit: "", standard: "" }])}>Add acceptance row</button>}
        </Section>
        <Section title="Manufacturing specification (BR-026)">
          {f("manufacturing_spec.job_number", <input value={ss("job_number")} onChange={(e) => setSpec("job_number", e.target.value)} />, undefined, spec.job_number)}
          {f("manufacturing_spec.machine", <ComboText value={ss("machine")} onChange={(v) => setSpec("machine", v)} options={opts.list("machines")} />, PROVISIONAL, spec.machine)}
          {f("manufacturing_spec.material", <ComboText value={ss("material")} onChange={(v) => setSpec("material", v)} options={opts.list("material_grades")} />, undefined, spec.material)}
          {f("manufacturing_spec.feedstock", <ComboText value={ss("feedstock")} onChange={(v) => setSpec("feedstock", v)} options={opts.list("feedstocks")} />, "Powder or wire, lot if known.", spec.feedstock)}
          {f("manufacturing_spec.layer_thickness", <NumberUnit value={ss("layer_thickness")} onChange={(v) => setSpec("layer_thickness", v)} units={opts.units("layer")} />, undefined, spec.layer_thickness)}
          {f("manufacturing_spec.inert_gas", <SelectOther value={ss("inert_gas")} onChange={(v) => setSpec("inert_gas", v)} options={opts.list("inert_gases")} />, undefined, spec.inert_gas)}
          {f("manufacturing_spec.support_strategy", <SelectOther value={ss("support_strategy")} onChange={(v) => setSpec("support_strategy", v)} options={opts.list("support_strategies")} />, undefined, spec.support_strategy)}
          {f("manufacturing_spec.build_orientation", <ComboText value={ss("build_orientation")} onChange={(v) => setSpec("build_orientation", v)} options={opts.list("build_orientations")} />, undefined, spec.build_orientation)}
          {f("manufacturing_spec.heat_treatment", <HeatTreatmentInput value={ss("heat_treatment")} onChange={(v) => setSpec("heat_treatment", v)} processes={opts.list("heat_treatments")} />,
            "Process with temperature and hold time. Other descriptions are kept as entered.", spec.heat_treatment)}
          {f("manufacturing_spec.machining", <input value={ss("machining")} onChange={(e) => setSpec("machining", e.target.value)} />, "Faces, fits and finishes to machine (e.g. Bore H7).", spec.machining)}
          <div className="span-2">
            {f("manufacturing_spec.post_processing", <MultiSelect label={FIELD_LABELS["manufacturing_spec.post_processing"]} value={ss("post_processing")}
              onChange={(v) => setSpec("post_processing", v)} options={opts.list("post_processing")} />, undefined, spec.post_processing)}
          </div>
          {hours("printing_hours")}
          {hours("post_processing_hours")}
        </Section>
        <Section title="Process parameters (BR-041)" grid={false}>
          <div className="table-scroll">
            <table className="table table-edit" aria-label="Process parameters">
              <thead><tr><th>Parameter</th><th>Value</th><th>Unit</th><th /></tr></thead>
              <tbody>
                {params.map((p, i) => {
                  const upd = (patch: Partial<ProcessParameter>) => setSpec("process_parameters", params.map((x, j) => (j === i ? { ...x, ...patch } : x)));
                  return (
                    <tr key={i}>
                      <td><ComboText id={`param-${i}`} ariaLabel={`Parameter ${i + 1}`} value={p.name} placeholder="Laser power" options={opts.list("process_parameters")} onChange={(v) => upd({ name: v })} /></td>
                      <td><input aria-label={`Value ${i + 1}`} inputMode="decimal" value={p.value ?? ""} onChange={(e) => upd({ value: e.target.value })} /></td>
                      <td><ComboText id={`param-unit-${i}`} ariaLabel={`Parameter unit ${i + 1}`} value={p.unit ?? ""} placeholder="W" options={opts.units("parameters").map((v) => ({ value: v }))} onChange={(v) => upd({ unit: v })} /></td>
                      <td>{editable && <button type="button" className="btn btn-small" onClick={() => setSpec("process_parameters", params.filter((_, j) => j !== i))}>Remove</button>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {editable && <button type="button" className="btn btn-small" onClick={() => setSpec("process_parameters", [...params, { name: "", value: "", unit: "" }])}>Add parameter</button>}
        </Section>
      </div>
      </EditableCtx.Provider>
      <Footer editable={editable} busy={busy} revision={revision} label="Save R-L2 draft" />
    </form>
  );
}

export function RL3Form({ passportId, revision, files, editable, onSaved, onOpenFile }: {
  passportId: string; revision: Revision; files: EngineeringFile[]; editable: boolean; onSaved: (r: Revision) => void; onOpenFile: (f: EngineeringFile) => void;
}) {
  const [rl3, setRl3] = useState<RL3>(revision.content?.rl3 ?? {});
  const { error, saved, busy, save } = useSave(passportId, revision, onSaved);
  useEffect(() => setRl3(revision.content?.rl3 ?? {}), [revision.id, revision.updated_at]);
  const evidence = rl3.evidence ?? {};
  const byId = new Map(files.map((f) => [f.id, f]));

  return (
    <form className="form-grid passport-form" onSubmit={(e) => { e.preventDefault(); void save({ rl3 }); }} aria-label="Readiness level 3 evidence">
      <ErrorNotice error={error} />
      {saved && <div className="notice notice-success" role="status">R-L3 evidence saved.</div>}
      <fieldset disabled={!editable} className="fieldset">
        <legend>R-L3 — document evidence</legend>
        <p className="muted small">
          Link each required document to a file uploaded to this passport. R-L3 can only be confirmed once all five are attached and QA-verified;
          QA verification is not available until the approval rules are decided (OQ-35).
        </p>
        <Missing c={revision.completeness?.rl3} />
        <div className="table-scroll">
          <table className="table evidence-table" aria-label="R-L3 evidence">
            <thead><tr><th>Required document</th><th>Linked file</th><th>QA verification</th></tr></thead>
            <tbody>
              {RL3_EVIDENCE.map((key) => {
                const linked = evidence[key] ? byId.get(evidence[key]!) : undefined;
                return (
                  <tr key={key} className={linked ? "" : "is-missing"}>
                    <td>{FIELD_LABELS[key]} <span className="req-tag is-required">Required</span>{!linked && <span className="missing-tag">Missing</span>}</td>
                    <td>
                      <select aria-label={FIELD_LABELS[key]} value={evidence[key] ?? ""} onChange={(e) => setRl3({ ...rl3, evidence: { ...evidence, [key]: e.target.value || null } })}>
                        <option value="">None linked</option>
                        {files.map((f) => <option key={f.id} value={f.id}>{f.title} ({(f.kind ?? "").toUpperCase()}, v{f.latest_version?.version_number})</option>)}
                      </select>
                      {linked && <button type="button" className="link-btn small" onClick={() => onOpenFile(linked)}>Open</button>}
                    </td>
                    <td><span className="muted small">Pending (OQ-35)</span></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <PField label="Evidence notes">
          <textarea rows={2} value={rl3.notes ?? ""} onChange={(e) => setRl3({ ...rl3, notes: e.target.value })} />
        </PField>
      </fieldset>
      <div className="form-actions">
        <DisabledAction label="Confirm R-L3 (QA)" reason="QA verification rules pending (OQ-35)." />
        {editable && <button className="btn btn-primary" disabled={busy} aria-busy={busy}>Save R-L3 evidence</button>}
      </div>
      {!editable && <p className="muted small span-2">{revision.editable ? "Your role can view this draft but not edit it." : "This revision is not a draft and cannot be edited."}</p>}
    </form>
  );
}
