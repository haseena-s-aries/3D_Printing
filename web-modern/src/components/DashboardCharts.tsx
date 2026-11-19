/**
 * Small analysis charts for the operator dashboard. Presentation only: they draw counts the page has already loaded
 * (open requests, client overview) and link to the same lists the KPI tiles open. Identity is never colour alone:
 * every slice/bar has a text label and count beside it, and a native tooltip on hover.
 */
import { Link } from "react-router-dom";

import { OPEN_STATUSES, STATUS } from "./requests";

/** Fixed categorical order (colour follows the status, never its rank). Values live in CSS (--series-N, light/dark). */
const SERIES = 7;

const SHORT: Record<string, string> = { submitted: "Awaiting ack." };
const statusLabel = (k: string) => SHORT[k] ?? STATUS[k]?.[0] ?? k;

/** Open requests by status: donut with the total in the middle and a legend that links to the filtered queue. */
export function RequestsByStatus({ requests }: { requests: { status: string }[] }) {
  const counts = new Map<string, number>();
  for (const r of requests) counts.set(r.status, (counts.get(r.status) ?? 0) + 1);
  // statuses in their workflow order; beyond the palette, the smallest fold into "Other"
  const present = [...counts.keys()].sort((a, b) => idx(a) - idx(b));
  const keep = new Set([...present].sort((a, b) => counts.get(b)! - counts.get(a)! || idx(a) - idx(b)).slice(0, present.length > SERIES ? SERIES - 1 : SERIES));
  const slices: { key: string; label: string; value: number; series: number; to?: string }[] = [];
  let other = 0;
  present.forEach((k) => {
    if (keep.has(k)) slices.push({ key: k, label: statusLabel(k), value: counts.get(k)!, series: slices.length + 1, to: `/incoming?status=${k}` });
    else other += counts.get(k)!;
  });
  if (other) slices.push({ key: "other", label: "Other", value: other, series: 0 });
  const total = requests.length;

  const r = 42, c = 2 * Math.PI * r, gap = slices.length > 1 ? 2 : 0;
  let offset = 0;
  return (
    <div className="chart-donut">
      <svg viewBox="0 0 120 120" role="img" aria-label={`${total} open requests by status`}>
        <circle cx="60" cy="60" r={r} className="donut-track" />
        {slices.map((s) => {
          const len = (s.value / total) * c;
          const el = (
            <circle key={s.key} cx="60" cy="60" r={r} className="donut-slice" style={{ stroke: `var(--series-${s.series})` }}
              strokeDasharray={`${Math.max(len - gap, 0.5)} ${c}`} strokeDashoffset={-offset} transform="rotate(-90 60 60)">
              <title>{`${s.label}: ${s.value}`}</title>
            </circle>
          );
          offset += len;
          return el;
        })}
        <text x="60" y="58" className="donut-total">{total}</text>
        <text x="60" y="76" className="donut-caption">Requests</text>
      </svg>
      <ul className="chart-legend">
        {slices.map((s) => {
          const body = <><span className="swatch" style={{ background: `var(--series-${s.series})` }} />{s.label} <strong>({s.value})</strong></>;
          return <li key={s.key}>{s.to ? <Link to={s.to}>{body}</Link> : body}</li>;
        })}
      </ul>
    </div>
  );
}

const idx = (k: string) => { const i = OPEN_STATUSES.indexOf(k); return i < 0 ? 99 : i; };

/** Digital passports per client: one series, the busiest clients by name and the rest as "Others". */
export function PassportsByClient({ rows }: { rows: { id: string; name: string; counts: { passports: number } }[] }) {
  const sorted = rows.filter((r) => r.counts.passports > 0).sort((a, b) => b.counts.passports - a.counts.passports || a.name.localeCompare(b.name));
  const top = sorted.slice(0, sorted.length > 4 ? 3 : 4);
  const rest = sorted.slice(top.length).reduce((n, r) => n + r.counts.passports, 0);
  const bars: { key: string; name: string; value: number; to?: string }[] = top.map((r) => ({ key: r.id, name: r.name, value: r.counts.passports, to: `/clients/${r.id}` }));
  if (rest) bars.push({ key: "others", name: "Others", value: rest });
  if (!bars.length) return <p className="muted small">No digital passports yet.</p>;
  const max = Math.max(...bars.map((b) => b.value));
  return (
    <ul className="chart-bars" aria-label="Digital passports by client">
      {bars.map((b) => {
        const body = (
          <>
            <span className="bar-value">{b.value}</span>
            <span className="bar-track"><span className="bar-fill" style={{ height: `${Math.max((b.value / max) * 100, 4)}%` }} /></span>
            <span className="bar-name">{b.name}</span>
          </>
        );
        return (
          <li key={b.key} title={`${b.name}: ${b.value} passport${b.value === 1 ? "" : "s"}`}>
            {b.to ? <Link to={b.to}>{body}</Link> : <div>{body}</div>}
          </li>
        );
      })}
    </ul>
  );
}
