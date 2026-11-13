/**
 * Aries Admin and Aries Manager: passport revisions waiting for approval across client companies. The queue is a narrow
 * column on the left; the selected revision fills the rest: summary, R-L1 / R-L2 fields as labelled grids, the mechanical
 * acceptance as a table, the manufacturing specification, R-L3 evidence by document name, and a sticky decision bar.
 * The submitter can never decide their own revision (server rule). Aries Engineers approve from the passport itself.
 */
import type { components, EngineeringFile } from "@passport/api-types";
import { Suspense, lazy, useState, type FormEvent, type ReactNode } from "react";

import { api, fetchObjectUrl } from "../api/client";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { Icon } from "../components/icons";
import { FIELD_LABELS, RL3_EVIDENCE } from "../components/passport/ReadinessForms";
import { Badge, Empty, ErrorNotice, Loading, Notice, PageHeader, formatBytes, formatDate, label } from "../components/ui";
import { viewerState } from "../components/viewerState";

const ModelViewer = lazy(() => import("../components/ModelViewer"));

type Row = components["schemas"]["PassportApprovalRow"];
type Detail = Row & { passport_state: string; revision: components["schemas"]["Revision"];
  evidence_files: Record<string, { title: string; category: string; kind: string }>; files: EngineeringFile[] };

/** Opens / downloads / views the passport's files through the approval endpoint (audited in the client company). */
function useApprovalFiles(d: Detail) {
  const base = `/operator/passport-approvals/${d.client_id}/${d.passport_id}/files`;
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState("");
  const [preview, setPreview] = useState<{ url: string; file: EngineeringFile } | null>(null);
  async function open(f: EngineeringFile, variant: "preview" | "original") {
    setError(null);
    setBusy(f.id + variant);
    try {
      const url = await fetchObjectUrl(`${base}/${f.id}/?variant=${variant}`);
      if (variant === "preview") {
        setPreview({ url, file: f });  // shown in the page (no pop-up); revoked when closed
      } else {
        const a = document.createElement("a");
        a.href = url;
        a.download = f.latest_version?.original_filename ?? f.title ?? "file";
        a.click();
        window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
      }
    } catch (err) {
      setError(err);
    } finally {
      setBusy("");
    }
  }
  const close = () => { if (preview) URL.revokeObjectURL(preview.url); setPreview(null); };
  const glb = (f: EngineeringFile) => () => fetchObjectUrl(`${base}/${f.id}/?variant=glb`);
  return { open, glb, error, busy, preview, close };
}

/** The document opened for review, inside the page: PDF in a frame, photographs as an image. */
function DocPreview({ files }: { files: ReturnType<typeof useApprovalFiles> }) {
  const p = files.preview;
  if (!p) return null;
  return (
    <div className="quickview-backdrop" onMouseDown={(e) => e.target === e.currentTarget && files.close()}>
      <div className="quickview report-preview" role="dialog" aria-modal="true" aria-label={`Preview of ${p.file.title}`}>
        <header className="quickview-head">
          <div><h2>{p.file.title}</h2><p className="muted small">{label(p.file.category ?? "")} · {p.file.latest_version?.original_filename}
            {p.file.latest_version ? ` · v${p.file.latest_version.version_number}` : ""}</p></div>
          <div className="toolbar">
            <button type="button" className="btn" onClick={() => void files.open(p.file, "original")}><Icon name="download" size="sm" />Download</button>
            <button type="button" className="btn btn-ghost" onClick={files.close}>Close</button>
          </div>
        </header>
        {p.file.kind === "image" ? <img className="assembled-preview doc-image" src={p.url} alt={p.file.title ?? ""} />
          : <iframe title={`Preview of ${p.file.title}`} src={p.url} className="assembled-preview" />}
      </div>
    </div>
  );
}

const PREVIEWABLE = ["pdf", "image"];

function FileActions({ f, files }: { f: EngineeringFile; files: ReturnType<typeof useApprovalFiles> }) {
  return (
    <span className="file-actions">
      {PREVIEWABLE.includes(f.kind ?? "") && (
        <button type="button" className="btn btn-small" disabled={files.busy === f.id + "preview"} onClick={() => void files.open(f, "preview")}>
          <Icon name="eye" size="sm" />Open</button>
      )}
      <button type="button" className="btn btn-small btn-ghost" disabled={files.busy === f.id + "original"} onClick={() => void files.open(f, "original")}>
        <Icon name="download" size="sm" />Download</button>
    </span>
  );
}

