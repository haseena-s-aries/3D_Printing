"""Provenance-aware contract route for Aries Admin inventory thumbnails (ADMIN_THUMBNAIL_PROVENANCE_ENABLED, approved
2026-10-29 for access-test; needs ADMIN_THUMBNAIL_CONSENT_ENABLED as well).

Two routes can let the Aries Admin see a company's sanitized photo thumbnails (480 px JPEG, metadata removed):
- Client consent (apps.files.admin_thumbnails): the company's Client Administrator allows it. Covers every released photo,
  whatever its origin. Client-uploaded and unknown-origin photos can only ever use this route.
- Contract route (this module), for photos Aries captured during scanning or digitisation work, without client consent,
  only when ALL of the following hold, re-checked on every thumbnail request:
  1. Origin: the Aries Engineer who uploaded that exact photo version claimed Aries captured it, and QA (an Aries Engineer with
     QA permission, or a legacy Aries QA account; never the claimant) confirmed the claim (ImageOriginEvent). The uploader's role is never taken as proof; nothing is classified
     automatically or in bulk; versions uploaded by client members can never be claimed. Only the file's latest version
     counts, and a withdrawal or rejection ends it.
  2. Contract: the company's current ContractAuthorization (contract reference, clause excerpt, effective and expiry
     dates, company or project scope) was recorded by an Aries Admin and verified against the signed agreement by a
     different Aries Admin or an Aries Engineer with contract review permission (legacy: Aries QA); it is within its dates, not rejected or ended, and covers the part's project.
     Entering clause text proves nothing by itself, so an unverified authorization has no effect.
  3. No unresolved client objection: if the company's latest decision is "Not allowed", the route is on hold until a
     review of that specific objection is documented under the separately configured objection-review authority
     (CONTRACT_OBJECTION_REVIEWERS + CONTRACT_OBJECTION_AUTHORITY; contract verification gives no such right) by a
     designated reviewer who neither recorded nor verified the authorization nor claimed or uploaded a photo it covers.
     A review only counts while its reviewer is still designated; with no authority configured every disputed route
     stays on hold. "Objection sustained" keeps it blocked; any later client decision needs a new review.
  4. Release and scope: the photo is released to the client (client_visible) and the part belongs to the company.
Every thumbnail link is bound to the records it was issued under (authorization, verification, objection and review,
QA confirmation), so ending, expiry, a new client decision, a withdrawn origin claim or a part moved out of scope blocks
previously issued links at once. Full client records stay closed (OQ-37 unchanged).
"""
from datetime import date

from django.conf import settings
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.service import record
from apps.core.exceptions import DomainError
from apps.projects.models import Project
from apps.projects.scoping import allowed_project_ids, restrict
from apps.tenancy.context import tenant_context
from apps.tenancy.models import CLIENT_ROLES, Membership, Tenant
from apps.tenancy.permissions import HasCapability, has_capability, objection_reviewer

from . import admin_thumbnails
from .admin_thumbnails import next_sequence
from .models import (AdminThumbnailConsent, ContractAuthorization, ContractAuthorizationEvent, Derivative, EngineeringFile,
                     FileVersion, ImageOriginEvent)

O = ImageOriginEvent.Event
E = ContractAuthorizationEvent.Event
LIFECYCLE = [E.VERIFIED, E.REJECTED, E.ENDED]
REVIEWS = [E.CONFLICT_PROCEED, E.CONFLICT_SUSTAINED]
# Stored role values stay as recorded (history is never rewritten). An Aries Engineer acting under a four-role permission is
# recorded as "operator_engineer:qa" or "operator_engineer:contract".
ROLE_LABELS = {"operator_admin": "Aries Admin", "operator_manager": "Aries Manager", "operator_qa": "Aries QA", "operator_engineer": "Aries Engineer",
               "operator_engineer:qa": "Aries Engineer (QA)", "operator_engineer:contract": "Aries Engineer (contract reviewer)"}

