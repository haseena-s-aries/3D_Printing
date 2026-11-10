/**
 * Client Administrator: what the company shares with Aries beyond the administrative summary, namely the two routes by
 * which the Aries Admin can see sanitized spare-part photo thumbnails in the administrative inventory.
 * 1. The company's own permission (default not allowed). Each decision is a new, audited entry; withdrawal blocks every
 *    thumbnail at once. "Not allowed" can also be recorded explicitly, which is the company's objection.
 * 2. The contract route (read-only here): photos Aries captured during scanning work, confirmed by Aries QA, under a
 *    contract authorization verified by a second Aries person. The company's objection holds it until Aries documents an
 *    independent review; the outcome is shown here. Client-uploaded photos never use this route.
 */
import { useState } from "react";

import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { Icon } from "../components/icons";
import { Badge, Card, ErrorNotice, Field, Loading, Notice, PageHeader, formatDate, label } from "../components/ui";

type ContractEvent = { event: string; label: string; by: string; at: string; note: string };
type Contract = {
  enabled: boolean; status?: string; label?: string; explanation?: string; verified_at?: string | null;
  authorization?: { contract_reference: string; clause_excerpt: string; effective_from: string; effective_until: string;
    scope: string; scope_label: string; projects: string[]; recorded_by: string; recorded_at: string; events: ContractEvent[] } | null;
  objection?: { at: string } | null;
  review?: { outcome: string; note: string; at: string; authority?: string } | null;
  photos?: { confirmed_aries_captures: number; shown_through_contract: number };
};
type Consent = { allowed: boolean; decided: boolean; terms: string; terms_version: string; contract: Contract;
  history: { decision: "granted" | "revoked"; label: string; by: string; role: string; at: string; note: string; terms_version: string }[] };
const PATH = "/company/admin-thumbnail-consent/";

/** A contract date (YYYY-MM-DD) as a calendar day, without the time-zone shift of parsing it as a UTC timestamp. */
const formatDay = (ymd: string) => {
  const [y, m, d] = ymd.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { dateStyle: "medium" });
};

const TONES: Record<string, "success" | "warning" | "info" | "neutral" | "danger"> = {
  active: "success", on_hold: "warning", pending_verification: "info", objection_sustained: "neutral", none: "neutral",
  rejected: "neutral", ended: "neutral", expired: "neutral", not_yet_effective: "info",
};

