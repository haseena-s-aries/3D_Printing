/**
 * Request on a catalog part. The part, organisation and current passport revision are attached by the server.
 * Before submitting, the dialog states what the request will be: parts that are not published and eligible are
 * always sent as ENQUIRIES, never as manufacturing orders (the server classifies independently).
 */
import type { Paginated, Part, ServiceRequest } from "@passport/api-types";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { api, upload } from "../api/client";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { ComboText, useFieldOptions } from "./passport/controls";
import { StatusBadge, classification } from "./requests";
import { ErrorNotice, Notice } from "./ui";

const inTwoWeeks = () => new Date(Date.now() + 14 * 864e5).toISOString().slice(0, 10);

const slug = (s: string) => s.toUpperCase().replace(/[^A-Z0-9]+/g, "").slice(0, 10);

export default function RequestDialog({ part, onClose }: { part: Part; onClose: () => void }) {
  const options = useApi<{ services: string[] }>("/requests/form-options/");
  const { can } = useAuth();
  const fieldOptions = useFieldOptions();
  const clones = useApi<Paginated<Part>>("/parts/", { query: { source_part: part.id, page_size: 50 } });
  // Material change (CN-003, BR-033): manufacture in the original material, or propose a different one. A proposal is
  // linked to a separate cloned part held for Aries review; the original part and passport are never changed.
  const canClone = can("parts.submit");
  const [material, setMaterial] = useState({ option: "original", proposed: "", reason: "", link: canClone ? "new" : "none", newNumber: "", linked: "" });
  const files = useRef<HTMLInputElement>(null);
  const proposing = material.option === "proposed";
  const cls = proposing
    ? { kind: "enquiry", title: "Sent as an enquiry", text: "A different material needs Aries engineering review for suitability before any manufacturing. Your original part and its passport are not changed." }
    : classification(part);
  const sameAsOriginal = proposing && material.proposed.trim().toLowerCase() === (part.original_material ?? "").trim().toLowerCase();
  const materialMissing = proposing && (!material.proposed.trim() || !material.reason.trim() || sameAsOriginal
    || (canClone && material.link === "new" && !material.newNumber.trim()) || (material.link === "existing" && !material.linked));
  const [form, setForm] = useState({ quantity: "1", required_date: inTwoWeeks(), delivery_location: "", priority: "routine", remarks: "", client_reference: "" });
  const [services, setServices] = useState<string[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<ServiceRequest | null>(null);
  const first = useRef<HTMLInputElement>(null);

  useEffect(() => {
    first.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const materialBody = !proposing ? { material_option: "original" } : {
        material_option: "proposed", proposed_material: material.proposed, material_change_reason: material.reason,
        ...(material.link === "existing" ? { linked_part: material.linked } : canClone && material.link === "new" ? { new_part_number: material.newNumber } : {}),
      };
      const r = await api<ServiceRequest>("/requests/", {
        body: { request_type: "manufacturing", part: part.id, ...form, quantity: Number(form.quantity), services, ...materialBody },
      });
      for (const f of Array.from(files.current?.files ?? [])) {
        const fd = new FormData();
        fd.append("file", f);
        await upload(`/requests/${r.id}/attachments/`, fd, () => undefined);
      }
      setDone(r);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="quickview-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="quickview request-dialog" role="dialog" aria-modal="true" aria-labelledby="request-title">
        <header className="quickview-head">
          <div>
            <h2 id="request-title">{done ? "Request submitted" : `Request · ${part.part_number}`}</h2>
            <p className="muted small">{part.name}{part.passport_number ? ` · ${part.passport_number}${part.revision ? ` rev ${part.revision.number}` : ""}` : ""}</p>
          </div>
          <button type="button" className="btn btn-ghost" onClick={onClose} aria-label="Close request">Close</button>
        </header>

        {done ? (
          <div className="request-done" role="status">
            <p className="request-ref">{done.reference}</p>
            <p>
              Your {done.kind === "enquiry" ? "enquiry" : "request"} has been sent to our team. Status: <StatusBadge status={done.status} />
            </p>
            {done.material_option === "proposed" && (
              <p className="notice notice-warning small">
                Material change proposed: {done.original_material || "original"} → <strong>{done.proposed_material}</strong>.{" "}
                {done.linked_part_number ? <>It is linked to the cloned part <Link to={`/parts/${done.linked_part}`}>{done.linked_part_number}</Link>, pending Aries review.</>
                  : "Aries will review the proposal and link it to a separate part."}{" "}
                Suitability is assessed by Aries Engineering; it is not accepted automatically.
              </p>
            )}
            <p className="muted">You will see a notification when it is acknowledged. You can follow it under My requests.</p>
            <div className="toolbar">
              <Link className="btn btn-primary" to={`/requests/${done.id}`}>View request</Link>
              <button type="button" className="btn" onClick={onClose}>Back to catalog</button>
            </div>
          </div>
        ) : (
          <form className="form-grid" onSubmit={submit} aria-label="Manufacturing request">
            <div className={`classification classification-${cls.kind}`} role="note">
              <strong>{cls.title}</strong>
              <p>{cls.text}</p>
            </div>
            <label className="field">
              <span>Quantity</span>
              <input ref={first} type="number" min={1} max={100000} required value={form.quantity} onChange={set("quantity")} />
            </label>
            <label className="field">
              <span>Required delivery date</span>
              <input type="date" required min={new Date().toISOString().slice(0, 10)} value={form.required_date} onChange={set("required_date")} />
            </label>
            <label className="field span-2">
              <span>Delivery location</span>
              <input required maxLength={300} placeholder="Site, building or warehouse" value={form.delivery_location} onChange={set("delivery_location")} />
            </label>
            <fieldset className="fieldset span-2" aria-label="Material">
              <legend>Material</legend>
              <div className="radio-row">
                <label className="inline-check">
                  <input type="radio" name="material-option" checked={!proposing} onChange={() => setMaterial({ ...material, option: "original" })} />{" "}
                  Manufacture using the original material ({part.original_material || "as recorded by Aries"})
                </label>
                <label className="inline-check">
                  <input type="radio" name="material-option" checked={proposing}
                    onChange={() => setMaterial({ ...material, option: "proposed", newNumber: material.newNumber || `${part.part_number}-${slug(material.proposed) || "ALT"}` })} />{" "}
                  Propose a different material
                </label>
              </div>
              {proposing && (
                <div className="form-grid">
                  <label className="field">
                    <span>Original material</span>
                    <input value={part.original_material || "Not recorded"} readOnly disabled />
                  </label>
                  <div className="field">
                    <label htmlFor="proposed-material">Proposed material grade *</label>
                    <ComboText id="proposed-material" value={material.proposed} options={fieldOptions.list("material_grades")}
                      onChange={(v) => setMaterial({ ...material, proposed: v })} />
                    {sameAsOriginal && <span className="ctl-warn">This is the original material.</span>}
                  </div>
                  <label className="field span-2">
                    <span>Reason for the material change *</span>
                    <textarea rows={2} maxLength={2000} value={material.reason} onChange={(e) => setMaterial({ ...material, reason: e.target.value })} />
                  </label>
                  <fieldset className="fieldset span-2">
                    <legend>Separate part for the new material</legend>
                    {canClone && (
                      <label className="inline-check">
                        <input type="radio" name="link" checked={material.link === "new"} onChange={() => setMaterial({ ...material, link: "new" })} />{" "}
                        Create a cloned part linked to {part.part_number}
                      </label>
                    )}
                    {canClone && material.link === "new" && (
                      <label className="field">
                        <span>New part number *</span>
                        <input value={material.newNumber} maxLength={80} onChange={(e) => setMaterial({ ...material, newNumber: e.target.value })} />
                      </label>
                    )}
                    {(clones.data?.results ?? []).length > 0 && (
                      <label className="inline-check">
                        <input type="radio" name="link" checked={material.link === "existing"} onChange={() => setMaterial({ ...material, link: "existing" })} />{" "}
                        Use an existing clone of this part
                      </label>
                    )}
                    {material.link === "existing" && (
                      <select aria-label="Existing clone" value={material.linked} onChange={(e) => setMaterial({ ...material, linked: e.target.value })}>
                        <option value="">Choose a clone…</option>
                        {(clones.data?.results ?? []).map((c) => <option key={c.id} value={c.id}>{c.part_number}{c.proposed_material ? ` · ${c.proposed_material}` : ""}</option>)}
                      </select>
                    )}
                    {!canClone && (
                      <label className="inline-check">
                        <input type="radio" name="link" checked={material.link === "none"} onChange={() => setMaterial({ ...material, link: "none" })} />{" "}
                        Send the proposal only; Aries links it to a separate part
                      </label>
                    )}
                  </fieldset>
                </div>
              )}
            </fieldset>
            <fieldset className="fieldset span-2">
              <legend>Required services (confirmed by our team)</legend>
              <div className="check-grid">
                {(options.data?.services ?? []).map((s) => (
                  <label key={s} className="inline-check">
                    <input type="checkbox" checked={services.includes(s)} onChange={(e) => setServices((x) => (e.target.checked ? [...x, s] : x.filter((y) => y !== s)))} /> {s}
                  </label>
                ))}
              </div>
            </fieldset>
            <label className="field">
              <span>Priority</span>
              <select value={form.priority} onChange={set("priority")}>
                <option value="routine">Routine</option>
                <option value="urgent">Urgent (breakdown)</option>
              </select>
            </label>
            <label className="field">
              <span>Your reference (optional)</span>
              <input maxLength={80} placeholder="Purchase order or work order" value={form.client_reference} onChange={set("client_reference")} />
            </label>
            <label className="field span-2">
              <span>Remarks</span>
              <textarea rows={3} maxLength={2000} value={form.remarks} onChange={set("remarks")} />
            </label>
            <label className="field span-2">
              <span>Supporting documents (optional)</span>
              <input ref={files} type="file" multiple accept=".pdf,.jpg,.jpeg,.png" aria-label="Supporting documents" />
            </label>
            <ErrorNotice error={error} />
            <Notice>The part, your organisation and the current passport revision are attached automatically. No prices or lead times are quoted here.</Notice>
            <div className="form-actions span-2">
              <button type="button" className="btn" onClick={onClose}>Cancel</button>
              <button className="btn btn-primary" disabled={busy || materialMissing} aria-busy={busy}>{busy ? "Sending…" : cls.kind === "enquiry" ? "Send enquiry" : "Submit request"}</button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
