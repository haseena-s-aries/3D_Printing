/**
 * Clone Part (BR-033 customisation, CN-003). The client starts a new part from an accepted part of its own company,
 * e.g. to propose a different material. The original part, its files and its passport are never changed; the clone is
 * a separate record linked to the original, held Pending Aries review, with nothing that implies engineering approval.
 */
import type { Part } from "@passport/api-types";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { ComboText, useFieldOptions } from "../components/passport/controls";
import { PartFieldInput, usePartFieldOptions, type StructuredPartField } from "../components/PartFieldInput";
import { CloneChanges, type ChangeRow } from "../components/PartLineage";
import { BackLink, Card, ErrorNotice, Field, Loading, PageHeader } from "../components/ui";

const EDITABLE: [keyof Values, string][] = [
  ["name", "Part name"], ["equipment_reference", "Equipment / machinery"], ["manufacturer", "Manufacturer / OEM"],
  ["application", "Application"], ["dimensions", "Dimensions"], ["description", "Description"],
];

type Values = {
  part_number: string; name: string; equipment_reference: string; manufacturer: string; application: string; dimensions: string;
  description: string; proposed_material: string; material_change_reason: string; client_remarks: string;
};

const same = (a?: string | null, b?: string | null) => (a ?? "").trim().toLowerCase() === (b ?? "").trim().toLowerCase();

export function canClone(part: Pick<Part, "review_state">, can: (c: string) => boolean): boolean {
  return can("parts.submit") && (part.review_state === "not_required" || part.review_state === "accepted");
}

export default function PartClonePage() {
  const { id } = useParams();
  const source = useApi<Part>(`/parts/${id}/`);
  if (source.loading && !source.data) return <Loading />;
  if (source.error || !source.data) return <ErrorNotice error={source.error ?? new Error("Not found")} />;
  return <CloneForm source={source.data} />;
}

function CloneForm({ source }: { source: Part }) {
  const navigate = useNavigate();
  const opts = useFieldOptions();
  const partOpts = usePartFieldOptions();
  const [v, setV] = useState<Values>({
    part_number: "", name: source.name, equipment_reference: source.equipment_reference ?? "", manufacturer: source.manufacturer ?? "",
    application: source.application ?? "", dimensions: source.dimensions ?? "", description: source.description ?? "",
    proposed_material: "", material_change_reason: "", client_remarks: "",
  });
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof Values, value: string) => setV({ ...v, [k]: value });
  const materialChanged = !!v.proposed_material.trim() && !same(v.proposed_material, source.original_material);
  const missing = [
    !v.part_number.trim() && "New part number",
    same(v.part_number, source.part_number) && "A part number different from the original",
    !v.name.trim() && "Part name",
    materialChanged && !v.material_change_reason.trim() && "Reason for the material change",
  ].filter(Boolean) as string[];

  const rows: ChangeRow[] = [
    ...EDITABLE.map(([k, label]) => ({ field: label, original: String(source[k as keyof Part] ?? ""), clone: v[k], changed: !same(String(source[k as keyof Part] ?? ""), v[k]) })),
    ...(v.proposed_material.trim() ? [{ field: "Material", original: source.original_material ?? "", clone: v.proposed_material, changed: materialChanged }] : []),
  ];

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const clone = await api<Part>(`/parts/${source.id}/clone/`, { body: v });
      navigate(`/parts/${clone.id}?cloned=1`);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <BackLink to={`/parts/${source.id}`}>{source.part_number}</BackLink>
      <PageHeader title={`Clone part ${source.part_number}`}
        subtitle="Create a new part based on this one, for example in a different material. The original part is not changed." />
      <Card title="Original part (not changed)">
        <dl className="facts" aria-label="Original part">
          <dt>Part number</dt><dd><Link to={`/parts/${source.id}`}>{source.part_number}</Link></dd>
          <dt>Name</dt><dd>{source.name}</dd>
          <dt>Material</dt><dd>{source.original_material || "—"}</dd>
          <dt>Description</dt><dd>{source.description || "—"}</dd>
          <dt>Digital passport</dt><dd>{source.passport_number ? `${source.passport_number}${source.revision ? ` rev ${source.revision.number}` : ""} (reference only, not copied)` : "None"}</dd>
        </dl>
      </Card>
      <Card title="New part (clone)">
        <form className="submission-form" onSubmit={submit} aria-label="Clone part">
          <p className="notice notice-info small">
            The clone is a <strong>separate spare part</strong> linked to {source.part_number}. It starts as <strong>Pending Aries review</strong>.
            It does not inherit the original's passport approval, evidence, publication or manufacturing eligibility, and the original CAD
            files stay with the original part as references. Any new material is assessed by Aries Engineering for suitability.
          </p>
          <ErrorNotice error={error} />
          <fieldset className="fieldset">
            <legend>Identification</legend>
            <div className="form-grid">
              <Field label="New part number *" hint="Must be unique in your organisation and different from the original.">
                <input value={v.part_number} onChange={(e) => set("part_number", e.target.value)} placeholder={`e.g. ${source.part_number}-B`} />
              </Field>
              {EDITABLE.slice(0, 5).map(([k, label]) => (
                <Field key={k} label={`${label}${k === "name" ? " *" : ""}`} hint={same(String(source[k as keyof Part] ?? ""), v[k]) ? "Same as original" : "Changed from original"}>
                  {k === "name" ? <input value={v[k]} onChange={(e) => set(k, e.target.value)} />
                    : <PartFieldInput field={k as StructuredPartField} opts={partOpts} value={v[k]} onChange={(x) => set(k, x)} />}
                </Field>
              ))}
              <div className="span-2">
                <Field label="Description" hint={same(source.description, v.description) ? "Same as original" : "Changed from original"}>
                  <textarea rows={3} value={v.description} onChange={(e) => set("description", e.target.value)} />
                </Field>
              </div>
            </div>
          </fieldset>
          <fieldset className="fieldset">
            <legend>Material</legend>
            <div className="form-grid">
              <Field label="Original material">
                <input value={source.original_material || "Not recorded"} readOnly disabled />
              </Field>
              <Field label="Proposed new material" hint="Leave empty to keep the original material. Provisional list (OQ-16); type another grade if needed.">
                <ComboText value={v.proposed_material} onChange={(x) => set("proposed_material", x)} options={opts.list("material_grades")} />
              </Field>
              <div className="span-2">
                <Field label={`Reason for the material change${materialChanged ? " *" : ""}`} hint="Required when you propose a different material.">
                  <textarea rows={2} value={v.material_change_reason} onChange={(e) => set("material_change_reason", e.target.value)} />
                </Field>
              </div>
            </div>
          </fieldset>
          <fieldset className="fieldset">
            <legend>Remarks to Aries</legend>
            <Field label="Remarks (optional)" hint="Anything Aries should know, e.g. operating conditions or required date.">
              <textarea rows={2} value={v.client_remarks} onChange={(e) => set("client_remarks", e.target.value)} />
            </Field>
          </fieldset>
          <fieldset className="fieldset">
            <legend>Proposed changes compared with the original</legend>
            <CloneChanges rows={rows} />
          </fieldset>
          <div className="form-actions sticky-actions">
            {missing.length > 0 && <span className="muted small">Still needed: {missing.join(", ")}</span>}
            <button className="btn btn-primary" disabled={busy || missing.length > 0}>{busy ? "Creating…" : "Create clone for Aries review"}</button>
          </div>
        </form>
      </Card>
    </>
  );
}

