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

export const roleLabel = (role: string): string => ROLE_LABELS[role] ?? role.replace(/_/g, " ");
