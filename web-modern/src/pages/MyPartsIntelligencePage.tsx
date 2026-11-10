/**
 * Client "My Parts Intelligence" (CN-007, ai.workspace). Only results that Aries Engineers explicitly shared with the
 * company are shown — never internal AI suggestions, costs or reviewer notes. Role differences come from the server:
 * prices (Client Admin, Procurement), requests (Client Admin, Client Engineer), downloads (Client Admin, Client Engineer,
 * Procurement), member access (Client Admin). Nothing here is an approval, publication or manufacturing release.
 */
import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { api, fetchObjectUrl } from "../api/client";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { SharedResultView, type Price, type Snapshot } from "../components/ClientSharing";
import { Icon } from "../components/icons";
import { StatusBadge } from "../components/requests";
import { useToast } from "../components/theme";
import { BackLink, Badge, Breakable, Card, Empty, ErrorNotice, Field, Loading, Notice, PageHeader, formatDate } from "../components/ui";

type Access = { enabled: boolean; allowed: boolean; role: string; can_request: boolean; can_see_prices: boolean; can_download: boolean;
  can_manage_members: boolean; statement: string };
type ClientStatus = { code: string; label: string; shared_at: string | null };
type Row = { id: string; part_number: string; name: string; status: ClientStatus; outcome: string | null;
  open_request: { id: string; reference: string; status_label: string } | null };
type Overview = { access: Access; parts: Row[]; counts: Record<string, number> };
type Dashboard = { access: Access; parts_in_scope: number; status_counts: Record<string, number>; results_available: number;
  option_suitability: Record<string, { title: string; potentially_suitable: number; not_qualified: number; excluded: number }>;
  evidence_gaps: number; released_quotes: number | null; requests: { open: number; total: number };
  shared_by_quarter: { quarter: string; shared: number }[]; statement: string };
type Member = { user: string; email: string; name: string; role: string; role_label: string; allowed: boolean; default: boolean; managed_by_role: boolean };
type PartDetail = { access: Access; part: { id: string; part_number: string; name: string }; status: ClientStatus;
  shared: (Snapshot & { id: string; shared_at: string; released_prices: Price[]; prices_hidden: boolean }) | null;
  history: { event: string; label: string; at: string }[];
  requests: { id: string; reference: string; status: string; status_label: string; created_at: string; remarks: string }[] };

const STATUS_TONE: Record<string, "neutral" | "info" | "warning" | "danger"> = {
  available: "info", preparing: "info", in_assessment: "warning", withdrawn: "danger", not_assessed: "neutral",
};
const TABS = [["parts", "My parts"], ["dashboard", "Dashboard"], ["access", "Access"]] as const;

function NotAvailable({ access }: { access: Access }) {
  return (
    <Card>
      <Empty icon="lock">
        {!access.enabled ? "Spare Parts Intelligence is not enabled for your company yet. Aries switches it on when assessment results can be shared."
          : "Your Client Administrator has not given you access to Spare Parts Intelligence."}
      </Empty>
    </Card>
  );
}

export default function MyPartsIntelligencePage() {
  const ov = useApi<Overview>("/client-intelligence/");
  const [params, setParams] = useSearchParams();
  const acc = ov.data?.access;
  const tabs = TABS.filter(([t]) => t !== "access" || acc?.can_manage_members);
  const tab = tabs.some(([t]) => t === params.get("tab")) ? params.get("tab")! : "parts";
  return (
    <>
      <PageHeader title="My parts intelligence" subtitle="Assessment results that Aries Engineering has shared with your company, and your assessment requests." />
      <ErrorNotice error={ov.error} />
      {ov.loading && !ov.data ? <Loading variant="cards" /> : acc && (!acc.enabled || !acc.allowed) ? <NotAvailable access={acc} /> : ov.data && (
        <>
          <div className="tabs" role="tablist" aria-label="My parts intelligence">
            {tabs.map(([t, name]) => (
              <button key={t} type="button" role="tab" aria-selected={tab === t} className={`tab ${tab === t ? "is-active" : ""}`}
                onClick={() => setParams(t === "parts" ? {} : { tab: t }, { replace: true })}>{name}</button>
            ))}
          </div>
          {tab === "parts" && <PartsList ov={ov.data} />}
          {tab === "dashboard" && <ClientDashboard />}
          {tab === "access" && <MemberAccess />}
        </>
      )}
    </>
  );
}

