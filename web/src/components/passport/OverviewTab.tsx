/**
 * Read-only passport overview (W2): product information, R-L1/R-L2/R-L3 summaries with completeness, R-L3 evidence
 * links, document availability per PSEC-001 section and 3D status. Completeness is guidance only: it never changes
 * the evidence level, publication state or manufacturing eligibility (OQ-35, OQ-36).
 */
import { useDecision } from "../decision";
import type { EngineeringFile, Part, Passport, Revision } from "@passport/api-types";

import { DataLevel, Thumbnail } from "../catalog";
import { CATEGORIES, conversionBadge } from "../FilesPanel";
import { Badge, label } from "../ui";
import { viewerState } from "../viewerState";
import EngineeringNotesPanel from "./EngineeringNotesPanel";
import { FIELD_LABELS, Progress, RL3_EVIDENCE } from "./ReadinessForms";

const show = (v: unknown): string | null => {
  if (v === null || v === undefined || v === "") return null;
  if (typeof v === "boolean") return v ? "Yes" : "No";
  return label(String(v));
};

function Facts({ rows }: { rows: [string, string | null][] }) {
  const filled = rows.filter(([, v]) => v);
  if (!filled.length) return <p className="muted small">Nothing recorded yet.</p>;
  return (
    <dl className="facts compact-facts">
      {filled.map(([k, v]) => (
        <div key={k} className="fact-row">
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export default function OverviewTab({ passport, revision, part, files, onOpen }: {
  passport: Passport; revision: Revision; part: Part | null; files: EngineeringFile[];
  onOpen: (tab: "readiness" | "model" | "documents", fileId?: string) => void;
}) {
  const oq = useDecision();
  const c = revision.content ?? {};
  const rl1 = c.rl1 ?? {};
  const rl2 = c.rl2 ?? {};
  const spec = rl2.manufacturing_spec ?? {};
  const evidence = c.rl3?.evidence ?? {};
  const na = rl1.not_applicable ?? {};
  const byId = new Map(files.map((f) => [f.id, f]));
  const steps = files.filter((f) => f.kind === "step");
  const ready = steps.find((f) => viewerState(f.latest_version).kind === "ready");

  const rl1Rows: [string, string | null][] = Object.keys(FIELD_LABELS)
    .filter((k) => k in rl1 || k in na)
    .map((k) => [FIELD_LABELS[k], k in na ? `Not applicable — ${na[k]}` : show((rl1 as Record<string, unknown>)[k])]);
  const rl2Rows: [string, string | null][] = [
    [FIELD_LABELS.manufacturing_process, show(rl2.manufacturing_process)],
    [FIELD_LABELS.manufacturing_solution, show(rl2.manufacturing_solution)],
    [FIELD_LABELS.material_selection, [show(rl2.material_selection), show(rl2.material_category)].filter(Boolean).join(" · ") || null],
    [FIELD_LABELS.criticality_amsl, rl2.criticality_amsl ? `${rl2.criticality_amsl} (provisional)` : null],
    [FIELD_LABELS.feedstock, show(rl2.feedstock)],
    [FIELD_LABELS.applicable_standards, show(rl2.applicable_standards)],
    ["Mechanical acceptance", (rl2.mechanical_acceptance ?? []).map((r) => `${label(r.property)} ${r.requirement ?? ""} ${r.unit ?? ""}${r.standard ? ` (${r.standard})` : ""}`.trim()).join("; ") || null],
    [FIELD_LABELS.dimensional_tolerances, show(rl2.dimensional_tolerances)],
    [FIELD_LABELS.ndt, show(rl2.ndt)],
    ["Machine / layer", [show(spec.machine), show(spec.layer_thickness)].filter(Boolean).join(" · ") || null],
    ["Print / post-processing hours", spec.printing_hours != null || spec.post_processing_hours != null ? `${spec.printing_hours ?? "—"} h / ${spec.post_processing_hours ?? "—"} h` : null],
  ];

  return (
    <div className="overview">
      <EngineeringNotesPanel revision={revision} />
      <div className="grid-2 wide-left">
        <section className="card" aria-label="Product information">
          <div className="card-head"><h2>Product information</h2></div>
          <div className="part-facts">
            <Thumbnail thumb={part?.thumbnail ?? null} alt={passport.part_summary.part_number} size={96} />
            <Facts rows={[
              ["Spare part", `${passport.part_summary.part_number} · ${passport.part_summary.name}`],
              ["Category / criticality", part ? `${label(part.category ?? "")} · ${label(part.criticality ?? "")}` : null],
              ["Original material", part?.original_material || null],
              ["Dimensions", part?.dimensions || null],
              ["Application", part?.application || null],
              ["Current revision", `rev ${revision.revision_number} (${revision.status})${revision.change_summary ? ` — ${revision.change_summary}` : ""}`],
            ]} />
          </div>
        </section>
        <section className="card" aria-label="Status">
          <div className="card-head"><h2>Status</h2></div>
          <Facts rows={[
            ["Publication", label(passport.publication_state ?? "")],
            ["Evidence level", passport.evidence_level === "none" ? `Not assessed${oq("OQ-35")}` : passport.evidence_level ?? null],
            ["Manufacturing", label(passport.manufacturing_eligibility ?? "")],
          ]} />
          <p><DataLevel level={passport.data_captured} /></p>
          <p className="muted small">Data completeness is guidance only and does not change the evidence level or eligibility.</p>
        </section>
      </div>

      <div className="grid-3">
        <section className="card" aria-label="R-L1 summary">
          <div className="card-head"><h2>R-L1 identification</h2><Progress level="" c={revision.completeness?.rl1} /></div>
          <Facts rows={rl1Rows} />
        </section>
        <section className="card" aria-label="R-L2 summary">
          <div className="card-head"><h2>R-L2 manufacturing</h2><Progress level="" c={revision.completeness?.rl2} /></div>
          <Facts rows={rl2Rows} />
        </section>
        <section className="card" aria-label="R-L3 summary">
          <div className="card-head"><h2>R-L3 evidence</h2><Progress level="" c={revision.completeness?.rl3} /></div>
          <ul className="list compact-list">
            {RL3_EVIDENCE.map((k) => {
              const f = evidence[k] ? byId.get(evidence[k]!) : undefined;
              return (
                <li key={k} className="row-between">
                  <span>{FIELD_LABELS[k]}</span>
                  {f ? <button type="button" className="link-btn small" onClick={() => onOpen("documents", f.id)}>{f.title}</button> : <span className="muted small">Not linked</span>}
                </li>
              );
            })}
          </ul>
          <p className="muted small">QA verification of evidence is not available yet{oq("OQ-35")}.</p>
        </section>
      </div>

      <div className="grid-2">
        <section className="card" aria-label="Document availability">
          <div className="card-head"><h2>Documents</h2><button type="button" className="btn btn-small" onClick={() => onOpen("documents")}>Open documents</button></div>
          <ul className="list compact-list">
            {CATEGORIES.map(([key, name]) => {
              const n = files.filter((f) => f.category === key).length;
              return (
                <li key={key} className="row-between">
                  <span>{name}</span>
                  {n ? <Badge tone="info">{n} {n === 1 ? "file" : "files"}</Badge> : <span className="muted small">None uploaded</span>}
                </li>
              );
            })}
          </ul>
        </section>
        <section className="card" aria-label="3D model status">
          <div className="card-head"><h2>Interactive 3D model</h2>{ready && <button type="button" className="btn btn-small" onClick={() => onOpen("model", ready.id)}>Open 3D view</button>}</div>
          {steps.length ? (
            <ul className="list compact-list">
              {steps.map((f) => (
                <li key={f.id} className="row-between">
                  <span>{f.title} <span className="muted small">v{f.latest_version?.version_number}</span></span>
                  {f.latest_version && conversionBadge(f.latest_version)}
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">No STEP model uploaded.</p>
          )}
        </section>
      </div>
    </div>
  );
}
