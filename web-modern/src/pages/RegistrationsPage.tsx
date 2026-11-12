/**
 * Aries Admin: self-registrations (CN-002). A company registration, once approved, creates a NEW private client
 * organisation with the registrant as its Client Administrator; possible duplicates are shown only here, never to
 * registrants. An Aries staff account request, once approved, gives the person the chosen Aries role (never Admin).
 */
import type { Paginated } from "@passport/api-types";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { useRegistrationConfig } from "../components/PublicShell";
import { roleLabel } from "../components/roles";
import { Badge, Card, Empty, ErrorNotice, Field, Loading, PageHeader, formatDate } from "../components/ui";

export interface Registration {
  id: string;
  kind?: "company" | "staff";
  requested_role?: string;
  company_name: string;
  trade_licence_number: string;
  licence_authority: string;
  country: string;
  city: string;
  state?: string;
  address?: string;
  contact_name: string;
  job_title: string;
  email: string;
  phone: string;
  status: "pending" | "approved" | "rejected" | "withdrawn" | "unverified";
  email_verified_at: string | null;
  reviewed_by_email: string;
  reviewed_at: string | null;
  decision_message: string;
  internal_note: string;
  client_id: string;
  client_slug: string;
  possible_duplicates: { kind: string; name: string; slug?: string; status?: string }[];
  created_at: string;
}

const TABS: [Registration["status"], string][] = [["pending", "Pending approval"], ["approved", "Approved"], ["rejected", "Rejected"]];
const DUPLICATE: Record<string, string> = {
  existing_organisation: "An organisation with this name already exists",
  same_trade_licence: "Same trade licence number in another registration",
  same_company_name: "Same company name in another registration",
  same_email_domain: "Users with this email domain already belong to a client",
};

export const isStaff = (r: Registration) => r.kind === "staff";
export const registrationTitle = (r: Registration) => (isStaff(r) ? `${r.contact_name} · Aries staff account` : r.company_name);

function Detail({ reg, onDone }: { reg: Registration; onDone: () => void }) {
  const staff = isStaff(reg);
  const roles = useRegistrationConfig()?.staff_roles ?? [];
  const [role, setRole] = useState(reg.requested_role ?? "");
  const [name, setName] = useState(reg.company_name);
  const [message, setMessage] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState<"" | "approve" | "reject">("");
  const navigate = useNavigate();

  async function decide(kind: "approve" | "reject", e?: FormEvent) {
    e?.preventDefault();
    setBusy(kind);
    setError(null);
    try {
      const body = kind === "approve" ? (staff ? { role } : { organisation_name: name }) : { message, internal_note: note };
      const r = await api<Registration>(`/registrations/${reg.id}/${kind}/`, { body });
      onDone();
      if (kind === "approve" && !staff) navigate(`/clients/${r.client_id}`);
    } catch (err) {
      setError(err);
    } finally {
      setBusy("");
    }
  }

  return (
    <Card title={registrationTitle(reg)}>
      <ErrorNotice error={error} />
      <dl className="facts">
        <div className="fact-row"><dt>Status</dt><dd><Badge tone={reg.status === "approved" ? "success" : reg.status === "rejected" ? "neutral" : "warning"}>{reg.status}</Badge></dd></div>
        {staff ? (
          <div className="fact-row"><dt>Role requested</dt><dd>{roleLabel(reg.requested_role ?? "")}</dd></div>
        ) : (
          <>
            <div className="fact-row"><dt>Trade licence</dt><dd>{reg.trade_licence_number}{reg.licence_authority && ` · ${reg.licence_authority}`}</dd></div>
            <div className="fact-row"><dt>Location</dt><dd>{[reg.address, reg.city, reg.state, reg.country].filter(Boolean).join(", ")}</dd></div>
          </>
        )}
        <div className="fact-row"><dt>{staff ? "Name" : "Contact"}</dt><dd>{reg.contact_name}{reg.job_title && ` · ${reg.job_title}`}</dd></div>
        <div className="fact-row"><dt>Email</dt><dd>{reg.email} {reg.email_verified_at && <Badge tone="success">verified {formatDate(reg.email_verified_at)}</Badge>}</dd></div>
        {reg.phone && <div className="fact-row"><dt>Phone</dt><dd>{reg.phone}</dd></div>}
        <div className="fact-row"><dt>Submitted</dt><dd>{formatDate(reg.created_at)}</dd></div>
        {reg.reviewed_at && <div className="fact-row"><dt>Decided</dt><dd>{formatDate(reg.reviewed_at)} by {reg.reviewed_by_email}</dd></div>}
        {reg.decision_message && <div className="fact-row"><dt>Message to registrant</dt><dd>{reg.decision_message}</dd></div>}
        {reg.internal_note && <div className="fact-row"><dt>Internal note</dt><dd>{reg.internal_note}</dd></div>}
        {reg.client_slug && <div className="fact-row"><dt>Organisation</dt><dd><Link to={`/clients/${reg.client_id}`}>{reg.client_slug}</Link></dd></div>}
      </dl>
      {reg.possible_duplicates.length > 0 && (
        <div className="notice notice-warning" role="note" data-testid="possible-duplicates">
          <strong>Check before approving — possible duplicates:</strong>
          <ul>{reg.possible_duplicates.map((d, i) => <li key={i}>{DUPLICATE[d.kind] ?? d.kind}: {d.name}{d.status ? ` (${d.status})` : ""}</li>)}</ul>
          Approval always creates a new organisation. If this company already has a workspace, reject and ask its Client Administrator to invite the person.
        </div>
      )}
      {reg.status === "pending" && (
        <div className="grid-2">
          {staff ? (
            <form className="form-grid single" onSubmit={(e) => void decide("approve", e)} aria-label="Approve registration">
              <h3>Approve</h3>
              <Field label="Aries role to grant" hint="Aries Admin cannot be granted from a request.">
                <select value={role} onChange={(e) => setRole(e.target.value)}>
                  {(roles.some((r) => r.value === role) ? roles : [{ value: role, label: roleLabel(role) }, ...roles]).map((r) =>
                    <option key={r.value} value={r.value}>{r.label}</option>)}
                </select>
              </Field>
              <p className="muted small">{reg.contact_name} ({reg.email}) can sign in after approval. Assign them to client companies under
                Clients → Engineers &amp; Access.</p>
              <button className="btn btn-primary" disabled={!!busy} aria-busy={busy === "approve"}>Approve account</button>
            </form>
          ) : (
            <form className="form-grid single" onSubmit={(e) => void decide("approve", e)} aria-label="Approve registration">
              <h3>Approve</h3>
              <Field label="Organisation name" hint="A new private client organisation is created with this name.">
                <input required value={name} onChange={(e) => setName(e.target.value)} />
              </Field>
              <p className="muted small">{reg.contact_name} ({reg.email}) becomes its first Client Administrator.</p>
              <button className="btn btn-primary" disabled={!!busy} aria-busy={busy === "approve"}>Approve and create organisation</button>
            </form>
          )}
          <form className="form-grid single" onSubmit={(e) => void decide("reject", e)} aria-label="Reject registration">
            <h3>Reject</h3>
            <Field label="Message to the registrant"><textarea rows={2} required value={message} onChange={(e) => setMessage(e.target.value)} /></Field>
            <Field label="Internal note (Aries only)"><textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
            <button className="btn" disabled={!!busy} aria-busy={busy === "reject"}>Reject registration</button>
          </form>
        </div>
      )}
    </Card>
  );
}

