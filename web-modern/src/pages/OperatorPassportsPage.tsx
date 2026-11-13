/**
 * Aries Admin and Aries Manager: every client company's digital passports (read-only), opened from the Aries
 * organisation. The list on the left can be filtered by company, status and text; the selected passport shows its data,
 * documents (opened in the page), reports, 3D model and revision history, with Publish / Unpublish. Every opening is
 * audited in the client company. Aries Engineers edit passports inside the client company.
 */
import type { components } from "@passport/api-types";
import { useMemo, useState } from "react";

import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Icon } from "../components/icons";
import { Badge, Empty, ErrorNotice, Loading, Notice, PageHeader, formatDate, label } from "../components/ui";
import { Meters, RevisionContent, type Detail } from "./PassportApprovalsPage";

type Row = components["schemas"]["OperatorPassportRow"];
type RegisterDetail = Detail & Row & {
  revisions: { revision_number: number; status: string; change_summary: string; completed_by_email: string; completed_at: string | null; created_at: string }[];
  can_publish: boolean;
};

const STATES: [string, string][] = [["", "All statuses"], ["draft", "Draft"], ["revision_in_progress", "Revision in progress"],
  ["complete", "Complete"], ["published", "Published"], ["submitted", "Submitted (earlier flow)"]];
const TONE: Record<string, "neutral" | "info" | "success" | "warning"> = {
  draft: "neutral", revision_in_progress: "warning", complete: "info", published: "success", submitted: "warning",
};
const REV_LABEL: Record<string, string> = { draft: "Draft", submitted: "Submitted", approved: "Complete", superseded: "Superseded" };

