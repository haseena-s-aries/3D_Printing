/**
 * Part intelligence (CN-007 Phase 2), Aries-internal. The rule-based analysis always works; external AI suggestions
 * (Gemini) are optional and only offered where the server permits them. Suggestions are kept apart from the part's
 * engineer-verified values: nothing here changes the part except "Record classification", which an engineer confirms.
 */
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { CostOverview } from "./CostComparison";
import { FeasibilityOverview } from "./ManufacturingFeasibility";
import { AiWorkflow } from "./AiWorkflow";
import { RecommendationQueue } from "./Recommendation";
import { Badge, Card, Empty, ErrorNotice, Loading, Notice, formatDate, label } from "./ui";

type Constraint = { code: string; kind: "block" | "review" | "insufficient"; text: string };
type Completeness = { score: number; items: { key: string; label: string; points: number; met: boolean; partial: boolean }[]; missing: string[] };
type Analysis = {
  rules_version: string;
  description: { as_supplied: string; expanded: string[]; unknown_tokens: string[] };
  classification: { family: string; category: string; assembly: boolean | null; basis: string; recorded_category: string };
  mentions: { dimensions: { value: number; unit: string; mm: number }[]; materials: { text: string; reading: string; class: string }[] };
  manufacturer: { as_supplied: string; cleaned: string; match_key: string; placeholder: boolean; possibly_truncated: boolean; alias_candidates: string[] };
  duplicates: { same_description_and_manufacturer: string[]; similar_description: string[] };
  completeness: Completeness;
  constraints: Constraint[];
  screening: string;
};
type Suggestion = {
  expanded_description: string; part_family: string; category: string; function: string; is_assembly: string;
  material: { value: string; basis: string }; am_screening: string; am_process_options: string[]; rationale: string;
  risks: string[]; information_needed: string[]; confidence: number; uncertainty: string;
};
export type Assessment = {
  id: string; status: string; status_label: string; tier: string; model: string; model_version: string; prompt_version: string;
  input_hash: string; inputs: Record<string, unknown>; result: Suggestion | Record<string, never>; confidence: number | null; removed: string[];
  error_code: string; error_message: string; current?: boolean; created_at: string; created_by_name: string;
  usage: { prompt_tokens: number; output_tokens: number; thinking_tokens: number; cost_usd: number | null; latency_ms: number; attempts: number };
};
export type AiStatus = { enabled: boolean; reason: string; provider: string; models: Record<string, string>; sent_fields: string[];
  limits: { calls_per_minute: number; calls_per_day: number; daily_budget_usd: number } };
type PartView = { analysis: Analysis; ai: AiStatus; assessments: Assessment[]; classification: { category: string; provenance?: { verified_by: string; verified_at: string; basis: string; note: string } } };
type Usage = { total: { calls: number; cache_hits: number; refused: number; failed: number; prompt_tokens: number; output_tokens: number; thinking_tokens: number; cost_usd: number };
  by_model: { model: string; calls: number; prompt_tokens: number; output_tokens: number; cost_usd: number }[]; note: string; days: number;
  by_company?: { company: string; calls: number; cost_usd: number; prompt_tokens: number; output_tokens: number }[] };
type OverviewRow = { id: string; part_number: string; name: string; manufacturer: string; category: string;
  rules: { family: string; category: string; screening: string; completeness: number; constraints: Constraint[]; duplicates: Analysis["duplicates"] };
  ai: { id: string; status: string; model: string; tier: string; category?: string; part_family?: string; am_screening?: string; confidence: number | null; cost_usd: number | null; created_at: string; error_code: string } | null };

export const SCREENING: Record<string, [string, "neutral" | "info" | "success" | "warning" | "danger"]> = {
  excluded_by_rule: ["Excluded by rule", "danger"], insufficient_information: ["Insufficient information", "neutral"],
  engineering_review_required: ["Engineering review required", "info"], candidate: ["AM candidate (suggestion)", "info"],
  possible_with_engineering_review: ["Possible, with engineering review", "info"], unlikely: ["Unlikely", "warning"],
};
const TIER: Record<string, string> = { lite: "Flash-Lite (default)", flash: "Flash (escalation)", pro: "Pro (escalation)" };
const CATEGORIES = ["mechanical", "electrical", "electronic", "other", "unknown"];

