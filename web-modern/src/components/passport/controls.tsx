/**
 * Structured inputs for the passport forms (requirement update 2026-10). Every control reads and writes the SAME string
 * field the free-text form used, so saved values, revisions and the API stay unchanged:
 * - a value is only rewritten when the user changes it (no silent conversion of stored text);
 * - a stored value that does not match the control's canonical format is shown as a custom value, readable and editable;
 * - controlled lists are provisional suggestions (OQ-16) and always allow Other / specify.
 */
import type { FieldOptions } from "@passport/api-types";
import { useState } from "react";

import { useApi } from "../../api/useApi";

export type Option = { value: string; group?: string };

export function useFieldOptions() {
  const r = useApi<FieldOptions>("/passport-field-options/");
  return {
    list: (name: string): Option[] => r.data?.lists?.[name] ?? [],
    units: (name: string): string[] => r.data?.units?.[name] ?? [],
    provisional: r.data?.provisional ?? true,
  };
}

const norm = (s: string) => s.trim().toLowerCase();
export const inList = (value: string, options: Option[]) => options.some((o) => norm(o.value) === norm(value));

// ------------------------------------------------------------------ pure helpers (unit-tested)

/** "A; B; C" <-> list. Text without ";" is one item, so legacy free text stays exactly as written. */
export function parseMulti(value: string | null | undefined): string[] {
  return (value ?? "").split(";").map((s) => s.trim()).filter(Boolean);
}
export function joinMulti(items: string[]): string {
  return items.map((s) => s.trim()).filter(Boolean).join("; ");
}

const NUM = String.raw`-?\d+(?:\.\d+)?`;

/** "<number> <unit>" (or a bare number when unit is omitted). Returns null when the text is not in that exact form. */
export function parseNumberUnit(value: string | null | undefined, units: string[]): { n: string; unit: string } | null {
  const v = (value ?? "").trim();
  if (!v) return { n: "", unit: units[0] ?? "" };
  const m = v.match(new RegExp(`^(${NUM})(?:\\s*(\\S.*))?$`));
  if (!m) return null;
  const unit = m[2] ?? "";
  if (unit && !units.includes(unit)) return null;
  if (!unit && units.length > 0 && !units.includes("")) return null;
  return { n: m[1], unit };
}
export function formatNumberUnit(n: string, unit: string): string {
  return n.trim() === "" ? "" : unit ? `${n.trim()} ${unit}` : n.trim();
}

export type Size = { shape: "box" | "cylinder"; dims: string[]; unit: string };
/** "L x W x H mm" or "Ø D x H mm". Anything else (e.g. "120.0 x 34.0 mm (Ø x H)") is left as a custom value. */
export function parseSize(value: string | null | undefined, units: string[]): Size | null {
  const v = (value ?? "").trim();
  if (!v) return { shape: "box", dims: ["", "", ""], unit: units[0] ?? "mm" };
  const box = v.match(new RegExp(`^(${NUM}) x (${NUM}) x (${NUM}) (\\S+)$`));
  if (box && units.includes(box[4])) return { shape: "box", dims: [box[1], box[2], box[3]], unit: box[4] };
  const cyl = v.match(new RegExp(`^Ø ?(${NUM}) x (${NUM}) (\\S+)$`));
  if (cyl && units.includes(cyl[3])) return { shape: "cylinder", dims: [cyl[1], cyl[2]], unit: cyl[3] };
  return null;
}
export function formatSize(s: Size): string {
  const d = s.dims.map((x) => x.trim());
  if (d.every((x) => !x)) return "";
  return s.shape === "cylinder" ? `Ø${d[0]} x ${d[1]} ${s.unit}` : `${d[0]} x ${d[1]} x ${d[2]} ${s.unit}`;
}

export type Heat = { process: string; temp: string; hours: string };
/** "Stress relief 650 °C / 2 h", or a process alone ("None", "HIP"). */
export function parseHeat(value: string | null | undefined, processes: Option[]): Heat | null {
  const v = (value ?? "").trim();
  if (!v) return { process: "", temp: "", hours: "" };
  if (inList(v, processes)) return { process: v, temp: "", hours: "" };
  const m = v.match(new RegExp(`^(.+?) (${NUM}) °C / (${NUM}) h$`));
  if (m && inList(m[1], processes)) return { process: m[1], temp: m[2], hours: m[3] };
  return null;
}
export function formatHeat(h: Heat): string {
  if (!h.process) return "";
  return h.temp.trim() && h.hours.trim() ? `${h.process} ${h.temp.trim()} °C / ${h.hours.trim()} h` : h.process;
}

// ------------------------------------------------------------------ controls

type Base = { id?: string; value: string | null | undefined; onChange: (v: string) => void; disabled?: boolean };

function CustomTag({ show }: { show: boolean }) {
  return show ? <span className="ctl-tag" title="Not in the provisional list; kept exactly as entered.">Custom value</span> : null;
}

