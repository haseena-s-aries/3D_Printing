"""Role-to-capability map (BRD v0.4 Section I role matrix) and DRF permission classes.

Actions governed by open business decisions are not granted here; they call apps.policies,
which refuses them until the decision is recorded.
"""
from django.conf import settings
from rest_framework.permissions import BasePermission

from . import admin_workspace
from .models import Role, Tenant

R = Role
ALL_ROLES = set(Role)

# CN-002: Aries Admin (operator_admin) administers the platform but holds no engineering edit capability; Aries
# Engineers (operator_engineer) do engineering work only in assigned client companies (and projects, see
# apps.projects.scoping); clients add supporting documents but never change Aries-controlled engineering files.
CAPABILITIES: dict[str, set] = {
    "clients.view": {R.OPERATOR_ADMIN},
    "clients.manage": {R.OPERATOR_ADMIN},
    # Administrative inventory summaries across client companies: read-only, audited, no documents, notes, CAD or
    # approvals. Opening full client records stays disabled until OQ-37 (support-access consent) is decided.
    "inventory.admin_overview": {R.OPERATOR_ADMIN},
    "registrations.review": {R.OPERATOR_ADMIN},
    # Assign/remove Aries staff to client companies and projects (never their own account).
    "assignments.manage": {R.OPERATOR_ADMIN},
    "users.view": {R.OPERATOR_ADMIN, R.CLIENT_ADMIN},
    "users.manage": {R.OPERATOR_ADMIN, R.CLIENT_ADMIN},
    "projects.view": ALL_ROLES,
    # D2: Aries Engineers manage scanning/digitisation projects; clients view progress and submit requests.
    "projects.manage": {R.OPERATOR_ENGINEER},
    "parts.view": ALL_ROLES,
    "parts.manage": {R.OPERATOR_ENGINEER},
    # Client spare-part submissions and clones (CN-003, FR-04 amended; CLIENT_PART_SUBMISSIONS_ENABLED). Client
    # Administrators and Client Engineers by role; a Client User only with Membership.part_submission_allowed.
    # Everything stays "Pending Aries review" and never carries engineering approval, publication or eligibility.
    "parts.submit": {R.CLIENT_ADMIN, R.CLIENT_ENGINEER, R.CLIENT_USER},
    # Aries Engineers review submissions of their assigned clients/projects (request details, accept, decline).
    "parts.review": {R.OPERATOR_ENGINEER},
    "passports.view": ALL_ROLES,
    # OQ-05: operator creates passport drafts; client approves (approval rules pending OQ-35).
    "passports.edit_draft": {R.OPERATOR_ENGINEER},
    # D-13: detailed engineering notes (conflict register) of a revision. Other roles only see that a review is pending.
    "passports.view_engineering_notes": {R.OPERATOR_ADMIN, R.OPERATOR_ENGINEER, R.OPERATOR_QA, R.CLIENT_ADMIN,
                                         R.CLIENT_ENGINEER, R.AUDITOR},
    "files.view": ALL_ROLES,
    # Engineering master files (STEP, DWG, drawings, specifications, inspection, certificates): Aries Engineers only.
    "files.upload": {R.OPERATOR_ENGINEER},
    # D1: clients may add supporting documents and photographs (PDF/JPEG/PNG, category photo/other) and manage only
    # those; they cannot replace, edit, reclassify or version Aries-controlled files (apps.files.api).
    "files.upload_supporting": {R.CLIENT_ADMIN, R.CLIENT_ENGINEER},
    # OQ-07: authorised CAD and specification downloads (watermark policy still open, OQ-33).
    "files.download_original": {R.OPERATOR_ADMIN, R.OPERATOR_ENGINEER, R.OPERATOR_QA, R.CLIENT_ADMIN, R.CLIENT_ENGINEER},
    "files.download_derivative": {R.OPERATOR_ADMIN, R.OPERATOR_ENGINEER, R.OPERATOR_QA, R.OPERATOR_SUPPORT,
                                  R.CLIENT_ADMIN, R.CLIENT_ENGINEER, R.CLIENT_USER},
    "audit.view": {R.OPERATOR_ADMIN, R.CLIENT_ADMIN, R.AUDITOR},
    # Client service requests (manufacturing enquiries, 3D scanning). Submitters per BR-015; client users view only.
    "requests.view": {R.CLIENT_ADMIN, R.CLIENT_ENGINEER, R.CLIENT_USER, R.PROCUREMENT, R.AUDITOR},
    "requests.create": {R.CLIENT_ADMIN, R.CLIENT_ENGINEER, R.PROCUREMENT},
    # Operator intake queue; opening a request also needs an active assignment to that client (checked per request).
    "requests.handle": {R.OPERATOR_ADMIN, R.OPERATOR_ENGINEER, R.OPERATOR_QA, R.OPERATOR_SUPPORT},
    # CN-004 draft manufacturing job sheets (internal to Aries). Engineers prepare and revise; QA may read. QA review,
    # issue and production release are separate restricted capabilities that stay unusable while OQ-36 is open.
    # CN-005 Digital Passport PDF reports. Internal (Aries-confidential) variant: Aries Engineers generate, QA reads.
    # Client-facing variant: Client Administrator and Client Engineer generate and download; Client Users preview only
    # (page images). Procurement and Auditor hold no 3D/preview right in CN-002, so they get no report access.
    "reports.generate_internal": {R.OPERATOR_ENGINEER},
    "reports.view_internal": {R.OPERATOR_ENGINEER, R.OPERATOR_QA},
    "reports.generate_client": {R.OPERATOR_ENGINEER, R.CLIENT_ADMIN, R.CLIENT_ENGINEER},
    "reports.download_client": {R.OPERATOR_ENGINEER, R.OPERATOR_QA, R.CLIENT_ADMIN, R.CLIENT_ENGINEER},
    "reports.preview_client": {R.OPERATOR_ENGINEER, R.OPERATOR_QA, R.CLIENT_ADMIN, R.CLIENT_ENGINEER, R.CLIENT_USER},
    # Report withdrawal (post-UAT D-19): Aries engineering authority only; never a client role.
    "reports.withdraw": {R.OPERATOR_ENGINEER},
    # CN-006 controlled edit requests (EDIT_REQUESTS_ENABLED). Requesters: Aries Engineers, Client Administrators and
    # Client Engineers, and Client Users permitted to submit parts. Reviewers: only Aries Engineers explicitly authorised
    # per client company (Membership.edit_reviewer); never the Aries Admin role, never the requester (self-approval).
    "edits.request": {R.OPERATOR_ENGINEER, R.CLIENT_ADMIN, R.CLIENT_ENGINEER, R.CLIENT_USER},
    "edits.review": {R.OPERATOR_ENGINEER},
    "jobsheets.view": {R.OPERATOR_ENGINEER, R.OPERATOR_QA},
    "jobsheets.prepare": {R.OPERATOR_ENGINEER},
    "jobsheets.qa_review": {R.OPERATOR_QA},
    # CN-007 bulk inventory import (INVENTORY_IMPORT_ENABLED). Assigned Aries Engineers within their company/project
    # scope; a Client Administrator only with Membership.inventory_import_allowed. The Aries Admin sees administrative
    # summaries across companies and may discard open previews, but imports nothing into a client company itself.
    "inventory.import": {R.OPERATOR_ENGINEER, R.CLIENT_ADMIN},
    "inventory.import_admin": {R.OPERATOR_ADMIN},
    # CN-007 Phase 2 part intelligence (PART_INTELLIGENCE_ENABLED): Aries-internal suggestions, never shown to clients.
    # Assigned Aries Engineers see the analysis and may request AI suggestions (where external AI is permitted for the
    # company) and record the verified classification. The Aries Admin sees AI usage and estimated cost only.
    "intelligence.view": {R.OPERATOR_ENGINEER},
    "intelligence.assess": {R.OPERATOR_ENGINEER},
    # recording the engineer-verified classification is an engineering decision (not given to the Aries Admin workspace)
    "intelligence.classify": {R.OPERATOR_ENGINEER},
    "intelligence.usage_admin": {R.OPERATOR_ADMIN},
    # CN-007 Phase 3: technical review of manufacturing feasibility screenings (not formal engineering approval).
    "intelligence.review": {R.OPERATOR_ENGINEER},
    # CN-007 role-based AI access (AI_CLIENT_ACCESS_ENABLED; docs/brd-change-notes/CN-007-ai-access-model.md).
    # Aries Admin: aggregate management dashboard and client workspace on/off; no review or sharing authority.
    "ai.management": {R.OPERATOR_ADMIN},
    # Assigned Aries Engineers: approve a reviewed result for client sharing, share and withdraw it (disclosure only).
    "ai.share": {R.OPERATOR_ENGINEER},
    # Client workspace. The service additionally requires the company to be switched on and, except for the Client
    # Admin, member access granted by the Client Admin (Client Engineers allowed by default).
    "ai.workspace": {R.CLIENT_ADMIN, R.CLIENT_ENGINEER, R.PROCUREMENT, R.CLIENT_USER, R.AUDITOR},
    "ai.request": {R.CLIENT_ADMIN, R.CLIENT_ENGINEER},
    "ai.prices": {R.CLIENT_ADMIN, R.PROCUREMENT},
    "ai.reports": {R.CLIENT_ADMIN, R.CLIENT_ENGINEER, R.PROCUREMENT},
    "ai.members": {R.CLIENT_ADMIN},
    # Per-company consent for Aries Admin inventory thumbnails (ADMIN_THUMBNAIL_CONSENT_ENABLED): only the company's own
    # Client Administrator decides. The Aries Admin can never grant it on the client's behalf.
    "files.admin_thumbnail_consent": {R.CLIENT_ADMIN},
    # Provenance-aware contract route for those thumbnails (ADMIN_THUMBNAIL_PROVENANCE_ENABLED). Inside a client company:
    # the Aries Engineer who uploaded a photo version may claim Aries captured it; QA (never the claimant) confirms: an Aries
    # Engineer with CanPerformQA (four-role model, QA_GRANTS below) or a legacy Aries QA account.
    "files.origin_claim": {R.OPERATOR_ENGINEER},
    "files.origin_confirm": {R.OPERATOR_QA},
    # In the Aries organisation: an Aries Admin records a contract authorization; a different Aries Admin, or an Aries Engineer
    # with CanReviewContract (legacy: Aries QA), verifies it against the signed agreement (never the recorder).
    "contracts.thumbnail_view": {R.OPERATOR_ADMIN, R.OPERATOR_QA},
    "contracts.thumbnail_record": {R.OPERATOR_ADMIN},
    "contracts.thumbnail_verify": {R.OPERATOR_ADMIN, R.OPERATOR_QA},
    # Resolving a client's objection to that route is a separate authority: only Aries Admin, Aries QA, or Aries Engineers with
    # CanReviewContract (never CanPerformQA alone) named in
    # CONTRACT_OBJECTION_REVIEWERS, while CONTRACT_OBJECTION_AUTHORITY is set (deployment configuration, never granted in
    # the application). Verification confers no such right; with nothing configured every disputed route stays on hold.
    "contracts.objection_review": {R.OPERATOR_ADMIN, R.OPERATOR_QA},
}
# Aries Admin in a client company (ADMIN_WORKSPACE_ENABLED, apps.tenancy.admin_workspace): engineering-platform operations
# on top of what the role already holds there. Independent sign-off is deliberately absent (edits.review,
# intelligence.review, jobsheets.qa_review, files.origin_confirm); passport approval and manufacturing release stay closed.
ADMIN_WORKSPACE_GRANTS = {"projects.manage", "parts.manage", "parts.review", "passports.edit_draft", "edits.request", "inventory.import",
                          "intelligence.view", "intelligence.assess", "ai.share", "jobsheets.view", "jobsheets.prepare",
                          "reports.generate_internal", "reports.view_internal", "reports.generate_client", "reports.download_client",
                          "reports.preview_client", "reports.withdraw"}
