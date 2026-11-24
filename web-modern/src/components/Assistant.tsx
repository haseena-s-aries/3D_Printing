/**
 * The in-app assistant (chatbot), on every page: questions about request status, next steps, counts, records and how
 * to do things. Answers come from POST /assistant/ (rule-based, no external AI) with the same visibility as the screens;
 * the Aries Admin and Manager can search everything. The current page goes with each question, so "what's next?" on a
 * request needs no number. The conversation lasts while the app is open in this tab.
 */
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { api } from "../api/client";
import { Icon } from "./icons";

type Item = { title: string; subtitle: string; link: string | null };
type Answer = { answer: string; items: Item[]; links: { label: string; to: string }[]; suggestions: string[] };
type Message = { from: "me" | "bot"; text: string; items?: Item[]; links?: Answer["links"] };

export default function Assistant() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [full, setFull] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const end = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    input.current?.focus();
    if (messages.length) return;
    api<{ suggestions: string[]; full_access: boolean }>("/assistant/").then((r) => {
      setSuggestions(r.suggestions);
      setFull(r.full_access);
      setMessages([{ from: "bot", text: "Hello! Ask me about a request's status, what happens next, counts, or how to do something." }]);
    }).catch(() => setMessages([{ from: "bot", text: "The assistant is not available right now." }]));
  }, [open, messages.length]);

  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [messages, busy]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  async function send(text: string) {
    const message = text.trim();
    if (!message || busy) return;
    setDraft("");
    setMessages((m) => [...m, { from: "me", text: message }]);
    setBusy(true);
    try {
      const r = await api<Answer>("/assistant/", { body: { message, context: { path: pathname } } });
      setMessages((m) => [...m, { from: "bot", text: r.answer, items: r.items, links: r.links }]);
      if (r.suggestions.length) setSuggestions(r.suggestions);
    } catch {
      setMessages((m) => [...m, { from: "bot", text: "Sorry, something went wrong. Please try again." }]);
    } finally {
      setBusy(false);
    }
  }

  const submit = (e: FormEvent) => { e.preventDefault(); void send(draft); };

  return (
    <>
      <button type="button" className={`assistant-fab ${open ? "is-open" : ""}`} aria-expanded={open} aria-controls="assistant-panel"
        aria-label={open ? "Close the assistant" : "Open the assistant"} onClick={() => setOpen((o) => !o)}>
        <Icon name={open ? "close" : "message"} />
      </button>
      {open && (
        <section id="assistant-panel" className="assistant" role="dialog" aria-label="Assistant">
          <header className="assistant-head">
            <span className="assistant-avatar" aria-hidden="true"><Icon name="spark" /></span>
            <div>
              <strong>Assistant</strong>
              <div className="assistant-note">{full ? "Full access: every company's records" : "Answers from the records you can open"}</div>
            </div>
            <button type="button" className="icon-btn" aria-label="Close the assistant" onClick={() => setOpen(false)}><Icon name="close" size="sm" /></button>
          </header>
          <div className="assistant-body" aria-live="polite">
            {messages.map((m, i) => (
              <div key={i} className={`assistant-msg from-${m.from}`}>
                <div className="assistant-bubble">{m.text.split("\n").map((line, j) => <p key={j}>{line}</p>)}</div>
                {!!m.items?.length && (
                  <ul className="assistant-items">
                    {m.items.map((it, j) => (
                      <li key={j}>
                        {it.link ? (
                          <button type="button" onClick={() => navigate(it.link!)}>
                            <strong>{it.title}</strong>{it.subtitle && <span>{it.subtitle}</span>}<Icon name="chevron" size="sm" />
                          </button>
                        ) : <div><strong>{it.title}</strong>{it.subtitle && <span>{it.subtitle}</span>}</div>}
                      </li>
                    ))}
                  </ul>
                )}
                {!!m.links?.length && (
                  <div className="assistant-links">
                    {m.links.map((l) => <button key={l.to} type="button" className="btn btn-small" onClick={() => navigate(l.to)}>{l.label}</button>)}
                  </div>
                )}
              </div>
            ))}
            {busy && <div className="assistant-msg from-bot"><div className="assistant-bubble assistant-typing" aria-label="Thinking"><span /><span /><span /></div></div>}
            <div ref={end} />
          </div>
          {!!suggestions.length && (
            <div className="assistant-chips" aria-label="Suggested questions">
              {suggestions.map((s) => <button key={s} type="button" disabled={busy} onClick={() => void send(s)}>{s}</button>)}
            </div>
          )}
          <form className="assistant-form" onSubmit={submit}>
            <input ref={input} value={draft} maxLength={500} placeholder="Ask about a request, part, passport…" aria-label="Your question"
              onChange={(e) => setDraft(e.target.value)} />
            <button type="submit" className="btn btn-primary" disabled={busy || !draft.trim()} aria-label="Send"><Icon name="arrowRight" /></button>
          </form>
        </section>
      )}
    </>
  );
}
