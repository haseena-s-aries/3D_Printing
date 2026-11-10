/**
 * Aries intake: scanning-to-passport handover of a 3D scanning request (post-UAT D-05 / D-15). Link the request to an
 * existing project of the company (or create one from the Actions card), assign the responsible Aries Engineer, record each
 * deliverable (scan data, CAD, drawing, report, photographs; optionally pinned to a file of the created part) and hand the
 * scanned part over to its digital passport. Recording a deliverable states what was produced; it verifies nothing.
 */
import type { OperatorRequest } from "@passport/api-types";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { Badge, Card, ErrorNotice, Notice, formatDate } from "./ui";

type Person = { id: string; name: string; email: string };
type ProjectRef = { id: string; code: string; name: string };
type Deliverable = { kind: string; kind_label: string; title: string; note: string; file: string | null; file_version: number | null;
  file_released: boolean; recorded_at: string };
type Handover = { deliverables: Deliverable[]; handed_over_at: string | null; passport: string | null; passport_number: string | null;
  created_part: string | null; note: string };

const KINDS: [string, string][] = [["scan_data", "Scan source data (mesh / point cloud)"], ["cad_model", "CAD model (STEP)"],
  ["drawing", "Engineering drawing"], ["report", "Scan / inspection report"], ["photos", "Photographs"], ["other", "Other"]];

export default function ScanHandoverPanel({ envelopeId, request: r, sameOrg, onChange }: {
  envelopeId: string; request: OperatorRequest; sameOrg: boolean; onChange: (r: OperatorRequest) => void;
}) {
  const handover = r.handover as Handover | null;
  const responsible = r.responsible as (Person & { assigned_at: string }) | null;
  const candidates = (r.engineer_candidates ?? []) as Person[];
  const projects = (r.company_projects ?? []) as ProjectRef[];
  const partFiles = (r.created_part_files ?? []) as { id: string; title: string; kind: string; client_visible: boolean }[];
  const [engineer, setEngineer] = useState("");
  const [project, setProject] = useState("");
  const [kind, setKind] = useState("scan_data");
  const [title, setTitle] = useState("");
  const [note, setNote] = useState("");
  const [file, setFile] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState("");
  if (r.kind !== "digitisation" || !handover) return null;
  const working = ["scheduled", "in_progress", "completed"].includes(r.status);

  async function act(body: Record<string, unknown>, message: string) {
    setBusy(true);
    setError(null);
    setDone("");
    try {
      onChange(await api<OperatorRequest>(`/operator/requests/${envelopeId}/act/`, { body }));
      setDone(message);
      setTitle("");
      setNote("");
      setFile("");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Scanning to passport handover">
      <ErrorNotice error={error} />
      {done && <Notice kind="success"><span role="status">{done}</span></Notice>}
      <dl className="facts">
        <dt>Project</dt><dd>{r.project_code ?? <span className="muted">Not linked yet</span>}</dd>
        <dt>Responsible engineer</dt><dd>{responsible ? `${responsible.name} · ${formatDate(responsible.assigned_at)}` : <span className="muted">Not assigned</span>}</dd>
        <dt>Handover</dt><dd>{handover.handed_over_at
          ? <><Badge tone="success">Handed over</Badge> {formatDate(handover.handed_over_at)} · passport {handover.passport_number}{" "}
            {sameOrg && handover.passport && <Link to={`/passports/${handover.passport}`}>Open passport</Link>}</>
          : <Badge>Not handed over</Badge>}</dd>
      </dl>
      {!r.project && projects.length > 0 && !handover.handed_over_at && (
        <div className="toolbar wrap">
          <label className="field"><span>Link to an existing project</span>
            <select value={project} onChange={(e) => setProject(e.target.value)}>
              <option value="">Choose a project</option>
              {projects.map((p) => <option key={p.id} value={p.id}>{p.code} · {p.name}</option>)}
            </select></label>
          <button type="button" className="btn" disabled={busy || !project} onClick={() => void act({ action: "link_project", project }, "Request linked to the project.")}>Link project</button>
        </div>
      )}
      {!handover.handed_over_at && (
        <div className="toolbar wrap">
          <label className="field"><span>Responsible Aries Engineer</span>
            <select value={engineer} onChange={(e) => setEngineer(e.target.value)}>
              <option value="">Choose an engineer</option>
              {candidates.map((c) => <option key={c.id} value={c.id}>{c.name} · {c.email}</option>)}
            </select></label>
          <button type="button" className="btn" disabled={busy || !engineer} onClick={() => void act({ action: "assign", engineer }, "Responsible engineer assigned.")}>
            {responsible ? "Reassign" : "Assign"}</button>
        </div>
      )}
      <h3>Deliverables</h3>
      {handover.deliverables.length === 0 ? <p className="muted small">None recorded yet.</p> : (
        <ul className="ref-list">{handover.deliverables.map((d, i) => (
          <li key={i}><strong>{d.title}</strong> · {d.kind_label}{d.file_version ? ` · file v${d.file_version}` : ""}{" "}
            {d.file && (d.file_released ? <Badge tone="success">Released to client</Badge> : <Badge>Aries only</Badge>)}
            <span className="muted small"> · {formatDate(d.recorded_at)}</span>{d.note && <div className="muted small">{d.note}</div>}</li>))}</ul>
      )}
      <p className="muted small">{handover.note}</p>
      {working && !handover.handed_over_at && (
        <div className="form-grid">
          <label className="field"><span>Deliverable</span>
            <select value={kind} onChange={(e) => setKind(e.target.value)}>{KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
          <label className="field"><span>Title</span><input maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} /></label>
          <label className="field"><span>File of the created part (optional)</span>
            <select value={file} onChange={(e) => setFile(e.target.value)}>
              <option value="">{partFiles.length ? "No file pinned" : "No files on the created part yet"}</option>
              {partFiles.map((f) => <option key={f.id} value={f.id}>{f.title} · {f.kind.toUpperCase()}{f.client_visible ? " · released" : " · Aries only"}</option>)}
            </select></label>
          <label className="field"><span>Note (Aries only)</span><input maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} /></label>
          <div className="form-actions">
            <button type="button" className="btn" disabled={busy || !title.trim()}
              onClick={() => void act({ action: "record_deliverable", deliverable_kind: kind, title, note, file: file || null }, "Deliverable recorded.")}>Record deliverable</button>
          </div>
        </div>
      )}
      {r.status === "completed" && !handover.handed_over_at && (
        <div className="stack">
          <p className="small">The handover needs the responsible engineer, at least one deliverable and the digital passport of the part
            created for this request. The passport is then completed through the normal engineering workflow.</p>
          <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void act({ action: "hand_over" }, "Handed over to the digital passport.")}>
            Hand over to the digital passport</button>
        </div>
      )}
    </Card>
  );
}
