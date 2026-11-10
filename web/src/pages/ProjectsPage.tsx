/** Digitalisation projects (BR-022). Parts can be grouped by project and the catalog filtered by it. */
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
      <PageHeader title="Projects" subtitle="Group spare parts by digitalisation project." />
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
                    <td><Link to={`/parts?project=${p.id}`}>View parts</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <Empty>No projects yet.</Empty>}
        </Card>
        {can("projects.manage") && (
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
