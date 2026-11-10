import type { Client, Paginated } from "@passport/api-types";
import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { CompanyProfileFields, EMPTY_PROFILE, type CompanyProfile } from "../components/CompanyProfileFields";
import { ListPager, ListToolbar, useListControls } from "../components/ListControls";
import { Badge, Card, Empty, ErrorNotice, Field, Loading, PageHeader, Pager } from "../components/ui";

export { compactBody } from "../components/ClientUsers";

/** Aries Admin: client companies and creating one. Each company opens its own Client Management page (/clients/:id). */
const VIEWS = [["list", "Client organisations"], ["new", "Add a client"]] as const;

export default function ClientsPage() {
  const [page, setPage] = useState(1);
  // All companies in one response where the API allows it, so the list can be searched, filtered and paged here; larger
  // sets fall back to the server's own pages below the list.
  const list = useApi<Paginated<Client>>("/clients/", { query: { page, page_size: 200 } });
  const rows = list.data?.results ?? [];
  const c = useListControls(rows, {
    text: (r) => `${r.name} ${r.slug}`,
    filters: [["all", "All", () => true], ["active", "Active", (r) => r.status === "active"], ["suspended", "Suspended", (r) => r.status !== "active"],
      ["incomplete", "Profile incomplete", (r) => !r.profile_complete]],
    sorts: [["name", "Name A–Z", (a, b) => a.name.localeCompare(b.name)], ["members", "Most members", (a, b) => b.member_count - a.member_count || a.name.localeCompare(b.name)]],
    pageSize: 15,
  });
  const [params, setParams] = useSearchParams();
  const view = params.get("view") === "new" ? "new" : "list";
  const NEW_SETTINGS = { slug: "", hosting_model: "shared", region_code: "", invite_contact: true };
  const [profile, setProfile] = useState<CompanyProfile>({ ...EMPTY_PROFILE, country: "United Arab Emirates" });
  const [form, setForm] = useState(NEW_SETTINGS);
  const [error, setError] = useState<unknown>(null);
  const navigate = useNavigate();
  const wanted = params.get("client");

  async function create(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const created = await api<Client>("/clients/", { body: { ...profile, ...form } });
      const message = form.invite_contact
        ? `Client organisation "${profile.name}" created. An invitation was emailed to ${profile.contact_email}; the contact is not active or verified until it is accepted.`
        : `Client organisation "${profile.name}" created. No contact was invited.`;
      navigate(`/clients/${created.id}`, { state: { message } }); // next steps (people, engineers) are on its own page
    } catch (err) {
      setError(err);
    }
  }

  // Older links (e.g. from an approved registration) used ?client=<id>
  if (wanted) return <Navigate to={`/clients/${wanted}`} replace />;

  return (
    <>
      <PageHeader title="Client organisations" subtitle="Each client is an isolated tenant. Dedicated hosting is recorded per client."
        actions={view === "list" ? <button type="button" className="btn btn-primary" onClick={() => setParams({ view: "new" })}>Add a client</button> : undefined} />
      <div className="tabs" role="tablist" aria-label="Client organisations">
        {VIEWS.map(([v, name]) => (
          <button key={v} type="button" role="tab" aria-selected={view === v} className={`tab ${view === v ? "is-active" : ""}`}
            onClick={() => setParams(v === "list" ? {} : { view: v })}>{name}{v === "list" && list.data ? <span className="count" aria-hidden>{list.data.count}</span> : null}</button>
        ))}
      </div>
      {view === "list" && (
        <Card>
          <ErrorNotice error={list.error} />
          {list.loading && !list.data ? (
            <Loading />
          ) : rows.length ? (
            <>
            <p className="list-summary">{list.data!.count} client organisations · {rows.filter((r) => r.status === "active").length} active ·{" "}
              {rows.filter((r) => !r.profile_complete).length} with an incomplete profile</p>
            <ListToolbar c={c} searchLabel="Search client organisations" placeholder="Search by name or short identifier" />
            <div className="table-scroll">
            <table className="table table-stack" aria-label="Client organisations">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Status</th>
                  <th>Hosting</th>
                  <th>Members</th>
                </tr>
              </thead>
              <tbody>
                {c.visible.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <Link to={`/clients/${r.id}`}>{r.name}</Link>
                      <div className="muted small">{r.slug}{!r.profile_complete && <> <Badge tone="warning">Profile incomplete</Badge></>}</div>
                    </td>
                    <td>
                      <Badge tone={r.status === "active" ? "success" : "warning"}>{r.status}</Badge>
                    </td>
                    <td>{r.hosting_model}</td>
                    <td>{r.member_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
            <ListPager c={c} noun="client organisations" />
            </>
          ) : (
            <Empty icon="building">No client organisations yet.</Empty>
          )}
          {list.data && list.data.count > rows.length && <Pager page={page} count={list.data.count} pageSize={200} onPage={setPage} />}
        </Card>
      )}
      {view === "new" && (
        <Card title="New client organisation">
          <form className="form-grid" onSubmit={create} aria-label="New client organisation">
            <ErrorNotice error={error} />
            <p className="muted small span-2">The same company profile as self-registration. Creating here needs no separate approval; the
              primary contact is only invited and is not active or verified until they accept the emailed link.</p>
            <CompanyProfileFields value={profile} onChange={setProfile} />
            <h2 className="span-2 form-section">Aries settings</h2>
            <Field label="Short identifier" hint="Lowercase letters, numbers and hyphens; used at sign-in. Cannot be changed later.">
              <input required pattern="[a-z0-9\-]+" value={form.slug} onChange={(e) => setForm({ ...form, slug: e.target.value })} />
            </Field>
            <Field label="Hosting model">
              <select value={form.hosting_model} onChange={(e) => setForm({ ...form, hosting_model: e.target.value })}>
                <option value="shared">Shared Azure platform</option>
                <option value="dedicated">Dedicated Azure deployment</option>
              </select>
            </Field>
            <Field label="Region (informational)" hint="Residency rules are not decided yet (OQ-71); nothing is enforced from this value.">
              <input value={form.region_code} onChange={(e) => setForm({ ...form, region_code: e.target.value })} />
            </Field>
            <label className="span-2 checkbox-row">
              <input type="checkbox" checked={form.invite_contact} onChange={(e) => setForm({ ...form, invite_contact: e.target.checked })} />
              <span>Email the primary contact an invitation to become Client Administrator</span>
            </label>
            <div className="form-actions span-2">
              <button className="btn btn-primary">Create client</button>
            </div>
          </form>
        </Card>
      )}
    </>
  );
}
