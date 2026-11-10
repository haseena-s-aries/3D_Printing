import type { Paginated, Passport } from "@passport/api-types";
import { useState } from "react";
import { useDecision } from "../components/decision";
import { Link } from "react-router-dom";

import { useApi } from "../api/useApi";
import { Badge, Card, Empty, ErrorNotice, Loading, PageHeader, Pager, label } from "../components/ui";

const PAGE_SIZE = 25;

export default function PassportsPage() {
  const oq = useDecision();
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState({ search: "", page: 1 });
  const list = useApi<Paginated<Passport>>("/passports/", { query: { ...filters, page_size: PAGE_SIZE } });
  return (
    <>
      <PageHeader title="Digital passports" subtitle="Passport drafts are created from a spare part." />
      <Card>
        <form className="toolbar" onSubmit={(e) => { e.preventDefault(); setFilters({ search, page: 1 }); }} role="search">
          <input type="search" placeholder="Search by passport number, title or part number" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search passports" />
          <button className="btn">Search</button>
        </form>
        <p className="muted small">Use the digital inventory to filter parts by data captured and manufacturing eligibility{oq("OQ-35, OQ-36")}.</p>
        <ErrorNotice error={list.error} />
        {list.loading && !list.data ? <Loading /> : list.data?.results.length ? (
          <>
            <table className="table">
              <thead>
                <tr><th>Passport</th><th>Spare part</th><th>Publication</th><th>Evidence level</th><th>Manufacturing</th><th>Revision</th><th>Data captured</th></tr>
              </thead>
              <tbody>
                {list.data.results.map((p) => {
                  const c = p.current_revision?.completeness;
                  return (
                    <tr key={p.id}>
                      <td><Link to={`/passports/${p.id}`}>{p.passport_number}</Link><div className="muted small">{p.title}</div></td>
                      <td>{p.part_summary.part_number}</td>
                      <td><Badge tone="info">{label(p.publication_state)}</Badge></td>
                      <td>{p.evidence_level === "none" ? "Not assessed" : p.evidence_level}</td>
                      <td>{label(p.manufacturing_eligibility)}</td>
                      <td>{p.current_revision ? `rev ${p.current_revision.revision_number} (${p.current_revision.status})` : "—"}</td>
                      <td className="small">{c ? `R-L1 ${c.rl1.done}/${c.rl1.total} · R-L2 ${c.rl2.done}/${c.rl2.total} · R-L3 ${c.rl3.done}/${c.rl3.total}` : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <Pager page={filters.page} count={list.data.count} pageSize={PAGE_SIZE} onPage={(page) => setFilters({ ...filters, page })} />
          </>
        ) : <Empty>No passports yet. Open a spare part and create a passport draft.</Empty>}
      </Card>
    </>
  );
}
