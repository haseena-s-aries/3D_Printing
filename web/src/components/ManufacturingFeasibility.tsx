/**
 * Manufacturing feasibility (CN-007 Phase 3), Aries-internal, inside the Part Intelligence workspace. Three comparable
 * panels (OEM procurement, additive manufacturing, conventional manufacturing) from deterministic rules; an optional
 * Gemini view is shown as preliminary and can only make a status more cautious. Each run is a stored version.
 * Engineering review is technical only: no approval, eligibility, publication or release action exists here.
 */
import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { AiGate, type AiStatus, usd } from "./PartIntelligence";
import { Badge, Card, Empty, ErrorNotice, Loading, Notice, formatDate, label } from "./ui";

type Tone = "neutral" | "info" | "success" | "warning" | "danger";
type Evidence = { key: string; label: string; state: "verified" | "recorded" | "mentioned" | "missing"; state_label: string; value: string; source: string; note: string };
type Constraint = { code: string; kind: string; text: string; verified?: boolean; applies_to?: string[] };
type Review = { id: string; alternative: string; alternative_label: string; decision: string; decision_label: string; corrected_status: string;
  corrected_status_label: string; findings: string; note: string; evidence_references: { reference: string; title?: string }[]; independent: boolean;
  reviewer: string; reviewer_id: string | null; created_at: string };
type AiAlt = { suggested_status?: string; candidate_processes?: string[]; candidate_methods?: string[]; considerations: string[];
  post_processing?: string[]; inspection_and_testing?: string[]; risks?: string[]; information_needed: string[]; rationale?: string };
type Panel = { status: string; status_label: string; rule_status?: string; evidence: Evidence[]; constraints: Constraint[]; missing: string[];
  risks: string[]; next_actions: string[]; note?: string; review: Review | null; ai?: AiAlt;
  candidate_processes?: { process: string; label: string }[]; process_basis?: string;
  candidate_methods?: { method: string; label: string; basis: string; needs: string }[]; method_basis?: string; qualification?: string[] };
type AiProv = { provider?: string; tier?: string; model?: string; model_version?: string; prompt_version?: string; sent?: unknown; removed?: string[];
  adjustments?: { alternative: string; kind: string; text: string }[]; confidence?: number | null; uncertainty?: string; qualification_requirements?: string[];
  usage?: { prompt_tokens: number; output_tokens: number; thinking_tokens: number; cost_usd: number | null; latency_ms: number; attempts: number };
  error_code?: string; error_message?: string };
export type Feasibility = { id: string; version: number; methodology_version: string; rules_version: string; project: string; passport_number: string;
  passport_revision_number: number | null; input_hash: string; inputs: unknown; created_at: string; created_by_name: string; created_by_id: string | null;
  oem: Panel; additive: Panel; conventional: Panel; constraints: Constraint[]; missing_information: string[]; next_actions: string[];
  ai_status: string; ai_status_label: string; ai: AiProv; reviews: Review[]; overall_review: Review | null; review_note: string;
  inputs_current: boolean | null; authorisation: { manufacturing_authorised: boolean; text: string } };
type View = { ai: AiStatus; statuses: { oem: Record<string, string>; manufacturing: Record<string, string> }; assessments: Feasibility[];
  inputs_changed: boolean; review_note: string };

const STATUS_TONE: Record<string, Tone> = {
  not_verified: "neutral", identified_confirmation_required: "info", potentially_suitable: "info", potentially_suitable_redesign: "info",
  insufficient_information: "neutral", specialist_assessment: "warning", not_suitable_verified: "danger",
};
const STATE_TONE: Record<string, Tone> = { verified: "success", recorded: "info", mentioned: "warning", missing: "neutral" };
const DECISIONS: [string, string][] = [["more_information_required", "Additional information required"], ["finding", "Record technical finding"],
  ["corrected", "Correct the preliminary result"], ["rejected", "Reject the preliminary result"], ["confirmed", "Confirm (technical review)"]];
const ALTS: [keyof Pick<Feasibility, "oem" | "additive" | "conventional">, string][] = [["oem", "A. OEM procurement"],
  ["additive", "B. Additive manufacturing"], ["conventional", "C. Conventional manufacturing"]];
const TIER_LABEL: Record<string, string> = { lite: "Flash-Lite", flash: "Flash", pro: "Pro" };

function List({ items, empty, name }: { items?: string[]; empty?: string; name: string }) {
  if (!items?.length) return empty ? <p className="muted small">{empty}</p> : null;
  return <ul className="plain-list small" aria-label={name}>{items.map((x) => <li key={x}>{x}</li>)}</ul>;
}

