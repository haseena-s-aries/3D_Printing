/**
 * Aries Admin: digital inventory across client companies. Administrative summaries only, from an audited read model
 * (GET /admin/inventory/). No engineering edits, engineering notes, document access, CAD originals, approvals or
 * manufacturing actions. Opening a full client record stays disabled until the support-access consent decision (OQ-37).
 */
import { Fragment, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";

import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { AdminIntelligenceUsage } from "../components/PartIntelligence";
import { AdminAssessmentSummary } from "../components/QuarterlyAssessment";
import { STAGE_TEXT, STAGES, stageFrom } from "../components/inventoryStages";
import { REVIEW_LABEL } from "../components/PartSubmission";
import { Badge, Card, Empty, ErrorNotice, Loading, Notice, PageHeader, Pager, label } from "../components/ui";

type Row = {
  id: string; client_id: string; client_name: string; part_number: string; name: string; project: string; project_name: string;
  origin: string; review_state: string; submission_kind: string; stage: string; digitisation: string; passport_number: string;
  revision: number | null; revision_status: string; publication_state: string; manufacturing_eligibility: string;
  completeness: Record<string, { done: number; total: number }> | null; completeness_pct: number; documents: number;
  assigned_engineers: string[]; updated_at: string;
};
type ClientSummary = { id: string; name: string; counts: Record<string, number>; engineers: string[]; unassigned_review: number };
type Overview = {
  count: number; results: Row[]; totals: Record<string, number>; clients: ClientSummary[]; all_clients: { id: string; name: string }[];
  projects: { id: string; code: string; name: string; client: string }[]; detail_access: { enabled: boolean; decision: string; reason: string };
};

const PAGE_SIZE = 25;
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
  return (
    <>
      {!clientId && <PageHeader title="Digital inventory · all client companies"
        subtitle="Administrative summaries across client companies, to follow review backlogs and digitisation progress." />}
      <Notice>
        Read-only administrative view. Every view is recorded in the Aries audit trail and in each company's own audit trail.
        Engineering edits, engineering notes, documents, CAD originals and approvals are not available here.
      </Notice>
      <div className="catalog-bar">
        <div className="segmented" role="group" aria-label="Inventory stage">
          {STAGES.map((st) => (
            <button key={st} type="button" aria-pressed={stage === st} title={STAGE_TEXT.admin[st][1]} onClick={() => set({ stage: st === "all" ? "" : st })}>
              {STAGE_TEXT.admin[st][0]} <span className="count">{o?.totals[st] ?? "…"}</span>
            </button>
          ))}
        </div>
      </div>
      <p className="muted small section-note" data-testid="stage-description">
        {STAGE_TEXT.admin[stage][1]}
        {stage === "all" && (o?.totals.declined ?? 0) > 0 && ` Includes ${o?.totals.declined} rejected submission${o?.totals.declined === 1 ? "" : "s"}.`}
      </p>
      <ErrorNotice error={data.error} />
      {o && !clientId && (
        <Card title="Backlog by client company">
          <div className="table-scroll">
            <table className="table" aria-label="Backlog by client company">
              <thead><tr><th>Client company</th><th>{STAGE_TEXT.admin.review[0]}</th><th>Review items without an assigned engineer</th>
                <th>{STAGE_TEXT.admin.in_digitisation[0]}</th><th>Published</th><th>All parts</th><th>Aries Engineers</th></tr></thead>
              <tbody>
                {o.clients.map((c) => (
                  <tr key={c.id}>
                    <td><button type="button" className="link-btn" onClick={() => set({ client: c.id, project: "" })}>{c.name}</button></td>
                    <td>{c.counts.review ? <Badge tone="warning">{c.counts.review}</Badge> : 0}</td>
                    <td>{c.unassigned_review ? <Badge tone="danger">{c.unassigned_review}</Badge> : 0}</td>
                    <td>{c.counts.in_digitisation}</td><td>{c.counts.published}</td><td>{c.counts.all}</td>
                    <td className="small">{c.engineers.join(", ") || <span className="muted">None assigned</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
      {!clientId && can("intelligence.usage_admin") && <AdminIntelligenceUsage />}
      {!clientId && can("intelligence.usage_admin") && <AdminAssessmentSummary />}
      <Card>
        <form className="toolbar wrap" role="search" aria-label="Inventory filters" onSubmit={(e: FormEvent) => { e.preventDefault(); set({ search: search.trim() }); }}>
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
          {KEYS.some((k) => k !== "stage" && (k !== "client" || !clientId) && f[k]) && <button type="button" className="btn btn-ghost" onClick={() => { setSearch(""); setParams(keep(stage === "all" ? {} : { stage })); }}>Clear filters</button>}
        </form>
        {o && <p className="muted small" data-testid="detail-access">"Open record" is disabled: {o.detail_access.reason}</p>}
        {data.loading && !o ? <Loading /> : o && o.results.length ? (
          <>
            <div className="table-scroll">
              <table className="table admin-inventory" aria-label="Administrative inventory" aria-busy={data.loading}>
                <thead><tr>{!clientId && <th>Client</th>}<th>Part</th><th>Project</th><th>Passport</th><th>Review</th><th>Digitisation</th><th>Publication</th>
                  <th>Engineering completeness</th><th>Assigned engineer</th><th /></tr></thead>
                <tbody>
                  {o.results.map((r) => (
                    <tr key={r.id}>
                      {!clientId && <td className="small">{r.client_name}</td>}
                      <td><strong>{r.part_number}</strong><div className="small">{r.name}</div>
                        {r.submission_kind === "clone" && <span className="muted small">Clone</span>}</td>
                      <td className="small">{r.project || "—"}</td>
                      <td className="small">{r.passport_number ? <>{r.passport_number}<div className="muted">rev {r.revision} · {r.revision_status}</div></> : "—"}</td>
                      <td className="small">{r.origin === "client" ? (REVIEW_LABEL[r.review_state] ?? label(r.review_state)) : <span className="muted">Aries-maintained</span>}</td>
                      <td><Badge tone={STAGE_BADGE[r.stage] ?? "neutral"}>{r.digitisation}</Badge></td>
                      <td className="small">{r.publication_state ? label(r.publication_state) : "No passport"}</td>
                      <td className="small" title={r.completeness ? Object.entries(r.completeness).map(([k, v]) => `${k.toUpperCase()} ${v.done}/${v.total}`).join(" · ") : ""}>
                        {r.completeness ? <>
                          <meter min={0} max={100} value={r.completeness_pct} aria-label={`Completeness ${r.part_number}`} /> {r.completeness_pct}%
                          <div className="muted">{Object.entries(r.completeness).map(([k, v]) => <Fragment key={k}>{k.toUpperCase().replace("RL", "R-L")} {v.done}/{v.total} </Fragment>)}</div>
                        </> : <span className="muted">No passport data</span>}
                        <div className="muted">{r.documents} document{r.documents === 1 ? "" : "s"}</div>
                      </td>
                      <td className="small">{r.assigned_engineers.length ? r.assigned_engineers.join(", ") : <Badge tone="danger">Unassigned</Badge>}</td>
                      <td><button type="button" className="btn btn-small" disabled title={o.detail_access.reason}>Open record</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager page={page} count={o.count} pageSize={PAGE_SIZE} onPage={(n) => set({ page: String(n) }, true)} />
          </>
        ) : o ? <Empty>No parts match these filters.</Empty> : null}
      </Card>
    </>
  );
}
