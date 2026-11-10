/**
 * Aries Engineer: client sharing queue (CN-007, ai.share). Disclosure state of every part in the engineering lifecycle in the engineer's
 * scope — internal draft, engineering reviewed, approved for client sharing, shared, withdrawn — and open client
 * assessment requests. Sharing happens on the part page (Client sharing panel).
 */
import { useState } from "react";
import { Link } from "react-router-dom";

import { useApi } from "../api/useApi";
import { AiWorkflow } from "../components/AiWorkflow";
import { STATE_TONE } from "../components/ClientSharing";
import { Badge, Card, Empty, ErrorNotice, Loading, Notice, PageHeader, formatDate } from "../components/ui";

type Row = { id: string; part_number: string; name: string; state: { code: string; label: string }; recommendation_version: number | null;
  shared_version: number | null; shared_at: string | null; open_request: { reference: string; status_label: string } | null };
type Queue = { parts: Row[]; counts: Record<string, number>; workspace_enabled: boolean; statement: string };

const FILTERS: [string, string][] = [["", "All"], ["engineering_reviewed", "Ready to approve"], ["approved", "Approved, not shared"],
  ["shared", "Shared"], ["internal_draft", "Internal draft"], ["withdrawn", "Withdrawn"], ["not_assessed", "No recommendation"]];

export default function AiSharingPage() {
  const q = useApi<Queue>("/intelligence/disclosures/");
  const [filter, setFilter] = useState("");
  const rows = (q.data?.parts ?? []).filter((r) => !filter || r.state.code === filter);
  const requested = (q.data?.parts ?? []).filter((r) => r.open_request).length;
  return (
    <>
      <PageHeader title="Client sharing" subtitle="Decide which reviewed assessment results the client company may see. Information disclosure only." />
      <AiWorkflow current="review" targets={{ inventory: "/inventory-import?tab=quality", classification: "/inventory-import?tab=intelligence",
        feasibility: "/inventory-import?tab=intelligence", commercial: "/inventory-import?tab=intelligence", recommendation: "/inventory-import?tab=intelligence",
        review: "/ai/sharing", assessment: "/inventory-import?tab=assessment" }} />
      <ErrorNotice error={q.error} />
      {q.loading && !q.data ? <Loading /> : q.data && (
        <>
          {!q.data.workspace_enabled && <Notice kind="warning">The client workspace of this company is switched off: results can be prepared but
            not approved or shared. The Aries Admin controls it under AI management.</Notice>}
          {requested > 0 && <Notice kind="info">{requested} part(s) have an open client assessment request (see Incoming requests).</Notice>}
          <Card title="Parts and their disclosure state" actions={
            <div className="segmented" role="group" aria-label="Filter by disclosure state">
              {FILTERS.map(([k, l]) => (
                <button key={k || "all"} type="button" aria-pressed={filter === k} onClick={() => setFilter(k)}>
                  {l}{k && <span className="count">{q.data!.counts[k] ?? 0}</span>}</button>))}
            </div>}>
            {rows.length === 0 ? <Empty icon="eye">Nothing in this state.</Empty> : (
              <div className="table-scroll">
                <table className="table table-stack" aria-label="Client sharing queue">
                  <thead><tr><th>Material number</th><th>Disclosure state</th><th>Latest version</th><th>Shared</th><th>Client request</th><th /></tr></thead>
                  <tbody>{rows.map((r) => (
                    <tr key={r.id}>
                      <td><Link to={`/parts/${r.id}?tab=ai&step=sharing`}><strong>{r.part_number}</strong></Link><div className="small">{r.name}</div></td>
                      <td><Badge tone={STATE_TONE[r.state.code] ?? "neutral"}>{r.state.label}</Badge></td>
                      <td>{r.recommendation_version ? `v${r.recommendation_version}` : "—"}</td>
                      <td className="small">{r.shared_version ? <>v{r.shared_version}<div className="muted">{formatDate(r.shared_at)}</div></> : "—"}</td>
                      <td className="small">{r.open_request ? <>{r.open_request.reference}<div className="muted">{r.open_request.status_label}</div></> : "—"}</td>
                      <td className="actions"><Link className="btn btn-small" to={`/parts/${r.id}?tab=ai&step=sharing`}>Open</Link></td>
                    </tr>))}
                  </tbody>
                </table>
              </div>
            )}
            <p className="muted small">{q.data.statement}</p>
          </Card>
        </>
      )}
    </>
  );
}