function ReviewStatus({ r }: { r: Review | null }) {
  if (!r) return <p className="small"><Badge>Not reviewed</Badge></p>;
  return (
    <p className="small"><Badge tone={r.decision === "confirmed" ? "success" : r.decision === "rejected" ? "danger" : "warning"}>{r.decision_label}</Badge>
      {r.corrected_status_label && <> → <strong>{r.corrected_status_label}</strong></>}
      <span className="muted"> · {r.reviewer}, {formatDate(r.created_at)}{r.independent ? " · independent" : " · by the engineer who ran it"}</span>
      {r.findings && <span className="block">{r.findings}</span>}</p>
  );
}

function AltPanel({ title, p, alt }: { title: string; p: Panel; alt: string }) {
  return (
    <section className="card feasibility-panel" aria-label={title} data-testid={`feasibility-${alt}`}>
      <h3 className="h-sub">{title}</h3>
      <p><Badge tone={STATUS_TONE[p.status] ?? "neutral"}>{p.status_label}</Badge>
        <span className="muted small"> preliminary screening{p.rule_status && p.rule_status !== p.status ? ` (rules: ${label(p.rule_status)})` : ""}</span></p>
      {p.note && <p className="muted small">{p.note}</p>}
      <h4 className="h-mini">Supporting evidence</h4>
      <ul className="plain-list small evidence-list" aria-label={`${title} evidence`}>
        {p.evidence.map((e) => (
          <li key={e.key}><Badge tone={STATE_TONE[e.state]}>{e.state_label}</Badge> <strong>{e.label}</strong>{e.value ? `: ${e.value}` : ""}
            {(e.note || e.source) && <span className="muted block">{[e.source, e.note].filter(Boolean).join(" · ")}</span>}</li>
        ))}
      </ul>
      {(p.candidate_processes || p.candidate_methods) && <>
        <h4 className="h-mini">{p.candidate_processes ? "Possible AM process families" : "Possibly applicable methods"}</h4>
        <List name="Candidate methods" items={(p.candidate_processes ?? []).map((x) => x.label).concat((p.candidate_methods ?? []).map((m) => `${m.label}: ${m.basis} Needs ${m.needs}.`))}
          empty="None identified from the evidence held." />
        <p className="muted small">{p.process_basis ?? p.method_basis}</p>
      </>}
      <h4 className="h-mini">Technical constraints</h4>
      {p.constraints.length ? (
        <ul className="plain-list small" aria-label={`${title} constraints`}>{p.constraints.map((c) => (
          <li key={c.code}><Badge tone={c.kind === "block" ? "danger" : c.kind === "review" ? "warning" : "neutral"}>{c.kind === "block" ? "verified, disqualifying" : c.kind}</Badge> {c.text}</li>))}</ul>
      ) : <p className="muted small">None from the evidence held.</p>}
      <h4 className="h-mini">Missing information</h4>
      <List name={`${title} missing information`} items={p.missing} empty="Nothing listed." />
      <h4 className="h-mini">Risks</h4>
      <List name={`${title} risks`} items={p.risks} empty="None identified." />
      <h4 className="h-mini">Required next actions</h4>
      <List name={`${title} next actions`} items={p.next_actions} />
      {p.ai && (
        <div className="ai-suggestion">
          <p className="small"><Badge tone="info">AI view · preliminary, not verified</Badge>
            {p.ai.suggested_status && <> suggested: <strong>{label(p.ai.suggested_status)}</strong></>}</p>
          {p.ai.rationale && <p className="small">{p.ai.rationale}</p>}
          <List name="AI considerations" items={[...p.ai.considerations, ...(p.ai.post_processing ?? []).map((x) => `Post-processing: ${x}`),
            ...(p.ai.inspection_and_testing ?? []).map((x) => `Inspection / testing: ${x}`), ...(p.ai.risks ?? []).map((x) => `Risk: ${x}`)]} />
          <List name="AI information needed" items={p.ai.information_needed.map((x) => `Needed: ${x}`)} />
        </div>
      )}
      <h4 className="h-mini">Engineering review</h4>
      <ReviewStatus r={p.review} />
    </section>
  );
}