STATUS = {  # status -> (label, explanation for the client company)
    "none": ("No contract authorization", "No contract authorization is recorded. Aries scanning photos follow your "
                                          "permission above, like every other photo."),
    "pending_verification": ("Awaiting independent verification", "Aries has recorded a contract authorization. It has no "
                             "effect until a second Aries person verifies it against the signed agreement."),
    "rejected": ("Rejected at verification", "The recorded contract authorization was not verified, so it has no effect."),
    "ended": ("Ended", "The contract authorization has ended. It no longer allows any thumbnails."),
    "not_yet_effective": ("Not yet in effect", "The contract authorization is verified but its effective date has not "
                          "been reached."),
    "expired": ("Expired", "The contract authorization has passed its expiry date. It no longer allows any thumbnails."),
    "on_hold": ("On hold: your objection is under review", "You have recorded \"Not allowed\". The contract route is on "
                "hold until an independent reviewer, acting under a documented Aries authority, records a decision on your "
                "objection. No thumbnails are shown through it."),
    "objection_sustained": ("Blocked: your objection was upheld", "Your \"Not allowed\" decision was reviewed and upheld. "
                            "The contract route stays blocked."),
    "active": ("Active", "Aries Admin may see thumbnails of released photos that Aries captured during scanning work, "
               "once Aries QA has confirmed each photo's origin. Every view is recorded in your audit trail."),
}


def enabled() -> bool:
    return admin_thumbnails.enabled() and bool(getattr(settings, "ADMIN_THUMBNAIL_PROVENANCE_ENABLED", False))


def _actor(request, duty: str = "") -> tuple[str, str]:
    role = request.membership.role
    if duty and role == "operator_engineer":
        role = f"{role}:{duty}"
    return (request.user.get_full_name().strip() or request.user.email), role


def _note(request, minimum: int, what: str) -> str:
    note = str(request.data.get("note", "")).strip()
    if len(note) < minimum:
        raise DomainError("note_required", f"{what} (at least {minimum} characters).", http_status=400)
    return note


def _operator_tenant():
    return Tenant.objects.filter(kind=Tenant.Kind.OPERATOR).order_by("created_at").first()


def _both_trails(request, action, tenant, obj_type, obj_id, data):
    """Record in the client company's trail and in the Aries trail."""
    with tenant_context(tenant):
        record(request, action, tenant=tenant, obj_type=obj_type, obj_id=obj_id, data=data)
    op = _operator_tenant()
    if op is not None:
        with tenant_context(op):
            record(request, action, tenant=op, obj_type=obj_type, obj_id=obj_id, data={**data, "company": tenant.name})


# ---------------------------------------------------------------------------------------------------- photo origin
def latest_origin(fv) -> ImageOriginEvent | None:
    return ImageOriginEvent.objects.filter(file_version=fv).order_by("-sequence").first()


def uploaded_by_client(fv) -> bool:
    """The version was uploaded by a member of a client organisation (or by no known user)."""
    if fv.created_by_id is None:
        return True
    return Membership.objects.filter(user_id=fv.created_by_id, role__in=CLIENT_ROLES).exists()


def origin_state(fv) -> str:
    ev = latest_origin(fv)
    if ev is not None:
        return ev.event
    return "client_uploaded" if uploaded_by_client(fv) else "unknown"


ORIGIN_LABELS = {"client_uploaded": "Client-uploaded", "unknown": "Origin unknown", O.CLAIMED: "Claimed as Aries capture, awaiting QA",
                 O.CONFIRMED: "Aries capture, confirmed by QA", O.REJECTED: "Claim rejected by QA (origin unknown)",
                 O.WITHDRAWN: "Claim withdrawn (origin unknown)"}


def _origin_payload(request, ef, fv) -> dict:
    state = origin_state(fv)
    ev = latest_origin(fv)
    open_claim = ev if ev is not None and ev.event == O.CLAIMED else None
    active_claim = open_claim or (ev.claim if ev is not None and ev.event == O.CONFIRMED else None)
    client_upload = uploaded_by_client(fv)
    claim_block = ("client_uploaded" if client_upload else "not_uploader" if fv.created_by_id != request.user.pk
                   else "already_claimed" if state in (O.CLAIMED, O.CONFIRMED) else "")
    uploader = fv.created_by
    return {
        "file": str(ef.pk), "version": fv.version_number, "state": state, "label": ORIGIN_LABELS[state],
        "part": {"id": str(ef.part_id), "part_number": ef.part.part_number, "name": ef.part.name}, "title": ef.title,
        "uploaded_by": (uploader.get_full_name().strip() or uploader.email) if uploader else "", "uploaded_at": fv.created_at.isoformat(),
        "uploaded_by_client": client_upload, "claim_block": claim_block if has_capability(request, "files.origin_claim") else "",
        "history": [{"event": e.event, "label": e.get_event_display(), "role": ROLE_LABELS.get(e.actor_role, e.actor_role),
                     "by": e.actor_name, "at": e.created_at.isoformat(), "capture_reference": e.capture_reference,
                     "capture_date": e.capture_date.isoformat() if e.capture_date else None, "note": e.note}
                    for e in ImageOriginEvent.objects.filter(file_version=fv).order_by("-sequence")],
        "can": {
            "claim": (has_capability(request, "files.origin_claim") and fv.created_by_id == request.user.pk
                      and not uploaded_by_client(fv) and state not in (O.CLAIMED, O.CONFIRMED)),
            "confirm": has_capability(request, "files.origin_confirm") and open_claim is not None
                       and open_claim.created_by_id != request.user.pk and fv.created_by_id != request.user.pk,
            "withdraw": active_claim is not None and (has_capability(request, "files.origin_confirm") or (
                has_capability(request, "files.origin_claim") and active_claim.created_by_id == request.user.pk)),
        },
    }