export const usd = (n: number | null | undefined) => (n == null ? "—" : `$${n < 0.01 ? n.toFixed(6) : n.toFixed(4)}`);
const catLabel = (c?: string) => (c === "unknown" ? "Not classified" : label(c ?? ""));

function Screening({ value }: { value?: string }) {
  if (!value) return <span className="muted">—</span>;
  const [text, tone] = SCREENING[value] ?? [label(value), "neutral"];
  return <Badge tone={tone}>{text}</Badge>;
}

export function AiGate({ ai }: { ai: AiStatus }) {
  return ai.enabled ? (
    <p className="muted small">External AI permitted for this company (synthetic pilot). Sent: {ai.sent_fields.join(", ")}. Nothing else
      leaves the platform (no location, tag, ABC indicator, files, drawings or CAD). Limits: {ai.limits.calls_per_minute}/min,
      {" "}{ai.limits.calls_per_day}/day, budget ${ai.limits.daily_budget_usd.toFixed(2)}/day.</p>
  ) : <Notice kind="info"><span role="status">External AI not used: {ai.reason}</span></Notice>;
}

function RulesFacts({ a }: { a: Analysis }) {
  return (
    <dl className="facts" aria-label="Rule-based analysis">
      <dt>Description</dt><dd>{a.description.expanded.join(", ") || "—"}{a.description.unknown_tokens.length > 0 &&
        <div className="muted small">Not recognised: {a.description.unknown_tokens.join(", ")}</div>}</dd>
      <dt>Part family</dt><dd>{a.classification.family || <span className="muted">Not recognised</span>} · {catLabel(a.classification.category)}
        {a.classification.assembly && <> · <Badge tone="warning">assembly</Badge></>} <span className="muted small">({a.classification.basis})</span></dd>
      <dt>Mentioned in text</dt><dd>{a.mentions.dimensions.length ? a.mentions.dimensions.map((d) => `${d.value} ${d.unit}`).join(", ") : "no dimensions"}
        {" · "}{a.mentions.materials.length ? a.mentions.materials.map((m) => m.reading).join(", ") : "no material"} <span className="muted small">(not verified)</span></dd>
      <dt>Manufacturer</dt><dd>{a.manufacturer.cleaned || <span className="muted">Not stated</span>}
        {a.manufacturer.placeholder && <> <Badge tone="warning">placeholder</Badge></>}
        {a.manufacturer.possibly_truncated && <> <Badge tone="warning">may be cut off at the source limit</Badge></>}
        {a.manufacturer.alias_candidates.length > 0 && <div className="muted small">Possible aliases: {a.manufacturer.alias_candidates.join(", ")}</div>}</dd>
      <dt>Duplicates</dt><dd>{[...a.duplicates.same_description_and_manufacturer.map((n) => `${n} (same description and manufacturer)`),
        ...a.duplicates.similar_description.map((n) => `${n} (similar description)`)].join("; ") || "None found"}</dd>
      <dt>Completeness</dt><dd><strong>{a.completeness.score}/100</strong>{a.completeness.missing.length > 0 &&
        <span className="muted small"> · missing: {a.completeness.missing.join(", ")}</span>}</dd>
      <dt>Screening rules</dt><dd><Screening value={a.screening} />
        <ul className="plain-list small" aria-label="Engineering constraints">
          {a.constraints.map((c) => <li key={c.code}><Badge tone={c.kind === "block" ? "danger" : c.kind === "review" ? "warning" : "neutral"}>{c.kind}</Badge> {c.text}</li>)}
          {a.constraints.length === 0 && <li className="muted">No rule applies.</li>}
        </ul></dd>
    </dl>
  );
}

