/**
 * Manufacturing cost estimate on an incoming request (Aries internal; decision of 16 Nov 2026): OEM purchase,
 * conventional manufacturing and 3D printing side by side, with feasibility, cost range, manpower and days, for Aries
 * to choose a route. Gemini estimates the work and finds web prices (with their sources); the server calculates the money
 * from Aries' rates. Engineers correct any figure (a new version); the Aries Admin or Manager chooses the route.
 */
import { Fragment, useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Badge, ErrorNotice, Loading, Notice, formatDate } from "./ui";

type Source = { source?: string; url?: string; title?: string; note?: string };
type Person = { role: string; label: string; hours: number; rate: number; cost: number };
type RouteResult = {
  label: string; feasible: string; reason: string; rule_status: string; process?: string; material?: string; material_kg?: number;
  material_price_per_kg?: number; material_price_source?: Source; machine?: string; machine_hours?: number; manpower: Person[];
  manpower_hours: number; days: Record<string, number>; total_days: number; risks: string[]; assumptions?: string[]; note?: string;
  price_per_part?: number | null; price_source?: Source;
  cost: { total: number; low: number; high: number; per_part: number; material?: number; machine?: number; manpower?: number;
    extras?: number; overhead?: number; margin?: number; shipping?: number } | null;
};
type Manpower = { role: string; hours_per_part: number; hours_per_batch: number };
type MakeWork = { feasible: string; reason: string; process: string; material: string; kg_per_part: number; machine: string;
  machine_hours_per_part: number; setup_hours: number; manpower: Manpower[]; heat_treatment: boolean; ndt: boolean;
  days: Record<string, number>; risks: string[]; assumptions: string[] };
type Work = { oem: { feasible: string; reason: string; lead_days: number; risks: string[] }; conventional: MakeWork; additive: MakeWork };
type Prices = { materials: Record<string, Source & { price_per_kg: number }>; oem: Source & { price_per_part?: number } };
type Estimate = {
  id: string; version: number; mode: string; mode_label: string; quantity: number; work: Work; prices: Prices; note: string;
  result: { currency: string; quantity: number; routes: Record<string, RouteResult>; cheapest: string; fastest: string };
  ai: { model?: string; confidence?: number; missing_information?: string[]; price_search?: { ok: boolean; sources: Source[] }; adjusted_from_version?: number };
  created_at: string; created_by: string; chosen_route: string; chosen_note: string; chosen_at: string | null; chosen_by: string;
};
type Data = {
  latest: Estimate | null; versions: { version: number; mode: string; created_at: string; created_by: string; chosen_route: string }[];
  ai: { enabled: boolean; reason: string }; can_prepare: boolean; can_choose: boolean;
  roles: Record<string, string>; machines: Record<string, string>; routes: Record<string, string>;
};

const ORDER = ["oem", "conventional", "additive"] as const;
const FEASIBLE: Record<string, [string, "success" | "warning" | "danger" | "neutral"]> = {
  yes: ["Feasible", "success"], with_review: ["Feasible with review", "warning"], no: ["Not feasible", "danger"], unknown: ["Not known", "neutral"],
};
const DAY_LABEL: Record<string, string> = { preparation: "Preparation", production: "Production", post_processing: "Post-processing",
  inspection: "Inspection", shipping: "Shipping" };
const SOURCE_LABEL: Record<string, string> = { web_search: "Web search", rate_table: "Aries rate table", rate_table_default: "Aries default price",
  quotation: "Quotation", engineer: "Engineer" };

function useMoney(currency: string) {
  let f: Intl.NumberFormat;
  try {
    f = new Intl.NumberFormat(undefined, { style: "currency", currency, maximumFractionDigits: 0 });
  } catch {
    f = new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 });
  }
  return (n: number | null | undefined) => (n == null ? "—" : f.format(n));
}

function SourceLink({ s }: { s?: Source }) {
  if (!s || !s.source) return null;
  const text = SOURCE_LABEL[s.source] ?? s.source;
  return s.url ? <a href={s.url} target="_blank" rel="noreferrer noopener" className="small">{s.title || text} ↗</a>
    : <span className="muted small">{s.note || text}</span>;
}

