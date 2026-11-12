"""Service-request rules: classification, references, allowed transitions, history, envelope sync, notifications.

Every state change goes through `transition()`, which validates it against TRANSITIONS, appends a RequestEvent,
writes an audit event in the client's tenant, refreshes the operator envelope and notifies the other side.
Manufacturing requests (published AND eligible parts) can be acknowledged and answered, but review, release and
production steps do not exist here: they are governed by OQ-36 (policy seam, refused).
"""
from __future__ import annotations

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.audit.service import record
from apps.core.exceptions import DomainError
from apps.parts.models import SparePart
from apps.passports.models import DigitalPassport
from apps.tenancy.context import tenant_context
from apps.tenancy.models import OPERATOR_ROLES, Membership, Role, Tenant

from .models import ClientRequest, Notification, RequestEnvelope, RequestEvent

K, S = ClientRequest.Kind, ClientRequest.Status
ELIGIBLE = {DigitalPassport.Eligibility.ELIGIBLE, DigitalPassport.Eligibility.SUBJECT_TO_AUTHORISATION}
OPEN = {S.SUBMITTED, S.ACKNOWLEDGED, S.INFORMATION_REQUESTED, S.INFORMATION_PROVIDED, S.ANSWERED, S.SCHEDULED, S.IN_PROGRESS}
CLIENT_SUBMIT_ROLES = {Role.CLIENT_ADMIN, Role.CLIENT_ENGINEER, Role.PROCUREMENT}

# operator action -> (allowed kinds, allowed from-states, to-state, message required)
_ACK_FROM = {S.SUBMITTED}
_WORKING = {S.ACKNOWLEDGED, S.INFORMATION_PROVIDED}
OPERATOR_ACTIONS = {
    "acknowledge": ({K.ENQUIRY, K.MANUFACTURING, K.DIGITISATION, K.ASSESSMENT}, _ACK_FROM, S.ACKNOWLEDGED, False),
    "request_information": ({K.ENQUIRY, K.MANUFACTURING, K.DIGITISATION, K.ASSESSMENT}, _WORKING | {S.ANSWERED, S.SCHEDULED, S.IN_PROGRESS}, S.INFORMATION_REQUESTED, True),
    "respond": ({K.ENQUIRY, K.MANUFACTURING, K.ASSESSMENT}, _WORKING | {S.ANSWERED}, S.ANSWERED, True),
    "close": ({K.ENQUIRY, K.MANUFACTURING, K.ASSESSMENT}, OPEN - {S.SUBMITTED}, S.CLOSED, True),
    "schedule": ({K.DIGITISATION}, _WORKING, S.SCHEDULED, False),
    "start": ({K.DIGITISATION}, _WORKING | {S.SCHEDULED}, S.IN_PROGRESS, False),
    "complete": ({K.DIGITISATION}, {S.IN_PROGRESS}, S.COMPLETED, False),
    "decline": ({K.DIGITISATION}, OPEN - {S.SUBMITTED}, S.DECLINED, True),
}
CLIENT_WITHDRAW_FROM = {S.SUBMITTED, S.ACKNOWLEDGED, S.INFORMATION_REQUESTED, S.INFORMATION_PROVIDED}

EVENT_TITLES = {
    "submitted": "New {kind} {ref}",
    "acknowledged": "{ref} acknowledged",
    "information_requested": "More information needed for {ref}",
    "information_provided": "{ref}: client provided information",
    "answered": "Reply to {ref}",
    "closed": "{ref} closed",
    "scheduled": "{ref} scheduled",
    "in_progress": "{ref} in progress",
    "completed": "{ref} completed",
    "declined": "{ref} declined",
    "withdrawn": "{ref} withdrawn by the client",
    "client_message": "{ref}: new message from the client",
    "operator_message": "{ref}: new message from Aries",
    "project_created": "{ref}: project and draft part created",
    "handed_over": "{ref}: scanning work handed over to the digital passport",
}


def operator_tenant() -> Tenant:
    t = Tenant.objects.filter(kind=Tenant.Kind.OPERATOR).first()
    if t is None:
        raise DomainError("operator_missing", "The platform operator organisation is not configured.", http_status=500)
    return t


