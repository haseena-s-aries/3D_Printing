/**
 * Archive from a list (Aries Admin): a spare part (with its passport) or a client request is hidden everywhere without
 * opening the record. Nothing is erased; it is restored from the Archive screen. The server keeps the same rules as on the
 * record's own page (open requests, a published passport or an order in production block it) and its reason is shown.
 */
import { useState } from "react";

import { ApiError, api } from "../api/client";
import { useToast } from "./theme";

/** `id`: the spare part's id (with `clientId`), or the request's id in the Aries incoming queue. */
export function ArchiveButton({ kind, clientId = "", id, title, onDone }: { kind: "part" | "request"; clientId?: string; id: string; title: string;
  onDone: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const what = kind === "part" ? `${title} and its passport are hidden everywhere and the part number becomes free`
    : `${title} is hidden for the client and for Aries`;
  async function run() {
    if (!window.confirm(`Archive ${title}? ${what}. Nothing is erased; you can restore it from the Archive.`)) return;
    setBusy(true);
    try {
      if (kind === "request") await api(`/operator/requests/${id}/archive/`, { body: {} });
      else await api("/operator/archive/", { body: { action: "archive", kind, client_id: clientId, id } });
      toast(`${title} archived.`);
      onDone();
    } catch (e) {
      window.alert(e instanceof ApiError ? e.message : "Archiving failed. Please try again.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <button type="button" className="btn btn-small btn-ghost btn-archive" disabled={busy} aria-busy={busy} onClick={() => void run()}
      aria-label={`Archive ${title}`}>Archive</button>
  );
}