function Documents({ d, files }: { d: Detail; files: ReturnType<typeof useApprovalFiles> }) {
  const models = d.files.filter((f) => f.kind === "step");
  const [model, setModel] = useState<string | null>(models.find((f) => viewerState(f.latest_version).kind === "ready")?.id ?? null);
  const current = models.find((f) => f.id === model) ?? null;
  return (
    <>
      <Section title="Documents and files" badge={<Badge>{d.files.length}</Badge>}>
        <ErrorNotice error={files.error} />
        {d.files.length === 0 ? <p className="muted small">No files are attached to this spare part.</p> : (
          <ul className="doc-list">
            {d.files.map((f) => (
              <li key={f.id}>
                <Icon name={f.kind === "step" ? "cube" : "file"} size="sm" />
                <span className="doc-name"><strong>{f.title}</strong>
                  <span className="muted small">{label(f.category ?? "")} · {(f.kind ?? "").toUpperCase()}{f.latest_version ? ` · v${f.latest_version.version_number} · ${formatBytes(f.latest_version.size_bytes)}` : ""}</span></span>
                {f.kind === "step" && viewerState(f.latest_version).kind === "ready" && (
                  <button type="button" className="btn btn-small" onClick={() => setModel(f.id)}><Icon name="cube" size="sm" />3D view</button>
                )}
                <FileActions f={f} files={files} />
              </li>
            ))}
          </ul>
        )}
      </Section>
      {current?.latest_version && (
        <Section title="3D model" badge={<span className="muted small">{current.title} · v{current.latest_version.version_number}</span>}>
          {viewerState(current.latest_version).kind === "ready" ? (
            <Suspense fallback={<Loading />}>
              <ModelViewer key={current.id} fileId={current.id} version={current.latest_version} revisionLabel={`${d.passport_number} rev ${d.revision_number}`}
                loadUrl={files.glb(current)} />
            </Suspense>
          ) : <p className="muted small">{(viewerState(current.latest_version) as { text?: string }).text}</p>}
        </Section>
      )}
    </>
  );
}
type Completeness = Record<string, { done: number; total: number }>;
type Obj = Record<string, unknown>;

const LEVEL_NAMES: Record<string, string> = { rl1: "R-L1", rl2: "R-L2", rl3: "R-L3" };
const ACCEPTANCE_COLS: [string, string][] = [["property", "Property"], ["requirement", "Requirement"], ["unit", "Unit"],
  ["standard", "Standard"], ["frequency", "Frequency"]];

function text(v: unknown): string {
  if (v === null || v === undefined || v === "") return "";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (Array.isArray(v)) return v.map(text).filter(Boolean).join(", ");
  if (typeof v === "object") return Object.entries(v as Obj).map(([k, x]) => `${label(k)}: ${text(x)}`).join(" · ");
  const s = String(v);
  return /^[a-z]+(_[a-z]+)*$/.test(s) ? label(s) : s;  // stored choice values (e.g. non_corrosive) read as words
}

/** Label/value tiles in a responsive grid; empty values are shown as "Not recorded" in a muted tone. */
function FieldGrid({ rows }: { rows: [string, unknown][] }) {
  if (!rows.length) return <p className="muted small">Nothing recorded.</p>;
  return (
    <dl className="field-grid">
      {rows.map(([k, v]) => {
        const t = text(v);
        return (
          <div key={k} className="field-tile">
            <dt>{k}</dt>
            <dd className={t ? "" : "muted"}>{t || "Not recorded"}</dd>
          </div>
        );
      })}
    </dl>
  );
}

function Section({ title, badge, children }: { title: string; badge?: ReactNode; children: ReactNode }) {
  return (
    <section className="approval-section">
      <header><h3>{title}</h3>{badge}</header>
      {children}
    </section>
  );
}

function Meters({ c }: { c: Completeness }) {
  return (
    <ul className="approval-meters" aria-label="Data captured">
      {Object.entries(c).map(([k, v]) => {
        const pct = v.total ? Math.round((v.done / v.total) * 100) : 0;
        return (
          <li key={k}>
            <span className="approval-meter-name">{LEVEL_NAMES[k] ?? k}</span>
            <span className="meter-bar" role="img" aria-label={`${v.done} of ${v.total}`}><span style={{ width: `${pct}%` }} /></span>
            <span className="approval-meter-count">{v.done}/{v.total}</span>
          </li>
        );
      })}
    </ul>
  );
}

const fieldLabel = (k: string, prefix = "") => FIELD_LABELS[prefix + k] ?? label(k);