function PartsList({ ov }: { ov: Overview }) {
  const [filter, setFilter] = useState("");
  const rows = ov.parts.filter((p) => !filter || p.status.code === filter);
  const FILTERS: [string, string][] = [["", "All"], ["available", "Results available"], ["in_assessment", "Under assessment"],
    ["preparing", "Being prepared"], ["not_assessed", "Not yet assessed"], ["withdrawn", "Withdrawn"]];
  return (
    <>
      <div className="catalog-bar">
        <div className="segmented" role="group" aria-label="Filter by status">
          {FILTERS.map(([k, l]) => <button key={k || "all"} type="button" aria-pressed={filter === k} onClick={() => setFilter(k)}>
            {l}{k ? <span className="count">{ov.counts[k] ?? 0}</span> : <span className="count">{ov.parts.length}</span>}</button>)}
        </div>
      </div>
      {rows.length === 0 ? <Card><Empty icon="boxes">No parts in this state.</Empty></Card> : (
        <ul className="intel-grid" aria-label="Parts">
          {rows.map((p) => (
            <li key={p.id}>
              <article className="intel-card" aria-labelledby={`intel-${p.id}`}>
                <div className="intel-card-head">
                  <Link id={`intel-${p.id}`} to={`/ai/my-parts/${p.id}`} className="part-card-number">{p.part_number}</Link>
                  <Badge tone={STATUS_TONE[p.status.code] ?? "neutral"}>{p.status.label}</Badge>
                </div>
                <p className="part-card-name">{p.name}</p>
                <p className="muted small intel-outcome">{p.outcome ?? (p.status.code === "available" ? "" : "No shared result yet.")}</p>
                <div className="intel-card-foot">
                  <span className="muted small">{p.open_request ? <>Request {p.open_request.reference} · {p.open_request.status_label}</> :
                    p.status.shared_at ? `Shared ${formatDate(p.status.shared_at)}` : ""}</span>
                  <Link className="btn btn-small btn-primary" to={`/ai/my-parts/${p.id}`}>Open</Link>
                </div>
              </article>
            </li>
          ))}
        </ul>
      )}
      <p className="muted small">{ov.access.statement}</p>
    </>
  );
}

function ClientDashboard() {
  const d = useApi<Dashboard>("/client-intelligence/dashboard/");
  if (d.loading && !d.data) return <Loading variant="cards" />;
  if (d.error || !d.data) return <ErrorNotice error={d.error} />;
  const x = d.data;
  return (
    <>
      <div className="stats stats-3">
        <div className="stat"><Icon name="boxes" /><div className="stat-value">{x.parts_in_scope}</div><div className="stat-label">Parts in assessment scope</div></div>
        <div className="stat"><Icon name="eye" /><div className="stat-value">{x.results_available}</div><div className="stat-label">Results available</div></div>
        <div className="stat"><Icon name="gauge" /><div className="stat-value">{x.status_counts.in_assessment ?? 0}</div><div className="stat-label">Under engineering assessment</div></div>
        <div className="stat"><Icon name="alert" /><div className="stat-value">{x.evidence_gaps}</div><div className="stat-label">Evidence gaps to close</div></div>
        <div className="stat"><Icon name="message" /><div className="stat-value">{x.requests.open}</div><div className="stat-label">Open assessment requests</div></div>
        {x.released_quotes != null && <div className="stat"><Icon name="scale" /><div className="stat-value">{x.released_quotes}</div><div className="stat-label">Released quotes</div></div>}
      </div>
      <div className="grid-2">
        <Card title="Manufacturing options across shared results">
          {x.results_available === 0 ? <Empty icon="chart">No results shared yet.</Empty> : (
            <table className="table" aria-label="Option suitability">
              <thead><tr><th>Option</th><th>Potentially suitable</th><th>Not qualified yet</th><th>Excluded</th></tr></thead>
              <tbody>{Object.entries(x.option_suitability).map(([k, o]) => (
                <tr key={k}><td>{o.title}</td><td>{o.potentially_suitable}</td><td>{o.not_qualified}</td><td>{o.excluded}</td></tr>))}</tbody>
            </table>
          )}
          <p className="muted small">"Potentially suitable" still requires engineering qualification. Nothing here authorises manufacturing.</p>
        </Card>
        <Card title="Parts with results shared, per quarter">
          {x.shared_by_quarter.length === 0 ? <Empty icon="calendar">No results shared yet.</Empty> : (
            <ul className="quarter-bars" aria-label="Results shared per quarter">
              {x.shared_by_quarter.map((q) => {
                const max = Math.max(...x.shared_by_quarter.map((y) => y.shared));
                return <li key={q.quarter}><span className="quarter-label">{q.quarter}</span>
                  <span className="meter-bar"><span style={{ width: `${(q.shared / max) * 100}%` }} /></span><strong>{q.shared}</strong></li>;
              })}
            </ul>
          )}
        </Card>
      </div>
      <Notice kind="info">{x.statement}</Notice>
    </>
  );
}

