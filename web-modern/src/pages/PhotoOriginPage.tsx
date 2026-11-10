/**
 * Photo origin of one photograph version (contract route for Aries Admin thumbnails), reached from the part's files or
 * from the Aries QA queue. What each person may do comes from the server:
 * - the Aries Engineer who uploaded this exact version may claim Aries captured it during scanning or digitisation work
 *   (never for a client-uploaded photo; the role alone is not proof);
 * - Aries QA confirms or rejects the claim (never their own), and either QA or the claimant may withdraw it.
 * Nothing here changes the photo, its release to the client or any thumbnail rule.
 */
import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { api, fetchObjectUrl } from "../api/client";
import { useApi } from "../api/useApi";
import { Icon } from "../components/icons";
import { Badge, BackLink, Card, ErrorNotice, Field, Loading, Notice, PageHeader, formatDate } from "../components/ui";

type OriginEvent = { event: string; label: string; role: string; by: string; at: string; capture_reference: string; capture_date: string | null; note: string };
type Origin = {
  file: string; version: number; state: string; label: string; title: string; part: { id: string; part_number: string; name: string };
  uploaded_by: string; uploaded_at: string; uploaded_by_client: boolean; claim_block: string;
  history: OriginEvent[]; can: { claim: boolean; confirm: boolean; withdraw: boolean };
};
type FileInfo = { id: string; title: string; latest_version: { version_number: number } | null };

const TONE: Record<string, "success" | "info" | "warning" | "neutral"> = { confirmed: "success", claimed: "info", rejected: "warning", withdrawn: "neutral" };
const CLAIM_BLOCK: Record<string, string> = {
  client_uploaded: "This photo was uploaded by the client. Client-uploaded photos can never be classified as Aries captures.",
  not_uploader: "Only the person who uploaded this version can claim its origin. If they are not available, the origin stays unresolved.",
  already_claimed: "This version already has an open or confirmed claim.",
};

function Thumb({ fileId, version, alt }: { fileId: string; version: number; alt: string }) {
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let url: string | null = null;
    let live = true;
    fetchObjectUrl(`/files/${fileId}/versions/${version}/thumbnail/`)
      .then((u) => { url = u; if (live) setSrc(u); else URL.revokeObjectURL(u); })
      .catch(() => live && setFailed(true));
    return () => { live = false; if (url) URL.revokeObjectURL(url); };
  }, [fileId, version]);
  if (failed) return <div className="origin-thumb origin-thumb-empty" role="img" aria-label="No thumbnail available"><Icon name="cube" size="sm" />No thumbnail</div>;
  return <div className="origin-thumb">{src ? <img src={src} alt={alt} /> : <span className="admin-preview-loading" aria-hidden />}</div>;
}

