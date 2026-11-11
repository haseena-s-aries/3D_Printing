/** Forgot password (request a single-use, expiring link) and reset password (choose a new one). */
import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/client";
import { BackToSignIn, DevOutboxHint, PublicShell, useRegistrationConfig } from "../components/PublicShell";
import { ErrorNotice, Field, Loading } from "../components/ui";
import { PasswordInput } from "../components/PasswordInput";

export function ForgotPasswordPage() {
  const cfg = useRegistrationConfig();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/public/password-reset/", { body: { email } });
      setSent(true);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <PublicShell title="Forgot password">
      {sent ? (
        <>
          <div className="notice notice-success" role="status" data-testid="reset-sent">
            If an account exists for <strong>{email}</strong>, we have sent a link to choose a new password. It is valid for 60 minutes and
            can be used once.
          </div>
          <DevOutboxHint cfg={cfg} />
        </>
      ) : (
        <form className="form-stack" onSubmit={submit} aria-label="Forgot password">
          <ErrorNotice error={error} />
          <Field label="Email">
            <input type="email" required autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <button className="btn btn-primary btn-block" disabled={busy} aria-busy={busy}>{busy ? "Sending…" : "Send reset link"}</button>
        </form>
      )}
      <BackToSignIn />
    </PublicShell>
  );
}

export function ResetPasswordPage() {
  const { token } = useParams();
  const [email, setEmail] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [form, setForm] = useState({ password: "", password_confirm: "" });
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<{ email: string }>(`/public/password-reset/${token}/`).then((r) => setEmail(r.email)).catch(setLoadError);
  }, [token]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (form.password !== form.password_confirm) return setError(new Error("The passwords do not match."));
    setBusy(true);
    try {
      await api(`/public/password-reset/${token}/`, { body: form });
      setDone(true);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <PublicShell title="Choose a new password">
      {loadError ? (
        <>
          <ErrorNotice error={loadError} />
          <p className="small"><Link to="/forgot-password">Request a new link</Link></p>
        </>
      ) : email === null ? (
        <Loading />
      ) : done ? (
        <>
          <div className="notice notice-success" role="status">Your password was changed and all your sessions were signed out.</div>
          <Link className="btn btn-primary btn-block" to="/login">Sign in</Link>
        </>
      ) : (
        <form className="form-stack" onSubmit={submit} aria-label="Choose a new password">
          <p>Account: <strong>{email}</strong></p>
          <ErrorNotice error={error} />
          <Field label="New password" hint="At least 12 characters; not a common or all-numeric password.">
            <PasswordInput required minLength={12} autoComplete="new-password" value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })} />
          </Field>
          <Field label="Confirm new password">
            <PasswordInput required autoComplete="new-password" value={form.password_confirm}
              onChange={(e) => setForm({ ...form, password_confirm: e.target.value })} />
          </Field>
          <button className="btn btn-primary btn-block" disabled={busy} aria-busy={busy}>{busy ? "Saving…" : "Save new password"}</button>
        </form>
      )}
      <BackToSignIn />
    </PublicShell>
  );
}