function MemberAccess() {
  const toast = useToast();
  const m = useApi<{ members: Member[] }>("/client-intelligence/members/");
  const [error, setError] = useState<unknown>(null);
  async function set(u: Member, allowed: boolean) {
    setError(null);
    try {
      m.setData(await api<{ members: Member[] }>("/client-intelligence/members/", { method: "PUT", body: { user: u.user, allowed } }));
      toast(`${u.email}: access ${allowed ? "granted" : "removed"}.`);
    } catch (e) { setError(e); }
  }
  return (
    <Card title="Who can use Spare Parts Intelligence">
      <p className="muted small">Client Administrators always have access. Client Engineers have access unless you remove it. Procurement, Client Users
        and Auditors need your explicit grant. Prices are shown only to Client Administrators and Procurement.</p>
      <ErrorNotice error={error ?? m.error} />
      {m.loading && !m.data ? <Loading /> : (
        <div className="table-scroll">
          <table className="table" aria-label="Member access">
            <thead><tr><th>Member</th><th>Role</th><th>Access</th><th /></tr></thead>
            <tbody>{(m.data?.members ?? []).map((u) => (
              <tr key={u.user}>
                <td>{u.name}<div className="muted small">{u.email}</div></td>
                <td>{u.role_label}</td>
                <td><Badge tone={u.allowed ? "info" : "neutral"}>{u.allowed ? "Has access" : "No access"}</Badge>
                  {u.default && !u.managed_by_role && <span className="muted small"> (role default)</span>}</td>
                <td className="actions">{u.managed_by_role ? <span className="muted small">By role</span> : (
                  <button type="button" className={`btn btn-small ${u.allowed ? "" : "btn-primary"}`} onClick={() => void set(u, !u.allowed)}
                    aria-label={`${u.allowed ? "Remove access for" : "Grant access to"} ${u.email}`}>{u.allowed ? "Remove access" : "Grant access"}</button>)}</td>
              </tr>))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

const REASONS: [string, string][] = [["assessment", "Assess this part"], ["reassessment", "Reassess this part"],
  ["new_information", "I have new technical information"]];

export function MyPartDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const { can } = useAuth();
  const v = useApi<PartDetail>(`/client-intelligence/parts/${id}/`);
  const [reason, setReason] = useState("assessment");
  const [remarks, setRemarks] = useState("");
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  if (v.loading && !v.data) return <Loading variant="page" />;
  if (v.error || !v.data) return <><BackLink to="/ai/my-parts">My parts intelligence</BackLink><ErrorNotice error={v.error} /></>;
  const d = v.data;
  const openRequest = d.requests.find((r) => !["closed", "withdrawn", "declined", "completed"].includes(r.status));

  async function send() {
    setBusy(true); setError(null);
    try {
      const r = await api<{ reference: string }>(`/client-intelligence/parts/${id}/request/`, { body: { reason, remarks } });
      toast(`Request ${r.reference} sent to Aries Engineering.`);
      setAsking(false); setRemarks("");
      await v.reload();
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function download() {
    setError(null);
    try {
      const url = await fetchObjectUrl(`/client-intelligence/parts/${id}/report.pdf`);
      const a = document.createElement("a");
      a.href = url; a.download = `assessment-${d.part.part_number}.pdf`; a.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 5000);
    } catch (e) { setError(e); }
  }

  return (
    <>
      <BackLink to="/ai/my-parts">My parts intelligence</BackLink>
      <header className="passport-hero">
        <div className="hero-top">
          <div className="hero-identity">
            <p className="hero-eyebrow"><Icon name="spark" size="sm" />Spare Parts Intelligence</p>
            <h1>{d.part.part_number}</h1>
            <p className="hero-sub"><Breakable text={d.part.name} /></p>
          </div>
          <div className="hero-actions">
            {d.access.can_request && !openRequest && <button type="button" className="btn btn-primary" onClick={() => setAsking(true)}>
              <Icon name="message" size="sm" />{d.shared ? "Request reassessment" : "Request assessment"}</button>}
            {d.access.can_download && d.shared && <button type="button" className="btn" onClick={() => void download()}><Icon name="download" size="sm" />Download report</button>}
            {can("files.upload_supporting") && <button type="button" className="btn btn-ghost" onClick={() => navigate(`/parts/${d.part.id}?tab=documents`)}>
              <Icon name="upload" size="sm" />Provide documents</button>}
          </div>
        </div>
        <div className="hero-summary">
          <div className="hero-status"><span className="hero-label">Status</span><Badge tone={STATUS_TONE[d.status.code] ?? "neutral"}>{d.status.label}</Badge></div>
          {d.shared && <dl className="hero-facts"><div><dt>Shared</dt><dd>{formatDate(d.shared.shared_at)}</dd></div>
            <div><dt>Assessment version</dt><dd>{d.shared.recommendation_version}</dd></div></dl>}
          {openRequest && <dl className="hero-facts"><div><dt>Your request</dt><dd>{openRequest.reference} · {openRequest.status_label}</dd></div></dl>}
        </div>
      </header>
      <ErrorNotice error={error} />
      {asking && (
        <Card title="Request an assessment from Aries Engineering">
          <div className="form-grid">
            <Field label="What do you need?"><select value={reason} onChange={(e) => setReason(e.target.value)}>
              {REASONS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
            <div className="span-2"><Field label="Remarks" hint="For example: the reason, new drawings or specifications you can provide, or urgency.">
              <textarea rows={3} value={remarks} maxLength={2000} onChange={(e) => setRemarks(e.target.value)} /></Field></div>
            <div className="form-actions span-2">
              <button type="button" className="btn btn-ghost" onClick={() => setAsking(false)}>Cancel</button>
              <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void send()}>Send request</button>
            </div>
          </div>
          <p className="muted small">The request goes to the Aries engineering team assigned to your company. It does not start any automatic processing.</p>
        </Card>
      )}
      {d.shared ? (
        <Card title="Shared assessment result">
          <SharedResultView snapshot={d.shared} prices={d.shared.released_prices} pricesHidden={d.shared.prices_hidden} />
        </Card>
      ) : (
        <Card><Empty icon="eye">{d.status.code === "withdrawn" ? "The previously shared result was withdrawn by Aries Engineering." :
          d.status.code === "in_assessment" || d.status.code === "preparing" ? "Aries Engineering is assessing this part. Results appear here once they are shared with you."
            : "This part has not been assessed yet. You can request an assessment."}</Empty></Card>
      )}
      <div className="grid-2">
        <Card title="Your assessment requests">
          {d.requests.length === 0 ? <p className="muted small">No requests for this part.</p> : (
            <ul className="plain-list">{d.requests.map((r) => (
              <li key={r.id} className="row-between request-row"><span><Link className="nowrap" to={`/requests/${r.id}`}>{r.reference}</Link> · {formatDate(r.created_at)}</span>
                <StatusBadge status={r.status} /></li>))}</ul>
          )}
        </Card>
        <Card title="History">
          {d.history.length === 0 ? <p className="muted small">Nothing shared yet.</p> : (
            <ul className="plain-list">{d.history.map((h, i) => <li key={i}>{h.label}<div className="muted small">{formatDate(h.at)}</div></li>)}</ul>
          )}
        </Card>
      </div>
    </>
  );
}
