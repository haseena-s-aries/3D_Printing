"""Edit-request workflow (CN-006): create, submit, review, decide, apply with conflict detection, notify, audit."""
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import serializers

from apps.audit.service import record
from apps.core.exceptions import DomainError
from apps.parts.models import SparePart
from apps.parts.submissions import display_name
from apps.passports.api import refresh_data_captured
from apps.passports.models import PassportRevision
from apps.projects.scoping import allowed_project_ids_for
from apps.servicerequests.models import Notification
from apps.tenancy.models import Membership, OPERATOR_ROLES, Role, Tenant
from apps.tenancy.permissions import has_capability
from apps.passports.confidential import aries_reader, is_aries_only

from . import fields as F
from .models import EditRequest, EditRequestEvent

S = EditRequest.Status
EDITABLE = (S.DRAFT, S.CORRECTIONS)
REVIEWABLE = (S.SUBMITTED, S.UNDER_REVIEW)


def side_of(request) -> str:
    return "aries" if request.membership.role in OPERATOR_ROLES else "client"


def next_reference(tenant) -> str:
    stem = f"ER-{timezone.now().year}-"
    last = EditRequest.objects.filter(tenant=tenant, reference__startswith=stem).order_by("-reference").values_list("reference", flat=True).first()
    return f"{stem}{(int(last.rsplit('-', 1)[1]) + 1) if last else 1:05d}"


def log(request, er: EditRequest, action: str, frm: str, to: str, note: str = "") -> None:
    EditRequestEvent.objects.create(tenant=er.tenant, created_by=request.user, request=er, action=action, from_status=frm,
                                    to_status=to, note=(note or "").strip()[:4000], side=side_of(request))
    record(request, f"edit_request.{action}", obj=er, data={"reference": er.reference, "fields": [c["field"] for c in er.changes],
                                                            "status": to, "note": (note or "")[:300],
                                                            "revision": er.applied_revision_number})


def _transition(request, er, to: str, action: str, note: str = "", **extra) -> EditRequest:
    frm = er.status
    er.status = to
    for k, v in extra.items():
        setattr(er, k, v)
    er.save()
    log(request, er, action, frm, to, note)
    return er


# ------------------------------------------------------------------ target and fields

def latest_revision(passport):
    return passport.revisions.order_by("-revision_number").first()


def available_fields(part, passport, request=None) -> list:
    if passport is None:
        return [{"field": k, "label": v, "current": F.part_value(part, k),
                 "kind": "choice" if k in F.PART_CHOICES else "text", "choices": F.PART_CHOICES.get(k, []),
                 "client_descriptive": part.origin == SparePart.Origin.CLIENT and k in F.CLIENT_DESCRIPTIVE}
                for k, v in F.PART_FIELDS.items()]
    rev = latest_revision(passport)
    content = rev.content if rev else {}
    aries = aries_reader(request)  # D-18: the Aries manufacturing specification is neither shown to nor requestable by clients
    return [{"field": k, "label": m["label"], "current": F.content_value(content, k), "kind": m["kind"], "choices": m.get("choices", [])}
            for k, m in F.PASSPORT_FIELDS.items() if aries or not is_aries_only(k)]


def _base(part, passport):
    if passport is None:
        return {"base_updated_at": part.updated_at, "base_revision_number": None, "base_revision_status": ""}
    rev = latest_revision(passport)
    if rev is None:
        raise DomainError("no_revision", "The passport has no revision.", http_status=409)
    return {"base_updated_at": rev.updated_at, "base_revision_number": rev.revision_number, "base_revision_status": rev.status}


def _changes(part, passport, raw: list, request=None) -> list:
    if not isinstance(raw, list) or not raw:
        raise DomainError("changes_required", "List at least one field change.", details={"changes": ["Required."]}, http_status=400)
    seen, out = set(), []
    catalog = F.PART_FIELDS if passport is None else F.PASSPORT_FIELDS
    content = latest_revision(passport).content if passport else None
    candidate = content
    for item in raw:
        field = (item or {}).get("field")
        if field not in catalog:
            raise DomainError("field_not_editable", f"'{field}' cannot be changed through an edit request.",
                              details={"field": field}, http_status=400)
        if passport is not None and is_aries_only(field) and not aries_reader(request):
            raise DomainError("field_not_editable", f"'{field}' is Aries-confidential and cannot be requested by your role.",
                              details={"field": field}, http_status=400)
        if field in seen:
            raise DomainError("duplicate_field", f"'{field}' is listed twice.", http_status=400)
        seen.add(field)
        proposed = item.get("proposed")
        if passport is None:
            proposed = F.validate_part_value(field, proposed if proposed is not None else "")
            original = F.part_value(part, field)
            label = catalog[field]
        else:
            original = F.content_value(content, field)
            candidate = F.set_content_value(candidate, field, proposed)
            label = catalog[field]["label"]
        if F.same(original, proposed):
            raise DomainError("no_change", f"The proposed value for '{label}' equals the current value.", details={"field": field},
                              http_status=400)
        out.append({"field": field, "label": label, "original": original, "proposed": proposed})
    if passport is not None:
        F.validate_passport_values(candidate)
    return out


