/**
 * Digital passport workspace (W1). Sections follow PSEC-001: product information with readiness levels,
 * interactive 3D model, documents (drawings, specifications, inspection, certificates), revision history and
 * manufacturing history. Approval, publication and manufacturing release stay gated (OQ-35, OQ-36).
 */
import type { EngineeringFile, Paginated, Part, Passport, Revision } from "@passport/api-types";
import { Suspense, lazy, useState, type FormEvent } from "react";
import { useDecision } from "../components/decision";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { useConversionPolling } from "../components/FilesPanel";
import DocumentsTab from "../components/passport/DocumentsTab";
import OverviewTab from "../components/passport/OverviewTab";
import { Progress, RL1Form, RL2Form, RL3Form } from "../components/passport/ReadinessForms";
import RevisionsTab from "../components/passport/RevisionsTab";
import EditRequestDialog from "../components/EditRequestDialog";
import { EditRequestList } from "./EditRequestsPage";
import { BackLink, Badge, Card, DisabledAction, Empty, ErrorNotice, Loading, Notice, PageHeader, label } from "../components/ui";
import { viewerState } from "../components/viewerState";

const ModelViewer = lazy(() => import("../components/ModelViewer"));
const ReportsTab = lazy(() => import("../components/passport/ReportsTab"));

const TABS = [
  ["overview", "Overview"],
  ["readiness", "Readiness data"],
  ["model", "Interactive 3D model"],
  ["documents", "Documents"],
  ["history", "Revision history"],
  ["reports", "Reports"],
  ["manufacturing", "Manufacturing history"],
] as const;
type Tab = (typeof TABS)[number][0];

function SummaryEditor({ passportId, revision, onSaved }: { passportId: string; revision: Revision; onSaved: (r: Revision) => void }) {
  // Starts empty so a new summary replaces the old one instead of being appended to it (review UX-4).
  const [value, setValue] = useState("");
  const [error, setError] = useState<unknown>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!value.trim()) return;
    try {
      onSaved(await api<Revision>(`/passports/${passportId}/revisions/${revision.revision_number}/`, { method: "PATCH", body: { change_summary: value.trim() } }));
      setValue("");
    } catch (err) {
      setError(err);
    }
  }
  return (
    <form className="inline-form" onSubmit={submit} aria-label="Revision summary">
      <ErrorNotice error={error} />
      <label className="small" htmlFor="rev-summary">
        Revision summary: <strong>{revision.change_summary || "—"}</strong>
      </label>
      <input id="rev-summary" placeholder="Replace with a new summary of this revision's changes" value={value} onChange={(e) => setValue(e.target.value)} />
      <button className="btn btn-small" disabled={!value.trim()}>
        Update summary
      </button>
    </form>
  );
}

function ModelTab({ files, selected, onSelect, revisionLabel }: { files: EngineeringFile[]; selected: string | null; onSelect: (id: string) => void; revisionLabel: string }) {
  const steps = files.filter((f) => f.kind === "step");
  if (!steps.length) return <Empty>None uploaded. Upload a STEP file in the Documents tab (section "Interactive 3D model").</Empty>;
  const file = steps.find((f) => f.id === selected) ?? steps.find((f) => viewerState(f.latest_version).kind === "ready") ?? steps[0];
  const v = file.latest_version;
  return (
    <>
      {steps.length > 1 && (
        <label className="inline-form">
          <span className="small">Model</span>
          <select aria-label="Choose 3D model" value={file.id} onChange={(e) => onSelect(e.target.value)}>
            {steps.map((f) => <option key={f.id} value={f.id}>{f.title} (v{f.latest_version?.version_number})</option>)}
          </select>
        </label>
      )}
      <p className="muted small">
        {file.title} · version {v?.version_number} · {v?.original_filename}. Viewer derivative generated from the STEP original; production CAD fidelity on
        real engineering files has not been verified yet.
      </p>
      {v && (
        <Suspense fallback={<Loading />}>
          <ModelViewer fileId={file.id} version={v} revisionLabel={`${revisionLabel} · file v${v.version_number}`} />
        </Suspense>
      )}
    </>
  );
}