# Capabilities that hand out confidential file content; closed to the Aries Admin in a company without a documented decision.
FILE_CONTENT_CAPABILITIES = {"files.download_original", "files.download_derivative", "reports.generate_internal", "reports.view_internal",
                             "reports.generate_client", "reports.download_client", "reports.preview_client"}
CONTRACT_CAPABILITIES = {"contracts.thumbnail_view", "contracts.thumbnail_record", "contracts.thumbnail_verify", "contracts.objection_review"}
PROVENANCE_CAPABILITIES = {"files.origin_claim", "files.origin_confirm"} | CONTRACT_CAPABILITIES
OPERATOR_TENANT_ONLY = {"clients.view", "clients.manage", "registrations.review", "assignments.manage",
                        "inventory.admin_overview", "inventory.import_admin", "intelligence.usage_admin", "ai.management"}
AI_ACCESS_CAPABILITIES = {"ai.management", "ai.share", "ai.workspace", "ai.request", "ai.prices", "ai.reports", "ai.members"}
CLIENT_AI_CAPABILITIES = {"ai.workspace", "ai.request", "ai.prices", "ai.reports", "ai.members"}
IMPORT_CAPABILITIES = {"inventory.import", "inventory.import_admin"}
SUBMISSION_CAPABILITIES = {"parts.submit", "parts.review"}
EDIT_CAPABILITIES = {"edits.request", "edits.review"}
INTELLIGENCE_CAPABILITIES = {"intelligence.view", "intelligence.assess", "intelligence.classify", "intelligence.review", "intelligence.usage_admin"}

