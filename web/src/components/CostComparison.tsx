/**
 * Cost & lead-time comparison (CN-007 Phase 4), Aries-internal, inside the Part Intelligence / Manufacturing
 * Feasibility workspace. OEM procurement, additive and conventional manufacturing side by side for one quantity and
 * reporting currency. The server calculates everything (deterministic Python); this screen edits scenarios, previews
 * what-if quantities without saving, and stores new versions. Every figure shows its data source. Technical status
 * comes from the Phase 3 feasibility version. No recommendation, approval or release is made here.
 */
import { Fragment, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError, api } from "../api/client";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { AiGate, type AiStatus, usd } from "./PartIntelligence";
import { Badge, Card, Empty, ErrorNotice, Loading, Notice, formatDate } from "./ui";

type Tone = "neutral" | "info" | "success" | "warning" | "danger";
type AltKey = "oem" | "additive" | "conventional";
const ALTS: [AltKey, string][] = [["oem", "A. OEM procurement"], ["additive", "B. Additive manufacturing"], ["conventional", "C. Conventional manufacturing"]];
type Line = { key: string; label: string; category: string; basis?: string; source?: string; source_label: string; reference?: string; note?: string;
  amount?: string | null; currency?: string; percent?: string | null; multiplier?: number; reporting_amount?: string | null; reporting_unit_amount?: string | null;
  valid_until?: string; expired?: boolean; missing_rate?: boolean; not_applicable: boolean; conversion?: { rate: string; inverse: boolean; rate_date: string; source: string } | null };
type Tech = { status: string; status_label: string; label: string; qualified: boolean; excluded: boolean; corrected_by_review: boolean; feasibility_version: number };
type AltResult = { key: AltKey; label: string; required_quantity: number; ordered_quantity: number; moq: number; order_multiple: number; qualification_units: number;
  surplus_units: number; lines: Line[]; categories: Record<string, { label: string; amount: string | null }>; one_time_total: string | null;
  quantity_dependent_total: string | null; duties_total: string | null; complete: boolean; total: string | null; known_costs_total: string | null;
  effective_unit_cost: string | null; cost_per_ordered_unit: string | null; setup_tooling_per_usable_unit: string | null; missing_inputs: string[]; warnings: string[];
  exchange_rates_used: { from: string; to: string; rate: string; inverse: boolean; rate_date: string; source: string }[]; confidence: string;
  explanation?: string[];
  lead_time: { components: { key: string; label: string; days: number | null; source_label: string; not_applicable: boolean; quotation_validity?: { expired: boolean; unknown: boolean; valid_until: string | null } }[]; total_days: number | null; confidence: string; assumption: string };
  technical: Tech; comparison: { baseline: string; baseline_label: string; savings: string | null; savings_percent: string | null;
    lead_time_difference_days: number | null; provisional: boolean; reason: string } };
type Results = { method_version: string; as_of: string; quantity: number; reporting_currency: string; baseline: AltKey;
  alternatives: Record<AltKey, AltResult>; exchange_rates: { from: string; to: string; rate: string; rate_date: string; source: string }[]; statement: string };
type AiNotes = { cost_drivers: string[]; assumptions_to_verify: string[]; missing_inputs: string[]; lead_time_considerations: string[]; uncertainty: string };
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Scenario = any;
export type Comparison = { id: string; version: number; name: string; synthetic: boolean; method_version: string; quantity: number; reporting_currency: string;
  as_of: string; feasibility_version: number; feasibility_superseded: boolean; project: string; passport_number: string; derived_from_version: number | null;
  inputs: Scenario; technical: Record<AltKey, Tech>; results: Results; ai_status: string; ai_status_label: string; created_at: string; created_by_name: string;
  ai: { model?: string; model_version?: string; response?: Partial<Record<AltKey, AiNotes>> & { general_notes?: string[]; confidence?: number }; removed?: string[];
    usage?: { prompt_tokens: number; output_tokens: number; cost_usd: number | null }; error_code?: string; error_message?: string };
  ai_consistency?: { alternative: string; recorded: string; stated: string; sentence: string }[] };
