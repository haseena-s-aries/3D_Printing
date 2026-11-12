/**
 * Edit requests (CN-006): requester list, reviewer queue, and the request detail with the original-versus-proposed
 * comparison, decision actions and history. Approval of an edit request is distinct from engineering verification,
 * passport publication and manufacturing authorisation.
 */
import type { EditRequest, Paginated } from "@passport/api-types";
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { show } from "../components/EditRequestDialog";
import { BackLink, Badge, Card, Empty, ErrorNotice, Loading, Notice, PageHeader, formatDate } from "../components/ui";

export const EDIT_STATUS: Record<string, [string, "neutral" | "info" | "success" | "warning" | "danger"]> = {
  draft: ["Draft", "neutral"], submitted: ["Submitted", "info"], under_review: ["Under Review", "info"],
  corrections_requested: ["Corrections Requested", "warning"], approved: ["Approved", "success"], rejected: ["Rejected", "danger"],
  applied: ["Applied", "success"], conflict: ["Conflict / Revalidation Required", "danger"], withdrawn: ["Withdrawn", "neutral"],
};

export function EditStatus({ status }: { status: string }) {
  const [text, tone] = EDIT_STATUS[status] ?? [status, "neutral"];
  return <Badge tone={tone}>{text}</Badge>;
}