function RevisionContent({ d }: { d: Detail }) {
  const c = (d.revision.content ?? {}) as Obj;
  const rl1 = (c.rl1 ?? {}) as Obj;
  const rl2 = (c.rl2 ?? {}) as Obj;
  const na = (rl1.not_applicable ?? {}) as Record<string, string>;
  const spec = (rl2.manufacturing_spec ?? {}) as Obj;
  const acceptance = (Array.isArray(rl2.mechanical_acceptance) ? rl2.mechanical_acceptance : []) as Obj[];
  const evidence = (((c.rl3 ?? {}) as Obj).evidence ?? {}) as Record<string, string>;
  const notes = typeof c.notes === "string" ? c.notes : "";
  const evidenceFiles = useApprovalFiles(d);
  const comp = (d.revision.completeness ?? {}) as Completeness;
  const count = (k: string) => comp[k] ? <Badge tone={comp[k].done === comp[k].total ? "success" : "neutral"}>{comp[k].done}/{comp[k].total}</Badge> : undefined;

  const rl1Rows: [string, unknown][] = Object.keys(rl1).filter((k) => k !== "not_applicable")
    .map((k) => [fieldLabel(k), k in na ? `Not applicable — ${na[k]}` : rl1[k]]);
  Object.keys(na).filter((k) => !(k in rl1)).forEach((k) => rl1Rows.push([fieldLabel(k), `Not applicable — ${na[k]}`]));
  const rl2Rows: [string, unknown][] = Object.keys(rl2).filter((k) => !["mechanical_acceptance", "manufacturing_spec"].includes(k))
    .map((k) => [fieldLabel(k), k === "criticality_amsl" && rl2[k] ? `${text(rl2[k])} (provisional)` : rl2[k]]);
  const specRows: [string, unknown][] = Object.keys(spec).map((k) => [fieldLabel(k, "manufacturing_spec.").replace(/^Spec: /, ""), spec[k]]);

  return (
    <>
      <Section title="R-L1 · Identification and operating context" badge={count("rl1")}><FieldGrid rows={rl1Rows} /></Section>
      <Section title="R-L2 · Manufacturing solution and acceptance" badge={count("rl2")}>
        <FieldGrid rows={rl2Rows} />
        {acceptance.length > 0 && (
          <div className="approval-sub">
            <h4>Mechanical acceptance</h4>
            <div className="table-scroll">
              <table className="table compact">
                <thead><tr>{ACCEPTANCE_COLS.map(([, h]) => <th key={h}>{h}</th>)}</tr></thead>
                <tbody>{acceptance.map((r, i) => <tr key={i}>{ACCEPTANCE_COLS.map(([k]) => <td key={k}>{k === "property" ? label(text(r[k])) : text(r[k]) || "—"}</td>)}</tr>)}</tbody>
              </table>
            </div>
          </div>
        )}
        {specRows.length > 0 && <div className="approval-sub"><h4>Manufacturing specification (Aries internal)</h4><FieldGrid rows={specRows} /></div>}
      </Section>
      <Section title="R-L3 · Document evidence" badge={count("rl3")}>
        <ul className="evidence-list">
          {RL3_EVIDENCE.map((k) => {
            const id = evidence[k];
            const f = id ? d.evidence_files?.[id] : undefined;
            const file = id ? d.files.find((x) => x.id === id) : undefined;
            return (
              <li key={k} className={f ? "" : "is-missing"}>
                <Icon name={f ? "file" : "alert"} size="sm" />
                <span className="evidence-name">{fieldLabel(k)}</span>
                <span className="evidence-file">{f ? <><strong>{f.title}</strong> <span className="muted small">{f.category}</span></> : <span className="muted">Not attached</span>}</span>
                {file && <FileActions f={file} files={evidenceFiles} />}
              </li>
            );
          })}
        </ul>
      </Section>
      <Documents d={d} files={evidenceFiles} />
      <DocPreview files={evidenceFiles} />
      {notes && <Section title="Engineering notes"><pre className="approval-notes">{notes}</pre></Section>}
    </>
  );
}

