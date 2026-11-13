"""Passport revision approval (business decision of 12 Nov 2026; replaces the OQ-35 seam for submit and approve).

Flow: draft -> submitted -> approved, or submitted -> draft again ("send back", with a note for the author).
- Submit: an Aries Engineer who may edit the passport (passports.edit_draft, project scope applies).
- Approve / send back (passports.approve): an Aries Admin or Aries Manager (from the Aries organisation, the approvals
  queue in apps.passports.approval_api) or an Aries Engineer with access to the passport's project (inside the client
  company). Never the person who submitted the revision (separation of duties).
- Approving supersedes the previously approved revision (approved revisions are immutable, database trigger) and marks the
  passport "Engineering approved". Publication and manufacturing eligibility are NOT changed: manufacturing
  authorisation stays governed by OQ-36.
Every step is audited in the client company's trail and notifies the people concerned.
"""
from django.db import transaction
from django.utils import timezone

from apps.audit.service import record
from apps.core.exceptions import DomainError
from apps.servicerequests.models import Notification
from apps.tenancy.models import Membership, Role, Tenant

from .models import DigitalPassport, PassportRevision

RS, PS = PassportRevision.Status, DigitalPassport.PublicationState


def _operator_tenant():
    return Tenant.objects.filter(kind=Tenant.Kind.OPERATOR).order_by("created_at").first()


def _label(passport: DigitalPassport, revision: PassportRevision) -> str:
    return f"{passport.passport_number} rev {revision.revision_number}"


def _notify(users, title: str, body: str, link: str, organisation: str) -> None:
    Notification.objects.bulk_create([Notification(recipient=u, title=title[:200], body=body[:500], link=link,
                                                   organisation_name=organisation) for u in users])


def approvers(passport: DigitalPassport, exclude_user_id=None) -> tuple[set, set]:
    """(Aries Admins and Managers, Aries Engineers of this company with access to the passport's project). Runs in the
    client company's tenant context."""
    from apps.projects.scoping import allowed_project_ids_for

    op = _operator_tenant()
    platform = {m.user for m in Membership.objects.filter(tenant=op, role__in=[Role.OPERATOR_ADMIN, Role.OPERATOR_MANAGER],
                                                         is_active=True, user__is_active=True).select_related("user")}
    project_id = passport.part.project_id
    engineers = set()
    for m in Membership.objects.filter(tenant_id=passport.tenant_id, role=Role.OPERATOR_ENGINEER, is_active=True,
                                       user__is_active=True).select_related("user"):
        allowed = allowed_project_ids_for(passport.tenant_id, m.user_id)
        if allowed is None or project_id in allowed:
            engineers.add(m.user)
    platform = {u for u in platform if u.pk != exclude_user_id}
    engineers = {u for u in engineers if u.pk != exclude_user_id}
    return platform, engineers


def submit(request, passport: DigitalPassport, revision: PassportRevision) -> PassportRevision:
    if revision.status != RS.DRAFT:
        raise DomainError("revision_not_draft", "Only a draft revision can be submitted for approval.", http_status=409)
    with transaction.atomic():
        revision.status, revision.submitted_by, revision.submitted_at = RS.SUBMITTED, request.user, timezone.now()
        revision.review_note = ""
        revision.save(update_fields=["status", "submitted_by", "submitted_at", "review_note", "updated_at"])
        passport.publication_state = PS.SUBMITTED
        passport.save(update_fields=["publication_state", "updated_at"])
        record(request, "passport.revision_submitted", obj=revision, tenant=passport.tenant,
               data={"passport": passport.passport_number, "revision_number": revision.revision_number})
    platform, engineers = approvers(passport, exclude_user_id=request.user.pk)
    org = passport.tenant.name
    title = f"Passport waiting for approval: {_label(passport, revision)}"
    body = f"{passport.title} ({org}) · submitted by {request.user.email}"
    # Admins and Managers decide from the Aries organisation's approval queue; engineers inside the client company
    op = _operator_tenant()
    _notify(platform, title, body, "/passport-approvals", op.name if op else org)
    _notify(engineers, title, body, f"/passports/{passport.pk}", org)
    return revision


def _check_reviewable(request, revision: PassportRevision) -> None:
    if revision.status != RS.SUBMITTED:
        raise DomainError("revision_not_submitted", "Only a revision submitted for approval can be approved or sent back.",
                          http_status=409)
    if revision.submitted_by_id and revision.submitted_by_id == request.user.pk:
        raise DomainError("separation_of_duties", "You submitted this revision; another approver must decide it.", http_status=403)


def approve(request, passport: DigitalPassport, revision: PassportRevision) -> PassportRevision:
    _check_reviewable(request, revision)
    with transaction.atomic():
        for old in passport.revisions.filter(status=RS.APPROVED).exclude(pk=revision.pk):
            old.status = RS.SUPERSEDED
            old.save(update_fields=["status", "updated_at"])
        revision.status, revision.approved_by, revision.approved_at = RS.APPROVED, request.user, timezone.now()
        revision.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
        passport.publication_state = PS.ENGINEERING_APPROVED
        passport.save(update_fields=["publication_state", "updated_at"])
        record(request, "passport.revision_approved", obj=revision, tenant=passport.tenant,
               data={"passport": passport.passport_number, "revision_number": revision.revision_number})
    if revision.submitted_by_id and revision.submitted_by_id != request.user.pk:
        _notify([revision.submitted_by], f"Passport approved: {_label(passport, revision)}",
                f"Approved by {request.user.email}.", f"/passports/{passport.pk}", passport.tenant.name)
    return revision


def send_back(request, passport: DigitalPassport, revision: PassportRevision, note: str) -> PassportRevision:
    _check_reviewable(request, revision)
    note = (note or "").strip()
    if not note:
        raise DomainError("note_required", "Tell the author what to change before sending the revision back.", http_status=400)
    with transaction.atomic():
        revision.status, revision.review_note = RS.DRAFT, note[:500]
        revision.save(update_fields=["status", "review_note", "updated_at"])
        has_approved = passport.revisions.filter(status=RS.APPROVED).exists()
        passport.publication_state = PS.REVISION_IN_PROGRESS if has_approved else PS.DRAFT
        passport.save(update_fields=["publication_state", "updated_at"])
        record(request, "passport.revision_returned", obj=revision, tenant=passport.tenant,
               data={"passport": passport.passport_number, "revision_number": revision.revision_number, "note": note[:500]})
    if revision.submitted_by_id:
        _notify([revision.submitted_by], f"Passport sent back: {_label(passport, revision)}", note,
                f"/passports/{passport.pk}", passport.tenant.name)
    return revision
