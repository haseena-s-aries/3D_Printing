/** Small, dependency-free UI building blocks used across the portals. */
import { cloneElement, useId, type ReactElement, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../api/client";

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        {subtitle && <p className="muted">{subtitle}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}

export function Card({ title, children, actions }: { title?: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="card">
      {(title || actions) && (
        <div className="card-head">
          {title && <h2>{title}</h2>}
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

export function ErrorNotice({ error }: { error: unknown }) {
  if (!error) return null;
  const e = error instanceof ApiError ? error : null;
  const fieldErrors = e?.code === "validation_error" ? Object.entries(e.details) : [];
  return (
    <div className="notice notice-error" role="alert">
      <strong>{e ? e.message : error instanceof Error && error.message ? error.message : "Something went wrong."}</strong>
      {fieldErrors.length > 0 && (
        <ul>
          {fieldErrors.map(([field, msgs]) => (
            <li key={field}>
              {label(field)}: {Array.isArray(msgs) ? msgs.join(" ") : JSON.stringify(msgs)}
            </li>
          ))}
        </ul>
      )}
      {e?.requestId && <div className="muted small">Reference: {e.requestId}</div>}
    </div>
  );
}

export function Notice({ kind = "info", children }: { kind?: "info" | "warning" | "success"; children: ReactNode }) {
  return <div className={`notice notice-${kind}`}>{children}</div>;
}

export function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "info" | "success" | "warning" | "danger" }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Loading() {
  return (
    <div className="loading" aria-live="polite">
      Loading…
    </div>
  );
}

/** Label + control + hint with explicit id/htmlFor and aria-describedby, so the accessible name is exactly the label. */
export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactElement<{ id?: string; "aria-describedby"?: string }> }) {
  const id = useId();
  const hintId = `${id}-hint`;
  return (
    <div className="field">
      <label className="field-label" htmlFor={id}>
        {label}
      </label>
      {cloneElement(children, { id, "aria-describedby": hint ? hintId : undefined })}
      {hint && (
        <span className="field-hint" id={hintId}>
          {hint}
        </span>
      )}
    </div>
  );
}

export function DisabledAction({ label, reason }: { label: string; reason: string }) {
  return (
    <span className="disabled-action" title={reason}>
      <button type="button" className="btn" disabled aria-describedby={undefined}>
        {label}
      </button>
      <span className="muted small">{reason}</span>
    </span>
  );
}

/** Previous/next paging for DRF page-number pagination. */
export function Pager({ page, count, pageSize, onPage }: { page: number; count: number; pageSize: number; onPage: (page: number) => void }) {
  const pages = Math.max(1, Math.ceil(count / pageSize));
  if (count <= pageSize) return <p className="muted small pager-info">{count} {count === 1 ? "record" : "records"}</p>;
  return (
    <nav className="pager" aria-label="Pagination">
      <button type="button" className="btn btn-small" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        Previous
      </button>
      <span className="muted small">
        Page {page} of {pages} · {count} records
      </span>
      <button type="button" className="btn btn-small" disabled={page >= pages} onClick={() => onPage(page + 1)}>
        Next
      </button>
    </nav>
  );
}

export function BackLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link className="back-link" to={to}>
      ← {children}
    </Link>
  );
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export const label = (s: string) => s.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
