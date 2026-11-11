/**
 * Draft manufacturing job sheet (CN-004, J1-J8 approved with amendments). Aries-internal: shown on the Aries
 * incoming-request page to Aries Engineers (prepare and revise) and QA (read). Built from the enquiry, its part (the clone
 * for a material change) and exactly one frozen passport revision. Every save is a new revision. QA submission, issue and
 * production release stay disabled (J4, OQ-36). Clients never reach this panel; they only see progress on their enquiry.
 */
import type { AcceptanceRow, JobSheet, ProcessParameter } from "@passport/api-types";
import { useState } from "react";

import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { ApiError } from "../api/client";
import { ComboText, HeatTreatmentInput, MultiSelect, NumberUnit, SelectOther, useFieldOptions } from "./passport/controls";
import { Badge, Card, DisabledAction, ErrorNotice, Field, Notice, formatDate } from "./ui";

type Content = { spec?: Record<string, unknown>; process_parameters?: ProcessParameter[]; quality?: Record<string, unknown>;
  engineering_notes?: string; deviation_reasons?: Record<string, string> };

const SOURCE: Record<string, [string, string]> = {
  verified: ["From approved passport revision", "prov-verified"],
  proposed: ["From passport draft · not approved", "prov-client"],
  missing: ["Missing", "prov-missing"],
  revalidate: ["Requires engineering revalidation", "prov-revalidate"],
  client_proposal: ["Client-proposed material · suitability not assessed", "prov-client"],
  entered: ["Entered on this job sheet", "prov-aries"],
};

export const FIELD_NAME: Record<string, string> = {
  "spec.material": "Material", "spec.feedstock": "Feedstock", "spec.machine": "Machine", "spec.layer_thickness": "Layer thickness",
  "spec.support_strategy": "Support strategy", "spec.build_orientation": "Build orientation", "spec.inert_gas": "Inert gas",
  "spec.heat_treatment": "Heat treatment", "spec.post_processing": "Post-processing", "spec.machining": "Machining",
  "spec.printing_hours": "Printing hours", "spec.post_processing_hours": "Post-processing hours", "process_parameters": "Process parameters",
  "quality.applicable_standards": "Applicable standards", "quality.dimensional_tolerances": "Dimensional tolerances", "quality.ndt": "NDT",
  "quality.inspection_test_plan": "Inspection and test plan", "quality.mtc_required": "Material test certificate required",
  "quality.test_coupons": "Test coupons", "quality.mechanical_acceptance": "Mechanical acceptance",
};

function SourceTag({ source }: { source?: string }) {
  if (!source || !SOURCE[source]) return null;
  return <span className={`prov ${SOURCE[source][1]}`}>{SOURCE[source][0]}</span>;
}

const show = (v: unknown) => (v == null || v === "" ? "—" : Array.isArray(v) ? v.map((r) => Object.values(r as object).filter(Boolean).join(" ")).join("; ") : typeof v === "boolean" ? (v ? "Yes" : "No") : String(v));

export function JobSheetPanel({ envelopeId, status, kind }: { envelopeId: string; status: string; kind: string }) {
  const { can } = useAuth();
  const base = `/operator/requests/${envelopeId}/jobsheet/`;
  const js = useApi<JobSheet>(can("jobsheets.view") ? base : null);
  if (!can("jobsheets.view") || kind === "digitisation") return null;
  const notFound = js.error instanceof ApiError && js.error.status === 404;
  return (
    <Card title="Manufacturing job sheet (draft · Aries internal)">
      {js.loading && !js.data ? <p className="muted small">Loading…</p>
        : js.data ? <JobSheetEditor sheet={js.data} base={base} onChange={js.setData} />
          : notFound ? <PrepareForm base={base} status={status} onCreated={js.setData} />
            : <ErrorNotice error={js.error} />}
    </Card>
  );
}

