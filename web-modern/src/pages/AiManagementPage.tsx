/**
 * Aries Admin: AI Management Dashboard (CN-007, ai.management). Aggregates per client company only — no part numbers,
 * descriptions, drawings, files or engineering records. The Admin switches a company's client workspace on or off but
 * holds no technical review, sharing or approval authority.
 */
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Icon } from "../components/icons";
import { useToast } from "../components/theme";
import { Badge, Card, Empty, ErrorNotice, Loading, Notice, PageHeader, formatDate } from "../components/ui";

type Money = Record<string, string>;
type Company = {
  id: string; company: string; workspace_enabled: boolean; sharing_permitted: boolean; external_ai_permitted: boolean;
  inventory: { parts: number; imported: number }; classification: { verified: number; ai_suggested: number };
  feasibility: { assessed: number; additive: Record<string, number>; conventional: Record<string, number> };
  reviews: { preliminary: number; information_requested: number; reviewed: number; pending: number; with_recommendation: number };
  savings: { estimated: Money; verified: Money };
  trend: { run: number; quarter: string; finished_at: string; assessed: number; estimated: Money; verified: Money }[];
  disclosure: { shared: number; awaiting_share: number }; open_requests: number;
};
type Usage = { calls: number; cache_hits: number; refused: number; failed: number; prompt_tokens: number; output_tokens: number; cost_usd: number };
type Dash = { companies: Company[]; totals: { imported: number; classified: number; feasibility: number; pending_reviews: number; shared: number;
  open_requests: number; estimated: Money; verified: Money };
  usage: { days: number; total: Usage; by_model: (Usage & { model: string })[]; by_company: (Usage & { company: string })[]; note: string };
  ai: { enabled: boolean; provider?: string; models?: Record<string, string> }; note: string };

const money = (m: Money) => Object.entries(m).map(([c, v]) => `${c} ${Number(v).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`).join("; ") || "none";
const usd = (n: number) => `USD ${n.toFixed(4)}`;
const pct = (a: number, b: number) => (b ? Math.round((a / b) * 100) : 0);
const STATUS_LABEL: Record<string, string> = {
  potentially_suitable: "Potentially suitable", potentially_suitable_redesign: "Potentially suitable (redesign)", insufficient_information: "Insufficient information",
  specialist_assessment: "Specialist assessment", not_suitable_verified: "Not suitable (verified)", not_verified: "Not verified",
};
const TABS = [["coverage", "Coverage"], ["access", "Client access"], ["trends", "Quarterly trends"], ["usage", "AI usage & cost"]] as const;

function Meter({ value, total, label }: { value: number; total: number; label: string }) {
  return (
    <div className="cov-meter">
      <div className="cov-meter-head"><span>{label}</span><strong>{value} / {total}</strong></div>
      <span className="meter-bar" role="img" aria-label={`${label}: ${value} of ${total}`}><span style={{ width: `${pct(value, total)}%` }} /></span>
    </div>
  );
}

