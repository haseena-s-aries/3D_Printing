/**
 * Embeddable interactive 3D viewer (VWR-001..011) for the GLB derivative of a STEP file version.
 * Every non-viewable state has its own message and next step (VWR-009); the panel is never left blank.
 */
import type { FileVersion } from "@passport/api-types";
import { VIEW_NAMES, createViewer, type Viewer, type ViewerStats, type ViewName } from "@passport/viewer3d";
import { useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import { ErrorNotice, Notice } from "./ui";
import { viewerState } from "./viewerState";

const LOAD_MESSAGES: Record<string, string> = {
  LOAD_FAILED: "The 3D model could not be loaded. Check your connection and reload the page; if it keeps failing, contact support with the passport number.",
  UNSUPPORTED_OR_CORRUPT: "This 3D derivative could not be displayed. The original STEP file is unchanged; an engineer can re-upload it as a new version.",
};

export default function ModelViewer({ fileId, version, revisionLabel }: { fileId: string; version: FileVersion; revisionLabel: string }) {
  const wrap = useRef<HTMLDivElement>(null);
  const host = useRef<HTMLDivElement>(null);
  const viewer = useRef<Viewer | null>(null);
  const [stats, setStats] = useState<ViewerStats | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [viewError, setViewError] = useState<string | null>(null);
  const [active, setActive] = useState<ViewName | null>("iso");
  const state = viewerState(version);

  useEffect(() => {
    if (state.kind !== "ready" || !host.current) return;
    let cancelled = false;
    setStats(null);
    setError(null);
    setViewError(null);
    const v = createViewer(host.current, { onError: (kind) => !cancelled && setViewError(LOAD_MESSAGES[kind]) });
    viewer.current = v;
    api<{ url: string }>(`/files/${fileId}/versions/${version.version_number}/download-link/`, { body: { variant: "glb" } })
      .then((link) => v.load(link.url))
      .then((s) => !cancelled && setStats(s))
      .catch((e: unknown) => {
        if (!cancelled && !(e as { kind?: string }).kind) setError(e);
      });
    return () => {
      cancelled = true;
      v.dispose();
      viewer.current = null;
    };
  }, [fileId, version.version_number, state.kind]);

  if (state.kind === "message") {
    return (
      <div className="viewer-empty" data-testid="viewer-message">
        <Notice kind={state.tone === "error" ? "warning" : state.tone}>{state.text}</Notice>
      </div>
    );
  }

  const go = (n: ViewName) => {
    viewer.current?.setView(n);
    setActive(n);
  };
  return (
    <div className="model-viewer" ref={wrap}>
      <ErrorNotice error={error} />
      {viewError && (
        <div className="notice notice-error" role="alert">
          {viewError}
        </div>
      )}
      <div className="viewer-toolbar" role="toolbar" aria-label="Model views">
        {VIEW_NAMES.map((n: ViewName) => (
          <button key={n} type="button" className={`btn btn-small ${active === n ? "is-active" : ""}`} aria-pressed={active === n} onClick={() => go(n)}>
            {n === "iso" ? "Isometric" : n[0].toUpperCase() + n.slice(1)}
          </button>
        ))}
        <button type="button" className="btn btn-small" onClick={() => viewer.current?.fit()}>
          Fit
        </button>
        <button type="button" className="btn btn-small" onClick={() => go("iso")}>
          Reset
        </button>
        <button
          type="button"
          className="btn btn-small"
          onClick={() => (document.fullscreenElement ? void document.exitFullscreen() : void wrap.current?.requestFullscreen?.())}
        >
          Full screen
        </button>
        <span className="muted small revision-label">Revision: {revisionLabel}</span>
      </div>
      <div className="viewer-stage">
        <div className="viewer-host" ref={host} data-testid="viewer-host" onPointerDown={() => setActive(null)} />
        {!stats && !viewError && !error && (
          <div className="viewer-loading" role="status" data-testid="viewer-loading">
            Loading 3D model…
          </div>
        )}
      </div>
      <p className="muted small viewer-hint">Drag to rotate · right-drag or Shift+drag to pan · scroll to zoom.</p>
      {stats && (
        <p className="muted small" data-testid="viewer-stats">
          Loaded in {stats.loadMs} ms · {stats.triangles.toLocaleString()} triangles · size {stats.sizeMm.map((v) => v.toFixed(2)).join(" × ")} mm
        </p>
      )}
    </div>
  );
}
