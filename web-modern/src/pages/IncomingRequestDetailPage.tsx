/**
 * Operator: one client request. Actions follow the server's workflow: acknowledge, request information, reply and
 * close (enquiries), schedule / start / complete / decline and create the project (3D scanning), and for manufacturing
 * requests the order flow: engineering check -> QA check -> release -> production -> inspection -> delivered. Each step
 * is shown only to the role that may take it (`my_steps` from the server, which enforces the same rule). Orders talk to
 * the client with "Send message" (a reply would leave the order flow). The ordered passport is shown read-only below.
 */
import type { OperatorRequest } from "@passport/api-types";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { Eligibility } from "../components/catalog";
import { JobSheetPanel } from "../components/JobSheetPanel";
import { CostEstimateCard } from "../components/CostEstimate";
import ScanHandoverPanel from "../components/ScanHandoverPanel";
import { KindBadge, OPEN_STATUSES, OrderProgress, StatusBadge, Timeline } from "../components/requests";
import { BackLink, Card, ErrorNotice, Loading, Notice, PageHeader, formatDate } from "../components/ui";
import { FieldGrid, Meters, PartFiles, RevisionContent, Section, type Detail } from "./PassportApprovalsPage";
import { AttachmentList, RequestFacts } from "./RequestDetailPage";

type PartDetails = Record<string, string | null> & { part_number: string; name: string };
type OrderPart = Detail & { part: PartDetails; has_passport: boolean; ordered_revision_number: number | null; current_revision_number: number | null };

const PART_FIELDS: [string, string][] = [
  ["part_number", "Part number"], ["name", "Name"], ["description", "Description"], ["category", "Category"], ["criticality", "Criticality"],
  ["original_material", "Original material"], ["dimensions", "Dimensions"], ["application", "Application"],
  ["equipment_reference", "Equipment"], ["manufacturer", "Manufacturer / OEM"], ["project", "Project"], ["origin", "Created by"],
  ["submission_kind", "Client submission"], ["submitted_by", "Submitted by"], ["source_part_number", "Clone of part"],
  ["source_passport_number", "Clone of passport"], ["proposed_material", "Proposed material"], ["material_change_reason", "Reason for material change"],
  ["client_remarks", "Client remarks"],
];
// shown only when filled (clone and submission details); the others always, as "Not recorded" when empty
const OPTIONAL = new Set(["submission_kind", "submitted_by", "source_part_number", "source_passport_number", "proposed_material",
  "material_change_reason", "client_remarks", "project"]);

/** The ordered part, read-only, so the engineering check, QA check and inspection are done from the request: the spare
 *  part's details, the passport revision the client ordered (R-L1 / R-L2 / R-L3), documents, reports and the 3D model.
 *  Every opening is audited in the client company. */
