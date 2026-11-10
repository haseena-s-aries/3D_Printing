/**
 * "Needs attention": the work waiting for the signed-in user, by role, from endpoints that role can already read (so
 * company, project and role scope come from the server):
 * - Aries Engineer: recommendations to review, client submissions to review, edit requests to decide, incoming requests
 *   to acknowledge (assigned clients only), results ready to approve or share with the client.
 * - Aries Admin: registrations to approve, requests awaiting acknowledgement, client companies with parts but no Aries staff.
 * - Client: newly shared assessment results, requests waiting for your information, submissions with corrections requested.
 * `compact` (dashboards) shows the counts; the full view (/attention) lists the items themselves.
 */
import type { EditRequest, IntakeEnvelope, Paginated, Part, ServiceRequestRow } from "@passport/api-types";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { Icon, type IconName } from "./icons";
import { Card, Empty, formatDate } from "./ui";

type Item = { key: string; count: number | null; label: string; hint: string; to: string; icon: IconName; tone?: "warning" | "info";
  rows?: { id: string; to: string; title: ReactNode; meta: ReactNode }[] };
type QRow = { id: string; part_number: string; name: string; review_state: { code: string; label: string };
  recommendation: { version: number; created_at: string } | null };
type DRow = { id: string; part_number: string; name: string; state: { code: string; label: string } };
type ClientRow = { id: string; part_number: string; name: string; status: { code: string; label: string; shared_at: string | null } };
type OverviewRow = { id: string; name: string; counts: { parts: number; assigned_staff: number } };

const MAX_ROWS = 6;