function PrepareForm({ base, status, onCreated }: { base: string; status: string; onCreated: (j: JobSheet) => void }) {
  const { can } = useAuth();
  const opts = useFieldOptions();
  const [jobRef, setJobRef] = useState("");
  const [method, setMethod] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const acknowledged = !["submitted", "closed", "declined", "withdrawn", "completed"].includes(status);
  if (!can("jobsheets.prepare")) return <p className="muted small">No job sheet has been prepared for this enquiry.</p>;
  if (!acknowledged) {
    return <p className="muted small">{status === "submitted" ? "Acknowledge the enquiry before preparing a job sheet." : "This enquiry is closed; no job sheet can be prepared."}</p>;
  }
  return (
    <form className="form-grid" aria-label="Prepare job sheet" onSubmit={async (e) => {
      e.preventDefault();
      setBusy(true);
      setError(null);
      try {
        onCreated(await api<JobSheet>(base, { body: { job_reference: jobRef, manufacturing_method: method } }));
      } catch (err) {
        setError(err);
      } finally {
        setBusy(false);
      }
    }}>
      <p className="muted small span-2">
        The draft links this enquiry, its part and the exact passport revision cited by the enquiry, and pre-fills the permitted
        engineering information from that revision. A provisional JS-DRAFT reference is assigned until you enter the Aries job number.
      </p>
      <ErrorNotice error={error} />
      <Field label="Aries job number (optional now)" hint="Must be unique across Aries. Format not fixed yet (J1).">
        <input value={jobRef} maxLength={60} onChange={(e) => setJobRef(e.target.value)} />
      </Field>
      <Field label="Manufacturing method" hint="Provisional list (J3); Other / specify allowed.">
        <SelectOther value={method} onChange={setMethod} options={opts.list("manufacturing_processes")} />
      </Field>
      <div className="form-actions"><button className="btn btn-primary" disabled={busy} aria-busy={busy}>Prepare job sheet draft</button></div>
    </form>
  );
}

