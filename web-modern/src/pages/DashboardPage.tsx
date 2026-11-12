import type { Client, DashboardSummary, IntakeEnvelope, MembershipSummary, Paginated } from "@passport/api-types";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { DATA_LEVEL_LABEL, DataLevel, DocChips, Thumbnail } from "../components/catalog";
import { useDecision } from "../components/decision";
import { Icon, type IconName } from "../components/icons";
import { ListPager, ListToolbar, useListControls } from "../components/ListControls";
import { NeedsAttention } from "../components/NeedsAttention";
import { ClientIntelligenceCard } from "../components/ClientIntelligenceLinks";
import { EntryRoutes } from "../components/EntryRoutes";
import { KpiWave, MarineBanner } from "../components/MarineHero";
import { Badge, Card, Empty, ErrorNotice, Loading, Notice, PageHeader, formatDate, label } from "../components/ui";

function Stat({ label, value, to, icon, hint }: { label: string; value: number | string; to?: string; icon?: IconName; hint?: string }) {
  const body = (
    <>
      {icon && <Icon name={icon} />}
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
      {hint && <div className="muted small">{hint}</div>}
      <KpiWave />
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
  const [all, setAll] = useState(false);
  const [filter, setFilter] = useState("");
  // Many organisations: the current one and the most active first, the rest on request (no wall of rows)
  const shown = useMemo(() => {
    const list = [...(rows.data ?? [])].filter((m) => !filter || m.tenant.name.toLowerCase().includes(filter.toLowerCase()))
      .sort((a, b) => Number(b.current) - Number(a.current) || (b.counts.parts + b.counts.passports) - (a.counts.parts + a.counts.passports));
    return all || filter ? list : list.slice(0, 6);
  }, [rows.data, all, filter]);
  if (!rows.data || rows.data.length < 2) return null;
  const total = rows.data.length;
  return (
    <Card title={`My organisations (${total})`} actions={total > 6 ? (
      <div className="toolbar" style={{ margin: 0 }}>
        <input type="search" aria-label="Filter organisations" placeholder="Filter organisations" value={filter}
          onChange={(e) => setFilter(e.target.value)} style={{ width: 220 }} />
        {!filter && <button type="button" className="btn btn-small" onClick={() => setAll((a) => !a)}>{all ? "Show fewer" : `Show all ${total}`}</button>}
      </div>) : undefined}>
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
          {shown.map((m) => (
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
      <MarineBanner>
        <PageHeader
          title={isOperator ? "Operator dashboard" : `${session?.tenant.name}`}
          subtitle={isOperator ? "Digitalisation, passports and client organisations" : `Digital inventory of ${session?.tenant.name}`}
        />
      </MarineBanner>
      {!isOperator && <EntryRoutes />}
      <NeedsAttention compact />
      <ClientIntelligenceCard />
      <ErrorNotice error={summary.error} />
      {summary.loading && !s ? (
        <Loading variant="cards" />
      ) : s ? (
        <>
          <div className="stats">
            {isOperator && can("clients.view") && <Stat label="Client organisations" value={clients.data?.count ?? "…"} to="/clients" icon="building" />}
            <Stat label="Spare parts" value={s.parts.total} to="/parts" icon="boxes" />
            <Stat label="Digital passports" value={s.passports.total} to="/passports" icon="passport" />
            <Stat label="Open passport drafts" value={s.passports.open_drafts} to="/passports" icon="edit" />
            <Stat label="Parts with a 3D view" value={s.documents.parts_with_3d} to="/parts?has_3d=true" icon="cube" />
          </div>
          {!isOperator && can("intelligence.view") && can("inventory.import") && <AssessmentSnapshot />}
          {s.passports.total === 0 && s.documents.total === 0 && s.conversions.succeeded + s.conversions.queued + s.conversions.running + s.conversions.failed === 0 ? (
            <p className="dash-quiet"><Icon name="info" size="sm" />No digital passports, engineering documents or 3D conversions yet. Passport data, document
              coverage and 3D conversion status appear here once parts are digitised.</p>
          ) : <div className="grid-3">
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
          </div>}
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
                        {p.passport_id ? <><Link to={`/passports/${p.passport_id}`}>{p.passport_number}</Link> · <DataLevel level={p.data_captured} /></>
                          : <span className="muted">No passport</span>}{" "}· <DocChips documents={p.documents} has3d={p.has_3d} />
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
      <MyOrganisations />
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
  const { can, session } = useAuth();
  const admin = can("clients.view");
  const overview = useApi<OverviewRow[]>(admin ? "/operator/overview/" : null);
  const pendingRegs = useApi<Paginated<{ id: string; company_name: string; contact_name: string; created_at: string }>>(
    can("registrations.review") ? "/registrations/" : null, { query: { status: "pending", page_size: 5 } });
  const queue = useApi<IntakeEnvelope[]>(can("requests.handle") ? "/operator/requests/" : null, { query: { open: "true" } });
  const open = queue.data ?? [];
  const waiting = open.filter((r) => r.status === "submitted").length;
  const rows = overview.data ?? [];
  const sum = (k: keyof OverviewRow["counts"]) => rows.reduce((n, r) => n + r.counts[k], 0);
  // 70+ organisations, most of them test registrations with no activity: open on the active ones, everything one click away
  const activity = (r: OverviewRow) => r.counts.parts + r.counts.passports + r.counts.open_requests * 5;
  const c = useListControls(rows, {
    text: (r) => r.name,
    filters: [["active", "With activity", (r) => activity(r) > 0], ["waiting", "Awaiting acknowledgement", (r) => r.counts.awaiting_acknowledgement > 0],
      ["no_staff", "No Aries staff", (r) => r.counts.assigned_staff === 0], ["all", "All", () => true]],
    sorts: [["activity", "Most activity", (a, b) => activity(b) - activity(a) || a.name.localeCompare(b.name)],
      ["requests", "Open requests", (a, b) => b.counts.open_requests - a.counts.open_requests || a.name.localeCompare(b.name)],
      ["parts", "Spare parts", (a, b) => b.counts.parts - a.counts.parts || a.name.localeCompare(b.name)], ["name", "Name A–Z", (a, b) => a.name.localeCompare(b.name)]],
    pageSize: 10,
  });
  return (
    <>
      <MarineBanner>
        <PageHeader title="Aries Admin Dashboard" subtitle="Manage client companies, registrations, assignments and incoming requests." />
      </MarineBanner>
      <NeedsAttention compact />
      <div className="stats stats-3">
        {can("registrations.review") && (
          <Stat label="Registrations pending approval" value={pendingRegs.data ? pendingRegs.data.count : "…"} to="/registrations" icon="inbox" />
        )}
        {admin && <Stat label="Client organisations" value={overview.data ? rows.length : "…"} to="/clients" icon="building" />}
        {admin && <Stat label="Spare parts across clients" value={overview.data ? sum("parts") : "…"} icon="boxes" />}
        {admin && <Stat label="Digital passports across clients" value={overview.data ? sum("passports") : "…"} icon="passport" />}
        <Stat label="Open requests" value={queue.data ? open.length : "…"} to="/incoming" icon="message" />
        <Stat label="Awaiting acknowledgement" value={queue.data ? waiting : "…"} to="/incoming?status=submitted" icon="clock" />
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
          {overview.loading && !overview.data ? <Loading /> : rows.length ? (<>
            <p className="list-summary">{rows.length} client organisations · {rows.filter((r) => activity(r) > 0).length} with activity ·{" "}
              {sum("open_requests")} open requests · {rows.filter((r) => r.counts.assigned_staff === 0).length} without Aries staff</p>
            <ListToolbar c={c} searchLabel="Search client organisations" />
            <div className="table-scroll">
            <table className="table table-stack" aria-label="Client overview">
              <thead><tr><th>Client</th><th className="num">Spare parts</th><th className="num">Passports</th><th className="num">Open requests</th><th className="num">Awaiting acknowledgement</th><th className="num">Client users</th><th className="num">Assigned staff</th><th>Hosting</th></tr></thead>
              <tbody>
                {c.visible.map((r) => (
                  <tr key={r.id}>
                    <td><Link to={`/clients/${r.id}`}><strong>{r.name}</strong></Link>{r.status !== "active" && <> <Badge tone="warning">{r.status}</Badge></>}</td>
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
            </div>
            <ListPager c={c} noun="client organisations" />
          </>) : <Empty>No client organisations yet.</Empty>}
          <p className="muted small">{session?.admin_access?.can_enter_companies
            ? <>Counts only here. Open a company's records through Digital inventory (Open record) or the company chooser; manage assignments
              and company details under <Link to="/clients">Clients</Link>.</>
            : <>Counts only. Client records are opened by Aries staff assigned to that client; manage assignments and company
              details under <Link to="/clients">Clients</Link>.</>}</p>
        </Card>
      )}
      <MyOrganisations />
    </>
  );
}

type AssessmentDash = { latest: { run: { number: number; quarter: string; finished_at: string; status_label: string };
  summary: { assessed: number; in_scope: number; insufficient_technical_data: number; am_candidates: number; conventional_candidates: number;
    review_backlog: { total: number }; savings: { estimated: Record<string, string>; verified: Record<string, string> } } | null } | null };

const money = (m: Record<string, string>) =>
  Object.entries(m).map(([c, v]) => `${c} ${Number(v).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`).join("; ") || "none";

/** Aries Engineer: the latest quarterly assessment at a glance (CN-007), linking into the AI workflow. */
function AssessmentSnapshot() {
  const d = useApi<AssessmentDash>("/intelligence/assessments/");
  const run = d.data?.latest?.run, s = d.data?.latest?.summary;
  return (
    <Card title="AI spare-parts assessment" actions={<Link to="/inventory-import?tab=assessment" className="btn btn-small"><Icon name="chart" size="sm" />Open quarterly assessment</Link>}>
      {d.loading && !d.data ? <Loading /> : !run || !s ? (
        <Empty icon="chart">No assessment run yet. Start one from the <Link to="/inventory-import?tab=assessment">quarterly assessment</Link>.</Empty>
      ) : (
        <>
          <p className="muted small">Run {run.number} · {run.quarter} · {run.status_label} · {formatDate(run.finished_at)}. Preliminary analytics: nothing is approved or released.</p>
          <div className="stat-row">
            <div className="stat"><strong>{s.assessed}/{s.in_scope}</strong><span className="muted small">Assessed</span></div>
            <div className="stat"><strong>{s.insufficient_technical_data}</strong><span className="muted small">Insufficient technical data</span></div>
            <div className="stat"><strong>{s.am_candidates} / {s.conventional_candidates}</strong><span className="muted small">AM / conventional candidates</span></div>
            <div className="stat"><strong>{s.review_backlog.total}</strong><span className="muted small">Review backlog</span></div>
          </div>
          <div className="savings-pair" style={{ marginTop: 10 }}>
            <div className="savings-box is-estimated"><span className="muted small">Estimated savings (provisional, not validated)</span><strong>{money(s.savings.estimated)}</strong></div>
            <div className="savings-box is-verified"><span className="muted small">Verified savings</span><strong>{money(s.savings.verified)}</strong></div>
          </div>
        </>
      )}
    </Card>
  );
}

export default function DashboardPage() {
  const { session } = useAuth();
  return session?.tenant.kind === "operator" ? <OperatorHome /> : <OrganisationDashboard />;
}
