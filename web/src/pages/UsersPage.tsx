import type { Invitation, Member, Paginated } from "@passport/api-types";
import { useState, type FormEvent } from "react";

import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { Badge, Card, Empty, ErrorNotice, Field, Loading, PageHeader, formatDate } from "../components/ui";

const OPERATOR_ROLES = ["operator_admin", "operator_engineer", "operator_qa", "operator_support"];
const CLIENT_ROLES = ["client_admin", "client_engineer", "client_user", "procurement", "auditor"];

/**
 * Organisation administrators invite people by email (W2). The response never reveals whether the address already
 * has an account; the person accepts through the emailed link. The link is shown here only in development.
 */
function InvitePanel({ roles, onChanged }: { roles: string[]; onChanged: () => void }) {
  const invitations = useApi<Paginated<Invitation>>("/invitations/");
  const [form, setForm] = useState({ email: "", role: roles.includes("client_user") ? "client_user" : roles[0] });
  const [error, setError] = useState<unknown>(null);
  const [created, setCreated] = useState<Invitation | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setCreated(null);
    try {
      setCreated(await api<Invitation>("/invitations/", { body: form }));
      setForm({ ...form, email: "" });
      await invitations.reload();
      onChanged();
    } catch (err) {
      setError(err);
    }
  }

  async function revoke(inv: Invitation) {
    setError(null);
    try {
      await api(`/invitations/${inv.id}/revoke/`, { method: "POST" });
      await invitations.reload();
    } catch (err) {
      setError(err);
    }
  }

  return (
    <Card title="Invite user">
      <form className="form-grid" onSubmit={submit} aria-label="Invite user">
        <ErrorNotice error={error} />
        {created && (
          <div className="notice notice-success span-2" role="status">
            Invitation sent to {created.email}. They appear in the member list after accepting.
            {created.invite_url && (
              <div className="small">
                Development only — share this link with the invitee:{" "}
                <input className="mono" readOnly value={created.invite_url} aria-label="Invitation link" onFocus={(e) => e.currentTarget.select()} />
              </div>
            )}
          </div>
        )}
        <Field label="Email">
          <input type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
        </Field>
        <Field label="Role">
          <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
            {roles.map((r) => <option key={r} value={r}>{r.replace(/_/g, " ")}</option>)}
          </select>
        </Field>
        <p className="muted small span-2">
          The invitation link expires after 7 days. Platform operator staff and accounts that belong to another organisation cannot join through an
          invitation; the platform operator adds them.
        </p>
        <div className="form-actions"><button className="btn btn-primary">Send invitation</button></div>
      </form>
      <h3>Invitations</h3>
      {invitations.data?.results.length ? (
        <table className="table table-compact" aria-label="Invitations">
          <thead><tr><th>Email</th><th>Role</th><th>Status</th><th /></tr></thead>
          <tbody>
            {invitations.data.results.map((i) => (
              <tr key={i.id}>
                <td>{i.email}</td>
                <td>{i.role.replace(/_/g, " ")}</td>
                <td>
                  <Badge tone={i.state === "accepted" ? "success" : i.state === "pending" ? "info" : "neutral"}>{i.state}</Badge>
                  <div className="muted small">{i.state === "pending" ? `expires ${formatDate(i.expires_at)}` : formatDate(i.accepted_at ?? i.created_at)}</div>
                </td>
                <td>{i.state === "pending" && <button type="button" className="link-btn small" onClick={() => void revoke(i)}>Withdraw</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : <p className="muted small">No invitations yet.</p>}
    </Card>
  );
}

export default function UsersPage() {
  const { session, can } = useAuth();
  const list = useApi<Paginated<Member>>("/users/");
  const platformAdmin = session?.tenant.kind === "operator" && session.membership.role === "operator_admin";
  const roles = session?.tenant.kind === "operator" ? OPERATOR_ROLES : CLIENT_ROLES;
  const [form, setForm] = useState({ email: "", first_name: "", last_name: "", role: roles[roles.length > 2 ? 1 : 0], password: "" });
  const [error, setError] = useState<unknown>(null);
  const [rowError, setRowError] = useState<unknown>(null);

  async function create(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api("/users/", { body: form });
      setForm({ ...form, email: "", first_name: "", last_name: "", password: "" });
      await list.reload();
    } catch (err) {
      setError(err);
    }
  }

  async function update(m: Member, patch: Partial<Member>) {
    setRowError(null);
    try {
      await api(`/users/${m.id}/`, { method: "PATCH", body: patch });
      await list.reload();
    } catch (err) {
      setRowError(err);
    }
  }

  return (
    <>
      <PageHeader title="Users" subtitle={`People with access to ${session?.tenant.name}`} />
      <div className="grid-2">
        <Card title="Members">
          <ErrorNotice error={list.error ?? rowError} />
          {list.loading ? (
            <Loading />
          ) : list.data?.results.length ? (
            <table className="table">
              <thead>
                <tr>
                  <th>User</th>
                  <th>Role</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {list.data.results.map((m) => (
                  <tr key={m.id}>
                    <td>
                      {m.first_name} {m.last_name}
                      <div className="muted small">{m.email}</div>
                      {m.managed_by === "operator" && session?.tenant.kind === "client" && (
                        <Badge tone="info">Platform operator staff · managed by the operator</Badge>
                      )}
                    </td>
                    <td>
                      {m.can_manage ? (
                        <select aria-label={`Role of ${m.email}`} value={m.role} onChange={(e) => void update(m, { role: e.target.value as Member["role"] })}>
                          {[...new Set([m.role, ...roles])].map((r) => (
                            <option key={r} value={r}>
                              {r.replace(/_/g, " ")}
                            </option>
                          ))}
                        </select>
                      ) : (
                        m.role.replace(/_/g, " ")
                      )}
                    </td>
                    <td>
                      <Badge tone={m.is_active ? "success" : "neutral"}>{m.is_active ? "Active" : "Inactive"}</Badge>{" "}
                      {m.can_manage && (
                        <button type="button" className="link-btn small" onClick={() => void update(m, { is_active: !m.is_active })}>
                          {m.is_active ? "Deactivate" : "Reactivate"}
                        </button>
                      )}
                      <div className="muted small">Since {formatDate(m.created_at)}</div>
                      {m.role === "client_user" && (
                        <label className="inline-check small" title="CN-003: lets this Client User submit and clone spare parts (always Pending Aries review)">
                          <input type="checkbox" disabled={!m.can_manage} checked={!!m.part_submission_allowed}
                            aria-label={`${m.email} may submit and clone spare parts`}
                            onChange={(e) => void update(m, { part_submission_allowed: e.target.checked })} />{" "}
                          May submit and clone spare parts
                        </label>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty>No users.</Empty>
          )}
        </Card>
        {can("users.manage") && !platformAdmin && <InvitePanel roles={roles} onChanged={() => void list.reload()} />}
        {can("users.manage") && platformAdmin && (
          <Card title="Add user">
            <form className="form-grid" onSubmit={create}>
              <ErrorNotice error={error} />
              <Field label="Email">
                <input type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
              </Field>
              <Field label="Role">
                <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                  {roles.map((r) => (
                    <option key={r} value={r}>
                      {r.replace(/_/g, " ")}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="First name">
                <input value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} />
              </Field>
              <Field label="Last name">
                <input value={form.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} />
              </Field>
              <Field label="Initial password" hint="At least 12 characters. Platform administrators add operator staff directly.">
                <input type="password" autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
              </Field>
              <div className="form-actions">
                <button className="btn btn-primary">Add user</button>
              </div>
            </form>
          </Card>
        )}
      </div>
    </>
  );
}