class ImageOriginView(APIView):
    """Origin of one photograph version inside a client company: read, claim, confirm, reject, withdraw."""
    permission_classes = [HasCapability]
    capabilities = {"get": "files.view", "post": "files.view"}

    def _load(self, request, file_id, number):
        if not enabled():
            raise DomainError("not_available", "Photo origin records are not enabled.", http_status=404)
        if not (has_capability(request, "files.origin_claim") or has_capability(request, "files.origin_confirm")):
            raise DomainError("permission_denied", "Only Aries Engineers (and Aries QA) record photo origin.", http_status=403)
        qs = restrict(request, EngineeringFile.objects.filter(tenant=request.membership.tenant).select_related("part"), "part__project")
        ef = qs.filter(pk=file_id).first()
        fv = ef.versions.filter(version_number=number).first() if ef else None
        if fv is None:
            raise DomainError("not_found", "File version not found.", http_status=404)
        if ef.kind != EngineeringFile.Kind.IMAGE:
            raise DomainError("not_a_photo", "Origin is recorded for photographs only.", http_status=400)
        return ef, fv

    @extend_schema(responses=dict)
    def get(self, request, file_id, number):
        ef, fv = self._load(request, file_id, number)
        return Response(_origin_payload(request, ef, fv))

    @extend_schema(request=dict, responses=dict)
    def post(self, request, file_id, number):
        ef, fv = self._load(request, file_id, number)
        action = request.data.get("action")
        current = latest_origin(fv)
        qa_duty = action in ("confirm", "reject", "withdraw") and has_capability(request, "files.origin_confirm")
        name, role = _actor(request, "qa" if qa_duty else "")
        fields = {"tenant": request.membership.tenant, "created_by": request.user, "file_version": fv, "actor_name": name, "actor_role": role,
                  "sequence": next_sequence(ImageOriginEvent.objects.filter(file_version=fv))}
        if action == "claim":
            if not has_capability(request, "files.origin_claim"):
                raise DomainError("permission_denied", "Only an Aries Engineer can claim a photo was captured by Aries.", http_status=403)
            if uploaded_by_client(fv):
                raise DomainError("client_uploaded", "Photos uploaded by the client can never be classified as Aries captures.", http_status=403)
            if fv.created_by_id != request.user.pk:
                raise DomainError("not_uploader", "Only the person who uploaded this version can claim its origin. "
                                  "If they are not available, the origin stays unresolved.", http_status=403)
            if current is not None and current.event in (O.CLAIMED, O.CONFIRMED):
                raise DomainError("already_claimed", "This version already has an open or confirmed claim.", http_status=409)
            reference = str(request.data.get("capture_reference", "")).strip()[:120]
            note = str(request.data.get("note", "")).strip()[:500]
            if not reference and len(note) < 15:
                raise DomainError("evidence_required", "Give the scanning job or digitisation reference, or describe the "
                                  "scanning work in the note (at least 15 characters).", http_status=400)
            capture_date = None
            if request.data.get("capture_date"):
                try:
                    capture_date = date.fromisoformat(str(request.data["capture_date"]))
                except ValueError:
                    raise DomainError("invalid_date", "Capture date must be YYYY-MM-DD.", http_status=400)
            ev = ImageOriginEvent.objects.create(**fields, event=O.CLAIMED, capture_reference=reference, capture_date=capture_date, note=note)
        elif action in ("confirm", "reject"):
            if not has_capability(request, "files.origin_confirm"):
                raise DomainError("permission_denied", "Only an Aries Engineer with QA permission (or a legacy Aries QA account) can confirm or reject an origin claim.", http_status=403)
            if current is None or current.event != O.CLAIMED:
                raise DomainError("no_open_claim", "There is no open origin claim for this version.", http_status=409)
            if current.created_by_id == request.user.pk or fv.created_by_id == request.user.pk:
                raise DomainError("self_verification", "The claimant cannot confirm their own claim.", http_status=403)
            note = _note(request, 10, "Record what you checked")[:500]
            ev = ImageOriginEvent.objects.create(**fields, event=O.CONFIRMED if action == "confirm" else O.REJECTED, claim=current, note=note)
        elif action == "withdraw":
            if current is None or current.event not in (O.CLAIMED, O.CONFIRMED):
                raise DomainError("no_open_claim", "There is no claim to withdraw.", http_status=409)
            claim = current if current.event == O.CLAIMED else current.claim
            if not (has_capability(request, "files.origin_confirm")
                    or (has_capability(request, "files.origin_claim") and claim is not None and claim.created_by_id == request.user.pk)):
                raise DomainError("permission_denied", "Only the claimant or someone with QA permission can withdraw this claim.", http_status=403)
            note = _note(request, 10, "Give the reason for withdrawing")[:500]
            ev = ImageOriginEvent.objects.create(**fields, event=O.WITHDRAWN, claim=claim, note=note)
        else:
            raise DomainError("invalid", "action must be claim, confirm, reject or withdraw.", http_status=400)
        data = {"file": str(ef.pk), "version": fv.version_number, "part_number": ef.part.part_number, "event": ev.event,
                "role": role, "capture_reference": ev.capture_reference}
        record(request, f"files.image_origin_{ev.event}", obj=fv, data=data)
        if ev.event in (O.CONFIRMED, O.WITHDRAWN):  # changes what the contract route may show: Aries is told too
            op = _operator_tenant()
            if op is not None:
                with tenant_context(op):
                    record(request, f"files.image_origin_{ev.event}", tenant=op, obj_type="file_version", obj_id=str(fv.pk),
                           data={**data, "company": request.membership.tenant.name})
        return Response(_origin_payload(request, ef, fv), status=201)


