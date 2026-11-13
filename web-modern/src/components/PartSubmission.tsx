/**
 * Client spare-part submissions and Aries review (requirement update 2026-10; access-test only until FR-04 is amended).
 * A Client Administrator creates a company record, other client users a new-part proposal. Both stay "Pending Aries
 * review": the client form never offers criticality, status, approval or manufacturing fields, and acceptance by an
 * Aries Engineer only admits the part to the engineering workflow (approval and eligibility stay gated, OQ-35/OQ-36).
 */
import type { Part, Paginated, Project } from "@passport/api-types";
import { useRef, useState, type FormEvent, type ReactNode } from "react";

import { api, upload } from "../api/client";
import { useApi } from "../api/useApi";
import { PartFieldInput, usePartFieldOptions, type StructuredPartField } from "./PartFieldInput";
import { Badge, ErrorNotice, Field, formatDate } from "./ui";

export type ReviewState = Part["review_state"];

export const REVIEW_LABEL: Record<string, string> = {
  pending_review: "Waiting for approval",
  info_requested: "Sent back for changes",
  accepted: "Approved",
  declined: "Declined",
};
const REVIEW_TONE: Record<string, "warning" | "info" | "success" | "danger"> = {
  pending_review: "warning", info_requested: "info", accepted: "success", declined: "danger",
};

export function ReviewBadge({ part }: { part: Pick<Part, "review_state" | "origin"> }) {
  if (part.origin !== "client" || !REVIEW_LABEL[part.review_state]) return null;
  return <Badge tone={REVIEW_TONE[part.review_state]}>{REVIEW_LABEL[part.review_state]}</Badge>;
}

export const isOpenReview = (p: Pick<Part, "review_state">) => p.review_state === "pending_review" || p.review_state === "info_requested";

export const FIELD_NAMES: Record<string, string> = {
  part_number: "Part number", name: "Part name", equipment_reference: "Equipment / machinery", manufacturer: "Manufacturer / OEM",
  application: "Application", original_material: "Material", dimensions: "Dimensions", description: "Description",
  project: "Project", category: "Category", criticality: "Criticality", status: "Status",
};

/** Where a value came from: client-submitted, verified by Aries, or entered by Aries. */
export function Provenance({ part, field }: { part: Pick<Part, "field_provenance" | "origin" | "unknown_fields">; field: string }) {
  if ((part.unknown_fields ?? []).includes(field as never)) return <span className="prov prov-unknown">Unknown / not available</span>;
  const p = part.field_provenance?.[field];
  if (!p) return null;
  if (p.source === "inherited") return <span className="prov prov-unknown" title="Copied unchanged from the original part">Inherited from original · reference</span>;
  if (p.source === "aries") return <span className="prov prov-aries" title={`Entered by ${p.entered_by}`}>Aries Engineering</span>;
  if (p.verified_by) return <span className="prov prov-verified" title={`Verified by ${p.verified_by}, ${formatDate(p.verified_at)}`}>Client-submitted · verified by Aries</span>;
  return <span className="prov prov-client" title={`Submitted by ${p.entered_by}`}>Client-submitted · not verified</span>;
}

type Values = {
  part_number: string; name: string; equipment_reference: string; manufacturer: string; application: string;
  original_material: string; dimensions: string; description: string; project: string | null; unknown_fields: string[];
};
const UNKNOWN_OK = ["part_number", "equipment_reference", "manufacturer", "application", "original_material", "dimensions"];
// Required unless marked unknown; part number, material and dimensions are asked "if known".
const REQUIRED = ["name", "equipment_reference", "manufacturer", "application", "description"];

function fromPart(p?: Part): Values {
  return {
    part_number: p && !(p.unknown_fields ?? []).includes("part_number") ? p.part_number : "", name: p?.name ?? "",
    equipment_reference: p?.equipment_reference ?? "", manufacturer: p?.manufacturer ?? "", application: p?.application ?? "",
    original_material: p?.original_material ?? "", dimensions: p?.dimensions ?? "", description: p?.description ?? "",
    project: p?.project ?? null, unknown_fields: [...(p?.unknown_fields ?? [])],
  };
}

const IMAGE = ["jpg", "jpeg", "png"];
const STRUCTURED_KEYS: (keyof Values)[] = ["equipment_reference", "manufacturer", "application", "original_material", "dimensions"];

