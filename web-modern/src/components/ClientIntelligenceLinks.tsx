/**
 * Spare Parts Intelligence where clients already work (CN-007): a dashboard card and a part-page panel. Both read the
 * client overview (/client-intelligence/, shared results and the client's own requests only; it records no part view),
 * so they never show internal AI records and add no request when the Needs attention panel is on the same page.
 */
import { Link } from "react-router-dom";

import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { Icon } from "./icons";
import { Badge, Card } from "./ui";

type Row = { id: string; part_number: string; status: { code: string; label: string; shared_at: string | null }; outcome: string | null;
  open_request: { reference: string; status_label: string } | null };
type Overview = { access: { enabled: boolean; allowed: boolean; can_request: boolean }; parts: Row[]; counts: Record<string, number> };
const TONE: Record<string, "neutral" | "info" | "warning" | "danger"> = {
  available: "info", preparing: "info", in_assessment: "warning", withdrawn: "danger", not_assessed: "neutral",
};

function useOverview() {
  const { session, can } = useAuth();
  const client = !session?.membership.role.startsWith("operator_");
  return useApi<Overview>(client && can("ai.workspace") ? "/client-intelligence/" : null);
}

export function ClientIntelligenceCard() {
  const ov = useOverview();
  if (!ov.data) return null;
  const { access, counts, parts } = ov.data;
  const n = (k: string) => counts[k] ?? 0;
  return (
    <section className="card spi-card" aria-label="Spare Parts Intelligence">
      <div className="card-head">
        <h2><Icon name="spark" size="sm" />Spare Parts Intelligence</h2>
        {access.enabled && access.allowed && <Link className="btn btn-primary btn-small" to="/ai/my-parts">Open my parts intelligence</Link>}
      </div>
      {!access.enabled ? (
        <p className="muted">Assessment of your spare parts by Aries Engineering (OEM, additive and conventional options). Not enabled for your company yet;
          Aries switches it on when results can be shared.</p>
      ) : !access.allowed ? (
        <p className="muted">Your Client Administrator has not given you access to Spare Parts Intelligence.</p>
      ) : (
        <>
          <div className="spi-stats">
            <Link to="/ai/my-parts" className="spi-stat"><strong>{n("available")}</strong><span>Results available</span></Link>
            <Link to="/ai/my-parts" className="spi-stat"><strong>{n("in_assessment") + n("preparing")}</strong><span>Under engineering assessment</span></Link>
            <Link to="/ai/my-parts" className="spi-stat"><strong>{n("not_assessed")}</strong><span>Not yet assessed</span></Link>
            <Link to="/ai/my-parts" className="spi-stat"><strong>{parts.filter((p) => p.open_request).length}</strong><span>Your open requests</span></Link>
          </div>
          <p className="muted small">Shared results are information for planning, not an engineering approval or manufacturing release.</p>
        </>
      )}
    </section>
  );
}

export function PartIntelligenceLink({ partId }: { partId: string }) {
  const ov = useOverview();
  if (!ov.data || !ov.data.access.enabled || !ov.data.access.allowed) return null;
  const row = ov.data.parts.find((p) => p.id === partId);
  if (!row) return null;
  return (
    <Card title="Spare Parts Intelligence">
      <div className="spi-part">
        <Badge tone={TONE[row.status.code] ?? "neutral"}>{row.status.label}</Badge>
        {row.outcome && <p className="spi-outcome">{row.outcome}</p>}
        {row.open_request && <p className="muted small">Your request {row.open_request.reference} · {row.open_request.status_label}</p>}
        <Link className={`btn ${row.status.code === "available" ? "btn-primary" : ""}`} to={`/ai/my-parts/${row.id}`}>
          <Icon name="spark" size="sm" />{row.status.code === "available" ? "Open assessment results" : ov.data.access.can_request && !row.open_request
            ? "Request an assessment" : "Open in Spare Parts Intelligence"}</Link>
      </div>
    </Card>
  );
}
