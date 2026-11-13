"""Client spare-part submissions and Aries review (requirement update 2026-10; CLIENT_PART_SUBMISSIONS_ENABLED).

A Client Administrator creates a company record and other client users create a new-part proposal. Either way the part
is held as "Pending Aries review": origin=client, status=draft, no passport. Aries Engineers assigned to the client (and,
for project-limited engineers, to the part's project) are notified and may request more information, accept the part
into the engineering workflow (optionally linking a project and marking fields as verified) or decline it.

Nothing here grants engineering approval, publication or manufacturing eligibility: those live on the passport and stay
gated (OQ-35/OQ-36). Field provenance records who entered each value and whether Aries verified it.

Decision of 13 Nov 2026 (three ways to a passport):
1. New part from the client: the client enters what it knows and either submits it for approval or asks Aries to complete
   the missing details (`aries_completion_requested`). Approvers: an Aries Admin or Manager (approval queue in the Aries
   organisation) or an Aries Engineer covering the part. "Send back" (request_info) opens the next submission revision;
   only the person who submitted may resubmit. Approval accepts the part and creates its passport draft for Aries.
2. Scan request: Aries creates the part and passport; no approval (the engineer marks the passport complete).
3. Clone with a changed material: approved the same way as 1; on approval the manufacturing request is sent
   automatically on the client's behalf.
Parts an Aries member creates need no approval.
"""
import secrets

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.service import record
from apps.core.exceptions import DomainError
from apps.projects.scoping import allowed_project_ids_for
from apps.servicerequests.models import Notification
from apps.tenancy.models import Membership, Role, Tenant
from apps.tenancy.permissions import authoring_allowed

from .models import SparePart, SparePartReviewEvent

R = SparePart.Review
# Fields a client may supply (and later correct while the submission is open).
CLIENT_FIELDS = ["part_number", "name", "equipment_reference", "manufacturer", "application", "original_material",
                 "dimensions", "description", "project", "category"]
# Fields a submitter may mark "Unknown / not available".
UNKNOWN_ALLOWED = ["part_number", "equipment_reference", "manufacturer", "application", "original_material", "dimensions"]
# Engineering classifications that only Aries sets.
ARIES_ONLY_FIELDS = ["criticality", "status"]
PROVENANCE_FIELDS = CLIENT_FIELDS + ARIES_ONLY_FIELDS + ["proposed_material", "material_change_reason"]
# Clone (BR-033): master data copied from the source as reference; the client may change the descriptive ones.
CLONE_COPIED = ["name", "category", "equipment_reference", "manufacturer", "application", "original_material",
                "dimensions", "description", "project"]
CLONE_EDITABLE = ["name", "equipment_reference", "manufacturer", "application", "dimensions", "description"]
SNAPSHOT_FIELDS = ["part_number", "name", "category", "criticality", "status", "equipment_reference", "manufacturer",
                   "application", "original_material", "dimensions", "description", "project"]


def display_name(user) -> str:
    if user is None:
        return ""
    return user.get_full_name().strip() or user.email


def provisional_number(tenant) -> str:
    """Placeholder for an unknown part number (numbering scheme OQ-14 is open). Unique within the company."""
    while True:
        number = f"TBC-{timezone.now():%y%m}-{secrets.token_hex(3).upper()}"
        if not SparePart.objects.filter(tenant=tenant, part_number=number).exists():
            return number


def log(part: SparePart, action: str, user, note: str = "", side: str = "aries") -> None:
    """Append to the review history shown to the client and the reviewers (rows are immutable)."""
    SparePartReviewEvent.objects.create(tenant_id=part.tenant_id, created_by=user, part=part, action=action,
                                        note=(note or "").strip(), side=side)


