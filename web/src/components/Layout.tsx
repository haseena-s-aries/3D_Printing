import type { MembershipSummary } from "@passport/api-types";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import NotificationBell from "./NotificationBell";
import { roleLabel } from "./roles";

interface NavItem {
  to: string;
  label: string;
  capability?: string;
  operatorOnly?: boolean;
  /** Client-inventory screens: hidden in the Platform Operator organisation, which holds no client records. */
  clientOrgOnly?: boolean;
}

const NAV: NavItem[] = [
  { to: "/", label: "Dashboard" },
  { to: "/registrations", label: "Registrations", capability: "registrations.review", operatorOnly: true },
  { to: "/clients", label: "Clients", capability: "clients.view", operatorOnly: true },
  // Aries Admin: audited administrative summaries across client companies (no record access, OQ-37)
  { to: "/admin/inventory", label: "Digital inventory", capability: "inventory.admin_overview", operatorOnly: true },
  { to: "/parts", label: "Digital inventory", capability: "parts.view", clientOrgOnly: true },
  { to: "/inventory-import", label: "Inventory import", capability: "inventory.import", clientOrgOnly: true },
  { to: "/projects", label: "Projects", capability: "projects.view", clientOrgOnly: true },
  { to: "/passports", label: "Digital passports", capability: "passports.view", clientOrgOnly: true },
  { to: "/requests", label: "My requests", capability: "requests.view" },
  { to: "/incoming", label: "Incoming requests", capability: "requests.handle" },
  { to: "/edit-requests", label: "Edit requests", capability: "edits.request" },
  { to: "/users", label: "Users", capability: "users.view" },
  { to: "/audit", label: "Audit trail", capability: "audit.view" },
];

export function visibleNav(can: (c: string) => boolean, isOperator: boolean): NavItem[] {
  return NAV.filter((n) => (!n.capability || can(n.capability)) && (!n.operatorOnly || isOperator) && (!n.clientOrgOnly || !isOperator));
}

const DETAIL: [RegExp, string, string][] = [
  [/^\/parts\/[^/]+/, "Digital inventory", "Spare part"],
  [/^\/passports\/[^/]+/, "Digital passports", "Passport"],
  [/^\/requests\/new-scan/, "My requests", "Request 3D scanning"],
  [/^\/requests\/[^/]+/, "My requests", "Request"],
  [/^\/incoming\/[^/]+/, "Incoming requests", "Request"],
  [/^\/edit-requests\/[^/]+/, "Edit requests", "Edit request"],
  [/^\/inventory-import\/[^/]+/, "Inventory import", "Import"],
  [/^\/clients\/[^/]+/, "Clients", "Client management"],
  [/^\/files\/[^/]+/, "Digital inventory", "3D model"],
];

/** Breadcrumb trail: organisation › section › item. */
export function breadcrumbs(pathname: string, organisation: string): string[] {
  for (const [re, section, item] of DETAIL) if (re.test(pathname)) return [organisation, section, item];
  const nav = NAV.filter((n) => n.to !== "/" && pathname.startsWith(n.to)).sort((a, b) => b.to.length - a.to.length)[0];
  return [organisation, nav ? nav.label : "Dashboard"];
}

/** Aries staff keep the Aries portal identity even while working inside a client organisation (UX-2, CN-002). */
export function portalLabel(tenantKind: string, role: string): string {
  if (tenantKind === "operator") return "Aries portal";
  return role.startsWith("operator_") ? "Aries portal · client workspace" : "Client portal";
}

function OrganisationSwitcher() {
  const { session, switchTenant } = useAuth();
  const navigate = useNavigate();
  const memberships = useApi<MembershipSummary[]>(session ? "/auth/memberships/" : null, { query: { m: session?.membership.id } });
  const [error, setError] = useState<unknown>(null);
  if (!session || !memberships.data || memberships.data.length < 2) return null;
  return (
    <label className="org-switcher">
      <span className="muted small">Change client</span>
      <select
        aria-label="Switch organisation"
        value={session.tenant.slug}
        onChange={async (e) => {
          setError(null);
          try {
            await switchTenant(e.target.value);
            navigate("/", { replace: true }); // the current page may not exist in the other organisation
          } catch (err) {
            setError(err);
          }
        }}
      >
        {memberships.data.map((m) => (
          <option key={m.tenant.slug} value={m.tenant.slug}>
            {m.tenant.name}
          </option>
        ))}
      </select>
      {error ? <span className="small error-text">Switch failed</span> : null}
    </label>
  );
}

export default function Layout({ children }: { children?: ReactNode }) {
  const { session, can, logout } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const location = useLocation();
  if (!session) return null;
  const crumbs = breadcrumbs(location.pathname, session.tenant.name);
  const isOperator = session.tenant.kind === "operator";
  const portal = portalLabel(session.tenant.kind, session.membership.role);
  const operatorStaff = session.membership.role.startsWith("operator_");
  return (
    <div className={`shell ${open ? "nav-open" : ""}`}>
      <aside className="sidebar" aria-label="Main navigation">
        <div className="brand">
          <span className="brand-mark" aria-hidden>
            DP
          </span>
          <div>
            <div className="brand-name">Digital Passport</div>
            <div className="brand-sub">{portal}</div>
          </div>
        </div>
        <nav>
          {visibleNav(can, isOperator).map((n) => (
            <NavLink key={n.to} to={n.to} end={n.to === "/"} onClick={() => setOpen(false)}>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot muted small">
          {session.tenant.hosting_model === "dedicated" ? "Dedicated deployment" : "Shared platform"}
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <button type="button" className="btn btn-ghost menu-toggle" onClick={() => setOpen((o) => !o)} aria-label="Toggle navigation">
            ☰
          </button>
          <div className={`topbar-tenant ${isOperator ? "is-operator" : "is-client"}`} data-testid="working-in">
            <span className="working-label">{isOperator ? "Aries workspace" : operatorStaff ? "Working in client" : "Organisation"}</span>
            <strong className="working-name">{session.tenant.name}</strong>
            <span className="muted small working-role" data-testid="working-role">{roleLabel(session.membership.role)}</span>
          </div>
          <OrganisationSwitcher />
          <NotificationBell />
          <div className="topbar-user">
            <span className="muted small">{session.user.email}</span>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={async () => {
                await logout();
                navigate("/login");
              }}
            >
              Sign out
            </button>
          </div>
        </header>
        <SwitchNotice name={session.tenant.name} membership={session.membership.id} />
        <main className="content" key={session.membership.id /* every page reloads for the selected organisation */}>
          <nav className="crumbs" aria-label="Breadcrumb">
            {crumbs.map((c, i) => <span key={i} aria-current={i === crumbs.length - 1 ? "page" : undefined}>{c}</span>)}
          </nav>
          {children ?? <Outlet />}
        </main>
      </div>
      {open && <div className="scrim" onClick={() => setOpen(false)} aria-hidden />}
    </div>
  );
}

/** Short confirmation after the organisation changes, so nobody keeps working in the wrong client by mistake. */
function SwitchNotice({ name, membership }: { name: string; membership: string }) {
  const first = useRef(membership);
  const [shown, setShown] = useState(false);
  useEffect(() => {
    if (membership === first.current) return;
    first.current = membership;
    setShown(true);
    const t = window.setTimeout(() => setShown(false), 5000);
    return () => window.clearTimeout(t);
  }, [membership]);
  return shown ? <div className="switch-notice" role="status">Now working in <strong>{name}</strong></div> : null;
}
