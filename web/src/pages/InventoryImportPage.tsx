/**
 * Bulk inventory import and data quality (CN-007 Phase 1). Upload an Excel/CSV file into this client company, map its
 * columns, review the preview (nothing is imported yet), then confirm. Imported parts are unclassified, unassessed
 * inventory records: no passport, approval, price or engineering specification is created or inferred.
 */
import type { InventoryImport, InventoryImportOptions, InventoryImportRow, Paginated, Project } from "@passport/api-types";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { api, upload } from "../api/client";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { IntelligenceOverview } from "../components/PartIntelligence";
import { AssessmentDashboard } from "../components/QuarterlyAssessment";
import { BackLink, Badge, Card, Empty, ErrorNotice, Field, Loading, Notice, PageHeader, Pager, formatDate } from "../components/ui";

const OUTCOME: Record<string, [string, "neutral" | "info" | "success" | "warning" | "danger"]> = {
  new: ["New part", "info"], unchanged: ["Already up to date", "neutral"], update: ["Update available", "warning"],
  conflict: ["Conflict: kept as is", "danger"], error: ["Error: not importable", "danger"],
};
const STATUS: Record<string, "info" | "success" | "neutral"> = { preview: "info", committed: "success", discarded: "neutral" };
type FlagInfo = Record<string, { label: string; level: string }>;
type Quality = {
  totals: Record<string, number>; flags: Record<string, number>; flag_labels: FlagInfo;
  parts: { id: string; part_number: string; name: string; flags: string[]; duplicates: string[]; edited_since_import: string[]; import_reference: string }[];
  conflicts: { import_reference: string; row_number: number; part_number: string; fields: Record<string, { current: string; incoming: string }>; committed_at: string }[];
};

export function useImportOptions() {
  return useApi<InventoryImportOptions>("/inventory-imports/options/");
}

export function FlagChips({ flags, info, onlyWarnings = false }: { flags: string[]; info?: FlagInfo; onlyWarnings?: boolean }) {
  const shown = flags.filter((f) => !onlyWarnings || info?.[f]?.level === "warning");
  if (!shown.length) return <span className="muted small">None</span>;
  return (
    <span className="chips">
      {shown.map((f) => <span key={f} className={`chip chip-${info?.[f]?.level ?? "info"}`} title={info?.[f]?.label}>{info?.[f]?.label ?? f}</span>)}
    </span>
  );
}

function NewImport() {
  const navigate = useNavigate();
  const projects = useApi<Paginated<Project>>("/projects/", { query: { page_size: 200 } });
  const opts = useImportOptions();
  const [file, setFile] = useState<File | null>(null);
  const [project, setProject] = useState("");
  const [preset, setPreset] = useState("sap_material_list");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(null);
    const form = new FormData();
    form.append("file", file);
    if (project) form.append("project", project);
    if (preset) form.append("preset", preset);
    try {
      const b = await upload<InventoryImport>("/inventory-imports/", form);
      navigate(`/inventory-import/${b.id}`);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card title="Upload an inventory file">
      <form className="form-grid" onSubmit={submit} aria-label="Upload inventory file">
        <ErrorNotice error={error} />
        <Notice>Uploading shows a preview only; nothing is imported until you confirm. Re-importing the same file never creates duplicates.
          Imported parts stay unclassified and unassessed; no passport, approval or price is created.</Notice>
        <Field label="Excel (.xlsx) or CSV file" hint={opts.data ? `Up to ${opts.data.max_rows.toLocaleString()} rows and ${Math.round(opts.data.max_bytes / 1048576)} MB. The first sheet is read; the file itself is not stored.` : undefined}>
          <input type="file" required accept=".xlsx,.csv" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </Field>
        <Field label="Column layout">
          <select value={preset} onChange={(e) => setPreset(e.target.value)}>
            {(opts.data?.presets ?? []).map((p) => <option key={p.key as string} value={p.key as string}>{p.label as string}</option>)}
            <option value="">Other layout (match columns by name, then map)</option>
          </select>
        </Field>
        <Field label="Project for new parts" hint="Required if your access is limited to selected projects.">
          <select value={project} onChange={(e) => setProject(e.target.value)}>
            <option value="">No project</option>
            {(projects.data?.results ?? []).map((p) => <option key={p.id} value={p.id}>{p.code} · {p.name}</option>)}
          </select>
        </Field>
        <div className="form-actions"><button className="btn btn-primary" disabled={busy || !file}>{busy ? "Reading file…" : "Upload and preview"}</button></div>
      </form>
    </Card>
  );
}