/** Searchable list with free entry (type 2): suggestions from controlled master data, any other value allowed. */
export function ComboText({ id, value, onChange, disabled, options, placeholder, ariaLabel }: Base & { options: Option[]; placeholder?: string; ariaLabel?: string }) {
  const listId = `${id ?? "combo"}-list`;
  const v = value ?? "";
  return (
    <span className="ctl">
      <input id={id} aria-label={ariaLabel} list={listId} value={v} disabled={disabled} placeholder={placeholder ?? "Search the list or type (Other / specify)"}
        onChange={(e) => onChange(e.target.value)} autoComplete="off" />
      <datalist id={listId}>
        {options.map((o) => <option key={o.value} value={o.value}>{o.group}</option>)}
      </datalist>
      <CustomTag show={!!v.trim() && options.length > 0 && !inList(v, options)} />
    </span>
  );
}

const OTHER = "__other__";

/** Fixed dropdown with Other / specify (type 1). A stored value not in the list opens as Other with its text. */
export function SelectOther({ id, value, onChange, disabled, options }: Base & { options: Option[] }) {
  const v = value ?? "";
  // derived on every render: the option list loads asynchronously, so nothing about the stored value is fixed up front
  const listed = !v || inList(v, options);
  const [other, setOther] = useState(false);
  const showOther = other || !listed;
  if (!options.length) {
    // list still loading: show the stored value as is rather than flashing "Other / specify"
    return (
      <span className="ctl ctl-select-other">
        <select id={id} disabled={disabled} value={v} onChange={() => undefined} aria-busy="true">
          <option value={v}>{v || "—"}</option>
        </select>
      </span>
    );
  }
  return (
    <span className="ctl ctl-select-other">
      <select id={id} disabled={disabled} value={showOther ? OTHER : options.find((o) => norm(o.value) === norm(v))?.value ?? ""}
        onChange={(e) => {
          if (e.target.value === OTHER) { setOther(true); return; }
          setOther(false);
          onChange(e.target.value);
        }}>
        <option value="">—</option>
        {options.map((o) => <option key={o.value} value={o.value}>{o.value}</option>)}
        <option value={OTHER}>Other / specify…</option>
      </select>
      {showOther && (
        <input aria-label="Specify" value={v} disabled={disabled} placeholder="Specify" onChange={(e) => onChange(e.target.value)} />
      )}
    </span>
  );
}

/** Multi-select with Other / specify (type 3). Stored as "A; B; other text". */
export function MultiSelect({ id, value, onChange, disabled, options, label }: Base & { options: Option[]; label: string }) {
  const items = parseMulti(value);
  const chosen = new Set(items.filter((i) => inList(i, options)).map(norm));
  const others = items.filter((i) => !inList(i, options));
  // while typing, the text box keeps exactly what is typed; otherwise it shows the stored items not in the list
  const [draft, setDraft] = useState<string | null>(null);
  const otherText = draft ?? joinMulti(others);
  const write = (nextChosen: Set<string>, otherStr: string) =>
    onChange(joinMulti([...options.filter((o) => nextChosen.has(norm(o.value))).map((o) => o.value), ...parseMulti(otherStr)]));
  return (
    <div className="ctl ctl-multi" role="group" aria-label={label} id={id}>
      <div className="chip-checks">
        {options.map((o) => (
          <label key={o.value} className={`chip-check ${chosen.has(norm(o.value)) ? "is-on" : ""}`}>
            <input type="checkbox" disabled={disabled} checked={chosen.has(norm(o.value))}
              onChange={(e) => {
                const next = new Set(chosen);
                if (e.target.checked) next.add(norm(o.value));
                else next.delete(norm(o.value));
                write(next, otherText);
              }} />
            {o.value}
          </label>
        ))}
      </div>
      <input aria-label={`${label}: other / specify`} disabled={disabled} value={otherText} placeholder="Other / specify (separate several with ;)"
        onChange={(e) => { setDraft(e.target.value); write(chosen, e.target.value); }} onBlur={() => setDraft(null)} />
    </div>
  );
}

/** Text that is not in the control's format: shown and editable as is, with an explicit switch to structured entry. */
function Custom({ id, value, onChange, disabled, onStructured, hint }: Base & { onStructured: () => void; hint: string }) {
  return (
    <span className="ctl ctl-custom">
      <input id={id} value={value ?? ""} disabled={disabled} onChange={(e) => onChange(e.target.value)} />
      <span className="ctl-tag" title={hint}>Custom value</span>
      {!disabled && <button type="button" className="link-btn small" onClick={onStructured}>Enter as number and unit</button>}
    </span>
  );
}