export function CostEstimateCard({ envelopeId, locked = false, onChange }: { envelopeId: string; locked?: boolean; onChange?: () => void }) {
  const base = `/operator/requests/${envelopeId}/estimate/`;
  const d = useApi<Data>(base);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [editing, setEditing] = useState(false);
  const data = d.data;

  async function post(body: Record<string, unknown>, label: string) {
    setBusy(label);
    setError(null);
    try {
      d.setData(await api<Data>(base, { body }));
      if (body.action === "choose") onChange?.(); // the request page shows the chosen route and enables release
      return true;
    } catch (err) {
      setError(err);
      return false;
    } finally {
      setBusy("");
    }
  }

  const e = data?.latest;
  return (
    <div className="card cost-estimate">
      <div className="card-head">
        <h2>Cost estimate <span className="muted small">Aries internal · not shown to the client</span></h2>
        {data && data.can_prepare && !editing && (
          <span className="toolbar wrap">
            {data.ai.enabled && (
              <button type="button" className="btn btn-primary" disabled={!!busy} aria-busy={busy === "run"} onClick={() => void post({ action: "run" }, "run")}>
                {busy === "run" ? "Gemini is estimating…" : e ? "Estimate again with Gemini" : "Estimate with Gemini"}</button>
            )}
            {!e && <button type="button" className="btn" disabled={!!busy} onClick={() => void post({ action: "manual" }, "manual")}>Fill in manually</button>}
            {e && <button type="button" className="btn" disabled={!!busy} onClick={() => setEditing(true)}>Edit figures</button>}
          </span>
        )}
      </div>
      <ErrorNotice error={d.error ?? error} />
      {d.loading && !data ? <Loading label="Loading estimate…" /> : data && (
        <>
          {!data.ai.enabled && data.can_prepare && <p className="muted small">Gemini is not available: {data.ai.reason} You can fill in the estimate manually.</p>}
          {busy === "run" && <Notice>Gemini is estimating the work and looking up prices on the web. This can take up to a minute.</Notice>}
          {!e ? (
            <p className="muted">No estimate yet. {data.can_prepare ? "Estimate the cost of OEM purchase, conventional manufacturing and 3D printing for this request." : "An Aries Engineer, Admin or Manager prepares it."}</p>
          ) : editing ? (
            <EstimateEditor e={e} data={data} busy={busy === "adjust"} onCancel={() => setEditing(false)}
              onSave={async (work, prices, note) => { if (await post({ action: "adjust", work, prices, note }, "adjust")) setEditing(false); }} />
          ) : (
            <Comparison e={e} data={data} busy={busy} locked={locked} onChoose={(route) => {
              const note = window.prompt(`Choose ${data.routes[route]} for this order? Why this route (e.g. "cheaper, only one day slower"):`, "");
              if (note !== null) void post({ action: "choose", route, note }, "choose");
            }} />
          )}
          {data.versions.length > 1 && (
            <details className="estimate-versions">
              <summary className="small">Earlier versions ({data.versions.length - 1})</summary>
              <ul className="small">{data.versions.slice(1).map((v) => (
                <li key={v.version}>v{v.version} · {v.mode} · {v.created_by} · {formatDate(v.created_at)}{v.chosen_route ? ` · chosen: ${data.routes[v.chosen_route]}` : ""}</li>
              ))}</ul>
            </details>
          )}
        </>
      )}
    </div>
  );
}