class OriginClaimsQueueView(APIView):
    """Open origin claims in this client company, for QA (Aries Engineers with QA permission, legacy Aries QA), within project scope."""
    permission_classes = [HasCapability]
    capabilities = {"get": "files.origin_confirm"}

    @extend_schema(responses=dict)
    def get(self, request):
        if not enabled():
            raise DomainError("not_available", "Photo origin records are not enabled.", http_status=404)
        tenant = request.membership.tenant
        scope = allowed_project_ids(request)  # project-limited QA staff see only their projects' claims
        latest = {}
        for e in ImageOriginEvent.objects.filter(tenant=tenant).select_related("file_version__file__part").order_by("file_version_id", "-sequence"):
            latest.setdefault(e.file_version_id, e)
        out = [{"file": str(e.file_version.file_id), "version": e.file_version.version_number, "part": str(e.file_version.file.part_id),
                "part_number": e.file_version.file.part.part_number, "title": e.file_version.file.title,
                "claimed_by": e.actor_name, "claimed_at": e.created_at.isoformat(), "capture_reference": e.capture_reference,
                "note": e.note, "own_claim": e.created_by_id == request.user.pk}
               for e in latest.values() if e.event == O.CLAIMED and (scope is None or e.file_version.file.part.project_id in scope)]
        return Response({"results": sorted(out, key=lambda x: x["claimed_at"])})


# ------------------------------------------------------------------------------------------------- contract route
def contract_state(tenant, today: date | None = None) -> dict:
    """Current contract-route state of a company (call inside its tenant context)."""
    auth = ContractAuthorization.objects.filter(tenant=tenant).order_by("-sequence").first()
    consent = admin_thumbnails.current(tenant)
    objection = consent if consent is not None and consent.decision == AdminThumbnailConsent.Decision.REVOKED else None
    st = {"authorization": auth, "status": "none", "verification": None, "review": None, "objection": objection}
    if auth is None:
        return st
    last = auth.events.filter(event__in=LIFECYCLE).order_by("-sequence").first()
    if last is None:
        st["status"] = "pending_verification"
    elif last.event == E.REJECTED:
        st["status"] = "rejected"
    elif last.event == E.ENDED:
        st["status"] = "ended"
    else:
        st["verification"] = last
        today = today or timezone.localdate()
        if today < auth.effective_from:
            st["status"] = "not_yet_effective"
        elif today > auth.effective_until:
            st["status"] = "expired"
        elif objection is not None:
            review = next((r for r in auth.events.filter(event__in=REVIEWS, objection=objection).select_related("created_by")
                           .order_by("-sequence") if valid_review(r)), None)
            st["review"] = review
            st["status"] = "on_hold" if review is None else ("objection_sustained" if review.event == E.CONFLICT_SUSTAINED else "active")
        else:
            st["status"] = "active"
    return st


