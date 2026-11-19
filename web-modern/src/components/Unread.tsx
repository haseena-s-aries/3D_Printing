/**
 * Unread notifications behind the menu (sidebar counts, "New" rows in lists). One shared source, kept in the layout:
 * refreshed every 15 seconds, on every navigation and whenever the bell marks something read. Opening an item marks its
 * notifications read (the page's path equals the notification's link), so its count and highlight clear.
 */
import { createContext, useContext, useEffect, useMemo } from "react";
import { useLocation } from "react-router-dom";

import { api } from "../api/client";
import { useApi } from "../api/useApi";

export const NOTIFICATIONS_CHANGED = "notifications-changed";

export interface Unread {
  /** an unread notification points exactly at this link */
  has: (link: string) => boolean;
  /** unread notifications in a section: the link equals `section` or lies below it */
  count: (section: string) => number;
  /** the ids at the end of the links below `section` (/incoming/<id> -> <id>) */
  ids: (section: string) => string[];
}

const EMPTY: Unread = { has: () => false, count: () => 0, ids: () => [] };
const UnreadContext = createContext<Unread>(EMPTY);
export const UnreadProvider = UnreadContext.Provider;
export const useUnread = () => useContext(UnreadContext);

const inSection = (link: string, section: string) => link === section || link.startsWith(`${section}/`);

export function useUnreadState(enabled: boolean): Unread {
  const { pathname } = useLocation();
  const list = useApi<{ id: string; link: string }[]>(enabled ? "/notifications/unread/" : null);
  const rows = list.data ?? [];
  const { reload } = list;

  useEffect(() => {
    if (!enabled) return;
    const t = window.setInterval(() => void reload(), 15000);
    const onChange = () => void reload();
    window.addEventListener(NOTIFICATIONS_CHANGED, onChange);
    return () => { window.clearInterval(t); window.removeEventListener(NOTIFICATIONS_CHANGED, onChange); };
  }, [enabled, reload]);

  // opening an item reads its notifications; other pages just refresh the counts
  useEffect(() => {
    if (!enabled) return;
    const here = rows.filter((n) => n.link === pathname);
    if (!here.length) { void reload(); return; }
    void Promise.all(here.map((n) => api(`/notifications/${n.id}/read/`, { method: "POST" }).catch(() => undefined)))
      .then(() => { void reload(); window.dispatchEvent(new Event(NOTIFICATIONS_CHANGED)); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname, enabled, list.data]);

  return useMemo<Unread>(() => ({
    has: (link) => rows.some((n) => n.link === link),
    count: (section) => rows.filter((n) => inSection(n.link, section)).length,
    ids: (section) => rows.filter((n) => n.link.startsWith(`${section}/`)).map((n) => n.link.slice(section.length + 1).split(/[/?#]/)[0]),
  }), [rows]);
}

/** Marks a list row that has something new for the person (an unread notification). */
export function NewTag() {
  return <span className="new-tag">New</span>;
}
