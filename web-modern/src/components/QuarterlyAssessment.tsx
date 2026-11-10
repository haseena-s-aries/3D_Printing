/**
 * Quarterly inventory assessment & analytics (CN-007 Phase 6), Aries-internal. Runs take every in-scope imported part
 * through part intelligence, feasibility, cost comparison and recommendation in the background (one part per job,
 * unchanged parts reuse the previous result). The dashboard shows the latest completed run and the changes since the
 * preceding run. Estimated savings are provisional; only verified savings meet every mandatory requirement with current
 * quotations. Nothing here approves, publishes or releases anything.
 */
import { Fragment, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, fetchObjectUrl } from "../api/client";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { AiWorkflow } from "./AiWorkflow";
import { Badge, Card, Empty, ErrorNotice, Loading, Notice, formatDate } from "./ui";

type Run = { id: string; number: number; kind: string; kind_label: string; quarter: string; status: string; status_label: string; ai_tier: string;
  methodology: Record<string, string>; part_count: number; done_count: number; reused_count: number; failed_count: number; started_at: string | null;
  finished_at: string | null; created_at: string; previous_run: number | null; requested_by: string; fault_injection: boolean };
type Money = Record<string, string>;
type Summary = { total_parts: number; in_scope: number; outside_scope: number; assessed: number; unassessed: number; insufficient_technical_data: number;
  am_candidates: number; am_specialist: number; conventional_candidates: number; conventional_specialist: number;
  oem: { identity_verified: number; identity_not_verified: number; cost_evidence: Record<string, { count: number; label: string }>; with_expired_evidence: number;
    availability_not_documented: number };
  potentially_obsolete: number; review_backlog: { preliminary: number; information_requested: number; total: number; reviewed: number };
  savings: { estimated: Money; verified: Money; estimated_parts: number; verified_parts: number; note: string }; evidence_gaps_total: number };
type Change = { part: string; [k: string]: unknown };
type Comparison = { previous_run: number | null; note?: string; new_am_candidates?: string[]; new_conventional_candidates?: string[];
  technical_changes?: Change[]; evidence_gaps?: Change[]; oem_changes?: Change[]; cost_changes?: Change[]; lead_time_changes?: Change[];
  outcome_changes?: Change[]; unchanged?: string[]; added_parts?: string[]; removed_parts?: string[] };
type Opt = { total: string | null; complete: boolean; lead_days: number | null; evidence: string; eligible: boolean; excluded: boolean };
type Item = { id: string; part_id: string; part_number: string; name: string; project: string; status: string; status_label: string; attempts: number;
  error_code: string; error_message: string; sources: { feasibility?: { version: number }; cost_comparison?: { version: number; synthetic: boolean } | null;
    recommendation?: { version: number }; reused_from_run?: number; notes?: string[] };
  result: { feasibility: Record<"oem" | "additive" | "conventional", { label: string }>; insufficient_technical_data: boolean; evidence_gaps: string[];
    oem: { cost_evidence: string; expired: string[] }; commercial: { currency: string; options: Record<string, Opt> } | null;
    savings: { estimated: { amount: string; currency: string; option: string; qualified: boolean } | null; verified: { amount: string; currency: string; option: string } | null };
    recommendation: { label: string }; obsolescence_signals: string[] } | Record<string, never>;
  review_state: { label: string; code: string } | null };
type Detail = { run: Run; items: Item[]; progress: Record<string, number>; summary: Summary | null; comparison: Comparison | null };
type Schedule = { enabled: boolean; months: number[]; day_of_month: number; ai_tier: string; updated_at: string | null; updated_by: string };
type Dash = { runs: Run[]; latest: Detail | null; active: Run | null; total_parts: number; ai: { enabled: boolean; reason: string; models: Record<string, string> };
  schedule: Schedule; statement: string };

const money = (m: Money | undefined) => (m && Object.keys(m).length ? Object.entries(m).map(([c, v]) => `${c} ${Number(v).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`).join("; ") : "none");
const TONE: Record<string, "neutral" | "info" | "success" | "warning" | "danger"> = { completed: "success", completed_with_errors: "warning", failed: "danger",
  running: "info", queued: "info", cancelled: "neutral", done: "success", reused: "info", pending: "neutral" };
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function Kpi({ label, value, sub, id }: { label: string; value: React.ReactNode; sub?: React.ReactNode; id: string }) {
  return <div className="stat" data-testid={`kpi-${id}`}><strong>{value}</strong><span className="muted small">{label}</span>{sub && <span className="muted small block">{sub}</span>}</div>;
}

