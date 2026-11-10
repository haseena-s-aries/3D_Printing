/**
 * Digital inventory catalog (BR-010, BR-011). Search, filters, sort and paging are server-side and kept in the URL,
 * so links from the dashboard land on a filtered view and the browser back button keeps the user's place.
 * Client users get a visual card grid by default and two clearly separated sections: the published manufacturing
 * catalog and parts still in digitisation (shown, never hidden, and marked as not manufacturing-ready). Operator staff
 * keep the engineering table by default. No ordering or approval action is offered (OQ-35/OQ-36).
 */
import type { Paginated, Part, Project } from "@passport/api-types";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useDecision } from "../components/decision";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { DATA_LEVEL_LABEL, DataLevel, ELIGIBILITY_LABEL, PartCard, Readiness, Thumbnail, docSummary } from "../components/catalog";
import PartForm, { EMPTY_PART, PART_CATEGORIES } from "../components/PartForm";
import { ReviewBadge } from "../components/PartSubmission";
import { STAGE_TEXT, STAGES, stageFrom, type Audience, type Stage } from "../components/inventoryStages";
import QuickView from "../components/QuickView";
import { canClone } from "./PartClonePage";
import RequestDialog from "../components/RequestDialog";
import { Icon } from "../components/icons";
import { Card, Empty, ErrorNotice, Loading, PageHeader, Pager, formatDate, label } from "../components/ui";

const PAGE_SIZE = 25;
const FILTER_KEYS = ["search", "project", "category", "data_level", "evidence_level", "eligibility", "has_3d", "ordering", "catalog"] as const;
const NOT_COUNTED = new Set(["ordering", "catalog"]);
const ADVANCED_KEYS = ["category", "data_level", "evidence_level", "eligibility", "has_3d"] as const;
const SORTS: [string, string][] = [
  ["-last_activity", "Recently updated"], ["part_number", "Part number A–Z"], ["-part_number", "Part number Z–A"], ["name", "Name A–Z"], ["-created", "Newest first"],
];

