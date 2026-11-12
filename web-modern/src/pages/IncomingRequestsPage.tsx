/**
 * Operator: incoming client requests from all client organisations (intake summaries kept in the operator
 * organisation). Opening a request needs an active assignment to that client; unassigned rows are shown but locked.
 */
import type { IntakeEnvelope } from "@passport/api-types";
import { useEffect } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { useApi } from "../api/useApi";
import { KIND, KindBadge, STATUS, StatusBadge } from "../components/requests";
import { ListPager, ListToolbar, useListControls } from "../components/ListControls";
import { Badge, Card, Empty, ErrorNotice, Loading, PageHeader, formatDate } from "../components/ui";

export default function IncomingRequestsPage() {
  const [params, setParams] = useSearchParams();
  const kind = params.get("kind") ?? "";
  const status = params.get("status") ?? "";
  const openOnly = params.get("all") !== "true";
  const clientId = params.get("client") ?? "";
  const list = useApi<IntakeEnvelope[]>("/operator/requests/", { query: { kind, status, client_tenant: clientId, open: openOnly && !status ? "true" : "" } });

  useEffect(() => {
    const t = window.setInterval(() => void list.reload(), 15000);
    return () => window.clearInterval(t);
  }, [list.reload]);

  const set = (k: string, v: string) => setParams((p) => { const n = new URLSearchParams(p); v ? n.set(k, v) : n.delete(k); return n; });
  const rows = list.data ?? [];
  const waiting = rows.filter((r) => r.status === "submitted").length;
  const c = useListControls(rows, {
    text: (r) => `${r.intake_number} ${r.reference} ${r.client_name} ${r.part_number ?? ""} ${r.part_name ?? ""}`,
    filters: [["all", "All shown", () => true], ["submitted", "Needs acknowledgement", (r) => r.status === "submitted"],
      ["working", "In progress", (r) => r.status !== "submitted" && !["closed", "declined", "withdrawn", "completed"].includes(r.status)],
      ["urgent", "Urgent", (r) => r.priority === "urgent"]],
    sorts: [["newest", "Newest first", (a, b) => b.submitted_at.localeCompare(a.submitted_at)],
      ["oldest", "Oldest first", (a, b) => a.submitted_at.localeCompare(b.submitted_at)], ["client", "Client A–Z", (a, b) => a.client_name.localeCompare(b.client_name)]],
    pageSize: 15,
  });

  return (
    <>
      <PageHeader marine title="Incoming requests" subtitle="Manufacturing enquiries, 3D scanning and AI assessment requests from client organisations." />
      <Card>
        {list.data && <p className="list-summary">{rows.length} {openOnly && !status ? "open " : ""}requests · {waiting} awaiting acknowledgement ·{" "}
          {rows.filter((r) => r.priority === "urgent").length} urgent · {new Set(rows.map((r) => r.client_name)).size} client organisations</p>}
        {rows.length > 0 && <ListToolbar c={c} searchLabel="Search requests" placeholder="Search by intake number, client reference, client or part" />}
        <div className="toolbar wrap">
          <select aria-label="Filter by request type" value={kind} onChange={(e) => set("kind", e.target.value)}>
            <option value="">All request types</option>
            {Object.entries(KIND).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          <select aria-label="Filter by status" value={status} onChange={(e) => set("status", e.target.value)}>
            <option value="">{openOnly ? "Open requests" : "All statuses"}</option>
            {Object.entries(STATUS).map(([v, [l]]) => <option key={v} value={v}>{l}</option>)}
          </select>
          <label className="inline-check"><input type="checkbox" checked={!openOnly} onChange={(e) => set("all", e.target.checked ? "true" : "")} /> Include closed</label>
          {clientId && <button type="button" className="btn btn-ghost" onClick={() => set("client", "")}>Show all clients</button>}
          <button type="button" className="btn btn-ghost" onClick={() => void list.reload()}>Refresh</button>
        </div>
        <ErrorNotice error={list.error} />
        {list.loading && !list.data ? <Loading /> : rows.length ? (<>
          <div className="table-scroll">
          <table className="table requests-table table-stack" aria-label="Incoming requests">
            <thead>
              <tr><th>Intake no. · client reference</th><th>Type</th><th>Part / subject</th><th className="num">Qty</th><th>Required</th><th>Priority</th><th>Status</th><th>Submitted</th></tr>
            </thead>
            <tbody>
              {c.visible.map((r) => (
                <tr key={r.id} className={r.status === "submitted" ? "row-attention" : ""}>
                  <td className="ref-cell">{r.assigned ? <Link to={`/incoming/${r.id}`}><strong>{r.intake_number || r.reference}</strong></Link>
                    : <span title="You are not assigned to this client organisation"><strong>{r.intake_number || r.reference}</strong> <span className="muted small">(not assigned)</span></span>}
                    <div className="small">{r.client_name} · <span className="muted">client ref.</span> {r.reference}</div></td>
                  <td><KindBadge kind={r.kind} /></td>
                  <td>{r.part_number && <strong>{r.part_number} </strong>}{r.part_name}</td>
                  <td className="num">{r.quantity ?? "—"}</td>
                  <td className="small">{r.required_date ?? "—"}</td>
                  <td>{r.priority === "urgent" ? <Badge tone="danger">Urgent</Badge> : <span className="muted small">Routine</span>}</td>
                  <td><StatusBadge status={r.status} /></td>
                  <td className="small">{formatDate(r.submitted_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
          <ListPager c={c} noun="requests" />
        </>) : (
          <Empty>{kind || status ? "No requests match these filters." : "No open requests. New client requests appear here and in your notifications."}</Empty>
        )}
      </Card>
    </>
  );
}