async function download(run: Run, fmt: "xlsx" | "pdf", onError: (e: unknown) => void) {
  try {
    const url = await fetchObjectUrl(`/intelligence/assessments/${run.id}/report.${fmt}`);
    const a = document.createElement("a");
    a.href = url;
    a.download = `assessment-run-${run.number}-${run.quarter}.${fmt}`;
    a.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 5000);
  } catch (e) { onError(e); }
}

function Changes({ c }: { c: Comparison | null }) {
  if (!c) return null;
  if (c.previous_run == null) return <p className="muted small" data-testid="changes">{c.note}</p>;
  const groups: [string, Change[] | string[] | undefined, (x: never) => string][] = [
    ["New AM candidates", c.new_am_candidates, (x: string) => x],
    ["New conventional candidates", c.new_conventional_candidates, (x: string) => x],
    ["Technical screening changes", c.technical_changes, (x: Change) => `${x.part} ${x.option}: ${x.before} → ${x.after}`],
    ["Evidence gaps", c.evidence_gaps, (x: Change) => `${x.part}: ${x.before} → ${x.after}` + ((x.closed as string[]).length ? `; closed: ${(x.closed as string[]).join(", ")}` : "") + ((x.new as string[]).length ? `; new: ${(x.new as string[]).join(", ")}` : "")],
    ["OEM / obsolescence changes", c.oem_changes, (x: Change) => `${x.part} ${x.what}: ${String(x.before)} → ${String(x.after)}`],
    ["Cost changes", c.cost_changes, (x: Change) => `${x.part} ${x.option}: ${x.before ?? "none"} → ${x.after ?? "incomplete"} ${x.currency ?? ""}${x.delta ? ` (Δ ${x.delta})` : ""} · scenario ${x.scenario}`],
    ["Lead-time changes", c.lead_time_changes, (x: Change) => `${x.part} ${x.option}: ${x.before ?? "—"} → ${x.after ?? "—"} days`],
    ["Recommendation outcome changes", c.outcome_changes, (x: Change) => `${x.part}: ${x.before} → ${x.after}`],
  ];
  return (
    <div data-testid="changes">
      <p className="small">Compared with run {c.previous_run}: {(c.unchanged ?? []).length} unchanged part(s){c.added_parts?.length ? `, added ${c.added_parts.join(", ")}` : ""}
        {c.removed_parts?.length ? `, removed ${c.removed_parts.join(", ")}` : ""}.</p>
      {groups.some(([, list]) => list?.length) && <dl className="facts small">
        {groups.filter(([, list]) => list?.length).map(([label, list, fmt]) => (
          <Fragment key={label}><dt>{label} ({list!.length})</dt>
            <dd><ul className="plain-list">{(list as never[]).map((x, i) => <li key={i}>{fmt(x)}</li>)}</ul></dd></Fragment>))}
      </dl>}
      {groups.some(([, list]) => !list?.length) && <p className="muted small">No changes: {groups.filter(([, list]) => !list?.length).map(([label]) => label).join(" · ")}.</p>}
    </div>
  );
}