export default function AiManagementPage() {
  const toast = useToast();
  const d = useApi<Dash>("/admin/ai-management/");
  const [params, setParams] = useSearchParams();
  const tab = TABS.some(([t]) => t === params.get("tab")) ? params.get("tab")! : "coverage";
  const [busy, setBusy] = useState("");
  const [error, setError] = useState<unknown>(null);

  async function toggle(c: Company) {
    setBusy(c.id); setError(null);
    try {
      await api(`/admin/ai-management/clients/${c.id}/`, { method: "PUT", body: { enabled: !c.workspace_enabled } });
      toast(`${c.company}: client workspace ${c.workspace_enabled ? "switched off" : "switched on"}.`);
      await d.reload();
    } catch (e) { setError(e); } finally { setBusy(""); }
  }

  return (
    <>
      <PageHeader title="AI management" subtitle="Spare Parts Intelligence across client companies: coverage, reviews, savings, client access and AI cost." />
      <div className="tabs" role="tablist" aria-label="AI management">
        {TABS.map(([t, name]) => (
          <button key={t} type="button" role="tab" aria-selected={tab === t} className={`tab ${tab === t ? "is-active" : ""}`}
            onClick={() => setParams(t === "coverage" ? {} : { tab: t }, { replace: true })}>{name}</button>
        ))}
      </div>
      <ErrorNotice error={d.error ?? error} />
      {d.loading && !d.data ? <Loading variant="cards" /> : d.data && (
        <>
          {tab === "coverage" && (
            <>
              <div className="stats stats-3">
                <div className="stat"><Icon name="boxes" /><div className="stat-value">{d.data.totals.imported}</div><div className="stat-label">Parts in assessment scope</div></div>
                <div className="stat"><Icon name="spark" /><div className="stat-value">{d.data.totals.classified}</div><div className="stat-label">Classification verified</div></div>
                <div className="stat"><Icon name="gauge" /><div className="stat-value">{d.data.totals.feasibility}</div><div className="stat-label">Feasibility assessed</div></div>
                <div className="stat"><Icon name="review" /><div className="stat-value">{d.data.totals.pending_reviews}</div><div className="stat-label">Pending engineering reviews</div></div>
                <div className="stat"><Icon name="eye" /><div className="stat-value">{d.data.totals.shared}</div><div className="stat-label">Results shared with clients</div></div>
                <div className="stat"><Icon name="message" /><div className="stat-value">{d.data.totals.open_requests}</div><div className="stat-label">Open client assessment requests</div></div>
              </div>
              <div className="savings-pair ai-savings">
                <div className="savings-box is-estimated"><span className="muted small">Estimated savings (provisional, not validated)</span><strong>{money(d.data.totals.estimated)}</strong></div>
                <div className="savings-box is-verified"><span className="muted small">Verified savings</span><strong>{money(d.data.totals.verified)}</strong></div>
              </div>
              {!d.data.companies.some((c) => c.inventory.imported > 0 || c.workspace_enabled) ? <Empty icon="building">No client company has parts in the engineering lifecycle yet.</Empty> : (
                <div className="company-grid">
                  {d.data.companies.filter((c) => c.inventory.imported > 0 || c.workspace_enabled).map((c) => (
                    <section key={c.id} className="card company-card" aria-label={c.company}>
                      <div className="card-head"><h2>{c.company}</h2>
                        <Badge tone={c.workspace_enabled ? "info" : "neutral"}>{c.workspace_enabled ? "Client workspace on" : "Client workspace off"}</Badge></div>
                      <Meter label="Classification verified" value={c.classification.verified} total={c.inventory.imported} />
                      <Meter label="Feasibility assessed" value={c.feasibility.assessed} total={c.inventory.imported} />
                      <Meter label="Recommendations reviewed" value={c.reviews.reviewed} total={c.reviews.with_recommendation} />
                      <dl className="company-facts">
                        <div><dt>Inventory</dt><dd>{c.inventory.imported} in assessment scope of {c.inventory.parts} parts</dd></div>
                        <div><dt>AI suggestions</dt><dd>{c.classification.ai_suggested} part(s)</dd></div>
                        <div><dt>Pending reviews</dt><dd>{c.reviews.pending} ({c.reviews.preliminary} preliminary, {c.reviews.information_requested} information requested)</dd></div>
                        <div><dt>Shared with client</dt><dd>{c.disclosure.shared} shared · {c.disclosure.awaiting_share} awaiting share</dd></div>
                        <div><dt>Client requests</dt><dd>{c.open_requests} open</dd></div>
                        <div><dt>Savings</dt><dd><span className="saving-estimated">{money(c.savings.estimated)}</span> est. · <span className="saving-verified">{money(c.savings.verified)}</span> verified</dd></div>
                      </dl>
                      {c.feasibility.assessed > 0 && (
                        <details className="small"><summary>Feasibility status</summary>
                          {(["additive", "conventional"] as const).map((k) => (
                            <p key={k}><strong>{k === "additive" ? "Additive" : "Conventional"}:</strong>{" "}
                              {Object.entries(c.feasibility[k]).map(([s, n]) => `${STATUS_LABEL[s] ?? s} ${n}`).join(" · ")}</p>))}
                        </details>
                      )}
                    </section>
                  ))}
                </div>
              )}
              <p className="muted small">{d.data.note}</p>
            </>
          )}

          {tab === "access" && (
            <Card title="Client workspace access">
              <p className="muted small">Switching a company on lets its authorised users see results that Aries Engineers explicitly share, and request
                assessments. It does not share anything by itself, does not enable external AI, and grants the Admin no review or approval authority.
                Companies not approved for client AI sharing cannot be switched on.</p>
              <div className="table-scroll">
                <table className="table" aria-label="Client workspace access">
                  <thead><tr><th>Company</th><th>Client workspace</th><th>Client sharing approved</th><th>External AI permitted</th><th>Shared results</th><th /></tr></thead>
                  <tbody>{d.data.companies.filter((c) => c.sharing_permitted || c.workspace_enabled).map((c) => (
                    <tr key={c.id}>
                      <td><strong>{c.company}</strong></td>
                      <td><Badge tone={c.workspace_enabled ? "info" : "neutral"}>{c.workspace_enabled ? "On" : "Off"}</Badge></td>
                      <td>{c.sharing_permitted ? "Yes" : <span className="muted">No — needs a reviewed decision</span>}</td>
                      <td>{c.external_ai_permitted ? "Yes (synthetic pilot)" : <span className="muted">No</span>}</td>
                      <td>{c.disclosure.shared}</td>
                      <td className="actions">
                        <button type="button" className={`btn btn-small ${c.workspace_enabled ? "" : "btn-primary"}`} disabled={!!busy || (!c.workspace_enabled && !c.sharing_permitted)}
                          aria-label={`${c.workspace_enabled ? "Switch off" : "Switch on"} the client workspace of ${c.company}`}
                          title={!c.workspace_enabled && !c.sharing_permitted ? "Not approved for client AI sharing" : undefined}
                          onClick={() => void toggle(c)}>{c.workspace_enabled ? "Switch off" : "Switch on"}</button>
                      </td>
                    </tr>))}
                  </tbody>
                </table>
              </div>
              {d.data.companies.some((c) => !c.sharing_permitted && !c.workspace_enabled) && (
                <details className="not-approved">
                  <summary>{d.data.companies.filter((c) => !c.sharing_permitted && !c.workspace_enabled).length} other client companies — not approved
                    for client AI sharing (workspace stays off)</summary>
                  <ul className="plain-list small">{d.data.companies.filter((c) => !c.sharing_permitted && !c.workspace_enabled).map((c) => (
                    <li key={c.id}>{c.company}{c.inventory.imported ? ` · ${c.inventory.imported} parts in assessment scope` : ""}</li>))}</ul>
                </details>
              )}
            </Card>
          )}

          {tab === "trends" && (
            <Card title="Quarterly assessment trends">
              {d.data.companies.every((c) => !c.trend.length) ? <Empty icon="chart">No completed assessment runs yet.</Empty> : (
                d.data.companies.filter((c) => c.trend.length).map((c) => (
                  <section key={c.id} className="trend-block" aria-label={`${c.company} trend`}>
                    <h3 className="h-sub">{c.company}</h3>
                    <div className="table-scroll">
                      <table className="table" aria-label={`${c.company} assessment runs`}>
                        <thead><tr><th>Run</th><th>Quarter</th><th>Finished</th><th>Assessed</th><th>Estimated savings</th><th>Verified savings</th></tr></thead>
                        <tbody>{c.trend.map((r) => (
                          <tr key={r.run}><td>Run {r.run}</td><td>{r.quarter}</td><td>{formatDate(r.finished_at)}</td><td>{r.assessed}</td>
                            <td className="saving-estimated">{money(r.estimated)}</td><td className="saving-verified">{money(r.verified)}</td></tr>))}
                        </tbody>
                      </table>
                    </div>
                  </section>
                ))
              )}
              <Notice kind="info">Estimated savings are provisional and include options that are not technically qualified; verified savings meet every
                mandatory requirement with current quotations.</Notice>
            </Card>
          )}

          {tab === "usage" && (
            <Card title={`AI usage and estimated cost (last ${d.data.usage.days} days)`}>
              <div className="stat-row">
                <div className="stat"><strong>{d.data.usage.total.calls}</strong><span className="muted small">AI calls</span></div>
                <div className="stat"><strong>{d.data.usage.total.cache_hits}</strong><span className="muted small">Reused (no call)</span></div>
                <div className="stat"><strong>{d.data.usage.total.refused}</strong><span className="muted small">Refused by limits</span></div>
                <div className="stat"><strong>{d.data.usage.total.failed}</strong><span className="muted small">Failed / invalid</span></div>
                <div className="stat"><strong>{usd(d.data.usage.total.cost_usd)}</strong><span className="muted small">Estimated cost</span></div>
              </div>
              <h3 className="h-sub">By company</h3>
              <div className="table-scroll">
                <table className="table" aria-label="AI usage by company">
                  <thead><tr><th>Company</th><th>Calls</th><th>Reused</th><th>Refused</th><th>Input tokens</th><th>Output tokens</th><th>Estimated cost</th></tr></thead>
                  <tbody>{d.data.usage.by_company.map((u) => (
                    <tr key={u.company}><td>{u.company}</td><td>{u.calls}</td><td>{u.cache_hits}</td><td>{u.refused}</td><td>{u.prompt_tokens}</td><td>{u.output_tokens}</td><td>{usd(u.cost_usd)}</td></tr>))}
                  </tbody>
                </table>
              </div>
              <h3 className="h-sub">By model</h3>
              <div className="table-scroll">
                <table className="table" aria-label="AI usage by model">
                  <thead><tr><th>Model</th><th>Calls</th><th>Input tokens</th><th>Output tokens</th><th>Estimated cost</th></tr></thead>
                  <tbody>{d.data.usage.by_model.map((u) => (
                    <tr key={u.model}><td>{u.model}</td><td>{u.calls}</td><td>{u.prompt_tokens}</td><td>{u.output_tokens}</td><td>{usd(u.cost_usd)}</td></tr>))}
                  </tbody>
                </table>
              </div>
              <p className="muted small">{d.data.usage.note}</p>
            </Card>
          )}
        </>
      )}
    </>
  );
}