export default function DataSharingPage() {
  const { session } = useAuth();
  const c = useApi<Consent>(PATH);
  const [confirmed, setConfirmed] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState("");
  const company = session?.tenant.name ?? "your company";

  const decide = async (allow: boolean) => {
    if (!c.data) return;
    setBusy(true); setError(null); setDone("");
    try {
      const next = await api<Consent>(PATH, { method: "POST", body: { allow, note, ...(allow ? { confirm_terms_version: c.data.terms_version } : {}) } });
      c.setData(next);
      setConfirmed(false); setNote("");
      setDone(allow ? "Aries Admin may now see your photo thumbnails. The decision is recorded in your audit trail."
        : c.data.allowed ? "Permission withdrawn. Aries Admin can no longer load any of your thumbnails, including ones already on screen."
          : "\"Not allowed\" is recorded. Any contract route is on hold until Aries documents an independent review.");
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  const status = c.data ? (c.data.allowed ? "Allowed" : c.data.decided ? "Not allowed" : "No decision (not allowed)") : "";
  return (
    <div className="data-sharing">
      <PageHeader title="Data sharing with Aries" subtitle={`What ${company} allows Aries to see beyond the administrative summary.`} />
      {c.loading && !c.data && <Loading />}
      <ErrorNotice error={c.error} />
      {c.data && (
        <>
          <section className="consent-routes" aria-label="How Aries Admin can see photo thumbnails" data-testid="thumbnail-routes">
            <div className="consent-route">
              <h2><Icon name="users" size="sm" />1. Your permission</h2>
              <p>Covers every released photo, whoever took or uploaded it. Only you decide; Aries cannot grant it for you.</p>
            </div>
            <div className="consent-route">
              <h2><Icon name="shield" size="sm" />2. Contract route</h2>
              <p>Only photos Aries took during contracted scanning work, each confirmed by Aries QA, and only while a contract
                authorization verified by a second Aries person is in effect. Photos you upload never use this route.</p>
            </div>
            <p className="muted small consent-routes-note">Either way, Aries Admin sees only 480 px thumbnails with metadata removed,
              never originals, CAD, drawings, documents or full part records, and every view is in your audit trail.</p>
          </section>

          <Card title="1. Your permission: Aries Admin inventory thumbnails"
            actions={<Badge tone={c.data.allowed ? "success" : "neutral"}>{status}</Badge>}>
            <div className="consent">
              <p className="consent-terms">{c.data.terms}</p>
              <ul className="consent-facts">
                <li><Icon name="check" size="sm" />Shared when allowed: 480 px photo thumbnails with all metadata removed, of photographs already released to your company.</li>
                <li><Icon name="lock" size="sm" />Never shared: original photographs, CAD and 3D models, drawings, documents, file links and full part records.</li>
                <li><Icon name="history" size="sm" />Every thumbnail Aries Admin views is recorded in your audit trail.</li>
              </ul>
              {done && <Notice kind="success">{done}</Notice>}
              <ErrorNotice error={error} />
              <Field label="Note for the record (optional)">
                <input value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} placeholder="For example: approved by operations director" />
              </Field>
              {c.data.allowed ? (
                <div className="consent-actions">
                  <button type="button" className="btn btn-danger" disabled={busy} onClick={() => void decide(false)}>Withdraw permission</button>
                  <span className="muted small">Takes effect immediately. It also puts any contract route on hold for review.</span>
                </div>
              ) : (
                <div className="consent-actions">
                  <label className="consent-check">
                    <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
                    <span>As Client Administrator of {company}, I allow Aries Admin to see these thumbnails (wording {c.data.terms_version}).</span>
                  </label>
                  <button type="button" className="btn btn-primary" disabled={busy || !confirmed} onClick={() => void decide(true)}>Allow thumbnails</button>
                  {!c.data.decided && (
                    <button type="button" className="btn" disabled={busy} onClick={() => void decide(false)}>Record "Not allowed"</button>
                  )}
                </div>
              )}
            </div>
            <h3 className="consent-history-title">Decision history</h3>
            {c.data.history.length === 0 ? <p className="muted">No decision recorded. Thumbnails are not shared through your permission (default).</p> : (
              <div className="table-scroll">
                <table className="table table-stack" aria-label="Decision history">
                  <thead><tr><th>Decision</th><th>By</th><th>Role</th><th>Date</th><th>Note</th></tr></thead>
                  <tbody>
                    {c.data.history.map((h) => (
                      <tr key={h.at}>
                        <td><Badge tone={h.decision === "granted" ? "success" : "neutral"}>{h.label}</Badge></td>
                        <td>{h.by}</td><td>{label(h.role)}</td><td>{formatDate(h.at)}</td><td>{h.note || <span className="muted">—</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          {c.data.contract.enabled && <ContractRoute contract={c.data.contract} />}
        </>
      )}
    </div>
  );
}

function ContractRoute({ contract }: { contract: Contract }) {
  const a = contract.authorization;
  return (
    <Card title="2. Contract route: Aries scanning photos"
      actions={<Badge tone={TONES[contract.status ?? "none"] ?? "neutral"}>{contract.label}</Badge>}>
      <div className="consent" data-testid="contract-route">
        <Notice kind={contract.status === "on_hold" ? "warning" : "info"}>{contract.explanation}</Notice>
        {a && (
          <>
            <dl className="facts">
              <dt>Contract reference</dt><dd>{a.contract_reference}</dd>
              <dt>Effective</dt><dd>{formatDay(a.effective_from)} to {formatDay(a.effective_until)}</dd>
              <dt>Scope</dt><dd>{a.scope_label}{a.projects.length > 0 && `: ${a.projects.join(", ")}`}</dd>
              <dt>Recorded</dt><dd>{a.recorded_by}, {formatDate(a.recorded_at)}</dd>
              <dt>Independent verification</dt><dd>{contract.verified_at ? formatDate(contract.verified_at) : "Not verified"}</dd>
              {contract.objection && <><dt>Your objection</dt><dd>"Not allowed" recorded {formatDate(contract.objection.at)}</dd></>}
              {contract.review && <><dt>Review of your objection</dt><dd>{contract.review.outcome} ({formatDate(contract.review.at)}){contract.review.authority && `, under ${contract.review.authority}`}: {contract.review.note}</dd></>}
              <dt>Photos</dt><dd>{contract.photos?.confirmed_aries_captures ?? 0} released photos confirmed by Aries QA as Aries captures;
                {" "}{contract.photos?.shown_through_contract ?? 0} currently shown through this route</dd>
            </dl>
            <div>
              <h3 className="consent-history-title">Clause excerpt (as recorded by Aries)</h3>
              <blockquote className="consent-terms">{a.clause_excerpt}</blockquote>
              <p className="muted small">The signed contract itself is not stored in the platform. The excerpt is kept unchanged as evidence.</p>
            </div>
            {a.events.length > 0 && (
              <div className="table-scroll">
                <table className="table table-stack" aria-label="Contract route history">
                  <thead><tr><th>Event</th><th>By</th><th>Date</th><th>Note</th></tr></thead>
                  <tbody>
                    {a.events.map((e) => (
                      <tr key={e.at + e.event}><td>{e.label}</td><td>{e.by}</td><td>{formatDate(e.at)}</td><td>{e.note}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>
    </Card>
  );
}
