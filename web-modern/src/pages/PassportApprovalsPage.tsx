/**
 * Aries Admin and Aries Manager: passport revisions waiting for approval across client companies. Opening one shows its
 * data; Approve or Send back (with a note) is decided here. The submitter can never decide their own revision (server rule).
 * Aries Engineers approve from the passport inside the client project.
 */
import type { components } from "@passport/api-types";
import { useState, type FormEvent } from "react";

import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { Badge, Card, Empty, ErrorNotice, Loading, Notice, PageHeader, formatDate, label } from "../components/ui";

type Row = components["schemas"]["PassportApprovalRow"];
type Detail = Row & { passport_state: string; revision: components["schemas"]["Revision"] };

const LEVELS: [string, string][] = [["rl1", "R-L1 · Identification and operating context"], ["rl2", "R-L2 · Manufacturing solution and acceptance"],
  ["rl3", "R-L3 · Document evidence"], ["notes", "Engineering notes"]];

function show(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (Array.isArray(v)) return v.map(show).join(", ") || "—";
  if (typeof v === "object") return Object.entries(v as Record<string, unknown>).map(([k, x]) => `${label(k)}: ${show(x)}`).join("; ");
  return String(v);
}

function Done({ c }: { c: Row["completeness"] }) {
  const parts = Object.entries((c ?? {}) as Record<string, { done: number; total: number }>)
    .map(([k, v]) => `${k.toUpperCase().replace("RL", "R-L")} ${v.done}/${v.total}`);
  return <span className="muted small">{parts.join(" · ") || "—"}</span>;
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
      setDone(`${open.passport_number} rev ${open.revision_number} ${decision === "approve" ? "approved" : "sent back to the author"}.`);
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
      <div className="grid-2 approvals">
        <Card title={`Waiting for approval (${rows.length})`}>
          <ErrorNotice error={list.error} />
          {list.loading && !list.data ? <Loading /> : rows.length === 0 ? <Empty icon="passport">Nothing is waiting for approval.</Empty> : (
            <ul className="approval-list">
              {rows.map((r) => (
                <li key={`${r.client_id}-${r.passport_id}`}>
                  <button type="button" className={`approval-row ${open?.passport_id === r.passport_id ? "is-active" : ""}`}
                    onClick={() => { setOpen(r); setDone(""); setError(null); setReturning(false); }}>
                    <span className="approval-main"><strong>{r.passport_number}</strong> rev {r.revision_number} · {r.title}</span>
                    <span className="muted small">{r.client_name} · part {r.part_number} · submitted by {r.submitted_by_email || "—"} · {formatDate(r.submitted_at)}</span>
                    <Done c={r.completeness} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title={open ? `${open.passport_number} rev ${open.revision_number}` : "Select a passport"}>
          {!open && <Empty icon="review">Choose a passport on the left to review its data and decide.</Empty>}
          {open && detail.loading && !d && <Loading />}
          <ErrorNotice error={detail.error ?? error} />
          {open && d && (
            <div className="stack">
              <dl className="facts">
                <div><dt>Client</dt><dd>{d.client_name}</dd></div>
                <div><dt>Spare part</dt><dd>{d.part_number} · {d.part_name}</dd></div>
                <div><dt>Passport state</dt><dd><Badge tone="info">{label(d.passport_state)}</Badge></dd></div>
                <div><dt>Submitted by</dt><dd>{d.submitted_by_email || "—"} · {formatDate(d.submitted_at)}</dd></div>
                <div><dt>Change summary</dt><dd>{d.change_summary || "—"}</dd></div>
              </dl>
              {LEVELS.map(([k, title]) => {
                const section = (d.revision.content as Record<string, unknown>)?.[k];
                if (!section || typeof section !== "object" || Object.keys(section).length === 0) return null;
                return (
                  <details key={k} className="approval-section" open={k === "rl1"}>
                    <summary>{title}</summary>
                    <dl className="facts">
                      {Object.entries(section as Record<string, unknown>).map(([f, v]) => <div key={f}><dt>{label(f)}</dt><dd>{show(v)}</dd></div>)}
                    </dl>
                  </details>
                );
              })}
              {own ? <Notice kind="warning">You submitted this revision; another approver must decide it.</Notice> : (
                returning ? (
                  <form className="stack" onSubmit={(e) => void decide("return", e)} aria-label="Send back for changes">
                    <label className="field"><span>What should the engineer change?</span>
                      <textarea rows={3} maxLength={500} required value={note} onChange={(e) => setNote(e.target.value)} /></label>
                    <div className="toolbar">
                      <button className="btn btn-primary" disabled={busy || !note.trim()}>Send back</button>
                      <button type="button" className="btn btn-ghost" onClick={() => setReturning(false)}>Cancel</button>
                    </div>
                  </form>
                ) : (
                  <div className="toolbar">
                    <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void decide("approve")}>Approve</button>
                    <button type="button" className="btn" disabled={busy} onClick={() => setReturning(true)}>Send back</button>
                  </div>
                )
              )}
              <p className="muted small">Approval marks the passport “Engineering approved”. Publication and manufacturing release are not changed.</p>
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