export default function PartsPage() {
  const { can, session } = useAuth();
  const isOperator = !!session?.membership.role.startsWith("operator");
  const oq = useDecision();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const filters = Object.fromEntries(FILTER_KEYS.map((k) => [k, params.get(k) ?? ""])) as Record<(typeof FILTER_KEYS)[number], string>;
  const page = Number(params.get("page") ?? "1") || 1;
  const list = useApi<Paginated<Part>>("/parts/", { query: { ...filters, catalog: filters.catalog === "all" ? "" : filters.catalog, page, page_size: PAGE_SIZE } });
  const projects = useApi<Paginated<Project>>("/projects/", { query: { page_size: 200 } });
  const [search, setSearch] = useState(filters.search);
  const [showForm, setShowForm] = useState(false);
  const [quick, setQuick] = useState<Part | null>(null);
  const closeQuick = useCallback(() => setQuick(null), []);
  const [requesting, setRequesting] = useState<Part | null>(null);
  const closeRequest = useCallback(() => setRequesting(null), []);
  const canRequest = can("requests.create");
  const active = FILTER_KEYS.filter((k) => !NOT_COUNTED.has(k) && filters[k]).length;
  // essential filters stay in the row; the rest open on demand (and start open when one of them is in use)
  const advanced = ADVANCED_KEYS.filter((k) => filters[k]).length;
  const [showAdvanced, setShowAdvanced] = useState(advanced > 0);
  const view = params.get("view") ?? (isOperator ? "list" : "grid");
  // Stage tabs (review / in digitisation / published / all) are derived server-side from the review status and the
  // publication state, which stay separate; counts follow the other filters.
  const stage: Stage | "" = stageFrom(filters.catalog);
  const section = stage === "all" ? "" : stage;
  const audience: Audience = isOperator ? "engineer" : "client";
  const countFilters = Object.fromEntries(Object.entries(filters).filter(([k]) => k !== "catalog" && k !== "ordering"));
  const counts = useApi<Record<string, number>>("/parts/stage-counts/", { query: countFilters });

  function update(changes: Partial<Record<string, string>>, keepPage = false, replace = false) {
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      for (const [k, v] of Object.entries(changes)) (v ? next.set(k, v) : next.delete(k));
      if (!keepPage) next.delete("page");
      return next;
    }, { replace });
  }

  // Clients open on the published catalog when it has parts, otherwise on the parts being digitised. "All parts" stays
  // selectable (explicit catalog=all).
  useEffect(() => {
    if (isOperator || stage || !counts.data) return;
    // a search opened without a tab looks across every stage, so awaiting-review parts are not hidden
    update({ catalog: filters.search ? "all" : counts.data.published > 0 ? "published" : "in_digitisation" }, true, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOperator, stage, counts.data]);

  function submitSearch(e: FormEvent) {
    e.preventDefault();
    update({ search: search.trim() });
  }

  return (
    <>
      <PageHeader
        title="Digital inventory"
        subtitle="Spare parts and their digital passports. Each part can hold one passport."
        actions={
          <div className="toolbar">
            {canRequest && <Link className="btn" to="/requests/new-scan">Request 3D scanning</Link>}
            {can("parts.submit") && (
              <Link className="btn btn-primary" to="/parts/submit">{session?.membership.role === "client_admin" ? "Add spare part" : "Propose a new part"}</Link>
            )}
            {can("parts.manage") && <button className="btn btn-primary" onClick={() => setShowForm((s) => !s)}>{showForm ? "Close" : "New spare part"}</button>}
          </div>
        }
      />
      {showForm && (
        <Card title="New spare part (draft)">
          <PartForm
            initial={EMPTY_PART}
            projects={projects.data?.results ?? []}
            submitLabel="Create spare part"
            onSubmit={async (values) => {
              const part = await api<Part>("/parts/", { body: values });
              navigate(`/parts/${part.id}`);
            }}
          />
        </Card>
      )}
      <div className="catalog-bar">
        <div className="segmented" role="group" aria-label="Catalog section">
          {STAGES.map((st) => (
            <button key={st} type="button" title={STAGE_TEXT[audience][st][1]} data-stage={st}
              aria-pressed={st === "all" ? !section : section === st}
              onClick={() => update({ catalog: st === "all" ? (isOperator ? "" : "all") : st })}>
              {STAGE_TEXT[audience][st][0]} <span className="count">{counts.data?.[st] ?? "…"}</span>
            </button>
          ))}
        </div>
        <div className="segmented" role="group" aria-label="Layout">
          <button type="button" aria-pressed={view === "grid"} onClick={() => update({ view: "grid" }, true)}><Icon name="grid" size="sm" />Grid</button>
          <button type="button" aria-pressed={view === "list"} onClick={() => update({ view: "list" }, true)}><Icon name="list" size="sm" />List</button>
        </div>
      </div>
      <p className="muted small section-note" data-testid="stage-description">
        {STAGE_TEXT[audience][section || "all"][1]}
        {!section && (counts.data?.declined ?? 0) > 0 && ` Includes ${counts.data?.declined} rejected submission${counts.data?.declined === 1 ? "" : "s"}.`}
        {section === "published" && !isOperator && " Manufacturing requests open once the manufacturing rules are agreed."}
      </p>
      <Card>
        <form className="catalog-filters" onSubmit={submitSearch} role="search" aria-label="Catalog filters">
          <div className="filter-row">
            <div className="search-field">
              <Icon name="search" />
              <input type="search" placeholder="Search part number, passport number, name or description" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search spare parts" />
            </div>
            <button className="btn">Search</button>
            <select aria-label="Filter by project" value={filters.project} onChange={(e) => update({ project: e.target.value })}>
              <option value="">All projects</option>
              {(projects.data?.results ?? []).map((p) => <option key={p.id} value={p.id}>{p.code} · {p.name}</option>)}
            </select>
            <select aria-label="Sort by" value={filters.ordering || "-last_activity"} onChange={(e) => update({ ordering: e.target.value === "-last_activity" ? "" : e.target.value })}>
              {SORTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
            <button type="button" className={`btn ${showAdvanced ? "is-active" : ""}`} aria-expanded={showAdvanced} aria-controls="advanced-filters"
              onClick={() => setShowAdvanced((v) => !v)}>
              <Icon name="filter" size="sm" />Advanced filters{advanced > 0 && <span className="count-dot" aria-label={`${advanced} active`}>{advanced}</span>}
            </button>
            {active > 0 && (
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => {
                  setSearch("");
                  const keep = new URLSearchParams();
                  for (const k of ["catalog", "view"]) if (params.get(k)) keep.set(k, params.get(k)!);
                  setParams(keep);
                }}
              >
                Clear filters ({active})
              </button>
            )}
          </div>
          <div id="advanced-filters" className="advanced-filters" hidden={!showAdvanced}>
            <label>Category
              <select aria-label="Filter by category" value={filters.category} onChange={(e) => update({ category: e.target.value })}>
                <option value="">All categories</option>
                {PART_CATEGORIES.map((c) => <option key={c} value={c}>{label(c)}</option>)}
              </select>
            </label>
            <label>Data captured
              <select aria-label="Filter by data captured" value={filters.data_level} onChange={(e) => update({ data_level: e.target.value })}>
                <option value="">Any data captured</option>
                <option value="rl1">{DATA_LEVEL_LABEL.rl1} or more</option>
                <option value="rl2">{DATA_LEVEL_LABEL.rl2} or more</option>
                <option value="rl3">{DATA_LEVEL_LABEL.rl3}</option>
                <option value="none">Incomplete or no passport</option>
              </select>
            </label>
            <label>Evidence level
              <select aria-label="Filter by evidence level" value={filters.evidence_level} onChange={(e) => update({ evidence_level: e.target.value })}
                title={`Official readiness (evidence) level${oq("OQ-35")}`}>
                <option value="">Any evidence level</option>
                <option value="none">Not assessed</option>
                <option value="R-L1">R-L1</option>
                <option value="R-L2">R-L2</option>
                <option value="R-L3">R-L3</option>
              </select>
            </label>
            <label>Manufacturing eligibility
              <select aria-label="Filter by manufacturing eligibility" value={filters.eligibility} onChange={(e) => update({ eligibility: e.target.value })}
                title={`Stored manufacturing eligibility${oq("OQ-36")}`}>
                <option value="">Any eligibility</option>
                {Object.entries(ELIGIBILITY_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </label>
            <label className="inline-check">
              <input type="checkbox" checked={filters.has_3d === "true"} onChange={(e) => update({ has_3d: e.target.checked ? "true" : "" })} /> Has 3D view
            </label>
          </div>
        </form>
        <ErrorNotice error={list.error} />
        {list.error ? null : list.loading && !list.data ? (
          <Loading />
        ) : list.data?.results.length ? (
          <>
            {view === "grid" ? (
              <ul className="part-grid" aria-label="Spare parts" aria-busy={list.loading}>
                {list.data.results.map((p) => <li key={p.id}><PartCard part={p} onQuickView={setQuick} onRequest={canRequest ? setRequesting : undefined} cloneable={canClone(p, can)} /></li>)}
              </ul>
            ) : (
            <table className="table catalog-table" aria-busy={list.loading}>
              <thead>
                <tr><th aria-label="Photo" /><th>Part</th><th>Passport</th><th>Data captured</th><th>Documents</th><th>Last activity</th></tr>
              </thead>
              <tbody>
                {list.data.results.map((p) => (
                  <tr key={p.id}>
                    <td><Thumbnail thumb={p.thumbnail} alt={p.part_number} /></td>
                    <td>
                      <div className="list-part-head"><Link to={`/parts/${p.id}`}><strong>{p.part_number}</strong></Link> <ReviewBadge part={p} /></div>
                      <div>{p.name}</div>
                      <div className="muted small">
                        {label(p.category ?? "")}{p.dimensions ? ` · ${p.dimensions}` : ""}{p.project_name ? ` · ${p.project_name}` : ""}
                      </div>
                      <button type="button" className="link-btn small" onClick={() => setQuick(p)}>Quick view</button>
                    </td>
                    <td>
                      {p.passport_id ? (
                        <>
                          <Link to={`/passports/${p.passport_id}`}>{p.passport_number}</Link>
                          <div className="muted small">
                            {p.revision ? `rev ${p.revision.number} (${p.revision.status})` : ""} · {label(p.publication_state ?? "")}
                          </div>
                          {!isOperator && <div className="list-passport-status"><Readiness part={p} />
                            <span className="muted small">{ELIGIBILITY_LABEL[p.manufacturing_eligibility ?? ""] ?? "No passport"}</span></div>}
                        </>
                      ) : (
                        <span className="muted">None</span>
                      )}
                    </td>
                    <td><DataLevel level={p.data_captured} /></td>
                    <td className="small">{docSummary(p.documents, p.has_3d)}</td>
                    <td className="small">{formatDate(p.last_activity)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            )}
            <Pager page={page} count={list.data.count} pageSize={PAGE_SIZE} onPage={(n) => update({ page: String(n) }, true)} />
          </>
        ) : (
          <Empty>
            {active
              ? "No spare parts match these filters."
              : counts.data?.all === 0
                ? "No spare parts yet."
                : section === "published"
                ? `No parts are published in your manufacturing catalog yet${oq("OQ-35")}. Your parts are listed under ${STAGE_TEXT[audience].in_digitisation[0]}, and you can send enquiries for them.`
                : section === "in_digitisation"
                  ? `No parts in "${STAGE_TEXT[audience].in_digitisation[0]}".`
                  : section === "review"
                    ? `Nothing in "${STAGE_TEXT[audience].review[0]}".`
                    : "No spare parts yet."}
          </Empty>
        )}
      </Card>
      {quick && <QuickView part={quick} cloneable={canClone(quick, can)} onClose={closeQuick} onRequest={canRequest ? (p) => { setQuick(null); setRequesting(p); } : undefined} />}
      {requesting && <RequestDialog part={requesting} onClose={closeRequest} />}
    </>
  );
}