export function EditRequestList({ query, empty }: { query: Record<string, string>; empty: string }) {
  const list = useApi<Paginated<EditRequest>>("/edit-requests/", { query: { ...query, page_size: 100 } });
  if (list.loading && !list.data) return <Loading />;
  if (list.error) return <ErrorNotice error={list.error} />;
  if (!list.data?.results.length) return <Empty>{empty}</Empty>;
  return (
    <div className="table-scroll">
      <table className="table" aria-label="Edit requests">
        <thead><tr><th>Request</th><th>Target</th><th>Fields</th><th>Status</th><th>Requester</th><th>Updated</th></tr></thead>
        <tbody>
          {list.data.results.map((r) => (
            <tr key={r.id}>
              <td><Link to={`/edit-requests/${r.id}`}><strong>{r.reference}</strong></Link></td>
              <td>{r.part_number}{r.passport_number ? ` · ${r.passport_number} (rev ${r.base_revision_number})` : ""}<div className="muted small">{r.part_name}</div></td>
              <td className="small">{(r.changes as { label: string }[]).map((c) => c.label).join(", ")}</td>
              <td><EditStatus status={r.status ?? "draft"} /></td>
              <td className="small">{r.requester}<div className="muted">{r.requester_role_label}</div></td>
              <td className="small">{formatDate(r.submitted_at ?? r.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function EditRequestsPage() {
  const { can } = useAuth();
  const [params, setParams] = useSearchParams();
  const reviewer = can("edits.review");
  const tab = params.get("tab") ?? (reviewer ? "review" : "mine");
  const tabs: [string, string][] = [...(reviewer ? [["review", "Review queue"] as [string, string]] : []), ["mine", "My requests"], ["all", "All requests"]];
  return (
    <>
      <PageHeader marine title="Edit requests" subtitle="Controlled changes to spare-part master data and Digital Passport drafts, decided by an authorised edit reviewer." />
      <div className="segmented" role="group" aria-label="Edit request lists">
        {tabs.map(([t, l]) => <button key={t} type="button" aria-pressed={tab === t} onClick={() => setParams({ tab: t })}>{l}</button>)}
      </div>
      <p className="muted small section-note">
        {tab === "review" ? "Requests from others waiting for your decision (you never review your own)." : tab === "mine" ? "Requests you created." : "All edit requests you may see in this company."}
      </p>
      <Card>
        {tab === "review" ? <EditRequestList query={{ queue: "review" }} empty="Nothing waiting for review." />
          : tab === "mine" ? <EditRequestList query={{ queue: "mine" }} empty="You have no edit requests." />
            : <EditRequestList query={{}} empty="No edit requests yet." />}
      </Card>
    </>
  );
}

type Change = { field: string; label: string; original: unknown; proposed: unknown; current: unknown; drifted: boolean };
type Event = { action: string; from_status: string; to_status: string; note: string; side: string; user: string; created_at: string };
const ACTION_TEXT: Record<string, string> = {
  created: "Created", updated: "Updated by requester", submitted: "Submitted", resubmitted: "Resubmitted after corrections",
  review_started: "Review started", corrections_requested: "Corrections requested", approved: "Approved", rejected: "Rejected",
  applied: "Applied", conflict: "Conflict: revalidation required", rebased: "Revalidated against current record", withdrawn: "Withdrawn",
};

export function EditRequestDetailPage() {
  const { id } = useParams();
  const er = useApi<EditRequest>(`/edit-requests/${id}/`);
  const [note, setNote] = useState("");
  const [edits, setEdits] = useState<Record<string, string> | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  if (er.loading && !er.data) return <Loading />;
  if (er.error || !er.data) return <><BackLink to="/edit-requests">Edit requests</BackLink><ErrorNotice error={er.error} /></>;
  const r = er.data;
  const changes = r.changes as Change[];
  const allowed = r.allowed_actions as string[];
  const events = r.events as Event[];

  async function run(path: string, body: Record<string, unknown> = {}, method = "POST") {
    setBusy(true);
    setError(null);
    try {
      er.setData(await api<EditRequest>(`/edit-requests/${r.id}/${path}`, { method, body }));
      setNote("");
      setEdits(null);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <BackLink to="/edit-requests">Edit requests</BackLink>
      <PageHeader title={`${r.reference} · ${r.part_number}`} subtitle={<><EditStatus status={r.status ?? "draft"} /> <span className="muted small">{r.data_class_label}</span></>} />
      <Notice>Approving an edit request records a reviewer decision and applies the change in a controlled way. It is not engineering verification,
        passport approval or publication, and it does not authorise manufacturing (OQ-35, OQ-36).</Notice>
      {r.status === "conflict" && (
        <Notice kind="warning">The target changed after this request was made, so nothing was written. {r.application_result}
          {allowed.includes("rebase") && " Revalidate to compare against the current values and resubmit."}</Notice>
      )}
      {r.status === "applied" && <Notice kind="success">{r.application_result}</Notice>}
      <ErrorNotice error={error} />
      <div className="grid-2 wide-left">
        <Card title="Requested changes">
          <div className="table-scroll">
            <table className="table compare-table" aria-label="Original versus proposed">
              <thead><tr><th>Field</th><th>Original (at request)</th><th>Proposed</th><th>Current now</th></tr></thead>
              <tbody>
                {changes.map((c) => (
                  <tr key={c.field} className="is-changed">
                    <td>{c.label}</td>
                    <td>{show(c.original)}</td>
                    <td>{edits ? <input aria-label={`Proposed ${c.label}`} value={edits[c.field] ?? ""} onChange={(e) => setEdits({ ...edits, [c.field]: e.target.value })} />
                      : <strong>{show(c.proposed)}</strong>}</td>
                    <td>{c.drifted && r.status !== "applied" ? <><Badge tone="danger">Changed since request</Badge> {show(c.current)}</> : <span className="muted small">{r.status === "applied" ? show(c.current) : "Unchanged"}</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <h4>Reason</h4>
          <p className="review-note">{r.reason}</p>
          {(r.evidence_files as { file: string; title: string }[]).length > 0 && (
            <><h4>Supporting documents</h4>
              <ul className="ref-list">{(r.evidence_files as { file: string; title: string }[]).map((f) => <li key={f.file}>{f.title} <Link className="small" to={`/parts/${r.part}`}>on the part</Link></li>)}</ul></>
          )}
          {r.decision_reason && <><h4>Reviewer note</h4><p className="review-note">{r.decision_reason}</p></>}
        </Card>
        <Card title="Request">
          <dl className="facts">
            <dt>Project</dt><dd>{r.project || "—"}</dd>
            <dt>Target</dt><dd><Link to={`/parts/${r.part}`}>{r.part_number} · {r.part_name}</Link>
              {r.passport && <div><Link to={`/passports/${r.passport}`}>{r.passport_number}</Link> · revision {r.base_revision_number} ({r.base_revision_status} when requested)</div>}</dd>
            <dt>Data</dt><dd>{r.data_class_label}</dd>
            <dt>Requester</dt><dd>{r.requester} · {r.requester_role_label}<div className="muted small">{formatDate(r.created_at)}</div></dd>
            <dt>Reviewer</dt><dd>{r.reviewer_name || "—"}{r.decided_at && <div className="muted small">{formatDate(r.decided_at)}</div>}</dd>
            {r.applied_revision_number && <><dt>New revision</dt><dd><Link to={`/passports/${r.passport}?tab=history`}>rev {r.applied_revision_number} (draft)</Link></dd></>}
          </dl>
          <div className="stack">
            {(allowed.includes("approve") || allowed.includes("reject") || allowed.includes("request_corrections")) && (
              <textarea rows={3} aria-label="Reviewer note" placeholder="Note to the requester (required to reject or request corrections)" value={note} onChange={(e) => setNote(e.target.value)} />
            )}
            <div className="toolbar wrap">
              {allowed.includes("start_review") && <button type="button" className="btn" disabled={busy} onClick={() => void run("start-review/")}>Start review</button>}
              {allowed.includes("approve") && <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void run("approve/", { note })}>Approve</button>}
              {allowed.includes("request_corrections") && <button type="button" className="btn" disabled={busy || !note.trim()} onClick={() => void run("request-corrections/", { note })}>Request corrections</button>}
              {allowed.includes("reject") && <button type="button" className="btn btn-ghost" disabled={busy || !note.trim()} onClick={() => void run("reject/", { note })}>Reject with reason</button>}
              {allowed.includes("update") && !edits && <button type="button" className="btn" onClick={() => setEdits(Object.fromEntries(changes.map((c) => [c.field, String(c.proposed ?? "")])))}>Edit proposals</button>}
              {edits && <button type="button" className="btn" disabled={busy} onClick={() => void run("", { changes: changes.map((c) => ({ field: c.field, proposed: typeof c.proposed === "boolean" ? edits[c.field] === "true" : typeof c.proposed === "number" ? Number(edits[c.field]) : edits[c.field] })) }, "PATCH")}>Save proposals</button>}
              {allowed.includes("submit") && <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void run("submit/")}>{r.status === "corrections_requested" ? "Resubmit" : "Submit for review"}</button>}
              {allowed.includes("rebase") && <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void run("rebase/")}>Revalidate and resubmit</button>}
              {allowed.includes("withdraw") && <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => void run("withdraw/")}>Withdraw</button>}
            </div>
          </div>
        </Card>
      </div>
      <Card title="History">
        <ol className="review-timeline" aria-label="Edit request history">
          {events.map((e, i) => (
            <li key={i} className={`side-${e.side}`}>
              <strong>{ACTION_TEXT[e.action] ?? e.action}</strong> <span className="muted small">{e.user} · {e.side === "aries" ? "Aries" : "Client"} · {formatDate(e.created_at)}</span>
              {e.note && <div className="review-note">{e.note}</div>}
            </li>
          ))}
        </ol>
      </Card>
    </>
  );
}