def classify(part) -> tuple[str, str]:
    """ENQUIRY unless the part has a published passport whose stored eligibility allows manufacturing."""
    passport = DigitalPassport.objects.filter(part=part).first()
    if passport is None:
        return K.ENQUIRY, "This part has no digital passport yet, so it is sent as an enquiry."
    if passport.publication_state != DigitalPassport.PublicationState.PUBLISHED:
        return K.ENQUIRY, "This part is not yet published in your manufacturing catalog, so it is sent as an enquiry."
    if passport.manufacturing_eligibility not in ELIGIBLE:
        return K.ENQUIRY, "This part is not currently eligible for manufacturing, so it is sent as an enquiry."
    return K.MANUFACTURING, "This part is published and eligible: the request needs engineering and QA review before any production."


def next_reference(tenant, kind: str) -> str:
    prefix = "DR" if kind == K.DIGITISATION else "AR" if kind == K.ASSESSMENT else "MR"
    year = timezone.now().year
    stem = f"{prefix}-{year}-"
    last = (ClientRequest.objects.filter(tenant=tenant, reference__startswith=stem).order_by("-reference")
            .values_list("reference", flat=True).first())
    n = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{stem}{n:05d}"


def material_change(request, part, d: dict) -> dict:
    """Material choice of a manufacturing enquiry. "original": nothing changes. "proposed": the proposal is linked to a
    clone of the part (an existing clone, or a new one when the requester may submit parts); without one the proposal
    is recorded on the enquiry for Aries to handle. The original part and passport are never modified."""
    from apps.parts import submissions
    from apps.parts.models import SparePart
    from apps.tenancy.permissions import has_capability

    option = d.pop("material_option", "original")
    proposed = d.pop("proposed_material", "").strip()
    reason = d.pop("material_change_reason", "").strip()
    linked_id = d.pop("linked_part", None)
    new_number = d.pop("new_part_number", "").strip()
    out = {"material_option": option, "original_material": part.original_material}
    if option != "proposed":
        return out
    if submissions.same(proposed, part.original_material):
        raise DomainError("same_material", "The proposed material is the same as the original material.",
                          details={"proposed_material": ["Same as the original material."]}, http_status=400)
    linked = None
    if linked_id:
        linked = SparePart.objects.filter(tenant=request.tenant, pk=linked_id, source_part=part).first()
        if linked is None:
            raise DomainError("invalid_linked_part", "Choose a clone of this part.", details={"linked_part": ["Not a clone of this part."]},
                              http_status=400)
    elif new_number:
        if not has_capability(request, "parts.submit"):
            raise DomainError("permission_denied", "Your role cannot create a cloned part; send the enquiry without one.",
                              http_status=403)
        linked = submissions.clone(request, part, {"part_number": new_number, "proposed_material": proposed,
                                                   "material_change_reason": reason,
                                                   "client_remarks": "Created from a manufacturing enquiry with a material change."})
    return {**out, "proposed_material": proposed, "material_change_reason": reason, "linked_part": linked}


def create_request(request, **fields) -> ClientRequest:
    """Create with a unique per-tenant reference (retry on the rare concurrent clash)."""
    for _ in range(5):
        try:
            with transaction.atomic():
                obj = ClientRequest.objects.create(tenant=request.tenant, created_by=request.user, requested_by=request.user,
                                                   reference=next_reference(request.tenant, fields["kind"]), **fields)
                break
        except IntegrityError:
            continue
    else:
        raise DomainError("reference_conflict", "Please submit the request again.", http_status=409)
    message = obj.remarks
    if obj.material_option == "proposed":
        linked = f" Linked cloned part: {obj.linked_part.part_number}." if obj.linked_part_id else " No cloned part linked yet."
        message = (f"Material change proposed: {obj.original_material or 'original not recorded'} → {obj.proposed_material}. "
                   f"Reason: {obj.material_change_reason}.{linked}\n{obj.remarks}").strip()
    RequestEvent.objects.create(tenant=obj.tenant, created_by=request.user, request=obj, event="submitted",
                                to_status=obj.status, author=request.user, author_side=RequestEvent.Side.CLIENT,
                                message=message[:2000])
    record(request, "request.submitted", obj=obj, data={"reference": obj.reference, "kind": obj.kind, "part": obj.part_number,
                                                       "material_option": obj.material_option, "proposed_material": obj.proposed_material,
                                                       "linked_part": obj.linked_part.part_number if obj.linked_part_id else None})
    sync_envelope(obj)
    notify_operators(obj, "submitted", body=_summary(obj))
    return obj