def authority() -> str:
    """The documented objection-review authority of this deployment ("" = none defined: disputed routes stay on hold)."""
    return getattr(settings, "CONTRACT_OBJECTION_AUTHORITY", "") if getattr(settings, "CONTRACT_OBJECTION_REVIEWERS", []) else ""


def valid_review(review) -> bool:
    """A conflict review resolves an objection only if it was made under a documented authority by someone who is still a
    designated objection reviewer (so withdrawing the designation puts the route back on hold)."""
    return bool(review.authority_reference) and objection_reviewer(review.created_by)


def related_people(tenant, auth) -> set:
    """Users too close to this authorization to resolve an objection to it: whoever recorded or verified it, and whoever
    claimed or uploaded a photo version it covers."""
    ids = {auth.created_by_id}
    ids |= set(auth.events.filter(event__in=LIFECYCLE).values_list("created_by_id", flat=True))
    for e in ImageOriginEvent.objects.filter(tenant=tenant, event=O.CLAIMED).select_related("file_version__file__part"):
        if in_scope(auth, e.file_version.file.part):
            ids |= {e.created_by_id, e.file_version.created_by_id}
    return ids - {None}


def review_block(request, tenant, st) -> str:
    """Why this user may not resolve the current objection ("" = may)."""
    if not has_capability(request, "contracts.objection_review"):
        return ("no_authority_configured" if not authority() else "not_designated")
    if st["authorization"] is not None and request.user.pk in related_people(tenant, st["authorization"]):
        return "not_independent"
    return ""


def in_scope(auth, part) -> bool:
    return auth.scope == ContractAuthorization.Scope.COMPANY or (part.project_id is not None and str(part.project_id) in auth.project_ids)


def _basis(st) -> dict:
    return {"a": str(st["authorization"].pk), "v": str(st["verification"].pk),
            "o": str(st["objection"].pk) if st["objection"] else "", "w": str(st["review"].pk) if st["review"] else ""}


def _confirmed_versions(tenant) -> dict:
    """{file_version_id: confirmation event} for versions whose current origin state is QA-confirmed."""
    latest = {}
    for e in ImageOriginEvent.objects.filter(tenant=tenant).order_by("file_version_id", "-sequence"):
        latest.setdefault(e.file_version_id, e)
    return {fv_id: e for fv_id, e in latest.items() if e.event == O.CONFIRMED}


def _latest_versions(tenant) -> set:
    newest = {}
    for fv_id, file_id, n in FileVersion.objects.filter(tenant=tenant, file__kind=EngineeringFile.Kind.IMAGE).values_list("id", "file_id", "version_number"):
        if file_id not in newest or n > newest[file_id][1]:
            newest[file_id] = (fv_id, n)
    return {v[0] for v in newest.values()}


def _thumbs(tenant):
    return (Derivative.objects.filter(tenant=tenant, kind=Derivative.Kind.THUMB, file_version__file__kind=EngineeringFile.Kind.IMAGE,
                                      file_version__file__client_visible=True)
            .select_related("file_version__file__part"))


def contract_eligible(tenant, st) -> dict:
    """{part_id: (derivative_id, basis)}: the newest released, QA-confirmed Aries-captured photo of each in-scope part."""
    if st["status"] != "active":
        return {}
    auth, base = st["authorization"], _basis(st)
    confirmed, latest = _confirmed_versions(tenant), _latest_versions(tenant)
    out = {}
    for d in _thumbs(tenant).order_by("file_version__file__part_id", "-file_version__file__created_at"):
        fv = d.file_version
        part = fv.file.part
        if part.pk in out or fv.pk not in latest or fv.pk not in confirmed or not in_scope(auth, part):
            continue
        out[part.pk] = (d.pk, {**base, "p": str(confirmed[fv.pk].pk)})
    return out