def _data_class(part, passport, changes) -> str:
    if passport is not None:
        rev = latest_revision(passport)
        return EditRequest.DataClass.PASSPORT_DRAFT if rev.status == PassportRevision.Status.DRAFT else EditRequest.DataClass.PASSPORT_NEW_REVISION
    descriptive = part.origin == SparePart.Origin.CLIENT and all(c["field"] in F.CLIENT_DESCRIPTIVE for c in changes)
    return EditRequest.DataClass.CLIENT_DESCRIPTIVE if descriptive else EditRequest.DataClass.ARIES_MASTER


def _evidence(part, ids) -> list:
    from apps.files.models import EngineeringFile

    out = []
    for fid in ids or []:
        f = EngineeringFile.objects.filter(tenant=part.tenant, part=part, pk=fid).first()
        if f is None:
            raise DomainError("invalid_evidence", "Supporting documents must be files of this spare part.", http_status=400)
        out.append({"file": str(f.pk), "title": f.title})
    return out


def create(request, part, passport, data: dict) -> EditRequest:
    if passport is not None and passport.part_id != part.pk:
        raise DomainError("invalid_target", "The passport does not belong to this spare part.", http_status=400)
    reason = str(data.get("reason") or "").strip()
    if not reason:
        raise DomainError("reason_required", "Give the reason for the change.", details={"reason": ["Required."]}, http_status=400)
    changes = _changes(part, passport, data.get("changes"), request)
    er = None
    for _ in range(5):
        try:
            with transaction.atomic():
                er = EditRequest.objects.create(
                    tenant=part.tenant, created_by=request.user, reference=next_reference(part.tenant),
                    target_type=EditRequest.Target.PASSPORT if passport else EditRequest.Target.PART, part=part, passport=passport,
                    data_class=_data_class(part, passport, changes), changes=changes, reason=reason,
                    evidence_files=_evidence(part, data.get("evidence_files")), requester_role=request.membership.role,
                    requester_side=side_of(request), **_base(part, passport))
            break
        except IntegrityError:
            continue
    if er is None:
        raise DomainError("reference_conflict", "Please try again.", http_status=409)
    log(request, er, "created", "", S.DRAFT)
    if data.get("submit"):
        submit(request, er)
    return er


def update(request, er, data: dict) -> EditRequest:
    _require_requester(request, er)
    if er.status not in EDITABLE:
        raise DomainError("not_editable", "Only drafts and requests returned for corrections can be changed.", http_status=409)
    part, passport = er.part, er.passport
    if "changes" in data:
        # originals stay those of the recorded base; only proposals and the field list change
        originals = {c["field"]: c["original"] for c in er.changes}
        changes = _changes(part, passport, data["changes"], request)
        for c in changes:
            if c["field"] in originals:
                c["original"] = originals[c["field"]]
        er.changes = changes
        er.data_class = _data_class(part, passport, changes)
    if "reason" in data:
        if not str(data["reason"]).strip():
            raise DomainError("reason_required", "Give the reason for the change.", http_status=400)
        er.reason = str(data["reason"]).strip()
    if "evidence_files" in data:
        er.evidence_files = _evidence(part, data["evidence_files"])
    er.save()
    log(request, er, "updated", er.status, er.status)
    return er


# ------------------------------------------------------------------ workflow

def _require_requester(request, er):
    if er.created_by_id != request.user.pk:
        raise DomainError("not_requester", "Only the requester can do this.", http_status=403)


def _require_reviewer(request, er):
    if not has_capability(request, "edits.review"):
        raise DomainError("not_reviewer", "You are not an authorised edit reviewer for this company.", http_status=403)
    if er.created_by_id == request.user.pk:
        raise DomainError("self_approval", "You cannot review your own edit request.", http_status=403)


