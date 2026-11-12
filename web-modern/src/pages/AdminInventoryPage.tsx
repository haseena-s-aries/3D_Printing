/**
 * Aries Admin: digital inventory across client companies. Administrative summaries only, from an audited read model
 * (GET /admin/inventory/). No engineering edits, engineering notes, document access, CAD originals, approvals or
 * manufacturing actions. Opening a full client record stays disabled until the support-access consent decision (OQ-37).
 */
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";

import { fetchObjectUrl } from "../api/client";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { AdminIntelligenceUsage } from "../components/PartIntelligence";
import { AdminAssessmentSummary } from "../components/QuarterlyAssessment";
import { STAGE_TEXT, STAGES, stageFrom } from "../components/inventoryStages";
import { REVIEW_LABEL } from "../components/PartSubmission";
import { useEnterContext } from "../components/AdminNav";
import { Icon } from "../components/icons";
import { ListPager, ListToolbar, useListControls } from "../components/ListControls";
import { Badge, Card, Empty, ErrorNotice, Loading, Notice, PageHeader, Pager, formatDate, label } from "../components/ui";

type Row = {
  id: string; client_id: string; client_name: string; client_slug?: string; part_number: string; name: string; project: string; project_name: string;
  origin: string; review_state: string; submission_kind: string; stage: string; digitisation: string; passport_number: string;
  revision: number | null; revision_status: string; publication_state: string; manufacturing_eligibility: string;
  completeness: Record<string, { done: number; total: number }> | null; completeness_pct: number; documents: number;
  assigned_engineers: string[]; updated_at: string;
  /** only for companies whose Client Administrator allowed Aries Admin thumbnails: an opaque token for one sanitized photo thumbnail */
  preview?: { token: string; route?: "consent" | "contract" } | null;
};
type ClientSummary = { id: string; name: string; counts: Record<string, number>; engineers: string[]; unassigned_review: number; thumbnails_allowed?: boolean;
  thumbnail_route?: "consent" | "contract" | null };
type Overview = {
  count: number; results: Row[]; totals: Record<string, number>; clients: ClientSummary[]; all_clients: { id: string; name: string }[];
  projects: { id: string; code: string; name: string; client: string }[]; detail_access: { enabled: boolean; decision: string; reason: string };
};

const PAGE_SIZE = 25;
// Separate views instead of stacked sections (the backlog list alone covers 70+ companies)
const VIEWS = [["backlog", "Backlog by company"], ["parts", "All parts"], ["usage", "AI usage"], ["assessments", "Assessments"]] as const;
type View = (typeof VIEWS)[number][0];
const KEYS = ["client", "project", "review_state", "publication", "stage", "search"] as const;
const STAGE_BADGE: Record<string, "warning" | "info" | "success" | "danger"> = { review: "warning", in_digitisation: "info", published: "success", declined: "danger" };

