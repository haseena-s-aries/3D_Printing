/**
 * Operator: one client request. Actions follow the server's workflow: acknowledge, request information, reply and
 * close (enquiries), schedule / start / complete / decline and create the project (3D scanning). There is no
 * review, release or production action: manufacturing authorisation is not part of this workflow.
 */
import type { OperatorRequest } from "@passport/api-types";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { Eligibility } from "../components/catalog";
import { JobSheetPanel } from "../components/JobSheetPanel";
import ScanHandoverPanel from "../components/ScanHandoverPanel";
import { KindBadge, OPEN_STATUSES, StatusBadge, Timeline } from "../components/requests";
import { BackLink, Card, ErrorNotice, Loading, Notice, PageHeader } from "../components/ui";
import { AttachmentList, RequestFacts } from "./RequestDetailPage";

type Action = { action: string; label: string; done: string; needsMessage?: boolean; primary?: boolean };

function actionsFor(kind: string, status: string): Action[] {
  const working = ["acknowledged", "information_provided"].includes(status);
  const out: Action[] = [];
  if (status === "submitted") out.push({ action: "acknowledge", label: "Acknowledge", done: "Request acknowledged", primary: true });
  if (kind !== "digitisation") {
    if (working || status === "answered") out.push({ action: "request_information", label: "Request information", done: "Information requested", needsMessage: true });
    if (working || status === "answered") out.push({ action: "respond", label: "Send reply", done: "Reply sent", needsMessage: true, primary: true });
    if (status === "information_requested") out.push({ action: "message", label: "Send message", done: "Message sent", needsMessage: true, primary: true });
    if (OPEN_STATUSES.includes(status) && status !== "submitted") out.push({ action: "close", label: "Close with reason", done: "Request closed", needsMessage: true });
  } else {
    // 3D scanning: a plain message to the client (the status stays as it is)
    if (OPEN_STATUSES.includes(status) && status !== "submitted") out.push({ action: "message", label: "Send message", done: "Message sent", needsMessage: true });
    if (working || ["scheduled", "in_progress"].includes(status)) out.push({ action: "request_information", label: "Request information", done: "Information requested", needsMessage: true });
    if (working) out.push({ action: "schedule", label: "Mark scheduled", done: "Marked as scheduled", primary: true });
    if (working || status === "scheduled") out.push({ action: "start", label: "Mark in progress", done: "Marked as in progress" });
    if (status === "in_progress") out.push({ action: "complete", label: "Mark completed", done: "Marked as completed", primary: true });
    if (OPEN_STATUSES.includes(status) && status !== "submitted") out.push({ action: "decline", label: "Decline with reason", done: "Request declined", needsMessage: true });
  }
  return out;
}

export default function IncomingRequestDetailPage() {
  const { id } = useParams();
  const { session } = useAuth();
  const req = useApi<OperatorRequest>(`/operator/requests/${id}/`);
  const [message, setMessage] = useState("");
  const [quote, setQuote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState("");

  useEffect(() => {
    const t = window.setInterval(() => void req.reload(), 20000);
    return () => window.clearInterval(t);
  }, [req.reload]);

  if (req.loading && !req.data) return <Loading />;
  if (req.error || !req.data) return <><BackLink to="/incoming">Incoming requests</BackLink><ErrorNotice error={req.error} /></>;
  const r = req.data;
  const sameOrg = session?.tenant.name === r.client_name; // passports open in the client organisation context

  async function act(a: Action) {
    if (a.needsMessage && !message.trim()) {
      setError(new Error("Enter a message for the client first."));
      return;
    }
    setBusy(true);
    setError(null);
    setDone("");
    try {
      const body: Record<string, string> = { action: a.action, message };
      if (quote !== null) body.quotation_reference = quote;
      req.setData(await api<OperatorRequest>(`/operator/requests/${id}/act/`, { body }));
      setMessage("");
      setDone(`${a.done}. The client has been notified.`);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const actions = actionsFor(r.kind, r.status);
  return (
    <>
      <BackLink to="/incoming">Incoming requests</BackLink>
      <PageHeader title={`${r.intake_number || r.reference} · ${r.client_name}`}
        subtitle={<><KindBadge kind={r.kind} /> <StatusBadge status={r.status} /> <span className="muted small">Client reference {r.reference}</span></>} />
      {r.kind === "enquiry" && (
        <Notice>Enquiry: the part is not published and eligible for manufacturing. Reply and close it; it cannot become a production order here.</Notice>
      )}
      {r.kind === "manufacturing_request" && (
        <Notice kind="warning">Engineering review, QA confirmation and production release are not available in this release. Acknowledge and reply only.</Notice>
      )}
      <div className="grid-2">
        <Card title="Request">
          <RequestFacts r={r} />
          {r.part_summary && (
            <div className="stack">
              <div className="chips"><Eligibility value={r.part_summary.manufacturing_eligibility as string | null} /></div>
              <p className="small">
                {r.part_summary.passport_number ? `Passport ${r.part_summary.passport_number}` : "No passport"} · {String(r.part_summary.dimensions || "")}{" "}
                {sameOrg && r.part_summary.passport_id ? <Link to={`/passports/${r.part_summary.passport_id}`}>Open passport</Link>
                  : <span className="muted">Switch to {r.client_name} to open the passport.</span>}
              </p>
            </div>
          )}
        </Card>
        <Card title="Actions">
          <ErrorNotice error={error} />
          {done && <Notice kind="success">{done}</Notice>}
          {actions.length ? (
            <div className="stack">
              <textarea rows={4} maxLength={2000} aria-label="Message to the client" placeholder="Message to the client (shown in their request history)" value={message} onChange={(e) => setMessage(e.target.value)} />
              {r.kind === "digitisation" && (
                <label className="field"><span>Quotation reference (offline, optional)</span>
                  <input maxLength={80} value={quote ?? r.quotation_reference ?? ""} onChange={(e) => setQuote(e.target.value)} />
                </label>
              )}
              <div className="toolbar wrap">
                {actions.map((a) => (
                  <button key={a.action} type="button" className={`btn ${a.primary ? "btn-primary" : ""}`} disabled={busy} onClick={() => void act(a)}>{a.label}</button>
                ))}
                {r.kind === "digitisation" && !r.created_part && ["acknowledged", "information_provided", "scheduled", "in_progress"].includes(r.status) && (
                  <button type="button" className="btn" disabled={busy} onClick={() => void act({ action: "create_project", label: r.project ? "Create draft part" : "Create project and draft part",
                    done: r.project ? "Draft part created" : "Project and draft part created" })}>{r.project ? "Create draft part in the project" : "Create project and draft part"}</button>
                )}
              </div>
            </div>
          ) : <p className="muted">No further actions: this request is {r.status.replace(/_/g, " ")}.</p>}
          {r.project_code && <p className="small">Project <strong>{r.project_code}</strong>{r.created_part ? " · draft part created" : ""} in {r.client_name}.</p>}
        </Card>
      </div>
      <ScanHandoverPanel envelopeId={id!} request={r} sameOrg={sameOrg} onChange={(next) => req.setData(next)} />
      <JobSheetPanel envelopeId={id!} status={r.status} kind={r.kind} />
      <div className="grid-2">
        <Card title="History"><Timeline events={r.events} /></Card>
        <Card title="Attachments"><AttachmentList request={r} basePath={`/operator/requests/${id}`} /></Card>
      </div>
    </>
  );
}
