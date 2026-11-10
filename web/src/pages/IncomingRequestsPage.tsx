/**
 * Operator: incoming client requests from all client organisations (intake summaries kept in the operator
 * organisation). Opening a request needs an active assignment to that client; unassigned rows are shown but locked.
 */
import type { IntakeEnvelope } from "@passport/api-types";
import { useEffect } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { useApi } from "../api/useApi";
import { KIND, KindBadge, STATUS, StatusBadge } from "../components/requests";
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

  return (
    <>
      <PageHeader title="Incoming requests" subtitle="Manufacturing enquiries and 3D scanning requests from client organisations." />
      <Card>
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
          {waiting > 0 && <Badge tone="warning">{waiting} awaiting acknowledgement</Badge>}
        </div>
        <ErrorNotice error={list.error} />
        {list.loading && !list.data ? <Loading /> : rows.length ? (
          <table className="table requests-table" aria-label="Incoming requests">
            <thead>
              <tr><th>Reference</th><th>Client</th><th>Type</th><th>Part / subject</th><th className="num">Qty</th><th>Required</th><th>Priority</th><th>Status</th><th>Submitted</th></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className={r.status === "submitted" ? "row-attention" : ""}>
                  <td>{r.assigned ? <Link to={`/incoming/${r.id}`}><strong>{r.reference}</strong></Link>
                    : <span title="You are not assigned to this client organisation"><strong>{r.reference}</strong> <span className="muted small">(not assigned)</span></span>}</td>
                  <td>{r.client_name}</td>
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
        ) : (
          <Empty>{kind || status ? "No requests match these filters." : "No open requests. New client requests appear here and in your notifications."}</Empty>
        )}
      </Card>
    </>
  );
}