def stamp(part: SparePart, fields, *, source: str, user, verified: bool = False) -> None:
    """Record who entered `fields` (client or Aries). A client change clears any earlier Aries verification."""
    now = timezone.now().isoformat()
    prov = dict(part.field_provenance or {})
    for f in fields:
        if f not in PROVENANCE_FIELDS:
            continue
        prov[f] = {"source": source, "entered_by": display_name(user), "entered_at": now,
                   "verified_by": display_name(user) if verified else None, "verified_at": now if verified else None}
    part.field_provenance = prov


def verify(part: SparePart, fields, user) -> list[str]:
    """Mark client-supplied values as verified by Aries without changing them."""
    now = timezone.now().isoformat()
    prov = dict(part.field_provenance or {})
    done = []
    for f in fields:
        if f not in PROVENANCE_FIELDS:
            continue
        entry = dict(prov.get(f) or {"source": "client", "entered_by": "", "entered_at": None})
        entry.update(verified_by=display_name(user), verified_at=now)
        prov[f] = entry
        done.append(f)
    part.field_provenance = prov
    return done


def reviewers(part: SparePart):
    """Aries Engineers active in the part's client company whose project scope covers the part (CN-002 D4).
    Parts without a project reach only company-wide engineers. Runs in the client's tenant context."""
    users = set()
    for m in Membership.objects.filter(tenant_id=part.tenant_id, role=Role.OPERATOR_ENGINEER, is_active=True,
                                       user__is_active=True).select_related("user"):
        if not authoring_allowed(m):  # QA-only engineers (four-role model) do not review submissions
            continue
        allowed = allowed_project_ids_for(part.tenant_id, m.user_id)
        if allowed is None or (part.project_id is not None and part.project_id in allowed):
            users.add(m.user)
    return users


def notify_reviewers(part: SparePart, event: str, body: str = "") -> None:
    """Notify every approver: the engineers who can review the part (link to the part in the client company) and the Aries
    Admins and Managers (link to the approval queue in the Aries organisation)."""
    from apps.servicerequests.services import operator_tenant

    users = reviewers(part)
    if users:
        notify(part, event, users, body=body)
    op = operator_tenant()
    admins = {m.user for m in Membership.objects.filter(tenant=op, role__in=[Role.OPERATOR_ADMIN, Role.OPERATOR_MANAGER], is_active=True,
                                                        user__is_active=True).select_related("user")} - users
    name = Tenant.objects.filter(pk=part.tenant_id).values_list("name", flat=True).first() or ""
    title = TITLES[event].format(part=f"{part.part_number} {part.name}")
    Notification.objects.bulk_create([
        Notification(recipient=u, title=f"{title} ({name})"[:200], body=(body or "")[:500], link="/approvals", organisation_name=op.name)
        for u in admins])


def submitter_recipients(part: SparePart):
    users = {m.user for m in Membership.objects.filter(tenant_id=part.tenant_id, role=Role.CLIENT_ADMIN, is_active=True,
                                                       user__is_active=True).select_related("user")}
    if part.submitted_by and Membership.objects.filter(tenant_id=part.tenant_id, user=part.submitted_by, is_active=True).exists():
        users.add(part.submitted_by)
    return users


TITLES = {
    "submitted": "New spare part waiting for approval: {part}",
    "completion": "Client asks Aries to complete the details: {part}",
    "cloned": "Clone waiting for approval: {part}",
    "resubmitted": "Spare part resubmitted for approval: {part}",
    "info_requested": "Sent back for changes: {part}",
    "accepted": "Spare part approved: {part}",
    "declined": "Spare part submission declined: {part}",
}


def notify(part: SparePart, event: str, recipients, body: str = "") -> None:
    name = Tenant.objects.filter(pk=part.tenant_id).values_list("name", flat=True).first() or ""
    title = TITLES[event].format(part=f"{part.part_number} {part.name}")[:200]
    Notification.objects.bulk_create([
        Notification(recipient=u, title=title, body=body[:500], link=f"/parts/{part.pk}", organisation_name=name)
        for u in recipients])


def submission_kind_for(membership) -> str:
    return SparePart.SubmissionKind.RECORD if membership.role == Role.CLIENT_ADMIN else SparePart.SubmissionKind.PROPOSAL


