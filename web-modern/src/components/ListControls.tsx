/**
 * Search, filter, sort and pagination for lists the server returns in full (company overviews and similar). Nothing is
 * removed or changed: rows outside the current filter or page are only not shown, and the summary always says how many
 * there are. Filter segments show their counts; the pager says "Showing x–y of n".
 */
import { useEffect, useMemo, useState } from "react";

import { Icon } from "./icons";

export type ListFilter<T> = [key: string, label: string, test: (r: T) => boolean];
export type ListSort<T> = [key: string, label: string, compare: (a: T, b: T) => number];

export function useListControls<T>(rows: T[], opts: {
  text: (r: T) => string; filters: ListFilter<T>[]; sorts: ListSort<T>[]; defaultFilter?: string; defaultSort?: string; pageSize?: number;
}) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState(opts.defaultFilter ?? opts.filters[0]?.[0] ?? "");
  const [sort, setSort] = useState(opts.defaultSort ?? opts.sorts[0]?.[0] ?? "");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(opts.pageSize ?? 15);
  const q = query.trim().toLowerCase();
  const matching = useMemo(() => rows.filter((r) => !q || opts.text(r).toLowerCase().includes(q)), [rows, q]);  // eslint-disable-line react-hooks/exhaustive-deps
  const counts = useMemo(() => Object.fromEntries(opts.filters.map(([k, , test]) => [k, matching.filter(test).length])),
    [matching]);  // eslint-disable-line react-hooks/exhaustive-deps
  const filtered = useMemo(() => {
    const test = opts.filters.find(([k]) => k === filter)?.[2] ?? (() => true);
    const cmp = opts.sorts.find(([k]) => k === sort)?.[2];
    const out = matching.filter(test);
    return cmp ? [...out].sort(cmp) : out;
  }, [matching, filter, sort]);  // eslint-disable-line react-hooks/exhaustive-deps
  const pages = Math.max(1, Math.ceil(filtered.length / pageSize));
  useEffect(() => setPage(1), [q, filter, sort, pageSize]);
  const current = Math.min(page, pages);
  const visible = filtered.slice((current - 1) * pageSize, current * pageSize);
  return { query, setQuery, filter, setFilter, sort, setSort, page: current, setPage, pageSize, setPageSize, pages, visible,
    total: rows.length, filteredCount: filtered.length, counts, filters: opts.filters, sorts: opts.sorts,
    from: filtered.length ? (current - 1) * pageSize + 1 : 0, to: Math.min(current * pageSize, filtered.length) };
}

type Controls<T> = ReturnType<typeof useListControls<T>>;

export function ListToolbar<T>({ c, searchLabel, placeholder }: { c: Controls<T>; searchLabel: string; placeholder?: string }) {
  return (
    <div className="list-toolbar">
      <div className="search-field">
        <Icon name="search" />
        <input type="search" aria-label={searchLabel} placeholder={placeholder ?? searchLabel} value={c.query} onChange={(e) => c.setQuery(e.target.value)} />
      </div>
      {c.filters.length > 1 && (
        <div className="segmented" role="group" aria-label="Show">
          {c.filters.map(([k, l]) => (
            <button key={k} type="button" aria-pressed={c.filter === k} onClick={() => c.setFilter(k)}>{l}<span className="count">{c.counts[k]}</span></button>
          ))}
        </div>
      )}
      {c.sorts.length > 1 && (
        <label className="list-sort">Sort
          <select aria-label="Sort" value={c.sort} onChange={(e) => c.setSort(e.target.value)}>
            {c.sorts.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </label>
      )}
    </div>
  );
}

export function ListPager<T>({ c, noun }: { c: Controls<T>; noun: string }) {
  return (
    <div className="list-pager" aria-label={`${noun} pages`}>
      <span className="muted small" role="status">{c.filteredCount ? `Showing ${c.from}–${c.to} of ${c.filteredCount} ${noun}` : `No ${noun} match`}
        {c.filteredCount !== c.total ? ` (${c.total} in total)` : ""}</span>
      <span className="list-pager-controls">
        <label className="small muted">Per page
          <select aria-label="Rows per page" value={c.pageSize} onChange={(e) => c.setPageSize(Number(e.target.value))}>
            {[10, 15, 25, 50, 100].map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
        <button type="button" className="btn btn-small" disabled={c.page <= 1} onClick={() => c.setPage(c.page - 1)}>Previous</button>
        <span className="small">Page {c.page} of {c.pages}</span>
        <button type="button" className="btn btn-small" disabled={c.page >= c.pages} onClick={() => c.setPage(c.page + 1)}>Next</button>
      </span>
    </div>
  );
}