def check_contract_claim(tenant, claim) -> tuple[Derivative | None, dict]:
    """Re-check a contract-route token inside the company's tenant context. Returns (derivative or None, state)."""
    st = contract_state(tenant)
    if st["status"] != "active" or any(_basis(st)[k] != claim.get(k) for k in ("a", "v", "o", "w")):
        return None, st
    d = _thumbs(tenant).filter(pk=claim.get("d")).first()
    if d is None:
        return None, st
    fv = d.file_version
    confirmation = latest_origin(fv)
    if (confirmation is None or confirmation.event != O.CONFIRMED or str(confirmation.pk) != claim.get("p")
            or fv.pk not in _latest_versions(tenant) or not in_scope(st["authorization"], fv.file.part)):
        return None, st
    return d, st


# -------------------------------------------------------------------------------------------- payloads and views
def _auth_payload(auth, client_view: bool) -> dict:
    who = (lambda name, role: ROLE_LABELS.get(role, role)) if client_view else (lambda name, role: f"{name} ({ROLE_LABELS.get(role, role)})")
    codes = dict((str(pk), code) for pk, code in Project.objects.filter(pk__in=auth.project_ids or []).values_list("pk", "code"))
    return {
        "id": str(auth.pk), "contract_reference": auth.contract_reference, "clause_excerpt": auth.clause_excerpt,
        "effective_from": auth.effective_from.isoformat(), "effective_until": auth.effective_until.isoformat(),
        "scope": auth.scope, "scope_label": auth.get_scope_display(), "projects": [codes.get(p, "(removed project)") for p in auth.project_ids],
        "recorded_by": who(auth.recorded_by_name, auth.recorded_by_role), "recorded_at": auth.created_at.isoformat(),
        "note": "" if client_view else auth.note,
        "events": [{"event": e.event, "label": e.get_event_display(), "by": who(e.actor_name, e.actor_role),
                    "at": e.created_at.isoformat(), "note": e.note, "authority": e.authority_reference,
                    "counts": e.event not in REVIEWS or valid_review(e)} for e in auth.events.select_related("created_by").order_by("-sequence")],
    }


def state_payload(tenant, client_view: bool) -> dict:
    """Contract-route state (call inside the company's tenant context)."""
    st = contract_state(tenant)
    auth = st["authorization"]
    label, explanation = STATUS[st["status"]]
    confirmed, latest = _confirmed_versions(tenant), _latest_versions(tenant)
    released = {d.file_version_id: d for d in _thumbs(tenant)}
    confirmed_released = [fv for fv in confirmed if fv in latest and fv in released]
    shown = len(contract_eligible(tenant, st))
    out = {
        "enabled": True, "status": st["status"], "label": label, "explanation": explanation,
        "authorization": _auth_payload(auth, client_view) if auth else None,
        "verified_at": st["verification"].created_at.isoformat() if st["verification"] else None,
        "objection": {"at": st["objection"].created_at.isoformat()} if st["objection"] else None,
        "review": ({"outcome": st["review"].get_event_display(), "note": st["review"].note, "at": st["review"].created_at.isoformat(),
                    "authority": st["review"].authority_reference} if st["review"] else None),
        "photos": {"confirmed_aries_captures": len(confirmed_released), "shown_through_contract": shown},
    }
    if not client_view:
        out["history"] = [_auth_payload(a, False) for a in ContractAuthorization.objects.filter(tenant=tenant).order_by("-sequence")[:20]]
        out["objection_authority"] = {"configured": bool(authority()), "reference": authority()}
    return out


REVIEW_BLOCKS = {
    "no_authority_configured": "No objection-review authority is defined for this deployment, so disputed contract routes stay on hold.",
    "not_designated": "You are not a designated objection reviewer. Verifying contracts does not give this authority.",
    "not_independent": "You recorded or verified this authorization, or claimed or uploaded a photo it covers, so you cannot "
                       "resolve the objection.",
}


def _admin_body(request, t) -> dict:
    """Aries view of one company's contract route, with what the requesting user may do now (inside tenant context)."""
    st = contract_state(t)
    auth = st["authorization"]
    mine = auth is not None and auth.created_by_id == request.user.pk
    block = review_block(request, t, st) if st["status"] == "on_hold" else ""
    return {
        "client": {"id": str(t.pk), "name": t.name}, **state_payload(t, client_view=False),
        "projects": [{"id": str(p.pk), "code": p.code, "name": p.name} for p in Project.objects.filter(tenant=t).order_by("code")],
        "can": {
            "record": has_capability(request, "contracts.thumbnail_record") and st["status"] != "pending_verification",
            "verify": has_capability(request, "contracts.thumbnail_verify") and st["status"] == "pending_verification" and not mine,
            "end": (has_capability(request, "contracts.thumbnail_verify") or has_capability(request, "contracts.thumbnail_record"))
                   and auth is not None and st["status"] not in ("ended", "rejected"),
            "review": st["status"] == "on_hold" and not block,
        },
        "own_record": mine,
        "review_block": REVIEW_BLOCKS.get(block, "") if st["status"] == "on_hold" else "",
    }


