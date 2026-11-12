/** Small, dependency-free UI building blocks used across the portals. */
import { cloneElement, useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactElement, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../api/client";
import { Icon, type IconName } from "./icons";
import { MarineBanner } from "./MarineHero";

/** Text with a line-break opportunity after commas and slashes (long material texts such as RING,WEAR,95MM,135MM). */
export function Breakable({ text }: { text: string }) {
  const parts = text.split(/(?<=[,/])/);
  return <>{parts.map((p, i) => <span key={i}>{p}{i < parts.length - 1 && <wbr />}</span>)}</>;
}

/** Page title. marine: shown on a compact marine banner (main section pages; detail pages and forms stay plain). */
export function PageHeader({ title, subtitle, actions, marine = false }: { title: string; subtitle?: ReactNode; actions?: ReactNode; marine?: boolean }) {
  const header = (
    <header className="page-header">
      <div>
        <h1><Breakable text={title} /></h1>
        {subtitle && <p className="muted">{subtitle}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
  return marine ? <MarineBanner compact>{header}</MarineBanner> : header;
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

export type MenuItem = { key: string; label: string; ariaLabel?: string; to?: string; onSelect?: () => void };

/** Overflow menu for secondary actions: a button that opens a list of menu items. Arrow keys move between items,
 *  Escape or a click outside closes it and returns focus to the button. Items are links or buttons as before. */
export function ActionMenu({ label, items }: { label: string; items: MenuItem[] }) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const id = useId();
  useEffect(() => {
    if (!open) return undefined;
    wrap.current?.querySelector<HTMLElement>("[role=menuitem]")?.focus();
    const away = (e: MouseEvent) => { if (!wrap.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);
  function onKey(e: KeyboardEvent) {
    const all = [...(wrap.current?.querySelectorAll<HTMLElement>("[role=menuitem]") ?? [])];
    const i = all.indexOf(document.activeElement as HTMLElement);
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); setOpen(false); button.current?.focus(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); all[(i + 1) % all.length]?.focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); all[(i - 1 + all.length) % all.length]?.focus(); }
    else if (e.key === "Home") { e.preventDefault(); all[0]?.focus(); }
    else if (e.key === "End") { e.preventDefault(); all[all.length - 1]?.focus(); }
    else if (e.key === "Tab") setOpen(false);
  }
  if (!items.length) return null;
  return (
    <div className="action-menu" ref={wrap} onKeyDown={onKey}>
      <button ref={button} type="button" className="btn btn-ghost icon-only" aria-label={label} title={label} aria-haspopup="menu"
        aria-expanded={open} aria-controls={open ? id : undefined} onClick={() => setOpen((o) => !o)}>
        <Icon name="more" />
      </button>
      {open && (
        <div className="menu" role="menu" id={id} aria-label={label}>
          {items.map((it) => it.to
            ? <Link key={it.key} role="menuitem" className="menu-item" to={it.to} aria-label={it.ariaLabel} onClick={() => setOpen(false)}>{it.label}</Link>
            : <button key={it.key} type="button" role="menuitem" className="menu-item" aria-label={it.ariaLabel}
                onClick={() => { setOpen(false); it.onSelect?.(); }}>{it.label}</button>)}
        </div>
      )}
    </div>
  );
}

/** Long free text in a table cell: the first lines, with a toggle to read the rest (keyboard-operable). */
export function Clamp({ children, lines = 3 }: { children: ReactNode; lines?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [long, setLong] = useState(false);
  useLayoutEffect(() => {
    const el = ref.current;
    if (el && !open) setLong(el.scrollHeight > el.clientHeight + 2);
  }, [children, open]);
  return (
    <>
      <div ref={ref} className={open ? "clamp-open" : "clamp"} style={{ WebkitLineClamp: open ? undefined : lines }}>{children}</div>
      {(long || open) && <button type="button" className="link-btn small" aria-expanded={open} onClick={() => setOpen((o) => !o)}>{open ? "Show less" : "Show more"}</button>}
    </>
  );
}

export function Empty({ children, icon = "inbox" }: { children: ReactNode; icon?: IconName }) {
  return (
    <div className="empty">
      <span className="empty-icon" aria-hidden><Icon name={icon} /></span>
      <div>{children}</div>
    </div>
  );
}

/** Content-shaped placeholder while data loads (no layout jump); the text stays available to screen readers. */
export function Loading({ variant = "lines" }: { variant?: "lines" | "page" | "cards" }) {
  return (
    <div className="loading" aria-live="polite" aria-busy="true">
      <span className="sr-only">Loading…</span>
      {variant === "page" && <span className="skeleton skeleton-title" />}
      {variant !== "lines" && (
        <div className="skeleton-grid">{[0, 1, 2, 3].map((i) => <span key={i} className="skeleton skeleton-card" />)}</div>
      )}
      {[92, 78, 85, 60].map((w, i) => <span key={i} className="skeleton skeleton-line" style={{ width: `${w}%` }} />)}
    </div>
  );
}

export function Skeleton({ width = "100%", height = 12 }: { width?: number | string; height?: number }) {
  return <span className="skeleton" style={{ width, height }} aria-hidden />;
}

/** A long technical value cut to one line, with the full value as a tooltip. */
export function Truncate({ text, max = 280 }: { text: string; max?: number }) {
  return <span className="truncate" style={{ maxWidth: max }} title={text}>{text}</span>;
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

/** A gated action shown disabled with its reason. `compact` (page headers, where a notice already explains the gate)
 * keeps the reason as the tooltip and accessible description instead of a text column under the button. */
export function DisabledAction({ label, reason, compact }: { label: string; reason: string; compact?: boolean }) {
  const id = useId();
  return (
    <span className={`disabled-action${compact ? " is-compact" : ""}`} title={reason}>
      <button type="button" className="btn" disabled aria-describedby={id}>
        <Icon name="lock" size="sm" />
        {label}
      </button>
      <span id={id} className={compact ? "sr-only" : "muted small"}>{reason}</span>
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
      <Icon name="arrowLeft" size="sm" /> {children}
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
