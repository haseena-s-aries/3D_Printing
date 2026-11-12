/**
 * Client: request 3D scanning / digitisation of a physical part that is not yet in the digital inventory.
 * Our team performs the scanning on site; this form only records the request. Quotations are handled offline.
 */
import type { Paginated, Project, ServiceRequest } from "@passport/api-types";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { api, upload } from "../api/client";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { BackLink, Card, ErrorNotice, Notice, PageHeader } from "../components/ui";

const REASONS: [string, string][] = [["obsolete", "Obsolete or no longer supplied"], ["long_lead_time", "Long lead time"], ["failure", "Failure or breakdown"], ["other", "Other"]];

export default function ScanRequestPage() {
  const { session } = useAuth();
  const navigate = useNavigate();
  const me = session?.user;
  const [form, setForm] = useState({
    site_location: "", equipment: "", part_description: "", reason: "obsolete", preferred_date: "", priority: "routine",
    contact_name: me ? `${me.first_name} ${me.last_name}`.trim() : "", contact_phone: "", contact_email: me?.email ?? "", remarks: "", client_reference: "",
    project: "",
  });
  const projects = useApi<Paginated<Project>>("/projects/", { query: { page_size: 200 } });
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState("");
  const [error, setError] = useState<unknown>(null);
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api<ServiceRequest>("/requests/", { body: { request_type: "digitisation", ...form, preferred_date: form.preferred_date || null, project: form.project || null } });
      for (const [i, f] of files.entries()) {
        setProgress(`Uploading ${i + 1} of ${files.length}: ${f.name}`);
        const fd = new FormData();
        fd.append("file", f);
        await upload(`/requests/${r.id}/attachments/`, fd);
      }
      navigate(`/requests/${r.id}`, { state: { created: true } });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
      setProgress("");
    }
  }

  return (
    <>
      <BackLink to="/requests">My requests</BackLink>
      <PageHeader marine title="Request 3D scanning" subtitle="Ask our team to scan and digitise a physical spare part that is not yet in your digital inventory." />
      <Card>
        <Notice>
          Our engineers perform the scanning and reverse engineering on site or in our facility. After acknowledgement we will contact you to agree the
          visit and any commercial terms; quotations are handled outside the portal.
        </Notice>
        <form className="form-grid" onSubmit={submit} aria-label="3D scanning request">
          <label className="field"><span>Site or location</span><input required maxLength={300} value={form.site_location} onChange={set("site_location")} placeholder="Plant, building, vessel" /></label>
          <label className="field"><span>Equipment</span><input maxLength={300} value={form.equipment} onChange={set("equipment")} placeholder="Equipment name or tag" /></label>
          <label className="field span-2"><span>Part description</span><textarea required rows={3} maxLength={2000} value={form.part_description} onChange={set("part_description")} placeholder="What the part is, size, material if known, condition" /></label>
          <label className="field"><span>Reason for digitisation</span>
            <select value={form.reason} onChange={set("reason")}>{REASONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
          </label>
          <label className="field"><span>Preferred service date</span><input type="date" min={new Date().toISOString().slice(0, 10)} value={form.preferred_date} onChange={set("preferred_date")} /></label>
          <label className="field"><span>Contact name</span><input required maxLength={150} value={form.contact_name} onChange={set("contact_name")} /></label>
          <label className="field"><span>Contact phone</span><input maxLength={60} value={form.contact_phone} onChange={set("contact_phone")} /></label>
          <label className="field"><span>Contact email</span><input type="email" maxLength={254} value={form.contact_email} onChange={set("contact_email")} /></label>
          <label className="field"><span>Priority</span>
            <select value={form.priority} onChange={set("priority")}><option value="routine">Routine</option><option value="urgent">Urgent (breakdown)</option></select>
          </label>
          <label className="field span-2"><span>Photographs, supporting documents or existing scan data (JPEG, PNG, PDF, STEP, DWG, STL, PLY, E57, LAS, XYZ, PTS)</span>
            <input type="file" multiple accept=".jpg,.jpeg,.png,.pdf,.stp,.step,.dwg,.stl,.ply,.e57,.las,.xyz,.pts" onChange={(e) => setFiles(Array.from(e.target.files ?? []).slice(0, 10))} aria-label="Photographs or supporting documents" />
          </label>
          <label className="field"><span>Your reference (optional)</span><input maxLength={80} value={form.client_reference} onChange={set("client_reference")} /></label>
          <label className="field"><span>Project (optional)</span>
            <select value={form.project} onChange={set("project")}>
              <option value="">No project yet: Aries links or creates one</option>
              {(projects.data?.results ?? []).map((p) => <option key={p.id} value={p.id}>{p.code} · {p.name}</option>)}
            </select></label>
          <label className="field span-2"><span>Remarks</span><textarea rows={3} maxLength={2000} value={form.remarks} onChange={set("remarks")} /></label>
          <ErrorNotice error={error} />
          {progress && <p className="muted small span-2" role="status">{progress}</p>}
          <div className="form-actions span-2">
            <button type="button" className="btn" onClick={() => navigate(-1)}>Cancel</button>
            <button className="btn btn-primary" disabled={busy} aria-busy={busy}>{busy ? "Sending…" : "Submit scanning request"}</button>
          </div>
        </form>
      </Card>
    </>
  );
}
