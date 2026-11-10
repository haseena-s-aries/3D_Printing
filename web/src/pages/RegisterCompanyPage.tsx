/**
 * Public company registration (CN-002). Submitting never reveals whether an email or company already exists; the
 * registrant must verify the email address (single-use link + the same password) and then wait for Aries approval.
 */
import { useState, type FormEvent } from "react";

import { api } from "../api/client";
import { CompanyProfileFields, EMPTY_PROFILE, type CompanyProfile } from "../components/CompanyProfileFields";
import { BackToSignIn, DevOutboxHint, PublicShell, useRegistrationConfig } from "../components/PublicShell";
import { ErrorNotice, Field, Loading } from "../components/ui";

const EMPTY = { password: "", password_confirm: "", accept_terms: false, website: "" };

/** The shared company profile under the registration API's field names. */
export function registrationBody(p: CompanyProfile) {
  return {
    company_name: p.name, trade_licence_number: p.trade_licence_number, licence_authority: p.licence_authority, country: p.country,
    state: p.state, city: p.city, address: p.address, contact_name: p.contact_name, job_title: p.contact_title,
    email: p.contact_email, phone: p.contact_phone,
  };
}

export default function RegisterCompanyPage() {
  const cfg = useRegistrationConfig();
  const [form, setForm] = useState(EMPTY);
  const [profile, setProfile] = useState<CompanyProfile>({ ...EMPTY_PROFILE, country: "United Arab Emirates" });
  const [error, setError] = useState<unknown>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof EMPTY) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (form.password !== form.password_confirm) return setError(new Error("The passwords do not match."));
    setBusy(true);
    try {
      await api("/public/registrations/", { body: { ...registrationBody(profile), ...form } });
      setSentTo(profile.contact_email);
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

  if (!cfg) return <PublicShell title="Register your company"><Loading /></PublicShell>;
  if (!cfg.registration_enabled) {
    return (
      <PublicShell title="Register your company">
        <div className="notice notice-info" role="status">
          Company registration is not open yet. Please contact Aries to request access for your organisation.
        </div>
        <BackToSignIn />
      </PublicShell>
    );
  }
  if (sentTo) {
    return (
      <PublicShell title="Check your email">
        <div className="notice notice-success" role="status" data-testid="registration-submitted">
          If the details can be used, we have sent a verification link to <strong>{sentTo}</strong>. Open it and enter the password you
          chose. The link is valid for 24 hours and can be used once.
        </div>
        <ol className="steps small">
          <li className="done">Company details submitted</li>
          <li>Verify your email address</li>
          <li>Aries reviews and approves the registration</li>
          <li>Sign in as Client Administrator and invite colleagues</li>
        </ol>
        <DevOutboxHint cfg={cfg} />
        <ErrorNotice error={error} />
        <p className="small">No email? <button type="button" className="link-btn" onClick={() => void resend()}>Send the link again</button></p>
        <BackToSignIn />
      </PublicShell>
    );
  }
  return (
    <PublicShell title="Register your company" subtitle="Request a private workspace on the Digital Passport Platform" wide>
      <form className="form-grid" onSubmit={submit} aria-label="Register your company" noValidate={false}>
        <ErrorNotice error={error} />
        <CompanyProfileFields value={profile} onChange={setProfile} contactHeading="Primary contact (first Client Administrator)"
          emailHint="Used to sign in. A verification link is sent here." />
        <h2 className="span-2 form-section">Your sign-in password</h2>
        <Field label="Password" hint="At least 12 characters; not a common or all-numeric password.">
          <input type="password" required autoComplete="new-password" minLength={12} value={form.password} onChange={set("password")} />
        </Field>
        <Field label="Confirm password"><input type="password" required autoComplete="new-password" value={form.password_confirm} onChange={set("password_confirm")} /></Field>
        <div className="honeypot" aria-hidden="true">
          <label>Website<input tabIndex={-1} autoComplete="off" value={form.website} onChange={set("website")} /></label>
        </div>
        <label className="span-2 checkbox-row">
          <input type="checkbox" required checked={form.accept_terms} onChange={(e) => setForm({ ...form, accept_terms: e.target.checked })} />
          <span>I am authorised to register this company and I accept the platform terms and privacy notice.</span>
        </label>
        <p className="muted small span-2">
          After you verify your email address, Aries reviews the registration. Your organisation's private workspace is created only after
          approval. Registering never gives access to an existing organisation; ask its Client Administrator for an invitation instead.
        </p>
        <div className="form-actions span-2">
          <button className="btn btn-primary" disabled={busy}>{busy ? "Submitting…" : "Register company"}</button>
        </div>
      </form>
      <BackToSignIn />
    </PublicShell>
  );
}
