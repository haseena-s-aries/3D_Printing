/**
 * Members of one client organisation, managed by the Aries Admin: role changes, activation/deactivation and Add member.
 * Moved unchanged from the Clients page; every rule is enforced server-side (membership policy).
 */
import type { Client, Member } from "@passport/api-types";
import { useState, type FormEvent } from "react";

import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { roleLabel } from "./roles";
import { Badge, Empty, ErrorNotice, Field, Loading, Notice } from "./ui";

export const CLIENT_ROLES = ["client_admin", "client_engineer", "client_user", "procurement", "auditor"];
// Operator roles usable inside a client organisation; operator administration stays in the operator organisation.
export const OPERATOR_ASSIGNABLE = ["operator_engineer", "operator_qa", "operator_support"];

/** Drop empty optional fields so the API can tell "not given" from a value (operator staff need no password). */
export function compactBody<T extends Record<string, string>>(form: T): Partial<T> {
  return Object.fromEntries(Object.entries(form).filter(([, v]) => v !== "")) as Partial<T>;
}

function AddMember({ client, onDone }: { client: Client; onDone: (message: string) => void }) {
  const [form, setForm] = useState({ email: "", first_name: "", last_name: "", role: "client_admin", password: "" });
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const operatorRole = form.role.startsWith("operator_");
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api(`/clients/${client.id}/members/`, { body: compactBody(form) });
      setForm({ email: "", first_name: "", last_name: "", role: "client_admin", password: "" });
      onDone(`${form.email} added as ${roleLabel(form.role)}.`);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="form-grid" onSubmit={submit} aria-label="Add member">
      <ErrorNotice error={error} />
      <Field label="Email">
        <input type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
      </Field>
      <Field label="Role">
        <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
          {[...CLIENT_ROLES, ...OPERATOR_ASSIGNABLE].map((r) => (
            <option key={r} value={r}>
              {roleLabel(r)}
            </option>
          ))}
        </select>
      </Field>
      {operatorRole ? (
        <p className="muted small span-2">Aries roles assign existing Aries staff; no name or password is needed.</p>
      ) : (
        <>
          <Field label="First name">
            <input value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} />
          </Field>
          <Field label="Last name">
            <input value={form.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} />
          </Field>
          <Field label="Initial password" hint="Required for new users (12+ characters); leave empty for existing users.">
            <input type="password" autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
          </Field>
        </>
      )}
      <div className="form-actions">
        <button className="btn btn-primary" disabled={busy}>
          Add member
        </button>
      </div>
    </form>
  );
}

/** Operator administrators manage memberships in client organisations, including operator staff assignments. */
export default function ClientUsers({ client, onChanged }: { client: Client; onChanged?: () => void }) {
  const { can } = useAuth();
  const importAdmin = can("inventory.import_admin"); // CN-007: only an Aries Admin allows a Client Administrator to import
  const members = useApi<Member[]>(`/clients/${client.id}/members/`);
  const [error, setError] = useState<unknown>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function updateMember(m: Member, patch: { role?: string; is_active?: boolean; inventory_import_allowed?: boolean }) {
    setError(null);
    setMessage(null);
    try {
      await api(`/clients/${client.id}/members/${m.id}/`, { method: "PATCH", body: patch });
      setMessage(`${m.email} updated.`);
      await members.reload();
      onChanged?.();
    } catch (err) {
      setError(err);
    }
  }

  return (
    <>
      {message && <Notice kind="success"><span role="status">{message}</span></Notice>}
      <ErrorNotice error={error ?? members.error} />
      {members.loading && !members.data ? <Loading /> : members.data?.length ? (
        <div className="table-scroll">
          <table className="table" aria-label={`Members of ${client.name}`}>
            <thead>
              <tr>
                <th>Email</th>
                <th>Role</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {members.data.map((m) => {
                const family = m.role.startsWith("operator_") ? OPERATOR_ASSIGNABLE : CLIENT_ROLES;
                return (
                  <tr key={m.id}>
                    <td>
                      {m.email}
                      {m.managed_by === "operator" && <div className="muted small">Aries staff assignment</div>}
                    </td>
                    <td>
                      {m.can_manage ? (
                        <select aria-label={`Role of ${m.email}`} value={m.role} onChange={(e) => void updateMember(m, { role: e.target.value })}>
                          {[...new Set([m.role, ...family])].map((r) => <option key={r} value={r}>{roleLabel(r)}</option>)}
                        </select>
                      ) : (
                        roleLabel(m.role)
                      )}
                    </td>
                    <td>
                      <Badge tone={m.is_active ? "success" : "neutral"}>{m.is_active ? "Active" : "Inactive"}</Badge>{" "}
                      {m.can_manage && (
                        <button type="button" className="link-btn small" onClick={() => void updateMember(m, { is_active: !m.is_active })}>
                          {m.is_active ? "Deactivate" : "Reactivate"}
                        </button>
                      )}
                      {importAdmin && m.role === "client_admin" && (
                        <label className="inline-check small"><input type="checkbox" checked={!!m.inventory_import_allowed}
                          onChange={(e) => void updateMember(m, { inventory_import_allowed: e.target.checked })} /> May import inventory</label>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : members.data ? (
        <Empty>No members yet. Add the first Client Administrator below, or invite the primary contact when creating the company.</Empty>
      ) : null}
      <h3>Add member</h3>
      <AddMember
        client={client}
        onDone={(msg) => {
          setMessage(msg);
          void members.reload();
          onChanged?.();
        }}
      />
    </>
  );
}
