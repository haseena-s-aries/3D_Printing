/**
 * Aries organisation: contract authorizations for Aries Admin thumbnails of Aries scanning photos (contract route).
 * - ThumbnailContractsPage: every client company with its contract-route status and what waits for the signed-in person.
 * - ThumbnailContractWorkspace (own page, and the "Thumbnail contract" tab of Client management): record (Aries Admin),
 *   independent verification (a different Aries Admin or Aries QA), the client-objection review (only a designated
 *   objection reviewer under the configured authority, independent of the recorder, verifier and photo claimants), ending,
 *   and the full immutable history. The server decides every permission; the screen only offers what it allows.
 */
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Badge, BackLink, Card, Empty, ErrorNotice, Field, Loading, Notice, PageHeader, formatDate } from "../components/ui";

type Event = { event: string; label: string; by: string; at: string; note: string; authority: string; counts: boolean };
type Authorization = { id: string; contract_reference: string; clause_excerpt: string; effective_from: string; effective_until: string;
  scope: string; scope_label: string; projects: string[]; recorded_by: string; recorded_at: string; note: string; events: Event[] };
type Contract = {
  client: { id: string; name: string }; status: string; label: string; verified_at: string | null;
  authorization: Authorization | null; history: Authorization[]; projects: { id: string; code: string; name: string }[];
  objection: { at: string } | null; review: { outcome: string; note: string; at: string; authority: string } | null;
  photos: { confirmed_aries_captures: number; shown_through_contract: number };
  objection_authority: { configured: boolean; reference: string };
  can: { record: boolean; verify: boolean; end: boolean; review: boolean }; own_record: boolean; review_block: string;
};
type Row = { id: string; name: string; status: string; label: string; contract_reference: string; effective_until: string | null;
  awaiting_verification: boolean; awaiting_my_review: boolean; objection_on_hold: boolean };

export const TONES: Record<string, "success" | "warning" | "info" | "neutral" | "danger"> = {
  active: "success", on_hold: "warning", pending_verification: "info", objection_sustained: "danger", none: "neutral",
  rejected: "neutral", ended: "neutral", expired: "neutral", not_yet_effective: "info",
};
/** Aries-facing wording for each status (the client sees its own explanation on Data sharing). */
const ARIES_STATUS: Record<string, string> = {
  none: "No contract authorization is recorded. Aries scanning photos reach the Aries Admin only with the client's permission.",
  pending_verification: "Recorded, waiting for independent verification against the signed agreement. It has no effect yet.",
  rejected: "Rejected at verification. It has no effect.",
  ended: "Ended. It no longer allows any thumbnails.",
  not_yet_effective: "Verified, but the effective date has not been reached.",
  expired: "Verified, but past its expiry date. It no longer allows any thumbnails.",
  on_hold: "The client has recorded \"Not allowed\". The route is on hold until a designated objection reviewer records a decision under the documented authority.",
  objection_sustained: "The client's objection was upheld. The route stays blocked until the client changes its decision.",
  active: "In effect: QA-confirmed, released Aries scanning photos in scope may appear as Aries Admin thumbnails.",
};
/** The server labels are written for the client ("your objection"); Aries screens name the client instead. */
const ariesLabel = (status: string, fallback: string) => ({ on_hold: "On hold: client objection", objection_sustained: "Blocked: client objection upheld" } as Record<string, string>)[status] ?? fallback;
const formatDay = (ymd: string) => { const [y, m, d] = ymd.split("-").map(Number); return new Date(y, m - 1, d).toLocaleDateString(undefined, { dateStyle: "medium" }); };

