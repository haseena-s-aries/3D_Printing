/** Client: one request with its status, details, history, messages, attachments and withdrawal. */
import type { ServiceRequest } from "@passport/api-types";
import { Fragment, useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import { api, fetchObjectUrl, upload } from "../api/client";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { KindBadge, OPEN_STATUSES, OrderProgress, StatusBadge, Timeline, formatDay, formatPrice, type ClientQuotation } from "../components/requests";
import { BackLink, Badge, Card, ErrorNotice, Loading, Notice, PageHeader, formatBytes, formatDate } from "../components/ui";

export async function downloadAttachment(path: string, filename: string) {
  const url = await fetchObjectUrl(path);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 5000);
}

export function AttachmentList({ request, basePath }: { request: ServiceRequest; basePath: string }) {
  const [error, setError] = useState<unknown>(null);
  if (!request.attachments.length) return <p className="muted small">No attachments.</p>;
  return (
    <>
      <ErrorNotice error={error} />
      <ul className="doc-list">
        {request.attachments.map((a) => (
          <li key={a.id}>
            <span><strong>{a.original_filename}</strong> <span className="muted small">{a.detected_format} · {formatBytes(a.size_bytes)}</span></span>
            <button type="button" className="btn btn-small" onClick={() => downloadAttachment(`${basePath}/attachments/${a.id}/`, a.original_filename).catch(setError)}>Download</button>
          </li>
        ))}
      </ul>
    </>
  );
}