def submit(request, er) -> EditRequest:
    _require_requester(request, er)
    if er.status not in EDITABLE:
        raise DomainError("not_submittable", "This request cannot be submitted now.", http_status=409)
    action = "resubmitted" if er.status == S.CORRECTIONS else "submitted"
    _transition(request, er, S.SUBMITTED, action, submitted_at=timezone.now())
    notify_reviewers(er, "Edit request submitted" if action == "submitted" else "Edit request resubmitted")
    return er


def start_review(request, er) -> EditRequest:
    _require_reviewer(request, er)
    if er.status != S.SUBMITTED:
        raise DomainError("not_submitted", "Only submitted requests can be taken into review.", http_status=409)
    return _transition(request, er, S.UNDER_REVIEW, "review_started", reviewer=request.user)


def request_corrections(request, er, note: str) -> EditRequest:
    _require_reviewer(request, er)
    if er.status not in REVIEWABLE:
        raise DomainError("not_in_review", "This request is not waiting for review.", http_status=409)
    if not note.strip():
        raise DomainError("note_required", "Say what needs to be corrected.", http_status=400)
    _transition(request, er, S.CORRECTIONS, "corrections_requested", note, reviewer=request.user, decision_reason=note.strip())
    notify_requester(er, "Corrections requested on your edit request", note)
    return er


def reject(request, er, note: str) -> EditRequest:
    _require_reviewer(request, er)
    if er.status not in REVIEWABLE:
        raise DomainError("not_in_review", "This request is not waiting for review.", http_status=409)
    if not note.strip():
        raise DomainError("reason_required", "Give the reason for rejecting.", http_status=400)
    _transition(request, er, S.REJECTED, "rejected", note, reviewer=request.user, decision_reason=note.strip(), decided_at=timezone.now())
    notify_requester(er, "Edit request rejected", note)
    return er


def withdraw(request, er, note: str = "") -> EditRequest:
    _require_requester(request, er)
    if er.status not in (S.DRAFT, S.SUBMITTED, S.CORRECTIONS, S.CONFLICT):
        raise DomainError("not_withdrawable", "This request can no longer be withdrawn.", http_status=409)
    return _transition(request, er, S.WITHDRAWN, "withdrawn", note)


def approve(request, er, note: str = "") -> EditRequest:
    """Record the decision, then apply it in a controlled way (or move to conflict without writing)."""
    _require_reviewer(request, er)
    if er.status not in REVIEWABLE:
        raise DomainError("not_in_review", "This request is not waiting for review.", http_status=409)
    _transition(request, er, S.APPROVED, "approved", note, reviewer=request.user, decision_reason=note.strip(), decided_at=timezone.now())
    try:
        with transaction.atomic():
            result = _apply_part(request, er) if er.passport_id is None else _apply_passport(request, er)
    except (_Conflict, serializers.ValidationError) as c:
        msg = str(c) if isinstance(c, _Conflict) else "The proposed values are no longer valid for the current record. Nothing was written."
        _transition(request, er, S.CONFLICT, "conflict", msg, application_result=msg)
        notify_requester(er, "Edit request needs revalidation (target changed)", str(c))
        return er
    _transition(request, er, S.APPLIED, "applied", result, applied_at=timezone.now(), application_result=result)
    notify_requester(er, "Edit request approved and applied", result)
    return er


def rebase(request, er) -> EditRequest:
    """After a conflict: refresh the base and originals to the target's current state; proposals are kept."""
    _require_requester(request, er)
    if er.status != S.CONFLICT:
        raise DomainError("not_conflict", "Only requests in conflict can be revalidated.", http_status=409)
    part, passport = er.part, er.passport
    base = _base(part, passport)
    content = latest_revision(passport).content if passport else None
    changes = []
    for c in er.changes:
        current = F.part_value(part, c["field"]) if passport is None else F.content_value(content, c["field"])
        if not F.same(current, c["proposed"]):
            changes.append({**c, "original": current})
    if not changes:
        return _transition(request, er, S.WITHDRAWN, "withdrawn", "All proposed values are already in place; nothing to change.")
    er.changes = changes
    er.data_class = _data_class(part, passport, changes)
    for k, v in base.items():
        setattr(er, k, v)
    _transition(request, er, S.SUBMITTED, "rebased", "Revalidated against the current record; originals refreshed.",
                submitted_at=timezone.now(), reviewer=None)
    notify_reviewers(er, "Edit request revalidated and resubmitted")
    return er


class _Conflict(Exception):
    pass


def _drift(current_of, changes) -> list:
    return [c["label"] for c in changes if not F.same(current_of(c["field"]), c["original"])]