function OrderPartCard({ id }: { id: string }) {
  const [open, setOpen] = useState(true);
  const root = `/operator/requests/${id}/passport`;
  const d = useApi<OrderPart>(open ? `${root}/` : null);
  const p = d.data;
  const partRows: [string, unknown][] = p ? PART_FIELDS.filter(([k]) => !OPTIONAL.has(k) || p.part[k]).map(([k, l]) => [l, p.part[k]]) : [];
  return (
    <div className="card order-passport">
      <div className="card-head">
        <h2>Part, passport and documents{p?.has_passport ? ` · ${p.passport_number} rev ${p.revision.revision_number}` : ""}</h2>
        <button type="button" className="btn btn-small" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "Hide" : "Show details"}</button>
      </div>
      {open && (
        <>
          <ErrorNotice error={d.error} />
          {d.loading && !p ? <Loading label="Loading part and passport…" /> : p && (
            <div className="approval-content">
              <p className="muted small">Read only. Check the part, its passport, documents and 3D model before taking your step.</p>
              <Section title="Spare part"><FieldGrid rows={partRows} /></Section>
              {p.has_passport ? (
                <>
                  {p.ordered_revision_number && p.current_revision_number && p.current_revision_number !== p.ordered_revision_number && (
                    <Notice kind="warning">The client ordered revision {p.ordered_revision_number}. The passport is now at revision {p.current_revision_number}; this shows the ordered revision.</Notice>
                  )}
                  <Meters c={(p.revision.completeness ?? {}) as Record<string, { done: number; total: number }>} />
                  <RevisionContent d={{ ...p, root }} />
                </>
              ) : (
                <>
                  <Notice>This part has no digital passport yet, so there are no R-L1 / R-L2 / R-L3 details or reports.</Notice>
                  <PartFiles d={{ ...p, root, passport_number: p.part.part_number } as Detail} />
                </>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

type Action = { action: string; label: string; done: string; needsMessage?: boolean; primary?: boolean };
type ProductionRoute = { route: string; label: string; version: number; newer_version: number | null; currency: string; low: number | null;
  high: number | null; days: number | null; manpower_hours: number | null; note: string; chosen_at: string | null; chosen_by: string };

/** The production route the Aries Admin or Manager chose in the cost estimate; release waits for it (decision of 17 Nov 2026). */
function RouteSummary({ route, status }: { route: ProductionRoute | null; status: string }) {
  if (!route) {
    return ["engineering_checked", "qa_approved"].includes(status)
      ? <Notice kind="warning">No production route chosen yet. The Aries Admin or Manager chooses it in the <strong>Cost estimate</strong> below; release waits for it.</Notice>
      : null;
  }
  let money = (n: number | null) => (n == null ? "—" : String(n));
  try {
    const f = new Intl.NumberFormat(undefined, { style: "currency", currency: route.currency || "USD", maximumFractionDigits: 0 });
    money = (n) => (n == null ? "—" : f.format(n));
  } catch { /* unknown currency code: plain numbers */ }
  return (
    <div className="route-summary">
      <span>Production route: <strong>{route.label}</strong></span>
      {route.low != null && <span>· estimated {money(route.low)} – {money(route.high)}</span>}
      {route.days != null && <span>· {route.days} days</span>}
      <span className="muted small">· chosen by {route.chosen_by}{route.chosen_at ? ` on ${formatDate(route.chosen_at)}` : ""}{route.note ? ` · “${route.note}”` : ""}
        {" "}(estimate v{route.version}{route.newer_version ? `; newer estimate v${route.newer_version} exists, choose again if the figures changed` : ""})</span>
    </div>
  );
}

/** Manufacturing order steps: [action, from statuses, roles, label, done text, message required]. */
const ORDER: [string, string[], string[], string, string, boolean][] = [
  ["engineering_check", ["acknowledged", "information_provided", "answered"], ["engineer"], "Engineering check passed", "Engineering check recorded", false],
  ["qa_approve", ["engineering_checked"], ["qa"], "QA approve", "QA approval recorded", false],
  ["release", ["qa_approved"], ["admin"], "Release for production", "Released for production", false],
  ["start_production", ["released"], ["engineer", "admin"], "Start production", "Production started", false],
  ["inspection_passed", ["in_production"], ["qa"], "Inspection passed", "Inspection passed", false],
  ["inspection_failed", ["in_production"], ["qa"], "Inspection failed · rework", "Inspection failure recorded", true],
  ["deliver", ["inspected"], ["engineer", "admin"], "Mark delivered", "Marked as delivered", false],
];
const WAITING: Record<string, string> = {
  acknowledged: "an Aries Engineer to do the engineering check", information_provided: "an Aries Engineer to do the engineering check",
  engineering_checked: "Aries QA to do the QA check (not the engineer who checked it)", qa_approved: "an Aries Admin or Manager to choose the production route (Cost estimate below) and release it",
  released: "an Aries Engineer, Admin or Manager to start production", in_production: "Aries QA to inspect the part",
  inspected: "an Aries Engineer, Admin or Manager to mark it delivered",
};

function actionsFor(kind: string, status: string, steps: string[]): Action[] {
  const working = ["acknowledged", "information_provided"].includes(status);
  const out: Action[] = [];
  if (status === "submitted") out.push({ action: "acknowledge", label: "Acknowledge", done: "Request acknowledged", primary: true });
  if (kind === "manufacturing_request") {
    ORDER.filter(([, from, roles]) => from.includes(status) && roles.some((x) => steps.includes(x)))
      .forEach(([action, , , label, done, needsMessage]) => out.push({ action, label, done, needsMessage, primary: action !== "inspection_failed" }));
    if (OPEN_STATUSES.includes(status) && status !== "submitted") out.push({ action: "message", label: "Send message", done: "Message sent", needsMessage: true });
    if (working || ["engineering_checked", "qa_approved"].includes(status)) out.push({ action: "request_information", label: "Request information", done: "Information requested", needsMessage: true });
    if (OPEN_STATUSES.includes(status) && status !== "submitted") out.push({ action: "close", label: "Close with reason", done: "Request closed", needsMessage: true });
    return out;
  }
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

  const steps = (r as OperatorRequest & { my_steps?: string[] }).my_steps ?? [];
  const route = (r as OperatorRequest & { production_route?: ProductionRoute | null }).production_route ?? null;
  const actions = actionsFor(r.kind, r.status, steps);
  return (
    <>
      <BackLink to="/incoming">Incoming requests</BackLink>
      <PageHeader title={`${r.intake_number || r.reference} · ${r.client_name}`}
        subtitle={<><KindBadge kind={r.kind} /> <StatusBadge status={r.status} /> <span className="muted small">Client reference {r.reference}</span></>} />
      {r.kind === "enquiry" && (
        <Notice>Enquiry: the part is not published and eligible for manufacturing. Reply and close it; it cannot become a production order here.</Notice>
      )}
      {r.kind === "manufacturing_request" && (
        <Card title="Order progress">
          <OrderProgress status={r.status} />
          {WAITING[r.status] && <p className="muted small">Waiting for {String(r.status) === "qa_approved" && route ? "an Aries Admin or Manager to release it" : WAITING[r.status]}.</p>}
          <RouteSummary route={route} status={r.status} />
        </Card>
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
                  : r.part_summary.passport_id ? <span className="muted">Details below, under "Part, passport and documents".</span> : null}
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
                {actions.map((a) => {
                  const blocked = a.action === "release" && !route; // production goes ahead the way the Admin or Manager chose
                  return <button key={a.action} type="button" className={`btn ${a.primary ? "btn-primary" : ""}`} disabled={busy || blocked}
                    title={blocked ? "Choose the production route in the Cost estimate first" : undefined} onClick={() => void act(a)}>{a.label}</button>;
                })}
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
      {r.kind !== "digitisation" && r.part_summary && <OrderPartCard id={id!} />}
      {r.kind !== "digitisation" && r.part_summary && (
        <CostEstimateCard envelopeId={id!} locked={["released", "in_production", "inspected", "completed"].includes(r.status)} onChange={() => void req.reload()} />
      )}
      <ScanHandoverPanel envelopeId={id!} request={r} sameOrg={sameOrg} onChange={(next) => req.setData(next)} />
      <JobSheetPanel envelopeId={id!} status={r.status} kind={r.kind} />
      <div className="grid-2">
        <Card title="History"><Timeline events={r.events} /></Card>
        <Card title="Attachments"><AttachmentList request={r} basePath={`/operator/requests/${id}`} /></Card>
      </div>
    </>
  );
}