def check_client_may_edit(request, part: SparePart) -> None:
    """Clients edit only their organisation's own open submissions; other client users only their own proposals."""
    if part.origin != SparePart.Origin.CLIENT:
        raise DomainError("aries_controlled_record", "This spare part is maintained by Aries Engineering. Send an enquiry "
                          "or add a supporting document instead.", http_status=403)
    if part.review_state not in SparePart.OPEN_REVIEW:
        raise DomainError("submission_locked", "This submission has been reviewed by Aries and can no longer be changed.",
                          http_status=403)
    if request.membership.role != Role.CLIENT_ADMIN and part.submitted_by_id != request.user.pk:
        raise DomainError("not_your_submission", "Only the person who submitted this proposal, or a Client Administrator, "
                          "can change it.", http_status=403)


def _close(part: SparePart, request, state: str, note: str) -> None:
    part.review_state = state
    part.reviewed_by = request.user
    part.reviewed_at = timezone.now()
    part.review_note = note


def request_info(request, part: SparePart, message: str) -> SparePart:
    _require_open(part)
    if not message.strip():
        raise DomainError("message_required", "Say what information is needed.", http_status=400)
    _close(part, request, R.INFO_REQUESTED, message.strip())
    part.submission_revision += 1  # "send back": the corrected submission is the next revision
    part.save(update_fields=["review_state", "reviewed_by", "reviewed_at", "review_note", "submission_revision", "updated_at"])
    record(request, "spare_part.info_requested", obj=part, tenant=part.tenant,
           data={"message": message.strip()[:300], "next_revision": part.submission_revision})
    log(part, SparePartReviewEvent.Action.INFO_REQUESTED, request.user, message)
    notify(part, "info_requested", submitter_recipients(part), body=message.strip())
    return part


def accept(request, part: SparePart, *, project=None, verified_fields=(), note: str = "") -> SparePart:
    """Approve the client submission: the part enters the engineering workflow and its passport draft is created for
    Aries to complete. A clone's manufacturing request is sent automatically on the client's behalf. Publication and
    manufacturing eligibility are untouched (OQ-36)."""
    _require_open(part)
    fields = ["review_state", "reviewed_by", "reviewed_at", "review_note", "field_provenance", "updated_at"]
    if project is not None and project.pk != part.project_id:
        part.project = project
        stamp(part, ["project"], source="aries", user=request.user, verified=True)
        fields.append("project")
    verified = verify(part, verified_fields, request.user)
    _close(part, request, R.ACCEPTED, note.strip())
    with transaction.atomic():
        part.save(update_fields=fields)
        record(request, "spare_part.accepted", obj=part, tenant=part.tenant,
               data={"project": str(part.project_id) if part.project_id else None, "verified_fields": verified,
                     "revision": part.submission_revision})
        log(part, SparePartReviewEvent.Action.ACCEPTED, request.user, note)
        from apps.passports.approval import create_for_part

        passport = create_for_part(request, part)
        sent = send_manufacturing_request(request, part, passport) if part.submission_kind == SparePart.SubmissionKind.CLONE else None
    body = note.strip()
    if sent is not None:
        body = (f"Manufacturing request {sent.reference} was sent to Aries automatically. " + body).strip()
    notify(part, "accepted", submitter_recipients(part), body=body)
    return part


def send_manufacturing_request(request, part: SparePart, passport):
    """Approved clone: the manufacturing request goes to Aries automatically, in the client's name (the submitter)."""
    from apps.servicerequests import services as svc

    kind, _ = svc.classify(part)  # an enquiry until the passport is published and eligible (OQ-36)
    requester = part.submitted_by or request.user
    proposed = part.proposed_material and not same(part.proposed_material, part.original_material)
    return svc.create_request(
        request, tenant=part.tenant, requested_by=requester, kind=kind, part=part, passport=passport,
        passport_revision_number=1, part_number=part.part_number, part_name=part.name,
        publication_state_at_submission=passport.publication_state, eligibility_at_submission=passport.manufacturing_eligibility,
        material_option="proposed" if proposed else "original", original_material=part.original_material,
        proposed_material=part.proposed_material if proposed else "", material_change_reason=part.material_change_reason if proposed else "",
        remarks=f"Sent automatically when Aries approved clone {part.part_number} of {part.source_part_number}.")