/** `clientId` embeds the same administrative summary for one client company (Client Management → Digital Inventory). */
export default function AdminInventoryPage({ clientId }: { clientId?: string } = {}) {
  const [params, setParams] = useSearchParams();
  const { can } = useAuth();
  const f = Object.fromEntries(KEYS.map((k) => [k, params.get(k) ?? ""])) as Record<(typeof KEYS)[number], string>;
  if (clientId) f.client = clientId;
  const page = Number(params.get("page") ?? "1") || 1;
  const stage = stageFrom(f.stage) || "all";
  const data = useApi<Overview>("/admin/inventory/", { query: { ...f, stage: stage === "all" ? "" : stage, page, page_size: PAGE_SIZE } });
  const [search, setSearch] = useState(f.search);
  const set = (changes: Partial<Record<string, string>>, keepPage = false) => setParams((prev) => {
    const next = new URLSearchParams(prev);
    for (const [k, v] of Object.entries(changes)) (v ? next.set(k, v) : next.delete(k));
    if (!keepPage) next.delete("page");
    return next;
  });
  const o = data.data;
  const projects = (o?.projects ?? []).filter((p) => !f.client || p.client === f.client);

  const keep = (next: Record<string, string>) => (clientId && params.get("tab") ? { ...next, tab: params.get("tab") as string } : next);
  const views = VIEWS.filter(([v]) => (v !== "usage" && v !== "assessments") || can("intelligence.usage_admin"));
  const view: View = clientId ? "parts" : views.some(([v]) => v === params.get("view")) ? (params.get("view") as View) : "backlog";
  const backlog = useListControls(o?.clients ?? [], {
    text: (c) => `${c.name} ${c.engineers.join(" ")}`,
    filters: [["with_parts", "With parts", (c) => c.counts.all > 0], ["backlog", "Review backlog", (c) => c.counts.review > 0],
      ["unassigned", "Unassigned review", (c) => c.unassigned_review > 0], ["no_engineer", "No engineer", (c) => c.engineers.length === 0], ["all", "All", () => true]],
    sorts: [["backlog", "Review backlog", (a, b) => b.counts.review - a.counts.review || b.counts.all - a.counts.all || a.name.localeCompare(b.name)],
      ["parts", "All parts", (a, b) => b.counts.all - a.counts.all || a.name.localeCompare(b.name)], ["name", "Name A–Z", (a, b) => a.name.localeCompare(b.name)]],
    pageSize: 10,
  });
  const showView = (v: View) => setParams(v === "backlog" ? {} : { view: v });
  const layout = params.get("layout") === "grid" ? "grid" : "list";
  const [expanded, setExpanded] = useState("");
  return (
    <>
      {!clientId && <PageHeader marine title="Digital inventory · all client companies"
        subtitle="Administrative summaries across client companies, to follow review backlogs and digitisation progress." />}
      <Notice>
        {o?.detail_access.enabled
          ? <>Cross-company summary. Every view is recorded in the Aries audit trail and in each company's own audit trail. Use
            Open record to work on a part inside its company's own workspace.</>
          : <>Read-only administrative view. Every view is recorded in the Aries audit trail and in each company's own audit trail.
            Engineering edits, engineering notes, documents, CAD originals and approvals are not available here.</>}
      </Notice>
      {!clientId && (
        <div className="tabs" role="tablist" aria-label="Administrative inventory views">
          {views.map(([v, name]) => (
            <button key={v} type="button" role="tab" aria-selected={view === v} className={`tab ${view === v ? "is-active" : ""}`} onClick={() => showView(v)}>{name}</button>
          ))}
        </div>
      )}
      {view === "parts" && <>
      <div className="catalog-bar">
        <div className="segmented" role="group" aria-label="Inventory stage">
          {STAGES.map((st) => (
            <button key={st} type="button" aria-pressed={stage === st} title={STAGE_TEXT.admin[st][1]} onClick={() => set({ stage: st === "all" ? "" : st })}>
              {STAGE_TEXT.admin[st][0]} <span className="count">{o?.totals[st] ?? "…"}</span>
            </button>
          ))}
        </div>
        <div className="segmented" role="group" aria-label="Layout">
          <button type="button" aria-pressed={layout === "grid"} onClick={() => set({ layout: "grid" }, true)}><Icon name="grid" size="sm" />Grid</button>
          <button type="button" aria-pressed={layout === "list"} onClick={() => set({ layout: "" }, true)}><Icon name="list" size="sm" />List</button>
        </div>
      </div>
      <p className="muted small section-note" data-testid="stage-description">
        {STAGE_TEXT.admin[stage][1]}
        {stage === "all" && (o?.totals.declined ?? 0) > 0 && ` Includes ${o?.totals.declined} rejected submission${o?.totals.declined === 1 ? "" : "s"}.`}
      </p>
      </>}
      <ErrorNotice error={data.error} />
      {view === "backlog" && !o && data.loading && <Loading variant="cards" />}
      {view === "backlog" && o && !clientId && (
        <Card title="Backlog by client company">
          <p className="list-summary">{o.clients.length} client companies · {o.clients.filter((c) => c.counts.all > 0).length} with parts ·{" "}
            {o.totals.review ?? 0} parts awaiting review · {o.clients.reduce((n, c) => n + c.unassigned_review, 0)} review items without an engineer</p>
          <ListToolbar c={backlog} searchLabel="Search client companies" placeholder="Search by company or engineer" />
          <div className="table-scroll">
            <table className="table backlog-table table-stack" aria-label="Backlog by client company">
              <thead><tr><th>Client company</th><th>{STAGE_TEXT.admin.review[0]}</th><th title="Review items without an assigned engineer">Unassigned review</th>
                <th>{STAGE_TEXT.admin.in_digitisation[0]}</th><th>Published</th><th>All parts</th><th>Aries Engineers</th></tr></thead>
              <tbody>
                {backlog.visible.map((c) => (
                  <tr key={c.id}>
                    <td><button type="button" className="link-btn" onClick={() => setParams({ view: "parts", client: c.id })}>{c.name}</button></td>
                    <td>{c.counts.review ? <Badge tone="warning">{c.counts.review}</Badge> : 0}</td>
                    <td>{c.unassigned_review ? <Badge tone="danger">{c.unassigned_review}</Badge> : 0}</td>
                    <td>{c.counts.in_digitisation}</td><td>{c.counts.published}</td><td>{c.counts.all}</td>
                    <td className="small">{c.engineers.join(", ") || <span className="muted">None assigned</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <ListPager c={backlog} noun="client companies" />
        </Card>
      )}
      {view === "usage" && <AdminIntelligenceUsage />}
      {view === "assessments" && <AdminAssessmentSummary />}
      {view === "parts" && <Card>
        <form className="toolbar wrap admin-filters" role="search" aria-label="Inventory filters" onSubmit={(e: FormEvent) => { e.preventDefault(); set({ search: search.trim() }); }}>
          <input type="search" aria-label="Search part number or name" placeholder="Part number or name" value={search} onChange={(e) => setSearch(e.target.value)} />
          <button className="btn">Search</button>
          {!clientId && (
            <select aria-label="Client company" value={f.client} onChange={(e) => set({ client: e.target.value, project: "" })}>
              <option value="">All client companies</option>
              {(o?.all_clients ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          )}
          <select aria-label="Project" value={f.project} onChange={(e) => set({ project: e.target.value })}>
            <option value="">All projects</option>
            {projects.map((p) => <option key={p.id} value={p.id}>{p.code} · {p.name}</option>)}
          </select>
          <select aria-label="Review status" value={f.review_state} onChange={(e) => set({ review_state: e.target.value })}>
            <option value="">Any review status</option>
            <option value="open">Awaiting Aries review (pending or corrections)</option>
            <option value="accepted">Accepted by Aries</option>
            <option value="declined">Rejected</option>
            <option value="not_required">Aries-maintained (no review)</option>
          </select>
          <select aria-label="Publication state" value={f.publication} onChange={(e) => set({ publication: e.target.value })}>
            <option value="">Any publication state</option>
            <option value="published">Published</option>
            <option value="not_published">Not published</option>
          </select>
          {KEYS.some((k) => k !== "stage" && (k !== "client" || !clientId) && f[k]) && <button type="button" className="btn btn-ghost" onClick={() => { setSearch(""); setParams(keep({ ...(stage === "all" ? {} : { stage }), ...(clientId ? {} : { view: "parts" }), ...(layout === "grid" ? { layout } : {}) })); }}>Clear filters</button>}
        </form>
        {o && <p className="muted small" id="admin-detail-access" data-testid="detail-access">
          {o.detail_access.enabled ? <>"Open record" opens the part in its company's own workspace. {o.detail_access.reason}</>
            : <>"Open record" is disabled: {o.detail_access.reason}</>}</p>}
        {o && layout === "grid" && (
          <p className="muted small admin-thumb-note" data-testid="thumbnail-access">
            Photo thumbnails appear only where the company's Client Administrator has allowed them, or for QA-confirmed Aries
            scanning photos under a verified contract authorization
            ({o.clients.filter((c) => c.thumbnails_allowed).length} of {o.clients.length} {o.clients.length === 1 ? "company" : "companies"} in this view).
            Originals, CAD and documents are never shown.
          </p>
        )}
        {data.loading && !o ? <Loading /> : o && o.results.length ? (
          <>
            {layout === "grid" ? (
              <ul className="part-grid admin-grid" aria-label="Administrative inventory" aria-busy={data.loading}>
                {o.results.map((r) => <li key={r.id}><AdminPartCard r={r} showClient={!clientId} canOpen={o.detail_access.enabled} /></li>)}
              </ul>
            ) : (
              <div className="table-scroll">
                <table className="table admin-list table-stack" aria-label="Administrative inventory" aria-busy={data.loading}>
                  <thead><tr><th>Part</th>{!clientId && <th>Client</th>}<th>Review · digitisation</th><th>Engineering completeness</th><th>Assigned engineer</th>
                    <th><span className="sr-only">Details and actions</span></th></tr></thead>
                  {o.results.map((r) => <AdminPartRows key={r.id} r={r} showClient={!clientId} reason={o.detail_access.reason} canOpen={o.detail_access.enabled}
                    open={expanded === r.id} onToggle={() => setExpanded((x) => (x === r.id ? "" : r.id))} />)}
                </table>
              </div>
            )}
            <Pager page={page} count={o.count} pageSize={PAGE_SIZE} onPage={(n) => set({ page: String(n) }, true)} />
          </>
        ) : o ? <Empty>No parts match these filters.</Empty> : null}
      </Card>}
    </>
  );
}

const levelName = (k: string) => k.toUpperCase().replace("RL", "R-L");
const reviewText = (r: Row) => (r.origin === "client" ? (REVIEW_LABEL[r.review_state] ?? label(r.review_state)) : "Aries-maintained");

/** Completeness of the passport data (summary only): a meter, the percentage and the per-level counts. */
function Completeness({ r }: { r: Row }) {
  if (!r.completeness) return <span className="muted small">No passport data</span>;
  return (
    <div className="admin-completeness">
      <span className="meter-bar" role="img" aria-label={`Engineering completeness ${r.completeness_pct}%`}><span style={{ width: `${r.completeness_pct}%` }} /></span>
      <strong>{r.completeness_pct}%</strong>
      <span className="muted small">{Object.entries(r.completeness).map(([k, v]) => `${levelName(k)} ${v.done}/${v.total}`).join(" · ")}</span>
    </div>
  );
}

const Engineers = ({ r }: { r: Row }) => (r.assigned_engineers.length ? <>{r.assigned_engineers.join(", ")}</> : <Badge tone="danger">Unassigned</Badge>);

/** Grid view: a read-only administrative summary card (no images, documents, notes or record access). */
/** Preview slot of a grid card. A row carries `preview` only when its company's Client Administrator has allowed Aries
 * Admin thumbnails: an opaque, short-lived token for one sanitized photo thumbnail (no file id or URL). The image is
 * fetched with the admin's own session once the card nears the viewport, shown at its own proportions, and replaced by
 * the neutral fallback when there is none or the server refuses it (for example after the company withdrew consent). */
function AdminPreview({ preview, alt }: { preview: Row["preview"]; alt: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [near, setNear] = useState(false);
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const token = preview?.token;
  useEffect(() => {
    const el = ref.current;
    if (!token || !el) return undefined;
    if (typeof IntersectionObserver === "undefined") { setNear(true); return undefined; }
    const io = new IntersectionObserver((entries) => { if (entries.some((e) => e.isIntersecting)) { setNear(true); io.disconnect(); } }, { rootMargin: "200px" });
    io.observe(el);
    return () => io.disconnect();
  }, [token]);
  useEffect(() => {
    if (!token || !near) return undefined;
    let url: string | null = null;
    let live = true;
    setFailed(false);
    fetchObjectUrl(`/admin/inventory/thumbnails/${encodeURIComponent(token)}/`)
      .then((u) => { url = u; if (live) setSrc(u); else URL.revokeObjectURL(u); })
      .catch(() => { if (live) setFailed(true); });
    return () => { live = false; if (url) URL.revokeObjectURL(url); setSrc(null); };
  }, [token, near]);
  if (!token || failed) {
    return (
      <div className="admin-preview admin-preview-empty" role="img" aria-label="No preview available">
        <Icon name="cube" size="sm" /><span>No preview available</span>
      </div>
    );
  }
  return (
    <div className="admin-preview" ref={ref}>
      {src ? <img src={src} alt={`Photo thumbnail of ${alt}`} loading="lazy" decoding="async" /> : <span className="admin-preview-loading" aria-hidden />}
      {src && preview?.route && (
        <span className="admin-preview-route">{preview.route === "contract" ? "Aries scan · contract" : "Client permission"}</span>
      )}
    </div>
  );
}

/** Open a part in its company's own workspace (Aries Admin super-administrator workspaces only). */
function OpenRecord({ r }: { r: Row }) {
  const enter = useEnterContext();
  const [busy, setBusy] = useState(false);
  return (
    <button type="button" className="btn btn-small" disabled={busy || !r.client_slug} aria-label={`Open record ${r.part_number} (${r.client_name})`}
      onClick={() => { setBusy(true); enter(r.client_slug!, `/parts/${r.id}`).finally(() => setBusy(false)); }}>Open record</button>
  );
}

function AdminPartCard({ r, showClient, canOpen }: { r: Row; showClient: boolean; canOpen?: boolean }) {
  return (
    <article className="part-card admin-card" aria-labelledby={`adm-${r.id}`}>
      <AdminPreview preview={r.preview} alt={r.part_number} />
      <div className="part-card-id">
        <span id={`adm-${r.id}`} className="part-card-number">{r.part_number}</span>
        <p className="part-card-name">{r.name}</p>
        <p className="part-card-meta">{[showClient ? r.client_name : "", r.project ? `${r.project}${r.project_name ? ` · ${r.project_name}` : ""}` : "No project"].filter(Boolean).join(" · ")}
          {r.submission_kind === "clone" && " · Clone"}</p>
      </div>
      <div className="part-card-status">
        <Badge tone={STAGE_BADGE[r.stage] ?? "neutral"}>{r.digitisation}</Badge>
      </div>
      <dl className="part-card-facts">
        <div><dt>Review</dt><dd>{reviewText(r)}</dd></div>
        <div><dt>Passport</dt><dd>{r.passport_number ? `${r.passport_number} · rev ${r.revision} (${r.revision_status})` : "No passport"}</dd></div>
        <div><dt>Publication</dt><dd>{r.publication_state ? label(r.publication_state) : "—"}</dd></div>
        <div><dt>Completeness</dt><dd><Completeness r={r} /></dd></div>
        <div><dt>Documents</dt><dd>{r.documents} on record</dd></div>
        <div><dt>Engineer</dt><dd><Engineers r={r} /></dd></div>
      </dl>
      <p className="admin-card-updated muted small">Updated {formatDate(r.updated_at)}</p>
      {canOpen && <div className="admin-card-actions"><OpenRecord r={r} /></div>}
    </article>
  );
}

/** List view: one concise row; the secondary summary opens in a details row below it (keyboard: the Details button). */
function AdminPartRows({ r, showClient, reason, open, onToggle, canOpen }: { r: Row; showClient: boolean; reason: string; open: boolean;
  onToggle: () => void; canOpen?: boolean }) {
  const id = `adm-detail-${r.id}`;
  return (
    <tbody className={open ? "is-open" : ""}>
      <tr>
        <td><strong>{r.part_number}</strong><div className="small">{r.name}</div>{r.submission_kind === "clone" && <span className="muted small">Clone</span>}</td>
        {showClient && <td className="small">{r.client_name}<div className="muted">{r.project || "No project"}</div></td>}
        <td><Badge tone={STAGE_BADGE[r.stage] ?? "neutral"}>{r.digitisation}</Badge><div className="muted small">{reviewText(r)}</div></td>
        <td><Completeness r={r} /></td>
        <td className="small"><Engineers r={r} /></td>
        <td className="admin-row-actions">
          <button type="button" className="btn btn-small btn-ghost" aria-expanded={open} aria-controls={id} onClick={onToggle}>
            <Icon name="chevron" size="sm" className="admin-chevron" />Details<span className="sr-only"> of {r.part_number}</span></button>
          {canOpen ? <OpenRecord r={r} /> : <button type="button" className="btn btn-small" disabled title={reason} aria-describedby="admin-detail-access">Open record</button>}
        </td>
      </tr>
      {open && (
        <tr id={id} className="admin-detail-row">
          <td colSpan={showClient ? 6 : 5}>
            <dl className="admin-detail">
              {!showClient && <div><dt>Project</dt><dd>{r.project ? `${r.project}${r.project_name ? ` · ${r.project_name}` : ""}` : "—"}</dd></div>}
              {showClient && r.project_name && <div><dt>Project</dt><dd>{r.project} · {r.project_name}</dd></div>}
              <div><dt>Passport</dt><dd>{r.passport_number ? `${r.passport_number} · rev ${r.revision} (${r.revision_status})` : "No passport"}</dd></div>
              <div><dt>Publication</dt><dd>{r.publication_state ? label(r.publication_state) : "No passport"}</dd></div>
              <div><dt>Documents</dt><dd>{r.documents} on record (not available in this view)</dd></div>
              <div><dt>Last updated</dt><dd>{formatDate(r.updated_at)}</dd></div>
            </dl>
          </td>
        </tr>
      )}
    </tbody>
  );
}
