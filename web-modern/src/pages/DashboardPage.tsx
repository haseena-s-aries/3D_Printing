import type { Client, DashboardSummary, IntakeEnvelope, MembershipSummary, Paginated } from "@passport/api-types";
import { useEffect, useMemo, useState, type ReactNode } from "react";
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
import { ActivityHeatmap, BarChart, ChartCard, Donut, Growth, RangeSelect, RequestWorkflow, RequestsByStatus, Sparkline, TrendChart,
  monthLabel } from "../components/DashboardCharts";

const countBy = (rows: { status: string }[]) => rows.reduce<Record<string, number>>((m, r) => ({ ...m, [r.status]: (m[r.status] ?? 0) + 1 }), {});
import { KpiWave, MarineBanner } from "../components/MarineHero";
import { KindBadge, StatusBadge } from "../components/requests";
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

interface OrgAnalytics {
  months: string[];
  series: Record<"parts" | "passports" | "approvals" | "requests", number[]>;
  requests_visible: boolean;
  activity: { start: string; weeks: number; days: number[][] };
  by_status: Record<string, number>;
}

const OPEN_REQUEST = new Set(["submitted", "acknowledged", "information_requested", "information_provided", "answered", "scheduled", "in_progress",
  "engineering_checked", "qa_approved", "released", "in_production", "inspected"]);

/** A client organisation (or Aries staff working inside one): the same analytics layout as the Aries dashboards, over
 *  this organisation's records that the member may see (the server limits parts, passports and requests by project). */
