/** Email verification for a company registration: the emailed single-use link plus the password chosen at registration. */
import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/client";
import { BackToSignIn, PublicShell } from "../components/PublicShell";
import { ErrorNotice, Field, Loading } from "../components/ui";

export default function VerifyEmailPage() {
  const { token } = useParams();
  const [info, setInfo] = useState<{ company_name: string; email: string } | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<{ company_name: string; email: string }>(`/public/registrations/verify/${token}/`).then(setInfo).catch(setLoadError);
  }, [token]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api(`/public/registrations/verify/${token}/`, { body: { password } });
      setDone(true);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <PublicShell title={done ? "Registration pending approval" : "Verify your email"}>
      {loadError ? (
        <>
          <ErrorNotice error={loadError} />
          <p className="small">Register again or use “Send the link again” on the registration page to get a new link.</p>
          <BackToSignIn />
        </>
      ) : !info ? (
        <Loading />
      ) : done ? (
        <>
          <div className="notice notice-success" role="status" data-testid="registration-pending">
            Thank you. <strong>{info.email}</strong> is verified. The registration of <strong>{info.company_name}</strong> is now waiting for
            Aries approval. You will receive an email when it is decided.
          </div>
          <p className="small">You can sign in at any time to see the status.</p>
          <Link className="btn btn-primary btn-block" to="/login">Go to sign in</Link>
        </>
      ) : (
        <form onSubmit={submit} aria-label="Verify your email">
          <p>Registration of <strong>{info.company_name}</strong> for <strong>{info.email}</strong>.</p>
          <ErrorNotice error={error} />
          <Field label="Password chosen at registration">
            <input type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </Field>
          <button className="btn btn-primary btn-block" disabled={busy}>{busy ? "Verifying…" : "Verify email address"}</button>
          <p className="muted small">The password confirms that the person who registered is the owner of this mailbox.</p>
        </form>
      )}
    </PublicShell>
  );
}