export default function PassportDetailPage() {
  const { id } = useParams();
  const { can } = useAuth();
  const oq = useDecision();
  const [params, setParams] = useSearchParams();
  const requestedTab = TABS.some(([t]) => t === params.get("tab")) ? (params.get("tab") as Tab) : null;
  const [level, setLevel] = useState<"rl1" | "rl2" | "rl3">("rl1");
  const [modelFile, setModelFile] = useState<string | null>(null);
  const [requesting, setRequesting] = useState(false);
  const passport = useApi<Passport>(`/passports/${id}/`);
  const revisions = useApi<Revision[]>(`/passports/${id}/revisions/`);
  const partId = passport.data?.part ?? null;
  const part = useApi<Part>(partId ? `/parts/${partId}/` : null);
  const files = useApi<Paginated<EngineeringFile>>(partId ? "/files/" : null, { query: { part: partId, page_size: 200 } });
  const [error, setError] = useState<unknown>(null);
  const converting = useConversionPolling(files.data?.results ?? [], files.reload);

  const go = (t: Tab) => setParams((p) => { p.set("tab", t); return p; }, { replace: true });
  const refresh = (r?: Revision) => {
    if (r && passport.data) passport.setData({ ...passport.data, current_revision: r });
    void revisions.reload();
  };
  async function newRevision() {
    setError(null);
    try {
      await api(`/passports/${id}/revisions/`, { body: { change_summary: "" } });
      await Promise.all([passport.reload(), revisions.reload()]);
    } catch (err) {
      setError(err);
    }
  }

  if (passport.loading && !passport.data) return <Loading />;
  if (passport.error || !passport.data) return <ErrorNotice error={passport.error ?? new Error("Not found")} />;
  const p = passport.data;
  const current = p.current_revision;
  const pub = p.policy?.publication;
  const editable = !!current?.editable && can("passports.edit_draft");
  // Editors land on the data forms; everyone else on the read-only overview
  const tab: Tab = requestedTab ?? (editable ? "readiness" : "overview");
  const allFiles = files.data?.results ?? [];
  const passportFiles = allFiles.filter((f) => f.passport === p.id);
  const revLabel = current ? `rev ${current.revision_number} (${current.status})` : "—";

  return (
    <>
      <BackLink to="/passports">Digital passports</BackLink>
      <PageHeader
        title={`${p.passport_number} · ${p.title}`}
        subtitle={<>Spare part <Link to={`/parts/${p.part}`}>{p.part_summary.part_number}</Link> · {revLabel}</>}
        actions={
          <div className="card-actions">
            {can("edits.request") && current && <button className="btn" onClick={() => setRequesting(true)}>Request edit</button>}
            {can("passports.edit_draft") && current && !current.editable && <button className="btn" onClick={newRevision}>Start new revision</button>}
            {can("passports.edit_draft") && <DisabledAction label="Submit for approval" reason={pub?.reason ?? `Approval rules not yet decided${oq("OQ-35")}.`} />}
            <DisabledAction label="Approve" reason={`Approval is not available yet${oq("OQ-35")}.`} />
          </div>
        }
      />
      <ErrorNotice error={error} />
      {requesting && <EditRequestDialog partId={p.part} passportId={p.id} title={`${p.passport_number} rev ${current?.revision_number}`} onClose={() => setRequesting(false)} />}
      <div className="state-strip">
        <div><span className="muted small">Publication</span><Badge tone="info">{label(p.publication_state)}</Badge></div>
        <div><span className="muted small">Evidence level</span><Badge>{p.evidence_level === "none" ? "Not assessed" : p.evidence_level}</Badge></div>
        <div><span className="muted small">Manufacturing</span><Badge tone="warning">{label(p.manufacturing_eligibility)}</Badge></div>
        <div>
          <span className="muted small">Data captured</span>
          <span>
            <Progress level="R-L1" c={current?.completeness?.rl1} /> <Progress level="R-L2" c={current?.completeness?.rl2} /> <Progress level="R-L3" c={current?.completeness?.rl3} />
          </span>
        </div>
      </div>
      <Notice kind="warning">
        Submission, approval, publication and manufacturing release are not available yet{oq(`${pub?.decision ?? "OQ-35"}; manufacturing OQ-36`)}.
        {editable ? " Drafts can be prepared now." : ""}
      </Notice>

      <div className="tabs" role="tablist" aria-label="Passport sections">
        {TABS.map(([t, name]) => (
          <button key={t} type="button" role="tab" id={`tab-${t}`} aria-selected={tab === t} aria-controls={`panel-${t}`} className={`tab ${tab === t ? "is-active" : ""}`} onClick={() => go(t)}>
            {name}
          </button>
        ))}
      </div>

      {converting && (
        <p className="muted small" aria-live="polite">
          A STEP file is being converted for the 3D view; this page updates automatically.
        </p>
      )}
      <section role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
        {tab === "overview" && current && (
          <OverviewTab passport={p} revision={current} part={part.data} files={allFiles}
            onOpen={(t, fileId) => { if (t === "model" && fileId) setModelFile(fileId); go(t); }} />
        )}
        {tab === "readiness" && current && (
          <Card>
            <dl className="facts compact-facts">
              <dt>Part</dt><dd>{p.part_summary.part_number} · {p.part_summary.name}</dd>
              <dt>Category / criticality</dt><dd>{label(part.data?.category ?? "")} · {label(part.data?.criticality ?? "")}</dd>
              <dt>Original material</dt><dd>{part.data?.original_material || "—"}</dd>
              <dt>Dimensions</dt><dd>{part.data?.dimensions || "—"}</dd>
            </dl>
            {editable && <SummaryEditor passportId={p.id} revision={current} onSaved={refresh} />}
            <div className="subtabs" role="tablist" aria-label="Readiness levels">
              {(["rl1", "rl2", "rl3"] as const).map((l) => (
                <button key={l} type="button" role="tab" aria-selected={level === l} className={`tab ${level === l ? "is-active" : ""}`} onClick={() => setLevel(l)}>
                  {l.toUpperCase().replace("RL", "R-L")} <Progress level="" c={current.completeness?.[l]} />
                </button>
              ))}
            </div>
            {level === "rl1" && <RL1Form key={current.id} passportId={p.id} revision={current} part={part.data} editable={editable} onSaved={refresh} />}
            {level === "rl2" && <RL2Form key={current.id} passportId={p.id} revision={current} editable={editable} onSaved={refresh} files={passportFiles} />}
            {level === "rl3" && (
              <RL3Form key={current.id} passportId={p.id} revision={current} files={passportFiles} editable={editable} onSaved={refresh}
                onOpenFile={(f) => (f.kind === "step" ? (setModelFile(f.id), go("model")) : go("documents"))} />
            )}
          </Card>
        )}
        {tab === "model" && (
          <Card>
            <ModelTab files={allFiles} selected={modelFile} onSelect={setModelFile} revisionLabel={revLabel} />
          </Card>
        )}
        {tab === "documents" && (
          <Card>
            <ErrorNotice error={files.error} />
            <DocumentsTab partId={p.part} passportId={p.id} files={allFiles} loading={files.loading} onChanged={() => void files.reload()}
              onOpen3d={(f) => { setModelFile(f.id); go("model"); }} />
          </Card>
        )}
        {tab === "history" && (
          <>
            <Card>
              <RevisionsTab revisions={revisions.data ?? []} />
            </Card>
            {(can("edits.request") || can("edits.review")) && (
              <Card title="Edit requests"><EditRequestList query={{ passport: p.id }} empty="No edit requests for this passport." /></Card>
            )}
          </>
        )}
        {tab === "reports" && (
          <Card>
            <Suspense fallback={<Loading />}><ReportsTab passportId={p.id} partId={p.part} revisions={revisions.data ?? []} files={allFiles} onFilesChanged={() => void files.reload()} /></Suspense>
          </Card>
        )}
        {tab === "manufacturing" && (
          <Card>
            <Empty>
              None recorded. Production orders, milestones and post-production reports are not part of this release{oq("OQ-36")}.
            </Empty>
          </Card>
        )}
      </section>
    </>
  );
}
