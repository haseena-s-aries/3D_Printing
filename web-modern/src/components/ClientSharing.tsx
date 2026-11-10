/**
 * CN-007 controlled disclosure of AI assessment results (AI_CLIENT_ACCESS_ENABLED). Information sharing only: approving
 * or sharing a result never approves, publishes, authorises or releases anything (OQ-35, OQ-36).
 *
 * - SharedResultView: the client-safe snapshot, exactly as a client sees it (also the engineer's preview).
 * - DisclosurePanel: on the part page for assigned Aries Engineers — state, preview, approve for client sharing (by an
 *   engineer who did not generate the version), share, withdraw, and the history.
 */
import { useState } from "react";

import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Icon } from "./icons";
import { useToast } from "./theme";
import { Badge, Card, Empty, ErrorNotice, Field, Loading, Notice, formatDate } from "./ui";

type Requirement = { label: string; met: boolean };
type OptionView = { title: string; technical_status: string; suitability: "potentially_suitable" | "not_qualified" | "excluded";
  suitability_label: string; requirements: Requirement[] };
export type Snapshot = { part_number: string; part_name: string; summary: string; outcome: { code: string; label: string };
  options: Record<string, OptionView>; evidence_gaps: string[]; recommendation_version: number; feasibility_version: number;
  cost_comparison_version: number | null; assessed_on: string; statement: string };
export type Price = { option: string; option_title: string; amount: string; currency: string; lead_time_days: number | null;
  valid_until: string | null; quote_reference: string };
type Share = { id: string; status: "approved" | "shared" | "withdrawn" | "superseded"; status_label: string; recommendation_version: number;
  snapshot: Snapshot; released_prices: Price[]; shared_at: string | null; withdrawn_at: string | null; withdrawn_reason: string;
  created_at: string; approved_by: string; shared_by: string; events: { event: string; note: string; actor: string; at: string }[] };
type PartDisclosure = { workspace_enabled: boolean; sharing_permitted: boolean; state: { code: string; label: string };
  latest_recommendation: { id: string; version: number; review_state: { code: string; label: string; reviewed: boolean }; created_by_name: string } | null;
  can_approve: boolean; approve_block: string | null; preview: Snapshot | null; shares: Share[]; options: Record<string, string>; statement: string };

/** Never green for suitability: "potentially suitable" still needs engineering qualification. */
const SUIT_TONE = { potentially_suitable: "info", not_qualified: "warning", excluded: "danger" } as const;
export const STATE_TONE: Record<string, "neutral" | "info" | "success" | "warning" | "danger"> = {
  not_assessed: "neutral", internal_draft: "neutral", engineering_reviewed: "warning", approved: "info", shared: "info", withdrawn: "danger",
};

