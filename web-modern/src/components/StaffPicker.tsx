/**
 * Searchable picker for Aries staff accounts: lists the people with the chosen role as "Name (email)", filtered by
 * name or email as you type. Keyboard: arrows move, Enter picks, Escape closes. People already assigned are shown but
 * cannot be picked. The value is the picked person's email.
 */
import { useId, useMemo, useRef, useState } from "react";

export interface StaffOption { email: string; name: string; role: string }

export const staffLabel = (o: StaffOption) => (o.name ? `${o.name} (${o.email})` : o.email);

export function filterStaff(options: StaffOption[], role: string, query: string): StaffOption[] {
  const q = query.trim().toLowerCase();
  return options
    .filter((o) => o.role === role && (!q || o.name.toLowerCase().includes(q) || o.email.toLowerCase().includes(q)))
    .sort((a, b) => (a.name || a.email).localeCompare(b.name || b.email));
}

export function StaffPicker({ id, options, role, value, onChange, assigned, loading, roleName }: {
  id?: string; options: StaffOption[]; role: string; value: string; onChange: (email: string) => void;
  assigned: Set<string>; loading?: boolean; roleName: string;
}) {
  const listId = useId();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const matches = useMemo(() => filterStaff(options, role, query), [options, role, query]);
  const picked = options.find((o) => o.email === value);
  const shown = open ? query : picked ? staffLabel(picked) : query;

  function pick(o: StaffOption) {
    if (assigned.has(o.email.toLowerCase())) return;
    onChange(o.email);
    setQuery("");
    setOpen(false);
  }
  function onKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!open) return setOpen(true);
      setActive((i) => Math.max(0, Math.min(matches.length - 1, i + (e.key === "ArrowDown" ? 1 : -1))));
    } else if (e.key === "Enter" && open) {
      e.preventDefault();
      if (matches[active]) pick(matches[active]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }
  return (
    <div className="staff-picker">
      <input ref={input} id={id} type="text" role="combobox" aria-expanded={open} aria-controls={listId} aria-autocomplete="list"
        aria-activedescendant={open && matches[active] ? `${listId}-${active}` : undefined} autoComplete="off"
        placeholder={`Search ${roleName} by name or email`} value={shown}
        onFocus={() => { setQuery(""); setActive(0); setOpen(true); }}
        onClick={() => setOpen(true)}
        onBlur={() => window.setTimeout(() => setOpen(false), 120)}
        onChange={(e) => { setQuery(e.target.value); setActive(0); setOpen(true); if (value) onChange(""); }}
        onKeyDown={onKey} />
      {open && (
        <ul className="staff-options" id={listId} role="listbox" aria-label={`${roleName} accounts`}>
          {loading ? <li className="staff-empty">Loading…</li>
            : matches.length === 0 ? <li className="staff-empty">{query.trim() ? `No ${roleName} matches “${query.trim()}”.` : `No ${roleName} accounts yet. Create one on the Users page.`}</li>
            : matches.map((o, i) => {
              const taken = assigned.has(o.email.toLowerCase());
              return (
                <li key={o.email} id={`${listId}-${i}`} role="option" aria-selected={o.email === value} aria-disabled={taken || undefined}
                  className={`staff-option${i === active ? " is-active" : ""}${taken ? " is-taken" : ""}`}
                  onMouseDown={(e) => { e.preventDefault(); pick(o); }} onMouseEnter={() => setActive(i)}>
                  <span>{o.name ? <><strong>{o.name}</strong> <span className="muted">({o.email})</span></> : o.email}</span>
                  {taken && <span className="muted small">Already assigned</span>}
                </li>
              );
            })}
        </ul>
      )}
    </div>
  );
}