def transition(request, obj: ClientRequest, *, to_status: str, event: str, side: str, message: str = "") -> ClientRequest:
    old = obj.status
    obj.status = to_status
    if to_status == S.ACKNOWLEDGED and not obj.acknowledged_at:
        obj.acknowledged_at, obj.acknowledged_by = timezone.now(), request.user
    if to_status in (S.CLOSED, S.DECLINED, S.WITHDRAWN):
        obj.closed_reason = message
    obj.save()
    RequestEvent.objects.create(tenant=obj.tenant, created_by=request.user, request=obj, event=event, from_status=old,
                                to_status=to_status, message=message, author=request.user, author_side=side)
    record(request, f"request.{event}", obj=obj, tenant=obj.tenant, data={"reference": obj.reference, "from": old, "to": to_status})
    sync_envelope(obj)
    if side == RequestEvent.Side.OPERATOR:
        notify_client(obj, event, body=message[:300])
    else:
        notify_operators(obj, event, body=message[:300])
    return obj


def operator_action(request, obj: ClientRequest, action: str, message: str = "") -> ClientRequest:
    if action not in OPERATOR_ACTIONS:
        raise DomainError("unknown_action", "This action is not available.", http_status=400)
    kinds, from_states, to_state, needs_message = OPERATOR_ACTIONS[action]
    if obj.kind not in kinds or obj.status not in from_states:
        raise DomainError("transition_not_allowed", f"'{action.replace('_', ' ')}' is not possible while the request is "
                          f"{ClientRequest.Status(obj.status).label.lower()}.", http_status=409)
    if needs_message and not message.strip():
        raise DomainError("message_required", "Please enter a message for the client.", http_status=400)
    return transition(request, obj, to_status=to_state, event=to_state, side=RequestEvent.Side.OPERATOR, message=message.strip())


def client_message(request, obj: ClientRequest, message: str) -> ClientRequest:
    if obj.status not in OPEN:
        raise DomainError("request_closed", "This request is closed. Submit a new request instead.", http_status=409)
    if not message.strip():
        raise DomainError("message_required", "Please enter a message.", http_status=400)
    if obj.status == S.INFORMATION_REQUESTED:
        return transition(request, obj, to_status=S.INFORMATION_PROVIDED, event="information_provided",
                          side=RequestEvent.Side.CLIENT, message=message.strip())
    RequestEvent.objects.create(tenant=obj.tenant, created_by=request.user, request=obj, event="client_message",
                                from_status=obj.status, to_status=obj.status, message=message.strip(), author=request.user,
                                author_side=RequestEvent.Side.CLIENT)
    record(request, "request.client_message", obj=obj, data={"reference": obj.reference})
    sync_envelope(obj)  # marks the request as waiting for an Aries reply in the intake queue and on the dashboard
    notify_operators(obj, "client_message", body=message.strip()[:300])
    return obj


def operator_message(request, obj: ClientRequest, message: str) -> ClientRequest:
    """A message from Aries to the client without changing the status (any kind of request, once acknowledged)."""
    if obj.status not in OPEN:
        raise DomainError("request_closed", "This request is closed.", http_status=409)
    if obj.status == S.SUBMITTED:
        raise DomainError("transition_not_allowed", "Acknowledge the request before sending a message.", http_status=409)
    if not message.strip():
        raise DomainError("message_required", "Please enter a message for the client.", http_status=400)
    RequestEvent.objects.create(tenant=obj.tenant, created_by=request.user, request=obj, event="operator_message",
                                from_status=obj.status, to_status=obj.status, message=message.strip(), author=request.user,
                                author_side=RequestEvent.Side.OPERATOR)
    record(request, "request.operator_message", obj=obj, tenant=obj.tenant, data={"reference": obj.reference})
    sync_envelope(obj)  # Aries has answered: no longer waiting for a reply
    notify_client(obj, "operator_message", body=message.strip()[:300])
    return obj


