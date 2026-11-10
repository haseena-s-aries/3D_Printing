/** Aries QA, inside a client company: photo-origin claims waiting for an independent decision. */
import { Link } from "react-router-dom";

import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { Card, Empty, ErrorNotice, Loading, PageHeader, formatDate } from "../components/ui";

type Claim = { file: string; version: number; part: string; part_number: string; title: string; claimed_by: string; claimed_at: string;
  capture_reference: string; note: string; own_claim: boolean };

export default function OriginQueuePage() {
  const { session } = useAuth();
  const q = useApi<{ results: Claim[] }>("/files/origin-claims/");
  return (
    <>
      <PageHeader title="Photo origin queue" subtitle={`Claims that a photo of ${session?.tenant.name ?? "this company"} was taken by Aries during scanning work, waiting for Aries QA.`} />
      <ErrorNotice error={q.error} />
      {q.loading && !q.data && <Loading />}
      {q.data && (
        <Card title={`Open claims (${q.data.results.length})`}>
          {q.data.results.length === 0 ? <Empty icon="check">No claims are waiting for review.</Empty> : (
            <div className="table-scroll">
              <table className="table table-stack" aria-label="Open photo origin claims">
                <thead><tr><th>Part</th><th>Photo</th><th>Claimed by</th><th>Reference or description</th><th><span className="sr-only">Action</span></th></tr></thead>
                <tbody>
                  {q.data.results.map((c) => (
                    <tr key={`${c.file}-${c.version}`}>
                      <td><strong>{c.part_number}</strong></td>
                      <td>{c.title} <span className="muted small">v{c.version}</span></td>
                      <td>{c.claimed_by}<div className="muted small">{formatDate(c.claimed_at)}</div></td>
                      <td>{c.capture_reference && <div>{c.capture_reference}</div>}{c.note && <div className="muted small">{c.note}</div>}</td>
                      <td className="actions">
                        <Link className="btn btn-small btn-primary" to={`/parts/${c.part}/photos/${c.file}/origin?from=queue`}
                          aria-label={`Review claim for ${c.part_number}`}>Review claim</Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="muted small">You cannot decide on a claim you made yourself. Confirming makes a photo eligible for the contract route
            only; it changes nothing about the photo, its release to the client or the client's own permission.</p>
        </Card>
      )}
    </>
  );
}
