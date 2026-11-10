/**
 * Aries Admin → Clients → one client company. Tabs reuse the existing panels and APIs unchanged; the selected tab is
 * kept in the URL (?tab=), so Back, refresh and links work. Digital Inventory is the administrative summary only.
 */
import type { Client } from "@passport/api-types";
import { useState } from "react";
import { Link, useLocation, useParams, useSearchParams } from "react-router-dom";

import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { ClientEngineers, ClientOverview, ClientProjects, useClientDetails } from "../components/ClientAdminPanels";
import ClientUsers from "../components/ClientUsers";
import { Badge, BackLink, Card, ErrorNotice, Loading, Notice } from "../components/ui";
import AdminInventoryPage from "./AdminInventoryPage";
import AuditPage from "./AuditPage";
import { ClientImports } from "./InventoryImportPage";
import { ThumbnailContractWorkspace } from "./ThumbnailContractPage";

export const CLIENT_TABS = [
  ["overview", "Overview"], ["engineers", "Engineers & Access"], ["projects", "Projects"], ["users", "Client Users"],
  ["inventory", "Digital Inventory"], ["imports", "Inventory Import"], ["contract", "Thumbnail Contract"], ["audit", "Audit History"],
] as const;
type Tab = (typeof CLIENT_TABS)[number][0];

export default function ClientManagementPage() {
  const { id = "" } = useParams();
  const location = useLocation();
  const { can } = useAuth();
  const tabs = CLIENT_TABS.filter(([t]) => t !== "contract" || can("contracts.thumbnail_view"));
  const [params, setParams] = useSearchParams();
  const tab: Tab = tabs.some(([t]) => t === params.get("tab")) ? (params.get("tab") as Tab) : "overview";
  const client = useApi<Client>(`/clients/${id}/`);
  const details = useClientDetails(id);
  const [message, setMessage] = useState<string | null>((location.state as { message?: string } | null)?.message ?? null);
  // A new history entry per tab, so browser Back returns to the previous tab; other query keys belong to the old tab.
  const go = (t: Tab) => { setMessage(null); setParams(t === "overview" ? {} : { tab: t }); };
  const changed = (msg: string) => { setMessage(msg); void client.reload(); };

  if (client.error) return <><BackLink to="/clients">Client organisations</BackLink><ErrorNotice error={client.error} /></>;
  if (!client.data) return <Loading />;
  const c = client.data;
  const tabName = CLIENT_TABS.find(([t]) => t === tab)?.[1];
  return (
    <>
      <nav className="crumbs client-crumbs" aria-label="Client breadcrumb">
        <Link to="/clients">Client organisations</Link><span>{c.name}</span><span aria-current="page">{tabName}</span>
      </nav>
      <header className="page-header client-header">
        <div>
          <h1>{c.name}</h1>
          <p className="muted">
            <Badge tone={c.status === "active" ? "success" : "warning"}>{c.status}</Badge>{" "}
            <span className="mono small">{c.slug}</span> · {c.hosting_model === "dedicated" ? "Dedicated Azure deployment" : "Shared Azure platform"}
            {" "}· {c.member_count} active member{c.member_count === 1 ? "" : "s"}{" "}
            {c.profile_complete ? <Badge tone="success">Profile complete</Badge> : <Badge tone="warning">Profile incomplete</Badge>}
          </p>
        </div>
      </header>
      {message && <Notice kind="success"><span role="status">{message}</span></Notice>}
      <div className="tabs" role="tablist" aria-label="Client management">
        {tabs.map(([t, name]) => (
          <button key={t} type="button" role="tab" id={`client-tab-${t}`} aria-selected={tab === t} aria-controls={`client-panel-${t}`}
            className={`tab ${tab === t ? "is-active" : ""}`} onClick={() => go(t)}>{name}</button>
        ))}
      </div>
      <section role="tabpanel" id={`client-panel-${tab}`} aria-labelledby={`client-tab-${tab}`} className="tab-panel">
        {tab === "overview" && <ClientOverview client={c} details={details} onChanged={changed} />}
        {tab === "engineers" && <ClientEngineers client={c} details={details} onChanged={changed} />}
        {tab === "projects" && <ClientProjects client={c} details={details} />}
        {tab === "users" && <Card title="Client users"><ClientUsers client={c} onChanged={() => { void client.reload(); void details.reload(); }} /></Card>}
        {tab === "inventory" && <AdminInventoryPage clientId={c.id} />}
        {tab === "imports" && <ClientImports clientId={c.id} />}
        {tab === "contract" && <ThumbnailContractWorkspace clientId={c.id} />}
        {tab === "audit" && <AuditPage clientId={c.id} />}
      </section>
    </>
  );
}