function SuggestionView({ a }: { a: Assessment }) {
  const r = a.result as Suggestion;
  return (
    <div className="ai-suggestion" data-testid="ai-suggestion">
      <p><Badge tone="info">AI suggestion · not verified</Badge> <strong>{a.model_version || a.model}</strong>{" "}
        <span className="muted small">{TIER[a.tier] ?? a.tier} · {formatDate(a.created_at)} · {a.created_by_name}{a.current === false ? " · inputs changed since" : ""}</span></p>
      {a.status !== "ok" ? (
        <Notice kind="warning"><span role="status">{a.status_label}: {a.error_message || a.error_code}. The rule-based analysis above still applies.</span></Notice>
      ) : (
        <dl className="facts" aria-label="AI suggestion">
          <dt>Classification</dt><dd>{r.part_family} · {catLabel(r.category)} · assembly: {r.is_assembly}</dd>
          <dt>Confidence</dt><dd>{Math.round((a.confidence ?? 0) * 100)}% <span className="muted small">{r.uncertainty}</span></dd>
          <dt>Description</dt><dd>{r.expanded_description}</dd>
          <dt>Function</dt><dd>{r.function}</dd>
          <dt>Material</dt><dd>{r.material.value} <span className="muted small">({label(r.material.basis)})</span></dd>
          <dt>AM screening</dt><dd><Screening value={r.am_screening} /> {r.am_process_options.filter((p) => p !== "none").map(label).join(", ")}
            <div className="muted small">Suggestion only: not a feasibility approval or manufacturing release.</div></dd>
          <dt>Rationale</dt><dd>{r.rationale}</dd>
          {r.risks.length > 0 && <><dt>Risks</dt><dd><ul className="plain-list">{r.risks.map((x) => <li key={x}>{x}</li>)}</ul></dd></>}
          {r.information_needed.length > 0 && <><dt>Information needed</dt><dd><ul className="plain-list">{r.information_needed.map((x) => <li key={x}>{x}</li>)}</ul></dd></>}
          {a.removed.length > 0 && <><dt>Removed</dt><dd className="muted small">{a.removed.length} price or cost statement(s) removed: AI prices are never quotations.</dd></>}
        </dl>
      )}
      <details className="small"><summary>Inputs sent and usage</summary>
        <pre className="mono small">{JSON.stringify(a.inputs, null, 1)}</pre>
        <p className="muted">Tokens: {a.usage.prompt_tokens} in, {a.usage.output_tokens} out{a.usage.thinking_tokens ? `, ${a.usage.thinking_tokens} thinking` : ""} ·
          estimated cost {usd(a.usage.cost_usd)} · {a.usage.latency_ms} ms · {a.usage.attempts} attempt(s) · prompt {a.prompt_version} · input hash {a.input_hash.slice(0, 12)}…</p>
      </details>
    </div>
  );
}

