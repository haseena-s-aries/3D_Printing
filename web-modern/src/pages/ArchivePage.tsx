/**
 * Archive (Aries Admin or Manager): the spare parts and requests that were archived in any company, with Restore.
 * Archiving hides an item everywhere without erasing anything (decision of 19 Nov 2026). Whole test companies are
 * removed from Clients instead.
 */
import { useState } from "react";

import { api } from "../api/client";
import { useApi } from "../api/useApi";
import { Badge, Card, Empty, ErrorNotice, Loading, Notice, PageHeader, formatDate } from "../components/ui";

type Row = { kind: "part" | "request"; id: string; client_id: string; client_name: string; title: string; archived_at: string; archived_by: string };

export default function ArchivePage() {
  const list = useApi<Row[]>("/operator/archive/");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState("");
  const rows = list.data ?? [];

  async function restore(r: Row) {
    setBusy(r.id);
    setError(null);
    setDone("");
    try {
      await api("/operator/archive/", { body: { kind: r.kind, client_id: r.client_id, id: r.id } });
      setDone(`${r.title} restored.`);
      await list.reload();
    } catch (err) {
      setError(err);
    } finally {
      setBusy("");
    }
  }

  return (
    <>
      <PageHeader title="Archive" subtitle="Spare parts and requests that were archived. Nothing is erased; restore an item to bring it back." />
      {done && <Notice kind="success">{done}</Notice>}
      <ErrorNotice error={list.error ?? error} />
      <Card>
        {list.loading && !list.data ? <Loading /> : rows.length === 0 ? <Empty icon="inbox">Nothing is archived.</Empty> : (
          <div className="table-scroll">
            <table className="table" aria-label="Archived items">
              <thead><tr><th>Item</th><th>Company</th><th>Archived</th><th /></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={`${r.kind}-${r.id}`}>
                    <td><Badge>{r.kind === "part" ? "Spare part" : "Request"}</Badge> {r.title}</td>
                    <td>{r.client_name}</td>
                    <td>{formatDate(r.archived_at)}<div className="muted small">{r.archived_by}</div></td>
                    <td><button type="button" className="btn btn-small" disabled={busy === r.id} aria-busy={busy === r.id} onClick={() => void restore(r)}>Restore</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
