/** In-app notifications: bell with unread count, list with links, read tracking. Polls while the app is open. */
import type { NotificationList } from "@passport/api-types";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Icon } from "./icons";
import { formatDate } from "./ui";

export default function NotificationBell() {
  const navigate = useNavigate();
  const list = useApi<NotificationList>("/notifications/");
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const t = window.setInterval(() => void list.reload(), 15000);
    return () => window.clearInterval(t);
  }, [list.reload]);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    window.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", esc);
    };
  }, [open]);

  const unread = list.data?.unread ?? 0;
  return (
    <div className="bell" ref={box}>
      <button type="button" className="icon-btn bell-button" aria-label={`Notifications, ${unread} unread`} aria-expanded={open}
        onClick={() => { setOpen((o) => !o); void list.reload(); }}>
        <Icon name="bell" />
        {unread > 0 && <span className="bell-count" data-testid="bell-count">{unread > 99 ? "99+" : unread}</span>}
      </button>
      {open && (
        <div className="bell-panel" role="dialog" aria-label="Notifications">
          <div className="bell-head">
            <strong>Notifications</strong>
            {unread > 0 && (
              <button type="button" className="link-button small" onClick={async () => { await api("/notifications/read-all/", { method: "POST" }); await list.reload(); }}>
                Mark all as read
              </button>
            )}
          </div>
          {list.data?.results.length ? (
            <ul className="bell-list">
              {list.data.results.map((n) => (
                <li key={n.id} className={n.read_at ? "" : "is-unread"}>
                  <button type="button" onClick={async () => {
                    if (!n.read_at) await api(`/notifications/${n.id}/read/`, { method: "POST" });
                    setOpen(false);
                    await list.reload();
                    if (n.link) navigate(n.link);
                  }}>
                    <span className="bell-title">{n.title}</span>
                    {n.body && <span className="bell-body">{n.body}</span>}
                    <span className="muted small">{n.organisation_name} · {formatDate(n.created_at)}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : <p className="muted small bell-empty">No notifications yet.</p>}
        </div>
      )}
    </div>
  );
}
