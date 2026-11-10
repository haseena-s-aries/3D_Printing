/**
 * One set of structured inputs for spare-part master data (CN-003), used by New Part, Edit Part, client submissions and
 * Clone Part, built from the same controls and master data as the passport forms (./passport/controls).
 *
 * - Material, application, OEM: searchable lists (provisional master data, OQ-16, plus values already used in this
 *   company) with free entry for anything else.
 * - Equipment / machinery: this company's own recorded equipment, with free entry for new equipment.
 * - Dimensions: L × W × H or Ø × H with unit; any other stored text stays exactly as entered ("Custom value").
 * - Category and criticality: the existing fixed choices only; project: this company's projects visible to the user.
 * Stored values are never rewritten unless the user changes them.
 */
import type { Paginated, PartFieldValues, Project } from "@passport/api-types";

import { useApi } from "../api/useApi";
import { ComboText, SizeInput, useFieldOptions, type Option } from "./passport/controls";
import { label } from "./ui";

export const PART_CATEGORIES = ["mechanical", "electrical", "electronic", "other", "unknown"];
export const PART_CRITICALITY: [string, string][] = [["unknown", "Not assessed"], ["critical", "Critical"], ["non_critical", "Non-critical"]];

export type StructuredPartField = "original_material" | "application" | "equipment_reference" | "manufacturer" | "dimensions"
  | "category" | "criticality" | "project";

const LIST: Partial<Record<StructuredPartField, string>> = { original_material: "material_grades", application: "applications", manufacturer: "manufacturers" };

export function mergeOptions(own: string[], list: Option[]): Option[] {
  const seen = new Set<string>();
  const out: Option[] = [];
  for (const o of [...own.map((value) => ({ value, group: "Used in your company" })), ...list]) {
    const key = o.value.trim().toLowerCase();
    if (!seen.has(key)) {
      seen.add(key);
      out.push(o);
    }
  }
  return out;
}

/** Options for the structured part fields: provisional master data plus this company's recorded values. */
export function usePartFieldOptions() {
  const field = useFieldOptions();
  const used = useApi<PartFieldValues>("/parts/field-values/");
  const projects = useApi<Paginated<Project>>("/projects/", { query: { page_size: 200 } });
  return {
    options(f: StructuredPartField): Option[] {
      const own = (used.data?.[f as keyof PartFieldValues] as string[] | undefined) ?? [];
      return f === "equipment_reference" ? own.map((value) => ({ value })) : mergeOptions(own, field.list(LIST[f] ?? ""));
    },
    units: field.units("length"),
    projects: projects.data?.results ?? [],
  };
}

export type PartFieldOptions = ReturnType<typeof usePartFieldOptions>;

const PLACEHOLDER: Partial<Record<StructuredPartField, string>> = {
  original_material: "Search grades or type (Other / specify)", application: "Search or describe the application",
  manufacturer: "Search OEMs or type (Other / specify)", equipment_reference: "Pick your equipment or type a new one",
};

export function PartFieldInput({ field, value, onChange, opts, id, disabled, ariaLabel }: {
  field: StructuredPartField; value: string | null | undefined; onChange: (v: string) => void; opts: PartFieldOptions; id?: string; disabled?: boolean;
  ariaLabel?: string;
}) {
  const v = value ?? "";
  switch (field) {
    case "dimensions":
      return <div role="group" aria-label={ariaLabel}><SizeInput id={id} value={v} onChange={onChange} disabled={disabled} units={opts.units} /></div>;
    case "category":
      return (
        <select id={id} aria-label={ariaLabel} value={v} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
          {PART_CATEGORIES.map((c) => <option key={c} value={c}>{c === "unknown" ? "Not classified" : label(c)}</option>)}
        </select>
      );
    case "criticality":
      return (
        <select id={id} aria-label={ariaLabel} value={v} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
          {PART_CRITICALITY.map(([c, l]) => <option key={c} value={c}>{l}</option>)}
        </select>
      );
    case "project":
      return (
        <select id={id} aria-label={ariaLabel} value={v} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
          <option value="">No project</option>
          {opts.projects.map((p) => <option key={p.id} value={p.id}>{p.code} · {p.name}</option>)}
        </select>
      );
    default:
      return <ComboText id={id} value={v} onChange={onChange} disabled={disabled} options={opts.options(field)} placeholder={PLACEHOLDER[field]} ariaLabel={ariaLabel} />;
  }
}