def decline(request, part: SparePart, reason: str) -> SparePart:
    _require_open(part)
    if not reason.strip():
        raise DomainError("reason_required", "Give a reason for declining.", http_status=400)
    _close(part, request, R.DECLINED, reason.strip())
    part.save(update_fields=["review_state", "reviewed_by", "reviewed_at", "review_note", "updated_at"])
    record(request, "spare_part.declined", obj=part, tenant=part.tenant, data={"reason": reason.strip()[:300]})
    log(part, SparePartReviewEvent.Action.DECLINED, request.user, reason)
    notify(part, "declined", submitter_recipients(part), body=reason.strip())
    return part


def verify_fields(request, part: SparePart, fields) -> SparePart:
    if part.origin != SparePart.Origin.CLIENT:
        raise DomainError("not_a_submission", "Only client-submitted values need verification.", http_status=400)
    done = verify(part, fields, request.user)
    part.save(update_fields=["field_provenance", "updated_at"])
    record(request, "spare_part.fields_verified", obj=part, tenant=part.tenant, data={"fields": done})
    log(part, SparePartReviewEvent.Action.VERIFIED, request.user, ", ".join(done))
    return part


def resubmit(request, part: SparePart, message: str) -> SparePart:
    check_client_may_edit(request, part)
    if part.submitted_by_id and part.submitted_by_id != request.user.pk:
        raise DomainError("not_your_submission", "Only the person who filled in and submitted these details can resubmit them.",
                          http_status=403)
    if part.review_state != R.INFO_REQUESTED:
        raise DomainError("not_requested", "Aries has not asked for more information on this submission.")
    part.review_state = R.PENDING
    part.save(update_fields=["review_state", "updated_at"])
    record(request, "spare_part.resubmitted", obj=part, tenant=part.tenant,
           data={"message": message.strip()[:300], "revision": part.submission_revision})
    log(part, SparePartReviewEvent.Action.RESUBMITTED, request.user, message, side="client")
    notify_reviewers(part, "resubmitted", body=message.strip())
    return part


def _require_open(part: SparePart) -> None:
    if part.origin != SparePart.Origin.CLIENT or part.review_state not in SparePart.OPEN_REVIEW:
        raise DomainError("not_pending_review", "This spare part is not waiting for Aries review.")


def _value(v):
    return str(v.pk) if hasattr(v, "pk") else v


def snapshot(part: SparePart) -> dict:
    """The source part as it was when cloned (kept permanently with the clone)."""
    snap = {f: _value(getattr(part, f)) for f in SNAPSHOT_FIELDS}
    snap["project_name"] = part.project.name if part.project_id else ""
    return snap


def same(a, b) -> bool:
    return str(a or "").strip().lower() == str(b or "").strip().lower()