export function ThumbnailContractsPage() {
  const list = useApi<{ results: Row[]; objection_authority: { configured: boolean; reference: string } }>("/admin/thumbnail-contracts/");
  return (
    <>
      <PageHeader title="Thumbnail contracts" subtitle="Contract authorizations that let the Aries Admin see thumbnails of Aries scanning photos without client permission." />
      <ErrorNotice error={list.error} />
      {list.loading && !list.data && <Loading />}
      {list.data && (
        <>
          <AuthorityNotice authority={list.data.objection_authority} />
          <Card title="Client companies">
            <div className="table-scroll">
              <table className="table table-stack" aria-label="Thumbnail contracts by company">
                <thead><tr><th>Company</th><th>Status</th><th>Contract reference</th><th>Expires</th><th>Waiting for you</th></tr></thead>
                <tbody>
                  {list.data.results.map((r) => (
                    <tr key={r.id}>
                      <td><Link to={`/thumbnail-contracts/${r.id}`}>{r.name}</Link></td>
                      <td><Badge tone={TONES[r.status] ?? "neutral"}>{ariesLabel(r.status, r.label)}</Badge></td>
                      <td>{r.contract_reference || <span className="muted">—</span>}</td>
                      <td>{r.effective_until ? formatDay(r.effective_until) : <span className="muted">—</span>}</td>
                      <td>
                        {r.awaiting_verification && <Badge tone="info">Verification</Badge>}{" "}
                        {r.awaiting_my_review && <Badge tone="warning">Objection review</Badge>}
                        {!r.awaiting_verification && !r.awaiting_my_review && <span className="muted">—</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </>
  );
}

function AuthorityNotice({ authority }: { authority: { configured: boolean; reference: string } }) {
  return authority.configured
    ? <Notice kind="info">Client objections are resolved only by designated reviewers under <strong>{authority.reference}</strong>. Verifying a contract gives no such right.</Notice>
    : <Notice kind="warning">No objection-review authority is defined, so every contract route the client has objected to stays on hold.</Notice>;
}

export default function ThumbnailContractPage() {
  const { clientId = "" } = useParams();
  return (
    <>
      <BackLink to="/thumbnail-contracts">Thumbnail contracts</BackLink>
      <ThumbnailContractWorkspace clientId={clientId} showTitle />
    </>
  );
}

export function ThumbnailContractWorkspace({ clientId, showTitle = false }: { clientId: string; showTitle?: boolean }) {
  const path = `/admin/clients/${clientId}/thumbnail-contract/`;
  const c = useApi<Contract>(path);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState("");
  const [busy, setBusy] = useState(false);

  const send = async (url: string, body: unknown, message: string) => {
    setBusy(true); setError(null); setDone("");
    try { c.setData(await api<Contract>(url, { method: "POST", body })); setDone(message); return true; }
    catch (e) { setError(e); return false; } finally { setBusy(false); }
  };
  if (c.error) return <ErrorNotice error={c.error} />;
  if (!c.data) return <Loading />;
  const d = c.data;
  const a = d.authorization;
  const event = (body: Record<string, unknown>, message: string) => a ? send(`${path}${a.id}/events/`, body, message) : Promise.resolve(false);
  return (
    <div className="contract-workspace">
      {showTitle && <PageHeader title={d.client.name} subtitle="Thumbnail contract route" actions={<Badge tone={TONES[d.status] ?? "neutral"}>{ariesLabel(d.status, d.label)}</Badge>} />}
      {!showTitle && <div className="contract-status-line"><Badge tone={TONES[d.status] ?? "neutral"}>{ariesLabel(d.status, d.label)}</Badge></div>}
      {done && <Notice kind="success"><span role="status">{done}</span></Notice>}
      <ErrorNotice error={error} />
      <Notice kind={d.status === "on_hold" ? "warning" : "info"}>{ARIES_STATUS[d.status]}</Notice>

      {a && (
        <Card title="Current authorization">
          <dl className="facts">
            <dt>Contract reference</dt><dd>{a.contract_reference}</dd>
            <dt>Effective</dt><dd>{formatDay(a.effective_from)} to {formatDay(a.effective_until)}</dd>
            <dt>Scope</dt><dd>{a.scope_label}{a.projects.length > 0 && `: ${a.projects.join(", ")}`}</dd>
            <dt>Recorded by</dt><dd>{a.recorded_by}, {formatDate(a.recorded_at)}</dd>
            <dt>Independent verification</dt><dd>{d.verified_at ? formatDate(d.verified_at) : "Not verified"}</dd>
            {d.objection && <><dt>Client objection</dt><dd>"Not allowed" recorded {formatDate(d.objection.at)}</dd></>}
            {d.review && <><dt>Objection decision</dt><dd>{d.review.outcome} under {d.review.authority} ({formatDate(d.review.at)})</dd></>}
            <dt>Photos</dt><dd>{d.photos.confirmed_aries_captures} released, QA-confirmed Aries captures; {d.photos.shown_through_contract} shown through this route</dd>
          </dl>
          <h3 className="consent-history-title">Clause excerpt (immutable evidence)</h3>
          <blockquote className="consent-terms">{a.clause_excerpt}</blockquote>
          <p className="muted small">The excerpt is evidence of what was recorded, not proof of authorization. The signed contract is not stored here.</p>
        </Card>
      )}

      {d.status === "pending_verification" && (d.can.verify ? <VerifyCard busy={busy} onVerify={event} /> : d.own_record
        ? <Notice kind="info">You recorded this authorization. A different Aries Admin or Aries QA must verify it against the signed agreement.</Notice>
        : <Notice kind="info">Waiting for independent verification by an Aries Admin or Aries QA who did not record it.</Notice>)}

      {d.status === "on_hold" && (d.can.review
        ? <ReviewCard busy={busy} authority={d.objection_authority.reference} objectionAt={d.objection?.at} onReview={event} />
        : <Card title="Client objection review"><Notice kind="warning">{d.review_block}</Notice>
            <p className="muted small">The route stays on hold. Only a designated objection reviewer who neither recorded nor verified this
              authorization, nor claimed or uploaded a photo it covers, can record a decision.</p></Card>)}

      {d.can.record && <RecordCard busy={busy} projects={d.projects} replacing={!!a && !["ended", "rejected", "none"].includes(d.status)}
        onRecord={(body) => send(path, body, "Authorization recorded. It has no effect until a different person verifies it.")} />}

      {d.can.end && a && <EndCard busy={busy} onEnd={event} />}

      <Card title="History">
        {d.history.length === 0 ? <Empty>No contract authorization has been recorded for this company.</Empty> : d.history.map((h) => (
          <section key={h.id} className="contract-history-item" aria-label={`Authorization ${h.contract_reference}`}>
            <h3>{h.contract_reference} <span className="muted small">recorded by {h.recorded_by}, {formatDate(h.recorded_at)}</span></h3>
            <p className="muted small">{formatDay(h.effective_from)} to {formatDay(h.effective_until)} · {h.scope_label}{h.projects.length > 0 && `: ${h.projects.join(", ")}`}</p>
            {h.events.length > 0 && (
              <div className="table-scroll">
                <table className="table table-stack" aria-label={`Events of ${h.contract_reference}`}>
                  <thead><tr><th>Event</th><th>By</th><th>Date</th><th>Authority</th><th>Note or rationale</th></tr></thead>
                  <tbody>
                    {h.events.map((e) => (
                      <tr key={e.at + e.event}>
                        <td>{e.label}{!e.counts && <div><Badge tone="neutral">Does not count: no authority</Badge></div>}</td>
                        <td>{e.by}</td><td>{formatDate(e.at)}</td><td>{e.authority || <span className="muted">—</span>}</td><td>{e.note}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        ))}
      </Card>
    </div>
  );
}

function VerifyCard({ busy, onVerify }: { busy: boolean; onVerify: (b: Record<string, unknown>, m: string) => Promise<boolean> }) {
  const [checked, setChecked] = useState(false);
  const [note, setNote] = useState("");
  return (
    <Card title="Independent verification">
      <form className="form-grid single" aria-label="Verify contract authorization" onSubmit={(e) => e.preventDefault()}>
        <p className="muted">Compare the recorded reference, clause excerpt, dates and scope with the signed agreement. You cannot verify an
          authorization you recorded. Verification gives no right to resolve client objections.</p>
        <Field label="Where and how you checked the signed agreement"><textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
        <label className="consent-check"><input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} />
          <span>I checked this excerpt, the dates and the scope against the signed agreement.</span></label>
        <div className="form-actions">
          <button type="button" className="btn btn-primary" disabled={busy || !checked || note.trim().length < 20}
            onClick={() => void onVerify({ action: "verify", checked_against_signed_agreement: true, note }, "Authorization verified.")}>Verify authorization</button>
          <button type="button" className="btn" disabled={busy || note.trim().length < 20}
            onClick={() => void onVerify({ action: "reject", note }, "Authorization rejected. It has no effect.")}>Reject</button>
        </div>
      </form>
    </Card>
  );
}

function ReviewCard({ busy, authority, objectionAt, onReview }: { busy: boolean; authority: string; objectionAt?: string;
  onReview: (b: Record<string, unknown>, m: string) => Promise<boolean> }) {
  const [outcome, setOutcome] = useState("");
  const [note, setNote] = useState("");
  return (
    <Card title="Client objection review">
      <form className="form-grid single" aria-label="Resolve client objection" onSubmit={(e) => e.preventDefault()}>
        <p className="muted">The client recorded "Not allowed"{objectionAt ? ` on ${formatDate(objectionAt)}` : ""}. Your decision is recorded
          with your name, the authority below and your rationale, and cannot be changed. A later client decision needs a new review.</p>
        <dl className="facts"><dt>Authority</dt><dd>{authority}</dd></dl>
        <fieldset className="fieldset radio-group">
          <legend>Decision</legend>
          <label><input type="radio" name="outcome" value="proceed" checked={outcome === "proceed"} onChange={() => setOutcome("proceed")} /> Contract route may proceed</label>
          <label><input type="radio" name="outcome" value="sustain" checked={outcome === "sustain"} onChange={() => setOutcome("sustain")} /> Objection upheld: route stays blocked</label>
        </fieldset>
        <Field label="Rationale"><textarea rows={4} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
        <div className="form-actions">
          <button type="button" className="btn btn-primary" disabled={busy || !outcome || note.trim().length < 30}
            onClick={() => void onReview({ action: "review", outcome, note }, "Decision on the client objection recorded.")}>Record decision</button>
        </div>
      </form>
    </Card>
  );
}

function RecordCard({ busy, projects, replacing, onRecord }: { busy: boolean; projects: Contract["projects"]; replacing: boolean;
  onRecord: (b: Record<string, unknown>) => Promise<boolean> }) {
  const [f, setF] = useState({ contract_reference: "", clause_excerpt: "", effective_from: "", effective_until: "", scope: "projects", note: "" });
  const [chosen, setChosen] = useState<string[]>([]);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (await onRecord({ ...f, project_ids: f.scope === "projects" ? chosen : [] })) {
      setF({ contract_reference: "", clause_excerpt: "", effective_from: "", effective_until: "", scope: "projects", note: "" }); setChosen([]);
    }
  };
  return (
    <Card title="Record a contract authorization">
      <form className="form-grid single" aria-label="Record contract authorization" onSubmit={(e) => void submit(e)}>
        <p className="muted">Record only what the signed agreement says. It has no effect until a different Aries Admin or Aries QA verifies it.
          {replacing && " Recording a new authorization replaces the current one, which pauses the route until the new one is verified."}</p>
        <Field label="Contract reference"><input value={f.contract_reference} maxLength={120} onChange={set("contract_reference")} /></Field>
        <Field label="Relevant clause excerpt" hint="Copy the clause that permits internal use of images Aries captures (30 to 4000 characters).">
          <textarea rows={4} value={f.clause_excerpt} maxLength={4000} onChange={set("clause_excerpt")} /></Field>
        <div className="form-row">
          <Field label="Effective from"><input type="date" value={f.effective_from} onChange={set("effective_from")} /></Field>
          <Field label="Expires"><input type="date" value={f.effective_until} onChange={set("effective_until")} /></Field>
        </div>
        <fieldset className="fieldset radio-group">
          <legend>Scope</legend>
          <label><input type="radio" name="scope" checked={f.scope === "projects"} onChange={() => setF({ ...f, scope: "projects" })} /> Listed projects only</label>
          <label><input type="radio" name="scope" checked={f.scope === "company"} onChange={() => setF({ ...f, scope: "company" })} /> Whole company</label>
        </fieldset>
        {f.scope === "projects" && (
          <fieldset className="fieldset radio-group">
            <legend>Projects covered</legend>
            {projects.map((p) => (
              <label key={p.id}><input type="checkbox" checked={chosen.includes(p.id)}
                onChange={(e) => setChosen(e.target.checked ? [...chosen, p.id] : chosen.filter((x) => x !== p.id))} /> {p.code} · {p.name}</label>
            ))}
          </fieldset>
        )}
        <Field label="Internal note (optional)"><input value={f.note} maxLength={500} onChange={set("note")} /></Field>
        <div className="form-actions">
          <button className="btn btn-primary" disabled={busy || f.contract_reference.trim().length < 3 || f.clause_excerpt.trim().length < 30
            || !f.effective_from || !f.effective_until || (f.scope === "projects" && chosen.length === 0)} aria-busy={busy}>Record authorization</button>
        </div>
      </form>
    </Card>
  );
}

function EndCard({ busy, onEnd }: { busy: boolean; onEnd: (b: Record<string, unknown>, m: string) => Promise<boolean> }) {
  const [note, setNote] = useState("");
  return (
    <Card title="End the authorization">
      <form className="form-grid single" aria-label="End contract authorization" onSubmit={(e) => { e.preventDefault();
        void onEnd({ action: "end", note }, "Authorization ended. Thumbnail links based on it stop working at once.").then((ok) => ok && setNote("")); }}>
        <Field label="Reason"><input value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} /></Field>
        <div className="form-actions"><button className="btn btn-danger" disabled={busy || note.trim().length < 10}>End authorization</button></div>
      </form>
    </Card>
  );
}
