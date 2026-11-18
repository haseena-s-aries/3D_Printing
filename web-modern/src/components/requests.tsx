/** Shared request UI: consistent status labels, request-type badges, classification explanation and history. */
import type { Part, RequestEvent } from "@passport/api-types";

import { Badge, formatDate } from "./ui";

type Tone = "neutral" | "info" | "success" | "warning" | "danger";

export const STATUS: Record<string, [string, Tone]> = {
  submitted: ["Submitted · awaiting acknowledgement", "warning"],
  acknowledged: ["Acknowledged", "info"],
  information_requested: ["Information requested", "warning"],
  information_provided: ["Information provided", "info"],
  answered: ["Answered", "success"],
  scheduled: ["Scheduled", "info"],
  in_progress: ["In progress", "info"],
  engineering_checked: ["Engineering checked", "info"],
  qa_approved: ["QA approved", "info"],
  released: ["Released for production", "info"],
  in_production: ["In production", "info"],
  inspected: ["Inspected · ready to deliver", "info"],
  completed: ["Completed", "success"],
  closed: ["Closed", "neutral"],
  declined: ["Declined", "danger"],
  withdrawn: ["Withdrawn", "neutral"],
};

export const KIND: Record<string, string> = {
  enquiry: "Manufacturing enquiry",
  manufacturing_request: "Manufacturing request",
  digitisation: "3D scanning request",
  assessment: "AI assessment request",
};

export const OPEN_STATUSES = ["submitted", "acknowledged", "information_requested", "information_provided", "answered", "scheduled", "in_progress",
  "engineering_checked", "qa_approved", "released", "in_production", "inspected"];

export function StatusBadge({ status }: { status: string }) {
  const [text, tone] = STATUS[status] ?? [status, "neutral"];
  return <Badge tone={tone}>{text}</Badge>;
}

export function KindBadge({ kind }: { kind: string }) {
  return <Badge tone={kind === "digitisation" ? "info" : "neutral"}>{KIND[kind] ?? kind}</Badge>;
}

const ELIGIBLE = ["eligible", "eligible_subject_to_authorisation"];

/** What a Request on this part will be. The server decides the same way and is authoritative. */
export function classification(part: Pick<Part, "publication_state" | "manufacturing_eligibility" | "passport_id">) {
  if (part.publication_state === "published" && ELIGIBLE.includes(part.manufacturing_eligibility ?? "")) {
    return {
      kind: "manufacturing_request",
      title: "Manufacturing request",
      text: "This part is published and eligible. Our engineering and QA teams review every request before anything is produced.",
    };
  }
  const why = !part.passport_id
    ? "This part does not have a digital passport yet."
    : part.publication_state !== "published"
      ? "This part is still being digitised and is not yet published in your manufacturing catalog."
      : "This part is not currently eligible for manufacturing.";
  return {
    kind: "enquiry",
    title: "This request will be sent as an enquiry",
    text: `${why} Your request will be sent to our team as an enquiry, not as a manufacturing order. We will acknowledge it and reply. Nothing is produced from an enquiry.`,
  };
}

const EVENT_TEXT: Record<string, string> = {
  submitted: "Request submitted",
  acknowledged: "Acknowledged by the operator team",
  information_requested: "More information requested",
  information_provided: "Information provided",
  answered: "Reply from the operator team",
  closed: "Request closed",
  scheduled: "Scanning scheduled",
  in_progress: "Work in progress",
  completed: "Completed",
  declined: "Request declined",
  withdrawn: "Withdrawn",
  client_message: "Message from the client",
  operator_message: "Message from the operator team",
  project_created: "Project and draft part",
  project_linked: "Linked to a project",
  assigned: "Responsible engineer assigned",
  deliverable_recorded: "Deliverable recorded",
  handed_over: "Handed over to the digital passport",
  job_preparation: "Manufacturing documentation in preparation",
  engineering_checked: "Engineering check passed",
  qa_approved: "QA approved",
  released: "Released for production",
  in_production: "Production started",
  inspection_failed: "Inspection found issues · part is being reworked",
  inspected: "Inspection passed",
  quotation_sent: "Quotation from Aries",
  quotation_withdrawn: "Quotation withdrawn by Aries",
  quotation_accepted: "Quotation accepted",
  quotation_rejected: "Quotation rejected",
};

/** What a client sees of a quotation: the method, one price, delivery days and validity (decision of 18 Nov 2026). */
export type ClientQuotation = { number: number; method: string; price: string; currency: string; delivery_days: number; valid_until: string;
  note: string; status: "sent" | "accepted" | "rejected" | "withdrawn" | "superseded"; status_label: string; expired: boolean;
  sent_at: string; decided_at: string | null; client_note: string; route?: string; sent_by?: string; decided_by?: string };

/** A date without a time (quotation validity). */
export function formatDay(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return new Date(y, (m || 1) - 1, d || 1).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export function formatPrice(q: Pick<ClientQuotation, "price" | "currency">): string {
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency: q.currency }).format(Number(q.price));
  } catch {
    return `${q.currency} ${q.price}`;
  }
}

/** Manufacturing order flow (decision of 13 Nov 2026). `completed` means delivered for a manufacturing request. */
export const ORDER_STEPS: [string, string][] = [
  ["submitted", "Submitted"], ["acknowledged", "Acknowledged"], ["engineering_checked", "Engineering check"], ["qa_approved", "QA check"],
  ["released", "Released"], ["in_production", "In production"], ["inspected", "Inspected"], ["completed", "Delivered"],
];

/** Where an order is in the flow: finished steps ticked, the next one highlighted. While information is requested or
 * provided it sits after "Acknowledged". */
export function OrderProgress({ status }: { status: string }) {
  if (["closed", "withdrawn", "declined"].includes(status)) return null;
  const found = ORDER_STEPS.findIndex(([s]) => s === status);
  const last = found >= 0 ? found : 1;  // the last step finished; the next one is under way
  return (
    <ol className="order-steps" aria-label="Order progress">
      {ORDER_STEPS.map(([s, text], i) => {
        const state = i <= last ? "done" : i === last + 1 ? "current" : "todo";
        return <li key={s} className={`order-step is-${state}`} aria-current={state === "current" ? "step" : undefined}><span className="order-dot">{state === "done" ? "✓" : i + 1}</span>{text}</li>;
      })}
    </ol>
  );
}

export function Timeline({ events }: { events: RequestEvent[] }) {
  return (
    <ol className="timeline" aria-label="Request history">
      {events.map((e) => (
        <li key={e.id} className={`timeline-item side-${e.author_side}`}>
          <div className="timeline-head">
            <strong>{EVENT_TEXT[e.event] ?? e.event}</strong>
            <span className="muted small">{e.author_name} · {formatDate(e.created_at)}</span>
          </div>
          {e.message && <p className="timeline-message">{e.message}</p>}
        </li>
      ))}
    </ol>
  );
}
