/**
 * Digital passport workspace (W1). Sections follow PSEC-001: product information with readiness levels,
 * interactive 3D model, documents (drawings, specifications, inspection, certificates), revision history and
 * manufacturing history. Revisions are submitted for approval and approved or sent back (never by the submitter);
 * publication and manufacturing release stay gated (OQ-36).
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
import { ReadinessSections, RL1Form, RL2Form, RL3Form } from "../components/passport/ReadinessForms";
import { Icon, type IconName } from "../components/icons";
import RevisionsTab from "../components/passport/RevisionsTab";
import EditRequestDialog from "../components/EditRequestDialog";
import { EditRequestList } from "./EditRequestsPage";
import { BackLink, Badge, Breakable, Card, DisabledAction, Empty, ErrorNotice, Loading, label } from "../components/ui";
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
const TAB_NAME = Object.fromEntries(TABS) as Record<Tab, string>;
// Same tabs and URLs (?tab=), shown in three groups so related sections sit together.
const TAB_GROUPS: [string, Tab[]][] = [["Passport", ["overview", "readiness"]], ["Engineering files", ["model", "documents", "reports"]],
  ["History", ["history", "manufacturing"]]];
const TAB_ICON: Record<Tab, IconName> = { overview: "dashboard", readiness: "review", model: "cube", documents: "file", reports: "layers",
  history: "history", manufacturing: "gauge" };
const LEVELS = [["rl1", "R-L1", "Identification and operating context"], ["rl2", "R-L2", "Manufacturing solution and acceptance"],
  ["rl3", "R-L3", "Document evidence"]] as const;

/** A thin completion meter with its count as text (never colour alone). */
function Meter({ done, total }: { done: number; total: number }) {
  const pct = total ? Math.round((done / total) * 100) : 0;
  return <span className="meter-bar" role="img" aria-label={`${done} of ${total}`}><span style={{ width: `${pct}%` }} /></span>;
}

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
  const { can, session } = useAuth();
  const oq = useDecision();
  const [returning, setReturning] = useState(false);
  const [returnNote, setReturnNote] = useState("");
  const [deciding, setDeciding] = useState(false);
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
  async function decide(path: "submit" | "approve" | "return", body: Record<string, string> = {}) {
    if (!passport.data?.current_revision) return;
    setError(null);
    setDeciding(true);
    try {
      await api(`/passports/${id}/revisions/${passport.data.current_revision.revision_number}/${path}/`, { body });
      setReturning(false);
      setReturnNote("");
      await Promise.all([passport.reload(), revisions.reload()]);
    } catch (err) {
      setError(err);
    } finally {
      setDeciding(false);
    }
  }
  async function newRevision() {
    setError(null);
    try {
      await api(`/passports/${id}/revisions/`, { body: { change_summary: "" } });
      await Promise.all([passport.reload(), revisions.reload()]);
    } catch (err) {
      setError(err);
    }
  }

  if (passport.loading && !passport.data) return <Loading variant="page" label="Loading passport…" />;
  if (passport.error || !passport.data) return <ErrorNotice error={passport.error ?? new Error("Not found")} />;
  const p = passport.data;
  const current = p.current_revision;
  const editable = !!current?.editable && can("passports.edit_draft");
  const ownSubmission = !!current?.submitted_by_email && current.submitted_by_email === session?.user.email;
  const canDecide = current?.status === "submitted" && can("passports.approve") && !ownSubmission;
  // Editors land on the data forms; everyone else on the read-only overview
  const tab: Tab = requestedTab ?? (editable ? "readiness" : "overview");
  const allFiles = files.data?.results ?? [];
  const passportFiles = allFiles.filter((f) => f.passport === p.id);
  const revLabel = current ? `rev ${current.revision_number} (${current.status})` : "—";
  const totals = LEVELS.reduce((a, [k]) => ({ done: a.done + (current?.completeness?.[k]?.done ?? 0), total: a.total + (current?.completeness?.[k]?.total ?? 0) }), { done: 0, total: 0 });

  return (
    <>
      <BackLink to="/passports">Digital passports</BackLink>
      <header className="passport-hero">
        <div className="hero-top">
          <div className="hero-identity">
            <p className="hero-eyebrow"><Icon name="passport" size="sm" />Digital passport <span className="hero-number">{p.passport_number}</span></p>
            <h1><Breakable text={p.title ?? ""} /></h1>
            <p className="hero-sub">
              Spare part <Link to={`/parts/${p.part}`}>{p.part_summary.part_number}</Link>
              <span aria-hidden> · </span><span>{revLabel}</span>
            </p>
          </div>
          <div className="hero-actions">
            {can("edits.request") && current && <button className="btn" onClick={() => setRequesting(true)}>Request edit</button>}
            {can("passports.edit_draft") && current && current.status === "approved" && <button className="btn" onClick={newRevision}>Start new revision</button>}
            {can("passports.edit_draft") && current?.status === "draft" && (
              <button className="btn btn-primary" disabled={deciding} onClick={() => void decide("submit")}>Submit for approval</button>
            )}
            {canDecide && (
              <>
                <button className="btn btn-primary" disabled={deciding} onClick={() => void decide("approve")}>Approve</button>
                <button className="btn" disabled={deciding} onClick={() => setReturning(true)}>Send back</button>
              </>
            )}
            {current?.status === "submitted" && !canDecide && (
              <DisabledAction label="Approve" reason={ownSubmission ? "You submitted this revision; another approver decides it." : "Waiting for an Aries Admin, Manager or project engineer to approve."} compact />
            )}
          </div>
        </div>
        <div className="hero-summary">
          <div className="hero-status">
            <span className="hero-label">Publication</span>
            <Badge tone="info">{label(p.publication_state)}</Badge>
          </div>
          <dl className="hero-facts">
            <div><dt>Evidence level</dt><dd>{p.evidence_level === "none" ? "Not assessed" : p.evidence_level}</dd></div>
            <div><dt>Manufacturing</dt><dd>{label(p.manufacturing_eligibility)}</dd></div>
          </dl>
          <div className="hero-progress" aria-label="Data captured" title="Data completeness is guidance only; it does not change the evidence level or eligibility.">
            <span className="hero-label">Data captured</span>
            <ul>
              {LEVELS.map(([k, name]) => {
                const c = current?.completeness?.[k];
                return c ? <li key={k}><span className="hero-level">{name}</span><Meter done={c.done} total={c.total} /><span className="hero-level-count">{c.done}/{c.total}</span></li> : null;
              })}
            </ul>
          </div>
        </div>
        {current?.status === "submitted" && (
          <p className="hero-gate" role="status"><Icon name="clock" size="sm" />
            Rev {current.revision_number} is waiting for approval{current.submitted_by_email ? ` (submitted by ${current.submitted_by_email})` : ""}.</p>
        )}
        {current?.status === "approved" && (
          <p className="hero-gate" role="status"><Icon name="check" size="sm" />
            Rev {current.revision_number} approved{current.approved_by_email ? ` by ${current.approved_by_email}` : ""}. Manufacturing release stays separate{oq("OQ-36")}.</p>
        )}
        {current?.status === "draft" && current.review_note && (
          <p className="hero-gate hero-gate-warn" role="status"><Icon name="alert" size="sm" />Sent back for changes: {current.review_note}</p>
        )}
        {returning && (
          <form className="return-form" onSubmit={(e) => { e.preventDefault(); void decide("return", { note: returnNote }); }} aria-label="Send back for changes">
            <label className="field"><span>What should the author change?</span>
              <textarea rows={3} maxLength={500} required value={returnNote} onChange={(e) => setReturnNote(e.target.value)} /></label>
            <div className="toolbar">
              <button className="btn btn-primary" disabled={deciding || !returnNote.trim()}>Send back</button>
              <button type="button" className="btn btn-ghost" onClick={() => setReturning(false)}>Cancel</button>
            </div>
          </form>
        )}
      </header>
      <ErrorNotice error={error} />
      {requesting && <EditRequestDialog partId={p.part} passportId={p.id} title={`${p.passport_number} rev ${current?.revision_number}`} onClose={() => setRequesting(false)} />}

      <nav className="ptabs" aria-label="Passport">
        <div className="ptabs-list" role="tablist" aria-label="Passport sections">
          {TAB_GROUPS.map(([group, tabs]) => (
            <div key={group} className="ptab-group" role="presentation">
              <span className="ptab-group-label" aria-hidden>{group}</span>
              <div className="ptab-row" role="presentation">
                {tabs.map((t) => (
                  <button key={t} type="button" role="tab" id={`tab-${t}`} aria-selected={tab === t} aria-controls={`panel-${t}`}
                    tabIndex={tab === t ? 0 : -1} className={`ptab ${tab === t ? "is-active" : ""}`} onClick={() => go(t)}>
                    <Icon name={TAB_ICON[t]} size="sm" />
                    {TAB_NAME[t]}
                    {t === "readiness" && totals.total > 0 && <span className="ptab-count" aria-hidden>{totals.done}/{totals.total}</span>}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      </nav>

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
          <ReadinessSections>
            <div className="readiness-levels" role="tablist" aria-label="Readiness levels">
              {LEVELS.map(([l, name, title]) => {
                const c = current.completeness?.[l];
                const missing = c ? c.total - c.done : 0;
                return (
                  <button key={l} type="button" role="tab" aria-selected={level === l} className={`level-card ${level === l ? "is-active" : ""}`} onClick={() => setLevel(l)}>
                    <span className="level-head"><span className="level-name">{name}</span>
                      {c && <span className={`level-state ${missing ? "is-missing" : "is-complete"}`}>{missing ? `${missing} missing` : "Complete"}</span>}</span>
                    <span className="level-title">{title}</span>
                    {c && <><Meter done={c.done} total={c.total} /><span className="level-count">{c.done} of {c.total} required captured</span></>}
                  </button>
                );
              })}
            </div>
            <Card>
              <div className="readiness-context">
                <p className="muted small">
                  {p.part_summary.part_number} · {p.part_summary.name} · {label(part.data?.category ?? "")} · {label(part.data?.criticality ?? "")}
                  {part.data?.original_material ? ` · ${part.data.original_material}` : ""}{part.data?.dimensions ? ` · ${part.data.dimensions}` : ""}
                </p>
                {editable && <SummaryEditor passportId={p.id} revision={current} onSaved={refresh} />}
              </div>
              {level === "rl1" && <RL1Form key={current.id} passportId={p.id} revision={current} part={part.data} editable={editable} onSaved={refresh} />}
              {level === "rl2" && <RL2Form key={current.id} passportId={p.id} revision={current} editable={editable} onSaved={refresh} files={passportFiles} />}
              {level === "rl3" && (
                <RL3Form key={current.id} passportId={p.id} revision={current} files={passportFiles} editable={editable} onSaved={refresh}
                  onOpenFile={(f) => (f.kind === "step" ? (setModelFile(f.id), go("model")) : go("documents"))} />
              )}
            </Card>
          </ReadinessSections>
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
