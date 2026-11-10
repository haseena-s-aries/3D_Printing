/**
 * Catalog quick view (VWR-001: the viewer opens from the catalog). Part facts and stored states, the interactive 3D
 * model of the current STEP version, and previews of the documents the user's role may view (BR-039, VWR-010).
 * Manufacturing requests are not available: eligibility and order rules are not approved (OQ-36).
 */
import type { EngineeringFile, Paginated, Part } from "@passport/api-types";
import { Suspense, lazy, useEffect, useRef, useState } from "react";
import { useDecision } from "./decision";
import { Link } from "react-router-dom";

import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { DataLevel, DocChips, Eligibility, Readiness, Thumbnail } from "./catalog";
import ImagePreview from "./ImagePreview";
import { classification } from "./requests";
import { Badge, ErrorNotice, Loading, label } from "./ui";
import { viewerState } from "./viewerState";

const ModelViewer = lazy(() => import("./ModelViewer"));
const PdfViewer = lazy(() => import("./PdfViewer"));

export default function QuickView({ part, onClose, onRequest, cloneable = false }: { part: Part; onClose: () => void; onRequest?: (p: Part) => void; cloneable?: boolean }) {
  const { can } = useAuth();
  const oq = useDecision();
  const files = useApi<Paginated<EngineeringFile>>("/files/", { query: { part: part.id, page_size: 200 } });
  const [preview, setPreview] = useState<EngineeringFile | null>(null);
  const close = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    close.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const all = files.data?.results ?? [];
  const steps = all.filter((f) => f.kind === "step");
  const model = steps.find((f) => viewerState(f.latest_version).kind === "ready") ?? steps[0];
  const documents = all.filter((f) => f.kind !== "step");
  const canPreview = can("files.download_derivative");
  const revision = part.revision ? `rev ${part.revision.number} (${part.revision.status})` : "no passport";

  return (
    <div className="quickview-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="quickview" role="dialog" aria-modal="true" aria-labelledby="quickview-title">
        <header className="quickview-head">
          <div>
            <h2 id="quickview-title">{part.part_number} · {part.name}</h2>
            <p className="muted small">{[part.project_name, part.passport_number && `${part.passport_number} ${revision}`].filter(Boolean).join(" · ")}</p>
          </div>
          <button ref={close} type="button" className="btn btn-ghost" onClick={onClose} aria-label="Close quick view">Close</button>
        </header>

        <div className="quickview-grid">
          <section aria-label="Part information" className="quickview-facts">
            <Thumbnail thumb={part.thumbnail} alt={part.part_number} fill />
            <div className="chips"><Readiness part={part} /><Eligibility value={part.manufacturing_eligibility} /></div>
            <dl className="facts">
              <dt>Category</dt><dd>{label(part.category ?? "")}{part.criticality === "critical" ? " · critical" : ""}</dd>
              <dt>Material (original)</dt><dd>{part.original_material || "—"}</dd>
              <dt>Dimensions</dt><dd>{part.dimensions || "—"}</dd>
              <dt>Application</dt><dd>{part.application || "—"}</dd>
              <dt>Equipment</dt><dd>{part.equipment_reference || "—"}</dd>
              <dt>Evidence level</dt><dd>{part.evidence_level === "none" || !part.evidence_level ? "Not assessed" : part.evidence_level}</dd>
              <dt>Data captured</dt><dd><DataLevel level={part.data_captured} /></dd>
            </dl>
            <DocChips documents={part.documents} has3d={part.has_3d} />
          </section>

          {/* One media item at a time: the 3D viewer redraws continuously, which would starve a PDF rendered beside it
              on software WebGL and low-end devices, and one large item suits small screens better. */}
          {preview?.latest_version ? (
            <section aria-label="Document preview" className="quickview-model quickview-preview">
              <div className="toolbar">
                <strong className="small">{preview.title}</strong>
                <button type="button" className="btn btn-small" onClick={() => setPreview(null)}>{model ? "Back to 3D model" : "Close preview"}</button>
              </div>
              {preview.kind === "image" ? <ImagePreview file={preview} version={preview.latest_version.version_number} /> : (
                <Suspense fallback={<Loading />}>
                  <PdfViewer fileId={preview.id} version={preview.latest_version.version_number} title={preview.title ?? "Document"} />
                </Suspense>
              )}
            </section>
          ) : (
          <section aria-label="3D model" className="quickview-model">
            {files.loading && !files.data ? <Loading /> : model?.latest_version && canPreview ? (
              <Suspense fallback={<Loading />}>
                <ModelViewer fileId={model.id} version={model.latest_version} revisionLabel={`${revision} · file v${model.latest_version.version_number}`} />
              </Suspense>
            ) : (
              <div className="viewer-empty"><p className="muted">{model ? "Your role cannot view 3D models." : "No 3D model has been uploaded for this part yet."}</p></div>
            )}
          </section>
          )}
        </div>

        <section aria-label="Documents" className="quickview-docs">
          <h3>Documents</h3>
          <ErrorNotice error={files.error} />
          {documents.length === 0 && !files.loading ? <p className="muted small">No documents yet.</p> : (
            <ul className="doc-list">
              {documents.map((f) => (
                <li key={f.id}>
                  <span><strong>{f.title}</strong> <Badge>{f.kind?.toUpperCase()}</Badge> <span className="muted small">{label(f.category ?? "")} · v{f.latest_version?.version_number}</span></span>
                  {f.kind === "dwg" ? <span className="muted small">Download only{oq("OQ-27")}</span>
                    : canPreview && f.latest_version ? (
                      <button type="button" className="btn btn-small" aria-expanded={preview?.id === f.id} onClick={() => setPreview(preview?.id === f.id ? null : f)}>
                        {preview?.id === f.id ? "Close preview" : "Preview"}
                      </button>
                    ) : <span className="muted small">No preview permission</span>}
                </li>
              ))}
            </ul>
          )}
        </section>

        <footer className="quickview-foot">
          <p className="muted small">
            {classification(part).kind === "enquiry"
              ? "Requests for this part are sent as enquiries: it is not yet published and eligible for manufacturing. Nothing shown here authorises manufacture."
              : "Requests for this part are reviewed by our engineering and QA teams before any production."}
          </p>
          <div className="toolbar">
            <Link className="btn" to={`/parts/${part.id}`}>Open part</Link>
            {part.passport_id && <Link className="btn" to={`/passports/${part.passport_id}`}>Open passport</Link>}
            {onRequest && <button type="button" className="btn btn-primary" onClick={() => onRequest(part)}>Request</button>}
            {cloneable && <Link className="btn" to={`/parts/${part.id}/clone`}>Clone part</Link>}
          </div>
        </footer>
      </div>
    </div>
  );
}