/** Validated number with a unit (type 5). */
export function NumberUnit({ id, value, onChange, disabled, units, min = 0, step = "any", fixedUnit }: Base & {
  units: string[]; min?: number; step?: string; fixedUnit?: string;
}) {
  const unitList = fixedUnit !== undefined ? [""] : units;
  const parsed = parseNumberUnit(value, unitList);
  const [forced, setForced] = useState(false);
  const [unit, setUnit] = useState(parsed?.unit || units[0] || "");
  if (!parsed && !forced) {
    return <Custom id={id} value={value} onChange={onChange} disabled={disabled} onStructured={() => setForced(true)}
      hint="Stored text is not a plain number with a unit; it is kept exactly as entered." />;
  }
  const n = parsed?.n ?? "";
  const u = fixedUnit !== undefined ? "" : parsed?.unit || unit;
  return (
    <span className="ctl ctl-number">
      <input id={id} type="number" inputMode="decimal" min={min} step={step} disabled={disabled} value={n}
        onChange={(e) => onChange(formatNumberUnit(e.target.value, u))} />
      {fixedUnit !== undefined ? <span className="unit">{fixedUnit}</span> : (
        <select aria-label="Unit" disabled={disabled} value={u} onChange={(e) => { setUnit(e.target.value); onChange(formatNumberUnit(n, e.target.value)); }}>
          {units.map((x) => <option key={x} value={x}>{x}</option>)}
        </select>
      )}
    </span>
  );
}

/** Overall size: box L × W × H or cylinder Ø × H, with unit (type 5). */
export function SizeInput({ id, value, onChange, disabled, units }: Base & { units: string[] }) {
  const parsed = parseSize(value, units);
  // While dimensions are being typed the draft is the source of truth; only a complete size is written.
  const [draft, setDraft] = useState<Size | null>(null);
  if (!parsed && !draft) {
    return <Custom id={id} value={value} onChange={onChange} disabled={disabled}
      onStructured={() => setDraft({ shape: "box", dims: ["", "", ""], unit: units[0] ?? "mm" })}
      hint="Stored size is not in the L x W x H / Ø x H format; it is kept exactly as entered." />;
  }
  const s = draft ?? parsed!;
  const filled = s.dims.filter((d) => d.trim()).length;
  const set = (next: Size) => {
    setDraft(next);
    onChange(next.dims.every((d) => d.trim()) ? formatSize(next) : "");
  };
  const labels = s.shape === "cylinder" ? ["Ø", "H"] : ["L", "W", "H"];
  return (
    <span className="ctl ctl-size">
      <select aria-label="Shape" disabled={disabled} value={s.shape}
        onChange={(e) => set({ ...s, shape: e.target.value as Size["shape"], dims: e.target.value === "cylinder" ? s.dims.slice(0, 2) : [...s.dims.slice(0, 2), s.dims[2] ?? ""] })}>
        <option value="box">L × W × H</option>
        <option value="cylinder">Ø × H</option>
      </select>
      {labels.map((l, i) => (
        <input key={l} id={i === 0 ? id : undefined} aria-label={i === 0 && id ? undefined : l} placeholder={l} type="number" min={0} step="any" inputMode="decimal"
          disabled={disabled} value={s.dims[i] ?? ""} onChange={(e) => set({ ...s, dims: s.dims.map((d, j) => (j === i ? e.target.value : d)) })} />
      ))}
      <select aria-label="Unit" disabled={disabled} value={s.unit} onChange={(e) => set({ ...s, unit: e.target.value })}>
        {units.map((u) => <option key={u} value={u}>{u}</option>)}
      </select>
      {filled > 0 && filled < s.dims.length && <span className="ctl-warn">Enter every dimension to save the size.</span>}
    </span>
  );
}

/** Heat treatment: process, temperature (°C) and hold time (h) (types 1 + 5). */
export function HeatTreatmentInput({ id, value, onChange, disabled, processes }: Base & { processes: Option[] }) {
  const parsed = parseHeat(value, processes);
  const [draft, setDraft] = useState<Heat | null>(null);
  if (!parsed && !draft) {
    return (
      <span className="ctl ctl-custom">
        <input id={id} value={value ?? ""} disabled={disabled} onChange={(e) => onChange(e.target.value)} />
        <span className="ctl-tag">Custom value</span>
        {!disabled && <button type="button" className="link-btn small" onClick={() => setDraft({ process: "", temp: "", hours: "" })}>Choose process and enter °C / h</button>}
      </span>
    );
  }
  const h = draft ?? parsed!;
  const half = !!h.temp.trim() !== !!h.hours.trim();
  const set = (next: Heat) => {
    setDraft(next);
    // temperature and time are written together; a half-entered pair keeps the process only until both are given
    onChange(formatHeat(!!next.temp.trim() !== !!next.hours.trim() ? { ...next, temp: "", hours: "" } : next));
  };
  return (
    <span className="ctl ctl-heat">
      <select id={id} disabled={disabled} value={processes.find((p) => norm(p.value) === norm(h.process))?.value ?? ""} onChange={(e) => set({ ...h, process: e.target.value })}>
        <option value="">—</option>
        {processes.map((p) => <option key={p.value} value={p.value}>{p.value}</option>)}
      </select>
      <input aria-label="Temperature °C" type="number" step="any" placeholder="°C" disabled={disabled || !h.process || h.process === "None"} value={h.temp}
        onChange={(e) => set({ ...h, temp: e.target.value })} />
      <span className="unit">°C</span>
      <input aria-label="Hold time h" type="number" min={0} step="any" placeholder="h" disabled={disabled || !h.process || h.process === "None"} value={h.hours}
        onChange={(e) => set({ ...h, hours: e.target.value })} />
      <span className="unit">h</span>
      {half && <span className="ctl-warn">Enter both temperature and time.</span>}
    </span>
  );
}