type View = { ai: AiStatus; feasibility: { id: string; version: number; technical: Record<AltKey, Tech> } | null; comparisons: Comparison[]; template: Scenario;
  labels: { sources: Record<string, string>; costs: Record<string, string>; lead: Record<string, string> }; statement: string };

const SOURCE_TONE: Record<string, Tone> = { quotation: "success", historical: "info", engineering_estimate: "warning", ai_estimate: "danger", missing: "neutral" };
const money = (v: string | null | undefined, cur: string) => (v == null ? "—" : `${cur} ${Number(v).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x)) as T;

function FieldErrors({ error }: { error: unknown }) {
  const errs = error instanceof ApiError ? (error.details?.errors as { field: string; message: string }[] | undefined) : undefined;
  if (!errs?.length) return <ErrorNotice error={error} />;
  return (
    <div className="notice notice-error" role="alert"><strong>{(error as ApiError).message}</strong>
      <ul>{errs.map((e) => <li key={e.field + e.message}><code>{e.field}</code>: {e.message}</li>)}</ul></div>
  );
}

function AltColumn({ title, a, cur, notes }: { title: string; a: AltResult; cur: string; notes?: AiNotes }) {
  const c = a.comparison;
  return (
    <section className="card feasibility-panel" aria-label={title} data-testid={`cost-${a.key}`}>
      <h3 className="h-sub">{title}</h3>
      <p><Badge tone={a.technical.excluded ? "danger" : a.technical.qualified ? "info" : "warning"}>{a.technical.label}</Badge>
        <span className="muted small block">Feasibility v{a.technical.feasibility_version}{a.technical.corrected_by_review ? " (corrected in technical review)" : ""}</span></p>
      <table className="table compact cost-lines" aria-label={`${title} cost breakdown`}>
        <thead><tr><th>Component · entered · source</th><th className="num">{cur}</th></tr></thead>
        <tbody>
          {a.lines.map((l) => (
            <tr key={l.key}>
              <td><strong>{l.label}</strong>{l.basis && <span className="muted"> · {l.basis}{l.multiplier && l.multiplier > 1 ? ` × ${l.multiplier}` : ""}</span>}
                {!l.not_applicable && <span className="block">{l.percent != null ? `${l.percent}%` : l.amount != null ? `${l.currency} ${l.amount}` : "no figure"}
                  {l.conversion && <span className="muted"> @ {l.conversion.rate}{l.conversion.inverse ? " (inverse)" : ""}, {l.conversion.rate_date}</span>}</span>}
                <span className="block">{l.not_applicable ? <span className="muted">Not applicable</span> : <Badge tone={SOURCE_TONE[l.source ?? "missing"]}>{l.source_label}</Badge>}
                  {l.expired && <> <Badge tone="danger">quotation expired</Badge></>}{l.missing_rate && <> <Badge tone="danger">no exchange rate</Badge></>}</span>
                {l.reference && <span className="muted block">{l.reference}{l.valid_until ? ` · valid until ${l.valid_until}` : ""}</span>}</td>
              <td className="num">{l.not_applicable ? "—" : l.reporting_amount == null ? <span className="muted">missing</span> : money(l.reporting_amount, "").trim()}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <dl className="facts small" aria-label={`${title} totals`}>
        {CATEGORY_ORDER.filter((k) => a.categories[k]).map((k) => <Fragment key={k}><dt>{a.categories[k].label}</dt><dd>{money(a.categories[k].amount, cur)}</dd></Fragment>)}
        <dt>One-time / quantity-dependent</dt><dd>{money(a.one_time_total, cur)} / {money(a.quantity_dependent_total, cur)}</dd>
        <dt><strong>Total landed / project cost</strong></dt><dd data-testid={`total-${a.key}`}><strong>{a.complete ? money(a.total, cur) : "Incomplete"}</strong>
          {!a.complete && <span className="muted block">Known costs so far: {money(a.known_costs_total, cur)}</span>}</dd>
        <dt><strong>Effective cost per usable unit</strong></dt><dd><strong>{money(a.effective_unit_cost, cur)}</strong></dd>
        <dt>Cost per ordered unit</dt><dd>{money(a.cost_per_ordered_unit, cur)}</dd>
        <dt>Quantities</dt><dd>{a.required_quantity} required · {a.ordered_quantity} ordered (MOQ {a.moq}{a.order_multiple > 1 ? `, multiple ${a.order_multiple}` : ""}
          {a.qualification_units ? `, ${a.qualification_units} for qualification` : ""}){a.surplus_units > 0 ? ` · ${a.surplus_units} surplus` : ""}</dd>
        <dt>Lead time</dt><dd data-testid={`lead-${a.key}`}>{a.lead_time.total_days == null ? "Incomplete" : `${a.lead_time.total_days} days`}
          <span className="muted block">{a.lead_time.components.map((x) => `${x.label}: ${x.not_applicable ? "n/a" : x.days == null ? "missing" : `${x.days} d (${x.source_label}${x.quotation_validity?.expired ? `, quotation expired ${x.quotation_validity.valid_until}` : x.quotation_validity?.unknown ? ", no validity date" : ""})`}`).join("; ")}</span></dd>
        <dt>Data confidence</dt><dd>{a.confidence}<span className="muted block">Lead time: {a.lead_time.confidence}</span></dd>
        <dt>Difference vs {c.baseline_label}</dt><dd data-testid={`savings-${a.key}`}>{c.reason === "Baseline" ? "Baseline" : c.savings == null ? <span className="muted">{c.reason}</span> : <>
          {Number(c.savings) >= 0 ? "Saves " : "Costs "}{money(String(Math.abs(Number(c.savings))), cur)} ({Math.abs(Number(c.savings_percent)).toFixed(1)}%{Number(c.savings) >= 0 ? " lower" : " higher"})
          {c.provisional && <Badge tone="warning">provisional: not technically qualified</Badge>}</>}
          {c.lead_time_difference_days != null && <span className="block">Lead time {c.lead_time_difference_days > 0 ? "+" : ""}{c.lead_time_difference_days} days</span>}</dd>
      </dl>
      {a.explanation && a.explanation.length > 0 && (
        <details className="small"><summary>How these figures are calculated</summary>
          <ol className="small" aria-label={`${title} calculation`}>{a.explanation.map((x) => <li key={x}>{x}</li>)}</ol></details>)}
      {a.warnings.length > 0 && <ul className="plain-list small" aria-label={`${title} warnings`}>{a.warnings.map((w) => <li key={w}><Badge tone="danger">warning</Badge> {w}</li>)}</ul>}
      <h4 className="h-mini">Missing inputs</h4>
      {a.missing_inputs.length ? <ul className="plain-list small" aria-label={`${title} missing inputs`}>{a.missing_inputs.map((m) => <li key={m}>{m}</li>)}</ul>
        : <p className="muted small">None.</p>}
      {notes && (
        <div className="ai-suggestion small">
          <p><Badge tone="info">AI notes · preliminary, not verified</Badge> uncertainty: <strong>{notes.uncertainty}</strong></p>
          <ul className="plain-list" aria-label={`${title} AI notes`}>{[...notes.cost_drivers.map((x) => `Driver: ${x}`), ...notes.assumptions_to_verify.map((x) => `Verify: ${x}`),
            ...notes.missing_inputs.map((x) => `Missing: ${x}`), ...notes.lead_time_considerations.map((x) => `Lead time: ${x}`)].map((x) => <li key={x}>{x}</li>)}</ul>
        </div>
      )}
    </section>
  );
}

function ResultsView({ r, notes }: { r: Results; notes?: Comparison["ai"]["response"] }) {
  return <>
    <div className="grid-3 feasibility-grid">
      {ALTS.map(([k, t]) => <AltColumn key={k} title={t} a={r.alternatives[k]} cur={r.reporting_currency} notes={notes?.[k] as AiNotes | undefined} />)}
    </div>
    <p className="muted small">Exchange rates (entered, dated; never assumed): {r.exchange_rates.length ? r.exchange_rates.map((x) => `1 ${x.from} = ${x.rate} ${x.to} (${x.rate_date}, ${x.source})`).join("; ") : "none"}.
      {" "}Method {r.method_version} · quotation validity checked on {r.as_of}. Effective cost per usable unit = total ÷ required quantity; MOQ surplus is paid for but not counted.</p>
  </>;
}

// stored as JSONB, which does not keep key order: show the categories in calculation order
const CATEGORY_ORDER = ["material_production", "setup_tooling", "testing_qualification", "logistics", "duties_taxes"];
const COMP_KEYS = ["unit_cost", "post_processing", "engineering_setup", "tooling", "testing_qualification", "logistics"];

function ScenarioForm({ draft, setDraft, labels }: { draft: Scenario; setDraft: (s: Scenario) => void; labels: View["labels"] }) {
  const set = (path: (string | number)[], value: unknown) => {
    const next = clone(draft);
    let t = next;
    path.slice(0, -1).forEach((k) => { t = t[k]; });
    t[path[path.length - 1]] = value;
    setDraft(next);
  };
  const src = (p: (string | number)[], v: string, name: string) => (
    <select aria-label={`${name} source`} value={v} onChange={(e) => set(p, e.target.value)}>
      {Object.entries(labels.sources).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
    </select>
  );
  return (
    <div className="scenario-form" aria-label="Scenario inputs">
      <div className="toolbar">
        <label className="small">Scenario name <input aria-label="Scenario name" value={draft.name} onChange={(e) => set(["name"], e.target.value)} /></label>
        <label className="small">Quantity <input aria-label="Scenario quantity" type="number" min={1} value={draft.quantity} onChange={(e) => set(["quantity"], e.target.value)} /></label>
        <label className="small">Reporting currency <input aria-label="Reporting currency" maxLength={3} size={4} value={draft.reporting_currency} onChange={(e) => set(["reporting_currency"], e.target.value.toUpperCase())} /></label>
        <label className="small">Baseline <select aria-label="Baseline" value={draft.baseline} onChange={(e) => set(["baseline"], e.target.value)}>
          {ALTS.map(([k, t]) => <option key={k} value={k}>{t}</option>)}</select></label>
        <label className="small inline-check"><input type="checkbox" aria-label="Synthetic test data" checked={!!draft.synthetic} onChange={(e) => set(["synthetic"], e.target.checked)} /> Synthetic test data</label>
      </div>
      <h4 className="h-mini">Exchange rates (explicit and dated)</h4>
      <table className="table compact" aria-label="Exchange rates">
        <thead><tr><th>1 unit of</th><th>=</th><th>of</th><th>Rate date</th><th>Source</th><th /></tr></thead>
        <tbody>{draft.exchange_rates.map((r: Scenario, i: number) => (
          <tr key={i}>
            <td><input aria-label={`Rate ${i + 1} from`} size={4} value={r.from} onChange={(e) => set(["exchange_rates", i, "from"], e.target.value.toUpperCase())} /></td>
            <td><input aria-label={`Rate ${i + 1} rate`} size={8} value={r.rate} onChange={(e) => set(["exchange_rates", i, "rate"], e.target.value)} /></td>
            <td><input aria-label={`Rate ${i + 1} to`} size={4} value={r.to} onChange={(e) => set(["exchange_rates", i, "to"], e.target.value.toUpperCase())} /></td>
            <td><input aria-label={`Rate ${i + 1} date`} type="date" value={r.rate_date ?? ""} onChange={(e) => set(["exchange_rates", i, "rate_date"], e.target.value)} /></td>
            <td><input aria-label={`Rate ${i + 1} source`} value={r.source} onChange={(e) => set(["exchange_rates", i, "source"], e.target.value)} /></td>
            <td><button type="button" className="link-btn small" onClick={() => set(["exchange_rates"], draft.exchange_rates.filter((_: unknown, j: number) => j !== i))}>Remove</button></td>
          </tr>))}</tbody>
      </table>
      <button type="button" className="btn btn-small" onClick={() => set(["exchange_rates"], [...draft.exchange_rates, { from: "", to: draft.reporting_currency, rate: "", rate_date: "", source: "" }])}>Add rate</button>
      {ALTS.map(([k, t]) => {
        const a = draft.alternatives[k];
        return (
          <fieldset key={k} className="scenario-alt"><legend>{t}</legend>
            <div className="toolbar small">
              <label>MOQ <input aria-label={`${t} MOQ`} type="number" min={1} value={a.moq} onChange={(e) => set(["alternatives", k, "moq"], e.target.value)} /></label>
              <label>Order multiple <input aria-label={`${t} order multiple`} type="number" min={1} value={a.order_multiple} onChange={(e) => set(["alternatives", k, "order_multiple"], e.target.value)} /></label>
              <label>Qualification units <input aria-label={`${t} qualification units`} type="number" min={0} value={a.qualification_units} onChange={(e) => set(["alternatives", k, "qualification_units"], e.target.value)} /></label>
            </div>
            <table className="table compact"><thead><tr><th>Cost component</th><th>N/A</th><th>Amount</th><th>Currency</th><th>Source</th><th>Reference</th><th>Valid until</th></tr></thead>
              <tbody>
                {COMP_KEYS.map((ck) => {
                  const c = a.costs[ck];
                  const name = `${t} ${labels.costs[ck]}`;
                  const p = ["alternatives", k, "costs", ck];
                  return (
                    <tr key={ck}>
                      <td>{labels.costs[ck]}{ck === "logistics" && !c.not_applicable && (
                        <select aria-label={`${name} basis`} value={c.basis ?? "per_order"} onChange={(e) => set([...p, "basis"], e.target.value)}>
                          <option value="per_order">per order</option><option value="per_unit">per unit</option></select>)}</td>
                      <td>{ck !== "unit_cost" && <input type="checkbox" aria-label={`${name} not applicable`} checked={!!c.not_applicable}
                        onChange={(e) => set(p, e.target.checked ? { not_applicable: true } : { amount: null, currency: draft.reporting_currency, source: "missing", reference: "" })} />}</td>
                      {c.not_applicable ? <td colSpan={5} className="muted">Not applicable</td> : <>
                        <td><input aria-label={`${name} amount`} size={9} value={c.amount ?? ""} onChange={(e) => set([...p, "amount"], e.target.value || null)} /></td>
                        <td><input aria-label={`${name} currency`} size={4} value={c.currency ?? ""} onChange={(e) => set([...p, "currency"], e.target.value.toUpperCase())} /></td>
                        <td>{src([...p, "source"], c.source ?? "missing", name)}</td>
                        <td><input aria-label={`${name} reference`} value={c.reference ?? ""} onChange={(e) => set([...p, "reference"], e.target.value)} /></td>
                        <td><input aria-label={`${name} valid until`} type="date" value={c.valid_until ?? ""} onChange={(e) => set([...p, "valid_until"], e.target.value || null)} /></td>
                      </>}
                    </tr>
                  );
                })}
                <tr>
                  <td>Duties / taxes (% of goods and logistics)</td>
                  <td><input type="checkbox" aria-label={`${t} duties not applicable`} checked={!!a.costs.duties.not_applicable}
                    onChange={(e) => set(["alternatives", k, "costs", "duties"], e.target.checked ? { not_applicable: true } : { percent: null, source: "missing", reference: "" })} /></td>
                  {a.costs.duties.not_applicable ? <td colSpan={5} className="muted">Not applicable</td> : <>
                    <td><input aria-label={`${t} duties percent`} size={6} value={a.costs.duties.percent ?? ""} onChange={(e) => set(["alternatives", k, "costs", "duties", "percent"], e.target.value || null)} /></td>
                    <td>%</td>
                    <td>{src(["alternatives", k, "costs", "duties", "source"], a.costs.duties.source ?? "missing", `${t} duties`)}</td>
                    <td colSpan={2}><input aria-label={`${t} duties reference`} value={a.costs.duties.reference ?? ""} onChange={(e) => set(["alternatives", k, "costs", "duties", "reference"], e.target.value)} /></td>
                  </>}
                </tr>
                {Object.entries(labels.lead).map(([lk, ll]) => {
                  const l = a.lead_time[lk];
                  const p = ["alternatives", k, "lead_time", lk];
                  return (
                    <tr key={lk}>
                      <td>{ll} (days)</td>
                      <td>{lk === "engineering_days" && <input type="checkbox" aria-label={`${t} ${ll} not applicable`} checked={!!l.not_applicable}
                        onChange={(e) => set(p, e.target.checked ? { not_applicable: true } : { days: null, source: "missing", reference: "" })} />}</td>
                      {l.not_applicable ? <td colSpan={5} className="muted">Not applicable</td> : <>
                        <td><input aria-label={`${t} ${ll} days`} size={5} value={l.days ?? ""} onChange={(e) => set([...p, "days"], e.target.value === "" ? null : e.target.value)} /></td>
                        <td>days</td>
                        <td>{src([...p, "source"], l.source ?? "missing", `${t} ${ll}`)}</td>
                        <td colSpan={2}><input aria-label={`${t} ${ll} reference`} value={l.reference ?? ""} onChange={(e) => set([...p, "reference"], e.target.value)} /></td>
                      </>}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </fieldset>
        );
      })}
    </div>
  );
}

export function CostComparisonPanel({ partId }: { partId: string }) {
  const { can } = useAuth();
  const view = useApi<View>(`/parts/${partId}/cost-comparisons/`);
  const [draft, setDraft] = useState<Scenario | null>(null);
  const [preview, setPreview] = useState<{ results: Results; scenario: Scenario } | null>(null);
  const [whatIf, setWhatIf] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [info, setInfo] = useState("");

  if (view.loading && !view.data) return <Card title="Cost & Lead-Time Comparison"><Loading /></Card>;
  if (view.error || !view.data) return <Card title="Cost & Lead-Time Comparison"><ErrorNotice error={view.error} /></Card>;
  const d = view.data;
  const latest = d.comparisons[0];
  const editable = can("intelligence.assess");

  async function calculate(scenario: Scenario) {
    setBusy("preview"); setError(null); setInfo("");
    try {
      const r = await api<{ results: Results }>(`/parts/${partId}/cost-comparisons/calculate/`, { body: { scenario } });
      setPreview({ results: r.results, scenario });
    } catch (e) { setError(e); } finally { setBusy(""); }
  }

  async function save(scenario: Scenario, tier: string | null, derivedFrom?: string) {
    setBusy(tier ?? "save"); setError(null); setInfo("");
    try {
      const r = await api<{ reused: boolean; comparison: Comparison }>(`/parts/${partId}/cost-comparisons/`,
        { body: { scenario, tier, derived_from: derivedFrom ?? null } });
      setInfo(r.reused ? `Inputs unchanged: version ${r.comparison.version} was reused.` : `Version ${r.comparison.version} stored${r.comparison.ai_status !== "none" ? ` (${r.comparison.ai_status_label})` : ""}.`);
      setPreview(null); setDraft(null); setWhatIf("");
      view.reload();
    } catch (e) { setError(e); } finally { setBusy(""); }
  }

  const shown = preview?.results ?? latest?.results;
  return (
    <Card title="Cost & Lead-Time Comparison (Aries internal)">
      <Notice kind="warning"><span role="note">{d.statement} A lower cost never overrides technical constraints or missing engineering approval.</span></Notice>
      <AiGate ai={d.ai} />
      <FieldErrors error={error} />
      {info && <Notice kind="success"><span role="status">{info}</span></Notice>}
      {!d.feasibility ? <Empty>Run the manufacturing feasibility assessment first: the comparison uses its technical status.</Empty> : <>
        {latest && !preview && (
          <p className="small" data-testid="cost-version">Version <strong>{latest.version}</strong> · {latest.name} {latest.synthetic && <Badge tone="warning">Synthetic test data: not real prices</Badge>}
            {" "}· {latest.quantity} required · {latest.reporting_currency} · {formatDate(latest.created_at)} · {latest.created_by_name} · feasibility v{latest.feasibility_version}
            {latest.feasibility_superseded && <> <Badge tone="warning">newer feasibility version exists</Badge></>}
            {latest.derived_from_version ? ` · derived from v${latest.derived_from_version}` : ""} · {latest.ai_status_label}</p>)}
        {latest && !preview && (latest.ai_consistency ?? []).length > 0 && (
          <Notice kind="warning"><span role="status" data-testid="ai-consistency">This stored AI note contradicts the recorded technical status
            and must be disregarded (stored versions are never changed): {latest.ai_consistency!.map((x) => `“${x.sentence}” (${x.alternative}: recorded ${x.recorded.replace(/_/g, " ")})`).join("; ")}</span></Notice>)}
        {preview && <Notice kind="info"><span role="status" data-testid="cost-preview">Preview, not saved: {preview.results.quantity} required. The stored versions are unchanged.</span></Notice>}
        {shown ? <ResultsView r={shown} notes={preview ? undefined : latest?.ai.response} /> : <Empty>No comparison yet. Enter a scenario below.</Empty>}
        {latest && editable && (
          <div className="toolbar" aria-label="What-if calculation">
            <label className="small">What-if quantity <input aria-label="What-if quantity" type="number" min={1} value={whatIf} onChange={(e) => setWhatIf(e.target.value)} /></label>
            <button type="button" className="btn btn-small" disabled={!whatIf || !!busy} onClick={() => calculate({ ...clone(latest.inputs), quantity: whatIf })}>
              {busy === "preview" ? "Calculating…" : "Recalculate (not saved)"}</button>
            {preview && <button type="button" className="btn btn-primary btn-small" disabled={!!busy}
              onClick={() => save(preview.scenario, null, latest.id)}>Save as new version</button>}
            {preview && <button type="button" className="btn btn-small" onClick={() => setPreview(null)}>Discard preview</button>}
          </div>
        )}
        {editable && (
          <details className="small" open={!latest} onToggle={(e) => { if ((e.target as HTMLDetailsElement).open && !draft) setDraft(clone(latest?.inputs ?? d.template)); }}>
            <summary>{latest ? "Edit scenario (saves a new version)" : "Enter scenario"}</summary>
            {(draft ?? (!latest ? d.template : null)) && <>
              <ScenarioForm draft={draft ?? clone(d.template)} setDraft={setDraft} labels={d.labels} />
              <div className="toolbar">
                <button type="button" className="btn btn-small" disabled={!!busy} onClick={() => calculate(draft ?? d.template)}>Calculate preview</button>
                <button type="button" className="btn btn-primary btn-small" disabled={!!busy} onClick={() => save(draft ?? d.template, null)}>{busy === "save" ? "Saving…" : "Save version"}</button>
                {d.ai.enabled && (draft ?? d.template).synthetic && <button type="button" className="btn btn-small" disabled={!!busy}
                  onClick={() => save(draft ?? d.template, "lite")}>{busy === "lite" ? "Asking…" : `Save with AI assumption notes (${d.ai.models.lite})`}</button>}
              </div>
            </>}
          </details>
        )}
        {latest?.ai_status === "ok" && (
          <details className="small"><summary>AI provenance: {latest.ai.model_version || latest.ai.model}, {latest.ai.usage?.prompt_tokens} in / {latest.ai.usage?.output_tokens} out tokens, estimated {usd(latest.ai.usage?.cost_usd)}</summary>
            <ul className="plain-list">{(latest.ai.response?.general_notes ?? []).map((x) => <li key={x}>{x}</li>)}</ul>
            {(latest.ai.removed ?? []).length > 0 && <p className="muted">{latest.ai.removed!.length} statement(s) removed (prices, recommendations or approval claims).</p>}
            <p className="muted">The AI received component shares, sources and lead times only: no amounts, rates or references.</p>
          </details>
        )}
        {d.comparisons.length > 1 && (
          <details className="small"><summary>Earlier versions ({d.comparisons.length - 1})</summary>
            <table className="table" aria-label="Earlier cost comparison versions">
              <thead><tr><th>Version</th><th>Scenario</th><th>Quantity</th><th>OEM</th><th>Additive</th><th>Conventional</th><th>Date</th></tr></thead>
              <tbody>{d.comparisons.slice(1).map((c) => (
                <tr key={c.id}><td>{c.version}</td><td>{c.name}</td><td>{c.quantity}</td>
                  {ALTS.map(([k]) => <td key={k}>{money(c.results.alternatives[k].total, c.reporting_currency)}</td>)}<td>{formatDate(c.created_at)}</td></tr>))}</tbody>
            </table>
          </details>
        )}
      </>}
    </Card>
  );
}

type OvAlt = { total: string | null; effective_unit_cost: string | null; lead_days: number | null; confidence: string; technical: string; savings: string | null; savings_percent: string | null; missing: number };
type OvRow = { id: string; part_number: string; name: string; comparison: null | { id: string; version: number; name: string; synthetic: boolean; quantity: number; currency: string;
  feasibility_version: number; alternatives: Record<AltKey, OvAlt> } };

export function CostOverview() {
  const ov = useApi<{ parts: OvRow[] }>("/intelligence/cost-comparisons/");
  if (ov.loading && !ov.data) return <Loading />;
  if (ov.error || !ov.data) return <ErrorNotice error={ov.error} />;
  return (
    <Card title="Cost & Lead-Time Comparison">
      <p className="muted small">Latest stored comparison per part. Totals in each scenario's reporting currency; every option shows its technical screening
        label. Comparison only: no recommendation, approval or release.</p>
      {ov.data.parts.length === 0 ? <Empty>No imported parts yet.</Empty> : (
        <div className="table-scroll">
          <table className="table" aria-label="Cost and lead-time comparison">
            <thead><tr><th>Material number</th><th>Scenario</th>{ALTS.map(([k, t]) => <th key={k}>{t}</th>)}</tr></thead>
            <tbody>{ov.data.parts.map((p) => (
              <tr key={p.id}>
                <td><Link to={`/parts/${p.id}`}><strong>{p.part_number}</strong></Link><div className="small">{p.name}</div></td>
                {p.comparison ? <>
                  <td className="small">v{p.comparison.version} · {p.comparison.name}{p.comparison.synthetic && <> <Badge tone="warning">synthetic</Badge></>}
                    <div className="muted">{p.comparison.quantity} units · {p.comparison.currency}</div></td>
                  {ALTS.map(([k]) => { const a = p.comparison!.alternatives[k]; return (
                    <td key={k} className="small"><strong>{a.total == null ? "Incomplete" : money(a.total, p.comparison!.currency)}</strong>
                      <div>{a.effective_unit_cost ? `${money(a.effective_unit_cost, p.comparison!.currency)} / unit` : ""}{a.lead_days != null ? ` · ${a.lead_days} d` : ""}</div>
                      <div className="muted">{a.technical}</div><div className="muted">{a.confidence}{a.missing ? ` · ${a.missing} missing` : ""}</div></td>); })}
                </> : <td colSpan={4} className="muted">No comparison yet</td>}
              </tr>))}</tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
