/**
 * Passport documents organised by PSEC-001 section, with version history (CAD-005, CAD-009, CAD-010),
 * new-version upload, embedded PDF preview (DRW-003) and controlled downloads (BR-039).
 */
import type { EngineeringFile, FileVersion } from "@passport/api-types";
import { Suspense, lazy, useRef, useState, type FormEvent } from "react";

import { upload } from "../../api/client";
import { useApi } from "../../api/useApi";
import { useAuth } from "../../auth/AuthContext";
import { CATEGORIES, UploadForm, conversionBadge, openDownload } from "../FilesPanel";
import ImagePreview from "../ImagePreview";
import { Badge, Empty, ErrorNotice, Loading, formatBytes, formatDate } from "../ui";

const PdfViewer = lazy(() => import("../PdfViewer"));


function NewVersionForm({ file, onDone }: { file: EngineeringFile; onDone: (v: FileVersion) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [progress, setProgress] = useState<number | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    const f = input.current?.files?.[0];
    if (!f) return setError(new Error("Choose a file."));
    const form = new FormData();
    form.append("file", f);
    form.append("note", note);
    setError(null);
    setProgress(0);
    try {
      onDone(await upload<FileVersion>(`/files/${file.id}/versions/`, form, setProgress));
      setNote("");
      if (input.current) input.current.value = "";
    } catch (err) {
      setError(err);
    } finally {
      setProgress(null);
    }
  }
  return (
    <form className="inline-form" onSubmit={submit} aria-label={`Upload new version of ${file.title}`}>
      <ErrorNotice error={error} />
      <input ref={input} type="file" aria-label="New version file" accept={(({ pdf: ".pdf", dwg: ".dwg", image: ".jpg,.jpeg,.png" }) as Record<string, string>)[file.kind ?? ""] ?? ".stp,.step"} required />
      <input aria-label="Change note" placeholder="What changed in this version?" value={note} onChange={(e) => setNote(e.target.value)} />
      <button className="btn btn-small btn-primary" disabled={progress !== null}>
        {progress === null ? "Upload version" : `Uploading ${Math.round(progress * 100)}%`}
      </button>
      <p className="muted small">The current version is kept unchanged; the new file becomes version {(file.version_count ?? 0) + 1}.</p>
    </form>
  );
}