function useItems(): { items: Item[]; loading: boolean } {
  const { session, can } = useAuth();
  const operatorTenant = session?.tenant.kind === "operator";
  const operatorStaff = !!session?.membership.role.startsWith("operator_");
  const engineerHere = operatorStaff && !operatorTenant;
  // --- Aries Engineer (working inside a client company)
  const queue = useApi<{ parts: QRow[] }>(engineerHere && can("intelligence.view") ? "/intelligence/recommendations/" : null);
  const subs = useApi<Paginated<Part>>(engineerHere && can("parts.review") ? "/parts/" : null, { query: { catalog: "review", page_size: MAX_ROWS } });
  const edits = useApi<Paginated<EditRequest>>(can("edits.review") ? "/edit-requests/" : null, { query: { queue: "review", page_size: MAX_ROWS } });
  const disc = useApi<{ parts: DRow[] }>(engineerHere && can("ai.share") ? "/intelligence/disclosures/" : null);
  // --- Aries staff (any organisation): incoming client requests
  const incoming = useApi<IntakeEnvelope[]>(can("requests.handle") ? "/operator/requests/" : null, { query: { open: "true" } });
  // --- Aries Admin (operator organisation)
  const regs = useApi<Paginated<{ id: string; company_name: string; created_at: string }>>(operatorTenant && can("registrations.review") ? "/registrations/" : null,
    { query: { status: "pending", page_size: 5 } });  // same request as the Admin dashboard's registrations card (shared)
  const overview = useApi<OverviewRow[]>(operatorTenant && can("clients.view") ? "/operator/overview/" : null);
  // --- Client
  const shared = useApi<{ access: { enabled: boolean; allowed: boolean }; parts: ClientRow[] }>(!operatorStaff && can("ai.workspace") ? "/client-intelligence/" : null);
  const infoReq = useApi<Paginated<ServiceRequestRow>>(!operatorStaff && can("requests.view") ? "/requests/" : null,
    { query: { status: "information_requested", page_size: MAX_ROWS } });
  const corrections = useApi<Paginated<Part>>(!operatorStaff && can("parts.submit") ? "/parts/" : null,
    { query: { review_state: "info_requested", page_size: MAX_ROWS } });

  const items: Item[] = [];
  if (engineerHere && can("intelligence.view")) {
    const open = (queue.data?.parts ?? []).filter((p) => p.recommendation && ["preliminary", "information_requested"].includes(p.review_state.code));
    items.push({ key: "reviews", count: queue.data ? open.length : null, label: "Recommendations awaiting engineering review",
      hint: "Preliminary or information requested", to: "/inventory-import?tab=intelligence&view=review", icon: "review", tone: "warning",
      rows: open.slice(0, MAX_ROWS).map((p) => ({ id: p.id, to: `/parts/${p.id}?tab=ai&step=recommendation`, title: <><strong>{p.part_number}</strong> {p.name}</>,
        meta: <>v{p.recommendation!.version} · {p.review_state.code === "preliminary" ? "not reviewed" : "information requested"}</> })) });
  }
  if (engineerHere && can("parts.review")) {
    items.push({ key: "submissions", count: subs.data ? subs.data.count : null, label: "Client part submissions to review",
      hint: "Pending Aries review or corrections returned", to: "/parts?catalog=review", icon: "inbox",
      rows: (subs.data?.results ?? []).map((p) => ({ id: p.id, to: `/parts/${p.id}`, title: <><strong>{p.part_number}</strong> {p.name}</>,
        meta: <>{p.submitted_by_name || "Client"} · {formatDate(p.submitted_at ?? null)}</> })) });
  }
  if (can("edits.review")) {
    items.push({ key: "edits", count: edits.data ? edits.data.count : null, label: "Edit requests to decide", hint: "Submitted by others in your scope",
      to: "/edit-requests", icon: "edit",
      rows: (edits.data?.results ?? []).map((e) => ({ id: e.id, to: `/edit-requests/${e.id}`, title: <><strong>{e.reference}</strong> {e.part_number}</>,
        meta: <>{e.status_label} · {e.requester}</> })) });
  }
  if (can("requests.handle")) {
    const waiting = (incoming.data ?? []).filter((r) => r.status === "submitted" && (operatorTenant || r.assigned));
    items.push({ key: "incoming", count: incoming.data ? waiting.length : null, label: "Client requests awaiting acknowledgement",
      // the intake summaries are filtered by client assignment; a request of a project you are not assigned to is listed but
      // opens only for staff of that project (the server checks it when the request is opened)
      hint: operatorTenant ? "All client organisations" : "Client organisations you are assigned to · requests of other projects open only for their project staff",
      to: "/incoming", icon: "incoming", tone: "warning",
      rows: waiting.slice(0, MAX_ROWS).map((r) => ({ id: r.id, to: r.assigned ? `/incoming/${r.id}` : "/incoming",
        title: <><strong>{r.reference}</strong> {r.part_number || r.part_name}</>, meta: <>{r.client_name} · {formatDate(r.submitted_at)}</> })) });
  }
  if (engineerHere && can("ai.share")) {
    const ready = (disc.data?.parts ?? []).filter((p) => p.state.code === "engineering_reviewed" || p.state.code === "approved");
    items.push({ key: "sharing", count: disc.data ? ready.length : null, label: "Results to approve or share with the client",
      hint: "Reviewed results not yet shared; approval by an engineer who did not generate them", to: "/ai/sharing", icon: "eye", tone: "info",
      rows: ready.slice(0, MAX_ROWS).map((p) => ({ id: p.id, to: `/parts/${p.id}?tab=ai&step=sharing`, title: <><strong>{p.part_number}</strong> {p.name}</>,
        meta: <>{p.state.code === "approved" ? "Approved, not yet shared" : "Reviewed, ready to approve"}</> })) });
  }
  if (operatorTenant && can("registrations.review")) {
    items.push({ key: "registrations", count: regs.data ? regs.data.count : null, label: "Company registrations to approve", hint: "Self-registered companies",
      to: "/registrations", icon: "building", tone: "warning",
      rows: (regs.data?.results ?? []).map((r) => ({ id: r.id, to: `/registrations/${r.id}`, title: <strong>{r.company_name}</strong>, meta: formatDate(r.created_at) })) });
  }
  if (operatorTenant && can("clients.view")) {
    const unstaffed = (overview.data ?? []).filter((r) => r.counts.parts > 0 && r.counts.assigned_staff === 0);
    items.push({ key: "unstaffed", count: overview.data ? unstaffed.length : null, label: "Client companies with parts but no Aries staff",
      hint: "Assign engineers under Clients › Engineers & Access", to: "/clients", icon: "users",
      rows: unstaffed.slice(0, MAX_ROWS).map((r) => ({ id: r.id, to: `/clients/${r.id}?tab=engineers`, title: <strong>{r.name}</strong>, meta: <>{r.counts.parts} parts</> })) });
  }
  if (!operatorStaff && can("ai.workspace") && shared.data?.access.enabled && shared.data.access.allowed) {
    const available = shared.data.parts.filter((p) => p.status.code === "available");
    items.push({ key: "results", count: available.length, label: "Assessment results shared with you", hint: "Spare Parts Intelligence",
      to: "/ai/my-parts", icon: "spark", tone: "info",
      rows: available.slice(0, MAX_ROWS).map((p) => ({ id: p.id, to: `/ai/my-parts/${p.id}`, title: <><strong>{p.part_number}</strong> {p.name}</>,
        meta: <>Shared {formatDate(p.status.shared_at)}</> })) });
  }
  if (!operatorStaff && can("requests.view")) {
    items.push({ key: "info", count: infoReq.data ? infoReq.data.count : null, label: "Requests waiting for your information", hint: "Aries asked a question",
      to: "/requests?status=information_requested", icon: "message", tone: "warning",
      rows: (infoReq.data?.results ?? []).map((r) => ({ id: r.id, to: `/requests/${r.id}`, title: <><strong>{r.reference}</strong> {r.part_number || r.part_description?.split("\n")[0]}</>,
        meta: r.kind_label })) });
  }
  if (!operatorStaff && can("parts.submit")) {
    items.push({ key: "corrections", count: corrections.data ? corrections.data.count : null, label: "Submissions returned for corrections",
      hint: "Aries requested details", to: "/parts?catalog=review", icon: "edit", tone: "warning",
      rows: (corrections.data?.results ?? []).map((p) => ({ id: p.id, to: `/parts/${p.id}`, title: <><strong>{p.part_number}</strong> {p.name}</>,
        meta: p.review_note ? p.review_note.slice(0, 80) : "Corrections requested" })) });
  }
  const loading = items.some((i) => i.count === null);
  return { items, loading };
}