# Four core roles (FOUR_ROLE_MODEL_ENABLED, AccessTest/FOUR-ROLE-MODEL.md). Legacy roles (Aries QA, Aries Support, Client Engineer,
# Procurement, Auditor) keep their rights above until their memberships are mapped; they are no longer offered.
LEGACY_ROLES = {R.OPERATOR_QA, R.OPERATOR_SUPPORT, R.CLIENT_ENGINEER, R.PROCUREMENT, R.AUDITOR}
# Aries Engineer permissions granted by the Aries Admin. CanPerformQA applies in a client company (origin claims) and in
# the Aries organisation (job-sheet QA from the intake queue, closed by OQ-36); CanReviewContract only in the Aries
# organisation; objection review is further limited to the deployment-designated reviewers (filtered below).
QA_GRANTS = {"files.origin_confirm", "jobsheets.qa_review"}
CONTRACT_REVIEW_GRANTS = {"contracts.thumbnail_view", "contracts.thumbnail_verify", "contracts.objection_review"}
# CanAuthorEngineering (Membership.engineering_authoring): the engineering work an Aries Engineer holds by role beyond read
# access, i.e. exactly what an Aries Engineer had and an Aries QA did not. Removed when the permission is off, so a converted
# QA membership keeps its QA rights without gaining authoring. Engineering review (edit_reviewer) stays a separate permission.
ENGINEERING_AUTHORING = {"projects.manage", "parts.manage", "parts.review", "passports.edit_draft", "files.upload", "files.origin_claim",
                         "reports.generate_internal", "reports.generate_client", "edits.request", "jobsheets.prepare", "inventory.import",
                         "intelligence.view", "intelligence.assess", "intelligence.classify", "intelligence.review", "ai.share",
                         "reports.withdraw"}