export default function RegistrationsPage() {
  const { id } = useParams();
  const [tab, setTab] = useState<Registration["status"]>("pending");
  const list = useApi<Paginated<Registration>>("/registrations/", { query: { status: tab, page_size: 50 } });
  const detail = useApi<Registration>(id ? `/registrations/${id}/` : null);
  const reload = () => {
    void list.reload();
    void detail.reload();
  };

  return (
    <>
      <PageHeader marine title="Registrations" subtitle="New client companies and Aries staff account requests waiting for review." />
      <div className="tabs" role="tablist" aria-label="Registration status">
        {TABS.map(([key, name]) => (
          <button key={key} type="button" role="tab" aria-selected={tab === key} className={`tab${tab === key ? " active" : ""}`} onClick={() => setTab(key)}>
            {name}
          </button>
        ))}
      </div>
      <div className="grid-2 wide-right">
        <Card title={TABS.find(([k]) => k === tab)?.[1]}>
          <ErrorNotice error={list.error} />
          {list.loading ? <Loading /> : list.data?.results.length ? (
            <ul className="list" aria-label="Registrations">
              {list.data.results.map((r) => (
                <li key={r.id} className={r.id === id ? "selected" : ""}>
                  <Link to={`/registrations/${r.id}`}><strong>{isStaff(r) ? r.contact_name : r.company_name}</strong></Link>{" "}
                  {isStaff(r) ? <Badge tone="info">Aries staff · {roleLabel(r.requested_role ?? "")}</Badge> : <Badge>Company</Badge>}
                  {r.possible_duplicates.length > 0 && <> <Badge tone="warning">check duplicates</Badge></>}
                  <div className="muted small">{isStaff(r) ? r.email : `${r.contact_name} · ${r.email}`} · {formatDate(r.created_at)}</div>
                </li>
              ))}
            </ul>
          ) : <Empty>No registrations here.</Empty>}
        </Card>
        {id ? (detail.loading ? <Loading /> : detail.data ? <Detail key={detail.data.id + detail.data.status} reg={detail.data} onDone={reload} /> : <ErrorNotice error={detail.error} />)
          : <Card><p className="muted">Select a registration to review it.</p></Card>}
      </div>
    </>
  );
}