export function NeedsAttention({ compact = false }: { compact?: boolean }) {
  const { items, loading } = useItems();
  if (!items.length) return null;
  const open = items.filter((i) => (i.count ?? 0) > 0);
  const total = open.reduce((n, i) => n + (i.count ?? 0), 0);
  if (compact) {
    return (
      <section className="card attention" aria-label="Needs your attention">
        <div className="card-head">
          <h2><Icon name="bell" size="sm" />Needs your attention</h2>
          <Link className="btn btn-small" to="/attention">Open all{total ? ` (${total})` : ""}</Link>
        </div>
        {loading && !open.length ? <p className="muted small">Checking…</p> : !open.length ? (
          <p className="attention-clear"><Icon name="check" size="sm" />Nothing waiting for you right now.</p>
        ) : (
          <ul className="attention-list">
            {open.map((i) => (
              <li key={i.key}>
                <Link to={i.to} className={`attention-item ${i.tone ? `is-${i.tone}` : ""}`}>
                  <span className="attention-count">{i.count}</span>
                  <span className="attention-text"><span className="attention-label">{i.label}</span><span className="muted small">{i.hint}</span></span>
                  <Icon name="chevron" size="sm" />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    );
  }
  // items with work first; the empty ones are gathered in one "nothing waiting" card
  const withWork = items.filter((i) => i.count === null || i.count > 0);
  const clear = items.filter((i) => i.count === 0);
  return (
    <div className="attention-page">
      {withWork.map((i) => (
        <Card key={i.key} title={`${i.label}${i.count !== null ? ` (${i.count})` : ""}`} actions={<Link className="btn btn-small" to={i.to}>Open</Link>}>
          <p className="muted small">{i.hint}</p>
          {i.count === null ? <p className="muted small">Loading…</p> : !i.count ? <p className="attention-clear"><Icon name="check" size="sm" />Nothing waiting.</p> : (
            <ul className="attention-rows">
              {(i.rows ?? []).map((r) => (
                <li key={r.id}><Link to={r.to}><span className="attention-row-title">{r.title}</span><span className="muted small">{r.meta}</span></Link></li>
              ))}
              {i.count > (i.rows?.length ?? 0) && <li className="muted small"><Link to={i.to}>and {i.count - (i.rows?.length ?? 0)} more…</Link></li>}
            </ul>
          )}
        </Card>
      ))}
      {clear.length > 0 && (
        <Card title="Nothing waiting">
          <ul className="attention-rows">
            {clear.map((i) => <li key={i.key}><Link to={i.to}><span className="attention-row-title"><Icon name="check" size="sm" /> {i.label}</span>
              <span className="muted small">{i.hint}</span></Link></li>)}
          </ul>
        </Card>
      )}
      {!loading && items.every((i) => !i.count) && <Empty icon="check">Nothing needs your attention right now.</Empty>}
    </div>
  );
}