# Client User feature permissions (part submissions and edit requests stay with part_submission_allowed).
TECHNICAL_GRANTS = {"files.upload_supporting", "passports.view_engineering_notes", "requests.create", "ai.request", "ai.reports"}
PROCUREMENT_GRANTS = {"requests.create", "ai.prices", "ai.reports"}
AUDIT_GRANTS = {"audit.view", "passports.view_engineering_notes"}
PREVIEW_DOCUMENTS = {"files.download_derivative", "reports.preview_client"}
DOCUMENT_GRANTS = {"none": set(), "preview": PREVIEW_DOCUMENTS,
                   "full": PREVIEW_DOCUMENTS | {"files.download_original", "reports.generate_client", "reports.download_client"}}


def four_roles() -> bool:
    return bool(getattr(settings, "FOUR_ROLE_MODEL_ENABLED", False))


def granted_permissions(membership) -> set:
    """Capabilities added by the four-role permissions of this membership (before the feature switches below)."""
    if not four_roles():
        return set()
    if membership.role == R.OPERATOR_ENGINEER:
        out = set()
        if membership.qa_permitted:  # job sheets are reviewed from the Aries intake queue, origin claims inside the company
            out |= QA_GRANTS if membership.tenant.kind == Tenant.Kind.CLIENT else {"jobsheets.qa_review"}
        if membership.contract_reviewer and membership.tenant.kind == Tenant.Kind.OPERATOR:
            out |= CONTRACT_REVIEW_GRANTS
        return out
    if membership.role == R.CLIENT_USER:
        out = set(DOCUMENT_GRANTS.get(membership.document_access, PREVIEW_DOCUMENTS))
        for flag, grants in (("technical_access", TECHNICAL_GRANTS), ("procurement_access", PROCUREMENT_GRANTS), ("audit_access", AUDIT_GRANTS)):
            if getattr(membership, flag):
                out |= grants
        return out
    return set()