function ReviewForm({ partId, a, statuses, onDone }: { partId: string; a: Feasibility; statuses: View["statuses"]; onDone: (v: View) => void }) {
  const { session } = useAuth();
  const [alternative, setAlternative] = useState("overall");
  const [decision, setDecision] = useState("more_information_required");
  const [corrected, setCorrected] = useState("");
  const [findings, setFindings] = useState("");
  const [reference, setReference] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const own = a.created_by_id === session?.user.id;
  const options = alternative === "oem" ? statuses.oem : statuses.manufacturing;

  async function submit() {
    setBusy(true); setError(null);
    try {
      const r = await api<View & { review: Review }>(`/parts/${partId}/feasibility/${a.id}/reviews/`, { body: {
        alternative, decision, corrected_status: decision === "corrected" ? corrected : "", findings,
        evidence_references: reference.trim() ? [{ reference: reference.trim() }] : [] } });
      setFindings(""); setReference(""); setCorrected("");
      onDone(r);
    } catch (e) { setError(e); } finally { setBusy(false); }
  }

  return (
    <div className="classify-row" aria-label="Technical review">
      <h3 className="h-sub">Record technical review (version {a.version})</h3>
      <p className="muted small">{a.review_note}{own ? " You ran this version: another assigned Aries Engineer must confirm it or correct it to a more favourable status." : ""}</p>
      <ErrorNotice error={error} />
      <div className="toolbar">
        <label className="small">Alternative{" "}
          <select aria-label="Review alternative" value={alternative} onChange={(e) => { setAlternative(e.target.value); setCorrected(""); }}>
            <option value="overall">Whole assessment</option>
            {ALTS.map(([k, t]) => <option key={k} value={k}>{t}</option>)}
          </select></label>
        <label className="small">Decision{" "}
          <select aria-label="Review decision" value={decision} onChange={(e) => setDecision(e.target.value)}>
            {DECISIONS.filter(([k]) => !(alternative === "overall" && k === "corrected")).map(([k, t]) => (
              <option key={k} value={k} disabled={k === "confirmed" && own}>{t}{k === "confirmed" && own ? " (not for your own run)" : ""}</option>))}
          </select></label>
        {decision === "corrected" && alternative !== "overall" && (
          <label className="small">Corrected status{" "}
            <select aria-label="Corrected status" value={corrected} onChange={(e) => setCorrected(e.target.value)}>
              <option value="">Choose…</option>
              {Object.entries(options).map(([k, t]) => <option key={k} value={k}>{t}</option>)}
            </select></label>
        )}
      </div>
      <textarea aria-label="Technical findings" rows={2} placeholder="Technical findings / note" value={findings} onChange={(e) => setFindings(e.target.value)} />
      <div className="toolbar">
        <input aria-label="Evidence reference" placeholder="Evidence reference (document, drawing number, inspection…)" value={reference} onChange={(e) => setReference(e.target.value)} />
        <button type="button" className="btn btn-small" disabled={busy || (decision === "corrected" && !corrected)} onClick={submit}>Record review</button>
      </div>
    </div>
  );
}

