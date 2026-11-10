/**
 * Aries Admin super-administrator workspace (ADMIN_WORKSPACE_ENABLED): one navigation for every module, whichever context
 * the Admin is in. Company modules run inside the selected client company (its own workspace, so tenant isolation and
 * row-level security apply); Aries modules run in the Aries organisation. A link to the other context switches it first
 * (company modules from the Aries workspace go through the company chooser). No module is duplicated: every entry opens
 * the existing page.
 */
import type { ReactNode } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import { Icon, type IconName } from "./icons";

type Item = { label: string; icon: IconName; group: string; aries?: string; company?: string; capability?: string };
const ITEMS: Item[] = [
  { label: "Dashboard", icon: "dashboard", group: "overview", aries: "/", company: "/" },
  { label: "Needs attention", icon: "bell", group: "overview", aries: "/attention", company: "/attention" },
  { label: "Digital inventory", icon: "boxes", group: "inventory", aries: "/admin/inventory", company: "/parts" },
  { label: "Digital passports", icon: "passport", group: "inventory", company: "/passports" },
  { label: "Projects", icon: "folder", group: "inventory", company: "/projects" },
  { label: "Inventory import", icon: "upload", group: "inventory", company: "/inventory-import" },
  { label: "Part intelligence", icon: "spark", group: "ai", company: "/inventory-import?tab=intelligence" },
  { label: "Manufacturing feasibility", icon: "gauge", group: "ai", company: "/inventory-import?tab=intelligence&view=feasibility" },
  { label: "Cost comparison", icon: "scale", group: "ai", company: "/inventory-import?tab=intelligence&view=cost" },
  { label: "AI recommendations", icon: "review", group: "ai", company: "/inventory-import?tab=intelligence&view=review" },
  { label: "Client sharing", icon: "eye", group: "ai", company: "/ai/sharing" },
  { label: "Quarterly assessment", icon: "chart", group: "ai", company: "/inventory-import?tab=assessment" },
  { label: "AI management", icon: "gauge", group: "ai", aries: "/ai/management" },
  { label: "Incoming requests", icon: "incoming", group: "requests", aries: "/incoming", company: "/incoming" },
  { label: "Manufacturing job sheets", icon: "file", group: "requests", aries: "/incoming?kind=manufacturing_request", company: "/incoming?kind=manufacturing_request" },
  { label: "Edit requests", icon: "edit", group: "requests", company: "/edit-requests" },
  { label: "Client management", icon: "building", group: "admin", aries: "/clients" },
  { label: "Registrations", icon: "inbox", group: "admin", aries: "/registrations" },
  { label: "Users and permissions", icon: "users", group: "admin", aries: "/users", company: "/users" },
  { label: "Audit history", icon: "shield", group: "admin", aries: "/audit", company: "/audit" },
  { label: "Thumbnail contracts", icon: "lock", group: "admin", aries: "/thumbnail-contracts", capability: "contracts.thumbnail_view" },
  { label: "Platform settings", icon: "layers", group: "admin", aries: "/admin/settings" },
];
const GROUPS: [string, string][] = [["overview", "Overview"], ["inventory", "Inventory & passports"], ["ai", "Spare Parts Intelligence"],
  ["requests", "Requests"], ["admin", "Administration"]];

/** True for the Aries Admin while super-administrator workspaces are on (either context). */
export function useIsSuperAdmin(): boolean {
  const { session } = useAuth();
  return !!session && session.membership.role === "operator_admin" && !!session.admin_access;
}

/** Switch to a company (or the Aries organisation) when needed, then open the path. */
export function useEnterContext() {
  const { session, switchTenant } = useAuth();
  const navigate = useNavigate();
  return async (slug: string, path: string) => {
    if (session?.tenant.slug !== slug) await switchTenant(slug);
    navigate(path);
  };
}

function useAriesSlug(): string | undefined {
  const { session } = useAuth();
  return session?.admin_access?.aries_slug || undefined;
}

function matches(href: string, pathname: string, search: string): boolean {
  const [path, query = ""] = href.split("?");
  if (path === "/" ? pathname !== "/" : !(pathname === path || pathname.startsWith(`${path}/`))) return false;
  const want = new URLSearchParams(query);
  const have = new URLSearchParams(search);
  if ([...want.keys()].length === 0) return !["intelligence", "assessment"].includes(have.get("tab") ?? "") && !have.get("kind");
  return [...want.entries()].every(([k, v]) => have.get(k) === v) && (want.has("view") || !have.get("view"));
}

export default function AdminNav({ rail }: { rail: boolean }) {
  const { session, can } = useAuth();
  const location = useLocation();
  const enter = useEnterContext();
  const ariesSlug = useAriesSlug();
  if (!session) return null;
  const inCompany = session.tenant.kind === "client";
  const link = (it: Item): ReactNode => {
    const here = inCompany ? it.company : it.aries;
    const label = <><Icon name={it.icon} /><span className="nav-label">{it.label}</span></>;
    if (here) {
      return (
        <NavLink key={it.label} to={here} end={here === "/"} title={rail ? it.label : undefined}
          className={() => (matches(here, location.pathname, location.search) ? "active" : "")}>{label}</NavLink>
      );
    }
    if (inCompany && it.aries) {  // an Aries module from inside a company: back to the Aries workspace first
      return (
        <a key={it.label} href={it.aries} title={rail ? it.label : undefined} aria-label={`${it.label} (Aries workspace)`}
          onClick={(e) => { e.preventDefault(); if (ariesSlug) void enter(ariesSlug, it.aries!); }}>
          {label}<span className="nav-context" title="Opens in the Aries workspace" aria-hidden><Icon name="route" size="sm" /></span>
        </a>
      );
    }
    const next = `/admin/companies?next=${encodeURIComponent(it.company!)}`;  // a company module from the Aries workspace
    return (
      <NavLink key={it.label} to={next} title={rail ? it.label : undefined} aria-label={`${it.label} (choose a company)`}
        className={() => (location.pathname === "/admin/companies" && new URLSearchParams(location.search).get("next") === it.company ? "active" : "")}>
        {label}<span className="nav-context" title="Choose a client company first" aria-hidden><Icon name="route" size="sm" /></span>
      </NavLink>
    );
  };
  return (
    <nav aria-label="Aries Admin workspace">
      {GROUPS.map(([g, title]) => {
        const links = ITEMS.filter((it) => it.group === g && (!it.capability || can(it.capability) || inCompany)).map(link);
        return links.length ? (
          <div key={g} className="nav-group">
            <div className="nav-group-label" aria-hidden>{title}</div>
            {links}
          </div>
        ) : null;
      })}
    </nav>
  );
}
