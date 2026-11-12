/**
 * Aries Admin: choose the client company to work in (super-administrator workspaces). Opening a company switches the
 * session to that company's own workspace (audited in both organisations), then opens the requested module there.
 */
import type { MembershipSummary } from "@passport/api-types";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { useApi } from "../api/useApi";
import { useEnterContext } from "../components/AdminNav";
import { Card, Empty, ErrorNotice, Loading, Notice, PageHeader } from "../components/ui";

const MODULES: Record<string, string> = {
  "/parts": "Digital inventory", "/passports": "Digital passports", "/projects": "Projects", "/inventory-import": "Inventory import",
  "/inventory-import?tab=intelligence": "Part intelligence", "/inventory-import?tab=intelligence&view=feasibility": "Manufacturing feasibility",
  "/inventory-import?tab=intelligence&view=cost": "Cost comparison", "/inventory-import?tab=intelligence&view=review": "AI recommendations",
  "/ai/sharing": "Client sharing", "/inventory-import?tab=assessment": "Quarterly assessment", "/edit-requests": "Edit requests",
};

export default function AdminCompaniesPage() {
  const [params] = useSearchParams();
  const next = params.get("next") && params.get("next")!.startsWith("/") ? params.get("next")! : "/parts";
  const m = useApi<MembershipSummary[]>("/auth/memberships/");
  const enter = useEnterContext();
  const [q, setQ] = useState("");
  const [error, setError] = useState<unknown>(null);
  const companies = (m.data ?? []).filter((x) => x.tenant.kind === "client" && x.tenant.name.toLowerCase().includes(q.trim().toLowerCase()));
  return (
    <>
      <PageHeader marine title="Choose a client company" subtitle={`Open ${MODULES[next] ?? "the module"} in a client company's own workspace.`} />
      <Notice kind="info">You work inside the company you choose: its data stays in its own workspace and every action is recorded in its
        audit trail. Engineering sign-off, passport approval and manufacturing release are not part of Aries Admin access.</Notice>
      <ErrorNotice error={m.error ?? error} />
      {m.loading && !m.data && <Loading />}
      {m.data && (
        <Card title={`Client companies (${companies.length})`}>
          <div className="toolbar"><input type="search" aria-label="Search companies" placeholder="Search companies" value={q} onChange={(e) => setQ(e.target.value)} /></div>
          {companies.length === 0 ? <Empty>No company matches.</Empty> : (
            <div className="table-scroll">
              <table className="table table-stack" aria-label="Client companies">
                <thead><tr><th>Company</th><th>Spare parts</th><th>Passports</th><th>Draft revisions</th><th><span className="sr-only">Open</span></th></tr></thead>
                <tbody>
                  {companies.map((c) => (
                    <tr key={c.tenant.slug}>
                      <td><strong>{c.tenant.name}</strong></td>
                      <td>{c.counts.parts}</td><td>{c.counts.passports}</td><td>{c.counts.draft_revisions}</td>
                      <td className="actions">
                        <button type="button" className="btn btn-small btn-primary" aria-label={`Open ${MODULES[next] ?? "module"} of ${c.tenant.name}`}
                          onClick={() => enter(c.tenant.slug, next).catch(setError)}>Open</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}
    </>
  );
}