export function FeasibilityPanel({ partId }: { partId: string }) {
  const { can } = useAuth();
  const view = useApi<View>(`/parts/${partId}/feasibility/`);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [info, setInfo] = useState("");

  async function run(tier: string | null) {
    setBusy(tier ?? "rules"); setError(null); setInfo("");
    try {
      const r = await api<{ reused: boolean; assessment: Feasibility }>(`/parts/${partId}/feasibility/assess/`, { body: { tier } });
      setInfo(r.reused ? `Inputs unchanged: version ${r.assessment.version} was reused${tier ? " (no new AI call)" : ""}.`
        : `Version ${r.assessment.version} stored${r.assessment.ai_status !== "none" ? ` (${r.assessment.ai_status_label})` : ""}.`);
      view.reload();
    } catch (e) { setError(e); } finally { setBusy(""); }
  }

  if (view.loading && !view.data) return <Card title="Manufacturing feasibility"><Loading /></Card>;
  if (view.error || !view.data) return <Card title="Manufacturing feasibility"><ErrorNotice error={view.error} /></Card>;
  const d = view.data;
  const a = d.assessments[0];
  return (
    <Card title="Manufacturing feasibility (Aries internal)" actions={can("intelligence.assess") ? (
      <div className="toolbar">
        <button type="button" className="btn btn-primary btn-small" disabled={!!busy} onClick={() => run(null)}>{busy === "rules" ? "Assessing…" : "Run assessment (rules)"}</button>
        {d.ai.enabled && Object.entries(TIER_LABEL).map(([t, l]) => (
          <button key={t} type="button" className="btn btn-small" disabled={!!busy} onClick={() => run(t)}>
            {busy === t ? "Asking…" : t === "lite" ? `With AI view (${d.ai.models.lite})` : `Escalate: ${d.ai.models[t] ?? l}`}</button>))}
      </div>) : undefined}>
      <p className="muted small section-note">Preliminary screening of three alternatives. Statuses come from engineering rules on the evidence
        held; an AI view may add explanations and can only make a status more cautious. No costs or savings are shown in this phase.</p>
      <AiGate ai={d.ai} />
      <ErrorNotice error={error} />
      {info && <Notice kind="success"><span role="status">{info}</span></Notice>}
      {!a ? <Empty>No feasibility assessment yet.</Empty> : <>
        <Notice kind="warning"><span role="note">{a.authorisation.text}</span></Notice>
        {d.inputs_changed && <Notice kind="info"><span role="status">The part's evidence has changed since version {a.version}: run the assessment again for a new version.</span></Notice>}
        <p className="small" data-testid="feasibility-version">Version <strong>{a.version}</strong> · {formatDate(a.created_at)} · {a.created_by_name} ·
          methodology {a.methodology_version} · rules {a.rules_version}{a.project ? ` · project ${a.project}` : ""}
          {a.passport_number ? ` · passport ${a.passport_number} rev ${a.passport_revision_number ?? "—"}` : " · no passport"} ·{" "}
          <Badge tone={a.ai_status === "ok" ? "info" : a.ai_status === "none" ? "neutral" : "warning"}>{a.ai_status_label}{a.ai.model ? `: ${a.ai.model_version || a.ai.model}` : ""}</Badge></p>
        {a.ai_status !== "none" && a.ai_status !== "ok" && (
          <Notice kind="warning"><span role="status">AI view not available ({a.ai.error_message || a.ai.error_code}). The rule-based screening below is complete without it.</span></Notice>)}
        <div className="grid-3 feasibility-grid">
          {ALTS.map(([k, t]) => <AltPanel key={k} title={t} p={a[k]} alt={k} />)}
        </div>
        <div className="grid-2">
          <div>
            <h3 className="h-sub">Constraints and disqualifying conditions</h3>
            {a.constraints.length ? <ul className="plain-list small" aria-label="Constraints and disqualifying conditions">{a.constraints.map((c) => (
              <li key={c.code}><Badge tone={c.kind === "block" ? "danger" : "warning"}>{c.kind === "block" ? "verified, disqualifying" : "specialist review"}</Badge> {c.text}
                <span className="muted"> ({(c.applies_to ?? []).map(label).join(", ")})</span></li>))}</ul> : <p className="muted small">None.</p>}
            <h3 className="h-sub">Whole assessment: review</h3>
            <ReviewStatus r={a.overall_review} />
          </div>
          <div>
            <h3 className="h-sub">Missing technical information ({a.missing_information.length})</h3>
            <List name="Missing technical information" items={a.missing_information} />
          </div>
        </div>
        {a.ai_status === "ok" && (
          <details className="small"><summary>AI provenance: {a.ai.model_version || a.ai.model}, {a.ai.usage?.prompt_tokens} in / {a.ai.usage?.output_tokens} out tokens, estimated {usd(a.ai.usage?.cost_usd)}</summary>
            <List name="AI adjustments" items={(a.ai.adjustments ?? []).map((x) => `${label(x.alternative)}: ${x.text}`)} empty="AI view matched the rule statuses." />
            {(a.ai.removed ?? []).length > 0 && <p className="muted">{a.ai.removed!.length} statement(s) removed (prices or unsupported approval/suitability claims).</p>}
            <p className="muted">Confidence {Math.round((a.ai.confidence ?? 0) * 100)}% · {a.ai.uncertainty} · prompt {a.ai.prompt_version} · {a.ai.usage?.latency_ms} ms ·
              {" "}{a.ai.usage?.attempts} attempt(s) · input hash {a.input_hash.slice(0, 12)}…</p>
            <p className="muted">Data sent (whitelist):</p>
            <pre className="mono small">{JSON.stringify(a.ai.sent, null, 1)}</pre>
          </details>
        )}
        {can("intelligence.review") && <ReviewForm partId={partId} a={a} statuses={d.statuses} onDone={(v) => view.setData(v)} />}
        {a.reviews.length > 0 && (
          <details className="small"><summary>Review history of version {a.version} ({a.reviews.length})</summary>
            <ul className="plain-list">{a.reviews.map((r) => <li key={r.id}><strong>{r.alternative_label}</strong>: <ReviewStatus r={r} />
              {r.evidence_references.length > 0 && <span className="muted">Evidence: {r.evidence_references.map((x) => x.title ?? x.reference).join("; ")}</span>}</li>)}</ul>
          </details>
        )}
        {d.assessments.length > 1 && (
          <details className="small"><summary>Earlier versions ({d.assessments.length - 1})</summary>
            <table className="table" aria-label="Earlier feasibility versions">
              <thead><tr><th>Version</th><th>Date</th><th>OEM</th><th>Additive</th><th>Conventional</th><th>AI</th></tr></thead>
              <tbody>{d.assessments.slice(1).map((x) => (
                <tr key={x.id}><td>{x.version}</td><td>{formatDate(x.created_at)}</td><td>{x.oem.status_label}</td><td>{x.additive.status_label}</td>
                  <td>{x.conventional.status_label}</td><td>{x.ai.model ?? "rules only"}</td></tr>))}</tbody>
            </table>
          </details>
        )}
      </>}
    </Card>
  );
}

type OvRow = { id: string; part_number: string; name: string; assessment: null | { id: string; version: number; created_at: string; ai_status: string; model: string;
  oem: { status: string; label: string }; additive: { status: string; label: string }; conventional: { status: string; label: string };
  missing_count: number; reviews: Record<string, string> } };

export function FeasibilityOverview() {
  const { can } = useAuth();
  const ov = useApi<{ ai: AiStatus; parts: OvRow[] }>("/intelligence/feasibility/");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [summary, setSummary] = useState("");

  async function batch(tier: string | null) {
    if (!ov.data) return;
    setBusy(tier ?? "rules"); setError(null); setSummary("");
    try {
      const r = await api<{ results: { part_number?: string; reused?: boolean; error?: { message: string } }[] }>("/intelligence/feasibility/assess-batch/",
        { body: { tier, parts: ov.data.parts.slice(0, 10).map((p) => p.id) } });
      const ok = r.results.filter((x) => !x.error);
      setSummary(`${ok.length} assessment(s): ${ok.filter((x) => !x.reused).length} new version(s), ${ok.filter((x) => x.reused).length} reused.` +
        r.results.filter((x) => x.error).map((x) => ` ${x.part_number ?? ""} ${x.error!.message}`).join(""));
      ov.reload();
    } catch (e) { setError(e); } finally { setBusy(""); }
  }

  if (ov.loading && !ov.data) return <Loading />;
  if (ov.error || !ov.data) return <ErrorNotice error={ov.error} />;
  const d = ov.data;
  const cell = (s: { status: string; label: string }) => <Badge tone={STATUS_TONE[s.status] ?? "neutral"}>{s.label}</Badge>;
  return (
    <Card title="Manufacturing feasibility" actions={can("intelligence.assess") && d.parts.length > 0 ? (
      <div className="toolbar">
        <button type="button" className="btn btn-primary btn-small" disabled={!!busy} onClick={() => batch(null)}>{busy === "rules" ? "Assessing…" : "Assess all (rules)"}</button>
        {d.ai.enabled && <button type="button" className="btn btn-small" disabled={!!busy} onClick={() => batch("lite")}>{busy === "lite" ? "Asking…" : `Assess all with AI view (${d.ai.models.lite})`}</button>}
      </div>) : undefined}>
      <p className="muted small">Preliminary screening of OEM procurement, additive and conventional manufacturing. Not an approval, authorisation or
        release; no costs or savings in this phase. Open a part for evidence, missing information and review.</p>
      <ErrorNotice error={error} />
      {summary && <Notice kind="success"><span role="status">{summary}</span></Notice>}
      {d.parts.length === 0 ? <Empty>No imported parts yet.</Empty> : (
        <div className="table-scroll">
          <table className="table" aria-label="Manufacturing feasibility">
            <thead><tr><th>Material number</th><th>A. OEM procurement</th><th>B. Additive</th><th>C. Conventional</th><th>Missing</th><th>Review</th><th>Version</th></tr></thead>
            <tbody>{d.parts.map((p) => (
              <tr key={p.id}>
                <td><Link to={`/parts/${p.id}`}><strong>{p.part_number}</strong></Link><div className="small">{p.name}</div></td>
                {p.assessment ? <>
                  <td>{cell(p.assessment.oem)}</td><td>{cell(p.assessment.additive)}</td><td>{cell(p.assessment.conventional)}</td>
                  <td>{p.assessment.missing_count} item(s)</td>
                  <td className="small">{Object.keys(p.assessment.reviews).length ? Object.entries(p.assessment.reviews).map(([k, v]) => `${label(k)}: ${v}`).join("; ") : <span className="muted">Not reviewed</span>}</td>
                  <td className="small">v{p.assessment.version}<div className="muted">{p.assessment.model || "rules only"}</div></td>
                </> : <td colSpan={6} className="muted">Not assessed yet</td>}
              </tr>))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
