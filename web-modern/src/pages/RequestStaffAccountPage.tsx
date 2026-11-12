/**
 * Public request for an Aries staff account (Aries Engineer, QA or Support). Same steps as a company registration:
 * the requester verifies the email address (single-use link + the same password), then an Aries Admin approves or
 * rejects the request on the Registrations page. Submitting never reveals whether an account already exists.
 */
import { useState, type FormEvent } from "react";

import { api } from "../api/client";
import { BackToSignIn, DevOutboxHint, PublicShell, useRegistrationConfig } from "../components/PublicShell";
import { ErrorNotice, Field, Loading } from "../components/ui";
import { PasswordInput } from "../components/PasswordInput";

const EMPTY = { full_name: "", job_title: "", email: "", phone: "", requested_role: "", password: "", password_confirm: "",
  accept_terms: false, website: "" };

export default function RequestStaffAccountPage() {
  const cfg = useRegistrationConfig();
  const [form, setForm] = useState(EMPTY);
  const [error, setError] = useState<unknown>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof EMPTY) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  const roles = cfg?.staff_roles ?? [];
  const role = form.requested_role || roles[0]?.value || "";

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (form.password !== form.password_confirm) return setError(new Error("The passwords do not match."));
    setBusy(true);
    try {
      await api("/public/staff-requests/", { body: { ...form, requested_role: role } });
      setSentTo(form.email);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function resend() {
    if (!sentTo) return;
    try {
      await api("/public/registrations/resend/", { body: { email: sentTo } });
    } catch (err) {
      setError(err);
    }
  }

  const title = "Request an Aries staff account";
  if (!cfg) return <PublicShell title={title}><Loading /></PublicShell>;
  if (!cfg.registration_enabled || !roles.length) {
    return (
      <PublicShell title={title}>
        <div className="notice notice-info" role="status">Account requests are not open yet. Please ask an Aries Admin to create your account.</div>
        <BackToSignIn />
      </PublicShell>
    );
  }
  if (sentTo) {
    return (
      <PublicShell title="Check your email">
        <div className="notice notice-success" role="status" data-testid="staff-request-submitted">
          If the details can be used, we have sent a verification link to <strong>{sentTo}</strong>. Open it and enter the password you
          chose. The link is valid for 24 hours and can be used once.
        </div>
        <ol className="steps small">
          <li className="done">Request submitted</li>
          <li>Verify your email address</li>
          <li>An Aries Admin or Manager approves the request</li>
          <li>Sign in; the admin assigns you to client companies and projects</li>
        </ol>
        <DevOutboxHint cfg={cfg} />
        <ErrorNotice error={error} />
        <p className="small">No email? <button type="button" className="link-btn" onClick={() => void resend()}>Send the link again</button></p>
        <BackToSignIn />
      </PublicShell>
    );
  }
  return (
    <PublicShell title={title} subtitle="For Aries employees: Managers, Engineers, QA and Support" wide>
      <form className="form-grid" onSubmit={submit} aria-label="Request an Aries staff account">
        <ErrorNotice error={error} />
        <Field label="Full name"><input required autoComplete="name" placeholder="Enter your full name" maxLength={150} value={form.full_name} onChange={set("full_name")} /></Field>
        <Field label="Role requested" hint="The approving Aries Admin or Manager confirms or changes it.">
          <select value={role} onChange={set("requested_role")}>
            {roles.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
          </select>
        </Field>
        <Field label="Work email" hint="Used to sign in. A verification link is sent here.">
          <input type="email" required autoComplete="email" placeholder="Enter your work email" value={form.email} onChange={set("email")} />
        </Field>
        <Field label="Job title (optional)"><input maxLength={120} placeholder="Enter your job title" value={form.job_title} onChange={set("job_title")} /></Field>
        <Field label="Phone (optional)" hint="International format, e.g. +971 50 123 4567">
          <input type="tel" autoComplete="tel" placeholder="e.g. +971 50 123 4567" maxLength={40} value={form.phone} onChange={set("phone")} />
        </Field>
        <div />
        <Field label="Password" hint="At least 12 characters; not a common or all-numeric password.">
          <PasswordInput required autoComplete="new-password" placeholder="Create a password" minLength={12} value={form.password} onChange={set("password")} />
        </Field>
        <Field label="Confirm password"><PasswordInput required autoComplete="new-password" placeholder="Re-enter your password" value={form.password_confirm} onChange={set("password_confirm")} /></Field>
        <div className="honeypot" aria-hidden="true">
          <label>Website<input tabIndex={-1} autoComplete="off" value={form.website} onChange={set("website")} /></label>
        </div>
        <label className="span-2 checkbox-row">
          <input type="checkbox" required checked={form.accept_terms} onChange={(e) => setForm({ ...form, accept_terms: e.target.checked })} />
          <span>I work for Aries and I accept the platform terms and privacy notice.</span>
        </label>
        <p className="notice notice-info small span-2">
          After you verify your email address, an Aries Admin or Manager reviews the request. You can sign in once it is approved; access to client
          companies and projects is then given by the admin. Client users are invited by their company's Client Administrator instead.
        </p>
        <div className="form-actions span-2">
          <button className="btn btn-primary" disabled={busy} aria-busy={busy}>{busy ? "Submitting…" : "Request account"}</button>
        </div>
      </form>
      <BackToSignIn />
    </PublicShell>
  );
}
