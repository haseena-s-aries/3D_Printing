/**
 * Digital Passport PDF reports (CN-005) with the Report Builder: choose a template (Manufacturing & Test Specification,
 * Standard Digital Passport, Aries Internal Engineering Report), pick supporting PDF documents in the order they should
 * follow the report (each pinned to an exact version), preview the complete assembled PDF, then generate. Generation
 * history, page previews (images) and downloads follow the server-enforced rules (R5). Client-facing reports can only
 * attach documents released to the client; MTS and internal reports are Aries-confidential.
 */
import type { EngineeringFile, Report, Revision } from "@passport/api-types";
import { useEffect, useMemo, useState } from "react";

import { api, fetchObjectUrl, postForObjectUrl, upload } from "../../api/client";
import { useApi } from "../../api/useApi";
import { useAuth } from "../../auth/AuthContext";
import { Badge, Empty, ErrorNotice, Field, Notice, formatBytes, formatDate } from "../ui";

const ACTION_TEXT: Record<string, string> = { generated: "Generated", previewed: "Previewed", downloaded: "Downloaded" };

export const TEMPLATES = [
  { key: "mts", label: "Manufacturing & Test Specification", audience: "internal",
    hint: "Aries confidential. Layout of the Manufacturing & Test Specification sample: specification grid, views, quantities, process steps, inspection and test table, then the attached documents." },
  { key: "standard", label: "Standard Digital Passport", audience: "client",
    hint: "Client-facing: identification, materials, dimensions, CAD views, quality requirements and documents released to the client." },
  { key: "internal", label: "Aries Internal Engineering Report", audience: "internal",
    hint: "Aries confidential: the passport report plus the manufacturing specification (BR-026), process parameters and solution." },
] as const;

// Supporting-document classes (existing categories plus the CN-005 report classes)
export const DOC_CLASSES: [string, string][] = [
  ["drawing", "Engineering drawing"], ["inspection", "QC / inspection report"], ["mat_cert", "Material certificate"],
  ["mech_test", "Mechanical test report"], ["chem_analysis", "Chemical analysis report"], ["lab_test", "Laboratory test report"],
  ["other", "Other supporting document"],
];
const CLASS_LABEL: Record<string, string> = { ...Object.fromEntries(DOC_CLASSES), certificate: "Certification", specification: "Manufacturing specification" };

type Pick = { file: string; version: number };
type Withdrawal = { at: string; by: string; reason?: string; file_state_label?: string };
const withdrawalOf = (r: Report) => r.withdrawal as Withdrawal | null;

export const OFFERED: string[] = ["mts"];

export function eligible(files: EngineeringFile[], audience: string): { file: EngineeringFile; allowed: boolean; reason: string }[] {
  return files.filter((f) => f.kind === "pdf").map((f) => {
    const released = !!f.client_visible;
    return { file: f, allowed: audience === "internal" || released, reason: audience === "client" && !released ? "Not released to the client" : "" };
  });
}

// Default attachment order (Project 1 sample): the 2D drawing first, then the QA / inspection report, then every other
// supporting document in the order it was ticked. The order can still be changed with the arrows.
const CLASS_RANK: Record<string, number> = { drawing: 0, inspection: 1 };
const rankOf = (category?: string | null) => CLASS_RANK[category ?? ""] ?? 2;

export function insertByClass<T extends { file: string }>(picks: T[], pick: T, categoryOf: (file: string) => string | null | undefined): T[] {
  const rank = rankOf(categoryOf(pick.file));
  let at = picks.length;
  while (at > 0 && rankOf(categoryOf(picks[at - 1].file)) > rank) at -= 1;
  return [...picks.slice(0, at), pick, ...picks.slice(at)];
}

export function move<T>(list: T[], index: number, delta: number): T[] {
  const j = index + delta;
  if (j < 0 || j >= list.length) return list;
  const next = [...list];
  [next[index], next[j]] = [next[j], next[index]];
  return next;
}

