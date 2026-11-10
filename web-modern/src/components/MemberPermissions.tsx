/**
 * Four-role model permission editors (AccessTest/FOUR-ROLE-MODEL.md). Every change is checked and audited server-side:
 * Client User features by the company's Client Admin or the Aries Admin; Aries Engineer permissions by the Aries Admin only;
 * nobody edits their own.
 */
import type { Member } from "@passport/api-types";
import { useState } from "react";

import { api } from "../api/client";

type Patch = Partial<Pick<Member, "part_submission_allowed" | "technical_access" | "procurement_access" | "audit_access" |
  "document_access" | "qa_permitted" | "contract_reviewer" | "engineering_authoring">>;

const FEATURES: { key: "part_submission_allowed" | "technical_access" | "procurement_access" | "audit_access"; label: string; hint: string }[] = [
  { key: "part_submission_allowed", label: "Submit and clone spare parts", hint: "Part submissions, clones and edit requests, always Pending Aries review" },
  { key: "technical_access", label: "Technical submissions", hint: "Supporting documents and photos, engineering notes, manufacturing and scanning requests, AI analysis requests" },
  { key: "procurement_access", label: "Procurement", hint: "Manufacturing and scanning requests, AI price comparisons and reports" },
  { key: "audit_access", label: "Read-only audit", hint: "The company audit trail and engineering notes, read only" },
];

export function ClientUserFeatures({ member, disabled, onChange }: { member: Member; disabled: boolean; onChange: (patch: Patch) => void }) {
  return (
    <fieldset className="member-permissions" aria-label={`Feature permissions of ${member.email}`}>
      <legend className="small muted">Feature permissions</legend>
      {FEATURES.map((f) => (
        <label key={f.key} className="inline-check small" title={f.hint}>
          <input type="checkbox" disabled={disabled} checked={!!member[f.key]} aria-label={`${member.email}: ${f.label}`}
            onChange={(e) => onChange({ [f.key]: e.target.checked })} /> {f.label}
        </label>
      ))}
      <label className="small member-doc-access">
        Document access{" "}
        <select disabled={disabled} value={member.document_access ?? "preview"} aria-label={`${member.email}: document access`}
          onChange={(e) => onChange({ document_access: e.target.value as Member["document_access"] })}>
          <option value="none">None</option>
          <option value="preview">Previews only</option>
          <option value="full">Full documents</option>
        </select>
      </label>
    </fieldset>
  );
}

/** Aries Engineer in the Aries organisation: engineering work, QA (job-sheet QA review) and contract review, each independent.
 * The same permissions inside a client company are set per assignment (Engineers & Access). */
export function EngineerPermissions({ member, disabled, onChange }: { member: Member; disabled: boolean; onChange: (patch: Patch) => void }) {
  return (
    <fieldset className="member-permissions" aria-label={`Permissions of ${member.email}`}>
      <legend className="small muted">Permissions</legend>
      <label className="inline-check small" title="Engineering work from the Aries organisation, such as drafting job sheets from the intake queue. Off for QA-only engineers.">
        <input type="checkbox" disabled={disabled} checked={member.engineering_authoring !== false} aria-label={`${member.email}: can do engineering work`}
          onChange={(e) => onChange({ engineering_authoring: e.target.checked })} /> Can do engineering work
      </label>
      <label className="inline-check small" title="Job-sheet QA review from the Aries intake queue (stays closed until OQ-36 is decided). QA in a client company is set under Clients → Engineers & Access.">
        <input type="checkbox" disabled={disabled} checked={!!member.qa_permitted} aria-label={`${member.email}: can perform QA`}
          onChange={(e) => onChange({ qa_permitted: e.target.checked })} /> Can perform QA
      </label>
      <label className="inline-check small" title="Verify or end thumbnail contract authorizations recorded by someone else. Objection review still needs the separately designated authority.">
        <input type="checkbox" disabled={disabled} checked={!!member.contract_reviewer} aria-label={`${member.email}: can review contracts`}
          onChange={(e) => onChange({ contract_reviewer: e.target.checked })} /> Can review contracts
      </label>
    </fieldset>
  );
}

export type ProjectAccess = { membership_id: string; scope: "company" | "projects"; explicit: boolean; projects: { id: string; code: string; name: string }[] };

/** Client Administrator: which projects a Client User may see (2 Nov 2026). "All projects" is an explicit grant that also
 * covers projects created later and can be revoked; selected projects can be none. Separate from feature permissions. */
export function ClientUserProjects({ member, access, projects, disabled, onSaved }: {
  member: Member; access: ProjectAccess | undefined; projects: { id: string; code: string; name: string }[]; disabled: boolean;
  onSaved: (a: ProjectAccess, msg: string) => void;
}) {
  const [scope, setScope] = useState<"company" | "projects">(access?.scope ?? "projects");
  const [chosen, setChosen] = useState<string[]>((access?.projects ?? []).map((p) => p.id));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const name = `access-${member.id}`;
  async function save() {
    setBusy(true);
    setError("");
    try {
      const a = await api<ProjectAccess>(`/users/${member.id}/projects/`, { method: "PUT", body: scope === "company" ? { scope } : { scope, project_ids: chosen } });
      onSaved(a, `Project access of ${member.email} saved: ${a.scope === "company" ? "all projects of the company" : a.projects.map((p) => p.code).join(", ") || "no projects"}.`);
    } catch (err) {
      setError((err as { message?: string })?.message ?? "Could not save.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <fieldset className="member-permissions" aria-label={`Project access of ${member.email}`}>
      <legend className="small muted">Project access {access && !access.explicit && "(all projects: access from before project assignment)"}</legend>
      <label className="inline-check small"><input type="radio" name={name} disabled={disabled} checked={scope === "company"} onChange={() => setScope("company")}
        aria-label={`${member.email}: all projects of the company`} /> All projects of the company (also projects created later)</label>
      <label className="inline-check small"><input type="radio" name={name} disabled={disabled} checked={scope === "projects"} onChange={() => setScope("projects")}
        aria-label={`${member.email}: selected projects only`} /> Selected projects only</label>
      {scope === "projects" && (projects.length === 0 ? <span className="muted small">The company has no projects yet.</span> : projects.map((p) => (
        <label key={p.id} className="inline-check small">
          <input type="checkbox" disabled={disabled} checked={chosen.includes(p.id)} aria-label={`${member.email}: project ${p.code}`}
            onChange={(e) => setChosen(e.target.checked ? [...chosen, p.id] : chosen.filter((x) => x !== p.id))} /> {p.code} · {p.name}
        </label>
      )))}
      {!disabled && <button type="button" className="btn btn-small" disabled={busy} onClick={() => void save()}
        aria-label={`Save project access of ${member.email}`}>{busy ? "Saving…" : "Save project access"}</button>}
      {error && <span className="muted small" role="alert">{error}</span>}
    </fieldset>
  );
}