def withdraw(request, obj: ClientRequest, reason: str) -> ClientRequest:
    if obj.status not in CLIENT_WITHDRAW_FROM:
        raise DomainError("transition_not_allowed", "This request can no longer be withdrawn.", http_status=409)
    return transition(request, obj, to_status=S.WITHDRAWN, event="withdrawn", side=RequestEvent.Side.CLIENT,
                       message=reason.strip() or "Withdrawn by the client.")


# ---- operator envelope -----------------------------------------------------------------------------------------

def sync_envelope(obj: ClientRequest) -> None:
    """Write the minimal operator-tenant summary (inside the operator's tenant context)."""
    op = operator_tenant()
    client_name = Tenant.objects.filter(pk=obj.tenant_id).values_list("name", flat=True).first() or ""
    last = RequestEvent.objects.filter(request=obj).order_by("-created_at").first()
    client_spoke = last is not None and last.author_side == RequestEvent.Side.CLIENT
    with tenant_context(op):
        env, _ = RequestEnvelope.objects.update_or_create(request_id=obj.pk, defaults=dict(
            awaiting_reply=client_spoke and obj.status in OPEN, last_client_activity=last.event[:30] if client_spoke else "",
            last_client_activity_at=last.created_at if client_spoke else None,
            tenant=op, client_tenant_id=obj.tenant_id, client_name=client_name, reference=obj.reference, kind=obj.kind,
            status=obj.status, priority=obj.priority, part_number=obj.part_number or "", part_name=(obj.part_name or obj.part_description)[:200],
            quantity=obj.quantity, required_date=obj.required_date or obj.preferred_date, submitted_at=obj.created_at,
            project_ref=request_project_id(obj), assigned_to_id=obj.assigned_to_id))
        if not env.intake_number:
            assign_intake_number(env)


def request_project_id(obj: ClientRequest):
    """The project a request belongs to: its own, its part's, or the part created for it (D-05)."""
    if obj.project_id:
        return obj.project_id
    for part_id in (obj.part_id, obj.created_part_id):
        if part_id:
            pid = SparePart.objects.filter(pk=part_id).values_list("project_id", flat=True).first()
            if pid:
                return pid
    return None


def assign_intake_number(env: RequestEnvelope) -> None:
    """Next platform-wide intake number of the submission year (called inside the operator context)."""
    stem = f"ARQ-{env.submitted_at.year}-"
    for _attempt in range(5):
        last = (RequestEnvelope.objects.filter(intake_number__startswith=stem).order_by("-intake_number")
                .values_list("intake_number", flat=True).first())
        env.intake_number = f"{stem}{(int(last.rsplit('-', 1)[1]) + 1) if last else 1:05d}"
        try:
            with transaction.atomic():
                env.save(update_fields=["intake_number"])
            return
        except IntegrityError:  # another request took the number at the same moment
            continue
    raise DomainError("intake_number_conflict", "Could not number the request in the Aries intake. Try again.", http_status=409)


def envelope_id(obj: ClientRequest):
    with tenant_context(operator_tenant()):
        return RequestEnvelope.objects.filter(request_id=obj.pk).values_list("pk", flat=True).first()


# ---- notifications -----------------------------------------------------------------------------------------------

def _summary(obj: ClientRequest) -> str:
    if obj.kind == K.DIGITISATION:
        return f"{obj.part_description[:120]} · {obj.site_location[:80]}"
    qty = f" · qty {obj.quantity}" if obj.quantity else ""
    return f"{obj.part_number} {obj.part_name}{qty}"


def _title(event: str, obj: ClientRequest) -> str:
    kind = {K.ENQUIRY: "enquiry", K.MANUFACTURING: "manufacturing request", K.DIGITISATION: "3D scanning request",
            K.ASSESSMENT: "assessment request"}[obj.kind]
    return EVENT_TITLES.get(event, "{ref} updated").format(ref=obj.reference, kind=kind)


