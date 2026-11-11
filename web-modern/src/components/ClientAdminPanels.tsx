/**
 * Aries Admin panels for one client organisation (CN-002): audited company details, assigning Aries engineers, and
 * each engineer's access scope (whole company or selected scanning projects). All checks are enforced server-side.
 */
import type { Client, Member, Paginated } from "@passport/api-types";
import { useMemo, useState, type FormEvent } from "react";

import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { CompanyProfileFields, PROFILE_FIELDS, type CompanyProfile, type ProfileKey } from "./CompanyProfileFields";
import { assignableRoles, fourRoles, roleLabel, roleOptionLabel } from "./roles";
import { StaffPicker, type StaffOption } from "./StaffPicker";
import { Badge, Card, Empty, ErrorNotice, Field, Loading, formatDate } from "./ui";

interface StaffRow {
  membership_id: string;
  email: string;
  name: string;
  role: string;
  is_active: boolean;
  scope: "company" | "projects";
  edit_reviewer?: boolean;
  qa_permitted?: boolean;
  engineering_authoring?: boolean;
  projects: { id: string; code: string; name: string }[];
}

interface ProfileState {
  values: CompanyProfile;
  missing: ProfileKey[];
  complete: boolean;
}

interface ContactState {
  state: string;
  email: string;
  email_verified: boolean;
  label: string;
  verified_at: string | null;
}

interface ClientDetails {
  name: string;
  slug: string;
  status: string;
  hosting_model: string;
  region_code: string;
  origin: "self_registration" | "aries_admin";
  profile: ProfileState;
  contact: ContactState;
  created_at: string;
  registration: null | Record<string, string | null>;
  people: { email: string; role: string; is_active: boolean }[];
  aries_staff: StaffRow[];
  counts: { projects: number; parts: number; passports: number };
}

interface ProjectRow {
  id: string;
  code: string;
  name: string;
  status: string;
}

function AccessEditor({ client, row, projects, onSaved }: { client: Client; row: StaffRow; projects: ProjectRow[]; onSaved: () => void }) {
  const [scope, setScope] = useState(row.scope);
  const [chosen, setChosen] = useState<string[]>(row.projects.map((p) => p.id));
  const { session } = useAuth();
  const four = fourRoles(session);
  const [reviewer, setReviewer] = useState(!!row.edit_reviewer);
  const [qa, setQa] = useState(!!row.qa_permitted);
  const [authoring, setAuthoring] = useState(row.engineering_authoring !== false);
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  async function save(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSaved(false);
    try {
      await api(`/clients/${client.id}/engineers/${row.membership_id}/access/`, {
        method: "PUT", body: { scope, project_ids: scope === "projects" ? chosen : [],
          ...(row.role === "operator_engineer" ? { edit_reviewer: reviewer, ...(four ? { qa_permitted: qa, engineering_authoring: authoring } : {}) } : {}) },
      });
      setSaved(true);
      onSaved();
    } catch (err) {
      setError(err);
    }
  }
  return (
    <form className="access-editor" onSubmit={save} aria-label={`Access of ${row.email}`}>
      <ErrorNotice error={error} />
      <div className="radio-row">
        <label><input type="radio" name={`scope-${row.membership_id}`} checked={scope === "company"} onChange={() => setScope("company")} /> All projects of the company</label>
        <label><input type="radio" name={`scope-${row.membership_id}`} checked={scope === "projects"} onChange={() => setScope("projects")} /> Selected projects only</label>
      </div>
      {scope === "projects" && (
        projects.length ? (
          <fieldset className="project-picks">
            <legend className="small muted">Projects this engineer may work on</legend>
            {projects.map((p) => (
              <label key={p.id}>
                <input type="checkbox" checked={chosen.includes(p.id)}
                  onChange={(e) => setChosen(e.target.checked ? [...chosen, p.id] : chosen.filter((x) => x !== p.id))} />
                {p.code} · {p.name}
              </label>
            ))}
          </fieldset>
        ) : <p className="muted small">This company has no projects yet. Create them on the Projects tab, then choose them here.</p>
      )}
      {row.role === "operator_engineer" && four && (
        <fieldset className="member-permissions">
          <legend className="small muted">Permissions in this company</legend>
          <label className="inline-check" title="Engineering work: parts, passport drafts, engineering files, intelligence, job-sheet drafts, imports. Independent of QA.">
            <input type="checkbox" checked={authoring} onChange={(e) => setAuthoring(e.target.checked)} aria-label={`${row.email}: can do engineering work`} /> Can do engineering work
          </label>
          <label className="inline-check" title="Confirm or reject photo-origin claims of other engineers, within this engineer's project scope. Never their own claim or upload.">
            <input type="checkbox" checked={qa} onChange={(e) => setQa(e.target.checked)} aria-label={`${row.email}: can perform QA`} /> Can perform QA
          </label>
          <label className="inline-check" title="Decide edit requests in this company (CN-006, provisional), never the engineer's own request. Not passport approval or manufacturing release (OQ-35).">
            <input type="checkbox" checked={reviewer} onChange={(e) => setReviewer(e.target.checked)} aria-label={`${row.email}: can review engineering`} /> Can review engineering (edit requests)
          </label>
        </fieldset>
      )}
      {row.role === "operator_engineer" && !four && (
        <label className="inline-check" title="Provisional authority for the access-test workflow (CN-006). Not engineering verification, passport approval or manufacturing release (OQ-35).">
          <input type="checkbox" checked={reviewer} onChange={(e) => setReviewer(e.target.checked)} /> Authorised edit reviewer (provisional, CN-006)
        </label>
      )}
      <button className="btn btn-small btn-primary">Save access</button>
      {saved && <span className="small muted" role="status"> Saved.</span>}
    </form>
  );
}