def clone(request, source: SparePart, data: dict) -> SparePart:
    """Create a new part linked to `source` (BR-033 customisation). The source part, its files and its passport are
    never modified. Nothing is inherited that would imply approval: no passport, evidence, publication or eligibility;
    criticality is left for Aries. The clone starts as Pending Aries review."""
    from apps.passports.models import DigitalPassport

    if source.review_state not in (R.NOT_REQUIRED, R.ACCEPTED):
        raise DomainError("source_not_accepted", "Only parts that Aries has accepted can be cloned.")
    number = str(data.get("part_number") or "").strip()
    if not number:
        raise DomainError("part_number_required", "Enter a new part number for the clone.",
                          details={"part_number": ["Required."]}, http_status=400)
    duplicate = DomainError("duplicate_part_number", "This part number already exists in your organisation.",
                            details={"part_number": ["This part number already exists in your organisation."]}, http_status=400)
    if SparePart.objects.filter(tenant=request.tenant, part_number__iexact=number).exists():
        raise duplicate
    proposed = str(data.get("proposed_material") or "").strip()
    reason = str(data.get("material_change_reason") or "").strip()
    if proposed and not same(proposed, source.original_material) and not reason:
        raise DomainError("reason_required", "Give the reason for the material change.",
                          details={"material_change_reason": ["Required when a new material is proposed."]}, http_status=400)
    passport = DigitalPassport.objects.filter(part=source).first()
    revision = passport.revisions.order_by("-revision_number").first() if passport else None
    part = SparePart(tenant=request.tenant, created_by=request.user, part_number=number, origin=SparePart.Origin.CLIENT,
                     review_state=R.PENDING, submission_kind=SparePart.SubmissionKind.CLONE, status=SparePart.Status.DRAFT,
                     criticality=SparePart.Criticality.UNKNOWN, submitted_by=request.user, submitted_at=timezone.now(),
                     source_part=source, source_part_number=source.part_number,
                     source_passport_number=passport.passport_number if passport else "",
                     source_revision_number=revision.revision_number if revision else None,
                     source_snapshot=snapshot(source), proposed_material=proposed, material_change_reason=reason,
                     client_remarks=str(data.get("client_remarks") or "").strip()[:2000])
    for f in CLONE_COPIED:
        value = data[f] if f in CLONE_EDITABLE and data.get(f) is not None else getattr(source, f)
        setattr(part, f, value.strip() if isinstance(value, str) else value)
    if data.get("project"):  # post-UAT D-21: the clone may go to another project of the company the requester may use
        from apps.projects.models import Project
        from apps.projects.scoping import project_allowed

        project = Project.objects.filter(tenant=request.tenant, pk=data["project"]).first()
        if project is None or not project_allowed(request, project.pk):
            raise DomainError("invalid_project", "Choose one of your organisation's projects.", details={"project": ["Not found."]},
                              http_status=400)
        part.project = project
    if not part.name:
        raise DomainError("name_required", "Enter a part name.", details={"name": ["Required."]}, http_status=400)
    changed = [f for f in [*CLONE_EDITABLE, "project"] if not same(getattr(part, f), getattr(source, f))]
    inherited = [f for f in CLONE_COPIED if f not in changed and getattr(part, f) not in ("", None)]
    stamp(part, inherited, source="inherited", user=request.user)
    stamp(part, ["part_number", *changed] + (["proposed_material", "material_change_reason"] if proposed else []),
          source="client", user=request.user)
    try:
        with transaction.atomic():
            part.save()
            log(part, SparePartReviewEvent.Action.CLONED, request.user, part.client_remarks, side="client")
            record(request, "spare_part.cloned", obj=part, data={
                "source_part": str(source.pk), "source_part_number": source.part_number, "changed_fields": changed,
                "proposed_material": proposed, "source_passport": part.source_passport_number,
                "source_revision": part.source_revision_number})
    except IntegrityError:
        raise duplicate
    was = source.original_material or "not recorded"
    material = f" Proposed material: {proposed} (was {was})." if proposed else ""
    notify_reviewers(part, "cloned", body=f"Cloned from {source.part_number}.{material}")
    return part


def clone_changes(part: SparePart) -> list[dict]:
    """Original (snapshot at clone time) versus the clone's current values, field by field."""
    snap = part.source_snapshot or {}
    rows = []
    for f in CLONE_EDITABLE + ["project"]:
        before, after = snap.get(f), _value(getattr(part, f))
        rows.append({"field": f, "original": "" if before is None else str(before), "clone": "" if after is None else str(after),
                     "changed": not same(before, after)})
    if part.proposed_material:
        rows.append({"field": "material", "original": snap.get("original_material") or "", "clone": part.proposed_material,
                     "changed": not same(snap.get("original_material"), part.proposed_material)})
    return rows