export default function ReportsTab({ passportId, partId, revisions, files, onFilesChanged }: {
  passportId: string; partId?: string; revisions: Revision[]; files: EngineeringFile[]; onFilesChanged?: () => void;
}) {
  const { can, session } = useAuth();
  const isAries = !!session?.membership.role.startsWith("operator");
  const list = useApi<Report[]>(`/passports/${passportId}/reports/`);
  // Only the Manufacturing & Test Specification is offered; the Standard and Internal templates stay readable in the history.
  const templates = TEMPLATES.filter((t) => OFFERED.includes(t.key) && can(t.audience === "internal" ? "reports.generate_internal" : "reports.generate_client"));
  const [template, setTemplate] = useState<string>(templates[0]?.key ?? "mts");
  const audience = TEMPLATES.find((t) => t.key === template)?.audience ?? "client";
  const latest = revisions[0]?.revision_number;
  const [revision, setRevision] = useState<number | undefined>(latest);
  const [picks, setPicks] = useState<Pick[]>([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState("");
  const [preview, setPreview] = useState<Report | null>(null);
  const [assembled, setAssembled] = useState<string | null>(null);
  const [withdrawing, setWithdrawing] = useState<Report | null>(null);
  const [modelFile, setModelFile] = useState("");
  // post-UAT D-03: the STEP model whose views are printed, chosen explicitly (clients only see released versions)
  const models = files.filter((f) => f.kind === "step" && f.latest_version?.derivatives?.some((d) => d.kind === "glb"));
  const [replacing, setReplacing] = useState<Report | null>(null);
  useEffect(() => setRevision(latest), [latest]);
  const docs = useMemo(() => eligible(files, audience), [files, audience]);
  const byId = Object.fromEntries(files.map((f) => [f.id, f]));
  // switching to a client-facing template drops documents that are not released to the client
  useEffect(() => setPicks((ps) => ps.filter((p) => docs.find((d) => d.file.id === p.file)?.allowed)), [docs]);
  const body = () => ({ template, revision: isAries ? revision : undefined, attachments: picks.map((p) => ({ file: p.file, version: p.version })),
    ...(replacing ? { replaces: replacing.id } : {}),
    ...(modelFile ? { model: { file: modelFile, version: files.find((f) => f.id === modelFile)?.latest_version?.version_number } } : {}) });
  const totalAttachedPages = picks.reduce((n, p) => n + (byId[p.file]?.latest_version?.page_count ?? 0), 0);

  async function generate() {
    setBusy("generate");
    setError(null);
    setDone("");
    try {
      const r = await api<Report>(`/passports/${passportId}/reports/`, { body: body() });
      setDone(`Report ${r.number} generated (${r.page_count} page${r.page_count === 1 ? "" : "s"})${r.replaces ? `, replacing withdrawn ${r.replaces}` : ""}.`);
      setPicks([]);
      setReplacing(null);
      await list.reload();
    } catch (err) {
      setError(err);
    } finally {
      setBusy("");
    }
  }

  async function previewAssembled() {
    setBusy("preview");
    setError(null);
    try {
      setAssembled(await postForObjectUrl(`/passports/${passportId}/reports/preview/`, body()));
    } catch (err) {
      setError(err);
    } finally {
      setBusy("");
    }
  }

  async function download(r: Report) {
    try {
      const url = await fetchObjectUrl(`/passports/${passportId}/reports/${r.id}/pdf/`);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${r.number}.pdf`;
      a.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 5000);
      void list.reload();
    } catch (err) {
      setError(err);
    }
  }

  async function setVisible(f: EngineeringFile, visible: boolean) {
    setError(null);
    try {
      await api(`/files/${f.id}/`, { method: "PATCH", body: { client_visible: visible } });
      onFilesChanged?.();
    } catch (err) {
      setError(err);
    }
  }

  function startReplacement(r: Report) {
    setReplacing(r);
    const t = templates.find((x) => x.key === r.template);
    if (t) setTemplate(t.key);
    setDone("");
    window.setTimeout(() => document.querySelector(".report-builder")?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
  }

  const toggle = (f: EngineeringFile, on: boolean) => setPicks(on
    ? insertByClass(picks, { file: f.id, version: f.latest_version?.version_number ?? 1 }, (id) => byId[id]?.category)
    : picks.filter((p) => p.file !== f.id));

  return (
    <div className="reports-tab">
      <Notice>
        Reports are generated from one passport revision. Attached documents are reproduced as uploaded: attaching
        a certificate or test report does not verify it. External sharing is subject to the open IP and redistribution rules (OQ-33, OQ-38).
      </Notice>
      <ErrorNotice error={error} />
      {done && <Notice kind="success"><span role="status">{done}</span></Notice>}
      {templates.length > 0 && (
        <section className="report-builder" aria-label="Report builder">
          <h3>Report builder</h3>
          {replacing && (
            <Notice kind="warning">
              <span role="status">Generating a replacement for withdrawn report <strong>{replacing.number}</strong>. The new report gets a new number and
                links back to it; the withdrawn report stays in the history.</span>{" "}
              <button type="button" className="link-btn small" onClick={() => setReplacing(null)}>Cancel replacement</button>
            </Notice>
          )}
          {templates.length > 1 ? <div className="template-cards" role="radiogroup" aria-label="Report template">
            {templates.map((t) => (
              <label key={t.key} className={`template-card ${template === t.key ? "is-on" : ""}`}>
                <input type="radio" name="template" value={t.key} checked={template === t.key} onChange={() => setTemplate(t.key)} />
                <strong>{t.label}</strong> {t.audience === "internal" ? <Badge tone="danger">Aries confidential</Badge> : <Badge tone="info">Client-facing</Badge>}
                <span className="muted small">{t.hint}</span>
              </label>
            ))}
          </div> : <p data-testid="report-template"><strong>{templates[0].label}</strong> <Badge tone="danger">Aries confidential</Badge></p>}
          <div className="form-grid">
            <Field label="Passport revision" hint={isAries ? "The exact revision is printed on every page." : "Client reports use the current revision."}>
              <select value={revision ?? ""} disabled={!isAries} onChange={(e) => setRevision(Number(e.target.value))}>
                {revisions.map((r) => <option key={r.revision_number} value={r.revision_number}>rev {r.revision_number} · {r.status}</option>)}
              </select>
            </Field>
            <Field label="3D model for the views" hint={audience === "client" ? "Client-facing reports render only a model version released to the client."
              : "The views are rendered from exactly this STEP version; it is printed in the report."}>
              <select value={modelFile} onChange={(e) => setModelFile(e.target.value)}>
                <option value="">{models.length ? "Default: newest converted model" + (audience === "client" ? " released to the client" : "") : "No converted STEP model"}</option>
                {models.map((f) => (
                  <option key={f.id} value={f.id}>{f.title} · v{f.latest_version?.version_number}
                    {isAries ? (f.client_visible && f.released_version === f.latest_version?.version_number ? " · released to client" : " · Aries only") : ""}</option>
                ))}
              </select>
            </Field>
          </div>
          <div className="grid-2">
            <div>
              <h4>Available documents (PDF)</h4>
              {docs.length === 0 ? <Empty>No PDF documents on this part or passport yet.</Empty> : (
                <table className="table" aria-label="Available documents">
                  <thead><tr><th /><th>Document</th><th>Class</th><th>Client</th></tr></thead>
                  <tbody>
                    {docs.map(({ file: f, allowed, reason }) => (
                      <tr key={f.id} className={allowed ? "" : "muted"}>
                        <td><input type="checkbox" aria-label={`Include ${f.title}`} disabled={!allowed} checked={picks.some((p) => p.file === f.id)}
                          onChange={(e) => toggle(f, e.target.checked)} /></td>
                        <td>{f.title}<div className="muted small">v{f.latest_version?.version_number} · {f.latest_version?.page_count ?? "?"} page(s){reason ? ` · ${reason}` : ""}</div></td>
                        <td className="small">{CLASS_LABEL[f.category ?? ""] ?? f.category}</td>
                        <td className="small">{f.client_visible ? <Badge tone="success">Released</Badge> : <Badge>Aries only</Badge>}
                          {can("files.upload") && (
                            <div><button type="button" className="link-btn small" onClick={() => void setVisible(f, !f.client_visible)}>
                              {f.client_visible ? "Withdraw from client" : "Release to client"}</button></div>
                          )}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {can("files.upload") && partId && <UploadSupporting passportId={passportId} partId={partId} onUploaded={() => onFilesChanged?.()} />}
            </div>
            <div className="attach-panel">
              <h4>Attachment order</h4>
              {picks.length === 0 ? <p className="muted small attach-empty">No documents selected. The report will contain only the {TEMPLATES.find((t) => t.key === template)?.label} pages.</p> : (
                <ol className="attach-order" aria-label="Attachment order">
                  {picks.map((p, i) => {
                    const f = byId[p.file];
                    const versions = Array.from({ length: f?.latest_version?.version_number ?? 1 }, (_, k) => k + 1).reverse();
                    return (
                      <li key={p.file}>
                        <span className="attach-title">{i + 1}. {f?.title} <span className="muted small">{CLASS_LABEL[f?.category ?? ""] ?? f?.category}</span></span>
                        <select aria-label={`Version of ${f?.title}`} value={p.version}
                          onChange={(e) => setPicks(picks.map((x) => (x.file === p.file ? { ...x, version: Number(e.target.value) } : x)))}>
                          {versions.map((n) => <option key={n} value={n}>v{n}{n === f?.latest_version?.version_number ? " (latest)" : ""}</option>)}
                        </select>
                        <span className="attach-move">
                          <button type="button" className="btn btn-small" aria-label={`Move ${f?.title} up`} disabled={i === 0} onClick={() => setPicks(move(picks, i, -1))}>↑</button>
                          <button type="button" className="btn btn-small" aria-label={`Move ${f?.title} down`} disabled={i === picks.length - 1} onClick={() => setPicks(move(picks, i, 1))}>↓</button>
                        </span>
                        <button type="button" className="btn btn-small btn-ghost" aria-label={`Exclude ${f?.title}`} onClick={() => toggle(f, false)}>Exclude</button>
                      </li>
                    );
                  })}
                </ol>
              )}
              {picks.length > 0 && <p className="muted small">About {totalAttachedPages} attached page(s) follow the report pages, in this order.</p>}
              <div className="toolbar wrap attach-actions">
                <button type="button" className="btn" disabled={!!busy} aria-busy={busy === "preview"} onClick={() => void previewAssembled()}>{busy === "preview" ? "Assembling preview…" : "Preview complete PDF"}</button>
                <button type="button" className="btn btn-primary" disabled={!!busy} aria-busy={busy === "generate"} onClick={() => void generate()}>{busy === "generate" ? "Rendering report…" : replacing ? `Generate replacement for ${replacing.number}` : "Generate report"}</button>
              </div>
            </div>
          </div>
        </section>
      )}
      <h3>Generated reports</h3>
      {list.loading && !list.data ? <p className="muted small">Loading…</p> : !list.data?.length ? <Empty>No reports generated yet.</Empty> : (
        <div className="table-scroll">
          <table className="table" aria-label="Generated reports">
            <thead><tr><th>Report</th><th>Template</th><th>Revision</th><th>Attachments</th><th>Generated</th><th>History</th><th /></tr></thead>
            <tbody>
              {list.data.map((r) => { const w = withdrawalOf(r); return (
                <tr key={r.id} className={w ? "is-withdrawn" : ""}>
                  <td><strong>{r.number}</strong><div className="muted small">{r.page_count} pages · {formatBytes(r.size_bytes)}</div>
                    {w && <div><Badge tone="danger">Withdrawn</Badge> <span className="muted small">{formatDate(w.at)} · {w.by}</span></div>}
                    {w?.reason && <div className="small">Reason (Aries only): {w.reason}</div>}
                    {w?.file_state_label && <div className="muted small">File: {w.file_state_label}</div>}
                    {r.replaced_by && <div className="small">Replaced by <strong>{r.replaced_by}</strong></div>}
                    {r.replaces && <div className="small">Replaces withdrawn <strong>{r.replaces}</strong></div>}</td>
                  <td>{r.template_label}<div>{r.variant === "internal" ? <Badge tone="danger">Aries confidential</Badge> : <Badge tone="info">Client-facing</Badge>}</div></td>
                  <td>rev {r.revision_number} · {r.revision_status}{r.watermarked && <div><Badge tone="warning">Draft</Badge></div>}
                    {r.superseded && <div><Badge>Superseded</Badge></div>}</td>
                  <td className="small">{(r.attachments as { order?: number; title: string; version: number; first_page?: number }[]).length === 0 ? <span className="muted">None</span> : (
                    <ol className="ref-list">{(r.attachments as { order?: number; title: string; version: number; first_page?: number }[]).map((a, i) => (
                      <li key={i}>{a.title} v{a.version}{a.first_page ? <span className="muted"> · from p. {a.first_page}</span> : null}</li>))}</ol>)}</td>
                  <td className="small">{r.generated_by}<div className="muted">{formatDate(r.created_at)}</div></td>
                  <td className="small">
                    <details><summary>{r.events.length} event{r.events.length === 1 ? "" : "s"}</summary>
                      <ul className="ref-list">{r.events.map((e, i) => <li key={i}>{ACTION_TEXT[e.action] ?? e.action} · {e.user} · {formatDate(e.created_at)}</li>)}</ul>
                    </details>
                  </td>
                  <td className="actions">
                    {w ? (
                      <>
                        <span className="muted small">Withdrawn: no preview or download</span>
                        {can("reports.withdraw") && !r.replaced_by && templates.some((t) => t.key === r.template) && (
                          <button type="button" className="btn btn-small" onClick={() => startReplacement(r)}>Generate replacement</button>)}
                      </>
                    ) : (
                      <>
                        {r.can_preview && <button type="button" className="btn btn-small" onClick={() => setPreview(r)}>Preview</button>}
                        {r.can_download ? <button type="button" className="btn btn-small btn-primary" onClick={() => void download(r)}>Download PDF</button>
                          : r.can_preview ? <span className="muted small">Preview only</span> : null}
                        {can("reports.withdraw") && <button type="button" className="btn btn-small btn-ghost" onClick={() => setWithdrawing(r)}>Withdraw</button>}
                      </>
                    )}
                  </td>
                </tr>
              ); })}
            </tbody>
          </table>
        </div>
      )}
      {preview && <ReportPreview passportId={passportId} report={preview} onClose={() => { setPreview(null); void list.reload(); }} />}
      {withdrawing && <WithdrawDialog passportId={passportId} report={withdrawing} onClose={() => setWithdrawing(null)}
        onDone={(r) => { setWithdrawing(null); setDone(`Report ${r.number} withdrawn. Nobody can preview or download it any more.`); void list.reload(); }} />}
      {assembled && <AssembledPreview url={assembled} onClose={() => { URL.revokeObjectURL(assembled); setAssembled(null); }} />}
    </div>
  );
}

const DEFAULT_UPLOAD_CLASS = "lab_test";

function UploadSupporting({ passportId, partId, onUploaded }: { passportId: string; partId: string; onUploaded: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [category, setCategory] = useState(DEFAULT_UPLOAD_CLASS);
  const [title, setTitle] = useState("");
  const [visible, setVisible] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [ok, setOk] = useState("");
  const [inputKey, setInputKey] = useState(0); // remounts the file input, so it is empty again after an upload
  async function send() {
    if (!file) return;
    setBusy(true);
    setError(null);
    setOk("");
    const form = new FormData();
    form.append("file", file);
    form.append("part", partId);
    form.append("passport", passportId);
    form.append("category", category);
    form.append("client_visible", visible ? "true" : "false");
    if (title.trim()) form.append("title", title.trim());
    try {
      await upload("/files/", form);
      setOk(`${title.trim() || file.name} uploaded${visible ? " and released to the client" : " (Aries only)"}.`);
      setFile(null);
      setCategory(DEFAULT_UPLOAD_CLASS);
      setTitle("");
      setVisible(false);
      setInputKey((k) => k + 1);
      onUploaded();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="upload-supporting">
      <summary>Upload a supporting PDF document</summary>
      <div className="form-grid" role="group" aria-label="Upload supporting document">
        <ErrorNotice error={error} />
        {ok && <p className="small span-2" role="status">{ok}</p>}
        <Field label="PDF document" hint="Checked on upload: readable, not encrypted, no scripts or embedded files, page limit.">
          <input key={inputKey} type="file" accept=".pdf,application/pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </Field>
        <Field label="Document class">
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            {DOC_CLASSES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </Field>
        <div className="span-2"><Field label="Title (optional)"><input value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} /></Field></div>
        <label className="inline-check span-2"><input type="checkbox" checked={visible} onChange={(e) => setVisible(e.target.checked)} />
          Release to the client now (otherwise Aries only; can be released later)</label>
        <div className="form-actions"><button type="button" className="btn btn-primary" disabled={busy || !file} aria-busy={busy} onClick={() => void send()}>
          {busy ? "Uploading…" : "Upload document"}</button></div>
      </div>
    </details>
  );
}

function WithdrawDialog({ passportId, report, onClose, onDone }: { passportId: string; report: Report; onClose: () => void; onDone: (r: Report) => void }) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  async function send() {
    setBusy(true);
    setError(null);
    try {
      onDone(await api<Report>(`/passports/${passportId}/reports/${report.id}/withdraw/`, { body: { reason } }));
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }
  return (
    <div className="quickview-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="quickview" role="dialog" aria-modal="true" aria-labelledby="withdraw-title">
        <header className="quickview-head">
          <div><h2 id="withdraw-title">Withdraw report {report.number}</h2>
            <p className="muted small">rev {report.revision_number} · {report.template_label}</p></div>
          <button type="button" className="btn btn-ghost" onClick={onClose}>Close</button>
        </header>
        <Notice kind="warning">Once withdrawn, nobody can preview or download this report, including Aries. Its number, revision,
          generation and download history stay in the record and the audit trail. Clients see that it was withdrawn and when, not the reason.
          You can then generate a replacement.</Notice>
        <ErrorNotice error={error} />
        <label className="field"><span>Reason for the withdrawal *</span>
          <textarea rows={3} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="For example: contains information not authorised for the client" /></label>
        <div className="form-actions">
          <button type="button" className="btn btn-danger" disabled={busy || reason.trim().length < 10} onClick={() => void send()}>
            {busy ? "Withdrawing…" : "Withdraw report"}</button>
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}

function AssembledPreview({ url, onClose }: { url: string; onClose: () => void }) {
  return (
    <div className="quickview-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="quickview report-preview" role="dialog" aria-modal="true" aria-label="Assembled report preview">
        <header className="quickview-head">
          <div><h2>Preview: complete assembled PDF</h2><p className="muted small">Not saved. Generate the report to keep it in the history.</p></div>
          <button type="button" className="btn btn-ghost" onClick={onClose}>Close</button>
        </header>
        <iframe title="Assembled report preview" src={url} className="assembled-preview" />
      </div>
    </div>
  );
}

function ReportPreview({ passportId, report, onClose }: { passportId: string; report: Report; onClose: () => void }) {
  const [page, setPage] = useState(1);
  const [src, setSrc] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    let url: string | null = null;
    setSrc(null);
    fetchObjectUrl(`/passports/${passportId}/reports/${report.id}/pages/${page}/`).then((u) => { url = u; setSrc(u); }, setError);
    return () => { if (url) URL.revokeObjectURL(url); };
  }, [passportId, report.id, page]);
  return (
    <div className="quickview-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="quickview report-preview" role="dialog" aria-modal="true" aria-label={`Preview ${report.number}`}>
        <header className="quickview-head">
          <div><h2>{report.number}</h2><p className="muted small">Page {page} of {report.page_count} · preview image</p></div>
          <div className="toolbar">
            <button type="button" className="btn btn-small" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous page</button>
            <button type="button" className="btn btn-small" disabled={page >= report.page_count} onClick={() => setPage(page + 1)}>Next page</button>
            <button type="button" className="btn btn-ghost" onClick={onClose}>Close</button>
          </div>
        </header>
        <ErrorNotice error={error} />
        {src ? <img className="report-page" src={src} alt={`${report.number} page ${page}`} /> : <p className="muted">Rendering page…</p>}
      </div>
    </div>
  );
}