export default function PhotoOriginPage() {
  const { id = "", fileId = "" } = useParams();
  const [params] = useSearchParams();
  const fromQueue = params.get("from") === "queue";
  const file = useApi<FileInfo>(`/files/${fileId}/`);
  const n = file.data?.latest_version?.version_number;
  const origin = useApi<Origin>(n ? `/files/${fileId}/versions/${n}/origin/` : null);
  const [reference, setReference] = useState("");
  const [captureDate, setCaptureDate] = useState("");
  const [note, setNote] = useState("");
  const [qaNote, setQaNote] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState("");

  const act = async (body: Record<string, unknown>, message: string) => {
    setBusy(true); setError(null); setDone("");
    try {
      origin.setData(await api<Origin>(`/files/${fileId}/versions/${n}/origin/`, { method: "POST", body }));
      setDone(message); setNote(""); setQaNote(""); setReason(""); setReference(""); setCaptureDate("");
    } catch (e) { setError(e); } finally { setBusy(false); }
  };

  const back = fromQueue ? <BackLink to="/origin-claims">Photo origin queue</BackLink> : <BackLink to={`/parts/${id}?tab=documents`}>Spare part documents</BackLink>;
  if (file.error || origin.error) return <>{back}<ErrorNotice error={file.error ?? origin.error} /></>;
  if (!origin.data) return <Loading />;
  const o = origin.data;
  return (
    <div className="photo-origin">
      {back}
      <PageHeader title="Photo origin" subtitle={<><Link to={`/parts/${o.part.id}`}>{o.part.part_number}</Link> · {o.part.name} · {o.title} (version {o.version})</>}
        actions={<Badge tone={TONE[o.state] ?? "neutral"}>{o.label}</Badge>} />
      {done && <Notice kind="success"><span role="status">{done}</span></Notice>}
      <ErrorNotice error={error} />
      <div className="origin-grid">
        <Card title="Photograph">
          <Thumb fileId={o.file} version={o.version} alt={`Photo ${o.title} of ${o.part.part_number}`} />
          <dl className="facts origin-facts">
            <dt>Uploaded by</dt><dd>{o.uploaded_by || "Unknown"}{o.uploaded_by_client && " (client)"}, {formatDate(o.uploaded_at)}</dd>
            <dt>Origin</dt><dd>{o.label}</dd>
          </dl>
          <p className="muted small">The uploader's role is never taken as proof of origin. Only a claim by the uploader, confirmed by Aries QA,
            lets this photo count towards a verified contract authorization.</p>
        </Card>

        <div className="origin-actions">
          {o.can.claim && (
            <Card title="Claim as an Aries capture">
              <form className="form-grid single" aria-label="Claim photo origin" onSubmit={(e) => { e.preventDefault();
                void act({ action: "claim", capture_reference: reference, capture_date: captureDate || undefined, note }, "Claim recorded. Aries QA will review it."); }}>
                <p className="muted">Claim only a photo you took during Aries scanning or digitisation work. Give the scanning job or
                  digitisation reference, or describe the work if the platform has no reference (historical photos).</p>
                <Field label="Scanning job or digitisation reference"><input value={reference} maxLength={120} onChange={(e) => setReference(e.target.value)} placeholder="For example SCAN-2026-014" /></Field>
                <Field label="Capture date (optional)"><input type="date" value={captureDate} onChange={(e) => setCaptureDate(e.target.value)} /></Field>
                <Field label="Description of the scanning work"><textarea value={note} maxLength={500} rows={3} onChange={(e) => setNote(e.target.value)} /></Field>
                <div className="form-actions"><button className="btn btn-primary" disabled={busy || (!reference.trim() && note.trim().length < 15)}>Claim as Aries capture</button></div>
              </form>
            </Card>
          )}
          {!o.can.claim && o.claim_block && o.state !== "claimed" && o.state !== "confirmed" && (
            <Notice kind="info">{CLAIM_BLOCK[o.claim_block]}</Notice>
          )}
          {o.can.confirm && (
            <Card title="QA decision">
              <form className="form-grid single" aria-label="QA decision on photo origin" onSubmit={(e) => e.preventDefault()}>
                <p className="muted">Check the claim against the scanning record and the photo itself. You cannot decide on a claim you made or a photo you uploaded.</p>
                <Field label="What you checked"><textarea value={qaNote} maxLength={500} rows={3} onChange={(e) => setQaNote(e.target.value)} /></Field>
                <div className="form-actions">
                  <button type="button" className="btn btn-primary" disabled={busy || qaNote.trim().length < 10}
                    onClick={() => void act({ action: "confirm", note: qaNote }, "Origin confirmed as an Aries capture.")}>Confirm origin</button>
                  <button type="button" className="btn" disabled={busy || qaNote.trim().length < 10}
                    onClick={() => void act({ action: "reject", note: qaNote }, "Claim rejected. The origin stays unknown.")}>Reject claim</button>
                </div>
              </form>
            </Card>
          )}
          {o.state === "claimed" && !o.can.confirm && <Notice kind="info">This claim is waiting for Aries QA. The claimant cannot confirm it.</Notice>}
          {o.can.withdraw && (
            <Card title="Withdraw the claim">
              <form className="form-grid single" aria-label="Withdraw photo origin claim" onSubmit={(e) => { e.preventDefault();
                void act({ action: "withdraw", note: reason }, "Claim withdrawn. Any Admin thumbnail link based on it stops working."); }}>
                <Field label="Reason"><input value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} /></Field>
                <div className="form-actions"><button className="btn btn-danger" disabled={busy || reason.trim().length < 10}>Withdraw claim</button></div>
              </form>
            </Card>
          )}
        </div>
      </div>

      <Card title="Origin history">
        {o.history.length === 0 ? <p className="muted">No origin has been claimed for this version.</p> : (
          <div className="table-scroll">
            <table className="table table-stack" aria-label="Origin history">
              <thead><tr><th>Event</th><th>By</th><th>Date</th><th>Reference</th><th>Note</th></tr></thead>
              <tbody>
                {o.history.map((h) => (
                  <tr key={h.at + h.event}>
                    <td><Badge tone={TONE[h.event] ?? "neutral"}>{h.label}</Badge></td>
                    <td>{h.by} ({h.role})</td><td>{formatDate(h.at)}</td>
                    <td>{h.capture_reference || <span className="muted">—</span>}{h.capture_date && <div className="muted small">Captured {h.capture_date}</div>}</td>
                    <td>{h.note || <span className="muted">—</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