/** Submit (or correct) a client spare-part record or proposal, with photographs and supporting PDFs. */
export function SubmissionForm({ part, isAdmin, onDone }: { part?: Part; isAdmin: boolean; onDone: (p: Part) => void }) {
  const opts = usePartFieldOptions();
  const [v, setV] = useState<Values>(() => fromPart(part));
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  // decision of 13 Nov 2026: all details entered -> submit for approval; otherwise ask Aries to complete the rest
  const [ariesComplete, setAriesComplete] = useState<boolean>(part?.aries_completion_requested ?? false);
  const files = useRef<HTMLInputElement>(null);
  const set = (k: keyof Values, value: string) => setV({ ...v, [k]: value });
  const unknown = (k: string) => v.unknown_fields.includes(k);
  const toggleUnknown = (k: string, on: boolean) =>
    setV({ ...v, [k]: on ? "" : v[k as keyof Values], unknown_fields: on ? [...v.unknown_fields, k] : v.unknown_fields.filter((x) => x !== k) });

  const missing = REQUIRED.filter((k) => !unknown(k) && !String(v[k as keyof Values] ?? "").trim());

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const body = { ...v, part_number: unknown("part_number") ? "" : v.part_number.trim(), aries_completion_requested: ariesComplete || v.unknown_fields.length > 0 };
      if (part && unknown("part_number")) delete (body as Partial<Values>).part_number;
      const saved = part ? await api<Part>(`/parts/${part.id}/`, { method: "PATCH", body }) : await api<Part>("/parts/", { body });
      const chosen = Array.from(files.current?.files ?? []);
      for (const [i, f] of chosen.entries()) {
        setStatus(`Uploading ${i + 1} of ${chosen.length}: ${f.name}`);
        const ext = f.name.split(".").pop()?.toLowerCase() ?? "";
        const form = new FormData();
        form.append("file", f);
        form.append("part", saved.id);
        form.append("category", IMAGE.includes(ext) ? "photo" : ["stp", "step"].includes(ext) ? "3d_model" : ext === "dwg" ? "drawing" : "other");
        form.append("title", f.name);
        await upload("/files/", form, () => undefined);
      }
      onDone(saved);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
      setStatus("");
    }
  }

  const partOpts = opts;
  const text = (k: keyof Values, label: string, opts: { hint?: string; area?: boolean; placeholder?: string } = {}) => {
    const req = REQUIRED.includes(k);
    const canUnknown = UNKNOWN_OK.includes(k);
    const isMissing = req && !unknown(k) && !String(v[k] ?? "").trim();
    return (
      <div className={`sub-field ${isMissing ? "is-missing" : ""}`}>
        <Field label={`${label}${req ? " *" : canUnknown ? " (if known)" : ""}`} hint={opts.hint}>
          {opts.area ? (
            <textarea rows={3} value={String(v[k] ?? "")} disabled={unknown(k)} placeholder={opts.placeholder} onChange={(e) => set(k, e.target.value)} />
          ) : STRUCTURED_KEYS.includes(k) && !unknown(k) ? (
            <PartFieldInput field={k as StructuredPartField} opts={partOpts} value={String(v[k] ?? "")} onChange={(x) => set(k, x)} />
          ) : (
            <input value={unknown(k) ? "" : String(v[k] ?? "")} disabled={unknown(k)} placeholder={unknown(k) ? "Unknown / not available" : opts.placeholder}
              onChange={(e) => set(k, e.target.value)} />
          )}
        </Field>
        {isMissing && <span className="missing-tag">Missing</span>}
        {canUnknown && (
          <label className="na-toggle small">
            <input type="checkbox" checked={unknown(k)} onChange={(e) => toggleUnknown(k, e.target.checked)} /> Unknown / not available
          </label>
        )}
      </div>
    );
  };

  return (
    <form className="submission-form" onSubmit={submit} aria-label="Spare part submission">
      <p className="notice notice-info small">
        {isAdmin ? "You are creating a spare-part record for your company." : "You are proposing a new spare part."}{" "}
        Enter everything you know. If you have all the details, submit them for <strong>approval</strong> by Aries. If some are
        missing, ask Aries to complete them. Submitting does not publish the part or make it eligible for manufacturing.
      </p>
      <ErrorNotice error={error} />
      <fieldset className="fieldset">
        <legend>Identification</legend>
        <div className="form-grid">
          {text("part_number", "Part number", { hint: "Client or OEM number. If unknown, a provisional TBC- number is assigned." })}
          {text("name", "Part name", { placeholder: "e.g. Seal housing" })}
          {text("equipment_reference", "Equipment / machinery", { placeholder: "e.g. Sea-water pump SWP-2" })}
          {text("manufacturer", "Manufacturer / OEM", { placeholder: "e.g. KSB" })}
        </div>
      </fieldset>
      <fieldset className="fieldset">
        <legend>Use and technical details</legend>
        <div className="form-grid">
          {text("application", "Application", { placeholder: "Where and how the part is used" })}
          {text("original_material", "Material", { placeholder: "e.g. AISI 316L" })}
          {text("dimensions", "Dimensions", { placeholder: "e.g. 120 x 80 x 40 mm or Ø102 x 60 mm" })}
          <Field label="Project (if applicable)" hint="A scanning or digitisation project of your company.">
            <PartFieldInput field="project" opts={opts} value={v.project ?? ""} onChange={(x) => setV({ ...v, project: x || null })} />
          </Field>
          <div className="span-2">{text("description", "Description", { area: true, placeholder: "Condition, failure, what you need, anything that helps Aries identify the part" })}</div>
        </div>
      </fieldset>
      <fieldset className="fieldset">
        <legend>CAD, drawings, photographs and supporting documents</legend>
        <Field label="Add files (optional)" hint="If you have them: the 3D CAD model (STEP) or drawing (DWG), photographs (JPEG/PNG) and PDF documents. Aries reviews them with the submission; nothing is verified by uploading.">
          <input ref={files} type="file" multiple accept=".stp,.step,.dwg,.pdf,.jpg,.jpeg,.png" />
        </Field>
      </fieldset>
      {!part && (
        <fieldset className="fieldset completion-choice">
          <legend>How should Aries handle it?</legend>
          <label className="inline-check">
            <input type="radio" name="completion" checked={!ariesComplete && v.unknown_fields.length === 0}
              disabled={v.unknown_fields.length > 0} onChange={() => setAriesComplete(false)} />{" "}
            <span><strong>I have entered all the details</strong> — submit them for approval</span>
          </label>
          <label className="inline-check">
            <input type="radio" name="completion" checked={ariesComplete || v.unknown_fields.length > 0} onChange={() => setAriesComplete(true)} />{" "}
            <span><strong>Some details are missing</strong> — ask Aries to complete them</span>
          </label>
          {v.unknown_fields.length > 0 && <p className="muted small">You marked {v.unknown_fields.map((f) => FIELD_NAMES[f] ?? f).join(", ")} as unknown, so Aries completes them.</p>}
        </fieldset>
      )}
      <div className="form-actions sticky-actions">
        {missing.length > 0 && <span className="muted small">Still needed: {missing.map((m) => FIELD_NAMES[m]).join(", ")}</span>}
        <button className="btn btn-primary" disabled={busy || missing.length > 0} aria-busy={busy}>
          {busy ? status || "Saving…" : part ? "Save changes" : ariesComplete || v.unknown_fields.length > 0 ? "Send to Aries to complete" : "Submit for approval"}
        </button>
      </div>
    </form>
  );
}

