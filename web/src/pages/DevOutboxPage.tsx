/**
 * Development outbox (DEBUG only): emails written by the file email backend. Nothing is delivered; opening a link here is
 * exactly what the recipient would do with the real email, so verification still requires the person to act.
 */
import { useEffect, useState, type ReactNode } from "react";

import { api } from "../api/client";
import { PublicShell } from "../components/PublicShell";
import { ErrorNotice, Loading } from "../components/ui";

interface OutboxMessage {
  id: string;
  to: string;
  subject: string;
  date: string;
  body: string;
}

/** Plain text with http(s) links made clickable (text stays text; no HTML is interpreted). */
function Linkified({ text }: { text: string }) {
  const parts: ReactNode[] = [];
  text.split(/(https?:\/\/\S+)/g).forEach((chunk, i) => {
    if (/^https?:\/\//.test(chunk)) {
      const local = chunk.replace(/^https?:\/\/[^/]+/, "");
      parts.push(<a key={i} href={local || chunk}>{chunk}</a>);
    } else {
      parts.push(chunk);
    }
  });
  return <pre className="outbox-body">{parts}</pre>;
}

export default function DevOutboxPage() {
  const [data, setData] = useState<{ notice: string; messages: OutboxMessage[] } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const load = () => api<{ notice: string; messages: OutboxMessage[] }>("/public/dev-outbox/").then(setData).catch(setError);
  useEffect(() => {
    void load();
  }, []);
  return (
    <PublicShell title="Development outbox" subtitle="Local development only — no email is delivered" wide>
      <ErrorNotice error={error} />
      {!data && !error && <Loading />}
      {data && (
        <>
          <p className="notice notice-warning small">{data.notice} This page does not exist outside the development environment.</p>
          <p><button type="button" className="btn btn-small" onClick={() => void load()}>Refresh</button></p>
          {data.messages.length === 0 ? <p className="muted">No messages yet.</p> : (
            <ul className="list outbox-list" aria-label="Outbox messages">
              {data.messages.map((m, i) => (
                <li key={`${m.id}-${i}`}>
                  <div><strong>{m.subject}</strong></div>
                  <div className="muted small">To {m.to} · {m.date}</div>
                  <Linkified text={m.body} />
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </PublicShell>
  );
}
