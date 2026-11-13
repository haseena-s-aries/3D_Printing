/**
 * Aries Admin and Aries Manager: client submissions waiting for approval across client companies (decision of
 * 13 Nov 2026). New parts entered by clients (route 1) and clones with a changed material (route 3). The queue is a
 * narrow column on the left; the selected submission fills the rest: what the client entered, what is missing, the
 * material change of a clone, the documents (opened in the page), the history, and Approve / Send back / Decline.
 * Approve creates the passport draft for Aries to complete and, for a clone, sends the manufacturing request.
 * Aries Engineers decide the same submissions on the part page inside the client company.
 */
import type { components, EngineeringFile } from "@passport/api-types";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { fetchObjectUrl, api } from "../api/client";
import { useApi } from "../api/useApi";
import { Icon } from "../components/icons";
import { Badge, Empty, ErrorNotice, Loading, Notice, PageHeader, formatBytes, formatDate, label } from "../components/ui";

type Row = components["schemas"]["SubmissionApprovalRow"];
type Detail = Row & {
  fields: Record<string, string>; category_label: string; project: string; review_note: string;
  clone_changes: { field: string; original: string; clone: string; changed: boolean }[];
  source_passport_number: string; files: EngineeringFile[];
  history: { action: string; action_label: string; side: string; note: string; by: string; at: string }[];
};

const FIELD_LABEL: Record<string, string> = {
  part_number: "Part number", name: "Part name", description: "Description", category: "Category", original_material: "Material",
  dimensions: "Dimensions", application: "Application", equipment_reference: "Equipment / machinery", manufacturer: "Manufacturer / OEM",
  proposed_material: "Proposed material", material_change_reason: "Reason for the material change", client_remarks: "Client remarks",
};
const ORDER = ["part_number", "name", "equipment_reference", "manufacturer", "application", "original_material", "dimensions", "category", "description"];

function useFiles(d: Detail) {
  const base = `/operator/approvals/${d.client_id}/${d.part_id}/files`;
  const [preview, setPreview] = useState<{ url: string; f: EngineeringFile } | null>(null);
  const [error, setError] = useState<unknown>(null);
  async function open(f: EngineeringFile, variant: "preview" | "original") {
    setError(null);
    try {
      const url = await fetchObjectUrl(`${base}/${f.id}/?variant=${variant}`);
      if (variant === "preview") setPreview({ url, f });
      else {
        const a = document.createElement("a");
        a.href = url;
        a.download = f.latest_version?.original_filename ?? f.title ?? "file";
        a.click();
        window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
      }
    } catch (err) {
      setError(err);
    }
  }
  const close = () => { if (preview) URL.revokeObjectURL(preview.url); setPreview(null); };
  return { open, preview, close, error };
}

