/**
 * Public invitation acceptance (W2 security item B). The page never says whether the address already has an
 * account: the invitee enters their existing password, or chooses one if they are new.
 */
import type { InvitationInfo } from "@passport/api-types";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/client";
import { ErrorNotice, Field, Loading, label } from "../components/ui";
import { PasswordInput } from "../components/PasswordInput";
import { MarineHero } from "../components/MarineHero";

export default function AcceptInvitationPage() {
  const { token } = useParams();
  const [info, setInfo] = useState<InvitationInfo | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [form, setForm] = useState({ first_name: "", last_name: "", password: "", confirm: "" });
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<InvitationInfo>(`/invitation-acceptance/${token}/`).then(setInfo).catch(setLoadError);
  }, [token]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (form.password !== form.confirm) return setError(new Error("The passwords do not match."));
    setBusy(true);
    try {
      const r = await api<{ organisation: string }>(`/invitation-acceptance/${token}/`, {
        body: { first_name: form.first_name, last_name: form.last_name, password: form.password },
      });
      setDone(r.organisation);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-page">
      <MarineHero />
      <div className="login-card">
        <div className="brand brand-lg">
          <span className="brand-mark" aria-hidden>DP</span>
          <div>
            <h1>Accept invitation</h1>
            <p className="muted">Digital Passport Platform</p>
          </div>
        </div>
        {loadError ? (
          <ErrorNotice error={loadError} />
        ) : !info ? (
          <Loading />
        ) : done ? (
          <>
            <div className="notice notice-success" role="status">You have joined {done}.</div>
            <Link className="btn btn-primary btn-block" to="/login">Sign in</Link>
          </>
        ) : (
          <form onSubmit={submit} className="stack" aria-label="Accept invitation">
            <p>
              You are invited to join <strong>{info.organisation}</strong> as <strong>{label(info.role)}</strong> with the address <strong>{info.email}</strong>.
            </p>
            <ErrorNotice error={error} />
            <Field label="First name"><input value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} /></Field>
            <Field label="Last name"><input value={form.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} /></Field>
            <Field label="Password" hint="If you already have an account with this address, enter its password. Otherwise choose a new password (at least 12 characters).">
              <PasswordInput autoComplete="current-password" required value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
            </Field>
            <Field label="Confirm password">
              <PasswordInput autoComplete="current-password" required value={form.confirm} onChange={(e) => setForm({ ...form, confirm: e.target.value })} />
            </Field>
            <button className="btn btn-primary btn-block" disabled={busy} aria-busy={busy}>{busy ? "Joining…" : "Accept invitation"}</button>
          </form>
        )}
      </div>
    </div>
  );
}