def operator_recipients(obj: ClientRequest):
    """Operator administrators, plus operator staff actively assigned to the client organisation. Project-limited staff
    (CN-002 D4) are notified only about requests of their assigned projects. Runs in the client's tenant context."""
    from apps.projects.scoping import allowed_project_ids_for

    op = operator_tenant()
    admins = {m.user for m in Membership.objects.filter(tenant=op, role__in=[Role.OPERATOR_ADMIN, Role.OPERATOR_MANAGER], is_active=True,
                                                        user__is_active=True).select_related("user")}
    project_id = obj.project_id or (obj.part.project_id if obj.part_id else None)
    staff = set()
    for m in Membership.objects.filter(tenant_id=obj.tenant_id, role__in=OPERATOR_ROLES, is_active=True,
                                       user__is_active=True).select_related("user"):
        allowed = allowed_project_ids_for(obj.tenant_id, m.user_id)
        if allowed is None or project_id in allowed:
            staff.add(m.user)
    return admins | staff


def client_recipients(obj: ClientRequest):
    """The requester and the organisation's client administrators."""
    users = {m.user for m in Membership.objects.filter(tenant_id=obj.tenant_id, role=Role.CLIENT_ADMIN, is_active=True,
                                                       user__is_active=True).select_related("user")}
    if obj.requested_by and Membership.objects.filter(tenant_id=obj.tenant_id, user=obj.requested_by, is_active=True).exists():
        users.add(obj.requested_by)
    return users


def notify_operators(obj: ClientRequest, event: str, body: str = "") -> None:
    env = envelope_id(obj)
    name = Tenant.objects.filter(pk=obj.tenant_id).values_list("name", flat=True).first() or ""
    Notification.objects.bulk_create([
        Notification(recipient=u, title=_title(event, obj), body=body, link=f"/incoming/{env}", organisation_name=name)
        for u in operator_recipients(obj)])


def notify_client(obj: ClientRequest, event: str, body: str = "") -> None:
    name = Tenant.objects.filter(pk=obj.tenant_id).values_list("name", flat=True).first() or ""
    Notification.objects.bulk_create([
        Notification(recipient=u, title=_title(event, obj), body=body, link=f"/requests/{obj.pk}", organisation_name=name)
        for u in client_recipients(obj)])


# ---- scanning-to-passport handover (post-UAT D-05 / D-15) ----------------------------------------------------------

def _handover_event(request, obj: ClientRequest, event: str, message: str) -> None:
    RequestEvent.objects.create(tenant=obj.tenant, created_by=request.user, request=obj, event=event, from_status=obj.status,
                                to_status=obj.status, author=request.user, author_side=RequestEvent.Side.OPERATOR, message=message[:2000])


def assign(request, obj: ClientRequest, engineer_id) -> ClientRequest:
    """Make an Aries Engineer of this company (allowed for the request's project) responsible for the request."""
    m = (Membership.objects.filter(tenant_id=obj.tenant_id, user_id=engineer_id, role=Role.OPERATOR_ENGINEER, is_active=True)
         .select_related("user").first()) if engineer_id else None
    if m is None:
        raise DomainError("invalid_engineer", "Choose an active Aries Engineer assigned to this company.", http_status=400)
    from apps.projects.scoping import allowed_project_ids_for

    allowed, pid = allowed_project_ids_for(obj.tenant_id, m.user_id), request_project_id(obj)
    if allowed is not None and pid not in allowed:
        raise DomainError("engineer_not_on_project", "This engineer is not assigned to the request's project.", http_status=400)
    obj.assigned_to, obj.assigned_at = m.user, timezone.now()
    obj.save(update_fields=["assigned_to", "assigned_at", "updated_at"])
    _handover_event(request, obj, "assigned", f"Responsible engineer: {m.user.get_full_name() or m.user.email}.")
    record(request, "request.assigned", obj=obj, tenant=obj.tenant, data={"reference": obj.reference, "engineer": str(m.user_id)})
    sync_envelope(obj)
    return obj


