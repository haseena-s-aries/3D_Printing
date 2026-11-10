/**
 * AI recommendation & engineering review (CN-007 Phase 5), Aries-internal. The server combines Phase 2 part intelligence,
 * Phase 3 feasibility and Phase 4 cost comparison with deterministic rules: mandatory technical, safety, certification
 * and IP requirements first, then separate statuses (cheapest, fastest, potentially suitable, engineering-approved) and
 * weighted ranking only among qualified options. Gemini may explain; it cannot change the result. Every version is
 * preliminary until reviewed, and nothing here approves, authorises, publishes or releases (OQ-35, OQ-36).
 */
import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { AiGate, type AiStatus, usd } from "./PartIntelligence";
import { Badge, Card, Empty, ErrorNotice, Loading, Notice, formatDate } from "./ui";

type OptKey = "oem" | "additive" | "conventional";
const OPTS: [OptKey, string][] = [["oem", "A. OEM procurement"], ["additive", "B. Additive manufacturing"], ["conventional", "C. Conventional manufacturing"]];
type Requirement = { code: string; label: string; kind: string; met: boolean; detail: string };
type Commercial = { available: boolean; complete: boolean; total?: string | null; effective_unit_cost?: string | null; known_costs_total?: string | null;
  lead_days?: number | null; lead_complete: boolean; confidence?: string; evidence: string; evidence_label: string; expired_quotations: string[];
  missing_inputs: string[]; ordered_quantity?: number; lead_evidence_label?: string; expired_lead_times?: string[]; savings_vs_baseline?: string | null; savings_percent?: string | null };
type Option = { label: string; technical: { status: string; status_label: string; label: string; corrected_by_review?: boolean }; requirements: Requirement[];
  eligible: boolean; excluded: boolean; failed_requirements: string[]; commercial: Commercial; rank?: number; score?: string;
  flags: { potentially_suitable: boolean; engineering_approved: boolean; commercially_cheapest: boolean; cheapest_definitive: boolean; fastest: boolean; fastest_definitive: boolean } };
type StatusText = { option?: string | null; options?: string[]; definitive?: boolean; text: string };
type Results = { method_version: string; as_of: string; weights: Record<string, string>; weights_applied: boolean; weights_note: string;
  options: Record<OptKey, Option>; ranking: { option: OptKey; score: string; rank: number }[];
  statuses: { commercially_cheapest: StatusText; fastest: StatusText; potentially_suitable: StatusText; engineering_approved: StatusText };
  outcome: { code: string; label: string; option: string | null; reasons: string[] }; statement: string; risks: string[]; missing_information: string[];
  confidence: { technical: string; commercial: string; overall: string };
  phase2: { family: string; category: string; category_verified: boolean; completeness: number; duplicates: string[];
    ai_suggestion: { model: string; part_family: string; am_screening: string; confidence: number; note: string } | null };
  sources: { feasibility: { version: number }; cost_comparison: { version: number; name: string; quantity: number; currency: string; synthetic: boolean } | null;
    intelligence: { model: string } | null } };
type Review = { id: string; decision: string; decision_label: string; option: string; option_label: string; findings: string; independent: boolean;
  option_eligible: boolean; reviewer: string; created_at: string; evidence_references: { reference: string }[] };
type AiExpl = { summary?: string; information_to_obtain?: string[] } & Partial<Record<OptKey, { technical_explanation: string; commercial_explanation: string;
  evidence_gaps: string[]; risks: string[] }>>;
export type Rec = { id: string; version: number; outcome: string; recommended_option: string; results: Results; feasibility_version: number;
  cost_comparison_version: number | null; passport_number: string; passport_revision_number: number | null; ai_status: string; ai_status_label: string;
  ai: { model?: string; model_version?: string; response?: AiExpl; removed?: string[]; usage?: { prompt_tokens: number; output_tokens: number; cost_usd: number | null };
    error_code?: string; error_message?: string };
  ai_consistency: { alternative: string; recorded: string; sentence: string }[]; created_at: string; created_by_name: string; created_by_id: string | null;
  reviews: Review[]; review_state: { code: string; label: string; reviewed: boolean }; stale: string[]; engineering_approved: boolean; authorisation: string };
type View = { ai: AiStatus; feasibility: { version: number } | null; cost_comparisons: { id: string; version: number; name: string; quantity: number; currency: string; synthetic: boolean }[];
  default_weights: Record<string, string>; recommendations: Rec[]; decisions: Record<string, string>; statement: string };

const money = (v: string | null | undefined, cur = "") => (v == null ? "—" : `${cur} ${Number(v).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`.trim());

