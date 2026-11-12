import type { MembershipSummary } from "@passport/api-types";
import { Suspense, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import AdminNav, { useEnterContext, useIsSuperAdmin } from "./AdminNav";
import { Icon, type IconName } from "./icons";
import NotificationBell from "./NotificationBell";
import { roleLabel } from "./roles";
import { ThemeToggle, useAppKeyboard } from "./theme";
import { Loading } from "./ui";
import ariesMark from "../assets/aries-mark.png";
import { ariesLogo } from "./MarineHero";

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
  // Client Administrator: what the company shares with Aries (Aries Admin inventory thumbnails, default not allowed)
  { to: "/company/data-sharing", label: "Data sharing", capability: "files.admin_thumbnail_consent", clientOrgOnly: true },
  // QA inside a client company (Aries Engineers with QA permission; legacy Aries QA): photo-origin claims awaiting an independent decision
  { to: "/origin-claims", label: "Photo origin queue", capability: "files.origin_confirm", clientOrgOnly: true },
  // Aries Admin and Aries Engineers with contract review permission (legacy Aries QA): contract authorizations for Admin thumbnails
  { to: "/thumbnail-contracts", label: "Thumbnail contracts", capability: "contracts.thumbnail_view", operatorOnly: true },
];

export function visibleNav(can: (c: string) => boolean, isOperator: boolean): NavItem[] {
  return NAV.filter((n) => (!n.capability || can(n.capability)) && (!n.operatorOnly || isOperator) && (!n.clientOrgOnly || !isOperator));
}

/** Presentation of the navigation: group and icon per destination (the items and their visibility come from NAV). */
const GROUPS: [string, string][] = [["overview", "Overview"], ["inventory", "Inventory & passports"], ["ai", "Spare Parts Intelligence"],
  ["requests", "Requests"], ["admin", "Administration"]];
const META: Record<string, [string, IconName]> = {
  "/": ["overview", "dashboard"], "/registrations": ["admin", "inbox"], "/clients": ["admin", "building"],
  "/admin/inventory": ["inventory", "boxes"], "/parts": ["inventory", "boxes"], "/inventory-import": ["inventory", "upload"],
  "/projects": ["inventory", "folder"], "/passports": ["inventory", "passport"], "/requests": ["requests", "message"],
  "/incoming": ["requests", "incoming"], "/edit-requests": ["requests", "edit"], "/users": ["admin", "users"], "/audit": ["admin", "shield"],
  "/company/data-sharing": ["admin", "lock"], "/origin-claims": ["inventory", "review"], "/thumbnail-contracts": ["admin", "lock"],
};
/** The AI assessment workflow (CN-007) lives in tabs of Inventory import; the sidebar links to it directly. */
const AI_LINKS: { to: string; tab: string; label: string; icon: IconName }[] = [
  { to: "/inventory-import?tab=intelligence", tab: "intelligence", label: "Part intelligence", icon: "spark" },
  { to: "/inventory-import?tab=assessment", tab: "assessment", label: "Quarterly assessment", icon: "chart" },
];

