import type { Paginated, Part, Passport, Project } from "@passport/api-types";
import { useState } from "react";
import { useDecision } from "../components/decision";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { DataLevel, DocChips, Thumbnail } from "../components/catalog";
import EditRequestDialog from "../components/EditRequestDialog";
import FilesPanel from "../components/FilesPanel";
import { EditRequestList } from "./EditRequestsPage";
import PartForm from "../components/PartForm";
import { CostComparisonPanel } from "../components/CostComparison";
import { FeasibilityPanel } from "../components/ManufacturingFeasibility";
import { PartIntelligencePanel } from "../components/PartIntelligence";
import { RecommendationPanel } from "../components/Recommendation";
import { CloneLineageCard, ClonesList, ReviewHistory } from "../components/PartLineage";
import { isOpenReview, Provenance, REVIEW_LABEL, ResubmitForm, ReviewBadge, ReviewPanel, SubmissionForm } from "../components/PartSubmission";
import { canClone, CloneEditForm } from "./PartClonePage";
import { BackLink, Badge, Card, DisabledAction, ErrorNotice, Loading, Notice, PageHeader, formatDate, label } from "../components/ui";

export default function PartDetailPage() {
  const { id } = useParams();
  const [search] = useSearchParams();
  const { can, session } = useAuth();
  const oq = useDecision();
  const navigate = useNavigate();
  const part = useApi<Part>(`/parts/${id}/`);
  const projects = useApi<Paginated<Project>>(can("parts.manage") ? "/projects/" : null, { query: { page_size: 200 } });
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [saved, setSaved] = useState(false);
  const [requesting, setRequesting] = useState(false);

  async function createPassport() {
    setBusy(true);
    setError(null);
    try {
      const p = await api<Passport>("/passports/", { body: { part: id } });
      navigate(`/passports/${p.id}`);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  if (part.loading && !part.data) return <Loading />;
  if (part.error || !part.data) return <ErrorNotice error={part.error ?? new Error("Not found")} />;
  const p = part.data;
  const submission = p.origin === "client";
  const open = isOpenReview(p);
  // Clients change only their organisation's own open submissions (the Client Administrator any, others their own).
  const clientMayEdit = can("parts.submit") && submission && open
    && (session?.membership.role === "client_admin" || p.submitted_by === session?.user.id);
  const mayEdit = can("parts.manage") || clientMayEdit;
  const blocked = submission && (open || p.review_state === "declined");
  const row = (name: string, field: string, value: string | null | undefined) => (
    <>
      <dt>{name}</dt>
      <dd>{value || "—"} {submission && <Provenance part={p} field={field} />}</dd>
    </>
  );

  return (
    <>
      <BackLink to="/parts">Digital inventory</BackLink>
      <PageHeader
        title={`${p.part_number} · ${p.name}`}
        subtitle={<><Badge>{p.status}</Badge> <ReviewBadge part={p} /> <span className="muted small">Last activity {formatDate(p.last_activity)}</span></>}
        actions={<div className="toolbar">{can("edits.request") && <button type="button" className="btn" onClick={() => setRequesting(true)}>Request edit</button>}{canClone(p, can) && <Link className="btn" to={`/parts/${p.id}/clone`}>Clone part</Link>}{
          p.passport_id ? (
            <Link className="btn btn-primary" to={`/passports/${p.passport_id}`}>Open digital passport</Link>
          ) : can("passports.edit_draft") ? (
            blocked ? <DisabledAction label="Create passport draft" reason={p.review_state === "declined" ? "This submission was declined." : "Accept the client submission first."} />
              : <button className="btn btn-primary" onClick={createPassport} disabled={busy}>Create passport draft</button>
          ) : null
        }</div>}
      />
      <ErrorNotice error={error} />
      {search.get("cloned") && open && (
        <Notice kind="success"><span role="status">Clone created and sent for Aries review. The original part {p.source_part_number} is unchanged.</span></Notice>
      )}
      {search.get("submitted") && open && (
        <Notice kind="success"><span role="status">Submitted. Aries Engineering has been notified and will review it.</span></Notice>
      )}
      {saved && <Notice kind="success"><span role="status">Part master data saved.</span></Notice>}
      {submission && (
        <Card title="Client submission">
          <dl className="facts" aria-label="Submission status">
            <dt>Status</dt><dd><ReviewBadge part={p} /> {p.review_state === "accepted" && <span className="muted small">Accepted into the engineering workflow. Not engineering-approved, published or manufacturing-eligible{oq("OQ-35")}.</span>}</dd>
            <dt>Type</dt><dd>{p.submission_kind === "clone" ? "Clone of an existing part" : p.submission_kind === "record" ? "Company record (Client Administrator)" : "New-part proposal"}</dd>
            <dt>Submitted</dt><dd>{p.submitted_by_name || "—"} · {formatDate(p.submitted_at)}</dd>
            {p.reviewed_at && <><dt>Aries review</dt><dd>{REVIEW_LABEL[p.review_state] ?? label(p.review_state)} by {p.reviewed_by_name} · {formatDate(p.reviewed_at)}</dd></>}
            {p.review_note && <><dt>{p.review_state === "info_requested" ? "Aries asks" : "Aries note"}</dt><dd className="review-note">{p.review_note}</dd></>}
          </dl>
          <ReviewHistory part={p} />
          {can("parts.review") && <ReviewPanel part={p} onChange={(next) => part.setData(next)} />}
          {clientMayEdit && p.review_state === "info_requested" && (
            <ResubmitForm part={p} onChange={(next) => part.setData(next)} />
          )}
        </Card>
      )}
      {p.source_part && <CloneLineageCard part={p} />}
      <div className="grid-2 wide-left">
        <Card
          title="Part master data"
          actions={mayEdit && <button type="button" className="btn btn-small" onClick={() => { setEditing((v) => !v); setSaved(false); }}>{editing ? "Cancel" : "Edit"}</button>}
        >
          {editing && clientMayEdit && p.submission_kind === "clone" ? (
            <CloneEditForm part={p} onDone={(next) => { part.setData(next); setEditing(false); setSaved(true); }} />
          ) : editing && clientMayEdit ? (
            <SubmissionForm part={p} isAdmin={session?.membership.role === "client_admin"} onDone={(next) => { part.setData(next); setEditing(false); setSaved(true); }} />
          ) : editing ? (
            <PartForm
              initial={p}
              projects={projects.data?.results ?? []}
              submitLabel="Save changes"
              onSubmit={async (values) => {
                part.setData(await api<Part>(`/parts/${p.id}/`, { method: "PATCH", body: values }));
                setEditing(false);
                setSaved(true);
              }}
            />
          ) : (
            <div className="part-facts">
              <Thumbnail thumb={p.thumbnail} alt={p.part_number} size={120} />
              <dl className="facts">
                {row("Part number", "part_number", p.part_number)}
                {row("Part name", "name", p.name)}
                {row("Equipment / machinery", "equipment_reference", p.equipment_reference)}
                {row("Manufacturer / OEM", "manufacturer", p.manufacturer)}
                <dt>Category</dt><dd>{p.category === "unknown" ? "Not classified" : label(p.category ?? "")}</dd>
                <dt>Criticality</dt><dd>{label(p.criticality ?? "")}</dd>
                <dt>Project</dt><dd>{p.project ? <Link to={`/parts?project=${p.project}`}>{p.project_name}</Link> : "—"} {submission && <Provenance part={p} field="project" />}</dd>
                {row("Original material", "original_material", p.original_material)}
                {row("Dimensions", "dimensions", p.dimensions)}
                {row("Application", "application", p.application)}
                {row("Description", "description", p.description)}
              </dl>
            </div>
          )}
        </Card>
        <Card title="Digital passport">
          {p.passport_id ? (
            <dl className="facts" aria-label="Passport summary">
              <dt>Passport</dt><dd><Link to={`/passports/${p.passport_id}`}>{p.passport_number}</Link></dd>
              <dt>Current revision</dt><dd>{p.revision ? `rev ${p.revision.number} (${p.revision.status})` : "—"}</dd>
              <dt>Publication</dt><dd>{label(p.publication_state ?? "")}</dd>
              <dt>Evidence level</dt><dd>{p.evidence_level === "none" ? `Not assessed${oq("OQ-35")}` : p.evidence_level}</dd>
              <dt>Data captured</dt><dd><DataLevel level={p.data_captured} /></dd>
              <dt>Documents</dt><dd><DocChips documents={p.documents} has3d={p.has_3d} /></dd>
            </dl>
          ) : blocked ? (
            <p className="muted">No digital passport. One can be created after Aries Engineering accepts this submission.</p>
          ) : (
            <p className="muted">No digital passport yet.{can("passports.edit_draft") ? " Create a draft to start capturing passport data." : ""}</p>
          )}
        </Card>
      </div>
      <InventoryDataCard part={p} />
      {can("intelligence.view") && p.import_record && Object.keys(p.import_record).length > 0 && <PartIntelligencePanel partId={p.id} onClassified={() => part.reload()} />}
      {can("intelligence.view") && p.import_record && Object.keys(p.import_record).length > 0 && <FeasibilityPanel partId={p.id} />}
      {can("intelligence.view") && p.import_record && Object.keys(p.import_record).length > 0 && <CostComparisonPanel partId={p.id} />}
      {can("intelligence.view") && p.import_record && Object.keys(p.import_record).length > 0 && <RecommendationPanel partId={p.id} />}
      <ClonesList part={p} />
      {(can("edits.request") || can("edits.review")) && (
        <Card title="Edit requests"><EditRequestList query={{ part: p.id }} empty="No edit requests for this part." /></Card>
      )}
      {requesting && <EditRequestDialog partId={p.id} title={`${p.part_number} · ${p.name}`} onClose={() => setRequesting(false)} />}
      <FilesPanel partId={p.id} passportId={p.passport_id ?? undefined}
        supportingUpload={can("files.upload_supporting") || clientMayEdit} />
    </>
  );
}

/** CN-007: customer inventory identifiers and the import that supplied them, kept apart from engineering specifications. */
function InventoryDataCard({ part: p }: { part: Part }) {
  const rec = (p.import_record ?? {}) as { reference?: string; row?: number; imported_at?: string; imported_by?: string };
  const any = rec.reference || p.plant || p.functional_location || p.equipment_tag || p.customer_abc_class || p.manufacturer_reference || p.oem_part_number;
  if (!any) return null;
  const v = (x?: string | null) => x || <span className="muted">Not recorded</span>;
  return (
    <Card title="Customer inventory data">
      {rec.reference && <p><Badge tone="warning">Imported inventory record · not engineering-verified</Badge>{" "}
        <span className="muted small">From import {rec.reference}, row {rec.row}, {formatDate(rec.imported_at ?? null)} by {rec.imported_by}.</span></p>}
      <dl className="facts inventory-ids" data-testid="inventory-data">
        <dt>Plant</dt><dd>{v(p.plant)}</dd>
        <dt>Functional location</dt><dd>{v(p.functional_location)}</dd>
        <dt>Equipment tag</dt><dd>{v(p.equipment_tag)}</dd>
        <dt>Customer ABC indicator</dt><dd>{v(p.customer_abc_class)} <span className="muted">(as supplied; meaning not confirmed; not criticality)</span></dd>
        <dt>Manufacturer (as supplied)</dt><dd>{p.manufacturer ? <span className="mono">{JSON.stringify(p.manufacturer)}</span> : v("")}{p.manufacturer_normalized && p.manufacturer_normalized !== p.manufacturer ? <span className="muted"> · cleaned: {p.manufacturer_normalized}</span> : null}</dd>
        <dt>Manufacturer reference</dt><dd>{v(p.manufacturer_reference)} <span className="muted">(customer code; not an OEM part number)</span></dd>
        <dt>OEM part number</dt><dd>{v(p.oem_part_number)}</dd>
        <dt>Classification</dt><dd>{p.category === "unknown" ? "Not classified" : label(p.category ?? "")} · criticality {p.criticality === "unknown" ? "not assessed" : label(p.criticality ?? "")}</dd>
      </dl>
    </Card>
  );
}