function ReviewBadge({ s }: { s: Rec["review_state"] }) {
  const tone = !s.reviewed ? "warning" : s.code === "rejected" ? "danger" : s.code === "approved_for_further_study" ? "success" : "info";
  return <Badge tone={tone}>{s.label}</Badge>;
}

function OptionColumn({ k, title, o, cur }: { k: OptKey; title: string; o: Option; cur: string }) {
  const c = o.commercial;
  return (
    <section className="card feasibility-panel" aria-label={title} data-testid={`rec-${k}`}>
      <h3 className="h-sub">{title}{o.rank ? <> <Badge tone="info">rank {o.rank} · score {o.score}</Badge></> : null}</h3>
      <p><Badge tone={o.excluded ? "danger" : o.eligible ? "success" : "warning"}>{o.excluded ? "Excluded by verified constraint" : o.eligible ? "Potentially suitable" : "Not technically qualified"}</Badge>
        <span className="muted small block">{o.technical.status_label}{o.technical.corrected_by_review ? " (corrected in technical review)" : ""}</span></p>
      <h4 className="h-mini">Mandatory requirements</h4>
      <ul className="plain-list small" aria-label={`${title} requirements`}>
        {o.requirements.map((r) => <li key={r.code}><Badge tone={r.met ? "success" : "danger"}>{r.met ? "met" : "not met"}</Badge> {r.label}
          {r.detail && <span className="muted block">{r.detail}</span>}</li>)}
      </ul>
      <h4 className="h-mini">Commercial evidence</h4>
      {!c.available ? <p className="muted small">No cost comparison.</p> : (
        <dl className="facts small">
          <dt>Total</dt><dd data-testid={`rec-total-${k}`}>{c.complete ? money(c.total, cur) : <>Incomplete <span className="muted">(known {money(c.known_costs_total, cur)})</span></>}</dd>
          <dt>Per usable unit</dt><dd>{money(c.effective_unit_cost, cur)}</dd>
          <dt>Lead time</dt><dd>{c.lead_complete ? `${c.lead_days} days` : "Incomplete"}</dd>
          <dt>Evidence</dt><dd>{c.evidence_label}{c.lead_evidence_label && <span className="muted block">Lead time: {c.lead_evidence_label}</span>}</dd>
          <dt>Flags</dt><dd>{o.flags.commercially_cheapest ? <Badge tone="info">{o.flags.cheapest_definitive ? "cheapest" : "lowest complete total (not definitive)"}</Badge> : null}{" "}
            {o.flags.fastest ? <Badge tone="info">{o.flags.fastest_definitive ? "fastest" : "fastest among complete (not definitive)"}</Badge> : null}
            {!o.flags.commercially_cheapest && !o.flags.fastest && <span className="muted">—</span>}</dd>
        </dl>
      )}
      {[...c.expired_quotations, ...(c.expired_lead_times ?? [])].length > 0 && <ul className="plain-list small" aria-label="Expired evidence">{[...c.expired_quotations, ...(c.expired_lead_times ?? [])].map((x) => <li key={x}><Badge tone="danger">expired</Badge> {x}</li>)}</ul>}
      {c.missing_inputs.length > 0 && <><h4 className="h-mini">Missing cost inputs</h4><ul className="plain-list small">{c.missing_inputs.map((x) => <li key={x}>{x}</li>)}</ul></>}
    </section>
  );
}