function Items({ d }: { d: Detail }) {
  return (
    <div className="table-scroll">
      <table className="table compact" aria-label="Assessed parts">
        <thead><tr><th>Material number</th><th>Run status</th><th>Outcome</th><th>AM / conventional screening</th><th>OEM evidence</th><th>Totals</th>
          <th>Estimated / verified saving</th><th>Review</th><th>Sources</th></tr></thead>
        <tbody>{d.items.map((i) => {
          const r = i.result as Exclude<Item["result"], Record<string, never>>;
          const has = r && "feasibility" in r;
          return (
            <tr key={i.id}>
              <td><Link to={`/parts/${i.part_id}`}><strong>{i.part_number}</strong></Link><div className="small">{i.name}</div></td>
              <td><Badge tone={TONE[i.status]}>{i.status_label}</Badge>{i.attempts > 1 && <span className="muted small block">{i.attempts} attempts</span>}
                {i.error_message && <span className="muted small block">{i.error_message}</span>}</td>
              {has ? <>
                <td className="small">{r.recommendation.label}</td>
                <td className="small">{r.feasibility.additive.label}<div className="muted">{r.feasibility.conventional.label}</div>
                  {r.insufficient_technical_data && <Badge tone="neutral">insufficient technical data</Badge>}</td>
                <td className="small">{r.feasibility.oem.label}<div className="muted">{r.oem.cost_evidence.replace(/_/g, " ")}{r.oem.expired.length ? ` · ${r.oem.expired.length} expired` : ""}</div></td>
                <td className="small totals-cell">{r.commercial ? Object.entries(r.commercial.options).map(([k, o]) => <div key={k}>{k}: {o.complete ? `${r.commercial!.currency} ${o.total}` : "incomplete"}{o.lead_days != null ? ` · ${o.lead_days} d` : ""}</div>) : <span className="muted">No cost comparison</span>}</td>
                <td className="small">{r.savings.estimated ? <>{r.savings.estimated.currency} {r.savings.estimated.amount} ({r.savings.estimated.option}){!r.savings.estimated.qualified && <Badge tone="warning">not technically qualified</Badge>}</> : "—"}
                  <div>{r.savings.verified ? `verified ${r.savings.verified.currency} ${r.savings.verified.amount}` : <span className="muted">not verified</span>}</div></td>
                <td className="small">{i.review_state?.label ?? "—"}</td>
                <td className="small muted">feasibility v{i.sources.feasibility?.version}{i.sources.cost_comparison ? `, cost v${i.sources.cost_comparison.version}` : ""}
                  , rec v{i.sources.recommendation?.version}{i.sources.reused_from_run ? ` (from run ${i.sources.reused_from_run})` : ""}</td>
              </> : <td colSpan={7} className="muted small">Not assessed</td>}
            </tr>);
        })}</tbody>
      </table>
    </div>
  );
}

function ScheduleForm({ s, onSaved }: { s: Schedule; onSaved: () => void }) {
  const [v, setV] = useState(s);
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  async function save() {
    setError(null); setSaved(false);
    try { await api(`/intelligence/assessment-schedule/`, { method: "PUT", body: { enabled: v.enabled, months: v.months, day_of_month: Number(v.day_of_month), ai_tier: v.ai_tier } }); setSaved(true); onSaved(); }
    catch (e) { setError(e); }
  }
  return (
    <div aria-label="Quarterly schedule">
      <ErrorNotice error={error} />
      {saved && <Notice kind="success"><span role="status">Schedule saved.</span></Notice>}
      <div className="toolbar small">
        <label className="inline-check"><input type="checkbox" aria-label="Schedule enabled" checked={v.enabled} onChange={(e) => setV({ ...v, enabled: e.target.checked })} /> Scheduled runs enabled</label>
        <span>Months: {MONTHS.map((m, i) => (
          <label key={m} className="inline-check"><input type="checkbox" aria-label={`Run in ${m}`} checked={v.months.includes(i + 1)}
            onChange={(e) => setV({ ...v, months: e.target.checked ? [...v.months, i + 1].sort((a, b) => a - b) : v.months.filter((x) => x !== i + 1) })} /> {m}</label>))}</span>
        <label>Day <input aria-label="Schedule day" type="number" min={1} max={28} value={v.day_of_month} onChange={(e) => setV({ ...v, day_of_month: Number(e.target.value) })} /></label>
        <label>AI <select aria-label="Schedule AI tier" value={v.ai_tier} onChange={(e) => setV({ ...v, ai_tier: e.target.value })}><option value="">None (rules only)</option><option value="lite">Flash-Lite</option></select></label>
        <button type="button" className="btn btn-small" onClick={save}>Save schedule</button>
      </div>
      <p className="muted small">The host scheduler runs <code>manage.py run_scheduled_assessments</code> daily; at most one scheduled run per company and quarter.
        {s.updated_at ? ` Last changed ${formatDate(s.updated_at)} by ${s.updated_by}.` : ""}</p>
    </div>
  );
}