const DETAIL: [RegExp, string, string][] = [
  [/^\/attention/, "Dashboard", "Needs attention"],
  [/^\/ai\/my-parts\/[^/]+/, "My parts intelligence", "Part"],
  [/^\/ai\/my-parts/, "Spare Parts Intelligence", "My parts intelligence"],
  [/^\/ai\/management/, "Spare Parts Intelligence", "AI management"],
  [/^\/ai\/sharing/, "Spare Parts Intelligence", "Client sharing"],
  [/^\/parts\/[^/]+\/photos\//, "Digital inventory", "Photo origin"],
  [/^\/parts\/[^/]+/, "Digital inventory", "Spare part"],
  [/^\/thumbnail-contracts\/[^/]+/, "Thumbnail contracts", "Company"],
  [/^\/admin\/companies/, "Aries Admin", "Choose a company"],
  [/^\/admin\/settings/, "Aries Admin", "Platform settings"],
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
  const memberships = useApi<MembershipSummary[]>(session ? "/auth/memberships/" : null, { query: { m: session?.membership.id, counts: "0" } });
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

const RAIL_KEY = "dp-rail";

function useMedia(query: string): boolean {
  const [match, setMatch] = useState(() => typeof window !== "undefined" && !!window.matchMedia?.(query).matches);
  useEffect(() => {
    const mq = window.matchMedia?.(query);
    if (!mq) return undefined;
    const on = () => setMatch(mq.matches);
    on();
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [query]);
  return match;
}

/** Phones show `table.table-stack` rows as cards: each cell gets its column name as a label (data-label from the header). */
function useStackTables() {
  useEffect(() => {
    const label = () => {
      for (const table of document.querySelectorAll<HTMLTableElement>("table.table-stack")) {
        const heads = [...table.querySelectorAll("thead th")].map((th) => (th.textContent ?? "").trim());
        for (const row of table.querySelectorAll("tbody tr")) {
          [...row.children].forEach((td, i) => { if (heads[i] && td.getAttribute("data-label") !== heads[i]) td.setAttribute("data-label", heads[i]); });
        }
      }
    };
    label();
    const obs = new MutationObserver(label);
    obs.observe(document.body, { childList: true, subtree: true });
    return () => obs.disconnect();
  }, []);
}
const initials = (email: string) => email.split("@")[0].split(/[._-]/).filter(Boolean).slice(0, 2).map((s) => s[0]!.toUpperCase()).join("") || "?";

export default function Layout({ children }: { children?: ReactNode }) {
  const { session, can, logout } = useAuth();
  const navigate = useNavigate();
  const superAdmin = useIsSuperAdmin();
  const [open, setOpen] = useState(false);
  // Tablets (761–1180 px) start with the icon rail so content gets the width; an explicit choice is remembered per size class.
  const tablet = useMedia("(min-width: 761px) and (max-width: 1180px)");
  const railKey = tablet ? `${RAIL_KEY}-tablet` : RAIL_KEY;
  const [pref, setPref] = useState<Record<string, boolean | null>>(() => {
    const read = (k: string) => { try { const v = window.localStorage.getItem(k); return v === null ? null : v === "1"; } catch { return null; } };
    return { [RAIL_KEY]: read(RAIL_KEY), [`${RAIL_KEY}-tablet`]: read(`${RAIL_KEY}-tablet`) };
  });
  const rail = pref[railKey] ?? tablet;
  const location = useLocation();
  useAppKeyboard();
  useStackTables();
  useEffect(() => { setOpen(false); }, [location.pathname, location.search]);
  useEffect(() => {
    if (!open) return undefined;
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [open]);
  if (!session) return null;
  const crumbs = breadcrumbs(location.pathname, session.tenant.name);
  const isOperator = session.tenant.kind === "operator";
  const operatorStaff = session.membership.role.startsWith("operator_");
  const items = visibleNav(can, isOperator);
  const tab = new URLSearchParams(location.search).get("tab") ?? "";
  const aiTab = location.pathname === "/inventory-import" && AI_LINKS.some((a) => a.tab === tab);
  const showAi = !isOperator && can("inventory.import") && can("intelligence.view");
  // role-specific Spare Parts Intelligence pages (CN-007): Aries Admin, engineer client sharing, client workspace
  const roleAi: [string, string, IconName][] = [
    ...(can("ai.management") ? [["/ai/management", "AI management", "gauge"] as [string, string, IconName]] : []),
    ...(can("ai.share") ? [["/ai/sharing", "Client sharing", "eye"] as [string, string, IconName]] : []),
    ...(can("ai.workspace") ? [["/ai/my-parts", "My parts intelligence", "spark"] as [string, string, IconName]] : []),
  ];
  const sectionHref = (label: string) => items.find((n) => n.label === label)?.to;
  const toggleRail = () => {
    const next = !rail;
    try { window.localStorage.setItem(railKey, next ? "1" : "0"); } catch { /* none */ }
    setPref((p) => ({ ...p, [railKey]: next }));
  };
  const navLink = (to: string, label: string, icon: IconName, active?: boolean) => (
    <NavLink key={to} to={to} end={to === "/"} title={rail ? label : undefined}
      className={({ isActive }) => ((active ?? isActive) ? "active" : "")}>
      <Icon name={icon} /><span className="nav-label">{label}</span>
    </NavLink>
  );
  return (
    <div className={`shell ${open ? "nav-open" : ""} ${rail ? "is-rail" : ""}`}>
      <a className="skip-link" href="#main-content">Skip to content</a>
      <aside className="sidebar" aria-label="Main navigation">
        <div className="brand brand-aries">
          <img className="brand-logo" src={ariesLogo} alt="Aries Marine & Engg. Services" />
          <img className="brand-logo-mark" src={ariesMark} alt="Aries" />
          <div className="brand-text">
            <div className="brand-name">Digital Passport Platform</div>
            <div className="brand-sub">Marine 3D Printing</div>
          </div>
        </div>
        {superAdmin ? <AdminNav rail={rail} /> : <nav>
          {GROUPS.map(([g, title]) => {
            const links = g === "ai"
              ? [...(showAi ? AI_LINKS.map((a) => navLink(a.to, a.label, a.icon, aiTab && tab === a.tab)) : []),
                  ...roleAi.map(([to, label, icon]) => navLink(to, label, icon, location.pathname.startsWith(to)))]
              : [...items.filter((n) => (META[n.to]?.[0] ?? "overview") === g)
                  .map((n) => navLink(n.to, n.label, META[n.to]?.[1] ?? "dashboard", n.to === "/inventory-import" ? !aiTab && location.pathname.startsWith("/inventory-import") : undefined)),
                  // the user's own work queue, next to the dashboard (every role; the page shows what applies)
                  ...(g === "overview" ? [navLink("/attention", "Needs attention", "bell")] : [])];
            return links.length ? (
              <div key={g} className="nav-group">
                <div className="nav-group-label" aria-hidden>{title}</div>
                {links}
              </div>
            ) : null;
          })}
        </nav>}
        <div className="sidebar-foot">
          <span className="sidebar-foot-text">{session.tenant.hosting_model === "dedicated" ? "Dedicated deployment" : "Shared platform"}</span>
          <button type="button" className="rail-toggle" onClick={toggleRail} aria-label={rail ? "Expand navigation" : "Collapse navigation"}
            title={rail ? "Expand navigation" : "Collapse navigation"}>
            <Icon name="panel" size="sm" />
          </button>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <button type="button" className="icon-btn menu-toggle" onClick={() => setOpen((o) => !o)} aria-label="Toggle navigation" aria-expanded={open}>
            <Icon name="menu" />
          </button>
          <div className={`topbar-tenant ${isOperator ? "is-operator" : "is-client"}`} data-testid="working-in">
            <span className="tenant-dot" aria-hidden />
            <span className="working-label">{isOperator ? "Aries workspace" : operatorStaff ? "Working in client" : "Organisation"}</span>
            <strong className="working-name">{session.tenant.name}</strong>
            <span className="muted small working-role" data-testid="working-role">{roleLabel(session.membership.role)}</span>
          </div>
          <OrganisationSwitcher />
          <div className="topbar-actions">
            <ThemeToggle />
            <NotificationBell />
          </div>
          <div className="topbar-user">
            <span className="avatar" aria-hidden>{initials(session.user.email)}</span>
            <span className="muted small user-email" title={session.user.email}>{session.user.email}</span>
            <button
              type="button"
              className="btn btn-ghost btn-small"
              aria-label="Sign out"
              onClick={async () => {
                await logout();
                navigate("/login");
              }}
            >
              <Icon name="logout" size="sm" /><span className="signout-text">Sign out</span>
            </button>
          </div>
        </header>
        <SwitchNotice name={session.tenant.name} membership={session.membership.id} />
        {session.admin_access?.admin_workspace && <AdminAccessBanner company={session.tenant.name} decision={session.admin_access.file_decision ?? ""} />}
        <main className="content" id="main-content" tabIndex={-1} key={session.membership.id /* every page reloads for the selected organisation */}>
          {/* client management pages carry their own, more specific trail (Client organisations › company › tab) */}
          {!/^\/clients\/[^/]+/.test(location.pathname) && <nav className="crumbs" aria-label="Breadcrumb">
            {crumbs.map((c, i) => {
              const last = i === crumbs.length - 1;
              const href = i === 0 ? "/" : !last ? sectionHref(c) : undefined;
              return href ? <Link key={i} to={href}>{c}</Link> : <span key={i} aria-current={last ? "page" : undefined}>{c}</span>;
            })}
          </nav>}
          {children ?? <Suspense fallback={<Loading variant="page" />}><Outlet /></Suspense>}
        </main>
      </div>
      {open && <div className="scrim" onClick={() => setOpen(false)} aria-hidden />}
    </div>
  );
}

/** Aries Admin inside a client company: administrative access, clearly not engineering sign-off; file content status. */
function AdminAccessBanner({ company, decision }: { company: string; decision: string }) {
  const enter = useEnterContext();
  const location = useLocation();
  const { session } = useAuth();
  const aries = session?.admin_access?.aries_slug;
  return (
    <div className="admin-access-banner" role="note" data-testid="admin-access-banner">
      <Icon name="shield" size="sm" />
      <span><strong>Aries Admin access in {company}.</strong> Every action is recorded in the company's audit trail. Independent engineering
        sign-off, passport approval and manufacturing release are not part of this access. Confidential files:{" "}
        {decision ? <>open under {decision}.</> : <>closed (no documented authorization decision).</>}</span>
      <Link className="btn btn-small btn-ghost" to={`/admin/companies?next=${encodeURIComponent(location.pathname.startsWith("/parts/") || location.pathname.startsWith("/passports/") ? "/parts" : location.pathname + location.search)}`}>Change company</Link>
      {aries && <button type="button" className="btn btn-small btn-ghost" onClick={() => void enter(aries, "/admin/inventory")}>Back to Aries workspace</button>}
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
