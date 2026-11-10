/**
 * Clone lineage (BR-033, CN-003): original-versus-clone comparison, source references (CAD and passport of the original,
 * shown as references only), clones of a part, and the review history of client submissions.
 */
import type { EngineeringFile, Paginated, Part, PartReviewEvent } from "@passport/api-types";
import { Link } from "react-router-dom";

import { useApi } from "../api/useApi";
import { Badge, Card, formatDate } from "./ui";

export type ChangeRow = { field: string; original: string; clone: string; changed: boolean };

const FIELD_NAME: Record<string, string> = {
  name: "Part name", equipment_reference: "Equipment / machinery", manufacturer: "Manufacturer / OEM", application: "Application",
  dimensions: "Dimensions", description: "Description", project: "Project", material: "Material",
};

export function CloneChanges({ rows, projectName }: { rows: ChangeRow[]; projectName?: (id: string) => string }) {
  const changed = rows.filter((r) => r.changed).length;
  return (
    <div className="table-scroll">
      <p className="small">{changed === 0 ? "No changes yet: the clone matches the original." : `${changed} field${changed === 1 ? "" : "s"} changed.`}</p>
      <table className="table compare-table" aria-label="Original versus clone">
        <thead><tr><th>Field</th><th>Original</th><th>Clone</th><th /></tr></thead>
        <tbody>
          {rows.map((r) => {
            const show = (x: string) => (FIELD_NAME[r.field] === "Project" && projectName ? projectName(x) : x) || "—";
            return (
              <tr key={r.field} className={r.changed ? "is-changed" : ""}>
                <td>{FIELD_NAME[r.field] ?? r.field}</td>
                <td>{show(r.original)}</td>
                <td>{show(r.clone)}</td>
                <td>{r.changed ? <Badge tone="warning">Changed</Badge> : <span className="muted small">Same</span>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** Lineage card on a clone: source part, source passport/revision, comparison, material change and source CAD references. */
export function CloneLineageCard({ part }: { part: Part }) {
  const source = useApi<Part>(part.source_part ? `/parts/${part.source_part}/` : null);
  const files = useApi<Paginated<EngineeringFile>>(part.source_part ? "/files/" : null, { query: { part: part.source_part ?? "", page_size: 100 } });
  const snap = (part.source_snapshot ?? {}) as Record<string, string>;
  const cad = (files.data?.results ?? []).filter((f) => f.kind === "step" || f.kind === "dwg" || f.category === "drawing" || f.category === "3d_model");
  const projectName = (id: string) => (id && id === snap.project ? snap.project_name || id : id === part.project ? part.project_name ?? id : id);
  return (
    <Card title="Clone of an existing part">
      <dl className="facts" aria-label="Clone lineage">
        <dt>Cloned from</dt>
        <dd>
          {source.data ? <Link to={`/parts/${part.source_part}`}>{part.source_part_number} · {source.data.name}</Link>
            : <span>{part.source_part_number}{source.error ? " (not visible to your role or project)" : ""}</span>}
        </dd>
        <dt>Source passport</dt>
        <dd>{part.source_passport_number ? `${part.source_passport_number}${part.source_revision_number ? ` · revision ${part.source_revision_number}` : ""} (reference only; not copied, not approved for this clone)` : "None"}</dd>
        <dt>Original material</dt><dd>{snap.original_material || "—"}</dd>
        <dt>Proposed material</dt><dd>{part.proposed_material ? <strong>{part.proposed_material}</strong> : "Unchanged"}</dd>
        {part.material_change_reason && <><dt>Reason for change</dt><dd className="review-note">{part.material_change_reason}</dd></>}
        {part.client_remarks && <><dt>Client remarks</dt><dd className="review-note">{part.client_remarks}</dd></>}
      </dl>
      {part.proposed_material && part.review_state !== "declined" && (
        <p className="notice notice-warning small">The proposed material has not been assessed for suitability. Aries Engineering assesses it in the
          engineering workflow; the clone is not manufacturing-eligible.</p>
      )}
      <h4>Original versus clone</h4>
      <CloneChanges rows={(part.clone_changes ?? []) as ChangeRow[]} projectName={projectName} />
      <h4>Source CAD and drawings (references)</h4>
      {files.loading && !files.data ? <p className="muted small">Loading source files…</p> : cad.length === 0 ? <p className="muted small">{files.error ? "Source files are not visible to your role or project." : "No CAD or drawings on the original part."}</p> : (
        <ul className="ref-list" aria-label="Source CAD references">
          {cad.map((f) => (
            <li key={f.id}>
              <Badge>{(f.kind ?? "").toUpperCase()}</Badge> {f.title} <span className="muted small">v{f.latest_version?.version_number} · stays with {part.source_part_number}</span>{" "}
              <Link className="small" to={`/parts/${part.source_part}`}>Open on original part</Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

/** Clones made from this part. */
export function ClonesList({ part }: { part: Part }) {
  const clones = useApi<Paginated<Part>>("/parts/", { query: { source_part: part.id, page_size: 50 } });
  const rows = clones.data?.results ?? [];
  if (!rows.length) return null;
  return (
    <Card title={`Clones of this part (${rows.length})`}>
      <ul className="ref-list" aria-label="Clones of this part">
        {rows.map((c) => (
          <li key={c.id}>
            <Link to={`/parts/${c.id}`}><strong>{c.part_number}</strong></Link> {c.name}
            {c.proposed_material && <span className="muted small"> · material {c.proposed_material}</span>}{" "}
            <ReviewStateText state={c.review_state} />
          </li>
        ))}
      </ul>
    </Card>
  );
}

const ACTION_LABEL: Record<string, string> = {
  submitted: "Submitted", cloned: "Clone requested", info_requested: "Corrections requested", resubmitted: "Resubmitted",
  accepted: "Accepted for engineering work", declined: "Rejected", verified: "Values verified",
};

function ReviewStateText({ state }: { state: string }) {
  const label: Record<string, string> = { pending_review: "Pending Aries review", info_requested: "Corrections requested", accepted: "Accepted", declined: "Rejected" };
  return label[state] ? <Badge tone={state === "accepted" ? "success" : state === "declined" ? "danger" : "warning"}>{label[state]}</Badge> : null;
}

/** Review history and comments of a client submission or clone. */
export function ReviewHistory({ part }: { part: Part }) {
  const history = useApi<PartReviewEvent[]>(`/parts/${part.id}/history/`, { query: { v: part.updated_at } });
  const rows = history.data ?? [];
  if (!rows.length) return null;
  return (
    <div className="review-history">
      <h4>Review history</h4>
      <ol className="review-timeline" aria-label="Review history">
        {rows.map((e) => (
          <li key={e.id} className={`side-${e.side}`}>
            <strong>{ACTION_LABEL[e.action] ?? e.action}</strong> <span className="muted small">{e.side === "aries" ? "Aries" : "Client"} · {e.author} · {formatDate(e.created_at)}</span>
            {e.note && <div className="review-note">{e.note}</div>}
          </li>
        ))}
      </ol>
    </div>
  );
}