export default function PassportApprovalsPage() {
  const { session } = useAuth();
  const list = useApi<Row[]>("/operator/passport-approvals/");
  const [open, setOpen] = useState<Row | null>(null);
  const detail = useApi<Detail>(open ? `/operator/passport-approvals/${open.client_id}/${open.passport_id}/` : null);
  const [note, setNote] = useState("");
  const [returning, setReturning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState("");

  async function decide(decision: "approve" | "return", e?: FormEvent) {
    e?.preventDefault();
    if (!open) return;
    setBusy(true);
    setError(null);
    try {
      await api(`/operator/passport-approvals/${open.client_id}/${open.passport_id}/`, { body: { decision, note } });
      setDone(`${open.passport_number} rev ${open.revision_number} ${decision === "approve" ? "approved" : "sent back to the engineer"}.`);
      setOpen(null);
      setNote("");
      setReturning(false);
      await list.reload();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const rows = list.data ?? [];
  const d = detail.data;
  const own = !!d && d.submitted_by_email === session?.user.email;
  return (
    <>
      <PageHeader marine title="Passport approvals" subtitle="Passport revisions submitted by Aries Engineers and waiting for approval, across all client companies." />
      {done && <Notice kind="success">{done}</Notice>}
      <div className="approvals-layout">
        <aside className="card approvals-queue" aria-label="Waiting for approval">
          <div className="card-head"><h2>Waiting <span className="count-pill">{rows.length}</span></h2></div>
          <ErrorNotice error={list.error} />
          {list.loading && !list.data ? <Loading /> : rows.length === 0 ? <Empty icon="passport">Nothing is waiting for approval.</Empty> : (
            <ul className="approval-list">
              {rows.map((r) => (
                <li key={`${r.client_id}-${r.passport_id}`}>
                  <button type="button" className={`approval-row ${open?.passport_id === r.passport_id ? "is-active" : ""}`} aria-current={open?.passport_id === r.passport_id}
                    onClick={() => { setOpen(r); setDone(""); setError(null); setReturning(false); setNote(""); }}>
                    <span className="approval-row-top"><strong>{r.passport_number}</strong><Badge tone="info">rev {r.revision_number}</Badge></span>
                    <span className="approval-row-title">{r.title}</span>
                    <span className="muted small">{r.client_name}</span>
                    <span className="muted small">{r.submitted_by_email || "—"} · {formatDate(r.submitted_at)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </aside>

        <section className="approvals-detail" aria-label="Selected passport">
          {!open && (
            <div className="card approvals-empty"><Empty icon="review">Choose a passport on the left to review its data and decide.</Empty></div>
          )}
          {open && detail.loading && !d && <div className="card"><Loading /></div>}
          {open && <ErrorNotice error={detail.error ?? error} />}
          {open && d && (
            <>
              <div className="card approval-summary">
                <div className="approval-summary-head">
                  <div>
                    <p className="hero-eyebrow"><Icon name="passport" size="sm" />Digital passport <span className="hero-number">{d.passport_number}</span> · rev {d.revision_number}</p>
                    <h2>{d.title}</h2>
                  </div>
                  <Badge tone="warning">Waiting for approval</Badge>
                </div>
                <dl className="approval-meta">
                  <div><dt>Client</dt><dd>{d.client_name}</dd></div>
                  <div><dt>Spare part</dt><dd>{d.part_number} · {d.part_name}</dd></div>
                  <div><dt>Submitted by</dt><dd>{d.submitted_by_email || "—"}</dd></div>
                  <div><dt>Submitted</dt><dd>{formatDate(d.submitted_at)}</dd></div>
                  <div className="span-2"><dt>Change summary</dt><dd>{d.change_summary || <span className="muted">No summary</span>}</dd></div>
                </dl>
                <Meters c={(d.revision.completeness ?? {}) as Completeness} />
              </div>
              <div className="card approval-content"><RevisionContent d={d} /></div>
              <div className="card approval-decision">
                {own ? <Notice kind="warning">You submitted this revision; another approver must decide it.</Notice> : returning ? (
                  <form className="stack" onSubmit={(e) => void decide("return", e)} aria-label="Send back for changes">
                    <label className="field"><span>What should the engineer change?</span>
                      <textarea rows={3} maxLength={500} required value={note} onChange={(e) => setNote(e.target.value)} /></label>
                    <div className="toolbar">
                      <button className="btn btn-primary" disabled={busy || !note.trim()}>Send back</button>
                      <button type="button" className="btn btn-ghost" onClick={() => setReturning(false)}>Cancel</button>
                    </div>
                  </form>
                ) : (
                  <div className="approval-decision-row">
                    <p className="muted small">Approval marks the passport “Engineering approved”. Publication and manufacturing release are not changed.</p>
                    <div className="toolbar">
                      <button type="button" className="btn" disabled={busy} onClick={() => setReturning(true)}>Send back</button>
                      <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void decide("approve")}>Approve</button>
                    </div>
                  </div>
                )}
              </div>
            </>
          )}
        </section>
      </div>
    </>
  );
}