export default function OperatorPassportsPage() {
  const [state, setState] = useState("");
  const [client, setClient] = useState("");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const list = useApi<Row[]>("/operator/passports/", { query: { state, client, search: query } });
  const all = useApi<Row[]>("/operator/passports/");  // the company filter offers every company that has passports
  const [open, setOpen] = useState<Row | null>(null);
  const root = open ? `/operator/passports/${open.client_id}/${open.passport_id}` : "";
  const detail = useApi<RegisterDetail>(open ? `${root}/` : null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState("");
  const companies = useMemo(() => {
    const m = new Map<string, string>();
    (all.data ?? []).forEach((r) => m.set(r.client_id, r.client_name));
    return [...m.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [all.data]);

  async function publish(action: "publish" | "unpublish") {
    if (!open) return;
    let reason = "";
    if (action === "unpublish") {
      const r = window.prompt("Why is it taken out of the client's catalog? (shown to the client)");
      if (r === null) return;
      reason = r;
    } else if (!window.confirm(`Publish ${open.passport_number} to ${open.client_name}'s catalog?`)) return;
    setBusy(true);
    setError(null);
    try {
      await api(`${root}/`, { body: { action, reason } });
      setDone(`${open.passport_number} ${action === "publish" ? "published to the client's catalog" : "taken out of the client's catalog"}.`);
      await Promise.all([detail.reload(), list.reload()]);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const rows = list.data ?? [];
  const d = detail.data;
  return (
    <>
      <PageHeader marine title="Digital passports" subtitle="Every client company's digital passports. Open one to see its data, documents, reports and 3D model, and publish it to the client." />
      {done && <Notice kind="success">{done}</Notice>}
      <div className="approvals-layout">
        <aside className="card approvals-queue" aria-label="Passports">
          <div className="card-head"><h2>Passports <span className="count-pill">{rows.length}</span></h2></div>
          <form className="register-filters" onSubmit={(e) => { e.preventDefault(); setQuery(search.trim()); }}>
            <input type="search" placeholder="Passport, part number or title" aria-label="Search passports" value={search} onChange={(e) => setSearch(e.target.value)} />
            <select aria-label="Company" value={client} onChange={(e) => setClient(e.target.value)}>
              <option value="">All companies</option>
              {companies.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
            </select>
            <select aria-label="Status" value={state} onChange={(e) => setState(e.target.value)}>
              {STATES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </form>
          <ErrorNotice error={list.error} />
          {list.loading && !list.data ? <Loading /> : rows.length === 0 ? <Empty icon="passport">No passports match.</Empty> : (
            <ul className="approval-list">
              {rows.map((r) => (
                <li key={r.passport_id}>
                  <button type="button" className={`approval-row ${open?.passport_id === r.passport_id ? "is-active" : ""}`} aria-current={open?.passport_id === r.passport_id}
                    onClick={() => { setOpen(r); setDone(""); setError(null); }}>
                    <span className="approval-row-top"><strong>{r.passport_number}</strong><Badge tone={TONE[r.passport_state] ?? "neutral"}>{r.passport_state_label}</Badge></span>
                    <span className="approval-row-title">{r.title}</span>
                    <span className="muted small">{r.client_name} · part {r.part_number}{r.revision_number ? ` · rev ${r.revision_number}` : ""}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </aside>

        <section className="approvals-detail" aria-label="Selected passport">
          {!open && <div className="card approvals-empty"><Empty icon="passport">Choose a passport on the left to open it.</Empty></div>}
          {open && detail.loading && !d && <div className="card"><Loading label="Loading passport…" /></div>}
          {open && <ErrorNotice error={detail.error ?? error} />}
          {open && d && (
            <>
              <div className="card approval-summary">
                <div className="approval-summary-head">
                  <div>
                    <p className="hero-eyebrow"><Icon name="passport" size="sm" />Digital passport <span className="hero-number">{d.passport_number}</span> · rev {d.revision_number}</p>
                    <h2>{d.title}</h2>
                  </div>
                  <span className="toolbar">
                    <Badge tone={TONE[d.passport_state] ?? "neutral"}>{d.passport_state_label}</Badge>
                    {d.can_publish && d.passport_state === "complete" && (
                      <button type="button" className="btn btn-primary" disabled={busy} aria-busy={busy} onClick={() => void publish("publish")}>
                        <Icon name="check" size="sm" />Publish to client</button>
                    )}
                    {d.can_publish && d.passport_state === "published" && (
                      <button type="button" className="btn" disabled={busy} aria-busy={busy} onClick={() => void publish("unpublish")}>Unpublish</button>
                    )}
                  </span>
                </div>
                <dl className="approval-meta">
                  <div><dt>Client</dt><dd>{d.client_name}</dd></div>
                  <div><dt>Spare part</dt><dd>{d.part_number} · {d.part_name}</dd></div>
                  <div><dt>Completed by</dt><dd>{d.submitted_by_email || "—"}{d.submitted_at ? ` · ${formatDate(d.submitted_at)}` : ""}</dd></div>
                  <div><dt>Manufacturing</dt><dd>{label(d.manufacturing_eligibility)}</dd></div>
                </dl>
                {d.passport_state !== "complete" && d.passport_state !== "published" && (
                  <p className="muted small">It can be published once an Aries Engineer has marked the current revision complete.</p>
                )}
                <Meters c={(d.revision.completeness ?? {}) as Record<string, { done: number; total: number }>} />
              </div>
              <div className="card approval-content">
                <RevisionContent d={{ ...d, root }} />
                <section className="approval-section">
                  <header><h3>Revision history</h3></header>
                  <ul className="doc-list">
                    {d.revisions.map((r) => (
                      <li key={r.revision_number}>
                        <Icon name="history" size="sm" />
                        <span className="doc-name"><strong>Rev {r.revision_number}</strong>
                          <span className="muted small">{r.change_summary || "No summary"}{r.completed_by_email ? ` · completed by ${r.completed_by_email}` : ""}
                            {r.completed_at ? ` · ${formatDate(r.completed_at)}` : ` · started ${formatDate(r.created_at)}`}</span></span>
                        <Badge tone={r.status === "approved" ? "success" : r.status === "draft" ? "neutral" : "info"}>{REV_LABEL[r.status] ?? label(r.status)}</Badge>
                        <span />
                      </li>
                    ))}
                  </ul>
                </section>
              </div>
            </>
          )}
        </section>
      </div>
    </>
  );
}
