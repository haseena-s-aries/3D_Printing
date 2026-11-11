import type { EngineeringFile, FileVersion, Paginated } from "@passport/api-types";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { api, sameOriginUrl, upload, type ApiError } from "../api/client";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { Badge, Card, Empty, ErrorNotice, Field, formatBytes, formatDate } from "./ui";

const ACCEPT = ".stp,.step,.dwg,.pdf,.jpg,.jpeg,.png,.stl,.ply,.e57,.las,.xyz,.pts";
const CLIENT_LIMIT_MB: Record<string, number> = { stp: 200, step: 200, dwg: 100, pdf: 100, jpg: 20, jpeg: 20, png: 20,
  stl: 500, ply: 500, e57: 500, las: 500, xyz: 500, pts: 500 };
const SCAN_EXT = ["stl", "ply", "e57", "las", "xyz", "pts"];
export const UNSUPPORTED_MESSAGE = "Only STEP (.stp, .step), DWG (.dwg), PDF (.pdf), part photographs (.jpg, .jpeg, .png) and 3D scan data (.stl, .ply, .e57, .las, .xyz, .pts) can be uploaded.";
export const CATEGORIES: [string, string][] = [
  ["3d_model", "Interactive 3D model"],
  ["drawing", "Engineering drawing"],
  ["specification", "Manufacturing specification"],
  ["inspection", "Inspection and quality"],
  ["certificate", "Certification"],
  ["photo", "Photographs"],
  ["scan_source", "3D scan source data"],
  ["other", "Other"],
];

const CONVERSION_TEXT: Record<string, string> = {
  succeeded: "3D view ready",
  queued: "Queued for 3D conversion",
  running: "Converting to 3D…",
  failed: "3D conversion failed",
  not_requested: "3D conversion not requested",
};

export function conversionBadge(v: FileVersion) {
  const c = v.conversion;
  if (!c) return null;
  const tone = c.status === "succeeded" ? "success" : c.status === "failed" ? "danger" : c.status === "not_available" ? "neutral" : "info";
  const text = c.status === "not_available" ? "Preview not available" : CONVERSION_TEXT[c.status] ?? c.status;
  return (
    <Badge tone={tone}>
      <span title={c.reason ?? c.error_code ?? ""} data-conversion={c.status}>
        {text}
        {c.status === "failed" && c.error_code ? ` (${c.error_code})` : ""}
      </span>
    </Badge>
  );
}

/** True while any file's latest version is waiting for or undergoing 3D conversion. */
export function conversionPending(files: EngineeringFile[]): boolean {
  return files.some((f) => ["queued", "running"].includes(f.latest_version?.conversion?.status ?? ""));
}

/** Re-fetch every few seconds while a conversion is pending (stops by itself, max ~3 minutes). */
export function useConversionPolling(files: EngineeringFile[], reload: () => unknown, intervalMs = 4000) {
  const pending = conversionPending(files);
  useEffect(() => {
    if (!pending) return;
    let n = 0;
    const t = window.setInterval(() => {
      if (++n > 45) return window.clearInterval(t);
      void reload();
    }, intervalMs);
    return () => window.clearInterval(t);
  }, [pending, reload, intervalMs]);
  return pending;
}

export async function openDownload(file: Pick<EngineeringFile, "id">, version: number, variant: "original" | "glb") {
  const link = await api<{ url: string }>(`/files/${file.id}/versions/${version}/download-link/`, { body: { variant } });
  window.location.assign(sameOriginUrl(link.url));
}

