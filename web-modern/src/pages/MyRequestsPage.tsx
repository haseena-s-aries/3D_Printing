/** Client: the organisation's manufacturing enquiries / requests and 3D scanning requests, with live status. */
import type { Paginated, ServiceRequestRow } from "@passport/api-types";
import { useEffect } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { KIND, KindBadge, STATUS, StatusBadge } from "../components/requests";
import { Card, Empty, ErrorNotice, Loading, PageHeader, formatDate } from "../components/ui";

export default function MyRequestsPage() {
  const { can } = useAuth();
  const [params, setParams] = useSearchParams();
  const kind = params.get("kind") ?? "";
  const status = params.get("status") ?? "";
  const list = useApi<Paginated<ServiceRequestRow>>("/requests/", { query: { kind, status, page_size: 100 } });

  useEffect(() => {
    const t = window.setInterval(() => void list.reload(), 20000); // status changes made by the operator team
    return () => window.clearInterval(t);
  }, [list.reload]);

  const set = (k: string, v: string) => setParams((p) => { const n = new URLSearchParams(p); v ? n.set(k, v) : n.delete(k); return n; });

  return (
    <>
      <PageHeader
        title="My requests"
        subtitle="Manufacturing enquiries and 3D scanning requests of your organisation, and their status."
        actions={can("requests.create") && (
          <div className="toolbar">
            <Link className="btn" to="/parts">Request from catalog</Link>
            <Link className="btn btn-primary" to="/requests/new-scan">Request 3D scanning</Link>
          </div>
        )}
      />
      <Card>
        <div className="toolbar wrap">
          <select aria-label="Filter by request type" value={kind} onChange={(e) => set("kind", e.target.value)}>
            <option value="">All request types</option>
            {Object.entries(KIND).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          <select aria-label="Filter by status" value={status} onChange={(e) => set("status", e.target.value)}>
            <option value="">All statuses</option>
            {Object.entries(STATUS).map(([v, [l]]) => <option key={v} value={v}>{l}</option>)}
          </select>
          <button type="button" className="btn btn-ghost" onClick={() => void list.reload()}>Refresh</button>
        </div>
        <ErrorNotice error={list.error} />
        {list.loading && !list.data ? <Loading /> : list.data?.results.length ? (
          <table className="table requests-table">
            <thead><tr><th>Reference</th><th>Type</th><th>Subject</th><th>Quantity / date</th><th>Status</th><th>Submitted</th></tr></thead>
            <tbody>
              {list.data.results.map((r) => (
                <tr key={r.id}>
                  <td><Link to={`/requests/${r.id}`}><strong>{r.reference}</strong></Link></td>
                  <td><KindBadge kind={r.kind} /></td>
                  <td>{r.kind === "digitisation" ? <>{r.part_description.split("\n")[0]}<div className="muted small">{r.site_location}</div></>
                    : <><strong>{r.part_number}</strong> {r.part_name}</>}</td>
                  <td className="small">{r.quantity ? `${r.quantity} pcs · ` : ""}{r.required_date ?? r.preferred_date ?? "—"}</td>
                  <td><StatusBadge status={r.status} /></td>
                  <td className="small">{formatDate(r.created_at)}<div className="muted small">{r.requested_by_email}</div></td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <Empty>{kind || status ? "No requests match these filters." : "No requests yet. Use Request on a part in the digital inventory, or request 3D scanning of a new part."}</Empty>
        )}
      </Card>
    </>
  );
}
