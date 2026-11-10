/**
 * The CN-007 assessment workflow as one navigable strip: Inventory → Classification → Feasibility → Commercial
 * comparison → Recommendation → Engineering review → Quarterly assessment. Steps on the current page jump to their
 * section; the others open the screen that holds them. Navigation only: it shows no status and approves nothing.
 */
import { Link } from "react-router-dom";

import { Icon, type IconName } from "./icons";

export type AiStep = "inventory" | "classification" | "feasibility" | "commercial" | "recommendation" | "review" | "assessment";

const STEPS: [AiStep, string, IconName][] = [
  ["inventory", "Inventory", "upload"],
  ["classification", "Classification", "spark"],
  ["feasibility", "Feasibility", "gauge"],
  ["commercial", "Commercial comparison", "scale"],
  ["recommendation", "Recommendation", "route"],
  ["review", "Engineering review", "review"],
  ["assessment", "Quarterly assessment", "chart"],
];

/** Where each step lives: `#id` = a section on this page, otherwise a route. */
export function AiWorkflow({ targets, current, sticky }: { targets: Partial<Record<AiStep, string>>; current?: AiStep; sticky?: boolean }) {
  return (
    <nav className={`workflow${sticky ? " is-sticky" : ""}`} aria-label="AI assessment workflow">
      {STEPS.map(([key, name, icon], i) => {
        const to = targets[key];
        const body = (
          <>
            <span className="step-num" aria-hidden>{i + 1}</span>
            <Icon name={icon} size="sm" />
            {name}
          </>
        );
        const cls = `workflow-step${current === key ? " is-current" : ""}`;
        if (!to) return <span key={key} className={cls}>{body}</span>;
        return to.startsWith("#")
          ? <a key={key} className={cls} href={to}>{body}</a>
          : <Link key={key} className={cls} to={to} aria-current={current === key ? "step" : undefined}>{body}</Link>;
      })}
    </nav>
  );
}
