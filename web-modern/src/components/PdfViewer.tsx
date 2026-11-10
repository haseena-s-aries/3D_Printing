/**
 * Embedded multi-page PDF viewer (DRW-003): page navigation, page-number entry, zoom in/out, fit to width.
 * Uses a short-lived "preview" link; the server checks the viewer's role and audits each preview (BR-039).
 * The rendering approach (cancel the previous render task before starting the next) is the one proved in Phase 0.
 */
import { GlobalWorkerOptions, getDocument, type PDFDocumentLoadingTask, type PDFDocumentProxy, type RenderTask } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import { ZOOM_STEP, clampPage } from "./pdfUtils";
import { ErrorNotice } from "./ui";

GlobalWorkerOptions.workerSrc = workerUrl;

export default function PdfViewer({ fileId, version, title }: { fileId: string; version: number; title: string }) {
  const frame = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const task = useRef<RenderTask | null>(null);
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null);
  const [page, setPage] = useState(1);
  const [scale, setScale] = useState<number | null>(null); // null = fit to width
  const [shownScale, setShownScale] = useState(1); // scale of the page currently on screen
  const [pageInput, setPageInput] = useState("1");
  const [error, setError] = useState<unknown>(null);
  const [status, setStatus] = useState("Loading document…");

  useEffect(() => {
    let cancelled = false;
    let loading: PDFDocumentLoadingTask | null = null;
    setDoc(null);
    setError(null);
    setStatus("Loading document…");
    api<{ url: string }>(`/files/${fileId}/versions/${version}/download-link/`, { body: { variant: "preview" } })
      .then((link) => {
        // The API streams files without HTTP range support; Azure Blob Storage would allow range loading later.
        loading = getDocument({ url: link.url, disableRange: true, disableStream: true });
        return loading.promise;
      })
      .then((d) => {
        if (cancelled) return;
        setDoc(d);
        setPage(1);
        setScale(null);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setStatus("");
        setError(e instanceof Error && e.name === "InvalidPDFException" ? new Error("This document could not be displayed. The original file is unchanged.") : e);
      });
    return () => {
      cancelled = true;
      task.current?.cancel();
      void (loading as PDFDocumentLoadingTask | null)?.destroy();
    };
  }, [fileId, version]);

  const render = useCallback(async () => {
    if (!doc || !canvas.current || !frame.current) return;
    if (task.current) {
      task.current.cancel();
      try {
        await task.current.promise;
      } catch {
        /* cancelled */
      }
    }
    const pg = await doc.getPage(page);
    const base = pg.getViewport({ scale: 1 });
    const effective = scale ?? Math.max(0.2, (frame.current.clientWidth - 24) / base.width);
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const vp = pg.getViewport({ scale: effective * dpr });
    const c = canvas.current;
    c.width = vp.width;
    c.height = vp.height;
    c.style.width = `${vp.width / dpr}px`;
    c.style.height = `${vp.height / dpr}px`;
    task.current = pg.render({ canvas: c, canvasContext: c.getContext("2d")!, viewport: vp });
    try {
      await task.current.promise;
      setShownScale(effective);
      setStatus(`Page ${page} of ${doc.numPages} · zoom ${Math.round(effective * 100)}%`);
    } catch (e) {
      if ((e as Error).name !== "RenderingCancelledException") setError(e);
    } finally {
      task.current = null;
    }
    setPageInput(String(page));
  }, [doc, page, scale]);

  useEffect(() => {
    void render();
  }, [render]);

  const currentScale = () => shownScale;
  const pages = doc?.numPages ?? 0;

  return (
    <div className="pdf-viewer" aria-label={`PDF viewer: ${title}`} role="region">
      <div className="viewer-toolbar" role="toolbar" aria-label="PDF controls">
        <button type="button" className="btn btn-small" disabled={!doc || page <= 1} onClick={() => setPage((p) => clampPage(p - 1, pages))}>
          Previous page
        </button>
        <label className="page-entry">
          <span className="sr-only">Page number</span>
          <input
            aria-label="Page number"
            inputMode="numeric"
            value={pageInput}
            disabled={!doc}
            onChange={(e) => setPageInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && setPage(clampPage(Number(pageInput), pages))}
            onBlur={() => setPage(clampPage(Number(pageInput), pages))}
          />
          <span className="muted small">/ {pages || "–"}</span>
        </label>
        <button type="button" className="btn btn-small" disabled={!doc || page >= pages} onClick={() => setPage((p) => clampPage(p + 1, pages))}>
          Next page
        </button>
        <span className="toolbar-gap" />
        <button type="button" className="btn btn-small" disabled={!doc} onClick={() => setScale(currentScale() / ZOOM_STEP)} aria-label="Zoom out">
          −
        </button>
        <button type="button" className="btn btn-small" disabled={!doc} onClick={() => setScale(currentScale() * ZOOM_STEP)} aria-label="Zoom in">
          +
        </button>
        <button type="button" className="btn btn-small" disabled={!doc} onClick={() => setScale(null)}>
          Fit width
        </button>
        <span className="muted small revision-label" data-testid="pdf-status" aria-live="polite">
          {status}
        </span>
      </div>
      <ErrorNotice error={error} />
      <div className="pdf-frame" ref={frame}>
        <canvas ref={canvas} data-testid="pdf-canvas" />
      </div>
    </div>
  );
}