const VERIFIABLE = ["part_number", "name", "equipment_reference", "manufacturer", "application", "original_material", "dimensions", "description"];

/** Aries approval of a client submission (decision of 13 Nov 2026): send back (next revision), approve (passport draft is
 *  created; a clone's manufacturing request is sent automatically), decline, or verify client values later. */
export function ReviewPanel({ part, onChange }: { part: Part; onChange: (p: Part) => void }) {
  const projects = useApi<Paginated<Project>>("/projects/", { query: { page_size: 200 } });
  const [mode, setMode] = useState<"" | "request_info" | "accept" | "decline" | "verify">("");
  const [message, setMessage] = useState("");
  const [project, setProject] = useState(part.project ?? "");
  const clientFields = VERIFIABLE.filter((f) => part.field_provenance?.[f]?.source === "client" && !part.field_provenance?.[f]?.verified_by);
  const [verified, setVerified] = useState<string[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const open = isOpenReview(part);

  async function send(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body: Record<string, unknown> = { decision: mode, message };
      if (mode === "accept") Object.assign(body, { project: project || null, verified_fields: verified });
      if (mode === "verify") body.verified_fields = verified;
      onChange(await api<Part>(`/parts/${part.id}/review/`, { body }));
      setMode("");
      setMessage("");
      setVerified([]);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const checks: ReactNode = clientFields.length > 0 && (
    <fieldset className="fieldset">
      <legend>Mark client-submitted values as verified by Aries</legend>
      <div className="check-grid">
        {clientFields.map((f) => (
          <label key={f} className="inline-check">
            <input type="checkbox" checked={verified.includes(f)} onChange={(e) => setVerified(e.target.checked ? [...verified, f] : verified.filter((x) => x !== f))} />{" "}
            {FIELD_NAMES[f]}
          </label>
        ))}
      </div>
      <p className="muted small">Only tick values you have checked. Unticked values stay marked as client-submitted.</p>
    </fieldset>
  );

  return (
    <div className="review-panel" aria-label="Aries review">
      <ErrorNotice error={error} />
      <div className="toolbar wrap">
        {open && <span className="muted small">Revision {part.submission_revision ?? 1}</span>}
        {open && <button type="button" className="btn" aria-pressed={mode === "request_info"} onClick={() => setMode("request_info")}>Send back for changes</button>}
        {open && <button type="button" className="btn btn-primary" aria-pressed={mode === "accept"} onClick={() => setMode("accept")}>Approve</button>}
        {open && <button type="button" className="btn btn-ghost" aria-pressed={mode === "decline"} onClick={() => setMode("decline")}>Decline</button>}
        {!open && part.review_state === "accepted" && clientFields.length > 0 && (
          <button type="button" className="btn" aria-pressed={mode === "verify"} onClick={() => setMode("verify")}>Verify client values</button>
        )}
      </div>
      {open && part.aries_completion_requested && (
        <p className="notice notice-warning small">The client asked Aries to complete the missing details
          {part.unknown_fields?.length ? ` (${part.unknown_fields.map((f) => FIELD_NAMES[f] ?? f).join(", ")})` : ""}. Fill them in with “Edit details”, then approve.</p>
      )}
      {mode && (
        <form className="form-grid" onSubmit={send}>
          {mode === "accept" && (
            <Field label="Scanning / digitisation project" hint="Optional. Only your assigned projects of this company are listed.">
              <select value={project} onChange={(e) => setProject(e.target.value)}>
                <option value="">No project</option>
                {(projects.data?.results ?? []).map((p) => <option key={p.id} value={p.id}>{p.code} · {p.name}</option>)}
              </select>
            </Field>
          )}
          {(mode === "accept" || mode === "verify") && <div className="span-2">{checks}</div>}
          {mode !== "verify" && (
            <Field label={mode === "request_info" ? "What needs to be corrected or added? (the client resubmits as the next revision) *" : mode === "decline" ? "Reason for declining *" : "Note to the client (optional)"}>
              <textarea rows={2} required={mode !== "accept"} value={message} onChange={(e) => setMessage(e.target.value)} />
            </Field>
          )}
          {mode === "accept" && part.proposed_material && (
            <p className="notice notice-warning small span-2">
              The client proposes {part.proposed_material} instead of {String((part.source_snapshot as Record<string, string> | undefined)?.original_material || "the original material")}.
              Accepting does not confirm the material is suitable: assess it in the passport (R-L2 material selection) before any manufacturing.
            </p>
          )}
          {mode === "accept" && (
            <p className="muted small span-2">
              Approving creates the part's digital passport draft for Aries to complete{part.submission_kind === "clone" ? " and sends the client's manufacturing request to Aries automatically" : ""}.
              It does not publish the part or change manufacturing eligibility.
            </p>
          )}
          <div className="form-actions">
            <button type="button" className="btn btn-ghost" onClick={() => setMode("")}>Cancel</button>
            <button className="btn btn-primary" disabled={busy} aria-busy={busy}>
              {mode === "request_info" ? "Send back" : mode === "accept" ? "Approve" : mode === "decline" ? "Decline with reason" : "Mark verified"}
            </button>
          </div>
        </form>
      )}
    </div>
  );
}

/** Client: send the corrected submission back after Aries asked for more information. */
export function ResubmitForm({ part, onChange }: { part: Part; onChange: (p: Part) => void }) {
  const [message, setMessage] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  return (
    <form
      className="form-grid"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError(null);
        try {
          onChange(await api<Part>(`/parts/${part.id}/resubmit/`, { body: { message } }));
        } catch (err) {
          setError(err);
        } finally {
          setBusy(false);
        }
      }}
    >
      <ErrorNotice error={error} />
      <Field label="Reply to Aries (optional)" hint={`Update the details or add files first, then resubmit. It is approved as revision ${part.submission_revision ?? 1}.`}>
        <textarea rows={2} value={message} onChange={(e) => setMessage(e.target.value)} />
      </Field>
      <div className="form-actions">
        <button className="btn btn-primary" disabled={busy} aria-busy={busy}>Resubmit for approval</button>
      </div>
    </form>
  );
}