function OrganisationDashboard() {
  const { session, can } = useAuth();
  const oq = useDecision();
  const isOperator = session?.tenant.kind === "operator";
  const summary = useApi<DashboardSummary>("/dashboard/summary/");
  const analytics = useApi<OrgAnalytics>("/dashboard/analytics/");
  const clients = useApi<Paginated<Client>>(isOperator && can("clients.view") ? "/clients/" : null);
  const [range, setRange] = useState(6);
  const [monthlyRange, setMonthlyRange] = useState(6);
  const s = summary.data;
  const a = analytics.data;
  const busy = !!s && s.conversions.queued + s.conversions.running > 0;
  const openCounts = a ? Object.fromEntries(Object.entries(a.by_status).filter(([k]) => OPEN_REQUEST.has(k))) : {};
  const openTotal = Object.values(openCounts).reduce((x, y) => x + y, 0);
  const requestsVisible = !!a?.requests_visible;
  const last = <T,>(xs: T[], n: number) => xs.slice(-n);
  const ic = (name: IconName) => <Icon name={name} size="sm" />;
  const rangeOpts: [number, string][] = [[6, "Last 6 months"], [12, "Last 12 months"]];

  // Keep conversion status current while STEP files are being converted
  useEffect(() => {
    if (!busy) return;
    const t = window.setInterval(() => void summary.reload(), 5000);
    return () => window.clearInterval(t);
  }, [busy, summary.reload]);

  return (
    <div className="analytics">
      <MarineBanner slim>
        <PageHeader
          title={isOperator ? "Operator dashboard" : `${session?.tenant.name}`}
          subtitle={isOperator ? "Digitalisation, passports and client organisations" : `Analytics for the digital inventory of ${session?.tenant.name}`}
        />
      </MarineBanner>
      {!isOperator && <EntryRoutes />}
      <ErrorNotice error={summary.error ?? analytics.error} />
      {summary.loading && !s ? (
        <Loading variant="cards" />
      ) : s ? (
        <>
          <div className="stats stats-6">
            {isOperator && can("clients.view") && <Stat label="Client organisations" value={clients.data?.count ?? "…"} to="/clients" icon="building" />}
            <Stat label="Spare parts" value={s.parts.total} to="/parts" icon="boxes" />
            <Stat label="Digital passports" value={s.passports.total} to="/passports" icon="passport" />
            <Stat label="Open passport drafts" value={s.passports.open_drafts} to="/passports" icon="edit" />
            <Stat label="Parts with a 3D view" value={s.documents.parts_with_3d} to="/parts?has_3d=true" icon="cube" />
            <Stat label="Engineering documents" value={s.documents.total} to="/parts" icon="file"
              hint={s.documents.parts_without_documents ? `${s.documents.parts_without_documents} parts without documents` : undefined} />
            {requestsVisible && <Stat label="Open requests" value={openTotal} to="/requests" icon="message" />}
          </div>
          <NeedsAttention compact />
          <ClientIntelligenceCard />
          {!isOperator && can("intelligence.view") && can("inventory.import") && <AssessmentSnapshot />}
          <div className="chart-grid">
            <ChartCard title="Digital passport trend" icon={ic("chart")}
              action={<RangeSelect label="Trend period" value={range} onChange={setRange} options={rangeOpts} />}>
              {a ? <TrendChart months={last(a.months, range)} series={[
                { label: "Digital passports (created)", values: last(a.series.passports, range), series: 1 },
                { label: "Spare parts (added)", values: last(a.series.parts, range), series: 3 }]} />
                : analytics.loading ? <Loading /> : null}
            </ChartCard>
            <ChartCard title="Passport data captured" icon={ic("layers")}>
              <BarChart series={[{ label: "Digital passports", series: 1 }]}
                groups={(["none", "rl1", "rl2", "rl3"] as const).map((k) => ({ key: k, label: DATA_LEVEL_LABEL[k],
                  values: [s.passports.by_data_captured[k] ?? 0], to: `/parts?data_level=${k}` }))} />
              <p className="muted small chart-note">Guidance on data entry. Official evidence level: {s.passports.by_evidence_level.none ?? 0} of{" "}
                {s.passports.total} not assessed; it cannot change yet{oq("OQ-35")}.</p>
            </ChartCard>
            {requestsVisible ? (
              <ChartCard title="Request status distribution" icon={ic("gauge")} action={<Link className="btn btn-small" to="/requests">Open all</Link>}>
                <RequestsByStatus counts={openCounts} base="/requests" />
              </ChartCard>
            ) : (
              <ConversionCard s={s} busy={busy} ic={ic} />
            )}
            {requestsVisible && a && (
              <ChartCard title="Monthly approvals & requests" icon={ic("calendar")}
                action={<RangeSelect label="Monthly period" value={monthlyRange} onChange={setMonthlyRange} options={rangeOpts} />}>
                <BarChart stacked series={[{ label: "Passport approvals", series: 7 }, { label: "Requests", series: 2 }]}
                  groups={last(a.months, monthlyRange).map((m, i) => {
                    const at = a.months.length - monthlyRange + i;
                    return { key: m, label: monthLabel(m), values: [a.series.approvals[at], a.series.requests[at]] };
                  })} />
              </ChartCard>
            )}
            {requestsVisible && a && (
              <ChartCard title="Request workflow" icon={ic("route")}>
                <RequestWorkflow byStatus={a.by_status} base="/requests" noun="requests" icon={(n) => <Icon name={n as IconName} />} />
              </ChartCard>
            )}
            <ChartCard title="Engineering documents" icon={ic("file")}>
              <Meter label="Parts with a drawing" value={s.documents.parts_with_drawing} total={s.parts.total} />
              <Meter label="Parts with a specification" value={s.documents.parts_with_specification} total={s.parts.total} />
              <Meter label="Parts with a 3D view" value={s.documents.parts_with_3d} total={s.parts.total} to="/parts?has_3d=true" />
              <Meter label="Parts with a photograph" value={s.documents.parts_with_photo} total={s.parts.total} />
              <p className="small chart-note">
                {s.documents.total} files: {s.documents.by_kind.step ?? 0} STEP · {s.documents.by_kind.dwg ?? 0} DWG · {s.documents.by_kind.pdf ?? 0} PDF ·{" "}
                {s.documents.by_kind.image ?? 0} photos. {s.documents.parts_without_documents} parts have no documents yet.
              </p>
            </ChartCard>
          </div>
          <div className="chart-grid chart-grid-foot">
            <ChartCard title="Recently updated parts" icon={ic("boxes")} className="chart-wide"
              action={<Link className="btn btn-small" to="/parts">Open digital inventory</Link>}>
              {s.recent_parts.length ? (
                <ul className="list recent-parts">
                  {s.recent_parts.slice(0, 5).map((p) => (
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
            </ChartCard>
            {requestsVisible && a && (
              <ChartCard title="Request activity" icon={ic("history")}>
                <ActivityHeatmap start={a.activity.start} days={a.activity.days} />
                <p className="muted small chart-note">Requests submitted per day, last {a.activity.weeks} weeks.</p>
              </ChartCard>
            )}
            {requestsVisible ? <ConversionCard s={s} busy={busy} ic={ic} /> : a ? (
              <ChartCard title="At a glance" icon={ic("gauge")}>
                <div className="glance">
                  <Growth values={a.series.passports} n={6} label="Digital passports created (vs. previous 6 months)" />
                  <Growth values={a.series.parts} n={6} label="Spare parts added (vs. previous 6 months)" />
                </div>
              </ChartCard>
            ) : null}
          </div>
        </>
      ) : null}
      <MyOrganisations />
      <div className="grid-2">
        <Card title="Platform status">
          <Notice>
            An Aries Engineer completes the passport (R-L1 and R-L2) and it is published to the client. Requests on a published part
            are manufacturing orders: engineering check, QA check, release, production, inspection and delivery. Other requests are enquiries.
          </Notice>
          <Notice>DWG drawings can be downloaded; in-browser DWG preview is not available yet{oq("OQ-27")}.</Notice>
        </Card>
      </div>
    </div>
  );
}

/** 3D conversion of STEP files: status as a donut, failed conversions listed with links (kept current while converting). */
function ConversionCard({ s, busy, ic }: { s: DashboardSummary; busy: boolean; ic: (n: IconName) => ReactNode }) {
  return (
    <ChartCard title="3D conversion" icon={ic("cube")} action={busy ? <span className="muted small" aria-live="polite">Updating…</span> : undefined}>
      <Donut caption="STEP files" empty="No STEP files yet."
        slices={CONVERSION_LABEL.map(([k, l], i) => ({ key: k, label: l, value: s.conversions[k] as number, series: [3, 4, 1, 2, 0][i] }))} />
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
    </ChartCard>
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
  // the client spoke last (a message or requested information) and Aries has not answered yet
  const messages = open.filter((r) => r.awaiting_reply && r.status !== "submitted")
    .sort((a, b) => (b.last_client_activity_at ?? "").localeCompare(a.last_client_activity_at ?? ""));
  const role = session?.membership.role ?? "";
  const platformAdmin = role === "operator_admin" || role === "operator_manager";
  const title = { operator_admin: "Aries Admin Dashboard", operator_manager: "Aries Manager Dashboard", operator_engineer: "Aries Engineer Dashboard",
    operator_qa: "Aries QA Dashboard", operator_support: "Aries Support Dashboard" }[role] ?? "Aries Dashboard";
  // newest work first, requests waiting for acknowledgement on top
  const recent = [...open].sort((a, b) => Number(b.status === "submitted") - Number(a.status === "submitted")
    || (b.submitted_at ?? "").localeCompare(a.submitted_at ?? ""));
  const approvalRows = useApi<{ client_id: string; client_name: string; part_id: string; part_number: string; name: string; revision: number;
    kind_label: string; review_state: string; aries_completion_requested: boolean; submitted_by_email: string; submitted_at: string }[]>(
    platformAdmin && can("passports.approve") ? "/operator/approvals/" : null);
  const approvals = { data: approvalRows.data ? approvalRows.data.filter((r) => r.review_state === "pending_review") : null };
  const rows = overview.data ?? [];
  const sum = (k: keyof OverviewRow["counts"]) => rows.reduce((n, r) => n + r.counts[k], 0);
  const staffAnalytics = admin || can("requests.handle");
  const analytics = useApi<Analytics>(staffAnalytics ? "/operator/analytics/" : null);
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
  if (staffAnalytics) {
    return <AnalyticsDashboard title={title} admin={admin} rows={rows} overview={overview} analytics={analytics} queue={queue} open={open} waiting={waiting}
      messages={messages.length} pendingRegs={can("registrations.review") ? pendingRegs.data?.count ?? null : undefined} />;
  }
  return (
    <>
      <MarineBanner slim>
        <PageHeader title={title} subtitle={platformAdmin ? "Manage client companies, registrations, assignments and incoming requests."
          : "Client requests from the companies you are assigned to, and the work waiting for you."} />
      </MarineBanner>
      <div className="dash-top">
      <div className="stats stats-3">
        {can("registrations.review") && (
          <Stat label="Registrations pending approval" value={pendingRegs.data ? pendingRegs.data.count : "…"} to="/registrations" icon="inbox" />
        )}
        {admin && <Stat label="Client organisations" value={overview.data ? rows.length : "…"} to="/clients" icon="building" />}
        {admin && <Stat label="Spare parts across clients" value={overview.data ? sum("parts") : "…"} icon="boxes" />}
        {admin && <Stat label="Digital passports across clients" value={overview.data ? sum("passports") : "…"} icon="passport" />}
        <Stat label="Open requests" value={queue.data ? open.length : "…"} to="/incoming" icon="message" />
        <Stat label="Awaiting acknowledgement" value={queue.data ? waiting : "…"} to="/incoming?status=submitted" icon="clock" />
        {can("requests.handle") && <Stat label="Client messages awaiting reply" value={queue.data ? messages.length : "…"} to="/incoming?awaiting=true" icon="message" />}
        {platformAdmin && can("passports.approve") && (
          <Stat label="Client submissions awaiting approval" value={approvals.data ? approvals.data.length : "…"} to="/approvals" icon="boxes" />
        )}
      </div>
      <NeedsAttention compact />
      </div>
      <div className="dash-main">
      <div className="dash-col dash-col-wide">
      {can("requests.handle") && (
        <Card title={`Client requests (${open.length} open)`} actions={<Link className="btn btn-small" to="/incoming">Open all</Link>}>
          <ErrorNotice error={queue.error} />
          {queue.loading && !queue.data ? <Loading /> : recent.length === 0 ? <Empty icon="message">No open client requests.</Empty> : (
            <ul className="list" aria-label="Open client requests">
              {recent.slice(0, 8).map((r) => (
                <li key={r.id} className="row-between">
                  <span>
                    <Link to={`/incoming/${r.id}`}><strong>{r.intake_number || r.reference}</strong></Link>{" "}
                    <KindBadge kind={r.kind} /> <StatusBadge status={r.status} />
                    {r.awaiting_reply && r.status !== "submitted" && <> <Badge tone="warning">New client message</Badge></>}
                    <br /><span className="muted small">{r.client_name} · {r.part_number ? `${r.part_number} · ` : ""}{r.part_name} · {formatDate(r.submitted_at)}</span>
                  </span>
                  <Link className="btn btn-small btn-primary" to={`/incoming/${r.id}`}>{r.status === "submitted" ? "Acknowledge" : "Open"}</Link>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}
      </div>
      <div className="dash-col">
      {messages.length > 0 && (
        <Card title="Client messages awaiting your reply">
          <ul className="list" aria-label="Client messages awaiting reply">
            {messages.slice(0, 6).map((r) => (
              <li key={r.id} className="row-between">
                <span><Link to={`/incoming/${r.id}`}><strong>{r.intake_number || r.reference}</strong></Link>{" "}
                  <span className="muted small">{r.client_name} · {r.last_client_activity === "information_provided" ? "sent the requested information" : "sent a message"} · {formatDate(r.last_client_activity_at)}</span></span>
                <Link className="btn btn-small btn-primary" to={`/incoming/${r.id}`}>Reply</Link>
              </li>
            ))}
          </ul>
        </Card>
      )}
      {queue.data && open.length > 0 && (
        <div className="dash-charts">
          <Card title="Requests by status"><RequestsByStatus counts={countBy(open)} /></Card>
        </div>
      )}
      </div>
      </div>
      {(approvals.data?.length ?? 0) > 0 && (
        <Card title="Client submissions awaiting approval">
          <ul className="list" aria-label="Client submissions awaiting approval">
            {approvals.data!.slice(0, 6).map((r) => (
              <li key={r.part_id} className="row-between">
                <span><strong>{r.part_number || "No part number yet"}</strong> · {r.name} <Badge tone="info">rev {r.revision}</Badge>
                  {r.aries_completion_requested && <> <Badge tone="warning">Aries to complete</Badge></>}{" "}
                  <span className="muted small">{r.client_name} · {r.kind_label} · {r.submitted_by_email} · {formatDate(r.submitted_at)}</span></span>
                <Link className="btn btn-small btn-primary" to="/approvals">Review</Link>
              </li>
            ))}
          </ul>
        </Card>
      )}
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

interface Analytics {
  scope: "all" | "assigned";
  client_assets: { id: string; name: string; counts: { parts: number; passports: number; open_requests: number } }[];
  months: string[];
  series: Record<"passports" | "parts" | "approvals" | "registrations" | "requests", number[]>;
  activity: { start: string; weeks: number; days: number[][] };
  by_status: Record<string, number>;
  clients: Record<string, number[]>;
}

/** Aries Admin / Manager: platform analytics. Counts and charts only; each chart links to the list behind it. */
function AnalyticsDashboard({ title, admin, rows: overviewRows, overview: adminOverview, analytics, queue, open, waiting, messages, pendingRegs }: {
  title: string; admin: boolean; rows: OverviewRow[]; overview: { data: OverviewRow[] | null; error: unknown; loading: boolean };
  analytics: { data: Analytics | null; error: unknown; loading: boolean }; queue: { data: IntakeEnvelope[] | null; error: unknown };
  open: IntakeEnvelope[]; waiting: number; messages: number; pendingRegs: number | null | undefined;
}) {
  const [range, setRange] = useState(6);
  const [monthlyRange, setMonthlyRange] = useState(6);
  const a = analytics.data;
  // Aries Admin: every client organisation (overview); Engineers, QA and support: only their assigned clients and projects
  const rows: OverviewRow[] = admin ? overviewRows : (a?.client_assets ?? []).map((r) => ({ ...r, slug: "", status: "active", hosting_model: "",
    counts: { ...r.counts, awaiting_acknowledgement: 0, client_users: 0, assigned_staff: 0 } }));
  const overview = admin ? adminOverview : { data: a ? rows : null, error: null, loading: analytics.loading };
  const clientLink = (id: string) => (admin ? `/clients/${id}` : undefined);
  const sum = (k: keyof OverviewRow["counts"]) => rows.reduce((n, r) => n + r.counts[k], 0);
  const last = <T,>(xs: T[], n: number) => xs.slice(-n);
  const activity = (r: OverviewRow) => r.counts.parts + r.counts.passports + r.counts.open_requests * 5;
  // busiest clients by name, the rest as "Others" (counts only)
  const ranked = [...rows].filter((r) => r.counts.parts + r.counts.passports > 0)
    .sort((x, y) => y.counts.parts + y.counts.passports - (x.counts.parts + x.counts.passports) || x.name.localeCompare(y.name));
  const topAssets = ranked.slice(0, ranked.length > 4 ? 3 : 4);
  const restAssets = ranked.slice(topAssets.length);
  const assetGroups = [
    ...topAssets.map((r) => ({ key: r.id, label: r.name, values: [r.counts.parts, r.counts.passports], to: clientLink(r.id) })),
    ...(restAssets.length ? [{ key: "others", label: `Others (${restAssets.length})`, to: admin ? "/clients" : undefined,
      values: [restAssets.reduce((n, r) => n + r.counts.parts, 0), restAssets.reduce((n, r) => n + r.counts.passports, 0)] }] : []),
  ];
  const summary = [...rows].sort((x, y) => activity(y) - activity(x) || x.name.localeCompare(y.name)).slice(0, 5);
  const ic = (name: IconName) => <Icon name={name} size="sm" />;
  const rangeOpts: [number, string][] = [[6, "Last 6 months"], [12, "Last 12 months"]];
  return (
    <div className="analytics">
      <MarineBanner slim>
        <PageHeader title={title} subtitle={admin ? "Platform analytics for digital passports and marine spare parts."
          : "Analytics for the client organisations and projects you are assigned to."} />
      </MarineBanner>
      <div className="stats stats-6">
        {admin && pendingRegs !== undefined && <Stat label="Registrations pending approval" value={pendingRegs ?? "…"} to="/registrations" icon="inbox" />}
        <Stat label={admin ? "Client organisations" : "Assigned client organisations"} value={overview.data ? rows.length : "…"}
          to={admin ? "/clients" : undefined} icon="building" />
        <Stat label="Spare parts across clients" value={overview.data ? sum("parts") : "…"} icon="boxes" />
        <Stat label="Digital passports across clients" value={overview.data ? sum("passports") : "…"} icon="passport" />
        <Stat label="Open requests" value={queue.data ? open.length : "…"} to="/incoming" icon="message"
          hint={messages ? `${messages} client message${messages === 1 ? "" : "s"} awaiting reply` : undefined} />
        <Stat label="Awaiting acknowledgement" value={queue.data ? waiting : "…"} to="/incoming?status=submitted" icon="clock" />
        {!admin && <Stat label="Client messages awaiting reply" value={queue.data ? messages : "…"} to="/incoming?awaiting=true" icon="message" />}
      </div>
      <ErrorNotice error={analytics.error ?? overview.error ?? queue.error} />
      <div className="chart-grid">
        <ChartCard title="Digital passport trend" icon={ic("chart")}
          action={<RangeSelect label="Trend period" value={range} onChange={setRange} options={rangeOpts} />}>
          {a ? <TrendChart months={last(a.months, range)} series={[
            { label: "Digital passports (created)", values: last(a.series.passports, range), series: 1 },
            { label: "Spare parts (added)", values: last(a.series.parts, range), series: 3 }]} />
            : analytics.loading ? <Loading /> : null}
        </ChartCard>
        <ChartCard title="Client organisations by digital assets" icon={ic("layers")}
          action={admin ? <Link className="btn btn-small" to="/clients">Clients</Link> : undefined}>
          {!overview.data ? <Loading /> : assetGroups.length ? (
            <BarChart groups={assetGroups} series={[{ label: "Spare parts", series: 3 }, { label: "Digital passports", series: 1 }]} />
          ) : <p className="muted small chart-empty">No spare parts or passports yet.</p>}
        </ChartCard>
        <ChartCard title="Request status distribution" icon={ic("gauge")} action={<Link className="btn btn-small" to="/incoming">Open all</Link>}>
          {queue.data ? <RequestsByStatus counts={countBy(open)} /> : <Loading />}
        </ChartCard>
        <ChartCard title="Monthly approvals & requests" icon={ic("calendar")}
          action={<RangeSelect label="Monthly period" value={monthlyRange} onChange={setMonthlyRange} options={rangeOpts} />}>
          {a ? <BarChart stacked series={admin ? [{ label: "Approvals", series: 7 }, { label: "Registrations", series: 4 }, { label: "Client requests", series: 2 }]
            : [{ label: "Approvals", series: 7 }, { label: "Client requests", series: 2 }]}
            groups={last(a.months, monthlyRange).map((m, i) => {
              const at = a.months.length - monthlyRange + i;
              return { key: m, label: monthLabel(m), values: admin ? [a.series.approvals[at], a.series.registrations[at], a.series.requests[at]]
                : [a.series.approvals[at], a.series.requests[at]] };
            })} /> : analytics.loading ? <Loading /> : null}
        </ChartCard>
        <ChartCard title="Client request workflow" icon={ic("route")}>
          {a ? <RequestWorkflow byStatus={a.by_status} icon={(n) => <Icon name={n as IconName} />} /> : analytics.loading ? <Loading /> : null}
        </ChartCard>
        <ChartCard title="Platform activity (requests)" icon={ic("history")}>
          {a ? <ActivityHeatmap start={a.activity.start} days={a.activity.days} /> : analytics.loading ? <Loading /> : null}
          {a && <p className="muted small chart-note">Client requests submitted per day, last {a.activity.weeks} weeks.</p>}
        </ChartCard>
      </div>
      <div className="chart-grid chart-grid-foot">
        <ChartCard title="Client summary" icon={ic("users")} className="chart-wide"
          action={admin ? <Link className="btn btn-small" to="/clients">All clients ({rows.length})</Link> : undefined}>
          {!overview.data ? <Loading /> : summary.length ? (
            <div className="table-scroll">
              <table className="table summary-table" aria-label="Client summary">
                <thead><tr><th>Client organisation</th><th className="num">Spare parts</th><th className="num">Digital passports</th>
                  <th className="num">Open requests</th><th>Passport coverage</th><th>Activity (8 weeks)</th></tr></thead>
                <tbody>
                  {summary.map((r) => {
                    const cover = r.counts.parts ? Math.round((Math.min(r.counts.passports, r.counts.parts) / r.counts.parts) * 100) : null;
                    return (
                      <tr key={r.id}>
                        <td>{admin ? <Link to={`/clients/${r.id}`}><strong>{r.name}</strong></Link> : <strong>{r.name}</strong>}</td>
                        <td className="num">{r.counts.parts}</td>
                        <td className="num">{r.counts.passports}</td>
                        <td className="num">{r.counts.open_requests ? <Link to={`/incoming?client=${r.id}`}>{r.counts.open_requests}</Link> : 0}</td>
                        <td>{cover === null ? <span className="muted small">No parts</span> : (
                          <span className="coverage" title={`${r.counts.passports} passports for ${r.counts.parts} spare parts`}>
                            <span>{cover}%</span><span className="coverage-track"><span style={{ width: `${cover}%` }} /></span></span>)}</td>
                        <td>{a ? <Sparkline values={a.clients[r.id] ?? Array(8).fill(0)} label={`${r.name} activity`} /> : null}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : <Empty>No client organisations yet.</Empty>}
        </ChartCard>
        <ChartCard title="Platform at a glance" icon={ic("gauge")}>
          {a ? (
            <div className="glance">
              <Growth values={a.series.passports} n={6} label="Digital passports created (vs. previous 6 months)" />
              <Growth values={a.series.parts} n={6} label="Spare parts added (vs. previous 6 months)" />
            </div>
          ) : analytics.loading ? <Loading /> : null}
        </ChartCard>
      </div>
    </div>
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
