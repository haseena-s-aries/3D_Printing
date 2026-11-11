import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";

import { ApiError } from "../api/client";
import { postLoginTarget, useAuth } from "../auth/AuthContext";
import { ThemeToggle } from "../components/theme";
import { ErrorNotice, Field, formatDate } from "../components/ui";
import { PasswordInput } from "../components/PasswordInput";

interface TenantChoice {
  slug: string;
  name: string;
}

export default function LoginPage() {
  const { session, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [tenants, setTenants] = useState<TenantChoice[] | null>(null);
  const [tenant, setTenant] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [registration, setRegistration] = useState<{ status: "pending" | "rejected"; company: string; at?: string; message?: string } | null>(null);

  if (session) return <Navigate to={postLoginTarget(location.state, session.user.id)} replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const s = await login(email, password, tenant || undefined);
      navigate(postLoginTarget(location.state, s.user.id), { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.code === "tenant_selection_required") {
        setTenants((err.details.tenants as TenantChoice[]) ?? []);
      } else if (err instanceof ApiError && (err.code === "registration_pending" || err.code === "registration_rejected")) {
        setRegistration({ status: err.code === "registration_pending" ? "pending" : "rejected", company: String(err.details.company_name ?? ""),
                          at: err.details.submitted_at as string | undefined, message: String(err.details.message ?? "") });
      } else {
        setError(err);
      }
    } finally {
      setBusy(false);
    }
  }

  if (registration) {
    return (
      <div className="login-page">
      <ThemeToggle className="public-theme" />
        <div className="login-card" data-testid={`registration-${registration.status}`}>
          <div className="brand brand-lg">
            <span className="brand-mark" aria-hidden>DP</span>
            <div>
              <h1>{registration.status === "pending" ? "Registration pending approval" : "Registration not approved"}</h1>
              <p className="muted">{registration.company}</p>
            </div>
          </div>
          {registration.status === "pending" ? (
            <div className="notice notice-info" role="status">
              Your email address is verified{registration.at ? ` (${formatDate(registration.at)})` : ""}. Aries is reviewing the registration of{" "}
              <strong>{registration.company}</strong>. You will receive an email when it is approved; then sign in again to open your
              organisation's workspace.
            </div>
          ) : (
            <div className="notice notice-warning" role="status">
              The registration of <strong>{registration.company}</strong> was not approved.
              {registration.message && <div><strong>Message from Aries:</strong> {registration.message}</div>}
              <div className="small">Please contact Aries if you have questions.</div>
            </div>
          )}
          <button type="button" className="btn btn-block" onClick={() => setRegistration(null)}>Back to sign in</button>
        </div>
      </div>
    );
  }

  return (
    <div className="login-page">
      <ThemeToggle className="public-theme" />
      <form className="login-card" onSubmit={submit} aria-labelledby="login-title">
        <div className="brand brand-lg">
          <span className="brand-mark" aria-hidden>
            DP
          </span>
          <div>
            <h1 id="login-title">Digital Passport Platform</h1>
            <p className="muted">Spare-part digital passports and inventory</p>
          </div>
        </div>
        <ErrorNotice error={error} />
        <Field label="Email">
          <input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label="Password">
          <PasswordInput autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        {tenants && (
          <Field label="Organisation" hint="Your account has access to more than one organisation.">
            <select required value={tenant} onChange={(e) => setTenant(e.target.value)}>
              <option value="">Select an organisation…</option>
              {tenants.map((t) => (
                <option key={t.slug} value={t.slug}>
                  {t.name}
                </option>
              ))}
            </select>
          </Field>
        )}
        <button className="btn btn-primary btn-block" type="submit" disabled={busy} aria-busy={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
        <p className="center small"><Link to="/forgot-password">Forgot password?</Link></p>
        <div className="login-register">
          <span className="muted small">New client company?</span> <Link to="/register" className="btn btn-small">Register your company</Link>
        </div>
        <div className="login-register">
          <span className="muted small">Aries Engineer, QA or Support?</span> <Link to="/register/staff" className="btn btn-small">Request an account</Link>
        </div>
        <p className="muted small">One sign-in for Aries Admins, Aries Engineers and client users. Access is limited to authorised users of each
          organisation. Activity is audited.</p>
      </form>
    </div>
  );
}