export function UploadForm({ partId, passportId, onUploaded, defaultCategory = "drawing", supportingOnly = false }: {
  partId: string; passportId?: string; onUploaded: () => void; defaultCategory?: string; supportingOnly?: boolean;
}) {
  const categories = supportingOnly ? CATEGORIES.filter(([k]) => k === "photo" || k === "other") : CATEGORIES;
  const input = useRef<HTMLInputElement>(null);
  const [category, setCategory] = useState(defaultCategory);
  const [title, setTitle] = useState("");
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState<string | null>(null);
  const [release, setRelease] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setDone(null);
    const f = input.current?.files?.[0];
    if (!f) return setError(new Error("Choose a file."));
    const ext = f.name.split(".").pop()?.toLowerCase() ?? "";
    if (!CLIENT_LIMIT_MB[ext]) return setError({ message: UNSUPPORTED_MESSAGE });
    if (f.size > CLIENT_LIMIT_MB[ext] * 1024 * 1024) return setError({ message: `The file is larger than the ${CLIENT_LIMIT_MB[ext]} MB limit.` });
    const form = new FormData();
    form.append("file", f);
    form.append("part", partId);
    if (passportId) form.append("passport", passportId);
    form.append("category", category);
    form.append("title", title || f.name);
    if (!supportingOnly) form.append("client_visible", release ? "true" : "false");  // D-02: never visible unless released on purpose
    setProgress(0);
    try {
      const res = await upload<EngineeringFile>("/files/", form, setProgress);
      setDone(`${res.title} uploaded (SHA-256 ${res.latest_version?.sha256.slice(0, 12)}…)${res.client_visible ? ", released to the client" : ", Aries only"}.`);
      setTitle("");
      setRelease(false);
      if (input.current) input.current.value = "";
      onUploaded();
    } catch (err) {
      setError(err);
    } finally {
      setProgress(null);
    }
  }

  const err = error as ApiError | { message: string } | Error | null;
  return (
    <form className="form-grid upload-form" onSubmit={submit} aria-label="Upload engineering file">
      {err && <ErrorNotice error={err instanceof Error || "code" in (err as object) ? err : new Error(err.message)} />}
      {done && <div className="notice notice-success">{done}</div>}
      <Field label="File" hint={supportingOnly ? "Photographs (JPEG/PNG) and PDF documents. Engineering master files are managed by Aries."
        : "STEP, DWG, PDF, a part photograph (JPEG/PNG) or 3D scan data (STL, PLY, E57, LAS, XYZ, PTS). The original is preserved unchanged and checksummed."}>
        <input
          ref={input}
          type="file"
          accept={supportingOnly ? ".pdf,.jpg,.jpeg,.png" : ACCEPT}
          required
          onChange={(e) => {
            // Photographs go to the Photographs section unless the user picked another one on purpose
            const ext = e.target.files?.[0]?.name.split(".").pop()?.toLowerCase() ?? "";
            if (["jpg", "jpeg", "png"].includes(ext) && category === defaultCategory) setCategory("photo");
            if (SCAN_EXT.includes(ext) && category === defaultCategory) setCategory("scan_source");
          }}
        />
      </Field>
      <Field label="Section">
        <select value={category} onChange={(e) => setCategory(e.target.value)}>
          {categories.map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Title">
        <input value={title} placeholder="Defaults to the file name" onChange={(e) => setTitle(e.target.value)} />
      </Field>
      {!supportingOnly && (
        <label className="inline-check span-2 wrap-text"><input type="checkbox" checked={release} onChange={(e) => setRelease(e.target.checked)} />
          Release this version to the client now (otherwise Aries only; you can release or withdraw it later)</label>
      )}
      <div className="form-actions">
        <button className="btn btn-primary" disabled={progress !== null}>
          {progress === null ? "Upload" : `Uploading ${Math.round(progress * 100)}%`}
        </button>
      </div>
      {progress !== null && <progress max={1} value={progress} aria-label="Upload progress" />}
    </form>
  );
}

