import type { AuditEvent, Paginated } from "@passport/api-types";
import { useState } from "react";

import { useApi } from "../api/useApi";
import { Card, Empty, ErrorNotice, Loading, PageHeader, Pager, formatDate } from "../components/ui";

const PAGE_SIZE = 50;
// Values are the model names recorded by apps.audit.service.record
const OBJECT_TYPES: [string, string][] = [
  ["digitalpassport", "Passport"], ["passportrevision", "Passport revision"], ["sparepart", "Spare part"], ["engineeringfile", "Engineering file"],
  ["fileversion", "File version"], ["derivative", "Derivative"], ["membership", "Membership / sign-in"], ["tenant", "Organisation"], ["project", "Project"],
];

/** `clientId` embeds the trail for one client company (Client Management → Audit History): events this organisation
 * recorded about that company. Record-view events are hidden unless asked for. */
export default function AuditPage({ clientId }: { clientId?: string } = {}) {
  const [action, setAction] = useState("");
  const [filters, setFilters] = useState({ action: "", object_type: "", page: 1, views: false });
  const { views, ...rest } = filters;
  const query = clientId ? { ...rest, client: clientId, exclude_views: views ? "" : "true" } : rest;
  const list = useApi<Paginated<AuditEvent>>("/audit-events/", { query: { ...query, page_size: PAGE_SIZE } });
  return (
    <>
      {!clientId && <PageHeader title="Audit trail" subtitle="Append-only record of activity in this organisation." />}
      <Card>
        <form className="toolbar" role="search" onSubmit={(e) => { e.preventDefault(); setFilters({ ...filters, action: action.trim(), page: 1 }); }}>
          <input aria-label="Filter by action" placeholder="Action, e.g. file.downloaded" value={action} onChange={(e) => setAction(e.target.value)} />
          <select aria-label="Filter by object type" value={filters.object_type} onChange={(e) => setFilters({ ...filters, object_type: e.target.value, page: 1 })}>
            <option value="">All objects</option>
            {OBJECT_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          {clientId && (
            <label className="inline-check"><input type="checkbox" checked={views} onChange={(e) => setFilters({ ...filters, views: e.target.checked, page: 1 })} /> Include record views</label>
          )}
          <button className="btn">Filter</button>
        </form>
        <ErrorNotice error={list.error} />
        {list.loading && !list.data ? <Loading /> : list.data?.results.length ? (
          <>
            <table className="table">
              <thead><tr><th>When</th><th>Who</th><th>Action</th><th>Object</th></tr></thead>
              <tbody>
                {list.data.results.map((e) => (
                  <tr key={e.id}>
                    <td className="small">{formatDate(e.created_at)}</td>
                    <td>{e.actor_email || "system"}<div className="muted small">{e.actor_role}</div></td>
                    <td className="mono small">{e.action}</td>
                    <td className="small">{e.object_type} <span className="muted mono">{(e.object_id ?? "").slice(0, 8)}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <Pager page={filters.page} count={list.data.count} pageSize={PAGE_SIZE} onPage={(page) => setFilters({ ...filters, page })} />
          </>
        ) : <Empty>No events match.</Empty>}
      </Card>
    </>
  );
}
