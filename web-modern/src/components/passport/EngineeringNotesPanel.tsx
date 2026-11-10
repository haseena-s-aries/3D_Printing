/**
 * D-13: the revision's engineering notes (conflict register), shown exactly as stored. Lines starting "C-nn:" are listed
 * as conflicts; a category is shown only when the line itself starts with a known label (no keyword guessing). No
 * verification status is stored, so none is shown as given. Roles without passports.view_engineering_notes never
 * receive the text from the API and see only a generic "Engineering review pending" indicator.
 */
import type { Revision } from "@passport/api-types";

import { Badge } from "../ui";

const LABELS: [RegExp, string][] = [
  [/^Material conflict\b/i, "Material"],
  [/^Job number conflict\b/i, "Job reference"],
  [/^Dimensional discrepancy\b/i, "Dimensional"],
  [/^Date inconsistency\b/i, "Document traceability"],
  [/^Incomplete QA documentation\b/i, "QA documentation"],
];

export function categoryOf(text: string): string | null {
  return LABELS.find(([re]) => re.test(text.trim()))?.[1] ?? null;
}

export function parseNotes(notes: string): { kind: "conflict" | "text"; id?: string; text: string }[] {
  return notes.split(/\r?\n/).map((line) => {
    const m = /^(C-\d+):\s?(.*)$/.exec(line);
    return m ? { kind: "conflict" as const, id: m[1], text: m[2] } : { kind: "text" as const, text: line };
  });
}

export default function EngineeringNotesPanel({ revision }: { revision: Revision }) {
  const notes = (revision.content as { notes?: string } | undefined)?.notes;
  if (!revision.engineering_review_pending) return null;
  if (revision.notes_restricted || !notes) {
    return (
      <section className="card notes-panel" aria-label="Engineering review">
        <div className="card-head"><h2>Engineering review pending</h2><Badge tone="warning">Review pending</Badge></div>
        <p className="muted small">Engineering notes are recorded for this revision. Their details are restricted to Aries engineering and QA, client
          administrators, and people given technical or audit access.</p>
      </section>
    );
  }
  const items = parseNotes(notes);
  return (
    <section className="card notes-panel" aria-label="Engineering notes">
      <div className="card-head"><h2>Engineering notes and conflicts</h2><Badge tone="warning">Review pending</Badge></div>
      <p className="muted small">
        Recorded in revision {revision.revision_number} ({revision.status}), shown exactly as stored. Not resolved and not an approval.
        Engineer verification: not recorded.
      </p>
      <ul className="list notes-list">
        {items.filter((i) => i.kind === "conflict").map((i) => {
          const cat = categoryOf(i.text);
          return (
            <li key={i.id}>
              <Badge tone="warning">{i.id}</Badge> {cat ? <Badge tone="info">{cat}</Badge> : null} <span className="pre-wrap">{i.text}</span>
              <div className="muted small">Engineer verification: not recorded</div>
            </li>
          );
        })}
      </ul>
      <h3>Full notes as stored</h3>
      <pre className="notes-verbatim" data-testid="notes-verbatim">{notes}</pre>
    </section>
  );
}