function Comparison({ e, data, busy, locked, onChoose }: { e: Estimate; data: Data; busy: string; locked: boolean; onChoose: (route: string) => void }) {
  const money = useMoney(e.result.currency);
  const routes = ORDER.filter((r) => e.result.routes[r]);
  const row = (title: string, cell: (r: RouteResult, key: string) => ReactNode) => (
    <tr><th scope="row">{title}</th>{routes.map((k) => <td key={k}>{cell(e.result.routes[k], k)}</td>)}</tr>
  );
  return (
    <>
      <p className="muted small">
        Version {e.version} · {e.mode_label} · quantity {e.result.quantity} · {e.created_by} · {formatDate(e.created_at)}
        {e.ai.confidence != null && ` · Gemini confidence ${Math.round(e.ai.confidence * 100)} %`} · rates in {e.result.currency}{" "}
        (<Link to="/estimate-rates">Estimate rates</Link>)
      </p>
      {!e.chosen_route && data.can_choose && !locked && (
        <Notice>Compare the routes and click <strong>Choose this route</strong> under the one Aries will use, with the reason. The order can be released after that.</Notice>
      )}
      {locked && e.chosen_route && <p className="muted small">The order is released: production goes ahead on the chosen route.</p>}
      {e.chosen_route && (
        <Notice kind="success">Route chosen: <strong>{data.routes[e.chosen_route]}</strong> by {e.chosen_by}
          {e.chosen_at ? ` · ${formatDate(e.chosen_at)}` : ""}{e.chosen_note ? ` · ${e.chosen_note}` : ""}</Notice>
      )}
      <div className="table-scroll">
        <table className="table estimate-table" aria-label="Cost estimate by route">
          <thead>
            <tr><th />{routes.map((k) => (
              <th key={k} className={e.chosen_route === k ? "is-chosen" : ""}>
                {e.result.routes[k].label}{" "}
                {e.result.cheapest === k && <Badge tone="success">Cheapest</Badge>}{" "}
                {e.result.fastest === k && <Badge tone="info">Fastest</Badge>}
              </th>
            ))}</tr>
          </thead>
          <tbody>
            {row("Feasible", (r) => {
              const [t, tone] = FEASIBLE[r.feasible] ?? FEASIBLE.unknown;
              return <><Badge tone={tone}>{t}</Badge><div className="small">{r.reason}</div>{r.rule_status && <div className="muted small">Rules: {r.rule_status}</div>}</>;
            })}
            {row("Estimated cost", (r) => r.cost
              ? <><strong className="estimate-total">{money(r.cost.low)} – {money(r.cost.high)}</strong>
                <div className="muted small">Estimate {money(r.cost.total)} · {money(r.cost.per_part)} per part</div></>
              : <span className="muted small">{r.note || "No price"}</span>)}
            {row("Cost breakdown", (r, k) => !r.cost ? "—" : k === "oem"
              ? <dl className="estimate-dl small"><dt>Part price</dt><dd>{money(r.price_per_part)} × {e.result.quantity}</dd><dt>Shipping</dt><dd>{money(r.cost.shipping)}</dd>
                <dt>Source</dt><dd><SourceLink s={r.price_source} /></dd></dl>
              : <dl className="estimate-dl small">
                <dt>Material</dt><dd>{money(r.cost.material)} <span className="muted">({r.material_kg} kg × {money(r.material_price_per_kg)}/kg)</span></dd>
                <dt>Machine</dt><dd>{money(r.cost.machine)} <span className="muted">({r.machine_hours} h)</span></dd>
                <dt>Manpower</dt><dd>{money(r.cost.manpower)}</dd>
                <dt>Extras</dt><dd>{money(r.cost.extras)}</dd>
                <dt>Overhead</dt><dd>{money(r.cost.overhead)}</dd>
                <dt>Margin</dt><dd>{money(r.cost.margin)}</dd>
              </dl>)}
            {row("Manpower", (r, k) => k === "oem" ? <span className="muted small">None (purchase)</span> : (
              <><strong>{r.manpower_hours} h</strong>
                <ul className="estimate-list small">{r.manpower.map((p) => <li key={p.role}>{p.label}: {p.hours} h</li>)}</ul></>
            ))}
            {row("Days", (r, k) => (
              <><strong>{r.total_days} days</strong>
                {k !== "oem" && <ul className="estimate-list small">{Object.keys(DAY_LABEL).filter((dk) => r.days[dk]).map((dk) => <li key={dk}>{DAY_LABEL[dk]}: {r.days[dk]}</li>)}</ul>}</>
            ))}
            {row("Process and material", (r, k) => k === "oem" ? "—" : (
              <span className="small">{r.process || "—"}<br />{r.material} · {r.machine}<br /><SourceLink s={r.material_price_source} /></span>
            ))}
            {row("Risks", (r) => r.risks.length ? <ul className="estimate-list small">{r.risks.map((x, i) => <li key={i}>{x}</li>)}</ul> : <span className="muted small">None stated</span>)}
            {data.can_choose && !locked && row("", (r, k) => (
              <button type="button" className={`btn btn-small ${e.chosen_route === k ? "btn-primary" : ""}`} disabled={r.feasible === "no" || !!busy}
                onClick={() => onChoose(k)}>{e.chosen_route === k ? "Chosen" : "Choose this route"}</button>
            ))}
          </tbody>
        </table>
      </div>
      {(e.ai.missing_information?.length ?? 0) > 0 && <p className="small"><strong>Missing information:</strong> {e.ai.missing_information!.join("; ")}</p>}
      {(e.ai.price_search?.sources?.length ?? 0) > 0 && (
        <p className="small"><strong>Websites used for prices:</strong>{" "}
          {e.ai.price_search!.sources.map((s, i) => <Fragment key={i}>{i ? " · " : ""}<a href={s.url} target="_blank" rel="noreferrer noopener">{s.title || "source"} ↗</a></Fragment>)}</p>
      )}
      {e.ai.price_search && !e.ai.price_search.ok && <p className="muted small">The web price search failed; material prices come from the Aries rate table.</p>}
      <p className="muted small">Estimates are indicative: Gemini estimates the work and finds public prices; the cost is calculated from Aries' rates.
        A supplier quotation replaces an estimate. Correct any figure with Edit figures.</p>
    </>
  );
}