export function PartIntelligencePanel({ partId, onClassified }: { partId: string; onClassified?: () => void }) {
  const { can } = useAuth();
  const view = useApi<PartView>(`/parts/${partId}/intelligence/`);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [info, setInfo] = useState("");
  const [category, setCategory] = useState("");
  const [note, setNote] = useState("");

  async function assess(tier: string) {
    setBusy(tier); setError(null); setInfo("");
    try {
      const r = await api<{ reused: boolean; assessment: Assessment }>(`/parts/${partId}/intelligence/assess/`, { body: { tier } });
      setInfo(r.reused ? "Inputs unchanged: the stored suggestion was reused (no new AI call)." : `Suggestion received from ${r.assessment.model_version || r.assessment.model}.`);
      view.reload();
    } catch (e) { setError(e); } finally { setBusy(""); }
  }

  async function classify(assessment?: string) {
    setBusy("classify"); setError(null);
    try {
      view.setData(await api<PartView>(`/parts/${partId}/intelligence/classification/`, { body: { category, note, assessment } }));
      setInfo("Classification recorded as an engineer-verified value."); setCategory(""); setNote("");
      onClassified?.();
    } catch (e) { setError(e); } finally { setBusy(""); }
  }

  if (view.loading && !view.data) return <Card title="Part intelligence"><Loading /></Card>;
  if (view.error || !view.data) return <Card title="Part intelligence"><ErrorNotice error={view.error} /></Card>;
  const d = view.data;
  const latest = d.assessments[0];
  const prov = d.classification.provenance;
  return (
    <Card title="Part intelligence (Aries internal)">
      <p className="muted small section-note">Proposals from rules and, where permitted, AI. They never change the part: the engineer records the
        verified classification. Rules version {d.analysis.rules_version}.</p>
      <ErrorNotice error={error} />
      {info && <Notice kind="success"><span role="status">{info}</span></Notice>}
      <div className="grid-2">
        <div>
          <h3 className="h-sub">Rule-based analysis</h3>
          <RulesFacts a={d.analysis} />
        </div>
        <div>
          <h3 className="h-sub">AI suggestion</h3>
          <AiGate ai={d.ai} />
          {d.ai.enabled && can("intelligence.assess") && (
            <div className="toolbar">
              {Object.keys(TIER).map((t) => (
                <button key={t} type="button" className={`btn ${t === "lite" ? "btn-primary" : ""} btn-small`} disabled={!!busy} onClick={() => assess(t)}>
                  {busy === t ? "Asking…" : t === "lite" ? "Get AI suggestion" : `Escalate: ${d.ai.models[t]}`}</button>
              ))}
            </div>
          )}
          {latest ? <SuggestionView a={latest} /> : <Empty>No AI suggestion yet.</Empty>}
          {d.assessments.length > 1 && (
            <details className="small"><summary>Earlier suggestions ({d.assessments.length - 1})</summary>
              {d.assessments.slice(1).map((a) => <SuggestionView key={a.id} a={a} />)}</details>
          )}
        </div>
      </div>
      {can("intelligence.classify") && (
        <div className="classify-row" aria-label="Engineer classification">
          <h3 className="h-sub">Engineer-verified classification</h3>
          <p className="small">Current: <strong>{catLabel(d.classification.category)}</strong>
            {prov ? <span className="muted"> · verified by {prov.verified_by}, {formatDate(prov.verified_at)} ({prov.basis}){prov.note ? `: ${prov.note}` : ""}</span>
              : <span className="muted"> · not verified</span>}</p>
          <div className="toolbar">
            <label className="small">Category{" "}
              <select aria-label="Verified category" value={category} onChange={(e) => setCategory(e.target.value)}>
                <option value="">Choose…</option>
                {CATEGORIES.map((c) => <option key={c} value={c}>{catLabel(c)}</option>)}
              </select></label>
            <input aria-label="Classification note" placeholder="Basis / note" value={note} onChange={(e) => setNote(e.target.value)} />
            <button type="button" className="btn btn-small" disabled={!category || !!busy}
              onClick={() => classify(latest?.status === "ok" ? latest.id : undefined)}>Record classification</button>
          </div>
        </div>
      )}
    </Card>
  );
}

export function UsageTable({ usage }: { usage: Usage }) {
  return (
    <>
      <div className="stat-row" data-testid="ai-usage">
        {([["calls", "AI calls"], ["cache_hits", "Reused (no call)"], ["refused", "Refused by limits"], ["failed", "Failed / invalid"]] as const).map(([k, l]) => (
          <div key={k} className="stat"><strong>{usage.total[k]}</strong><span className="muted small">{l}</span></div>))}
        <div className="stat"><strong>{usage.total.prompt_tokens + usage.total.output_tokens + usage.total.thinking_tokens}</strong><span className="muted small">Tokens</span></div>
        <div className="stat"><strong>{usd(usage.total.cost_usd)}</strong><span className="muted small">Estimated cost</span></div>
      </div>
      {usage.by_model.length > 0 && (
        <table className="table" aria-label="AI usage by model">
          <thead><tr><th>Model</th><th>Calls</th><th>Input tokens</th><th>Output tokens</th><th>Estimated cost</th></tr></thead>
          <tbody>{usage.by_model.map((m) => <tr key={m.model}><td>{m.model}</td><td>{m.calls}</td><td>{m.prompt_tokens ?? 0}</td><td>{m.output_tokens ?? 0}</td><td>{usd(m.cost_usd)}</td></tr>)}</tbody>
        </table>
      )}
      <p className="muted small">Last {usage.days} days. {usage.note}</p>
    </>
  );
}

