import type { Session } from "@passport/api-types";

/** Display names of roles (CN-002): the platform operator is Aries. Stored role values are unchanged. */
export const ROLE_LABELS: Record<string, string> = {
  operator_admin: "Aries Admin",
  operator_engineer: "Aries Engineer",
  operator_qa: "Aries QA",
  operator_support: "Aries Support",
  client_admin: "Client Administrator",
  client_engineer: "Client Engineer",
  client_user: "Client User",
  procurement: "Procurement",
  auditor: "Auditor",
};

/** Roles of the earlier model: existing memberships keep them (and their rights) until mapped; never assigned again. */
export const LEGACY_ROLES = ["operator_qa", "operator_support", "client_engineer", "procurement", "auditor"];

export const roleLabel = (role: string): string => ROLE_LABELS[role] ?? role.replace(/_/g, " ");

/** Label for lists and pickers: legacy roles are marked so nobody mistakes them for a current choice. */
export const roleOptionLabel = (role: string): string => (LEGACY_ROLES.includes(role) ? `${roleLabel(role)} (legacy)` : roleLabel(role));

export const fourRoles = (session: Session | null | undefined): boolean => session?.role_model === "four_roles";

const LEGACY_OPERATOR = ["operator_admin", "operator_engineer", "operator_qa", "operator_support"];
const LEGACY_CLIENT = ["client_admin", "client_engineer", "client_user", "procurement", "auditor"];

/** Roles that may be assigned; the server enforces the same list (membership_policy.roles_assignable). */
export function assignableRoles(session: Session | null | undefined, family: "operator" | "client" | "operator_in_client"): string[] {
  const four = fourRoles(session);
  if (family === "client") return four ? ["client_admin", "client_user"] : LEGACY_CLIENT;
  if (family === "operator_in_client") return four ? ["operator_engineer"] : ["operator_engineer", "operator_qa", "operator_support"];
  return four ? ["operator_admin", "operator_engineer"] : LEGACY_OPERATOR;
}