export default function FilesPanel({ partId, passportId, title = "Engineering files", supportingUpload = false }: {
  partId: string; passportId?: string; title?: string; supportingUpload?: boolean;
}) {
  const { can, session } = useAuth();
  const files = useApi<Paginated<EngineeringFile>>("/files/", { query: { part: partId, page_size: 100 } });
  const [error, setError] = useState<unknown>(null);
  useConversionPolling(files.data?.results ?? [], files.reload);
  const grouped =CATEGORIES.map(([key, name]) => [name, (files.data?.results ?? []).filter((f) => f.category === key)] as const).filter(([, list]) => list.length);

  return (
    <Card title={title}>
      {session?.admin_access?.admin_workspace && !session.admin_access.file_decision && (
        <div className="notice notice-info" data-testid="file-content-closed">File contents (downloads, 3D views, photos and documents) are closed
          to the Aries Admin in this company until an authorization decision is documented. Titles and versions are shown for reference.</div>
      )}
      <ErrorNotice error={files.error ?? error} />
      {grouped.length === 0 && !files.loading && <Empty>No files yet.</Empty>}
      {grouped.map(([section, list]) => (
        <div key={section} className="file-section">
          <h3>{section}</h3>
          <table className="table">
            <thead>
              <tr>
                <th>File</th>
                <th>Version</th>
                <th>Integrity</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {list.map((f) => {
                const v = f.latest_version;
                return (
                  <tr key={f.id}>
                    <td>
                      <strong>{f.title}</strong> <Badge>{(f.kind ?? "").toUpperCase()}</Badge>
                      {can("files.upload") && (f.client_visible
                        ? <> <Badge tone="success">Released to client · v{f.released_version}</Badge>
                          {v && f.released_version != null && v.version_number > f.released_version && <> <Badge tone="warning">v{v.version_number} not released</Badge></>}</>
                        : <> <Badge>Aries only</Badge></>)}
                      {f.kind === "scan" && <div className="muted small">Scan source data: stored as uploaded, not converted and not production-ready CAD.</div>}
                      <div className="muted small">
                        {v?.original_filename} · {v && formatBytes(v.size_bytes)} · {v?.detected_format}
                      </div>
                      {v && conversionBadge(v)}
                    </td>
                    <td>
                      v{v?.version_number}
                      <div className="muted small">{formatDate(v?.created_at)}</div>
                    </td>
                    <td className="mono small" title={v?.sha256}>
                      {v?.sha256.slice(0, 16)}…
                    </td>
                    <td className="actions">
                      {v && can("files.download_original") && (
                        <button type="button" className="btn btn-small" onClick={() => openDownload(f, v.version_number, "original").catch(setError)}>
                          Download original
                        </button>
                      )}
                      {v && can("files.upload") && (
                        <button type="button" className="btn btn-small" aria-label={`${f.client_visible ? "Withdraw from client" : `Release v${v.version_number} to client`}: ${f.title}`}
                          onClick={() => api(`/files/${f.id}/`, { method: "PATCH", body: f.client_visible ? { client_visible: false } : { client_visible: true, released_version: v.version_number } })
                            .then(() => files.reload()).catch(setError)}>
                          {f.client_visible ? "Withdraw from client" : `Release v${v.version_number} to client`}
                        </button>
                      )}
                      {v && can("files.upload") && f.client_visible && f.released_version != null && v.version_number > f.released_version && (
                        <button type="button" className="btn btn-small" aria-label={`Release v${v.version_number} to client instead of v${f.released_version}: ${f.title}`}
                          onClick={() => api(`/files/${f.id}/`, { method: "PATCH", body: { released_version: v.version_number } }).then(() => files.reload()).catch(setError)}>
                          Release v{v.version_number} instead
                        </button>
                      )}
                      {v && f.kind === "image" && (can("files.origin_claim") || can("files.origin_confirm")) && (
                        <Link className="btn btn-small" to={`/parts/${partId}/photos/${f.id}/origin`} aria-label={`Photo origin of ${f.title}`}>
                          Photo origin
                        </Link>
                      )}
                      {v && v.derivatives.some((d) => d.kind === "glb") && can("files.download_derivative") && (
                        <Link className="btn btn-small" to={`/files/${f.id}/versions/${v.version_number}/view?rev=${encodeURIComponent(`v${v.version_number}`)}`}>
                          View 3D
                        </Link>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ))}
      {can("files.upload") ? (
        <>
          <h3>Upload file</h3>
          <UploadForm partId={partId} passportId={passportId} onUploaded={() => void files.reload()} />
        </>
      ) : supportingUpload && (
        <>
          <h3>Add a photograph or supporting document</h3>
          <UploadForm partId={partId} onUploaded={() => void files.reload()} defaultCategory="other" supportingOnly />
        </>
      )}
    </Card>
  );
}