/** Client correction of an open clone (while Pending or Corrections requested). Lineage and part number stay fixed. */
export function CloneEditForm({ part, onDone }: { part: Part; onDone: (p: Part) => void }) {
  const opts = useFieldOptions();
  const partOpts = usePartFieldOptions();
  const original = (part.source_snapshot ?? {}) as Record<string, string>;
  const [v, setV] = useState({
    name: part.name, equipment_reference: part.equipment_reference ?? "", manufacturer: part.manufacturer ?? "",
    application: part.application ?? "", dimensions: part.dimensions ?? "", description: part.description ?? "",
    proposed_material: part.proposed_material ?? "", material_change_reason: part.material_change_reason ?? "", client_remarks: part.client_remarks ?? "",
  });
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const materialChanged = !!v.proposed_material.trim() && !same(v.proposed_material, original.original_material);
  const missing = [!v.name.trim() && "Part name", materialChanged && !v.material_change_reason.trim() && "Reason for the material change"].filter(Boolean) as string[];
  return (
    <form className="submission-form" aria-label="Correct clone" onSubmit={async (e) => {
      e.preventDefault();
      setBusy(true);
      setError(null);
      try {
        onDone(await api<Part>(`/parts/${part.id}/`, { method: "PATCH", body: v }));
      } catch (err) {
        setError(err);
      } finally {
        setBusy(false);
      }
    }}>
      <ErrorNotice error={error} />
      <div className="form-grid">
        {EDITABLE.slice(0, 5).map(([k, label]) => (
          <Field key={k} label={`${label}${k === "name" ? " *" : ""}`} hint={same(original[k], v[k as keyof typeof v]) ? "Same as original" : "Changed from original"}>
            {k === "name" ? <input value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} />
              : <PartFieldInput field={k as StructuredPartField} opts={partOpts} value={v[k as keyof typeof v]} onChange={(x) => setV({ ...v, [k]: x })} />}
          </Field>
        ))}
        <div className="span-2">
          <Field label="Description" hint={same(original.description, v.description) ? "Same as original" : "Changed from original"}>
            <textarea rows={3} value={v.description} onChange={(e) => setV({ ...v, description: e.target.value })} />
          </Field>
        </div>
        <Field label="Proposed new material" hint={`Original: ${original.original_material || "not recorded"}`}>
          <ComboText value={v.proposed_material} onChange={(x) => setV({ ...v, proposed_material: x })} options={opts.list("material_grades")} />
        </Field>
        <Field label={`Reason for the material change${materialChanged ? " *" : ""}`}>
          <textarea rows={2} value={v.material_change_reason} onChange={(e) => setV({ ...v, material_change_reason: e.target.value })} />
        </Field>
        <div className="span-2">
          <Field label="Remarks (optional)">
            <textarea rows={2} value={v.client_remarks} onChange={(e) => setV({ ...v, client_remarks: e.target.value })} />
          </Field>
        </div>
      </div>
      <div className="form-actions">
        {missing.length > 0 && <span className="muted small">Still needed: {missing.join(", ")}</span>}
        <button className="btn btn-primary" disabled={busy || missing.length > 0}>Save changes</button>
      </div>
    </form>
  );
}