export function SharedResultView({ snapshot, prices = [], pricesHidden = false }: { snapshot: Snapshot; prices?: Price[]; pricesHidden?: boolean }) {
  return (
    <div className="shared-result">
      <section className="shared-summary" aria-label="Summary from Aries Engineering">
        <h3 className="h-sub">Summary from Aries Engineering</h3>
        <p>{snapshot.summary || <span className="muted">The engineer's client summary is written when the result is approved for sharing.</span>}</p>
        <p className="shared-outcome"><Icon name="review" size="sm" />{snapshot.outcome.label}</p>
      </section>
      <h3 className="h-sub">Manufacturing options</h3>
      <div className="option-cards">
        {Object.entries(snapshot.options).map(([k, o]) => (
          <section key={k} className="option-card" aria-label={o.title}>
            <h4>{o.title}</h4>
            <Badge tone={SUIT_TONE[o.suitability]}>{o.suitability_label}</Badge>
            <p className="muted small">{o.technical_status}</p>
            <ul className="req-list" aria-label={`${o.title}: mandatory requirements`}>
              {o.requirements.map((q) => (
                <li key={q.label} className={q.met ? "is-met" : "is-unmet"}>
                  <Icon name={q.met ? "check" : "close"} size="sm" /><span>{q.label}</span>
                  <span className="sr-only">{q.met ? "met" : "not met"}</span>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
      <h3 className="h-sub">Evidence gaps</h3>
      {snapshot.evidence_gaps.length ? (
        <ul className="gap-list">{snapshot.evidence_gaps.map((g) => <li key={g}>{g}</li>)}</ul>
      ) : <p className="muted small">None recorded.</p>}
      {(prices.length > 0 || pricesHidden) && <h3 className="h-sub">Quoted prices released by Aries</h3>}
      {prices.length > 0 && (
        <div className="table-scroll">
          <table className="table" aria-label="Released quoted prices">
            <thead><tr><th>Option</th><th>Price</th><th>Lead time</th><th>Valid until</th><th>Quote reference</th></tr></thead>
            <tbody>{prices.map((p) => (
              <tr key={p.option}><td>{p.option_title}</td><td><strong>{p.currency} {Number(p.amount).toLocaleString("en-GB", { minimumFractionDigits: 2 })}</strong></td>
                <td>{p.lead_time_days != null ? `${p.lead_time_days} days` : "—"}</td><td>{p.valid_until ?? "—"}</td><td>{p.quote_reference || "—"}</td></tr>))}
            </tbody>
          </table>
        </div>
      )}
      {pricesHidden && <p className="muted small">Quoted prices were released to your company; your role does not show prices.</p>}
      <p className="muted small">Assessment version {snapshot.recommendation_version} (feasibility v{snapshot.feasibility_version}
        {snapshot.cost_comparison_version ? `, cost comparison v${snapshot.cost_comparison_version}` : ""}) · assessed {snapshot.assessed_on}</p>
      <Notice kind="info">{snapshot.statement}</Notice>
    </div>
  );
}

type PriceDraft = { option: string; amount: string; currency: string; lead_time_days: string; valid_until: string; quote_reference: string };
const EMPTY_PRICE: PriceDraft = { option: "oem", amount: "", currency: "USD", lead_time_days: "", valid_until: "", quote_reference: "" };

export function DisclosurePanel({ partId }: { partId: string }) {
  const toast = useToast();
  const v = useApi<PartDisclosure>(`/parts/${partId}/disclosures/`);
  const [summary, setSummary] = useState("");
  const [prices, setPrices] = useState<PriceDraft[]>([]);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [showPreview, setShowPreview] = useState(false);

  if (v.loading && !v.data) return <Card title="Client sharing"><Loading /></Card>;
  if (v.error || !v.data) return <Card title="Client sharing"><ErrorNotice error={v.error} /></Card>;
  const d = v.data;
  const open = d.shares.find((s) => s.status === "approved");
  const shared = d.shares.find((s) => s.status === "shared");

  async function call(fn: () => Promise<unknown>, done: string) {
    setBusy(true); setError(null);
    try { await fn(); toast(done); setSummary(""); setPrices([]); setReason(""); await v.reload(); } catch (e) { setError(e); } finally { setBusy(false); }
  }
  const approve = () => call(() => api(`/parts/${partId}/disclosures/`, { body: {
    recommendation: d.latest_recommendation?.id, summary,
    released_prices: prices.map((p) => ({ ...p, lead_time_days: p.lead_time_days === "" ? null : Number(p.lead_time_days) })) } }),
  "Approved for client sharing. Not yet visible to the client.");

  return (
    <Card title="Client sharing (information disclosure)" actions={<Badge tone={STATE_TONE[d.state.code] ?? "neutral"}>{d.state.label}</Badge>}>
      <p className="muted small">{d.statement} Only an explicitly shared, frozen snapshot is ever visible to the client; new or changed results stay internal.</p>
      <ErrorNotice error={error} />
      {!d.workspace_enabled && <Notice kind="warning">Client sharing is not switched on for this company. The Aries Admin controls it under AI management.</Notice>}
      <div className="sharing-steps" aria-label="Disclosure steps">
        {[["internal_draft", "Internal draft"], ["engineering_reviewed", "Engineering reviewed"], ["approved", "Approved for client sharing"],
          ["shared", "Shared with client"]].map(([code, name], i) => {
          const order = ["not_assessed", "internal_draft", "engineering_reviewed", "approved", "shared"];
          const reached = order.indexOf(d.state.code) >= order.indexOf(code) || (d.state.code === "shared" && code !== "approved");
          return <span key={code} className={`sharing-step ${d.state.code === code ? "is-current" : reached ? "is-done" : ""}`}>
            <span className="step-num" aria-hidden>{i + 1}</span>{name}</span>;
        })}
      </div>

      {open && (
        <section className="sharing-pending" aria-label="Approved, not yet shared">
          <h3 className="h-sub">Approved for client sharing · version {open.recommendation_version}</h3>
          <p className="muted small">Approved by {open.approved_by} on {formatDate(open.created_at)}. Sharing makes this snapshot visible to the
            company's authorised users and notifies its Client Administrators.</p>
          <div className="toolbar">
            <button type="button" className="btn btn-primary" disabled={busy}
              onClick={() => call(() => api(`/parts/${partId}/disclosures/${open.id}/share/`, { body: {} }), "Shared with the client.")}>
              <Icon name="check" size="sm" />Share with client</button>
          </div>
          <details><summary>Preview what the client will see</summary><SharedResultView snapshot={open.snapshot} prices={open.released_prices} /></details>
        </section>
      )}

      {!open && d.latest_recommendation && (
        <section aria-label="Approve for client sharing">
          <h3 className="h-sub">Approve version {d.latest_recommendation.version} for client sharing</h3>
          <p className="muted small">{d.latest_recommendation.review_state.label} · generated by {d.latest_recommendation.created_by_name}</p>
          {d.can_approve ? (
            <div className="form-grid">
              <div className="span-2">
                <Field label="Client summary" hint="Plain-language findings for the client. Shared exactly as written; no internal costs, suppliers or margins.">
                  <textarea rows={3} value={summary} onChange={(e) => setSummary(e.target.value)} maxLength={2000} />
                </Field>
              </div>
              <div className="span-2">
                <h4 className="h-mini">Client-facing quoted prices (optional, explicit release)</h4>
                {prices.map((p, i) => {
                  const upd = (patch: Partial<PriceDraft>) => setPrices(prices.map((x, j) => (j === i ? { ...x, ...patch } : x)));
                  return (
                    <div key={i} className="price-row" role="group" aria-label={`Released price ${i + 1}`}>
                      <select aria-label="Option" value={p.option} onChange={(e) => upd({ option: e.target.value })}>
                        {Object.entries(d.options).map(([k, t]) => <option key={k} value={k}>{t}</option>)}</select>
                      <input aria-label="Amount" inputMode="decimal" placeholder="Amount" value={p.amount} onChange={(e) => upd({ amount: e.target.value })} />
                      <input aria-label="Currency" maxLength={3} value={p.currency} onChange={(e) => upd({ currency: e.target.value.toUpperCase() })} />
                      <input aria-label="Lead time (days)" inputMode="numeric" placeholder="Lead days" value={p.lead_time_days} onChange={(e) => upd({ lead_time_days: e.target.value })} />
                      <input aria-label="Valid until" type="date" value={p.valid_until} onChange={(e) => upd({ valid_until: e.target.value })} />
                      <input aria-label="Quote reference" placeholder="Client quote ref." value={p.quote_reference} onChange={(e) => upd({ quote_reference: e.target.value })} />
                      <button type="button" className="btn btn-ghost btn-small" onClick={() => setPrices(prices.filter((_, j) => j !== i))}>Remove</button>
                    </div>
                  );
                })}
                {prices.length < Object.keys(d.options).length && (
                  <button type="button" className="btn btn-small" onClick={() => setPrices([...prices, EMPTY_PRICE])}><Icon name="plus" size="sm" />Add a released price</button>
                )}
              </div>
              <div className="form-actions span-2">
                <button type="button" className="btn btn-ghost" onClick={() => setShowPreview((s) => !s)} aria-expanded={showPreview}>
                  {showPreview ? "Hide client preview" : "Preview what the client will see"}</button>
                <button type="button" className="btn btn-primary" disabled={busy || !summary.trim()} onClick={approve}>Approve for client sharing</button>
              </div>
              {showPreview && d.preview && <div className="span-2 preview-box"><SharedResultView snapshot={{ ...d.preview, summary }} /></div>}
            </div>
          ) : <Notice kind="info">{d.approve_block}</Notice>}
        </section>
      )}
      {!d.latest_recommendation && <Empty icon="route">Generate and review a recommendation first.</Empty>}

      {(open || shared) && (
        <section aria-label="Withdraw">
          <h3 className="h-sub">Withdraw {shared && !open ? "the shared result" : "the approval"}</h3>
          <div className="toolbar">
            <input aria-label="Reason for withdrawal" placeholder="Reason (shown to the client if the result was shared)" value={reason} onChange={(e) => setReason(e.target.value)} />
            <button type="button" className="btn btn-danger" disabled={busy || !reason.trim()}
              onClick={() => call(() => api(`/parts/${partId}/disclosures/${(open ?? shared)!.id}/withdraw/`, { body: { reason } }), "Withdrawn.")}>Withdraw</button>
          </div>
        </section>
      )}

      {d.shares.length > 0 && (
        <details className="small">
          <summary>Disclosure history ({d.shares.length})</summary>
          <table className="table" aria-label="Disclosure history">
            <thead><tr><th>Version</th><th>Status</th><th>Events</th></tr></thead>
            <tbody>{d.shares.map((s) => (
              <tr key={s.id}><td>v{s.recommendation_version}</td><td><Badge tone={STATE_TONE[s.status] ?? "neutral"}>{s.status_label}</Badge></td>
                <td>{s.events.map((e, i) => <div key={i}>{e.event} · {e.actor} · {formatDate(e.at)}{e.note ? ` — ${e.note}` : ""}</div>)}</td></tr>))}
            </tbody>
          </table>
        </details>
      )}
    </Card>
  );
}
