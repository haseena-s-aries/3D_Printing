import type { Revision } from "@passport/api-types";
import { useState } from "react";

import { Badge, Empty, formatDate } from "../ui";
import { FIELD_LABELS, Progress } from "./ReadinessForms";
import { diffContent, flattenContent } from "./revisionDiff";

const readable = (key: string) => {
  const [level, ...rest] = key.split(".");
  const field = rest.join(".");
  const name = FIELD_LABELS[field] ?? FIELD_LABELS[key] ?? field.replace(/_/g, " ").replace(/\./g, " › ");
  return level === "notes" ? "Notes" : `${level.toUpperCase().replace("RL", "R-L")} · ${name}`;
};

/** Revision history: who changed what and when; any revision can be opened read-only and compared (BR-034). */
export default function RevisionsTab({ revisions }: { revisions: Revision[] }) {
  const [selected, setSelected] = useState<number | null>(revisions[0]?.revision_number ?? null);
  if (!revisions.length) return <Empty>No revisions yet.</Empty>;
  const sorted = [...revisions].sort((a, b) => b.revision_number - a.revision_number);
  const current = sorted.find((r) => r.revision_number === selected) ?? sorted[0];
  const previous = sorted.find((r) => r.revision_number < current.revision_number);
  const changes = previous ? diffContent(previous.content, current.content) : [];
  const fields = Object.entries(flattenContent(current.content));

  return (
    <div className="grid-2 wide-right">
      <ul className="list revision-list" aria-label="Revisions">
        {sorted.map((r) => (
          <li key={r.id} className={r.revision_number === current.revision_number ? "selected" : ""}>
            <button type="button" className="link-btn" onClick={() => setSelected(r.revision_number)}>
              Revision {r.revision_number}
            </button>{" "}
            <Badge tone={r.status === "approved" ? "success" : r.status === "draft" ? "info" : "neutral"}>{r.status}</Badge>
            <div className="muted small">{r.change_summary || "No summary"}</div>
            <div className="muted small">
              Created {formatDate(r.created_at)} by {r.created_by_email || "—"}
              {r.updated_by_email && <> · last changed {formatDate(r.updated_at)} by {r.updated_by_email}</>}
            </div>
          </li>
        ))}
      </ul>
      <div>
        <h3>
          Revision {current.revision_number} <span className="muted small">({current.status}, read-only view)</span>
        </h3>
        <p>
          <Progress level="R-L1" c={current.completeness?.rl1} /> <Progress level="R-L2" c={current.completeness?.rl2} /> <Progress level="R-L3" c={current.completeness?.rl3} />
        </p>
        {previous ? (
          <>
            <h4>Changes since revision {previous.revision_number}</h4>
            {changes.length ? (
              <table className="table table-compact" aria-label="Changes from previous revision">
                <thead><tr><th>Field</th><th>Before</th><th>After</th></tr></thead>
                <tbody>
                  {changes.map((c) => (
                    <tr key={c.key}><td>{readable(c.key)}</td><td className="diff-before">{c.before || "—"}</td><td className="diff-after">{c.after || "—"}</td></tr>
                  ))}
                </tbody>
              </table>
            ) : <p className="muted">No data changes.</p>}
          </>
        ) : <p className="muted small">First revision: nothing to compare with.</p>}
        <h4>Recorded data</h4>
        {fields.length ? (
          <dl className="facts">
            {fields.map(([k, v]) => (
              <div key={k} className="fact-row"><dt>{readable(k)}</dt><dd>{v}</dd></div>
            ))}
          </dl>
        ) : <p className="muted">No data recorded in this revision.</p>}
        <p className="muted small">
          New revisions are started once the current one is approved. Approval is not available until the rules are decided (OQ-35),
          so passports currently have a single draft revision.
        </p>
      </div>
    </div>
  );
}
