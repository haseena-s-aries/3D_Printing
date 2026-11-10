/**
 * The AI assessment of one part as a stepped workspace (CN-007): Classification → Feasibility → Cost & lead time →
 * Recommendation & review → Client sharing. One step is shown at a time; each step shows its status, read from the same
 * part endpoints the step panels use. The panels themselves (content, actions, wording, separation of duties) are the
 * existing ones; nothing here approves, authorises or releases anything (OQ-35, OQ-36).
 */
import type { Part } from "@passport/api-types";
import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";

import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { DisclosurePanel } from "./ClientSharing";
import { CostComparisonPanel } from "./CostComparison";
import { Icon, type IconName } from "./icons";
import { FeasibilityPanel } from "./ManufacturingFeasibility";
import { PartIntelligencePanel } from "./PartIntelligence";
import { RecommendationPanel } from "./Recommendation";

export type AiStepKey = "classification" | "feasibility" | "commercial" | "recommendation" | "sharing";
type Status = { text: string; done: boolean };

const STEPS: [AiStepKey, string, IconName][] = [
  ["classification", "Classification", "spark"], ["feasibility", "Feasibility", "gauge"], ["commercial", "Cost & lead time", "scale"],
  ["recommendation", "Recommendation & review", "route"], ["sharing", "Client sharing", "eye"],
];

export const AI_STEP_KEYS = STEPS.map(([k]) => k);

export function AiAssessmentTab({ part, step, onStep, onClassified }: { part: Part; step: AiStepKey; onStep: (s: AiStepKey) => void; onClassified: () => void }) {
  const { can } = useAuth();
  const steps = STEPS.filter(([k]) => k !== "sharing" || can("ai.share"));
  const current = steps.some(([k]) => k === step) ? step : "classification";
  // step statuses: the same part endpoints the panels read (identical in-flight requests are shared)
  const intel = useApi<{ assessments: unknown[]; classification: { category: string; provenance?: { verified_by: string } } }>(`/parts/${part.id}/intelligence/`);
  const feas = useApi<{ assessments: { version: number; reviews: unknown[] }[] }>(`/parts/${part.id}/feasibility/`);
  const cost = useApi<{ comparisons: { version: number }[] }>(`/parts/${part.id}/cost-comparisons/`);
  const rec = useApi<{ recommendations: { version: number; review_state: { code: string; reviewed: boolean } }[] }>(`/parts/${part.id}/recommendations/`);
  const disc = useApi<{ state: { code: string; label: string } }>(can("ai.share") ? `/parts/${part.id}/disclosures/` : null);
  const strip = useRef<HTMLOListElement>(null);
  useEffect(() => {  // keep the current step visible in the strip on narrow screens (it scrolls sideways there)
    const ol = strip.current, el = document.getElementById(`ai-step-${current}`);
    if (ol && el && ol.scrollWidth > ol.clientWidth) ol.scrollLeft = Math.max(0, (el.parentElement?.offsetLeft ?? 0) - 8);
  }, [current]);
  const first = useRef(true);
  useEffect(() => {  // a step's actions change its status: refresh the statuses when the engineer moves on
    if (first.current) { first.current = false; return; }
    void intel.reload(); void feas.reload(); void cost.reload(); void rec.reload(); if (can("ai.share")) void disc.reload();
  }, [current]);  // eslint-disable-line react-hooks/exhaustive-deps

  const fa = feas.data?.assessments?.[0];
  const cc = cost.data?.comparisons?.[0];
  const rv = rec.data?.recommendations?.[0];
  const status: Record<AiStepKey, Status | null> = {
    classification: intel.data ? (intel.data.classification?.provenance ? { text: "Verified by engineer", done: true }
      : intel.data.assessments?.length ? { text: "AI suggestion · not verified", done: false } : { text: "Not classified", done: false }) : null,
    feasibility: feas.data ? (fa ? { text: `v${fa.version} · ${fa.reviews?.length ? "reviewed" : "preliminary"}`, done: true } : { text: "Not run", done: false }) : null,
    commercial: cost.data ? (cc ? { text: `v${cc.version} stored`, done: true } : { text: "No comparison", done: false }) : null,
    recommendation: rec.data ? (rv ? { text: `v${rv.version} · ${rv.review_state.reviewed ? "reviewed" : "preliminary"}`, done: rv.review_state.reviewed }
      : { text: "Not generated", done: false }) : null,
    sharing: disc.data ? { text: disc.data.state.label.replace(" (internal)", "").replace(" (not reviewed)", ""), done: disc.data.state.code === "shared" } : null,
  };
  const i = steps.findIndex(([k]) => k === current);
  const prev = steps[i - 1], next = steps[i + 1];

  return (
    <div className="ai-workspace">
      <nav className="ai-steps" aria-label="AI assessment steps">
        <ol ref={strip} role="tablist" aria-label="AI assessment steps">
          {steps.map(([k, name, icon], n) => {
            const st = status[k];
            return (
              <li key={k} role="presentation">
                <button type="button" role="tab" id={`ai-step-${k}`} aria-selected={current === k} aria-controls="ai-step-panel"
                  tabIndex={current === k ? 0 : -1} className={`ai-step ${current === k ? "is-active" : ""} ${st?.done ? "is-done" : ""}`} onClick={() => onStep(k)}>
                  <span className="ai-step-num" aria-hidden>{st?.done ? <Icon name="check" size="sm" /> : n + 1}</span>
                  <span className="ai-step-text">
                    <span className="ai-step-name"><Icon name={icon} size="sm" />{name}</span>
                    <span className="ai-step-status">{st ? st.text : "…"}</span>
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
        <Link className="ai-steps-link" to="/inventory-import?tab=assessment"><Icon name="chart" size="sm" />Quarterly assessment</Link>
      </nav>
      <div id="ai-step-panel" role="tabpanel" aria-labelledby={`ai-step-${current}`} className="ai-step-panel">
        {current === "classification" && <PartIntelligencePanel partId={part.id} onClassified={onClassified} />}
        {current === "feasibility" && <FeasibilityPanel partId={part.id} />}
        {current === "commercial" && <CostComparisonPanel partId={part.id} />}
        {current === "recommendation" && <RecommendationPanel partId={part.id} />}
        {current === "sharing" && <DisclosurePanel partId={part.id} />}
      </div>
      <div className="ai-step-pager">
        {prev ? <button type="button" className="btn" onClick={() => { onStep(prev[0]); window.scrollTo({ top: 0 }); }}><Icon name="arrowLeft" size="sm" />{prev[1]}</button> : <span />}
        {next && <button type="button" className="btn btn-primary" onClick={() => { onStep(next[0]); window.scrollTo({ top: 0 }); }}>Next: {next[1]}<Icon name="chevron" size="sm" /></button>}
      </div>
    </div>
  );
}
