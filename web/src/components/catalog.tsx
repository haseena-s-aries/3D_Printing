/** Catalog building blocks: authenticated thumbnails, data-captured, readiness and eligibility badges, document chips
 *  and the visual part card. Status labels show stored states only; nothing is inferred or invented. */
import type { Part } from "@passport/api-types";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { fetchObjectUrl } from "../api/client";
import { ReviewBadge } from "./PartSubmission";
import { Badge } from "./ui";

export const DATA_LEVEL_LABEL: Record<string, string> = {
  none: "Data incomplete",
  rl1: "R-L1 data complete",
  rl2: "R-L1–R-L2 data complete",
  rl3: "R-L1–R-L3 data complete",
};

/** Data completeness, shown as guidance. It is not the official evidence level (transitions gated, OQ-35). */
export function DataLevel({ level }: { level: string | null | undefined }) {
  if (!level) return <span className="muted small">No passport</span>;
  return (
    <span className={`progress-pill ${level === "none" ? "" : "is-complete"}`} title="Data completeness only; the evidence level is set separately (OQ-35).">
      {DATA_LEVEL_LABEL[level] ?? level}
    </span>
  );
}

export function DocChips({ documents, has3d }: { documents: Part["documents"]; has3d: boolean }) {
  if (!documents?.total) return <span className="muted small">No documents</span>;
  const chips: [string, number][] = [["STEP", documents.step], ["DWG", documents.dwg], ["PDF", documents.pdf], ["Photo", documents.image]];
  return (
    <span className="chips">
      {has3d && <Badge tone="success">3D view</Badge>}
      {chips.filter(([, n]) => n > 0).map(([label, n]) => (
        <Badge key={label}>
          {label} {n}
        </Badge>
      ))}
    </span>
  );
}

/** Thumbnail loaded with the user's own session (no download link per image); placeholder when there is no photo.
 *  `fill` stretches it to its container (catalog cards). */
export function Thumbnail({ thumb, alt, size = 56, fill = false }: { thumb: Part["thumbnail"]; alt: string; size?: number; fill?: boolean }) {
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!thumb) return;
    let url: string | null = null;
    let cancelled = false;
    fetchObjectUrl(`/files/${thumb.file}/versions/${thumb.version}/thumbnail/`)
      .then((u) => (cancelled ? URL.revokeObjectURL(u) : setSrc((url = u))))
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [thumb?.file, thumb?.version]);
  const style = fill ? undefined : { width: size, height: size };
  const cls = fill ? "thumb thumb-fill" : "thumb";
  if (!thumb || failed) {
    return (
      <span className={`${cls} thumb-empty`} style={style} role="img" aria-label={`${alt}: no photograph`}>
        {fill ? "No image yet" : alt.slice(0, 2).toUpperCase()}
      </span>
    );
  }
  return src ? <img className={cls} style={style} src={src} alt={alt} /> : <span className={`${cls} thumb-loading`} style={style} aria-hidden />;
}

export const ELIGIBILITY_LABEL: Record<string, string> = {
  not_eligible: "Not eligible for manufacturing",
  eligible_subject_to_authorisation: "Eligible, subject to authorisation",
  eligible: "Eligible for manufacturing",
  suspended: "Manufacturing suspended",
};

/** The stored eligibility state (read-only; transitions are gated, OQ-36). Never inferred from data completeness. */
export function Eligibility({ value }: { value: string | null | undefined }) {
  if (!value) return <Badge>No passport</Badge>;
  const tone = value === "eligible" ? "success" : value === "suspended" ? "danger" : value === "eligible_subject_to_authorisation" ? "info" : "neutral";
  return <Badge tone={tone}>{ELIGIBILITY_LABEL[value] ?? value}</Badge>;
}

export const isPublished = (p: Pick<Part, "publication_state">) => p.publication_state === "published";

/** Published (in the client manufacturing catalog) or still in digitisation. Drafts are shown, never hidden, and marked. */
export function Readiness({ part }: { part: Pick<Part, "publication_state" | "passport_id"> }) {
  if (isPublished(part)) return <Badge tone="success">Published</Badge>;
  return <Badge tone="warning">In digitisation · not manufacturing-ready</Badge>;
}

/** Visual catalog card: stored image, identity, readiness, eligibility, data captured and documents. */
export function PartCard({ part, onQuickView, onRequest, cloneable = false }: { part: Part; onQuickView: (p: Part) => void; onRequest?: (p: Part) => void; cloneable?: boolean }) {
  return (
    <article className="part-card" aria-labelledby={`card-${part.id}`} data-testid={`part-card-${part.part_number}`}>
      <button type="button" className="part-card-media" onClick={() => onQuickView(part)} aria-label={`Quick view of ${part.part_number}`}>
        <Thumbnail thumb={part.thumbnail} alt={part.part_number} fill />
      </button>
      <div className="part-card-body">
        <div className="part-card-head">
          <Link id={`card-${part.id}`} to={`/parts/${part.id}`} className="part-card-number">{part.part_number}</Link>
          {part.criticality === "critical" && <Badge tone="danger">Critical</Badge>}
          <ReviewBadge part={part} />
        </div>
        <p className="part-card-name">{part.name}</p>
        <p className="muted small part-card-meta">
          {[part.project_name, part.dimensions].filter(Boolean).join(" · ") || "No project"}
          {part.passport_number ? ` · ${part.passport_number}${part.revision ? ` rev ${part.revision.number}` : ""}` : ""}
        </p>
        <div className="chips">
          <Readiness part={part} />
          <Eligibility value={part.manufacturing_eligibility} />
        </div>
        {part.data_captured && (
          <div className="chips">
            <DataLevel level={part.data_captured} />
          </div>
        )}
        <DocChips documents={part.documents} has3d={part.has_3d} />
      </div>
      <div className="part-card-actions">
        <button type="button" className="btn btn-small" onClick={() => onQuickView(part)}>Quick view</button>
        {onRequest && <button type="button" className="btn btn-small btn-primary" onClick={() => onRequest(part)}>Request</button>}
        {cloneable && <Link className="btn btn-small" to={`/parts/${part.id}/clone`} aria-label={`Clone part ${part.part_number}`}>Clone part</Link>}
        {part.passport_id ? <Link className="btn btn-small btn-ghost" to={`/passports/${part.passport_id}`}>Open passport</Link>
          : <Link className="btn btn-small btn-ghost" to={`/parts/${part.id}`}>Open part</Link>}
      </div>
    </article>
  );
}