function ReviewForm({ partId, rec, onDone }: { partId: string; rec: Rec; onDone: (v: View) => void }) {
  const { session } = useAuth();
  const own = rec.created_by_id === session?.user.id;
  const [decision, setDecision] = useState("information_requested");
  const [option, setOption] = useState("");
  const [findings, setFindings] = useState("");
  const [reference, setReference] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const needsOption = decision === "approved_for_further_study" || decision === "corrected";
  async function submit() {
    setBusy(true); setError(null);
    try {
      const v = await api<View>(`/parts/${partId}/recommendations/${rec.id}/reviews/`, { body: { decision, option: needsOption ? option : "", findings,
        evidence_references: reference.trim() ? [{ reference: reference.trim() }] : [] } });
      setFindings(""); setReference(""); setOption(""); onDone(v);
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  return (
    <div className="classify-row" aria-label="Engineering review">
      <h3 className="h-sub">Engineering review (version {rec.version})</h3>
      <p className="muted small">"Approved for further study" continues the evaluation; it is not an engineering approval and authorises nothing.
        {own ? " You generated this version: another assigned Aries Engineer must approve it for further study or correct it." : ""}</p>
      <ErrorNotice error={error} />
      <div className="toolbar">
        <label className="small">Decision <select aria-label="Recommendation decision" value={decision} onChange={(e) => setDecision(e.target.value)}>
          <option value="information_requested">Request information</option>
          <option value="approved_for_further_study" disabled={own}>Approve for further study{own ? " (not for your own version)" : ""}</option>
          <option value="corrected" disabled={own}>Correct the recommendation{own ? " (not for your own version)" : ""}</option>
          <option value="rejected">Reject the recommendation</option>
        </select></label>
        {needsOption && <label className="small">Option <select aria-label="Review option" value={option} onChange={(e) => setOption(e.target.value)}>
          <option value="">Choose…</option>
          {OPTS.map(([k, t]) => <option key={k} value={k} disabled={rec.results.options[k].excluded || (decision === "corrected" && !rec.results.options[k].eligible)}>{t}</option>)}
          {decision === "corrected" && <option value="none">None (no route yet)</option>}
        </select></label>}
      </div>
      <textarea aria-label="Review findings" rows={2} placeholder="Findings (required)" value={findings} onChange={(e) => setFindings(e.target.value)} />
      <div className="toolbar">
        <input aria-label="Review evidence reference" placeholder="Evidence reference" value={reference} onChange={(e) => setReference(e.target.value)} />
        <button type="button" className="btn btn-small" disabled={busy || !findings.trim() || (needsOption && !option)} onClick={submit}>Record decision</button>
      </div>
    </div>
  );
}

export function RecommendationPanel({ partId }: { partId: string }) {
  const { can } = useAuth();
  const view = useApi<View>(`/parts/${partId}/recommendations/`);
  const [weights, setWeights] = useState<Record<string, string> | null>(null);
  const [comparison, setComparison] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [info, setInfo] = useState("");

  if (view.loading && !view.data) return <Card title="AI Recommendation & Engineering Review"><Loading /></Card>;
  if (view.error || !view.data) return <Card title="AI Recommendation & Engineering Review"><ErrorNotice error={view.error} /></Card>;
  const d = view.data;
  const rec = d.recommendations[0];
  const w = weights ?? d.default_weights;

  async function generate(tier: string | null) {
    setBusy(tier ?? "rules"); setError(null); setInfo("");
    try {
      const r = await api<{ reused: boolean; recommendation: Rec }>(`/parts/${partId}/recommendations/`,
        { body: { tier, weights: weights ?? null, cost_comparison: comparison || null } });
      setInfo(r.reused ? `Inputs unchanged: version ${r.recommendation.version} was reused.` : `Version ${r.recommendation.version} stored (${r.recommendation.ai_status_label}).`);
      view.reload();
    } catch (e) { setError(e); } finally { setBusy(""); }
  }

  const r = rec?.results;
  const cur = r?.sources.cost_comparison?.currency ?? "";
  return (
    <Card title="AI Recommendation & Engineering Review (Aries internal)">
      <Notice kind="warning"><span role="note">{d.statement}</span></Notice>
      <AiGate ai={d.ai} />
      <ErrorNotice error={error} />
      {info && <Notice kind="success"><span role="status">{info}</span></Notice>}
      {!d.feasibility ? <Empty>Run the manufacturing feasibility assessment first.</Empty> : <>
        {can("intelligence.assess") && (
          <div className="toolbar" aria-label="Generate recommendation">
            <label className="small">Cost comparison <select aria-label="Cost comparison version" value={comparison} onChange={(e) => setComparison(e.target.value)}>
              <option value="">Latest</option>
              {d.cost_comparisons.map((c) => <option key={c.id} value={c.id}>v{c.version} · {c.quantity} units · {c.name.slice(0, 40)}</option>)}</select></label>
            {(["cost", "lead_time", "evidence"] as const).map((k) => (
              <label key={k} className="small">{k === "lead_time" ? "Lead-time" : k === "cost" ? "Cost" : "Evidence"} weight{" "}
                <input aria-label={`${k} weight`} size={4} value={w[k]} onChange={(e) => setWeights({ ...w, [k]: e.target.value })} /></label>))}
            <button type="button" className="btn btn-primary btn-small" disabled={!!busy} onClick={() => generate(null)}>{busy === "rules" ? "Evaluating…" : "Generate recommendation"}</button>
            {d.ai.enabled && <button type="button" className="btn btn-small" disabled={!!busy} onClick={() => generate("lite")}>
              {busy === "lite" ? "Asking…" : `With AI explanation (${d.ai.models.lite})`}</button>}
          </div>
        )}
        <p className="muted small">Weights are applied only among options that meet every mandatory technical, safety, certification and IP requirement.</p>
        {!rec || !r ? <Empty>No recommendation yet.</Empty> : <>
          <div className={`notice ${rec.outcome === "preliminary_recommendation" ? "notice-info" : "notice-warning"}`} data-testid="rec-outcome">
            <strong>{r.outcome.label}</strong>{" "}<ReviewBadge s={rec.review_state} />
            {r.outcome.reasons.length > 0 && <ul className="plain-list small">{r.outcome.reasons.map((x) => <li key={x}>{x}</li>)}</ul>}
          </div>
          <p className="small" data-testid="rec-version">Version <strong>{rec.version}</strong> · {formatDate(rec.created_at)} · {rec.created_by_name} · feasibility v{rec.feasibility_version}
            {r.sources.cost_comparison ? ` · cost comparison v${r.sources.cost_comparison.version} (${r.sources.cost_comparison.quantity} units, ${r.sources.cost_comparison.currency})` : " · no cost comparison"}
            {r.sources.cost_comparison?.synthetic && <> <Badge tone="warning">synthetic figures</Badge></>}
            {r.sources.intelligence ? ` · Phase 2 suggestion ${r.sources.intelligence.model}` : ""} · {rec.passport_number ? `passport ${rec.passport_number} rev ${rec.passport_revision_number}` : "no passport"} · {rec.ai_status_label}</p>
          {rec.stale.map((x) => <Notice key={x} kind="info"><span role="status">{x} Generate a new version to use it.</span></Notice>)}
          <table className="table compact" aria-label="Recommendation statuses">
            <tbody>
              <tr><th>Commercially cheapest</th><td data-testid="status-cheapest">{r.statuses.commercially_cheapest.text}</td></tr>
              <tr><th>Fastest</th><td data-testid="status-fastest">{r.statuses.fastest.text}</td></tr>
              <tr><th>Potentially suitable</th><td data-testid="status-suitable">{r.statuses.potentially_suitable.text}</td></tr>
              <tr><th>Engineering-approved</th><td data-testid="status-approved">{r.statuses.engineering_approved.text}</td></tr>
            </tbody>
          </table>
          <div className="grid-3 feasibility-grid">{OPTS.map(([k, t]) => <OptionColumn key={k} k={k} title={t} o={r.options[k]} cur={cur} />)}</div>
          <p className="small">Weights {Object.entries(r.weights).map(([k, v]) => `${k.replace("_", " ")} ${Number(v).toFixed(2)}`).join(", ")} · {r.weights_note}</p>
          <p className="small">Confidence: technical {r.confidence.technical}; commercial {r.confidence.commercial}; overall <strong>{r.confidence.overall}</strong>.
            {" "}Part: {r.phase2.family || "family not recognised"}, category {r.phase2.category}{r.phase2.category_verified ? " (engineer-verified)" : " (not verified)"}, record completeness {r.phase2.completeness}/100.
            {r.phase2.ai_suggestion && ` Phase 2 AI suggestion (context only): ${r.phase2.ai_suggestion.part_family}, AM screening ${r.phase2.ai_suggestion.am_screening}.`}</p>
          <details className="small"><summary>Risks ({r.risks.length}) and missing information ({r.missing_information.length})</summary>
            <ul className="plain-list" aria-label="Recommendation risks">{r.risks.map((x) => <li key={x}>{x}</li>)}</ul>
            <ul className="plain-list" aria-label="Recommendation missing information">{r.missing_information.map((x) => <li key={x}>{x}</li>)}</ul></details>
          {rec.ai_status === "ok" && rec.ai.response && (
            <div className="ai-suggestion small" data-testid="rec-ai">
              <p><Badge tone="info">AI explanation · preliminary, not verified</Badge> {rec.ai.response.summary}</p>
              <ul className="plain-list">{OPTS.map(([k, t]) => rec.ai.response?.[k] && <li key={k}><strong>{t}:</strong> {rec.ai.response[k]!.technical_explanation} {rec.ai.response[k]!.commercial_explanation}</li>)}</ul>
              {(rec.ai.response.information_to_obtain ?? []).length > 0 && <p>To obtain: {rec.ai.response.information_to_obtain!.join("; ")}</p>}
              <p className="muted">{rec.ai.model_version || rec.ai.model} · {rec.ai.usage?.prompt_tokens} in / {rec.ai.usage?.output_tokens} out tokens · estimated {usd(rec.ai.usage?.cost_usd)}
                {(rec.ai.removed ?? []).length > 0 ? ` · ${rec.ai.removed!.length} statement(s) removed (prices, recommendations, approval claims or contradictions)` : ""}</p>
            </div>
          )}
          {rec.ai_status !== "none" && rec.ai_status !== "ok" && <Notice kind="warning"><span role="status">AI explanation not available ({rec.ai.error_code}). The deterministic result above stands.</span></Notice>}
          {rec.ai_consistency.length > 0 && <Notice kind="warning"><span role="status">Stored AI text contradicts the recorded technical status: {rec.ai_consistency.map((x) => `“${x.sentence}”`).join("; ")}</span></Notice>}
          {can("intelligence.review") && <ReviewForm partId={partId} rec={rec} onDone={(v) => view.setData(v)} />}
          {rec.reviews.length > 0 && (
            <ul className="plain-list small" aria-label="Review history">{rec.reviews.map((x) => (
              <li key={x.id}><Badge tone={x.decision === "rejected" ? "danger" : "info"}>{x.decision_label}</Badge>{x.option_label ? ` ${x.option_label}` : ""}
                {x.option && x.option !== "none" && !x.option_eligible ? " (not technically qualified)" : ""} · {x.reviewer}{x.independent ? " (independent)" : " (generated it)"}, {formatDate(x.created_at)}
                <span className="block">{x.findings}</span></li>))}</ul>
          )}
          {d.recommendations.length > 1 && (
            <details className="small"><summary>Earlier versions ({d.recommendations.length - 1})</summary>
              <table className="table" aria-label="Earlier recommendation versions"><thead><tr><th>Version</th><th>Outcome</th><th>Sources</th><th>Review</th><th>Date</th></tr></thead>
                <tbody>{d.recommendations.slice(1).map((x) => (
                  <tr key={x.id}><td>{x.version}</td><td>{x.results.outcome.label}</td><td>feasibility v{x.feasibility_version}{x.cost_comparison_version ? `, cost v${x.cost_comparison_version}` : ""}</td>
                    <td>{x.review_state.label}</td><td>{formatDate(x.created_at)}</td></tr>))}</tbody></table></details>
          )}
        </>}
      </>}
    </Card>
  );
}

type QRow = { id: string; part_number: string; name: string; review_state: { code: string; label: string; reviewed: boolean };
  recommendation: { version: number; outcome: string; outcome_label: string; cheapest: string; fastest: string; potentially_suitable: string; created_at: string } | null };
const STATES: [string, string][] = [["", "All"], ["preliminary", "Preliminary: not reviewed"], ["information_requested", "Information requested"],
  ["approved_for_further_study", "Approved for further study"], ["corrected", "Corrected"], ["rejected", "Rejected"], ["not_generated", "Not generated"]];

export function RecommendationQueue() {
  const [state, setState] = useState("");
  const q = useApi<{ parts: QRow[]; counts: Record<string, number> }>(`/intelligence/recommendations/${state ? `?state=${state}` : ""}`);
  return (
    <Card title="Engineering review queue (recommendations)" actions={
      <label className="small">Show <select aria-label="Queue state" value={state} onChange={(e) => setState(e.target.value)}>
        {STATES.map(([k, l]) => <option key={k} value={k}>{l}{q.data && k ? ` (${q.data.counts[k] ?? 0})` : ""}</option>)}</select></label>}>
      <p className="muted small">Latest recommendation version per part. Preliminary until reviewed; "approved for further study" is not an engineering approval.</p>
      {q.loading && !q.data ? <Loading /> : q.error || !q.data ? <ErrorNotice error={q.error} /> : q.data.parts.length === 0 ? <Empty>Nothing in this state.</Empty> : (
        <div className="table-scroll">
          <table className="table" aria-label="Engineering review queue">
            <thead><tr><th>Material number</th><th>Outcome</th><th>Potentially suitable</th><th>Cheapest / fastest</th><th>Review</th></tr></thead>
            <tbody>{q.data.parts.map((p) => (
              <tr key={p.id}>
                <td><Link to={`/parts/${p.id}`}><strong>{p.part_number}</strong></Link><div className="small">{p.name}</div></td>
                <td className="small">{p.recommendation ? <>{p.recommendation.outcome_label}<div className="muted">v{p.recommendation.version} · {formatDate(p.recommendation.created_at)}</div></> : <span className="muted">Not generated</span>}</td>
                <td className="small">{p.recommendation?.potentially_suitable ?? "—"}</td>
                <td className="small">{p.recommendation ? <><div>{p.recommendation.cheapest}</div><div className="muted">{p.recommendation.fastest}</div></> : "—"}</td>
                <td><Badge tone={p.review_state.reviewed ? "info" : "warning"}>{p.review_state.label}</Badge></td>
              </tr>))}</tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