def authoring_allowed(membership) -> bool:
    """False only for an Aries Engineer whose engineering authoring the Aries Admin has switched off (four-role model)."""
    return not (four_roles() and membership.role == R.OPERATOR_ENGINEER and not membership.engineering_authoring)


def objection_reviewer(user) -> bool:
    """Named in the deployment's objection-review configuration (and an authority reference is set)."""
    reviewers = getattr(settings, "CONTRACT_OBJECTION_REVIEWERS", [])
    return bool(getattr(settings, "CONTRACT_OBJECTION_AUTHORITY", "")) and user is not None and user.email.lower() in reviewers


def capabilities_for(membership) -> list[str]:
    if membership is None or not admin_workspace.usable(membership):
        return []
    caps = {c for c, roles in CAPABILITIES.items() if membership.role in roles}
    if four_roles() and membership.role == R.CLIENT_USER:
        caps -= PREVIEW_DOCUMENTS  # document access is a feature permission (default: previews, as before)
    caps |= granted_permissions(membership)
    if not authoring_allowed(membership):
        caps -= ENGINEERING_AUTHORING
    if admin_workspace.is_admin_workspace(membership):
        caps |= ADMIN_WORKSPACE_GRANTS
    elif membership.role == R.OPERATOR_ADMIN and admin_workspace.enabled():
        caps |= {"jobsheets.view", "jobsheets.prepare"}  # draft job sheets from the Aries intake queue (gates stay closed, OQ-36)
    if membership.tenant.kind != Tenant.Kind.OPERATOR:
        caps -= OPERATOR_TENANT_ONLY
    if not getattr(settings, "CLIENT_PART_SUBMISSIONS_ENABLED", False):
        caps -= SUBMISSION_CAPABILITIES
    elif membership.role == R.CLIENT_USER and not membership.part_submission_allowed:
        caps.discard("parts.submit")
    if not getattr(settings, "EDIT_REQUESTS_ENABLED", False):
        caps -= EDIT_CAPABILITIES
    else:
        if membership.role == R.CLIENT_USER and not membership.part_submission_allowed:
            caps.discard("edits.request")
        if not membership.edit_reviewer or membership.tenant.kind != Tenant.Kind.CLIENT:
            caps.discard("edits.review")
    if not getattr(settings, "INVENTORY_IMPORT_ENABLED", False):
        caps -= IMPORT_CAPABILITIES
    elif membership.role == R.CLIENT_ADMIN and not membership.inventory_import_allowed:
        caps.discard("inventory.import")
    if not getattr(settings, "PART_INTELLIGENCE_ENABLED", False):
        caps -= INTELLIGENCE_CAPABILITIES
    if not getattr(settings, "ADMIN_THUMBNAIL_CONSENT_ENABLED", False) or membership.tenant.kind != Tenant.Kind.CLIENT:
        caps.discard("files.admin_thumbnail_consent")
    if not (getattr(settings, "ADMIN_THUMBNAIL_CONSENT_ENABLED", False) and getattr(settings, "ADMIN_THUMBNAIL_PROVENANCE_ENABLED", False)):
        caps -= PROVENANCE_CAPABILITIES
    elif membership.tenant.kind == Tenant.Kind.CLIENT:
        caps -= CONTRACT_CAPABILITIES
    else:
        caps -= {"files.origin_claim", "files.origin_confirm"}
        if not objection_reviewer(membership.user):
            caps.discard("contracts.objection_review")
    if not (getattr(settings, "AI_CLIENT_ACCESS_ENABLED", False) and getattr(settings, "PART_INTELLIGENCE_ENABLED", False)):
        caps -= AI_ACCESS_CAPABILITIES
    elif membership.tenant.kind != Tenant.Kind.CLIENT:
        caps -= CLIENT_AI_CAPABILITIES | {"ai.share"}
    if admin_workspace.file_content_blocked(membership):
        caps -= FILE_CONTENT_CAPABILITIES
    return sorted(caps)


def has_capability(request, capability: str) -> bool:
    return capability in capabilities_for(getattr(request, "membership", None))


class HasCapability(BasePermission):
    """Views declare `capabilities = {"list": "parts.view", ...}`. Actions not declared are denied."""

    message = "Your role does not allow this action."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated and getattr(request, "membership", None)):
            return False
        action = getattr(view, "action", None) or request.method.lower()
        needed = getattr(view, "capabilities", {}).get(action)
        return bool(needed) and has_capability(request, needed)
