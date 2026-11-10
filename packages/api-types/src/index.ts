/** Shared API types for the web portal and the mobile apps (generated from the OpenAPI schema). */
import type { components, paths } from "./schema";

export type { components, paths };
type S = components["schemas"];

export type Part = S["SparePart"];
export type Passport = S["Passport"];
export type Revision = S["Revision"];
export type RevisionContent = S["RevisionContent"];
export type EngineeringFile = S["EngineeringFile"];
export type FileVersion = S["FileVersion"];
export type Project = S["Project"];
export type Client = S["Client"];
export type Member = S["Member"];
export type AuditEvent = S["AuditEvent"];
export type RL1 = S["RL1"];
export type RL2 = S["RL2"];
export type RL3 = S["RL3"];
export type AcceptanceRow = S["AcceptanceRow"];
export type ManufacturingSpec = S["ManufacturingSpec"];
export type ProcessParameter = S["ProcessParameter"];
export type FieldOptions = S["FieldOptions"];
export type ProvenanceEntry = S["ProvenanceEntry"];
export type CloneChange = S["CloneChange"];
export type PartFieldValues = S["PartFieldValues"];
export type JobSheet = S["JobSheet"];
export type Report = S["Report"];
export type EditRequest = S["EditRequest"];
export type PartReviewEvent = S["ReviewEvent"];
export type Completeness = S["Completeness"];
export type LevelCompleteness = S["LevelCompleteness"];

export type Invitation = S["Invitation"];
export type InvitationInfo = S["InvitationInfo"];

/** GET /dashboard/summary/ — facts from the organisation's own records (no production statistics). */
export interface DashboardSummary {
  parts: { total: number; with_passport: number; by_category: Record<string, number> };
  passports: {
    total: number;
    open_drafts: number;
    by_publication: Record<string, number>;
    by_evidence_level: Record<string, number>;
    by_data_captured: Record<"none" | "rl1" | "rl2" | "rl3", number>;
  };
  documents: {
    total: number;
    by_kind: Record<string, number>;
    by_category: Record<string, number>;
    parts_with_3d: number;
    parts_with_drawing: number;
    parts_with_specification: number;
    parts_with_photo: number;
    parts_without_documents: number;
  };
  conversions: {
    queued: number;
    running: number;
    succeeded: number;
    failed: number;
    not_requested: number;
    failed_items: { file: string; title: string; part: string; part_number: string; passport: string | null }[];
  };
  recent_parts: Part[];
}

/** GET /auth/memberships/ row: an organisation the signed-in user belongs to, with counts. */
export interface MembershipSummary {
  tenant: { id: string; name: string; slug: string; kind: "operator" | "client"; hosting_model: "shared" | "dedicated" };
  role: string;
  current: boolean;
  counts: { parts: number; passports: number; draft_revisions: number };
}

export interface Paginated<T> { count: number; next: string | null; previous: string | null; results: T[] }

/** Error envelope returned by every endpoint. */
export interface ApiErrorBody { error: { code: string; message: string; details: Record<string, unknown>; request_id: string } }

export interface Session {
  user: { id: string; email: string; first_name: string; last_name: string };
  tenant: { id: string; name: string; slug: string; kind: "operator" | "client"; hosting_model: "shared" | "dedicated" };
  membership: { id: string; role: string };
  capabilities: string[];
  /** Aries Admin super-administrator workspaces (ADMIN_WORKSPACE_ENABLED): in a company (admin_workspace) or the Aries organisation. */
  admin_access?: { admin_workspace: boolean; file_decision?: string; can_enter_companies?: boolean; aries_slug?: string };
  /** four_roles: Aries Admin, Aries Engineer, Client Admin, Client User, with QA and feature permissions (FOUR_ROLE_MODEL_ENABLED). */
  role_model?: "four_roles" | "legacy";
}
export interface TokenResponse { access: string; refresh: string; session: Session }

/** Client service requests (manufacturing enquiries / requests and 3D scanning), operator intake and notifications. */
export type ServiceRequest = S["Request"];
export type ServiceRequestRow = S["RequestList"];
export type RequestEvent = S["Event"];
export type RequestAttachment = S["Attachment"];
export type IntakeEnvelope = S["Envelope"];
export type OperatorRequest = S["OperatorRequest"];
export type AppNotification = S["Notification"];
export interface NotificationList { unread: number; results: AppNotification[] }
export type InventoryImport = S["InventoryImport"];
export type InventoryImportRow = S["ImportRow"];
export type InventoryImportOptions = S["InventoryImportOptions"];