const VIEWS: [string, string][] = [["pipeline", "Assessment pipeline"], ["classification", "Classification"], ["feasibility", "Feasibility"],
  ["cost", "Cost & lead time"], ["review", "Review queue"], ["usage", "AI usage"]];
const FEAS_SHORT: Record<string, string> = {
  potentially_suitable: "Potentially suitable", potentially_suitable_redesign: "Potentially suitable (redesign)", insufficient_information: "Insufficient information",
  specialist_assessment: "Specialist assessment required", not_suitable_verified: "Not suitable (verified)", not_verified: "Not verified",
  identified_confirmation_required: "Identified, confirmation required",
};
type FeasRow = { id: string; assessment: null | { version: number; additive: { status: string }; conventional: { status: string }; reviews: Record<string, string> } };
type CostRow = { id: string; comparison: null | { version: number; synthetic: boolean } };
type RecRow = { id: string; review_state: { code: string; label: string; reviewed: boolean }; recommendation: null | { version: number; outcome: string; outcome_label: string } };
type DiscRow = { id: string; state: { code: string; label: string } };

/** One row per part in the engineering lifecycle across the whole assessment journey; each cell opens that step of the part. Statuses are
 *  shown as stored (preliminary until reviewed); nothing here is an approval or authorisation. */
function Pipeline({ parts }: { parts: OverviewRow[] }) {
  const { can } = useAuth();
  const feas = useApi<{ parts: FeasRow[] }>("/intelligence/feasibility/");
  const cost = useApi<{ parts: CostRow[] }>("/intelligence/cost-comparisons/");
  const rec = useApi<{ parts: RecRow[] }>("/intelligence/recommendations/");
  const disc = useApi<{ parts: DiscRow[] }>(can("ai.share") ? "/intelligence/disclosures/" : null);
  const by = <T extends { id: string }>(rows?: T[]) => new Map((rows ?? []).map((r) => [r.id, r]));
  const F = by(feas.data?.parts), C = by(cost.data?.parts), R = by(rec.data?.parts), S = by(disc.data?.parts);
  const step = (id: string, s: string) => `/parts/${id}?tab=ai&step=${s}`;
  const loading = (feas.loading && !feas.data) || (cost.loading && !cost.data) || (rec.loading && !rec.data);
  return (
    <Card title={`Assessment pipeline (${parts.length} imported part${parts.length === 1 ? "" : "s"})`}>
      <p className="muted small">Where each part stands in the journey. Open a cell to work on that step of the part. Everything is preliminary until an
        engineer reviews it; "potentially suitable" still requires engineering qualification.</p>
      {loading ? <Loading /> : parts.length === 0 ? <Empty icon="boxes">No imported parts yet.</Empty> : (
        <div className="table-scroll">
          <table className="table pipeline-table table-stack" aria-label="Assessment pipeline">
            <thead><tr><th>Material number</th><th>Classification</th><th>Feasibility (AM / conventional)</th><th>Cost &amp; lead time</th>
              <th>Recommendation</th><th>Engineering review</th>{can("ai.share") && <th>Client sharing</th>}</tr></thead>
            <tbody>{parts.map((p) => {
              const f = F.get(p.id)?.assessment, c = C.get(p.id)?.comparison, r = R.get(p.id), s = S.get(p.id);
              return (
                <tr key={p.id}>
                  <td><Link to={step(p.id, "classification")}><strong>{p.part_number}</strong></Link><div className="small muted">{p.name}</div></td>
                  <td><Link className="cell-link" to={step(p.id, "classification")}>{p.category && p.category !== "unknown" ? <>{catLabel(p.category)}<span className="muted"> · verified</span></>
                    : p.ai?.status === "ok" ? <>AI: {catLabel(p.ai.category)}<span className="muted"> · not verified</span></> : <span className="muted">Not classified</span>}</Link></td>
                  <td><Link className="cell-link" to={step(p.id, "feasibility")}>{f ? <>{FEAS_SHORT[f.additive.status] ?? label(f.additive.status)}<span className="muted"> / </span>
                    {FEAS_SHORT[f.conventional.status] ?? label(f.conventional.status)}<div className="muted small">v{f.version}{Object.keys(f.reviews ?? {}).length ? " · reviewed" : " · preliminary"}</div></>
                    : <span className="muted">Not run</span>}</Link></td>
                  <td><Link className="cell-link" to={step(p.id, "commercial")}>{c ? <>v{c.version}{c.synthetic && <span className="muted"> · synthetic</span>}</> : <span className="muted">None</span>}</Link></td>
                  <td><Link className="cell-link" to={step(p.id, "recommendation")}>{r?.recommendation ? <>v{r.recommendation.version}<div className="muted small" title={r.recommendation.outcome_label}>{r.recommendation.outcome_label.split(" — ")[0].split(" (")[0]}</div></>
                    : <span className="muted">Not generated</span>}</Link></td>
                  <td>{r?.recommendation ? <Badge tone={r.review_state.reviewed ? "info" : "warning"}>{r.review_state.reviewed ? r.review_state.label.split(",")[0].replace("Reviewed: ", "") : "Not reviewed"}</Badge>
                    : <span className="muted">—</span>}</td>
                  {can("ai.share") && <td><Link className="cell-link" to={step(p.id, "sharing")}>{s ? s.state.label.replace(" (internal)", "") : "—"}</Link></td>}
                </tr>
              );
            })}</tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

export function IntelligenceOverview() {
  const { can } = useAuth();
  const ov = useApi<{ ai: AiStatus; parts: OverviewRow[]; usage: Usage }>("/intelligence/overview/");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [summary, setSummary] = useState("");

  async function batch(tier: string) {
    if (!ov.data) return;
    setBusy(tier); setError(null); setSummary("");
    try {
      const r = await api<{ results: { part_number: string; reused?: boolean; error?: { code: string; message: string } }[] }>("/intelligence/assess-batch/",
        { body: { tier, parts: ov.data.parts.slice(0, 10).map((p) => p.id) } });
      const ok = r.results.filter((x) => !x.error);
      setSummary(`${ok.length} suggestion(s): ${ok.filter((x) => !x.reused).length} new, ${ok.filter((x) => x.reused).length} reused.` +
        r.results.filter((x) => x.error).map((x) => ` ${x.part_number}: ${x.error!.message}`).join(""));
      ov.reload();
    } catch (e) { setError(e); } finally { setBusy(""); }
  }

  const [params, setParams] = useSearchParams();
  const views = VIEWS;
  const view = views.some(([v]) => v === params.get("view")) ? params.get("view")! : "pipeline";
  const setView = (v: string) => setParams((prev) => { const n = new URLSearchParams(prev); if (v === "pipeline") n.delete("view"); else n.set("view", v); return n; },
    { replace: true });

  if (ov.loading && !ov.data) return <Loading />;
  if (ov.error || !ov.data) return <ErrorNotice error={ov.error} />;
  const d = ov.data;
  const at = (v: string) => `/inventory-import?tab=intelligence&view=${v}`;
  return (
    <>
      <AiWorkflow targets={{ inventory: "/inventory-import?tab=quality", classification: at("classification"), feasibility: at("feasibility"),
        commercial: at("cost"), recommendation: at("review"), review: at("review"), assessment: "/inventory-import?tab=assessment" }} />
      <div className="subtabs ai-views" role="tablist" aria-label="AI assessment views">
        {views.map(([v, name]) => (
          <button key={v} type="button" role="tab" aria-selected={view === v} className={`tab ${view === v ? "is-active" : ""}`} onClick={() => setView(v)}>{name}</button>
        ))}
      </div>
      {view === "pipeline" && <Pipeline parts={d.parts} />}
      {view === "classification" && <Card title="Part intelligence (Aries internal)" actions={d.ai.enabled && can("intelligence.assess") && d.parts.length > 0 ? (
        <button type="button" className="btn btn-primary btn-small" disabled={!!busy} onClick={() => batch("lite")}>
          {busy ? "Asking…" : `Get AI suggestions (${d.ai.models.lite})`}</button>) : undefined}>
        <AiGate ai={d.ai} />
        <ErrorNotice error={error} />
        {summary && <Notice kind="success"><span role="status">{summary}</span></Notice>}
        {d.parts.length === 0 ? <Empty>No imported parts yet.</Empty> : (
          <div className="table-scroll">
            <table className="table" aria-label="Part intelligence">
              <thead><tr><th>Material number</th><th>Rules: family / category</th><th>Completeness</th><th>Screening rules</th><th>AI suggestion</th><th>Verified category</th></tr></thead>
              <tbody>
                {d.parts.map((p) => (
                  <tr key={p.id}>
                    <td><Link to={`/parts/${p.id}`}><strong>{p.part_number}</strong></Link><div className="small">{p.name}</div></td>
                    <td className="small">{p.rules.family || <span className="muted">Not recognised</span>}<div className="muted">{catLabel(p.rules.category)}</div></td>
                    <td>{p.rules.completeness}/100</td>
                    <td><Screening value={p.rules.screening} /><div className="muted small">{p.rules.constraints.filter((c) => c.kind !== "insufficient").map((c) => c.code.replace(/_/g, " ")).join(", ")}</div></td>
                    <td className="small">{p.ai ? (p.ai.status === "ok" ? <>
                      {p.ai.part_family} · {catLabel(p.ai.category)}<div><Screening value={p.ai.am_screening} /> {Math.round((p.ai.confidence ?? 0) * 100)}%</div>
                      <div className="muted">{p.ai.model} · {usd(p.ai.cost_usd)}</div></> : <Badge tone="warning">{label(p.ai.status)}</Badge>) : <span className="muted">None yet</span>}</td>
                    <td>{catLabel(p.category)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>}
      {view === "feasibility" && <FeasibilityOverview />}
      {view === "cost" && <CostOverview />}
      {view === "review" && <RecommendationQueue />}
      {view === "usage" && <Card title="AI usage and estimated cost (this company)"><UsageTable usage={d.usage} /></Card>}
    </>
  );
}

export function AdminIntelligenceUsage() {
  const u = useApi<{ ai: AiStatus; allowed_companies: number; usage: Usage }>("/admin/intelligence-usage/");
  if (u.loading && !u.data) return <Loading />;
  if (u.error || !u.data) return <ErrorNotice error={u.error} />;
  const d = u.data;
  return (
    <Card title="External AI usage (part intelligence)">
      <p className="muted small">Provider: {d.ai.provider || "off"} · models {Object.entries(d.ai.models).map(([t, m]) => `${t}: ${m}`).join(", ")} ·
        companies permitted: {d.allowed_companies}. Usage metadata only: no part data is shown here.</p>
      <UsageTable usage={d.usage} />
      {(d.usage.by_company ?? []).length > 0 && (
        <table className="table" aria-label="AI usage by company">
          <thead><tr><th>Company</th><th>Calls</th><th>Estimated cost</th></tr></thead>
          <tbody>{d.usage.by_company!.map((c) => <tr key={c.company}><td>{c.company}</td><td>{c.calls}</td><td>{usd(c.cost_usd)}</td></tr>)}</tbody>
        </table>
      )}
    </Card>
  );
}
