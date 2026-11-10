"""Aries Admin super-administrator workspaces in client companies (ADMIN_WORKSPACE_ENABLED, business decision of
2026-10-29; access-test only; a proposed revision of OQ-37 and of CN-002 D3, documented in AccessTest/ADMIN-SUPER-ACCESS-POLICY.md).

How it works without weakening tenant isolation:
- The Aries Admin works inside a client company through an ordinary membership of that company with the role
  `operator_admin` (created for every active client company when the Admin opens the company list, signs in or switches;
  each creation is audited in the company's trail and in the Aries trail). Every request then runs inside that company's
  tenant context, so PostgreSQL row-level security, project scoping and all service rules apply unchanged; nothing is
  read across companies and no RLS policy is relaxed.
- With the switch off these memberships are unusable: no sign-in, no switch, no capabilities (token refresh fails).
- Capabilities in a client company: the platform-administration ones the role already had there, plus the engineering-
  platform operations of ADMIN_WORKSPACE_GRANTS (apps.tenancy.permissions). Independent sign-off stays with others:
  no edit-request review, no feasibility/recommendation technical review, no QA job-sheet review, no photo-origin
  decisions; passport approval (OQ-35) and manufacturing release (OQ-36) stay closed for everyone; self-approval checks
  in the services still apply.
- Confidential file content (CAD originals, 3D derivatives and viewer, photos and thumbnails, PDF documents and drawings,
  passport reports that embed model views and attached documents, request attachments) stays closed to the Aries Admin
  in a company until a documented authorization decision for that company is configured in ADMIN_FILE_ACCESS_DECISIONS
  ("slug=decision reference, ..."). File metadata (titles, versions, sizes) is visible.
"""
from django.conf import settings
from django.db import transaction

from .context import tenant_context
from .models import Membership, Role, Tenant


def enabled() -> bool:
    return bool(getattr(settings, "ADMIN_WORKSPACE_ENABLED", False))


def is_platform_admin(user) -> bool:
    """An active Aries Admin membership in the operator organisation."""
    return user is not None and Membership.objects.filter(user=user, role=Role.OPERATOR_ADMIN, is_active=True,
                                                          tenant__kind=Tenant.Kind.OPERATOR).exists()


def is_admin_workspace(membership) -> bool:
    return membership is not None and membership.role == Role.OPERATOR_ADMIN and membership.tenant.kind == Tenant.Kind.CLIENT


def usable(membership) -> bool:
    """False for an Aries Admin client-company membership while the switch is off (or the person is no longer Aries Admin)."""
    return not is_admin_workspace(membership) or (enabled() and is_platform_admin(membership.user))


def file_decisions() -> dict:
    raw = getattr(settings, "ADMIN_FILE_ACCESS_DECISIONS", "") or ""
    out = {}
    for item in raw.split(","):
        slug, _, ref = item.partition("=")
        if slug.strip() and ref.strip():
            out[slug.strip()] = ref.strip()
    return out


def file_decision(tenant) -> str:
    """The documented decision reference that opens confidential file content of this company to the Aries Admin ("" = none)."""
    return file_decisions().get(getattr(tenant, "slug", ""), "")


def file_content_blocked(membership) -> bool:
    """Confidential file content is closed for this membership (only Aries Admin company workspaces without a decision)."""
    return is_admin_workspace(membership) and not file_decision(membership.tenant)


def file_content_blocked_for(user, tenant) -> bool:
    """Same rule for requests handled from the Aries organisation (request attachments): an Aries Admin, a company
    without a documented decision. Assigned engineers, QA and support are unaffected."""
    return is_platform_admin(user) and not Membership.objects.filter(
        user=user, tenant=tenant, is_active=True, role__in=[Role.OPERATOR_ENGINEER, Role.OPERATOR_QA, Role.OPERATOR_SUPPORT]
    ).exists() and not file_decision(tenant)


def without_workspaces(qs):
    """Membership querysets for member lists and counts: Aries Admin company workspaces are platform access, not company
    members, so they are not listed or counted (and so not manageable by the company). Every creation is in the company's
    audit trail (admin.workspace_membership_created)."""
    return qs.exclude(role=Role.OPERATOR_ADMIN, tenant__kind=Tenant.Kind.CLIENT)


BLOCKED = ("file_access_not_authorized", "Confidential file content of this company is not open to the Aries Admin until a "
           "documented authorization decision exists (OQ-37 / contractual confidentiality).")


def ensure_workspaces(user) -> int:
    """Give an Aries Admin a membership in every active client company that lacks one. Returns how many were created."""
    if not (enabled() and is_platform_admin(user)):
        return 0
    from apps.audit.service import record

    have = set(Membership.objects.filter(user=user).values_list("tenant_id", flat=True))
    op = Tenant.objects.filter(kind=Tenant.Kind.OPERATOR).order_by("created_at").first()
    created = 0
    for t in Tenant.objects.filter(kind=Tenant.Kind.CLIENT, status=Tenant.Status.ACTIVE).exclude(pk__in=have):
        with transaction.atomic():
            m = Membership.objects.create(user=user, tenant=t, role=Role.OPERATOR_ADMIN, created_by=user)
            data = {"role": Role.OPERATOR_ADMIN, "company": t.name, "reason": "Aries Admin super-administrator workspace (ADMIN_WORKSPACE_ENABLED)"}
            with tenant_context(t):
                record(None, "admin.workspace_membership_created", actor=user, tenant=t, obj_type="membership", obj_id=m.pk, data=data)
            if op is not None:
                with tenant_context(op):
                    record(None, "admin.workspace_membership_created", actor=user, tenant=op, obj_type="tenant", obj_id=t.pk, data=data)
        created += 1
    return created
