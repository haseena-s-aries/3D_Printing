import type { Client, DashboardSummary, IntakeEnvelope, MembershipSummary, Paginated } from "@passport/api-types";
import { useEffect, useState } from "react";
import { useDecision } from "../components/decision";
import { Link, useNavigate } from "react-router-dom";

import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { DATA_LEVEL_LABEL, DataLevel, DocChips, Thumbnail } from "../components/catalog";
import { Badge, Card, Empty, ErrorNotice, Loading, Notice, PageHeader, formatDate, label } from "../components/ui";

function Stat({ label, value, to }: { label: string; value: number | string; to?: string }) {
  const body = (
    <>
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </>
  );
  return to ? (
    <Link className="stat" to={to}>
      {body}
    </Link>
  ) : (
    <div className="stat">{body}</div>
  );
}

/** Organisations this user works in, with counts; one click switches the session there (UX-1). */
function MyOrganisations() {
  const { session, switchTenant } = useAuth();
  const navigate = useNavigate();
  const rows = useApi<MembershipSummary[]>("/auth/memberships/", { query: { m: session?.membership.id } });
  const [error, setError] = useState<unknown>(null);
  if (!rows.data || rows.data.length < 2) return null;
  return (
    <Card title="My organisations">
      <ErrorNotice error={error} />
      <table className="table">
        <thead>
          <tr>
            <th>Organisation</th>
            <th>Role</th>
            <th className="num">Spare parts</th>
            <th className="num">Passports</th>
            <th className="num">Open drafts</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.data.map((m) => (
            <tr key={m.tenant.slug} className={m.current ? "selected" : ""}>
              <td>
                <strong>{m.tenant.name}</strong> <Badge>{m.tenant.kind}</Badge>
              </td>
              <td>{label(m.role)}</td>
              <td className="num">{m.counts.parts}</td>
              <td className="num">{m.counts.passports}</td>
              <td className="num">{m.counts.draft_revisions}</td>
              <td className="actions">
                {m.current ? (
                  <span className="muted small">Current</span>
                ) : (
                  <button
                    type="button"
                    className="btn btn-small"
                    onClick={async () => {
                      try {
                        await switchTenant(m.tenant.slug);
                        navigate("/", { replace: true });
                      } catch (e) {
                        setError(e);
                      }
                    }}
                  >
                    Open
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function Meter({ label, value, total, to }: { label: string; value: number; total: number; to?: string }) {
  const pct = total ? Math.round((value / total) * 100) : 0;
  const body = (
    <>
      <span className="meter-label">{label}</span>
      <span className="meter-track" aria-hidden>
        <span className="meter-fill" style={{ width: `${pct}%` }} />
      </span>
      <span className="meter-value">{value}</span>
    </>
  );
  return to ? <Link className="meter" to={to}>{body}</Link> : <div className="meter">{body}</div>;
}

const CONVERSION_LABEL: [keyof DashboardSummary["conversions"], string][] = [
  ["succeeded", "3D view ready"], ["queued", "Queued"], ["running", "Converting"], ["failed", "Failed"], ["not_requested", "Not requested"],
];

function OrganisationDashboard() {
  const { session, can } = useAuth();
  const oq = useDecision();
  const isOperator = session?.tenant.kind === "operator";
  const summary = useApi<DashboardSummary>("/dashboard/summary/");
  const clients = useApi<Paginated<Client>>(isOperator && can("clients.view") ? "/clients/" : null);
  const s = summary.data;
  const busy = !!s && s.conversions.queued + s.conversions.running > 0;

  // Keep conversion status current while STEP files are being converted
  useEffect(() => {
    if (!busy) return;
    const t = window.setInterval(() => void summary.reload(), 5000);
    return () => window.clearInterval(t);
  }, [busy, summary.reload]);

  return (
    <>
      <PageHeader
        title={isOperator ? "Operator dashboard" : `${session?.tenant.name}`}
        subtitle={isOperator ? "Digitalisation, passports and client organisations" : `Digital inventory of ${session?.tenant.name}`}
      />
      <MyOrganisations />
      <ErrorNotice error={summary.error} />
      {summary.loading && !s ? (
        <Loading />
      ) : s ? (
        <>
          <div className="stats">
            {isOperator && can("clients.view") && <Stat label="Client organisations" value={clients.data?.count ?? "…"} to="/clients" />}
            <Stat label="Spare parts" value={s.parts.total} to="/parts" />
            <Stat label="Digital passports" value={s.passports.total} to="/passports" />
            <Stat label="Open passport drafts" value={s.passports.open_drafts} to="/passports" />
            <Stat label="Parts with a 3D view" value={s.documents.parts_with_3d} to="/parts?has_3d=true" />
          </div>
          <div className="grid-3">
            <Card title="Passport data captured">
              <p className="muted small">Guidance on data entry. The official evidence level is a separate field that cannot change yet{oq("OQ-35")}.</p>
              {(["none", "rl1", "rl2", "rl3"] as const).map((k) => (
                <Meter key={k} label={DATA_LEVEL_LABEL[k]} value={s.passports.by_data_captured[k] ?? 0} total={s.passports.total} to={`/parts?data_level=${k}`} />
              ))}
              <p className="small">
                Official evidence level: {s.passports.by_evidence_level.none ?? 0} of {s.passports.total} not assessed.
              </p>
            </Card>
            <Card title="Engineering documents">
              <Meter label="Parts with a drawing" value={s.documents.parts_with_drawing} total={s.parts.total} />
              <Meter label="Parts with a specification" value={s.documents.parts_with_specification} total={s.parts.total} />
              <Meter label="Parts with a 3D view" value={s.documents.parts_with_3d} total={s.parts.total} to="/parts?has_3d=true" />
              <Meter label="Parts with a photograph" value={s.documents.parts_with_photo} total={s.parts.total} />
              <p className="small">
                {s.documents.total} files: {s.documents.by_kind.step ?? 0} STEP · {s.documents.by_kind.dwg ?? 0} DWG · {s.documents.by_kind.pdf ?? 0} PDF ·{" "}
                {s.documents.by_kind.image ?? 0} photos. {s.documents.parts_without_documents} parts have no documents yet.
              </p>
            </Card>
            <Card title="3D conversion" actions={busy ? <span className="muted small" aria-live="polite">Updating…</span> : undefined}>
              <ul className="list compact-list" aria-label="Conversion status">
                {CONVERSION_LABEL.map(([k, l]) => (
                  <li key={k} className="row-between">
                    <span>{l}</span> <strong>{s.conversions[k] as number}</strong>
                  </li>
                ))}
              </ul>
              {s.conversions.failed_items.length > 0 && (
                <>
                  <h3>Needs attention</h3>
                  <ul className="list compact-list">
                    {s.conversions.failed_items.map((f) => (
                      <li key={f.file}>
                        <Link to={f.passport ? `/passports/${f.passport}?tab=documents` : `/parts/${f.part}`}>{f.part_number}</Link>{" "}
                        <span className="muted small">{f.title}</span>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </Card>
          </div>
          <Card title="Recently updated parts" actions={<Link to="/parts">Open digital inventory</Link>}>
            {s.recent_parts.length ? (
              <ul className="list recent-parts">
                {s.recent_parts.map((p) => (
                  <li key={p.id}>
                    <Thumbnail thumb={p.thumbnail} alt={p.part_number} size={44} />
                    <div className="grow">
                      <Link to={`/parts/${p.id}`}>
                        <strong>{p.part_number}</strong>
                      </Link>{" "}
                      <span className="muted">{p.name}</span>
                      <div className="small">
                        {p.passport_id ? <Link to={`/passports/${p.passport_id}`}>{p.passport_number}</Link> : <span className="muted">No passport</span>}{" "}
                        · <DataLevel level={p.data_captured} /> · <DocChips documents={p.documents} has3d={p.has_3d} />
                      </div>
                    </div>
                    <span className="muted small">{formatDate(p.last_activity)}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <Empty>No spare parts yet.</Empty>
            )}
          </Card>
        </>
      ) : null}
      <div className="grid-2">
        <Card title="Platform status">
          <Notice kind="warning">
            Passport approval, publication and manufacturing release are not available yet{oq("OQ-35, OQ-36")}. Manufacturing requests are received as enquiries.
          </Notice>
          <Notice>DWG drawings can be downloaded; in-browser DWG preview is not available yet{oq("OQ-27")}.</Notice>
        </Card>
      </div>
    </>
  );
}

interface OverviewRow {
  id: string; name: string; slug: string; status: string; hosting_model: string;
  counts: { parts: number; passports: number; open_requests: number; awaiting_acknowledgement: number; client_users: number; assigned_staff: number };
}

/** Platform Operator organisation: client overview and request oversight instead of an (always empty) inventory.
 *  Aggregate counts only; detailed records stay inside each client organisation. */
function OperatorHome() {
  const { can } = useAuth();
  const admin = can("clients.view");
  const overview = useApi<OverviewRow[]>(admin ? "/operator/overview/" : null);
  const pendingRegs = useApi<Paginated<{ id: string; company_name: string; contact_name: string; created_at: string }>>(
    can("registrations.review") ? "/registrations/" : null, { query: { status: "pending", page_size: 5 } });
  const queue = useApi<IntakeEnvelope[]>(can("requests.handle") ? "/operator/requests/" : null, { query: { open: "true" } });
  const open = queue.data ?? [];
  const waiting = open.filter((r) => r.status === "submitted").length;
  const rows = overview.data ?? [];
  const sum = (k: keyof OverviewRow["counts"]) => rows.reduce((n, r) => n + r.counts[k], 0);
  return (
    <>
      <PageHeader title="Aries Admin dashboard" subtitle="Client companies, registrations, assignments and incoming requests" />
      <MyOrganisations />
      <div className="stats">
        {can("registrations.review") && (
          <Stat label="Registrations pending approval" value={pendingRegs.data ? pendingRegs.data.count : "…"} to="/registrations" />
        )}
        {admin && <Stat label="Client organisations" value={overview.data ? rows.length : "…"} to="/clients" />}
        {admin && <Stat label="Spare parts across clients" value={overview.data ? sum("parts") : "…"} />}
        {admin && <Stat label="Digital passports across clients" value={overview.data ? sum("passports") : "…"} />}
        <Stat label="Open requests" value={queue.data ? open.length : "…"} to="/incoming" />
        <Stat label="Awaiting acknowledgement" value={queue.data ? waiting : "…"} to="/incoming?status=submitted" />
      </div>
      {can("registrations.review") && (pendingRegs.data?.count ?? 0) > 0 && (
        <Card title="Pending company registrations">
          <ul className="list" aria-label="Pending registrations">
            {pendingRegs.data!.results.map((r) => (
              <li key={r.id} className="row-between">
                <span><Link to={`/registrations/${r.id}`}><strong>{r.company_name}</strong></Link> <span className="muted small">{r.contact_name}</span></span>
                <Link className="btn btn-small btn-primary" to={`/registrations/${r.id}`}>Review</Link>
              </li>
            ))}
          </ul>
        </Card>
      )}
      {admin && (
        <Card title="Client organisations">
          <ErrorNotice error={overview.error} />
          {overview.loading && !overview.data ? <Loading /> : rows.length ? (
            <table className="table" aria-label="Client overview">
              <thead><tr><th>Client</th><th className="num">Spare parts</th><th className="num">Passports</th><th className="num">Open requests</th><th className="num">Awaiting acknowledgement</th><th className="num">Client users</th><th className="num">Assigned staff</th><th>Hosting</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td><strong>{r.name}</strong>{r.status !== "active" && <> <Badge tone="warning">{r.status}</Badge></>}</td>
                    <td className="num">{r.counts.parts}</td>
                    <td className="num">{r.counts.passports}</td>
                    <td className="num">{r.counts.open_requests ? <Link to={`/incoming?client=${r.id}`}>{r.counts.open_requests}</Link> : 0}</td>
                    <td className="num">{r.counts.awaiting_acknowledgement ? <Badge tone="warning">{r.counts.awaiting_acknowledgement}</Badge> : 0}</td>
                    <td className="num">{r.counts.client_users}</td>
                    <td className="num">{r.counts.assigned_staff}</td>
                    <td className="small">{label(r.hosting_model)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <Empty>No client organisations yet.</Empty>}
          <p className="muted small">Counts only. Client records are opened by Aries staff assigned to that client; manage assignments and company
            details under <Link to="/clients">Clients</Link>.</p>
        </Card>
      )}
    </>
  );
}

export default function DashboardPage() {
  const { session } = useAuth();
  return session?.tenant.kind === "operator" ? <OperatorHome /> : <OrganisationDashboard />;
}