function JobSheetEditor({ sheet, base, onChange }: { sheet: JobSheet; base: string; onChange: (j: JobSheet) => void }) {
  const { can } = useAuth();
  const opts = useFieldOptions();
  const editable = can("jobsheets.prepare") && sheet.status === "draft";
  const [viewing, setViewing] = useState<JobSheet | null>(null);
  const current = viewing ?? sheet;
  const content0 = current.content as Content;
  const [jobRef, setJobRef] = useState(sheet.job_reference);
  const [method, setMethod] = useState(sheet.manufacturing_method);
  const [content, setContent] = useState<Content>(content0);
  const [summary, setSummary] = useState("");
  const [cancelReason, setCancelReason] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState("");
  const [busy, setBusy] = useState(false);
  const shown = viewing ? content0 : content;  // an older revision is displayed read-only
  const spec = shown.spec ?? {};
  const quality = shown.quality ?? {};
  const params = shown.process_parameters ?? [];
  const rows = (quality.mechanical_acceptance as AcceptanceRow[] | undefined) ?? [];
  const readOnly = !editable || !!viewing;
  const src = current.sources as Record<string, string>;
  const setSpec = (k: string, v: unknown) => setContent({ ...content, spec: { ...spec, [k]: v } });
  const setQ = (k: string, v: unknown) => setContent({ ...content, quality: { ...quality, [k]: v } });
  const s = (k: string) => (spec[k] as string | undefined) ?? "";
  const q = (k: string) => (quality[k] as string | undefined) ?? "";
  const field = (key: string, control: React.ReactElement<{ id?: string }>) => (
    <div className={`sub-field ${src[key] === "missing" ? "is-missing" : ""}`} key={key}>
      <Field label={FIELD_NAME[key]}>{control}</Field>
      <SourceTag source={src[key]} />
    </div>
  );

  async function save() {
    setBusy(true);
    setError(null);
    setSaved("");
    try {
      const next = await api<JobSheet>(base, { method: "PATCH", body: { job_reference: jobRef, manufacturing_method: method, content, change_summary: summary } });
      onChange(next);
      setContent(next.content as Content);
      setSummary("");
      setSaved(`Saved as revision ${next.revision_number}.`);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="jobsheet" aria-label="Job sheet">
      <dl className="facts" aria-label="Job sheet identity">
        <dt>Enquiry</dt><dd>{sheet.enquiry_reference}</dd>
        <dt>Aries job number</dt><dd>{current.job_reference || <span className="muted">Not entered · provisional {sheet.draft_reference}</span>}</dd>
        <dt>Job-sheet revision</dt><dd>rev {current.revision_number}{viewing ? " (older revision, read-only)" : ""} · <Badge tone={sheet.status === "draft" ? "info" : "neutral"}>{sheet.status}</Badge></dd>
        <dt>Part</dt><dd>{sheet.part_number}{sheet.source_part_number ? ` (clone of ${sheet.source_part_number})` : ""}</dd>
        <dt>Passport basis</dt>
        <dd>{sheet.passport_number ? `${sheet.passport_number} rev ${sheet.passport_revision_number} · ${sheet.passport_revision_status === "approved" ? "approved" : "not approved (draft)"} · frozen for this job` : "No passport: all engineering data must be entered"}</dd>
        <dt>Material</dt>
        <dd>{sheet.proposed_material ? <>{sheet.original_material || "original not recorded"} → <strong>{sheet.proposed_material}</strong> <Badge tone="warning">Suitability not assessed</Badge></> : sheet.original_material || "—"}</dd>
      </dl>
      {sheet.revalidation_required.length > 0 && (
        <Notice kind="warning">
          Material change: these parameters depend on the material and require engineering revalidation before use:{" "}
          {sheet.revalidation_required.map((k) => FIELD_NAME[k] ?? k).join(", ")}.
        </Notice>
      )}
      <ErrorNotice error={error} />
      {saved && <Notice kind="success"><span role="status">{saved}</span></Notice>}
      <fieldset className="fieldset form-sections" disabled={readOnly} key={`${current.revision_number}-${viewing ? "v" : "e"}`}>
        <legend>Job details</legend>
        <div className="form-grid">
          <Field label="Aries job number" hint="Unique across Aries (J1). JS-DRAFT references are provisional.">
            <input value={viewing ? current.job_reference : jobRef} maxLength={60} onChange={(e) => setJobRef(e.target.value)} />
          </Field>
          <Field label="Manufacturing method" hint="Provisional list (J3); Other / specify allowed.">
            <SelectOther value={viewing ? current.manufacturing_method : method} onChange={setMethod} options={opts.list("manufacturing_processes")} />
          </Field>
        </div>
        <fieldset className="fieldset form-section">
          <legend>Engineering specification (BR-026)</legend>
          <div className="form-grid">
            {field("spec.material", <ComboText value={s("material")} onChange={(v) => setSpec("material", v)} options={opts.list("material_grades")} />)}
            {field("spec.feedstock", <ComboText value={s("feedstock")} onChange={(v) => setSpec("feedstock", v)} options={opts.list("feedstocks")} />)}
            {field("spec.machine", <ComboText value={s("machine")} onChange={(v) => setSpec("machine", v)} options={opts.list("machines")} />)}
            {field("spec.layer_thickness", <NumberUnit value={s("layer_thickness")} onChange={(v) => setSpec("layer_thickness", v)} units={opts.units("layer")} />)}
            {field("spec.support_strategy", <SelectOther value={s("support_strategy")} onChange={(v) => setSpec("support_strategy", v)} options={opts.list("support_strategies")} />)}
            {field("spec.build_orientation", <ComboText value={s("build_orientation")} onChange={(v) => setSpec("build_orientation", v)} options={opts.list("build_orientations")} />)}
            {field("spec.inert_gas", <SelectOther value={s("inert_gas")} onChange={(v) => setSpec("inert_gas", v)} options={opts.list("inert_gases")} />)}
            {field("spec.heat_treatment", <HeatTreatmentInput value={s("heat_treatment")} onChange={(v) => setSpec("heat_treatment", v)} processes={opts.list("heat_treatments")} />)}
            {field("spec.machining", <input value={s("machining")} onChange={(e) => setSpec("machining", e.target.value)} />)}
            {field("spec.printing_hours", <input type="number" min={0} step="0.25" value={(spec.printing_hours as number | null | undefined) ?? ""} onChange={(e) => setSpec("printing_hours", e.target.value === "" ? null : Number(e.target.value))} />)}
            {field("spec.post_processing_hours", <input type="number" min={0} step="0.25" value={(spec.post_processing_hours as number | null | undefined) ?? ""} onChange={(e) => setSpec("post_processing_hours", e.target.value === "" ? null : Number(e.target.value))} />)}
            <div className="span-2">{field("spec.post_processing", <MultiSelect label="Post-processing" value={s("post_processing")} onChange={(v) => setSpec("post_processing", v)} options={opts.list("post_processing")} />)}</div>
          </div>
          <h4>Process parameters (BR-041) <SourceTag source={src["process_parameters"]} /></h4>
          <div className="table-scroll">
            <table className="table table-edit" aria-label="Job process parameters">
              <thead><tr><th>Parameter</th><th>Value</th><th>Unit</th><th /></tr></thead>
              <tbody>
                {params.map((p, i) => {
                  const upd = (patch: Partial<ProcessParameter>) => setContent({ ...content, process_parameters: params.map((x, j) => (j === i ? { ...x, ...patch } : x)) });
                  return (
                    <tr key={i}>
                      <td><ComboText ariaLabel={`Job parameter ${i + 1}`} value={p.name} options={opts.list("process_parameters")} onChange={(v) => upd({ name: v })} /></td>
                      <td><input aria-label={`Job value ${i + 1}`} value={p.value ?? ""} onChange={(e) => upd({ value: e.target.value })} /></td>
                      <td><ComboText ariaLabel={`Job unit ${i + 1}`} value={p.unit ?? ""} options={opts.units("parameters").map((v) => ({ value: v }))} onChange={(v) => upd({ unit: v })} /></td>
                      <td>{!readOnly && <button type="button" className="btn btn-small" onClick={() => setContent({ ...content, process_parameters: params.filter((_, j) => j !== i) })}>Remove</button>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {!readOnly && <button type="button" className="btn btn-small" onClick={() => setContent({ ...content, process_parameters: [...params, { name: "", value: "", unit: "" }] })}>Add parameter</button>}
        </fieldset>
        <fieldset className="fieldset form-section">
          <legend>Quality and inspection requirements</legend>
          <div className="form-grid">
            <div className="span-2">{field("quality.applicable_standards", <MultiSelect label="Applicable standards" value={q("applicable_standards")} onChange={(v) => setQ("applicable_standards", v)} options={opts.list("applicable_standards")} />)}</div>
            {field("quality.dimensional_tolerances", <ComboText value={q("dimensional_tolerances")} onChange={(v) => setQ("dimensional_tolerances", v)} options={opts.list("dimensional_tolerances")} />)}
            {field("quality.mtc_required", (
              <select value={quality.mtc_required == null ? "" : String(quality.mtc_required)} onChange={(e) => setQ("mtc_required", e.target.value === "" ? null : e.target.value === "true")}>
                <option value="">—</option><option value="true">Yes</option><option value="false">No</option>
              </select>
            ))}
            <div className="span-2">{field("quality.ndt", <MultiSelect label="NDT" value={q("ndt")} onChange={(v) => setQ("ndt", v)} options={opts.list("inspection_methods")} />)}</div>
            {field("quality.inspection_test_plan", <input value={q("inspection_test_plan")} onChange={(e) => setQ("inspection_test_plan", e.target.value)} />)}
            {field("quality.test_coupons", <textarea rows={2} value={q("test_coupons")} onChange={(e) => setQ("test_coupons", e.target.value)} />)}
          </div>
          <h4>Mechanical acceptance <SourceTag source={src["quality.mechanical_acceptance"]} /></h4>
          <p className="small">{rows.length ? rows.map((r) => `${r.property} ${r.requirement ?? ""} ${r.unit ?? ""}${r.standard ? ` (${r.standard})` : ""}`).join("; ") : "—"}</p>
        </fieldset>
        <fieldset className="fieldset form-section">
          <legend>Engineering notes (internal)</legend>
          <textarea rows={3} aria-label="Engineering notes" value={(viewing ? content0 : content).engineering_notes ?? ""} onChange={(e) => setContent({ ...content, engineering_notes: e.target.value })} />
        </fieldset>
      </fieldset>
      <h4>Deviations from passport {sheet.passport_number ? `${sheet.passport_number} rev ${sheet.passport_revision_number}` : "(no passport)"}</h4>
      {current.deviations.length === 0 ? <p className="muted small">None: the job matches the passport template.</p> : (
        <div className="table-scroll">
          <table className="table compare-table" aria-label="Deviations">
            <thead><tr><th>Field</th><th>Passport</th><th>This job</th><th>Reason</th></tr></thead>
            <tbody>
              {current.deviations.map((d) => (
                <tr key={d.field} className="is-changed">
                  <td>{FIELD_NAME[d.field] ?? d.field}</td><td>{show(d.passport)}</td><td>{show(d.job)}</td>
                  <td>{readOnly ? d.reason || "—" : (
                    <input aria-label={`Reason for ${FIELD_NAME[d.field] ?? d.field}`} value={content.deviation_reasons?.[d.field] ?? d.reason ?? ""}
                      onChange={(e) => setContent({ ...content, deviation_reasons: { ...(content.deviation_reasons ?? {}), [d.field]: e.target.value } })} />
                  )}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editable && !viewing && (
        <div className="form-actions sticky-actions">
          <input aria-label="Change summary" placeholder="Change summary (optional)" value={summary} maxLength={500} onChange={(e) => setSummary(e.target.value)} />
          <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void save()}>Save new revision</button>
        </div>
      )}
      <div className="toolbar wrap gate-row">
        <DisabledAction label="Submit for QA review" reason="Disabled until manufacturing authorisation is decided (J4, OQ-36)." />
        <DisabledAction label="Issue job sheet" reason="Disabled (J4, OQ-36)." />
        <DisabledAction label="Release to production" reason="Disabled: no production release in this release (PUB-004, OQ-36)." />
      </div>
      <h4>Revisions</h4>
      <ol className="review-timeline" aria-label="Job-sheet revisions">
        {sheet.revisions.map((r) => (
          <li key={r.revision_number}>
            <strong>rev {r.revision_number}</strong> <span className="muted small">{r.author} · {formatDate(r.created_at)}{r.job_reference ? ` · job ${r.job_reference}` : ""}</span>
            {r.change_summary && <div className="small">{r.change_summary}</div>}
            {r.revision_number !== current.revision_number && (
              <button type="button" className="link-btn small" onClick={async () => {
                if (r.revision_number === sheet.revision_number) return setViewing(null);
                setViewing(await api<JobSheet>(`${base}revisions/${r.revision_number}/`));
              }}>View</button>
            )}
            {viewing && r.revision_number === current.revision_number && <button type="button" className="link-btn small" onClick={() => setViewing(null)}>Back to current</button>}
          </li>
        ))}
      </ol>
      {editable && !viewing && (
        <details className="cancel-box">
          <summary className="small">Cancel this draft</summary>
          <div className="toolbar wrap">
            <input aria-label="Reason for cancelling" value={cancelReason} placeholder="Reason" onChange={(e) => setCancelReason(e.target.value)} />
            <button type="button" className="btn" disabled={busy || !cancelReason.trim()} onClick={async () => {
              try { onChange(await api<JobSheet>(`${base}cancel/`, { body: { reason: cancelReason } })); } catch (err) { setError(err); }
            }}>Cancel draft</button>
          </div>
        </details>
      )}
    </div>
  );
}