def _apply_part(request, er) -> str:
    from apps.parts import submissions

    part = SparePart.objects.select_for_update().get(pk=er.part_id)
    drift = _drift(lambda f: F.part_value(part, f), er.changes)
    if drift:
        raise _Conflict(f"Changed since the request was made: {', '.join(drift)}. Nothing was written.")
    stale = part.updated_at != er.base_updated_at
    fields = [c["field"] for c in er.changes]
    for c in er.changes:
        setattr(part, c["field"], c["proposed"])
    part.unknown_fields = [f for f in (part.unknown_fields or []) if f not in fields]
    client = er.requester_side == "client" and er.data_class == EditRequest.DataClass.CLIENT_DESCRIPTIVE
    submissions.stamp(part, fields, source="client" if client else "aries", user=er.created_by)
    submissions.verify(part, fields, request.user)  # decided by an authorised reviewer (not engineering verification of the passport)
    part.save(update_fields=[*fields, "unknown_fields", "field_provenance", "updated_at"])
    return ("Applied to the spare-part master data; previous values are kept in this request."
            + (" Other fields had changed since the request; they were left as they are." if stale else ""))


def _apply_passport(request, er) -> str:
    passport = er.passport
    latest = PassportRevision.objects.select_for_update().filter(passport=passport).order_by("-revision_number").first()
    drift = _drift(lambda f: F.content_value(latest.content, f), er.changes)
    if drift:
        raise _Conflict(f"Changed since the request was made: {', '.join(drift)}. Nothing was written.")
    content = latest.content or {}
    for c in er.changes:
        content = F.set_content_value(content, c["field"], c["proposed"])
        if c["field"].startswith("rl1."):  # provenance of R-L1 values
            key = c["field"].split(".", 1)[1]
            sources = dict((content.get("rl1") or {}).get("value_sources") or {})
            if er.requester_side == "client":
                sources[key] = "client_submitted"
            else:
                sources.pop(key, None)
            content["rl1"]["value_sources"] = sources
    F.validate_passport_values(content)
    previous = latest.revision_number
    if latest.status == PassportRevision.Status.DRAFT:
        latest.status = PassportRevision.Status.SUPERSEDED  # the earlier draft is kept unchanged as history
        latest.save(update_fields=["status", "updated_at"])
    new = PassportRevision.objects.create(tenant=passport.tenant, created_by=request.user, passport=passport,
                                          revision_number=previous + 1, content=content,
                                          change_summary=f"{er.reference}: " + ", ".join(c["label"] for c in er.changes)[:450])
    refresh_data_captured(passport, content)
    er.applied_revision_number = new.revision_number
    er.save(update_fields=["applied_revision_number", "updated_at"])
    return (f"Applied as new draft revision {new.revision_number} (from revision {previous}, which is kept unchanged). "
            "The new revision is a draft: it is not approved, verified or published (OQ-35).")


# ------------------------------------------------------------------ notifications (field names only; no values, notes or job data)

def reviewers(er):
    out = []
    for m in Membership.objects.filter(tenant_id=er.tenant_id, role=Role.OPERATOR_ENGINEER, is_active=True, edit_reviewer=True,
                                       user__is_active=True).select_related("user"):
        if m.user_id == er.created_by_id:
            continue
        allowed = allowed_project_ids_for(er.tenant_id, m.user_id)
        if allowed is None or (er.part.project_id is not None and er.part.project_id in allowed):
            out.append(m.user)
    return out


def _notify(users, er, title, body=""):
    name = Tenant.objects.filter(pk=er.tenant_id).values_list("name", flat=True).first() or ""
    Notification.objects.bulk_create([Notification(recipient=u, title=f"{title}: {er.reference} ({er.part.part_number})"[:200],
                                                   body=body[:500], link=f"/edit-requests/{er.pk}", organisation_name=name) for u in users])


def notify_reviewers(er, title):
    users = reviewers(er)
    fields = ", ".join(c["label"] for c in er.changes)
    if users:
        _notify(users, er, title, f"Fields: {fields}")
        return
    from apps.servicerequests.services import operator_tenant

    admins = [m.user for m in Membership.objects.filter(tenant=operator_tenant(), role__in=[Role.OPERATOR_ADMIN, Role.OPERATOR_MANAGER], is_active=True)
              .select_related("user")]
    _notify(admins, er, "No authorised edit reviewer for", "Authorise an Aries Engineer as edit reviewer for this company (CN-006).")


def notify_requester(er, title, body=""):
    if er.created_by_id:
        _notify([er.created_by], er, title, body)


def requester_name(er) -> str:
    return display_name(er.created_by)