class ContractListView(APIView):
    """Aries organisation: contract-route status of every client company, with the actions waiting for this user."""
    permission_classes = [HasCapability]
    capabilities = {"get": "contracts.thumbnail_view"}

    @extend_schema(responses=dict)
    def get(self, request):
        if not enabled():
            raise DomainError("not_available", "Contract authorizations are not enabled.", http_status=404)
        out = []
        for t in Tenant.objects.filter(kind=Tenant.Kind.CLIENT).order_by("name"):
            with tenant_context(t):
                body = _admin_body(request, t)
            out.append({"id": body["client"]["id"], "name": body["client"]["name"], "status": body["status"], "label": body["label"],
                        "contract_reference": body["authorization"]["contract_reference"] if body["authorization"] else "",
                        "effective_until": body["authorization"]["effective_until"] if body["authorization"] else None,
                        "awaiting_verification": body["can"]["verify"], "awaiting_my_review": body["can"]["review"],
                        "objection_on_hold": body["status"] == "on_hold"})
        return Response({"results": out, "objection_authority": {"configured": bool(authority()), "reference": authority()}})


def _client(client_id) -> Tenant:
    if not enabled():
        raise DomainError("not_available", "Contract authorizations are not enabled.", http_status=404)
    t = Tenant.objects.filter(pk=client_id, kind=Tenant.Kind.CLIENT).first()
    if t is None:
        raise DomainError("not_found", "Client company not found.", http_status=404)
    return t


class ContractAuthorizationView(APIView):
    """Aries organisation: a client company's contract authorization for thumbnails of Aries scanning photos."""
    permission_classes = [HasCapability]
    capabilities = {"get": "contracts.thumbnail_view", "post": "contracts.thumbnail_record"}

    @extend_schema(responses=dict)
    def get(self, request, client_id):
        t = _client(client_id)
        with tenant_context(t):
            body = _admin_body(request, t)
        return Response(body)

    @extend_schema(request=dict, responses=dict)
    def post(self, request, client_id):
        t = _client(client_id)
        d = request.data
        reference = str(d.get("contract_reference", "")).strip()
        excerpt = str(d.get("clause_excerpt", "")).strip()
        if not 3 <= len(reference) <= 120:
            raise DomainError("reference_required", "Give the contract reference (3 to 120 characters).", http_status=400)
        if not 30 <= len(excerpt) <= 4000:
            raise DomainError("excerpt_required", "Give the relevant clause excerpt (30 to 4000 characters).", http_status=400)
        try:
            start, until = date.fromisoformat(str(d.get("effective_from"))), date.fromisoformat(str(d.get("effective_until")))
        except ValueError:
            raise DomainError("dates_required", "Give the effective and expiry dates (YYYY-MM-DD).", http_status=400)
        if until < start:
            raise DomainError("dates_invalid", "The expiry date is before the effective date.", http_status=400)
        scope = d.get("scope")
        if scope not in ContractAuthorization.Scope.values:
            raise DomainError("scope_required", "Scope must be company or projects.", http_status=400)
        with tenant_context(t):
            project_ids = []
            if scope == ContractAuthorization.Scope.PROJECTS:
                wanted = [str(x) for x in (d.get("project_ids") or [])]
                project_ids = [str(pk) for pk in Project.objects.filter(tenant=t, pk__in=wanted).values_list("pk", flat=True)]
                if not wanted or len(project_ids) != len(set(wanted)):
                    raise DomainError("projects_invalid", "List one or more projects of this company.", http_status=400)
            if contract_state(t)["status"] == "pending_verification":
                raise DomainError("pending_exists", "An authorization is already awaiting verification. Verify, reject or "
                                  "end it first.", http_status=409)
            name, role = _actor(request)
            auth = ContractAuthorization.objects.create(
                tenant=t, created_by=request.user, sequence=next_sequence(ContractAuthorization.objects.filter(tenant=t)),
                contract_reference=reference, clause_excerpt=excerpt, effective_from=start,
                effective_until=until, scope=scope, project_ids=project_ids, recorded_by_name=name, recorded_by_role=role,
                note=str(d.get("note", "")).strip()[:500])
        _both_trails(request, "contracts.thumbnail_authorization_recorded", t, "contract_authorization", str(auth.pk),
                     {"contract_reference": reference, "scope": scope, "effective_from": start.isoformat(),
                      "effective_until": until.isoformat(), "role": role})
        with tenant_context(t):
            body = _admin_body(request, t)
        return Response(body, status=201)


