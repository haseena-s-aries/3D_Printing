import type { Part, Project } from "@passport/api-types";
import { useState, type FormEvent } from "react";

import { PART_CATEGORIES, PART_CRITICALITY, PartFieldInput, usePartFieldOptions, type StructuredPartField } from "./PartFieldInput";
import { Provenance } from "./PartSubmission";
import { ErrorNotice, Field } from "./ui";

export { PART_CATEGORIES, PART_CRITICALITY };

export type PartFields = Pick<Part, "part_number" | "name" | "category" | "criticality" | "original_material" | "dimensions" | "application" | "description" | "project" | "manufacturer" | "equipment_reference"
  | "plant" | "functional_location" | "equipment_tag" | "customer_abc_class" | "manufacturer_reference" | "oem_part_number">;

export const EMPTY_PART: PartFields = {
  part_number: "", name: "", category: "mechanical", criticality: "unknown", original_material: "", dimensions: "", application: "", description: "", project: null,
  manufacturer: "", equipment_reference: "",
  plant: "", functional_location: "", equipment_tag: "", customer_abc_class: "", manufacturer_reference: "", oem_part_number: "",
};

// CN-007 customer inventory identifiers: recorded as supplied; not engineering specifications.
const INVENTORY: [keyof PartFields, string, number, string?][] = [
  ["plant", "Plant", 80], ["functional_location", "Functional location", 80], ["equipment_tag", "Equipment tag", 60],
  ["customer_abc_class", "Customer ABC indicator", 20, "As supplied by the customer. Its meaning is not confirmed; it is not criticality."],
  ["manufacturer_reference", "Manufacturer reference", 60, "Customer/ERP manufacturer code. Not an OEM part number."],
  ["oem_part_number", "OEM part number", 80, "Only a verified OEM part number."],
];

const STRUCTURED: [StructuredPartField, string, string?][] = [
  ["category", "Category"],
  ["criticality", "Criticality", "Existing classifications only. Approved criticality rules are not defined yet (OQ-36)."],
  ["equipment_reference", "Equipment / machinery", "Your company's recorded equipment, or type a new one."],
  ["manufacturer", "Manufacturer / OEM"],
  ["application", "Application"],
  ["original_material", "Original material", "Provisional grade list (OQ-16); type another grade if needed."],
  ["dimensions", "Dimensions", "L × W × H or Ø × H. Other recorded formats are kept exactly as entered."],
  ["project", "Project", "Optional digitisation project this part belongs to."],
];

/** Spare-part master data form (Aries Engineers), used for both creating and editing a part. Uses the same structured
 *  controls as client submissions, Clone Part and the passport forms; provenance is shown when editing. */
export default function PartForm({ initial, submitLabel, onSubmit }: {
  initial: PartFields & Partial<Pick<Part, "field_provenance" | "origin" | "unknown_fields">>; submitLabel: string;
  onSubmit: (values: PartFields) => Promise<void>; projects?: Project[];
}) {
  const opts = usePartFieldOptions();
  const [form, setForm] = useState<PartFields>({ ...EMPTY_PART, ...initial });
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof PartFields, v: string | null) => setForm({ ...form, [k]: v });
  const editing = "field_provenance" in initial;
  const prov = (f: string) => editing && initial.origin === "client" ? <Provenance part={initial as Part} field={f} /> : null;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await onSubmit(form);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="form-grid" onSubmit={submit} aria-label="Spare part master data">
      <ErrorNotice error={error} />
      <Field label="Part number" hint="Client or OEM number, unique in this organisation.">
        <input required maxLength={80} value={form.part_number} onChange={(e) => set("part_number", e.target.value)} />
      </Field>
      <Field label="Name">
        <input required maxLength={200} value={form.name} onChange={(e) => set("name", e.target.value)} />
      </Field>
      {STRUCTURED.map(([k, l, hint]) => (
        <div key={k} className="sub-field">
          <Field label={l} hint={hint}>
            <PartFieldInput field={k} opts={opts} value={(form[k] as string | null) ?? ""} onChange={(v) => set(k, k === "project" ? v || null : v)} />
          </Field>
          {prov(k)}
        </div>
      ))}
      <h3 className="span-2 form-section">Customer inventory identifiers</h3>
      {INVENTORY.map(([k, l, max, hint]) => (
        <Field key={k} label={l} hint={hint}>
          <input maxLength={max} value={(form[k] as string | null) ?? ""} onChange={(e) => set(k, e.target.value)} />
        </Field>
      ))}
      <div className="span-2 sub-field">
        <Field label="Description">
          <textarea rows={2} value={form.description ?? ""} onChange={(e) => set("description", e.target.value)} />
        </Field>
        {prov("description")}
      </div>
      <div className="form-actions">
        <button className="btn btn-primary" disabled={busy} aria-busy={busy}>{submitLabel}</button>
      </div>
    </form>
  );
}