function SubmissionDetail({ d, onDecided }: { d: Detail; onDecided: (text: string) => void }) {
  const files = useFiles(d);
  const [mode, setMode] = useState<"" | "send_back" | "decline">("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const unknown = new Set(d.unknown_fields);

  async function decide(decision: "approve" | "send_back" | "decline", e?: FormEvent) {
    e?.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ review_state: string; revision: number; passport_number: string }>(`/operator/approvals/${d.client_id}/${d.part_id}/`,
        { body: { decision, message } });
      onDecided(decision === "approve"
        ? `${d.part_number || d.name} approved. Passport draft ${r.passport_number} created${d.submission_kind === "clone" ? " and the manufacturing request sent to Aries" : ""}.`
        : decision === "send_back" ? `${d.part_number || d.name} sent back to the client (next: revision ${r.revision}).` : `${d.part_number || d.name} declined.`);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="card approval-summary">
        <div className="approval-summary-head">
          <div>
            <p className="hero-eyebrow"><Icon name="boxes" size="sm" />{d.kind_label || "Client submission"} · revision {d.revision}</p>
            <h2>{d.part_number ? `${d.part_number} · ` : ""}{d.name}</h2>
          </div>
          <span className="toolbar">
            {d.aries_completion_requested && <Badge tone="warning">Aries to complete</Badge>}
            <Badge tone={d.review_state === "pending_review" ? "info" : "warning"}>{d.review_state === "pending_review" ? "Waiting for approval" : "Sent back to the client"}</Badge>
          </span>
        </div>
        <dl className="approval-meta">
          <div><dt>Client</dt><dd>{d.client_name}</dd></div>
          <div><dt>Submitted by</dt><dd>{d.submitted_by_email || "—"}</dd></div>
          <div><dt>Submitted</dt><dd>{formatDate(d.submitted_at)}</dd></div>
          <div><dt>Project</dt><dd>{d.project || "—"}</dd></div>
        </dl>
        {d.aries_completion_requested && (
          <Notice kind="warning">The client asked Aries to complete the missing details{d.unknown_fields.length ? `: ${d.unknown_fields.map((f) => FIELD_LABEL[f] ?? f).join(", ")}` : ""}.
            An Aries Engineer fills them in on the part page; then approve.</Notice>
        )}
        {d.review_state === "info_requested" && <Notice>Sent back: {d.review_note}. Waiting for the client to resubmit as revision {d.revision}.</Notice>}
      </div>

      <div className="card approval-content">
        <section className="approval-section">
          <header><h3>Details entered by the client</h3></header>
          <dl className="field-grid">
            {ORDER.map((k) => {
              const v = k === "category" ? d.category_label : d.fields[k];
              const missing = unknown.has(k) || !v;
              return (
                <div key={k} className={`field-tile ${missing ? "is-missing" : ""}`}>
                  <dt>{FIELD_LABEL[k]}</dt>
                  <dd className={missing ? "muted" : ""}>{unknown.has(k) ? "Unknown — Aries to complete" : v || "Not given"}</dd>
                </div>
              );
            })}
          </dl>
        </section>
        {d.submission_kind === "clone" && (
          <section className="approval-section">
            <header><h3>Clone of {d.source_part_number}{d.source_passport_number ? ` (passport ${d.source_passport_number})` : ""}</h3></header>
            <dl className="field-grid">
              <div className="field-tile"><dt>Original material</dt><dd>{d.fields.original_material || "—"}</dd></div>
              <div className="field-tile is-changed"><dt>Proposed material</dt><dd>{d.fields.proposed_material || "Same as the original"}</dd></div>
              <div className="field-tile"><dt>Reason</dt><dd>{d.fields.material_change_reason || "—"}</dd></div>
            </dl>
            {d.clone_changes.some((c) => c.changed && c.field !== "material") && (
              <div className="table-scroll approval-sub">
                <table className="table compact">
                  <thead><tr><th>Changed</th><th>Original part</th><th>Clone</th></tr></thead>
                  <tbody>{d.clone_changes.filter((c) => c.changed && c.field !== "material").map((c) => (
                    <tr key={c.field}><td>{FIELD_LABEL[c.field] ?? label(c.field)}</td><td>{c.original || "—"}</td><td>{c.clone || "—"}</td></tr>))}</tbody>
                </table>
              </div>
            )}
            <p className="muted small">On approval, the manufacturing request is sent to Aries automatically in the client's name.</p>
          </section>
        )}
        {d.fields.client_remarks && (
          <section className="approval-section"><header><h3>Client remarks</h3></header><p>{d.fields.client_remarks}</p></section>
        )}
        <section className="approval-section">
          <header><h3>Documents</h3><Badge>{d.files.length}</Badge></header>
          <ErrorNotice error={files.error} />
          {d.files.length === 0 ? <p className="muted small">No documents were submitted.</p> : (
            <ul className="doc-list">
              {d.files.map((f) => (
                <li key={f.id}>
                  <Icon name={f.kind === "step" ? "cube" : "file"} size="sm" />
                  <span className="doc-name"><strong>{f.title}</strong>
                    <span className="muted small">{label(f.category ?? "")} · {(f.kind ?? "").toUpperCase()}{f.latest_version ? ` · ${formatBytes(f.latest_version.size_bytes)}` : ""}</span></span>
                  <span />
                  <span className="file-actions">
                    {["pdf", "image"].includes(f.kind ?? "") && <button type="button" className="btn btn-small" onClick={() => void files.open(f, "preview")}><Icon name="eye" size="sm" />Open</button>}
                    <button type="button" className="btn btn-small btn-ghost" onClick={() => void files.open(f, "original")}><Icon name="download" size="sm" />Download</button>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section className="approval-section">
          <header><h3>History</h3></header>
          <ol className="approval-history">
            {d.history.map((h, i) => (
              <li key={i}><strong>{h.action_label}</strong> <span className="muted small">{h.by} · {formatDate(h.at)}</span>{h.note && <p>{h.note}</p>}</li>
            ))}
          </ol>
        </section>
      </div>

      {d.review_state === "pending_review" && (
        <div className="card approval-decision">
          <ErrorNotice error={error} />
          {mode ? (
            <form className="stack" onSubmit={(e) => void decide(mode, e)}>
              <label className="field"><span>{mode === "send_back" ? "What should the client change or add? (they resubmit as the next revision)" : "Reason for declining"}</span>
                <textarea rows={3} required value={message} onChange={(e) => setMessage(e.target.value)} /></label>
              <div className="toolbar">
                <button className="btn btn-primary" disabled={busy || !message.trim()} aria-busy={busy}>{mode === "send_back" ? "Send back" : "Decline"}</button>
                <button type="button" className="btn btn-ghost" onClick={() => setMode("")}>Cancel</button>
              </div>
            </form>
          ) : (
            <div className="approval-decision-row">
              <p className="muted small">Approving creates the passport draft for Aries to complete{d.submission_kind === "clone" ? " and sends the manufacturing request" : ""}.</p>
              <div className="toolbar">
                <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => setMode("decline")}>Decline</button>
                <button type="button" className="btn" disabled={busy} onClick={() => setMode("send_back")}>Send back</button>
                <button type="button" className="btn btn-primary" disabled={busy} aria-busy={busy} onClick={() => void decide("approve")}>Approve</button>
              </div>
            </div>
          )}
        </div>
      )}

      {files.preview && (
        <div className="quickview-backdrop" onMouseDown={(e) => e.target === e.currentTarget && files.close()}>
          <div className="quickview report-preview" role="dialog" aria-modal="true" aria-label={`Preview of ${files.preview.f.title}`}>
            <header className="quickview-head">
              <div><h2>{files.preview.f.title}</h2><p className="muted small">{files.preview.f.latest_version?.original_filename}</p></div>
              <div className="toolbar">
                <button type="button" className="btn" onClick={() => files.preview && void files.open(files.preview.f, "original")}><Icon name="download" size="sm" />Download</button>
                <button type="button" className="btn btn-ghost" onClick={files.close}>Close</button>
              </div>
            </header>
            {files.preview.f.kind === "image" ? <img className="assembled-preview doc-image" src={files.preview.url} alt={files.preview.f.title ?? ""} />
              : <iframe title={`Preview of ${files.preview.f.title}`} src={files.preview.url} className="assembled-preview" />}
          </div>
        </div>
      )}
    </>
  );
}

export default function SubmissionApprovalsPage() {
  const list = useApi<Row[]>("/operator/approvals/");
  const legacy = useApi<unknown[]>("/operator/passport-approvals/");
  const [open, setOpen] = useState<Row | null>(null);
  const detail = useApi<Detail>(open ? `/operator/approvals/${open.client_id}/${open.part_id}/` : null);
  const [done, setDone] = useState("");
  const rows = list.data ?? [];
  const waiting = rows.filter((r) => r.review_state === "pending_review").length;

  return (
    <>
      <PageHeader marine title="Approvals" subtitle="Spare parts entered by clients and clones with a changed material, waiting for Aries approval across all client companies." />
      {done && <Notice kind="success">{done}</Notice>}
      {(legacy.data?.length ?? 0) > 0 && (
        <Notice>{legacy.data!.length} passport revision(s) were submitted for approval before Aries-prepared passports stopped needing approval.{" "}
          <Link to="/passport-approvals">Review them</Link>, or the engineer marks them complete.</Notice>
      )}
      <div className="approvals-layout">
        <aside className="card approvals-queue" aria-label="Client submissions">
          <div className="card-head"><h2>Waiting <span className="count-pill">{waiting}</span></h2></div>
          <ErrorNotice error={list.error} />
          {list.loading && !list.data ? <Loading /> : rows.length === 0 ? <Empty icon="inbox">No client submissions are waiting.</Empty> : (
            <ul className="approval-list">
              {rows.map((r) => (
                <li key={r.part_id}>
                  <button type="button" className={`approval-row ${open?.part_id === r.part_id ? "is-active" : ""}`} aria-current={open?.part_id === r.part_id}
                    onClick={() => { setOpen(r); setDone(""); }}>
                    <span className="approval-row-top"><strong>{r.part_number || "No part number yet"}</strong><Badge tone="info">rev {r.revision}</Badge></span>
                    <span className="approval-row-title">{r.name}</span>
                    <span className="muted small">{r.client_name} · {r.kind_label}</span>
                    <span className="approval-row-badges">
                      {r.review_state === "info_requested" && <Badge>Sent back</Badge>}
                      {r.aries_completion_requested && <Badge tone="warning">Aries to complete</Badge>}
                    </span>
                    <span className="muted small">{r.submitted_by_email} · {formatDate(r.submitted_at)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </aside>
        <section className="approvals-detail" aria-label="Selected submission">
          {!open && <div className="card approvals-empty"><Empty icon="review">Choose a submission on the left to review it and decide.</Empty></div>}
          {open && detail.loading && !detail.data && <div className="card"><Loading label="Loading submission…" /></div>}
          {open && <ErrorNotice error={detail.error} />}
          {open && detail.data && (
            <SubmissionDetail key={detail.data.part_id + detail.data.revision} d={detail.data}
              onDecided={(text) => { setDone(text); setOpen(null); void list.reload(); }} />
          )}
        </section>
      </div>
    </>
  );
}
