/**
 * Analysis charts for the operator dashboard. Presentation only: each chart draws counts the page has loaded
 * (`/operator/analytics/`, `/operator/overview/`, the open-request queue) and links to the lists behind them.
 * Identity is never colour alone: every series has a legend or a direct label, and every mark a hover tooltip.
 * Colours come from CSS (--series-N, a fixed order per entity, light and dark steps); the same entity keeps its colour
 * on every chart (spare parts aqua, digital passports blue).
 */
import { useState, type CSSProperties, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { STATUS } from "./requests";

const MONTH = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export const monthLabel = (ym: string) => MONTH[Number(ym.slice(5, 7)) - 1] ?? ym;
const monthLong = (ym: string) => `${monthLabel(ym)} ${ym.slice(0, 4)}`;

/** A rounded axis maximum and its ticks (4 steps). */
function scale(max: number): { top: number; ticks: number[] } {
  const raw = Math.max(max, 4) / 4;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const top = step * 4;
  return { top, ticks: [0, 1, 2, 3, 4].map((i) => +(i * step).toFixed(2)) };
}

export function Legend({ items }: { items: { label: string; series: number }[] }) {
  return (
    <ul className="chart-key">
      {items.map((i) => <li key={i.label}><span className="swatch" style={{ background: `var(--series-${i.series})` }} />{i.label}</li>)}
    </ul>
  );
}

/** Card frame for a chart: icon + title, optional control on the right. */
export function ChartCard({ title, icon, action, children, className = "" }: { title: string; icon?: ReactNode; action?: ReactNode;
  children: ReactNode; className?: string }) {
  return (
    <section className={`card chart-card ${className}`}>
      <div className="card-head"><h2>{icon}{title}</h2>{action}</div>
      {children}
    </section>
  );
}

export function RangeSelect({ value, onChange, options, label }: { value: number; onChange: (v: number) => void; options: [number, string][]; label: string }) {
  return (
    <select className="chart-range" aria-label={label} value={value} onChange={(e) => onChange(Number(e.target.value))}>
      {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select>
  );
}

const W = 420, H = 190, PAD = { l: 30, r: 12, t: 10, b: 24 };

/** Line chart over months: the first series also gets a soft area fill. Hover a month for its values. */
export function TrendChart({ months, series }: { months: string[]; series: { label: string; values: number[]; series: number }[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const { top, ticks } = scale(Math.max(0, ...series.flatMap((s) => s.values)));
  const iw = W - PAD.l - PAD.r, ih = H - PAD.t - PAD.b;
  const x = (i: number) => PAD.l + (months.length < 2 ? iw / 2 : (i / (months.length - 1)) * iw);
  const y = (v: number) => PAD.t + ih - (v / top) * ih;
  const line = (vals: number[]) => vals.map((v, i) => `${i ? "L" : "M"}${x(i)},${y(v)}`).join(" ");
  return (
    <div className="chart-plot">
      <Legend items={series.map((s) => ({ label: s.label, series: s.series }))} />
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={series.map((s) => `${s.label}: ${s.values.join(", ")}`).join("; ")}
        onMouseLeave={() => setHover(null)}>
        {ticks.map((t) => <g key={t}><line className="grid" x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} /><text className="tick" x={PAD.l - 6} y={y(t) + 3} textAnchor="end">{t}</text></g>)}
        {months.map((m, i) => <text key={m} className="tick" x={x(i)} y={H - 6} textAnchor="middle">{monthLabel(m)}</text>)}
        {series[0] && <path d={`${line(series[0].values)} L${x(months.length - 1)},${y(0)} L${x(0)},${y(0)} Z`} className="area" style={{ fill: `var(--series-${series[0].series})` }} />}
        {hover !== null && <line className="crosshair" x1={x(hover)} x2={x(hover)} y1={PAD.t} y2={PAD.t + ih} />}
        {series.map((s) => (
          <g key={s.label} style={{ color: `var(--series-${s.series})` }}>
            <path d={line(s.values)} className="trend-line" />
            {s.values.map((v, i) => <circle key={i} cx={x(i)} cy={y(v)} r={hover === i ? 5 : 3.5} className="dot" />)}
          </g>
        ))}
        {months.map((m, i) => (
          <rect key={m} className="hit" x={x(i) - iw / months.length / 2} y={PAD.t} width={iw / months.length} height={ih} onMouseEnter={() => setHover(i)} />
        ))}
      </svg>
      {hover !== null && (
        <div className="chart-tip" style={{ left: `${(x(hover) / W) * 100}%` }}>
          <strong>{monthLong(months[hover])}</strong>
          {series.map((s) => <span key={s.label}><span className="swatch" style={{ background: `var(--series-${s.series})` }} />{s.label}: <b>{s.values[hover]}</b></span>)}
        </div>
      )}
    </div>
  );
}

/** Vertical bars per category. `stacked`: segments on top of each other with the total above; otherwise side by side
 *  with each value above its bar. */
export function BarChart({ groups, series, stacked = false }: { stacked?: boolean; series: { label: string; series: number }[];
  groups: { key: string; label: string; values: number[]; to?: string; tip?: string }[] }) {
  const max = Math.max(0, ...groups.map((g) => (stacked ? g.values.reduce((a, b) => a + b, 0) : Math.max(...g.values))));
  const { top, ticks } = scale(max);
  return (
    <div className="chart-plot">
      <Legend items={series} />
      <div className="bars">
        <div className="bars-axis" aria-hidden="true">{[...ticks].reverse().map((t) => <span key={t}>{t}</span>)}</div>
        <ul className="bars-plot" aria-label={series.map((s) => s.label).join(" and ")}>
          {ticks.slice(1).map((t) => <li key={`g${t}`} className="bars-grid" style={{ bottom: `${(t / top) * 100}%` }} aria-hidden="true" />)}
          {groups.map((g) => {
            const total = g.values.reduce((a, b) => a + b, 0);
            const tip = g.tip ?? `${g.label}: ${g.values.map((v, i) => `${series[i].label} ${v}`).join(", ")}`;
            const body = stacked ? (
              <span className="bar-stack" style={{ height: `${(total / top) * 100}%` }}>
                <span className="bar-total">{total}</span>
                {g.values.map((v, i) => v > 0 && <span key={i} className="bar-seg" style={{ flexGrow: v, background: `var(--series-${series[i].series})` }} />)}
              </span>
            ) : (
              <span className="bar-pair">
                {g.values.map((v, i) => (
                  <span key={i} className="bar-col" style={{ height: `${(v / top) * 100}%`, background: `var(--series-${series[i].series})` }}>
                    <span className="bar-total">{v}</span>
                  </span>
                ))}
              </span>
            );
            return (
              <li key={g.key} className="bars-group" title={tip}>
                {g.to ? <Link to={g.to} aria-label={tip}>{body}</Link> : body}
                <span className="bars-label">{g.label}</span>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}

const SHORT: Record<string, string> = { submitted: "Awaiting ack." };
const statusLabel = (k: string) => SHORT[k] ?? STATUS[k]?.[0] ?? k;

/** Open requests by status: donut with the total in the middle; the legend gives share and count and links to the queue. */
export function RequestsByStatus({ requests }: { requests: { status: string }[] }) {
  const counts = new Map<string, number>();
  for (const r of requests) counts.set(r.status, (counts.get(r.status) ?? 0) + 1);
  const order = Object.keys(STATUS);
  const present = [...counts.keys()].sort((a, b) => order.indexOf(a) - order.indexOf(b));
  // colour follows the status (its place in the workflow); beyond six statuses the smallest fold into "Other"
  const keep = new Set([...present].sort((a, b) => counts.get(b)! - counts.get(a)!).slice(0, present.length > 6 ? 5 : 6));
  const slices: { key: string; label: string; value: number; series: number; to?: string }[] = [];
  let other = 0;
  present.forEach((k) => {
    if (keep.has(k)) slices.push({ key: k, label: statusLabel(k), value: counts.get(k)!, series: slices.length + 1, to: `/incoming?status=${k}` });
    else other += counts.get(k)!;
  });
  if (other) slices.push({ key: "other", label: "Other", value: other, series: 0, to: "/incoming" });
  const total = requests.length;
  if (!total) return <p className="muted small chart-empty">No open client requests.</p>;
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
              <title>{`${s.label}: ${s.value} (${Math.round((s.value / total) * 100)}%)`}</title>
            </circle>
          );
          offset += len;
          return el;
        })}
        <text x="60" y="58" className="donut-total">{total}</text>
        <text x="60" y="75" className="donut-caption">Requests</text>
      </svg>
      <ul className="chart-legend">
        {slices.map((s) => (
          <li key={s.key}>
            <Link to={s.to!}><span className="swatch" style={{ background: `var(--series-${s.series})` }} />
              {s.label} – {Math.round((s.value / total) * 100)}% <strong>({s.value})</strong></Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Client request flow (decision of 13 Nov 2026), grouped into its main stages, with the requests currently at each. */
const STAGES: { label: string; statuses: string[]; icon: string }[] = [
  { label: "Submitted", statuses: ["submitted"], icon: "inbox" },
  { label: "Engineering", statuses: ["acknowledged", "information_requested", "information_provided", "answered", "scheduled", "in_progress", "engineering_checked"], icon: "gear" },
  { label: "QA check", statuses: ["qa_approved"], icon: "shield" },
  { label: "Production", statuses: ["released", "in_production"], icon: "printer3d" },
  { label: "Inspected", statuses: ["inspected"], icon: "check" },
  { label: "Delivered", statuses: ["completed", "closed"], icon: "passport" },
];

export function RequestWorkflow({ byStatus, icon }: { byStatus: Record<string, number>; icon: (name: string) => ReactNode }) {
  const n = (ss: string[]) => ss.reduce((a, s) => a + (byStatus[s] ?? 0), 0);
  const counted = STAGES.reduce((a, s) => a + n(s.statuses), 0);
  const done = n(STAGES[STAGES.length - 1].statuses);
  const rate = counted ? Math.round((done / counted) * 100) : null;
  return (
    <>
      <ol className="flow">
        {STAGES.map((s, i) => (
          <li key={s.label} className={i === STAGES.length - 1 ? "is-last" : ""}>
            <Link to={s.statuses.length === 1 ? `/incoming?status=${s.statuses[0]}` : "/incoming"} title={`${s.label}: ${n(s.statuses)}`}>
              {icon(s.icon)}<span className="flow-label">{s.label}</span><strong>{n(s.statuses)}</strong>
            </Link>
          </li>
        ))}
      </ol>
      <div className="flow-foot">
        <span className="muted small">Submitted → Delivered (all client requests, excluding declined and withdrawn)</span>
        <span className="flow-rate"><strong>{rate === null ? "–" : `${rate}%`}</strong><span className="muted small">Completion rate</span></span>
      </div>
    </>
  );
}

/** Client requests per day: rows Monday..Sunday, one column per week, one blue ramp from light (few) to dark (many). */
export function ActivityHeatmap({ start, days }: { start: string; days: number[][] }) {
  const max = Math.max(0, ...days.flat());
  const step = (v: number) => (v === 0 ? 0 : max <= 1 ? 3 : Math.min(5, 1 + Math.floor(((v - 1) / Math.max(max - 1, 1)) * 5)));
  const base = new Date(`${start}T00:00:00`);
  const today = new Date();
  const fmt = (d: Date) => d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  return (
    <div className="heat">
      <div className="heat-grid" style={{ "--weeks": days[0]?.length ?? 12 } as CSSProperties} role="img" aria-label={`Client requests per day over ${days[0]?.length ?? 0} weeks; busiest day ${max}`}>
        {days.map((row, d) => (
          <div key={d} className="heat-row">
            <span className="heat-day">{["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][d]}</span>
            {row.map((v, w) => {
              const date = new Date(base); date.setDate(base.getDate() + w * 7 + d);
              const future = date > today;
              return <span key={w} className={`heat-cell s${future ? "x" : step(v)}`} title={future ? "" : `${fmt(date)}: ${v} request${v === 1 ? "" : "s"}`} />;
            })}
          </div>
        ))}
      </div>
      <div className="heat-key" aria-hidden="true"><span>Lower activity</span>{[0, 1, 2, 3, 4, 5].map((s) => <span key={s} className={`heat-cell s${s}`} />)}<span>Higher activity</span></div>
    </div>
  );
}

export function Sparkline({ values, label }: { values: number[]; label: string }) {
  const max = Math.max(1, ...values);
  const pts = values.map((v, i) => `${(i / Math.max(values.length - 1, 1)) * 116 + 2},${26 - (v / max) * 22}`);
  return (
    <svg className="spark" viewBox="0 0 120 30" role="img" aria-label={`${label}: ${values.join(", ")} per week`}>
      <title>{`${label}, last ${values.length} weeks: ${values.join(", ")}`}</title>
      <polyline points={pts.join(" ")} />
      <circle cx={pts.length ? Number(pts[pts.length - 1].split(",")[0]) : 0} cy={pts.length ? Number(pts[pts.length - 1].split(",")[1]) : 0} r="3" />
    </svg>
  );
}

/** Change of the last `n` months against the `n` before. */
export function Growth({ values, n, label }: { values: number[]; n: number; label: string }) {
  const now = values.slice(-n).reduce((a, b) => a + b, 0);
  const before = values.slice(-2 * n, -n).reduce((a, b) => a + b, 0);
  const pct = before ? Math.round(((now - before) / before) * 100) : null;
  const dir = pct === null ? (now > 0 ? "up" : "flat") : pct > 0 ? "up" : pct < 0 ? "down" : "flat";
  return (
    <div className={`growth is-${dir}`}>
      <strong>{dir === "up" ? "▲ " : dir === "down" ? "▼ " : ""}{pct === null ? (now > 0 ? "New" : "–") : `${pct > 0 ? "+" : ""}${pct}%`}</strong>
      <span>{label}</span>
      <span className="muted small">{now} in the last {n} months · {before} in the {n} before</span>
    </div>
  );
}