/** Parts processed per run (assessed, reused, failed), oldest left: one axis, stacked counts, legend + table view. */
function RunTrend({ runs }: { runs: Run[] }) {
  const rows = [...runs].slice(0, 12).reverse();
  const W = 640, H = 170, L = 32, B = 22, T = 10;
  const max = Math.max(1, ...rows.map((r) => r.done_count + r.reused_count + r.failed_count));
  const step = (W - L) / rows.length;
  const bw = Math.min(34, step * 0.56);
  const y = (v: number) => T + (H - T - B) * (1 - v / max);
  const ticks = Array.from(new Set([0, Math.round(max / 2), max]));
  const SERIES = [["done_count", "Assessed", "bar-assessed"], ["reused_count", "Unchanged (reused)", "bar-reused"], ["failed_count", "Failed", "bar-failed"]] as const;
  return (
    <figure className="run-trend">
      <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Parts processed in the last ${rows.length} runs`}>
        {ticks.map((t) => <g key={t}><line className={t ? "grid" : "axis"} x1={L} x2={W} y1={y(t)} y2={y(t)} /><text x={L - 6} y={y(t) + 4} textAnchor="end">{t}</text></g>)}
        {rows.map((r, i) => {
          const x = L + step * i + (step - bw) / 2;
          let base = 0;
          return (
            <g key={r.id} className="bar-group">
              <title>{`Run ${r.number} (${r.quarter}): ${r.done_count} assessed, ${r.reused_count} reused, ${r.failed_count} failed`}</title>
              <rect className="hit" x={L + step * i} y={T} width={step} height={H - T - B} />
              {SERIES.map(([k, , cls]) => {
                const v = r[k];
                if (!v) return null;
                const y0 = y(base), y1 = y(base + v);
                base += v;
                return <rect key={k} className={cls} x={x} y={y1} width={bw} height={Math.max(0, y0 - y1 - 2)} rx={3} />;
              })}
              <text x={x + bw / 2} y={H - 6} textAnchor="middle">{r.number}</text>
            </g>
          );
        })}
      </svg>
      <figcaption className="legend">
        {SERIES.map(([, l, cls]) => <span key={cls}><span className={`swatch ${cls}`} />{l}</span>)}
        <span className="muted">Run number on the axis; hover a bar for its counts.</span>
      </figcaption>
      <details className="small"><summary>Show as table</summary>
        <table className="table compact" aria-label="Parts processed per run">
          <thead><tr><th>Run</th><th>Quarter</th><th>Assessed</th><th>Reused</th><th>Failed</th></tr></thead>
          <tbody>{rows.map((r) => <tr key={r.id}><td>{r.number}</td><td>{r.quarter}</td><td>{r.done_count}</td><td>{r.reused_count}</td><td>{r.failed_count}</td></tr>)}</tbody>
        </table>
      </details>
    </figure>
  );
}

export function AssessmentDashboard() {
  const { can } = useAuth();
  const dash = useApi<Dash>("/intelligence/assessments/");
  const [selected, setSelected] = useState<string | null>(null);
  const detail = useApi<Detail>(selected ? `/intelligence/assessments/${selected}/` : null);
  const [tier, setTier] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const active = dash.data?.active;
  useEffect(() => {  // poll while a run is queued or running
    if (!active) return undefined;
    const t = window.setInterval(() => dash.reload(), 3000);
    return () => window.clearInterval(t);
  }, [active?.id, active?.status]);  // eslint-disable-line react-hooks/exhaustive-deps

  if (dash.loading && !dash.data) return <Loading />;
  if (dash.error || !dash.data) return <ErrorNotice error={dash.error} />;
  const d = dash.data;
  const shown = selected ? detail.data : d.latest;
  const s = shown?.summary;

  async function startRun() {
    setBusy(true); setError(null);
    try { await api("/intelligence/assessments/", { body: { ai_tier: tier } }); dash.reload(); } catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function act(run: Run, what: "retry" | "cancel") {
    setError(null);
    try { await api(`/intelligence/assessments/${run.id}/${what}/`, { body: {} }); dash.reload(); if (selected) detail.reload(); } catch (e) { setError(e); }
  }

  return (
    <>
      <AiWorkflow current="assessment" targets={{ inventory: "/inventory-import?tab=quality", classification: "/inventory-import?tab=intelligence",
        feasibility: "/inventory-import?tab=intelligence", commercial: "/inventory-import?tab=intelligence", recommendation: "/inventory-import?tab=intelligence",
        review: "/inventory-import?tab=intelligence", assessment: "/inventory-import?tab=assessment" }} />
      <Card title="Quarterly inventory assessment" actions={can("intelligence.assess") ? (
        <div className="toolbar">
          <label className="small">AI <select aria-label="Run AI tier" value={tier} onChange={(e) => setTier(e.target.value)}>
            <option value="">None (rules only)</option>{d.ai.enabled && <option value="lite">{d.ai.models.lite} (within limits)</option>}</select></label>
          <button type="button" className="btn btn-primary btn-small" disabled={busy || !!active} onClick={startRun}>{active ? "Run in progress…" : "Start assessment run"}</button>
        </div>) : undefined}>
        <Notice kind="warning"><span role="note">{d.statement}</span></Notice>
        <ErrorNotice error={error} />
        {active && <Notice kind="info"><span role="status" data-testid="active-run">Run {active.number} ({active.quarter}) is {active.status_label.toLowerCase()}:
          {" "}{active.done_count + active.reused_count} of {active.part_count} parts processed. The page updates automatically.</span></Notice>}
        {!shown ? <Empty>No completed assessment run yet.</Empty> : <>
          <p className="small" data-testid="shown-run">Run <strong>{shown.run.number}</strong> · {shown.run.quarter} · {shown.run.kind_label} · <Badge tone={TONE[shown.run.status]}>{shown.run.status_label}</Badge>
            {" "}· finished {formatDate(shown.run.finished_at)} · {shown.run.done_count} assessed, {shown.run.reused_count} unchanged (reused), {shown.run.failed_count} failed
            {shown.run.previous_run ? ` · compared with run ${shown.run.previous_run}` : ""}{shown.run.fault_injection ? " · test fault injection" : ""}
            {selected && <> · <button type="button" className="link-btn" onClick={() => setSelected(null)}>show latest</button></>}</p>
          {s && <div className="stat-row kpis" aria-label="Assessment dashboard">
            <Kpi id="total" label="Total parts" value={s.total_parts} sub={`${s.in_scope} in scope, ${s.outside_scope} outside`} />
            <Kpi id="assessed" label="Assessed / unassessed" value={`${s.assessed} / ${s.unassessed}`} />
            <Kpi id="insufficient" label="Insufficient technical data" value={s.insufficient_technical_data} />
            <Kpi id="am" label="Potential AM candidates" value={s.am_candidates} sub={`${s.am_specialist} need specialist assessment`} />
            <Kpi id="conventional" label="Potential conventional candidates" value={s.conventional_candidates} sub={`${s.conventional_specialist} need specialist assessment`} />
            <Kpi id="oem" label="OEM identity verified" value={`${s.oem.identity_verified} / ${s.assessed}`}
              sub={Object.values(s.oem.cost_evidence).map((x) => `${x.label}: ${x.count}`).join("; ")} />
            <Kpi id="obsolete" label="Potentially obsolete" value={s.potentially_obsolete} sub={`availability not documented: ${s.oem.availability_not_documented}`} />
            <Kpi id="backlog" label="Review backlog" value={s.review_backlog.total} sub={`${s.review_backlog.preliminary} preliminary, ${s.review_backlog.information_requested} information requested`} />
            <Kpi id="savings" label="Estimated vs verified savings" value={<><span className="saving-estimated" title="Estimated: provisional, not validated">{money(s.savings.estimated)}</span> <span className="muted">vs</span>{" "}
              <span className="saving-verified" title="Verified: qualified options with current quotations">{money(s.savings.verified)}</span></>}
              sub={`${s.savings.estimated_parts} estimated (provisional), ${s.savings.verified_parts} verified`} />
            <Kpi id="gaps" label="Open evidence gaps" value={s.evidence_gaps_total} sub={`expired OEM evidence: ${s.oem.with_expired_evidence} part(s)`} />
          </div>}
          {s && <p className="muted small">{s.savings.note}</p>}
          <h3 className="h-sub">Changes since the preceding assessment</h3>
          <Changes c={shown.comparison} />
          <h3 className="h-sub">Parts</h3>
          <Items d={shown} />
        </>}
      </Card>
      <Card title="Assessment run history">
        {d.runs.length > 1 && <RunTrend runs={d.runs} />}
        {d.runs.length === 0 ? <Empty>No runs yet.</Empty> : (
          <table className="table compact" aria-label="Assessment run history">
            <thead><tr><th>Run</th><th>Quarter</th><th>Kind</th><th>Status</th><th>Parts</th><th>Started / finished</th><th>Requested by</th><th>Reports</th><th /></tr></thead>
            <tbody>{d.runs.map((r) => (
              <tr key={r.id}>
                <td><button type="button" className="link-btn" onClick={() => setSelected(r.id)}>Run {r.number}</button>{r.previous_run ? <span className="muted small block">vs run {r.previous_run}</span> : null}</td>
                <td>{r.quarter}</td><td>{r.kind_label}{r.ai_tier ? ` · AI ${r.ai_tier}` : ""}</td><td><Badge tone={TONE[r.status]}>{r.status_label}</Badge></td>
                <td className="small">{r.part_count}: {r.done_count} assessed, {r.reused_count} reused, {r.failed_count} failed</td>
                <td className="small">{formatDate(r.started_at)}<div className="muted">{formatDate(r.finished_at)}</div></td><td className="small">{r.requested_by}</td>
                <td className="small">{["completed", "completed_with_errors"].includes(r.status) ? <>
                  <button type="button" className="link-btn" onClick={() => download(r, "xlsx", setError)}>Excel</button> · <button type="button" className="link-btn" onClick={() => download(r, "pdf", setError)}>PDF</button></> : "—"}</td>
                <td className="small">{can("intelligence.assess") && ["completed_with_errors", "running", "queued"].includes(r.status) && <button type="button" className="btn btn-small" onClick={() => act(r, "retry")}>{r.status === "completed_with_errors" ? "Retry failed parts" : "Resume"}</button>}
                  {can("intelligence.assess") && ["completed_with_errors", "running", "queued"].includes(r.status) && <button type="button" className="link-btn" onClick={() => act(r, "cancel")}>Cancel</button>}</td>
              </tr>))}</tbody>
          </table>
        )}
      </Card>
      {can("intelligence.assess") && <Card title="Quarterly schedule"><ScheduleForm s={d.schedule} onSaved={() => dash.reload()} /></Card>}
    </>
  );
}

type AdminRow = { company: string; latest_run: number | null; quarter: string; status: string; finished_at: string | null; active_run: boolean;
  counts: Record<string, number | null>; review_backlog: number | null; savings: { estimated: Money; verified: Money } };

export function AdminAssessmentSummary() {
  const q = useApi<{ companies: AdminRow[]; note: string }>("/admin/assessment-summary/");
  if (q.loading && !q.data) return <Loading />;
  if (q.error || !q.data) return <ErrorNotice error={q.error} />;
  return (
    <Card title="Inventory assessments (aggregate)">
      <p className="muted small">{q.data.note}</p>
      {q.data.companies.length === 0 ? <Empty>No assessment runs yet.</Empty> : (
        <table className="table compact" aria-label="Assessment summary by company">
          <thead><tr><th>Company</th><th>Latest run</th><th>Parts / assessed</th><th>Insufficient data</th><th>AM / conventional candidates</th><th>Potentially obsolete</th><th>Review backlog</th><th>Estimated / verified savings</th></tr></thead>
          <tbody>{q.data.companies.map((c) => (
            <tr key={c.company}><td>{c.company}{c.active_run && <Badge tone="info">run in progress</Badge>}</td>
              <td className="small">{c.latest_run ? `Run ${c.latest_run} · ${c.quarter} · ${c.status}` : "—"}<div className="muted">{formatDate(c.finished_at)}</div></td>
              <td>{c.counts.total_parts ?? "—"} / {c.counts.assessed ?? "—"}</td><td>{c.counts.insufficient_technical_data ?? "—"}</td>
              <td>{c.counts.am_candidates ?? "—"} / {c.counts.conventional_candidates ?? "—"}</td><td>{c.counts.potentially_obsolete ?? "—"}</td><td>{c.review_backlog ?? "—"}</td>
              <td className="small">{money(c.savings.estimated)} / {money(c.savings.verified)}</td></tr>))}</tbody>
        </table>
      )}
    </Card>
  );
}
