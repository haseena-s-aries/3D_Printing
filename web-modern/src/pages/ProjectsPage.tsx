/** Digitalisation projects (BR-022). Parts can be grouped by project and the catalog filtered by it. Authorised users create
 * projects and edit their name, description and status (post-UAT D-21); the project code is the stable identifier and is kept. */
import type { Paginated, Project } from "@passport/api-types";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { Badge, Card, Empty, ErrorNotice, Field, Loading, Notice, PageHeader, formatDate } from "../components/ui";

export default function ProjectsPage() {
  const { can } = useAuth();
  const list = useApi<Paginated<Project>>("/projects/", { query: { page_size: 200 } });
  const [form, setForm] = useState({ code: "", name: "", description: "" });
  const [error, setError] = useState<unknown>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [editing, setEditing] = useState<Project | null>(null);
  const [edit, setEdit] = useState({ name: "", description: "", status: "active" });

  function startEdit(p: Project) {
    setEditing(p);
    setEdit({ name: p.name, description: p.description ?? "", status: p.status ?? "active" });
    setError(null);
    setMessage(null);
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!editing) return;
    setError(null);
    try {
      const p = await api<Project>(`/projects/${editing.id}/`, { method: "PATCH", body: edit });
      setMessage(`Project ${p.code} updated.`);
      setEditing(null);
      await list.reload();
    } catch (err) {
      setError(err);
    }
  }

  async function create(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const p = await api<Project>("/projects/", { body: form });
      setMessage(`Project ${p.code} created.`);
      setForm({ code: "", name: "", description: "" });
      await list.reload();
    } catch (err) {
      setError(err);
    }
  }

  return (
    <>
      <PageHeader marine title="Projects" subtitle="Group spare parts by digitalisation project." />
      {message && <Notice kind="success"><span role="status">{message}</span></Notice>}
      <div className={can("projects.manage") ? "grid-2 wide-left" : ""}>
        <Card title="Projects">
          <ErrorNotice error={list.error} />
          {list.loading && !list.data ? <Loading /> : list.data?.results.length ? (
            <table className="table">
              <thead><tr><th>Project</th><th>Status</th><th>Created</th><th /></tr></thead>
              <tbody>
                {list.data.results.map((p) => (
                  <tr key={p.id}>
                    <td><strong>{p.code}</strong> · {p.name}<div className="muted small">{p.description}</div></td>
                    <td><Badge>{p.status}</Badge></td>
                    <td className="small">{formatDate(p.created_at)}</td>
                    <td className="actions"><Link to={`/parts?project=${p.id}`}>View parts</Link>
                      {can("projects.manage") && <button type="button" className="btn btn-small btn-ghost" aria-label={`Edit project ${p.code}`}
                        onClick={() => startEdit(p)}>Edit</button>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <Empty>No projects yet.</Empty>}
        </Card>
        {can("projects.manage") && editing && (
          <Card title={`Edit project ${editing.code}`}>
            <form className="form-grid" onSubmit={save} aria-label={`Edit project ${editing.code}`}>
              <ErrorNotice error={error} />
              <Field label="Code" hint="The project code is the stable identifier and cannot be changed."><input value={editing.code} disabled /></Field>
              <Field label="Project name"><input required value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></Field>
              <Field label="Description"><textarea rows={3} value={edit.description} onChange={(e) => setEdit({ ...edit, description: e.target.value })} /></Field>
              <Field label="Status">
                <select value={edit.status} onChange={(e) => setEdit({ ...edit, status: e.target.value })}>
                  <option value="active">Active</option><option value="on_hold">On hold</option><option value="closed">Closed</option>
                </select>
              </Field>
              <div className="form-actions">
                <button className="btn btn-primary">Save changes</button>
                <button type="button" className="btn" onClick={() => setEditing(null)}>Cancel</button>
              </div>
            </form>
          </Card>
        )}
        {can("projects.manage") && !editing && (
          <Card title="New project">
            <form className="form-grid" onSubmit={create}>
              <ErrorNotice error={error} />
              <Field label="Code"><input required value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} /></Field>
              <Field label="Project name"><input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
              <Field label="Description"><textarea rows={2} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
              <div className="form-actions"><button className="btn btn-primary">Create project</button></div>
            </form>
          </Card>
        )}
      </div>
    </>
  );
}