function History() {
  const list = useApi<Paginated<InventoryImport>>("/inventory-imports/", { query: { page_size: 100 } });
  if (list.loading && !list.data) return <Loading />;
  if (list.error) return <ErrorNotice error={list.error} />;
  if (!list.data?.results.length) return <Card><Empty>No imports yet. Upload a file on the New import tab.</Empty></Card>;
  return (
    <Card>
      <div className="table-scroll">
        <table className="table" aria-label="Import history">
          <thead><tr><th>Import</th><th>File</th><th>Status</th><th>Rows</th><th>Result</th><th>By</th><th>Date</th></tr></thead>
          <tbody>
            {list.data.results.map((b) => {
              const o = (b.counts as { outcomes?: Record<string, number> }).outcomes ?? {};
              const res = b.result as Record<string, number>;
              return (
                <tr key={b.id}>
                  <td><Link to={`/inventory-import/${b.id}`}><strong>{b.reference}</strong></Link><div className="muted small">{b.project_name}</div></td>
                  <td className="small">{b.file_name}</td>
                  <td><Badge tone={STATUS[b.status ?? ""] ?? "neutral"}>{b.status_label}</Badge></td>
                  <td>{b.row_count}</td>
                  <td className="small">{b.status === "committed"
                    ? `${res.created ?? 0} created · ${res.updated ?? 0} updated · ${res.unchanged ?? 0} unchanged · ${res.skipped ?? 0} not applied`
                    : `${o.new ?? 0} new · ${o.update ?? 0} updates · ${o.conflict ?? 0} conflicts · ${o.error ?? 0} errors`}</td>
                  <td className="small">{b.created_by_name}</td>
                  <td className="small">{formatDate(b.committed_at ?? b.created_at)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function DataQuality() {
  const q = useApi<Quality>("/inventory-imports/quality/");
  const [flag, setFlag] = useState("");
  if (q.loading && !q.data) return <Loading />;
  if (q.error || !q.data) return <ErrorNotice error={q.error} />;
  const d = q.data;
  if (!d.totals.imported_parts) return <Card><Empty>No imported parts yet.</Empty></Card>;
  const parts = d.parts.filter((p) => !flag || p.flags.includes(flag));
  const tiles: [string, string][] = [["imported_parts", "Imported parts"], ["with_warnings", "With warnings"], ["possible_duplicates", "Possible duplicates"],
    ["edited_since_import", "Edited since import"], ["not_classified", "Not classified"], ["not_assessed", "Criticality not assessed"]];
  return (
    <>
      <div className="stat-row" data-testid="quality-totals">
        {tiles.map(([k, l]) => <div key={k} className="stat"><strong>{d.totals[k] ?? 0}</strong><span className="muted small">{l}</span></div>)}
      </div>
      <p className="muted small section-note">Checked live against the current records. Flags describe the supplied data; nothing is corrected or
        extracted automatically. Customer ABC indicators are shown as supplied and are not engineering criticality.</p>
      <div className="grid-2 wide-right">
        <Card title="Issues found">
          <table className="table" aria-label="Data-quality issues">
            <thead><tr><th>Issue</th><th>Parts</th></tr></thead>
            <tbody>
              {Object.entries(d.flags).sort((a, b) => (d.flag_labels[a[0]]?.level === "warning" ? 0 : 1) - (d.flag_labels[b[0]]?.level === "warning" ? 0 : 1) || b[1] - a[1]).map(([f, n]) => (
                <tr key={f} className={flag === f ? "selected" : ""}>
                  <td><button type="button" className="link-btn" onClick={() => setFlag(flag === f ? "" : f)}>{d.flag_labels[f]?.label ?? f}</button>
                    {d.flag_labels[f]?.level === "warning" && <> <Badge tone="warning">check</Badge></>}</td>
                  <td>{n}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
        <Card title={flag ? `Parts: ${d.flag_labels[flag]?.label ?? flag}` : "Imported parts"} actions={flag ? <button type="button" className="btn btn-small" onClick={() => setFlag("")}>Show all</button> : undefined}>
          <div className="table-scroll">
            <table className="table" aria-label="Imported parts quality">
              <thead><tr><th>Material number</th><th>Description</th><th>Flags</th><th>Notes</th></tr></thead>
              <tbody>
                {parts.map((p) => (
                  <tr key={p.id}>
                    <td><Link to={`/parts/${p.id}`}><strong>{p.part_number}</strong></Link><div className="muted small">{p.import_reference}</div></td>
                    <td className="small">{p.name}</td>
                    <td><FlagChips flags={p.flags} info={d.flag_labels} onlyWarnings /></td>
                    <td className="small">
                      {p.duplicates.length > 0 && <div>Same description as {p.duplicates.join(", ")}</div>}
                      {p.edited_since_import.length > 0 && <div>Edited since import: {p.edited_since_import.join(", ")}</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
      <Card title="Conflicts left by imports">
        {d.conflicts.length === 0 ? <Empty>No conflicts. Values changed in the application were never overwritten by an import.</Empty> : (
          <table className="table" aria-label="Import conflicts">
            <thead><tr><th>Import / row</th><th>Material number</th><th>Kept value → value in file</th></tr></thead>
            <tbody>
              {d.conflicts.map((c) => (
                <tr key={`${c.import_reference}-${c.row_number}`}>
                  <td className="small">{c.import_reference} · row {c.row_number}</td>
                  <td>{c.part_number}</td>
                  <td className="small">{Object.entries(c.fields).map(([f, v]) => <div key={f}><strong>{f}</strong>: {v.current || "—"} → {v.incoming || "—"}</div>)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}

const TABS = [["new", "New import"], ["history", "Import history"], ["quality", "Data quality"], ["intelligence", "Part intelligence"],
  ["assessment", "Quarterly assessment"]] as const;

export default function InventoryImportPage() {
  const [params, setParams] = useSearchParams();
  const { can } = useAuth();
  // CN-007 Phase 2: Aries-internal part intelligence (rules plus optional AI suggestions)
  const tabs = TABS.filter(([t]) => !(t === "intelligence" || t === "assessment") || can("intelligence.view"));
  const tab = tabs.some(([t]) => t === params.get("tab")) ? params.get("tab") : "new";
  return (
    <>
      <PageHeader title="Inventory import" subtitle="Bulk-import this company's spare-parts inventory from Excel or CSV and review its data quality." />
      <div className="tabs" role="tablist" aria-label="Inventory import">
        {tabs.map(([t, l]) => (
          <button key={t} type="button" role="tab" aria-selected={tab === t} className={`tab ${tab === t ? "is-active" : ""}`}
            onClick={() => setParams(t === "new" ? {} : { tab: t })}>{l}</button>
        ))}
      </div>
      {tab === "new" && <NewImport />}
      {tab === "history" && <History />}
      {tab === "quality" && <DataQuality />}
      {tab === "intelligence" && <IntelligenceOverview />}
      {tab === "assessment" && <AssessmentDashboard />}
    </>
  );
}

const PAGE = 50;

export function InventoryImportDetailPage() {
  const { id } = useParams();
  const batch = useApi<InventoryImport>(`/inventory-imports/${id}/`);
  const opts = useImportOptions();
  const projects = useApi<Paginated<Project>>("/projects/", { query: { page_size: 200 } });
  const [outcome, setOutcome] = useState("");
  const [page, setPage] = useState(1);
  const rows = useApi<Paginated<InventoryImportRow>>(`/inventory-imports/${id}/rows/`, { query: { outcome, page, page_size: PAGE, v: batch.data?.analysed_at ?? "" } });
  const [draft, setDraft] = useState<Record<string, string> | null>(null);
  const [applyUpdates, setApplyUpdates] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  if (batch.loading && !batch.data) return <Loading />;
  if (batch.error || !batch.data) return <><BackLink to="/inventory-import?tab=history">Import history</BackLink><ErrorNotice error={batch.error} /></>;
  const b = batch.data;
  const preview = b.status === "preview";
  const counts = (b.counts as { outcomes?: Record<string, number>; flags?: Record<string, number> }) ?? {};
  const o = counts.outcomes ?? {};
  const mapping = draft ?? (b.mapping as Record<string, string>);
  const firstRow = rows.data?.results[0]?.source as Record<string, string> | undefined;
  const flagInfo = (opts.data?.flags ?? {}) as FlagInfo;

  async function run(fn: () => Promise<InventoryImport>) {
    setBusy(true);
    setError(null);
    try {
      batch.setData(await fn());
      setDraft(null);
      setPage(1);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  const saveMapping = () => run(() => api<InventoryImport>(`/inventory-imports/${b.id}/`, { method: "PATCH", body: { mapping } }));
  const changeProject = (project: string) => run(() => api<InventoryImport>(`/inventory-imports/${b.id}/`, { method: "PATCH", body: { mapping, project: project || null } }));
  const commit = () => run(() => api<InventoryImport>(`/inventory-imports/${b.id}/commit/`, { body: { confirm: true, apply_updates: applyUpdates } }));
  const discard = () => run(() => api<InventoryImport>(`/inventory-imports/${b.id}/discard/`, { body: {} }));
  const res = b.result as Record<string, number>;

  return (
    <>
      <BackLink to="/inventory-import?tab=history">Import history</BackLink>
      <PageHeader title={`${b.reference} · ${b.file_name}`}
        subtitle={<><Badge tone={STATUS[b.status ?? ""] ?? "neutral"}>{b.status_label}</Badge> <span className="muted small">{b.row_count} rows · {b.file_kind?.toUpperCase()}
          {b.sheet_name ? ` · sheet "${b.sheet_name}"` : ""} · header row {b.header_row} · SHA-256 {b.file_sha256?.slice(0, 12)}… · {b.created_by_name}, {formatDate(b.created_at)}</span></>} />
      <ErrorNotice error={error} />
      {preview ? <Notice>Preview: nothing has been imported yet. Check the mapping and the rows, then confirm below.</Notice>
        : b.status === "committed" ? <Notice kind="success">Imported {formatDate(b.committed_at)} by {b.committed_by_name}: {res.created ?? 0} created,
          {" "}{res.updated ?? 0} updated, {res.unchanged ?? 0} already up to date, {res.skipped ?? 0} not applied (errors, conflicts or updates not chosen).</Notice>
          : <Notice kind="warning">Discarded. Nothing was imported.</Notice>}
      <div className="grid-2">
        <Card title="Column mapping">
          <div className="table-scroll">
            <table className="table" aria-label="Column mapping">
              <thead><tr><th>Field</th><th>Column in the file</th><th>First row</th></tr></thead>
              <tbody>
                {(opts.data?.targets ?? []).map((t) => {
                  const field = t.field as string;
                  return (
                    <tr key={field}>
                      <td><strong>{t.label as string}</strong>{t.required ? " *" : ""}{t.note ? <div className="muted small">{t.note as string}</div> : null}</td>
                      <td>{preview ? (
                        <select aria-label={`Column for ${t.label as string}`} value={mapping[field] ?? ""} onChange={(e) => setDraft({ ...mapping, [field]: e.target.value })}>
                          <option value="">Not imported</option>
                          {(b.headers as string[]).map((h) => <option key={h} value={h}>{h}</option>)}
                        </select>
                      ) : (mapping[field] || <span className="muted">Not imported</span>)}</td>
                      <td className="small mono">{mapping[field] && firstRow ? (firstRow[mapping[field]] || "—") : ""}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {preview && draft && <div className="form-actions"><button type="button" className="btn" onClick={() => setDraft(null)}>Undo</button>
            <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void saveMapping()}>Apply mapping</button></div>}
        </Card>
        <Card title={preview ? "Confirm import" : "Summary"}>
          <dl className="facts">
            <div className="fact-row"><dt>Project for new parts</dt><dd>{preview ? (
              <select aria-label="Project for new parts" value={b.project ?? ""} disabled={busy} onChange={(e) => void changeProject(e.target.value)}>
                <option value="">No project</option>
                {(projects.data?.results ?? []).map((p) => <option key={p.id} value={p.id}>{p.code} · {p.name}</option>)}
              </select>) : (b.project_name || "No project")}</dd></div>
            <div className="fact-row"><dt>Imported by</dt><dd>{b.importer_side === "client" ? "Client (new parts wait for Aries review)" : "Aries"}</dd></div>
          </dl>
          <div className="stat-row" data-testid="outcome-counts">
            {Object.entries(OUTCOME).map(([k, [l]]) => <div key={k} className="stat"><strong>{o[k] ?? 0}</strong><span className="muted small">{l}</span></div>)}
          </div>
          {preview && (
            <div className="stack">
              {(o.update ?? 0) > 0 && <label className="inline-check"><input type="checkbox" checked={applyUpdates} onChange={(e) => setApplyUpdates(e.target.checked)} />
                Also apply {o.update} update{o.update === 1 ? "" : "s"} to values that still hold what an earlier import wrote</label>}
              <label className="inline-check"><input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
                I reviewed the preview. Rows with errors or conflicts are not applied.</label>
              <div className="toolbar wrap">
                <button type="button" className="btn btn-primary" disabled={busy || !confirmed || ((o.new ?? 0) + (applyUpdates ? (o.update ?? 0) : 0) === 0)}
                  onClick={() => void commit()}>Import {o.new ?? 0} new part{o.new === 1 ? "" : "s"}{applyUpdates && o.update ? ` and ${o.update} update${o.update === 1 ? "" : "s"}` : ""}</button>
                <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => void discard()}>Discard</button>
              </div>
            </div>
          )}
        </Card>
      </div>
      <Card title="Rows">
        <div className="segmented" role="group" aria-label="Filter rows">
          <button type="button" aria-pressed={outcome === ""} onClick={() => { setOutcome(""); setPage(1); }}>All <span className="count">{b.row_count}</span></button>
          {Object.entries(OUTCOME).map(([k, [l]]) => (
            <button key={k} type="button" aria-pressed={outcome === k} onClick={() => { setOutcome(k); setPage(1); }}>{l} <span className="count">{o[k] ?? 0}</span></button>
          ))}
        </div>
        {rows.loading && !rows.data ? <Loading /> : rows.data?.results.length ? (
          <>
            <div className="table-scroll">
              <table className="table import-rows" aria-label="Import rows">
                <thead><tr><th>Row</th><th>Material number</th><th>Description</th><th>Manufacturer (as supplied)</th><th>Result</th><th>Data quality</th></tr></thead>
                <tbody>
                  {rows.data.results.map((r) => {
                    const v = r.values as Record<string, string>;
                    const [ol, tone] = OUTCOME[r.outcome ?? ""] ?? [r.outcome, "neutral"];
                    return (
                      <tr key={r.id} data-testid={`row-${r.row_number}`}>
                        <td>{r.row_number}</td>
                        <td>{r.part ? <Link to={`/parts/${r.part}`}>{v.part_number}</Link> : (v.part_number || <span className="muted">—</span>)}</td>
                        <td className="small">{v.name}</td>
                        <td className="small">{v.manufacturer ? <><span className="mono">{JSON.stringify(v.manufacturer)}</span>{v.manufacturer_reference && <div className="muted">ref {v.manufacturer_reference}</div>}</> : <span className="muted">—</span>}</td>
                        <td>
                          <Badge tone={tone as "neutral"}>{ol}</Badge>
                          {r.applied && <div className="muted small">{r.applied}</div>}
                          {(r.messages as { level: string; text: string }[]).map((m, i) => <div key={i} className={`small ${m.level === "error" ? "text-danger" : "muted"}`}>{m.text}</div>)}
                          {Object.entries(r.changes as Record<string, { current: string; incoming: string }>).map(([f, c]) => <div key={f} className="small">{f}: {c.current || "—"} → {c.incoming || "—"}</div>)}
                          {Object.entries(r.conflicts as Record<string, { current: string; incoming: string }>).map(([f, c]) => <div key={f} className="small">{f}: kept “{c.current}”, file has “{c.incoming}”</div>)}
                        </td>
                        <td><FlagChips flags={r.flags as string[]} info={flagInfo} /></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <Pager page={page} count={rows.data.count} pageSize={PAGE} onPage={setPage} />
          </>
        ) : <Empty>No rows match this filter.</Empty>}
      </Card>
    </>
  );
}

type AdminImport = { id: string; reference: string; status: string; status_label: string; file_name: string; row_count: number;
  outcomes: Record<string, number>; result: Record<string, number>; importer_side: string; created_by: string; created_at: string;
  committed_at: string | null; project: string };

/** Aries Admin (Client Management → Inventory Import): import summaries for one company and discarding open previews. */
export function ClientImports({ clientId }: { clientId: string }) {
  const { can } = useAuth();
  const data = useApi<{ clients: { client_id: string; imports: AdminImport[] }[] }>(can("inventory.import_admin") ? "/admin/inventory-imports/" : null, { query: { client: clientId } });
  const [error, setError] = useState<unknown>(null);
  if (!can("inventory.import_admin")) return <Card><Empty>Inventory import is not enabled.</Empty></Card>;
  if (data.loading && !data.data) return <Loading />;
  const imports = data.data?.clients[0]?.imports ?? [];
  async function discard(id: string) {
    setError(null);
    try {
      await api("/admin/inventory-imports/", { body: { client: clientId, import: id } });
      await data.reload();
    } catch (err) {
      setError(err);
    }
  }
  return (
    <Card title="Inventory imports">
      <p className="muted small">Summaries only: file, counts and who imported. Row contents and part data are not shown here. Assigned Aries
        Engineers (and Client Administrators you allow on Client Users) carry out imports inside the company.</p>
      <ErrorNotice error={error ?? data.error} />
      {imports.length === 0 ? <Empty>No inventory imports for this company yet.</Empty> : (
        <table className="table" aria-label="Company inventory imports">
          <thead><tr><th>Import</th><th>File</th><th>Status</th><th>Rows</th><th>Result</th><th>By</th><th /></tr></thead>
          <tbody>
            {imports.map((b) => (
              <tr key={b.id}>
                <td><strong>{b.reference}</strong><div className="muted small">{b.project || "No project"} · {b.importer_side === "client" ? "client" : "Aries"}</div></td>
                <td className="small">{b.file_name}</td>
                <td><Badge tone={STATUS[b.status] ?? "neutral"}>{b.status_label}</Badge></td>
                <td>{b.row_count}</td>
                <td className="small">{b.status === "committed" ? `${b.result.created ?? 0} created · ${b.result.updated ?? 0} updated`
                  : `${b.outcomes.new ?? 0} new · ${b.outcomes.conflict ?? 0} conflicts · ${b.outcomes.error ?? 0} errors`}</td>
                <td className="small">{b.created_by}<div className="muted">{formatDate(b.committed_at ?? b.created_at)}</div></td>
                <td>{b.status === "preview" && <button type="button" className="btn btn-small btn-ghost" onClick={() => void discard(b.id)}>Discard preview</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