function NumberInput({ value, onChange, label, step = "0.1" }: { value: number; onChange: (n: number) => void; label: string; step?: string }) {
  return <input type="number" min={0} step={step} aria-label={label} value={Number.isFinite(value) ? value : 0}
    onChange={(ev) => onChange(ev.target.value === "" ? 0 : Number(ev.target.value))} />;
}

function EstimateEditor({ e, data, busy, onSave, onCancel }: {
  e: Estimate; data: Data; busy: boolean; onSave: (w: Work, p: Prices, note: string) => void; onCancel: () => void;
}) {
  const [w, setW] = useState<Work>(() => JSON.parse(JSON.stringify(e.work)));
  const [prices, setPrices] = useState<Prices>(() => ({ materials: { ...(e.prices.materials ?? {}) }, oem: { ...(e.prices.oem ?? {}) } }));
  const [note, setNote] = useState("");
  useEffect(() => setW(JSON.parse(JSON.stringify(e.work))), [e.id, e.work]);
  const setRoute = (k: "conventional" | "additive", patch: Partial<MakeWork>) => setW({ ...w, [k]: { ...w[k], ...patch } });
  const matPrice = (m: string) => prices.materials[m]?.price_per_kg;
  const setMatPrice = (m: string, v: number | null) => {
    const next = { ...prices.materials };
    if (v == null || !m) delete next[m];
    else next[m] = { ...(next[m] ?? {}), price_per_kg: v, source: next[m]?.source === "web_search" && next[m]?.price_per_kg === v ? "web_search" : "engineer" };
    setPrices({ ...prices, materials: next });
  };
  const feasSelect = (value: string, onChange: (v: string) => void, lbl: string) => (
    <select aria-label={lbl} value={value} onChange={(ev) => onChange(ev.target.value)}>
      {Object.entries(FEASIBLE).map(([v, [t]]) => <option key={v} value={v}>{t}</option>)}
    </select>
  );
  return (
    <form className="estimate-editor" onSubmit={(ev) => { ev.preventDefault(); onSave(w, prices, note); }}>
      <p className="muted small">Correct the work and prices; the cost is recalculated with the Aries rates and saved as a new version (v{e.version + 1}).</p>
      <fieldset className="fieldset">
        <legend>OEM purchase</legend>
        <div className="form-grid">
          <label className="field"><span>Feasible</span>{feasSelect(w.oem.feasible, (v) => setW({ ...w, oem: { ...w.oem, feasible: v } }), "OEM feasible")}</label>
          <label className="field"><span>Lead time (days)</span><NumberInput label="OEM lead time" value={w.oem.lead_days} onChange={(n) => setW({ ...w, oem: { ...w.oem, lead_days: n } })} step="1" /></label>
          <label className="field"><span>Price per part ({e.result.currency})</span>
            <input type="number" min={0} step="0.01" aria-label="OEM price per part" value={prices.oem.price_per_part ?? ""}
              onChange={(ev) => setPrices({ ...prices, oem: ev.target.value === "" ? {} : { ...prices.oem, price_per_part: Number(ev.target.value), source: "engineer" } })} /></label>
          <label className="field span-2"><span>Reason</span><input value={w.oem.reason} onChange={(ev) => setW({ ...w, oem: { ...w.oem, reason: ev.target.value } })} /></label>
        </div>
      </fieldset>
      {(["conventional", "additive"] as const).map((k) => {
        const r = w[k];
        return (
          <fieldset key={k} className="fieldset">
            <legend>{data.routes[k]}</legend>
            <div className="form-grid">
              <label className="field"><span>Feasible</span>{feasSelect(r.feasible, (v) => setRoute(k, { feasible: v }), `${k} feasible`)}</label>
              <label className="field"><span>Process</span><input value={r.process} onChange={(ev) => setRoute(k, { process: ev.target.value })} /></label>
              <label className="field"><span>Material bought</span><input value={r.material} onChange={(ev) => setRoute(k, { material: ev.target.value })} /></label>
              <label className="field"><span>Material price per kg ({e.result.currency})</span>
                <input type="number" min={0} step="0.01" aria-label={`${k} material price per kg`} value={matPrice(r.material) ?? ""}
                  placeholder="From the rate table" onChange={(ev) => setMatPrice(r.material, ev.target.value === "" ? null : Number(ev.target.value))} /></label>
              <label className="field"><span>Material per part (kg)</span><NumberInput label={`${k} kg per part`} value={r.kg_per_part} onChange={(n) => setRoute(k, { kg_per_part: n })} /></label>
              <label className="field"><span>Machine</span>
                <select value={r.machine} onChange={(ev) => setRoute(k, { machine: ev.target.value })}>
                  {Object.entries(data.machines).map(([v, t]) => <option key={v} value={v}>{t}</option>)}
                </select></label>
              <label className="field"><span>Machine hours per part</span><NumberInput label={`${k} machine hours`} value={r.machine_hours_per_part} onChange={(n) => setRoute(k, { machine_hours_per_part: n })} /></label>
              <label className="field"><span>Set-up hours (order)</span><NumberInput label={`${k} set-up hours`} value={r.setup_hours} onChange={(n) => setRoute(k, { setup_hours: n })} /></label>
              <label className="inline-check"><input type="checkbox" checked={r.heat_treatment} onChange={(ev) => setRoute(k, { heat_treatment: ev.target.checked })} /> Heat treatment</label>
              <label className="inline-check"><input type="checkbox" checked={r.ndt} onChange={(ev) => setRoute(k, { ndt: ev.target.checked })} /> NDT</label>
            </div>
            <div className="estimate-sub">
              <strong className="small">Manpower</strong>
              {r.manpower.map((m, i) => (
                <div key={i} className="estimate-row">
                  <select aria-label={`${k} role ${i + 1}`} value={m.role} onChange={(ev) => setRoute(k, { manpower: r.manpower.map((x, j) => j === i ? { ...x, role: ev.target.value } : x) })}>
                    {Object.entries(data.roles).map(([v, t]) => <option key={v} value={v}>{t}</option>)}
                  </select>
                  <label className="small">h/part <NumberInput label={`${k} role ${i + 1} hours per part`} value={m.hours_per_part} onChange={(n) => setRoute(k, { manpower: r.manpower.map((x, j) => j === i ? { ...x, hours_per_part: n } : x) })} /></label>
                  <label className="small">h/order <NumberInput label={`${k} role ${i + 1} hours per order`} value={m.hours_per_batch} onChange={(n) => setRoute(k, { manpower: r.manpower.map((x, j) => j === i ? { ...x, hours_per_batch: n } : x) })} /></label>
                  <button type="button" className="btn btn-small btn-ghost" onClick={() => setRoute(k, { manpower: r.manpower.filter((_, j) => j !== i) })}>Remove</button>
                </div>
              ))}
              {r.manpower.length < 8 && <button type="button" className="btn btn-small" onClick={() => setRoute(k, { manpower: [...r.manpower, { role: Object.keys(data.roles)[0], hours_per_part: 0, hours_per_batch: 0 }] })}>Add role</button>}
            </div>
            <div className="estimate-sub">
              <strong className="small">Days</strong>
              <div className="estimate-row">{Object.keys(DAY_LABEL).map((dk) => (
                <label key={dk} className="small">{DAY_LABEL[dk]} <NumberInput label={`${k} ${dk} days`} step="0.5" value={r.days[dk] ?? 0}
                  onChange={(n) => setRoute(k, { days: { ...r.days, [dk]: n } })} /></label>
              ))}</div>
            </div>
            <label className="field"><span>Reason / notes</span><input value={r.reason} onChange={(ev) => setRoute(k, { reason: ev.target.value })} /></label>
          </fieldset>
        );
      })}
      <label className="field"><span>What changed (saved with the version)</span><input maxLength={500} value={note} onChange={(ev) => setNote(ev.target.value)} placeholder="e.g. supplier quotation for bar stock" /></label>
      <div className="form-actions">
        <button type="button" className="btn btn-ghost" onClick={onCancel}>Cancel</button>
        <button className="btn btn-primary" disabled={busy} aria-busy={busy}>{busy ? "Saving…" : "Save and recalculate"}</button>
      </div>
    </form>
  );
}
