/**
 * Inventory stages and their role-specific wording. A stage is derived on the server from two separate stored
 * dimensions, the review status of client submissions and the passport's publication state; tabs never write either.
 *   review          client-submitted or cloned part awaiting Aries review
 *   in_digitisation not published; Aries-maintained or accepted into the engineering workflow
 *   published       passport officially published
 *   all             every record the user is authorised to see (including rejected submissions)
 */
export type Stage = "all" | "review" | "in_digitisation" | "published";
export type Audience = "engineer" | "client" | "admin";
export const STAGES: Stage[] = ["all", "review", "in_digitisation", "published"];

export const STAGE_TEXT: Record<Audience, Record<Stage, [string, string]>> = {
  engineer: {
    all: ["All parts", "Every part in the companies and projects you are assigned to."],
    review: ["Awaiting Review", "Client-submitted or cloned parts waiting for your engineering review."],
    in_digitisation: ["In Digitisation", "Accepted or Aries-maintained parts whose digitisation or publication preparation is still underway. Not manufacturing-ready."],
    published: ["Published", "Parts with an officially published passport."],
  },
  client: {
    all: ["All parts", "Every spare part of your company."],
    review: ["Submitted for Review", "Parts your company submitted or cloned that Aries Engineering is still reviewing."],
    in_digitisation: ["Being Digitised", "Aries is digitising or documenting these parts. They are not published and not manufacturing-ready."],
    published: ["Published", "Parts published in your manufacturing catalog."],
  },
  admin: {
    all: ["All parts", "Administrative summary of every client company's inventory."],
    review: ["Review Backlog", "Client submissions and clones waiting for Aries Engineering review."],
    in_digitisation: ["Digitisation Progress", "Parts in digitisation or publication preparation, not yet published."],
    published: ["Published", "Parts with an officially published passport."],
  },
};

export const stageParam = (s: Stage) => (s === "all" ? "all" : s);
export const stageFrom = (v: string | null): Stage | "" => (v === "all" || v === "review" || v === "in_digitisation" || v === "published" ? v : "");