class ContractAuthorizationEventView(APIView):
    """Verify, reject or end an authorization, or document the review of a client objection (each action checks its own
    right: verification, or the separately configured objection-review authority)."""
    permission_classes = [HasCapability]
    capabilities = {"post": "contracts.thumbnail_view"}

    @extend_schema(request=dict, responses=dict)
    def post(self, request, client_id, auth_id):
        t = _client(client_id)
        action = request.data.get("action")
        name, role = _actor(request, "contract")
        with tenant_context(t):
            auth = ContractAuthorization.objects.filter(tenant=t, pk=auth_id).first()
            if auth is None:
                raise DomainError("not_found", "Authorization not found.", http_status=404)
            st = contract_state(t)
            if st["authorization"] is None or st["authorization"].pk != auth.pk:
                raise DomainError("superseded", "Only the company's current authorization can be changed.", http_status=409)
            independent = auth.created_by_id != request.user.pk
            objection, authority_ref = None, ""
            if action in ("verify", "reject", "end") and not has_capability(request, "contracts.thumbnail_verify") and not (
                    action == "end" and has_capability(request, "contracts.thumbnail_record")):
                raise DomainError("permission_denied", "Your role cannot verify, reject or end contract authorizations.", http_status=403)
            if action in ("verify", "reject"):
                if st["status"] != "pending_verification":
                    raise DomainError("not_pending", "This authorization is not awaiting verification.", http_status=409)
                if not independent:
                    raise DomainError("self_verification", "The person who recorded the authorization cannot verify it.", http_status=403)
                if action == "verify" and request.data.get("checked_against_signed_agreement") is not True:
                    raise DomainError("attestation_required", "Confirm that you checked the clause against the signed agreement.", http_status=400)
                note = _note(request, 20, "Record where and how the signed agreement was checked")
                event = E.VERIFIED if action == "verify" else E.REJECTED
            elif action == "end":
                if st["status"] in ("ended", "rejected"):
                    raise DomainError("not_active", "This authorization has already ended or was rejected.", http_status=409)
                note = _note(request, 10, "Give the reason for ending it")
                event = E.ENDED
            elif action == "review":
                block = review_block(request, t, st)
                if block in ("no_authority_configured", "not_designated"):
                    raise DomainError("no_review_authority", REVIEW_BLOCKS[block], http_status=403)
                if st["status"] != "on_hold":
                    raise DomainError("no_conflict", "There is no client objection waiting for review.", http_status=409)
                if block:
                    raise DomainError("self_review" if not independent else "not_independent", REVIEW_BLOCKS[block], http_status=403)
                outcome = request.data.get("outcome")
                if outcome not in ("proceed", "sustain"):
                    raise DomainError("outcome_required", "Outcome must be proceed or sustain.", http_status=400)
                note = _note(request, 30, "Document the rationale for your decision on the client's objection")
                event, objection, authority_ref = ((E.CONFLICT_PROCEED if outcome == "proceed" else E.CONFLICT_SUSTAINED),
                                                   st["objection"], authority())
            else:
                raise DomainError("invalid", "action must be verify, reject, end or review.", http_status=400)
            ev = ContractAuthorizationEvent.objects.create(tenant=t, created_by=request.user, authorization=auth, event=event,
                                                           sequence=next_sequence(auth.events.all()),
                                                           objection=objection, authority_reference=authority_ref, note=note,
                                                           actor_name=name, actor_role=role)
        _both_trails(request, f"contracts.thumbnail_authorization_{ev.event}", t, "contract_authorization", str(auth.pk),
                     {"event": ev.event, "role": role, "objection": str(objection.pk) if objection else "",
                      **({"authority": authority_ref, "rationale": note} if authority_ref else {})})
        with tenant_context(t):
            body = _admin_body(request, t)
        return Response(body, status=201)