function FileRow({ file, onOpen3d, onChanged }: { file: EngineeringFile; onOpen3d: (f: EngineeringFile) => void; onChanged: () => void }) {
  const { can } = useAuth();
  const [open, setOpen] = useState<"versions" | "preview" | "upload" | null>(null);
  const [previewVersion, setPreviewVersion] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);
  const versions = useApi<FileVersion[]>(open === "versions" ? `/files/${file.id}/versions/` : null);
  const v = file.latest_version;
  const canPreview = (file.kind === "pdf" || file.kind === "image") && can("files.download_derivative");
  const toggle = (what: typeof open) => setOpen((o) => (o === what ? null : what));

  return (
    <>
      <tr data-testid={`file-${file.title}`}>
        <td>
          <strong>{file.title}</strong> <Badge>{(file.kind ?? "").toUpperCase()}</Badge>
          <div className="muted small">
            {v?.original_filename} · {v && formatBytes(v.size_bytes)} · {v?.detected_format}
          </div>
          {v && conversionBadge(v)}
        </td>
        <td>
          v{v?.version_number}
          {(file.version_count ?? 1) > 1 && <span className="muted small"> of {file.version_count}</span>}
          <div className="muted small">{formatDate(v?.created_at)}</div>
          <div className="muted small">{v?.uploaded_by}</div>
        </td>
        <td className="mono small" title={v?.sha256}>
          {v?.sha256.slice(0, 12)}…
        </td>
        <td className="actions">
          {canPreview && v && (
            <button type="button" className="btn btn-small" aria-expanded={open === "preview"} onClick={() => { setPreviewVersion(v.version_number); toggle("preview"); }}>
              {open === "preview" ? "Close preview" : "Preview"}
            </button>
          )}
          {v?.derivatives.some((d) => d.kind === "glb") && can("files.download_derivative") && (
            <button type="button" className="btn btn-small" onClick={() => onOpen3d(file)}>
              View 3D
            </button>
          )}
          {v && can("files.download_original") && (
            <button type="button" className="btn btn-small" onClick={() => openDownload(file, v.version_number, "original").catch(setError)}>
              Download original
            </button>
          )}
          <button type="button" className="btn btn-small btn-ghost" aria-expanded={open === "versions"} onClick={() => toggle("versions")}>
            Versions
          </button>
          {can("files.upload") && (
            <button type="button" className="btn btn-small btn-ghost" aria-expanded={open === "upload"} onClick={() => toggle("upload")}>
              New version
            </button>
          )}
        </td>
      </tr>
      {(open || error) && (
        <tr className="row-detail">
          <td colSpan={4}>
            <ErrorNotice error={error} />
            {open === "preview" && previewVersion && (file.kind === "image" ? (
              <ImagePreview file={file} version={previewVersion} />
            ) : (
              <Suspense fallback={<Loading />}>
                <PdfViewer fileId={file.id} version={previewVersion} title={file.title ?? "Document"} />
              </Suspense>
            ))}
            {open === "upload" && <NewVersionForm file={file} onDone={() => { setOpen("versions"); onChanged(); }} />}
            {open === "versions" && (
              versions.loading && !versions.data ? <Loading /> : (
                <table className="table table-compact" aria-label={`Versions of ${file.title}`}>
                  <thead><tr><th>Version</th><th>Passport rev</th><th>File</th><th>Uploaded</th><th>SHA-256</th><th>Note</th><th /></tr></thead>
                  <tbody>
                    {(versions.data ?? []).map((x) => (
                      <tr key={x.id}>
                        <td>v{x.version_number}{x.version_number === v?.version_number && <Badge tone="info">current</Badge>}</td>
                        <td className="small">{x.passport_revision_number ? `rev ${x.passport_revision_number}` : "—"}</td>
                        <td className="small">{x.original_filename} · {formatBytes(x.size_bytes)}</td>
                        <td className="small">{formatDate(x.created_at)}<div className="muted">{x.uploaded_by}</div></td>
                        <td className="mono small" title={x.sha256}>{x.sha256.slice(0, 12)}…</td>
                        <td className="small">{x.note || "—"}</td>
                        <td className="actions">
                          {canPreview && <button type="button" className="btn btn-small" onClick={() => { setPreviewVersion(x.version_number); setOpen("preview"); }}>Preview</button>}
                          {can("files.download_original") && <button type="button" className="btn btn-small" onClick={() => openDownload(file, x.version_number, "original").catch(setError)}>Download</button>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )
            )}
          </td>
        </tr>
      )}
    </>
  );
}

export default function DocumentsTab({ partId, passportId, files, loading, onChanged, onOpen3d }: {
  partId: string; passportId: string; files: EngineeringFile[]; loading: boolean; onChanged: () => void; onOpen3d: (f: EngineeringFile) => void;
}) {
  const { can } = useAuth();
  return (
    <div className="documents">
      {loading && !files.length ? <Loading /> : CATEGORIES.map(([key, section]) => {
        const list = files.filter((f) => f.category === key);
        return (
          <section key={key} className="file-section" aria-label={section}>
            <h3>{section}</h3>
            {list.length ? (
              <table className="table files-table">
                <colgroup><col className="col-file" /><col className="col-version" /><col className="col-hash" /><col className="col-actions" /></colgroup>
                <thead><tr><th>File</th><th>Version</th><th>Integrity</th><th>Actions</th></tr></thead>
                <tbody>{list.map((f) => <FileRow key={f.id} file={f} onOpen3d={onOpen3d} onChanged={onChanged} />)}</tbody>
              </table>
            ) : (
              <Empty>None uploaded.</Empty>
            )}
          </section>
        );
      })}
      {can("files.upload") && (
        <section className="file-section">
          <h3>Upload file</h3>
          <UploadForm partId={partId} passportId={passportId} onUploaded={onChanged} />
        </section>
      )}
    </div>
  );
}