export function RequestFacts({ r }: { r: ServiceRequest }) {
  const rows: [string, string | null | undefined][] = r.kind === "digitisation"
    ? [["Site / location", r.site_location], ["Equipment", r.equipment], ["Part to digitise", r.part_description], ["Reason", r.reason?.replace(/_/g, " ")],
       ["Preferred date", r.preferred_date], ["Contact", [r.contact_name, r.contact_phone, r.contact_email].filter(Boolean).join(" · ")],
       ["Quotation reference", r.quotation_reference], ["Project", r.project_code]]
    : [["Part", `${r.part_number} ${r.part_name}`], ["Passport revision", r.passport_revision_number ? `rev ${r.passport_revision_number}` : "No passport"],
       ["Quantity", r.quantity ? String(r.quantity) : null], ["Required date", r.required_date], ["Delivery location", r.delivery_location],
       ["Services", (r.services as string[]).join(", ")]];
  return (
    <dl className="facts">
      {rows.map(([k, v]) => <Fragment key={k}><dt>{k}</dt><dd>{v || "—"}</dd></Fragment>)}
      {r.kind !== "digitisation" && (
        <>
          <dt>Material</dt>
          <dd>
            {r.material_option === "proposed" ? (
              <span data-testid="material-change">
                Change proposed: {r.original_material || "original not recorded"} → <strong>{r.proposed_material}</strong>{" "}
                <span className="badge badge-warning">Suitability not yet assessed</span>
                <div className="pre small">Reason: {r.material_change_reason}</div>
                <div className="small">{r.linked_part ? <>Linked part: <Link to={`/parts/${r.linked_part}`}>{r.linked_part_number}</Link> (clone, pending Aries review)</>
                  : "No separate part linked yet."}</div>
              </span>
            ) : <>Original material{r.original_material ? ` (${r.original_material})` : ""}</>}
          </dd>
        </>
      )}
      {r.kind === "digitisation" && (() => {
        const h = r.handover as { deliverables: { title: string; kind_label: string; file: string | null; file_version: number | null }[];
          handed_over_at: string | null; passport: string | null; passport_number: string | null } | null;
        const resp = r.responsible as { name: string } | null;
        return (
          <>
            <dt>Responsible</dt><dd>{resp ? resp.name : "Not assigned yet"}</dd>
            <dt>Deliverables</dt>
            <dd data-testid="scan-deliverables">{h && h.deliverables.length ? (
              <ul className="ref-list">{h.deliverables.map((d, i) => <li key={i}>{d.title} · {d.kind_label}
                {d.file ? <span className="muted small"> · v{d.file_version}, in the part's documents</span> : <span className="muted small"> · held by Aries</span>}</li>)}</ul>
            ) : "None recorded yet"}</dd>
            <dt>Handover</dt>
            <dd>{h?.handed_over_at ? <>Handed over to the digital passport{" "}
              {h.passport ? <Link to={`/passports/${h.passport}`}>{h.passport_number}</Link> : h.passport_number}</> : "Not yet"}</dd>
          </>
        );
      })()}
      {r.job_progress && (
        <>
          <dt>Manufacturing preparation</dt>
          <dd data-testid="job-progress">
            {r.job_progress === "preparing" ? "Aries is preparing the manufacturing documentation. This is not a production order or release."
              : "Aries has stopped the manufacturing preparation for this enquiry."}
          </dd>
        </>
      )}
      <dt>Priority</dt><dd>{r.priority === "urgent" ? "Urgent (breakdown)" : "Routine"}</dd>
      <dt>Your reference</dt><dd>{r.client_reference || "—"}</dd>
      <dt>Remarks</dt><dd className="pre">{r.remarks || "—"}</dd>
      <dt>Submitted</dt><dd>{formatDate(r.created_at)} · {r.requested_by_email}</dd>
      {r.acknowledged_at && <><dt>Acknowledged</dt><dd>{formatDate(r.acknowledged_at)}</dd></>}
      {r.closed_reason && <><dt>Closing note</dt><dd>{r.closed_reason}</dd></>}
    </dl>
  );
}

/** The quotation from Aries: the proposed method, price, delivery time and validity. The client accepts or rejects. */
function QuotationCard({ q, canDecide, requestId, onDone }: { q: ClientQuotation; canDecide: boolean; requestId: string; onDone: (r: ServiceRequest) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const open = q.status === "sent" && !q.expired;
  async function decide(decision: "accept" | "reject") {
    if (decision === "accept" && !window.confirm(`Accept ${q.method} for ${formatPrice(q)}, delivery in ${q.delivery_days} days? Aries then starts the order.`)) return;
    setBusy(true);
    setError(null);
    try {
      onDone(await api<ServiceRequest>(`/requests/${requestId}/quotation/`, { body: { decision, note: decision === "reject" ? reason : "" } }));
      setRejecting(false);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  const tone: "success" | "warning" | "info" = q.status === "accepted" ? "success" : q.status === "rejected" || q.status === "withdrawn" || q.expired ? "warning" : "info";
  return (
    <div className={`card quotation-card is-${q.status}`}>
      <div className="card-head">
        <h2>Quotation from Aries <span className="muted small">#{q.number}</span></h2>
        <Badge tone={tone}>{q.expired ? "Expired" : q.status === "sent" ? "Waiting for your decision" : q.status === "accepted" ? "Accepted" : q.status_label}</Badge>
      </div>
      <dl className="quotation-facts">
        <div><dt>Proposed method</dt><dd>{q.method}</dd></div>
        <div><dt>Price</dt><dd className="quotation-price">{formatPrice(q)}</dd></div>
        <div><dt>Delivery</dt><dd>{q.delivery_days} days after your acceptance</dd></div>
        <div><dt>Valid until</dt><dd>{formatDay(q.valid_until)}</dd></div>
      </dl>
      {q.note && <p className="small">{q.note}</p>}
      <ErrorNotice error={error} />
      {q.status === "accepted" && <Notice kind="success">You accepted this quotation{q.decided_at ? ` on ${formatDate(q.decided_at)}` : ""}. Aries is preparing the order.</Notice>}
      {q.status === "rejected" && <Notice kind="warning">You rejected this quotation{q.client_note ? `: ${q.client_note}` : ""}. Aries may send a revised one.</Notice>}
      {q.status === "withdrawn" && <Notice kind="warning">Aries withdrew this quotation. A new one will follow.</Notice>}
      {q.expired && <Notice kind="warning">This quotation has expired. Send Aries a message to ask for a new one.</Notice>}
      {open && canDecide && !rejecting && (
        <div className="toolbar">
          <button type="button" className="btn btn-primary" disabled={busy} aria-busy={busy} onClick={() => void decide("accept")}>Accept quotation</button>
          <button type="button" className="btn" disabled={busy} onClick={() => setRejecting(true)}>Reject</button>
        </div>
      )}
      {open && canDecide && rejecting && (
        <form className="stack" onSubmit={(e) => { e.preventDefault(); void decide("reject"); }}>
          <label className="field"><span>Why do you reject it? (shown to Aries)</span>
            <textarea rows={2} maxLength={1000} required value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. price too high, delivery too late" /></label>
          <div className="toolbar">
            <button type="button" className="btn btn-ghost" onClick={() => setRejecting(false)}>Cancel</button>
            <button className="btn btn-primary" disabled={busy || !reason.trim()} aria-busy={busy}>Reject quotation</button>
          </div>
        </form>
      )}
      {open && !canDecide && <p className="muted small">Your Client Administrator or the person who sent the request decides.</p>}
    </div>
  );
}

export default function RequestDetailPage() {
  const { id } = useParams();
  const { can } = useAuth();
  const req = useApi<ServiceRequest>(`/requests/${id}/`);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [file, setFile] = useState<File | null>(null);

  useEffect(() => {
    const t = window.setInterval(() => void req.reload(), 20000);
    return () => window.clearInterval(t);
  }, [req.reload]);

  if (req.loading && !req.data) return <Loading />;
  if (req.error || !req.data) return <ErrorNotice error={req.error} />;
  const r = req.data;
  const open = OPEN_STATUSES.includes(r.status);
  const canAct = can("requests.create") && open;

  async function send(e: FormEvent, path: "reply" | "withdraw") {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      req.setData(await api<ServiceRequest>(`/requests/${id}/${path}/`, { body: { message } }));
      setMessage("");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function attach() {
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    setError(null);
    try {
      await upload(`/requests/${id}/attachments/`, form);
      setFile(null);
      await req.reload();
    } catch (err) {
      setError(err);
    }
  }

  return (
    <>
      <BackLink to="/requests">My requests</BackLink>
      <PageHeader title={`${r.reference}`} subtitle={<><KindBadge kind={r.kind} /> <StatusBadge status={r.status} /></>} />
      {r.kind === "enquiry" && (
        <Notice>This is an enquiry. Our team will reply here; an enquiry does not start manufacturing.</Notice>
      )}
      {r.kind === "manufacturing_request" && (
        <Card title="Order progress">
          <OrderProgress status={r.status} />
          <p className="muted small">Every order is checked by Aries engineering and QA and released before production, and inspected before delivery.</p>
        </Card>
      )}
      {(r as ServiceRequest & { quotation?: ClientQuotation | null }).quotation && (
        <QuotationCard q={(r as ServiceRequest & { quotation: ClientQuotation }).quotation} canDecide={can("requests.create")} requestId={r.id}
          onDone={(next) => req.setData(next)} />
      )}
      {r.status === "information_requested" && <Notice kind="warning">Our team needs more information. Please reply below.</Notice>}
      <div className="grid-2">
        <Card title="Details">
          <RequestFacts r={r} />
          {r.kind !== "digitisation" && r.part && <p><Link to={`/parts/${r.part}`}>Open part</Link></p>}
        </Card>
        <Card title="History">
          <Timeline events={r.events} />
          <ErrorNotice error={error} />
          {canAct && (
            <form className="stack" onSubmit={(e) => send(e, "reply")} aria-label="Reply to the operator team">
              <textarea rows={3} maxLength={2000} placeholder={r.status === "information_requested" ? "Your answer" : "Message to our team"} value={message} onChange={(e) => setMessage(e.target.value)} />
              <div className="toolbar">
                <button className="btn btn-primary" disabled={busy || !message.trim()} aria-busy={busy}>{r.status === "information_requested" ? "Send information" : "Send message"}</button>
                {["submitted", "acknowledged", "information_requested", "information_provided"].includes(r.status) && (
                  <button type="button" className="btn btn-ghost" disabled={busy} onClick={(e) => { if (window.confirm("Withdraw this request?")) void send(e as unknown as FormEvent, "withdraw"); }}>Withdraw request</button>
                )}
              </div>
            </form>
          )}
        </Card>
      </div>
      <Card title="Attachments">
        <AttachmentList request={r} basePath={`/requests/${id}`} />
        {canAct && (
          <div className="toolbar">
            <input type="file" aria-label="Add attachment" accept=".jpg,.jpeg,.png,.pdf,.stp,.step,.dwg" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            <button type="button" className="btn" disabled={!file} onClick={() => void attach()}>Upload</button>
          </div>
        )}
      </Card>
    </>
  );
}
