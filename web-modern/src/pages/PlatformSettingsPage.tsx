/** Aries Admin: read-only platform configuration (deployment-controlled; no secrets are shown). */
import { Fragment } from "react";

import { useApi } from "../api/useApi";
import { Badge, Card, ErrorNotice, Loading, Notice, PageHeader } from "../components/ui";

type Settings = {
  switches: { key: string; label: string; on: boolean }[];
  ai: { provider: string; provider_configured: boolean; allowed_companies: string[]; client_sharing_companies: string[];
    calls_per_minute: number; calls_per_day: number; daily_budget_usd: number };
  access: { file_access_decisions: { company: string; decision: string }[]; objection_authority: string; objection_reviewers: string[] };
  links: { download_link_seconds: number; admin_thumbnail_link_seconds: number };
  open_decisions: { key: string; text: string }[]; managed_by: string;
};
const list = (xs: string[]) => (xs.length ? xs.join(", ") : <span className="muted">None</span>);

export default function PlatformSettingsPage() {
  const s = useApi<Settings>("/admin/platform-settings/");
  return (
    <>
      <PageHeader title="Platform settings" subtitle="Feature switches, AI limits and access decisions of this deployment." />
      <ErrorNotice error={s.error} />
      {s.loading && !s.data && <Loading />}
      {s.data && (
        <div className="settings-grid">
          <Notice kind="info">{s.data.managed_by} Authorities that open access (file access, objection review) are set with the deployment
            so nobody can grant them to themselves.</Notice>
          <Card title="Feature switches">
            <ul className="settings-list" aria-label="Feature switches">
              {s.data.switches.map((x) => (
                <li key={x.key}><span>{x.label}<span className="muted small mono"> {x.key}</span></span>
                  <Badge tone={x.on ? "success" : "neutral"}>{x.on ? "On" : "Off"}</Badge></li>
              ))}
            </ul>
          </Card>
          <Card title="Access decisions">
            <dl className="facts">
              <dt>Confidential file content for Aries Admin</dt>
              <dd>{s.data.access.file_access_decisions.length ? s.data.access.file_access_decisions.map((d) => `${d.company}: ${d.decision}`).join("; ")
                : "Closed in every company (no documented decision)"}</dd>
              <dt>Client-objection authority</dt><dd>{s.data.access.objection_authority || <span className="muted">Not defined</span>}</dd>
              <dt>Designated objection reviewers</dt><dd>{list(s.data.access.objection_reviewers)}</dd>
              <dt>Download link lifetime</dt><dd>{s.data.links.download_link_seconds} s</dd>
              <dt>Admin thumbnail link lifetime</dt><dd>{s.data.links.admin_thumbnail_link_seconds} s</dd>
            </dl>
          </Card>
          <Card title="External AI">
            <dl className="facts">
              <dt>Provider</dt><dd>{s.data.ai.provider} {s.data.ai.provider_configured ? <Badge tone="success">Configured</Badge> : <Badge>Not configured</Badge>}</dd>
              <dt>Companies allowed to use external AI</dt><dd>{list(s.data.ai.allowed_companies)}</dd>
              <dt>Client sharing allowed</dt><dd>{list(s.data.ai.client_sharing_companies)}</dd>
              <dt>Limits</dt><dd>{s.data.ai.calls_per_minute}/min · {s.data.ai.calls_per_day}/day · USD {s.data.ai.daily_budget_usd.toFixed(2)}/day</dd>
            </dl>
          </Card>
          <Card title="Open business decisions">
            <dl className="facts">{s.data.open_decisions.map((d) => <Fragment key={d.key}><dt>{d.key}</dt><dd>{d.text}</dd></Fragment>)}</dl>
          </Card>
        </div>
      )}
    </>
  );
}