def link_project(request, obj: ClientRequest, project_id) -> ClientRequest:
    """Attach a scanning request to an existing project of the company (instead of creating a new one)."""
    from apps.projects.models import Project

    if obj.kind != K.DIGITISATION:
        raise DomainError("transition_not_allowed", "Only scanning requests are linked to a project here.", http_status=409)
    if obj.project_id:
        raise DomainError("already_linked", "This request already belongs to a project.", http_status=409)
    project = Project.objects.filter(tenant_id=obj.tenant_id, pk=project_id).first() if project_id else None
    if project is None:
        raise DomainError("not_found", "Project not found in this company.", http_status=404)
    obj.project = project
    obj.save(update_fields=["project", "updated_at"])
    _handover_event(request, obj, "project_linked", f"Linked to project {project.code}.")
    record(request, "request.project_linked", obj=obj, tenant=obj.tenant, data={"project": project.code})
    sync_envelope(obj)
    return obj


def record_deliverable(request, obj: ClientRequest, kind: str, title: str, file_id=None, note: str = ""):
    from apps.files.models import EngineeringFile

    from .models import ScanDeliverable

    if obj.kind != K.DIGITISATION:
        raise DomainError("transition_not_allowed", "Deliverables are recorded for scanning requests.", http_status=409)
    if obj.status not in (S.SCHEDULED, S.IN_PROGRESS, S.COMPLETED):
        raise DomainError("transition_not_allowed", "Record deliverables once the scanning work is scheduled or under way.", http_status=409)
    if kind not in ScanDeliverable.Kind.values:
        raise DomainError("invalid_kind", "Choose the kind of deliverable.", http_status=400)
    title = (title or "").strip()
    if not title:
        raise DomainError("title_required", "Give the deliverable a title.", http_status=400)
    ef, version = None, None
    if file_id:
        ef = EngineeringFile.objects.filter(pk=file_id, tenant_id=obj.tenant_id).first()
        if ef is None or not obj.created_part_id or ef.part_id != obj.created_part_id:
            raise DomainError("invalid_file", "The file must belong to the part created for this request.", http_status=400)
        version = ef.versions.order_by("-version_number").values_list("version_number", flat=True).first()
    d = ScanDeliverable.objects.create(tenant=obj.tenant, created_by=request.user, request=obj, kind=kind, title=title[:200],
                                       file=ef, file_version=version, note=(note or "")[:500])
    _handover_event(request, obj, "deliverable_recorded", f"Deliverable recorded: {d.get_kind_display()} - {d.title}"
                    + (f" (file version {version})" if version else "") + ".")
    record(request, "request.deliverable_recorded", obj=obj, tenant=obj.tenant, data={"kind": kind, "title": d.title,
                                                                                      "file": str(ef.pk) if ef else None, "version": version})
    return obj


def hand_over(request, obj: ClientRequest) -> ClientRequest:
    """Hand the scanned part over into the passport workflow: needs the created part, its passport and a responsible engineer."""
    from apps.passports.models import DigitalPassport

    if obj.kind != K.DIGITISATION:
        raise DomainError("transition_not_allowed", "Only scanning requests are handed over.", http_status=409)
    if obj.handed_over_at:
        raise DomainError("already_handed_over", "This request was already handed over.", http_status=409)
    if obj.status != S.COMPLETED:
        raise DomainError("transition_not_allowed", "Complete the scanning work before the handover.", http_status=409)
    if not obj.assigned_to_id:
        raise DomainError("engineer_required", "Assign the responsible engineer first.", http_status=409)
    passport = DigitalPassport.objects.filter(part_id=obj.created_part_id).first() if obj.created_part_id else None
    if passport is None:
        raise DomainError("passport_required", "Create the part's digital passport before the handover.", http_status=409)
    if not obj.deliverables.exists():
        raise DomainError("deliverables_required", "Record at least one deliverable before the handover.", http_status=409)
    obj.handed_over_at, obj.handed_over_by, obj.handover_passport = timezone.now(), request.user, passport
    obj.save(update_fields=["handed_over_at", "handed_over_by", "handover_passport", "updated_at"])
    _handover_event(request, obj, "handed_over", f"Handed over to the digital passport workflow: passport {passport.passport_number}.")
    record(request, "request.handed_over", obj=obj, tenant=obj.tenant, data={"passport": passport.passport_number})
    notify_client(obj, "handed_over", body=f"Passport {passport.passport_number} created from the scanning work.")
    return obj
