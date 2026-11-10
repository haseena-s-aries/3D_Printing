/**
 * Request Edit (CN-006): propose new values for fields of a spare part or of a Digital Passport's current revision,
 * with a reason and optional supporting documents of the same part. Nothing changes until an authorised edit reviewer
 * approves; approval is not engineering verification, publication or manufacturing authorisation.
 */
import type { EditRequest, EngineeringFile, Paginated } from "@passport/api-types";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { PartFieldInput, usePartFieldOptions, type StructuredPartField } from "./PartFieldInput";
import { ErrorNotice, Notice, label as humanise } from "./ui";

type FieldOption = { field: string; label: string; current: unknown; kind: string; choices: string[] };
const STRUCTURED = new Set(["category", "criticality", "equipment_reference", "manufacturer", "application", "original_material", "dimensions"]);

export const show = (v: unknown) => (v === null || v === undefined || v === "" ? "—" : typeof v === "boolean" ? (v ? "Yes" : "No") : String(v));

export default function EditRequestDialog({ partId, passportId, title, onClose }: { partId: string; passportId?: string; title: string; onClose: () => void }) {
  const navigate = useNavigate();
  const fields = useApi<FieldOption[]>("/edit-requests/fields/", { query: { part: partId, ...(passportId ? { passport: passportId } : {}) } });
  const files = useApi<Paginated<EngineeringFile>>("/files/", { query: { part: partId, page_size: 100 } });
  const opts = usePartFieldOptions();
  const [proposed, setProposed] = useState<Record<string, unknown>>({});
  const [reason, setReason] = useState("");
  const [evidence, setEvidence] = useState<string[]>([]);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const first = useRef<HTMLInputElement>(null);
  useEffect(() => {
    first.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const chosen = Object.keys(proposed);
  const toggle = (f: FieldOption, on: boolean) => {
    const next = { ...proposed };
    if (on) next[f.field] = f.kind === "bool" ? (f.current ?? null) : (f.current ?? "");
    else delete next[f.field];
    setProposed(next);
  };

  async function send(submit: boolean) {
    setBusy(true);
    setError(null);
    try {
      const er = await api<EditRequest>("/edit-requests/", { body: {
        part: partId, passport: passportId ?? null, reason, evidence_files: evidence, submit,
        changes: chosen.map((field) => ({ field, proposed: proposed[field] })),
      } });
      navigate(`/edit-requests/${er.id}`);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const input = (f: FieldOption) => {
    const v = proposed[f.field];
    const set = (x: unknown) => setProposed({ ...proposed, [f.field]: x });
    if (!passportId && STRUCTURED.has(f.field)) {
      return <PartFieldInput field={f.field as StructuredPartField} opts={opts} value={String(v ?? "")} onChange={set} />;
    }
    if (f.kind === "bool") {
      return (
        <select aria-label={`Proposed ${f.label}`} value={v === null || v === undefined ? "" : String(v)} onChange={(e) => set(e.target.value === "" ? null : e.target.value === "true")}>
          <option value="">— (not recorded)</option><option value="true">Yes</option><option value="false">No</option>
        </select>
      );
    }
    if (f.kind === "choice") {
      return (
        <select aria-label={`Proposed ${f.label}`} value={String(v ?? "")} onChange={(e) => set(e.target.value)}>
          <option value="">—</option>
          {f.choices.map((c) => <option key={c} value={c}>{humanise(c)}</option>)}
        </select>
      );
    }
    if (f.kind === "number") {
      return <input aria-label={`Proposed ${f.label}`} type="number" min={0} step="0.25" value={v === null || v === undefined ? "" : String(v)}
        onChange={(e) => set(e.target.value === "" ? null : Number(e.target.value))} />;
    }
    return <input aria-label={`Proposed ${f.label}`} value={String(v ?? "")} onChange={(e) => set(e.target.value)} />;
  };

  const list = (fields.data ?? []).filter((f) => !filter || f.label.toLowerCase().includes(filter.toLowerCase()));
  return (
    <div className="quickview-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="quickview edit-dialog" role="dialog" aria-modal="true" aria-labelledby="edit-title">
        <header className="quickview-head">
          <div><h2 id="edit-title">Request edit · {title}</h2>
            <p className="muted small">{passportId ? "Changes to the passport's current revision become a new draft revision once approved." : "Changes to the spare-part master data."}</p></div>
          <button type="button" className="btn btn-ghost" onClick={onClose}>Close</button>
        </header>
        <Notice>An authorised edit reviewer decides on the request. Approval applies the change in a controlled way; it is not engineering verification,
          passport publication or manufacturing authorisation. Files, history, ownership and approval records cannot be changed here.</Notice>
        <ErrorNotice error={error} />
        <input ref={first} type="search" placeholder="Find a field" aria-label="Find a field" value={filter} onChange={(e) => setFilter(e.target.value)} />
        <div className="table-scroll edit-fields">
          <table className="table" aria-label="Fields">
            <thead><tr><th style={{ width: "4%" }} /><th style={{ width: "28%" }}>Field</th><th style={{ width: "30%" }}>Current value</th><th>Proposed value</th></tr></thead>
            <tbody>
              {list.map((f) => (
                <tr key={f.field} className={f.field in proposed ? "is-changed" : ""}>
                  <td><input type="checkbox" aria-label={`Change ${f.label}`} checked={f.field in proposed} onChange={(e) => toggle(f, e.target.checked)} /></td>
                  <td>{f.label}</td>
                  <td className="small">{show(f.current)}</td>
                  <td>{f.field in proposed ? input(f) : <span className="muted small">Unchanged</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <label className="field"><span>Reason for the change *</span>
          <textarea rows={3} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why the current values are wrong or out of date" /></label>
        {(files.data?.results ?? []).length > 0 && (
          <fieldset className="fieldset">
            <legend>Supporting documents (existing files of this part)</legend>
            <div className="check-grid">
              {(files.data?.results ?? []).map((f) => (
                <label key={f.id} className="inline-check"><input type="checkbox" checked={evidence.includes(f.id)}
                  onChange={(e) => setEvidence(e.target.checked ? [...evidence, f.id] : evidence.filter((x) => x !== f.id))} /> {f.title}</label>
              ))}
            </div>
          </fieldset>
        )}
        <div className="form-actions">
          <span className="muted small">{chosen.length} field{chosen.length === 1 ? "" : "s"} selected</span>
          <button type="button" className="btn" disabled={busy || !chosen.length || !reason.trim()} onClick={() => void send(false)}>Save as draft</button>
          <button type="button" className="btn btn-primary" disabled={busy || !chosen.length || !reason.trim()} onClick={() => void send(true)}>Submit for review</button>
        </div>
      </div>
    </div>
  );
}
