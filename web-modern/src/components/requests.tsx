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

export const OPEN_STATUSES = ["submitted", "acknowledged", "information_requested", "information_provided", "answered", "scheduled", "in_progress"];

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
  client_message: "Message",
  project_created: "Project and draft part",
  project_linked: "Linked to a project",
  assigned: "Responsible engineer assigned",
  deliverable_recorded: "Deliverable recorded",
  handed_over: "Handed over to the digital passport",
  job_preparation: "Manufacturing documentation in preparation",
};

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