/** Company profile with missing fields marked, the contact's real activation state, and administrative editing. */
function CompanyProfileCard({ client, d, onSaved }: { client: Client; d: ClientDetails; onSaved: (msg: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<CompanyProfile>(d.profile.values);
  const [error, setError] = useState<unknown>(null);
  async function save(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const changed = Object.fromEntries(PROFILE_FIELDS.filter((f) => draft[f.key] !== d.profile.values[f.key]).map((f) => [f.key, draft[f.key]]));
    try {
      if (Object.keys(changed).length) await api(`/clients/${client.id}/profile/`, { method: "PATCH", body: changed });
      setEditing(false);
      onSaved(Object.keys(changed).length ? `Company profile of ${client.name} updated.` : "No changes.");
    } catch (err) {
      setError(err);
    }
  }
  const verified = d.contact.email_verified;
  return (
    <section aria-label="Company profile">
      <h3>Company profile {d.profile.complete ? <Badge tone="success">Complete</Badge>
        : <Badge tone="warning">Incomplete: {d.profile.missing.length} missing</Badge>}</h3>
      {editing ? (
        <form className="form-grid" onSubmit={save} aria-label="Edit company profile">
          <ErrorNotice error={error} />
          <CompanyProfileFields value={draft} onChange={setDraft} />
          <p className="muted small span-2">Changing the contact email here does not change user accounts or invitations.</p>
          <div className="form-actions span-2">
            <button type="button" className="btn btn-ghost" onClick={() => { setEditing(false); setDraft(d.profile.values); }}>Cancel</button>
            <button className="btn btn-primary">Save profile</button>
          </div>
        </form>
      ) : (
        <>
          <dl className="facts" data-testid="company-profile">
            {PROFILE_FIELDS.map((f) => (
              <div key={f.key} className="fact-row"><dt>{f.label}</dt>
                <dd>{d.profile.values[f.key] || (f.required ? <Badge tone="warning">Missing</Badge> : <span className="muted">—</span>)}</dd></div>
            ))}
            <div className="fact-row"><dt>Contact access</dt>
              <dd data-testid="contact-status"><Badge tone={verified ? "success" : "warning"}>{verified ? "Email verified" : "Not verified"}</Badge> {d.contact.label}
                {d.contact.verified_at && <span className="muted small"> · {formatDate(d.contact.verified_at)}</span>}</dd></div>
          </dl>
          <button type="button" className="btn btn-small" onClick={() => { setDraft(d.profile.values); setEditing(true); }}>Edit company profile</button>
        </>
      )}
    </section>
  );
}

function AssignStaff({ client, assigned, onDone }: { client: Client; assigned: Set<string>; onDone: (msg: string) => void }) {
  const { session } = useAuth();
  const roles = assignableRoles(session, "operator_in_client");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("operator_engineer");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  // Aries staff accounts (members of the Aries organisation), for the picker
  const staff = useApi<Paginated<Member>>("/users/", { query: { page_size: 200 } });
  const options: StaffOption[] = useMemo(() => (staff.data?.results ?? [])
    .filter((m) => m.is_active !== false)
    .map((m) => ({ email: m.email, name: [m.first_name, m.last_name].filter(Boolean).join(" "), role: m.role })), [staff.data]);
  const roleName = roleOptionLabel(role);
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!email) {
      setError(new Error(`Choose a ${roleName} from the list.`));
      return;
    }
    setError(null);
    setBusy(true);
    try {
      await api(`/clients/${client.id}/members/`, { body: { email, role } });
      setEmail("");
      onDone(`${email} assigned to ${client.name} as ${roleLabel(role)}, with no project access yet: choose the projects under Access.`);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="form-grid single" onSubmit={submit} aria-label="Assign Aries engineer">
      <ErrorNotice error={error ?? staff.error} />
      <Field label="Role in this company">
        <select value={role} onChange={(e) => { setRole(e.target.value); setEmail(""); }}>
          {roles.map((r) => <option key={r} value={r}>{roleOptionLabel(r)}</option>)}
        </select>
      </Field>
      <Field label="Aries staff" hint={`Click to list every ${roleName}, or type part of a name or email. Accounts are created on the Users page.`
        + (roles.length === 1 ? " QA is a permission given after assignment." : "")}>
        <StaffPicker options={options} role={role} value={email} onChange={setEmail} assigned={assigned} loading={staff.loading} roleName={roleName} />
      </Field>
      <p className="muted small">New Aries staff start with access to <strong>no projects</strong>. Then give them specific projects (or, as an
        exception, all projects) in the list on the left. Engineering review is also limited to the projects given.</p>
      <div className="form-actions"><button className="btn btn-primary" disabled={!email || busy} aria-busy={busy}>Assign to {client.name}</button></div>
    </form>
  );
}

type Loaded<T> = { data: T | null; loading: boolean; error: unknown; reload: () => Promise<unknown> | void };

/** One audited details request per page visit, shared by the Overview, Engineers & Access and Projects tabs. */
export function useClientDetails(clientId: string) {
  return useApi<ClientDetails>(`/clients/${clientId}/details/`);
}

/** Overview: company information, profile and the existing project/part/passport counts. */
export function ClientOverview({ client, details, onChanged }: { client: Client; details: Loaded<ClientDetails>; onChanged: (msg: string) => void }) {
  const d = details.data;
  if (details.error) return <ErrorNotice error={details.error} />;
  if (details.loading || !d) return <Loading />;
  return (
    <div className="grid-2">
      <Card title="Company">
        <p className="muted small">Viewing these details is recorded in the audit trail of Aries and of the client. Part, passport and document
          content is not shown here.</p>
        <dl className="facts">
          <div className="fact-row"><dt>Status</dt><dd><Badge tone={d.status === "active" ? "success" : "warning"}>{d.status}</Badge></dd></div>
          <div className="fact-row"><dt>Short identifier</dt><dd>{d.slug}</dd></div>
          <div className="fact-row"><dt>Hosting</dt><dd>{d.hosting_model === "dedicated" ? "Dedicated Azure deployment" : "Shared Azure platform"}{d.region_code ? ` · ${d.region_code}` : ""}</dd></div>
          <div className="fact-row"><dt>Origin</dt><dd>{d.origin === "self_registration" ? "Self-registration, verified and approved" : "Created by Aries Admin"}</dd></div>
          <div className="fact-row"><dt>Created</dt><dd>{formatDate(d.created_at)}</dd></div>
          {d.registration && (
            <div className="fact-row"><dt>Registration</dt><dd>Submitted by {d.registration.email}; approved {formatDate(d.registration.approved_at)} by {d.registration.approved_by}</dd></div>
          )}
        </dl>
        <div className="stat-row" data-testid="client-counts">
          <div className="stat"><strong>{d.counts.projects}</strong><span className="muted small">Projects</span></div>
          <div className="stat"><strong>{d.counts.parts}</strong><span className="muted small">Parts</span></div>
          <div className="stat"><strong>{d.counts.passports}</strong><span className="muted small">Passports</span></div>
          <div className="stat"><strong>{d.people.filter((x) => x.is_active).length}</strong><span className="muted small">Active client users</span></div>
          <div className="stat"><strong>{d.aries_staff.filter((x) => x.is_active).length}</strong><span className="muted small">Aries staff</span></div>
        </div>
      </Card>
      <Card>
        <CompanyProfileCard key={JSON.stringify(d.profile.values)} client={client} d={d} onSaved={(msg) => { void details.reload(); onChanged(msg); }} />
      </Card>
    </div>
  );
}

/** Engineers & Access: existing company-wide / project-specific scope controls, edit-reviewer flag and staff assignment. */
export function ClientEngineers({ client, details, onChanged }: { client: Client; details: Loaded<ClientDetails>; onChanged: (msg: string) => void }) {
  const projects = useApi<ProjectRow[]>(`/clients/${client.id}/projects/`);
  const four = fourRoles(useAuth().session);
  const d = details.data;
  if (details.error) return <ErrorNotice error={details.error} />;
  return (
    <div className="grid-2 wide-left">
      <Card title="Aries engineers and project access">
        {details.loading || !d ? <Loading /> : d.aries_staff.length === 0 ? (
          <Empty>No Aries staff assigned to {client.name} yet. Assign an Aries Engineer with the form on the right.</Empty>
        ) : d.aries_staff.map((row) => (
          <div key={row.membership_id} className="staff-row" data-testid={`staff-${row.email}`}>
            <div>
              <strong>{row.name || row.email}</strong> <span className="muted small">{row.email}</span> · {roleOptionLabel(row.role)}{" "}
              {!row.is_active && <Badge>inactive</Badge>}{" "}
              <Badge tone={row.scope === "projects" && !row.projects.length ? "warning" : "info"}>{row.scope === "company" ? "All projects (company-wide)"
                : row.projects.length ? `Projects: ${row.projects.map((p) => p.code).join(", ")}` : "No projects yet"}</Badge>
              {row.qa_permitted && <> <Badge tone="info">QA</Badge></>}
              {four && row.role === "operator_engineer" && row.engineering_authoring === false && <> <Badge>No engineering work</Badge></>}
              {row.edit_reviewer && <> <Badge tone="warning">{four ? "Engineering review (provisional)" : "Edit reviewer (provisional)"}</Badge></>}
            </div>
            {row.is_active && (
              <AccessEditor key={`${row.scope}-${row.projects.map((p) => p.id).join()}-${row.edit_reviewer}-${row.qa_permitted}-${row.engineering_authoring}`} client={client} row={row} projects={projects.data ?? []}
                onSaved={() => { void details.reload(); onChanged(`Access of ${row.email} updated.`); }} />
            )}
          </div>
        ))}
      </Card>
      <Card title="Assign Aries staff">
        <AssignStaff client={client} assigned={new Set((d?.aries_staff ?? []).filter((r) => r.is_active).map((r) => r.email.toLowerCase()))}
          onDone={(msg) => { void details.reload(); onChanged(msg); }} />
      </Card>
    </div>
  );
}

/** Aries Admin: create a project directly in the client company; engineers are then assigned to it under Engineers & Access. */
function NewClientProject({ client, onCreated }: { client: Client; onCreated: (msg: string) => void }) {
  const [form, setForm] = useState({ code: "", name: "", description: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const p = await api<ProjectRow>(`/clients/${client.id}/projects/`, { body: form });
      setForm({ code: "", name: "", description: "" });
      onCreated(`Project ${p.code} created in ${client.name}. Assign Aries Engineers to it under Engineers & Access.`);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card title="New project">
      <form className="form-grid" onSubmit={submit} aria-label={`New project for ${client.name}`}>
        <ErrorNotice error={error} />
        <Field label="Project code" hint="Unique in this company; it identifies the project and cannot be changed later.">
          <input required maxLength={40} value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} /></Field>
        <Field label="Project name"><input required maxLength={200} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
        <Field label="Description"><textarea rows={2} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
        <div className="form-actions"><button className="btn btn-primary" disabled={busy} aria-busy={busy}>{busy ? "Creating…" : "Create project"}</button></div>
      </form>
    </Card>
  );
}

/** Projects: the client's projects, which Aries staff may work on each (from the existing scope data), and project creation. */
export function ClientProjects({ client, details }: { client: Client; details: Loaded<ClientDetails> }) {
  const projects = useApi<ProjectRow[]>(`/clients/${client.id}/projects/`);
  const staff = (details.data?.aries_staff ?? []).filter((s) => s.is_active);
  const [message, setMessage] = useState("");
  const create = <NewClientProject client={client} onCreated={(msg) => { setMessage(msg); void projects.reload(); }} />;
  const notice = message ? <div className="notice notice-success" role="status">{message}</div> : null;
  if (projects.error) return <ErrorNotice error={projects.error} />;
  if (projects.loading && !projects.data) return <Loading />;
  if (!projects.data?.length) {
    return (
      <div className="grid-2 wide-left">
        <Card>{notice}<Empty>{client.name} has no projects yet. Create the first project here, then assign Aries Engineers to it under
          Engineers &amp; Access.</Empty></Card>
        {create}
      </div>
    );
  }
  return (
    <div className="grid-2 wide-left">
    <Card>
      {notice}
      <div className="table-scroll">
        <table className="table" aria-label={`Projects of ${client.name}`}>
          <thead><tr><th>Code</th><th>Name</th><th>Status</th><th>Aries staff with access</th></tr></thead>
          <tbody>
            {projects.data.map((p) => {
              const access = staff.filter((s) => s.scope === "company" || s.projects.some((x) => x.id === p.id));
              return (
                <tr key={p.id}>
                  <td><strong>{p.code}</strong></td>
                  <td>{p.name}</td>
                  <td><Badge>{p.status}</Badge></td>
                  <td className="small">{details.loading && !details.data ? "…" : access.length
                    ? access.map((s) => `${s.name || s.email}${s.scope === "company" ? " (all projects)" : ""}`).join(", ")
                    : <span className="muted">No Aries staff</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="muted small">Project scope is changed under Engineers &amp; Access. Part, passport and document content is not shown here.</p>
    </Card>
    {create}
    </div>
  );
}
