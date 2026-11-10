"""CN-007 role-based AI access (AI_CLIENT_ACCESS_ENABLED; docs/brd-change-notes/CN-007-ai-access-model.md).

- Company workspace: the Aries Admin switches a client company's "My Parts Intelligence" on or off (only companies in
  AI_CLIENT_SHARING_COMPANIES can be switched on).
- Member access: the Client Admin grants or removes other members' access (Client Engineers allowed by default).
- Disclosure: an Aries Engineer who did not generate a reviewed recommendation version freezes a client-safe snapshot
  of it (approved for client sharing), then shares it; it can be withdrawn, and a newer shared result supersedes the
  older one. Information disclosure only: no approval, publication, eligibility or release is set (OQ-35, OQ-36).
- Client views read only shared snapshots, never the internal assessment tables. The snapshot is built from a
  whitelist (`client_safe`): no AI text, prompts, models, internal costs, sources, supplier or quotation references,
  margins, savings or reviewer findings. Released prices are entered explicitly by the engineer.
- Client assessment requests use the existing request workflow (kind "assessment"); they never call external AI.
- Aries Admin dashboard: aggregate counts per client company, no part-level engineering records.
"""
from __future__ import annotations

import html
import re
import shutil
import tempfile
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.audit.service import record
from apps.core.exceptions import DomainError
from apps.parts.models import SparePart, lifecycle_parts
from apps.parts.submissions import display_name
from apps.servicerequests import services as SR
from apps.servicerequests.models import ClientRequest, Notification
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Membership, Role, Tenant
from apps.tenancy.permissions import has_capability

from . import recommendation as R
from . import recommendation_service as RS
from . import service
from .models import (AIWorkspaceMember, AssessmentRun, ClientAIWorkspace, CostComparison, DisclosureEvent, FeasibilityAssessment,
                     PartAssessment, Recommendation, RecommendationReview, SharedAssessment)

SA = SharedAssessment.Status
RD = RecommendationReview.Decision
K = ClientRequest.Kind
STATEMENT = ("Information shared by Aries Engineering for your planning. It is not an engineering approval, a manufacturing "
             "authorisation, a passport publication or a production release.")
GRANTABLE = {Role.CLIENT_ENGINEER, Role.PROCUREMENT, Role.CLIENT_USER, Role.AUDITOR}
DEFAULT_ALLOWED = {Role.CLIENT_ENGINEER}
REQUEST_REASONS = {"assessment": "Assessment requested", "reassessment": "Reassessment requested",
                   "new_information": "New technical information provided"}
SUITABILITY = {"potentially_suitable": "Potentially suitable — requires engineering qualification",
               "not_qualified": "Not technically qualified at present", "excluded": "Excluded by a verified technical constraint"}


# ------------------------------------------------------------------ company workspace and member access

def workspace(tenant) -> ClientAIWorkspace | None:
    return ClientAIWorkspace.objects.filter(tenant=tenant).first()


def workspace_enabled(tenant) -> bool:
    return ClientAIWorkspace.objects.filter(tenant=tenant, enabled=True).exists()


def sharing_permitted(tenant) -> bool:
    return tenant.slug in settings.AI_CLIENT_SHARING_COMPANIES


def member_allowed(membership) -> bool:
    if membership is None or not membership.is_active:
        return False
    if membership.role == Role.CLIENT_ADMIN:
        return True
    if membership.role not in GRANTABLE:
        return False
    row = AIWorkspaceMember.objects.filter(tenant_id=membership.tenant_id, user_id=membership.user_id).first()
    return row.allowed if row else (membership.role in DEFAULT_ALLOWED or technical_user(membership))


def technical_user(membership) -> bool:
    """Four-role model: a Client User with technical submissions is allowed by default, as a Client Engineer was."""
    from apps.tenancy.permissions import four_roles

    return four_roles() and membership.role == Role.CLIENT_USER and membership.technical_access


def access(request) -> dict:
    enabled = workspace_enabled(request.tenant)
    allowed = member_allowed(request.membership)
    can = lambda c: enabled and allowed and has_capability(request, c)  # noqa: E731
    return {"enabled": enabled, "allowed": allowed, "role": request.membership.role,
            "can_request": can("ai.request"), "can_see_prices": can("ai.prices"), "can_download": can("ai.reports"),
            "can_manage_members": enabled and has_capability(request, "ai.members"), "statement": STATEMENT}


def require_workspace(request) -> None:
    if not workspace_enabled(request.tenant):
        raise DomainError("ai_workspace_off", "Spare Parts Intelligence is not enabled for your company.", http_status=403)
    if not member_allowed(request.membership):
        raise DomainError("ai_access_not_granted", "Your Client Administrator has not given you access to Spare Parts Intelligence.",
                          http_status=403)


def set_workspace(request, client: Tenant, enabled: bool, note: str = "") -> dict:
    """Aries Admin: switch a client company's workspace on or off (inside that company's tenant context)."""
    if client.kind != Tenant.Kind.CLIENT:
        raise DomainError("not_a_client", "Only client companies have a client workspace.", http_status=400)
    if enabled and not sharing_permitted(client):
        raise DomainError("sharing_not_permitted", "Client sharing for this company needs a reviewed decision first: it is not in "
                          "the list of companies approved for client AI sharing.", http_status=409)
    with tenant_context(client):
        ws, _ = ClientAIWorkspace.objects.get_or_create(tenant=client, defaults={"created_by": request.user})
        before = ws.enabled
        ws.enabled, ws.changed_by, ws.note = bool(enabled), request.user, (note or "")[:300]
        ws.save()
        record(request, "ai_workspace.switched", obj=ws, tenant=client, data={"from": before, "to": ws.enabled, "note": ws.note})
    record(request, "ai_workspace.switched", obj_type="tenant", obj_id=str(client.pk), data={"company": client.name, "from": before,
                                                                                           "to": ws.enabled})
    return {"company": str(client.pk), "enabled": ws.enabled}


def members(request) -> list[dict]:
    rows = {r.user_id: r for r in AIWorkspaceMember.objects.filter(tenant=request.tenant)}
    out = []
    for m in (Membership.objects.filter(tenant=request.tenant, is_active=True, role__in=[Role.CLIENT_ADMIN, *GRANTABLE])
              .select_related("user").order_by("user__email")):
        row = rows.get(m.user_id)
        out.append({"user": str(m.user_id), "email": m.user.email, "name": display_name(m.user), "role": m.role,
                    "role_label": m.get_role_display(), "allowed": member_allowed(m), "default": row is None,
                    "managed_by_role": m.role == Role.CLIENT_ADMIN})
    return out


def set_member(request, user_id, allowed: bool) -> list[dict]:
    m = Membership.objects.filter(tenant=request.tenant, user_id=user_id, is_active=True).select_related("user").first()
    if m is None:
        raise DomainError("not_found", "Member not found in your company.", http_status=404)
    if m.role not in GRANTABLE:
        raise DomainError("not_grantable", "Client Administrators always have access; Aries staff are not managed here.", http_status=400)
    row, _ = AIWorkspaceMember.objects.get_or_create(tenant=request.tenant, user=m.user, defaults={"created_by": request.user})
    before = member_allowed(m)
    row.allowed, row.changed_by = bool(allowed), request.user
    row.save()
    record(request, "ai_workspace.member_access_changed", obj=row, data={"member": m.user.email, "role": m.role, "from": before,
                                                                         "to": row.allowed})
    return members(request)


# ------------------------------------------------------------------ client-safe snapshot (whitelist)

def client_safe(part: SparePart, rec: Recommendation, summary: str) -> dict:
    """Only these fields ever reach a client. Requirement details, commercial figures, sources, AI text and reviewer
    findings stay internal."""
    res = rec.results or {}
    options = {}
    for k, title in R.OPTIONS.items():
        o = (res.get("options") or {}).get(k) or {}
        suit = "excluded" if o.get("excluded") else "potentially_suitable" if o.get("eligible") else "not_qualified"
        options[k] = {"title": title, "technical_status": str((o.get("technical") or {}).get("status_label", ""))[:200],
                      "suitability": suit, "suitability_label": SUITABILITY[suit],
                      "requirements": [{"label": str(q.get("label", ""))[:200], "met": bool(q.get("met"))} for q in o.get("requirements") or []]}
    outcome = res.get("outcome") or {}
    return {"part_number": part.part_number, "part_name": part.name, "summary": summary,
            "outcome": {"code": str(outcome.get("code", "")), "label": str(outcome.get("label", ""))[:300]},
            "options": options, "evidence_gaps": [str(x)[:300] for x in (res.get("missing_information") or [])][:40],
            "recommendation_version": rec.version, "feasibility_version": rec.feasibility_version,
            "cost_comparison_version": rec.cost_comparison_version, "assessed_on": rec.as_of.isoformat(), "statement": STATEMENT}


def _prices(raw) -> list[dict]:
    """Explicitly released client-facing quoted prices: one per option at most."""
    if raw in (None, ""):
        return []
    if not isinstance(raw, list) or len(raw) > len(R.OPTIONS):
        raise DomainError("invalid_prices", "Release at most one quoted price per option.", http_status=400)
    out, seen = [], set()
    for i, p in enumerate(raw):
        if not isinstance(p, dict) or p.get("option") not in R.OPTIONS or p["option"] in seen:
            raise DomainError("invalid_prices", f"Price {i + 1}: choose a different option.", http_status=400)
        try:
            amount = Decimal(str(p.get("amount")))
        except (InvalidOperation, TypeError):
            amount = Decimal(-1)
        if not amount.is_finite() or amount <= 0 or amount > Decimal("1e12"):
            raise DomainError("invalid_prices", f"Price {i + 1}: enter an amount greater than zero.", http_status=400)
        cur = str(p.get("currency") or "").strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", cur):
            raise DomainError("invalid_prices", f"Price {i + 1}: enter a three-letter currency code.", http_status=400)
        lead = p.get("lead_time_days")
        if lead not in (None, ""):
            if not str(lead).isdigit() or int(lead) > 3650:
                raise DomainError("invalid_prices", f"Price {i + 1}: lead time must be whole days.", http_status=400)
            lead = int(lead)
        else:
            lead = None
        valid = str(p.get("valid_until") or "").strip()
        if valid:
            try:
                date.fromisoformat(valid)
            except ValueError:
                raise DomainError("invalid_prices", f"Price {i + 1}: valid-until must be a date.", http_status=400)
        seen.add(p["option"])
        out.append({"option": p["option"], "option_title": R.OPTIONS[p["option"]], "amount": str(amount.quantize(Decimal("0.01"))),
                    "currency": cur, "lead_time_days": lead, "valid_until": valid or None,
                    "quote_reference": str(p.get("quote_reference") or "").strip()[:80]})
    return out


# ------------------------------------------------------------------ engineer: disclosure workflow

def _latest_rec(tenant, part):
    return (Recommendation.objects.filter(tenant=tenant, part=part).select_related("created_by").prefetch_related("reviews")
            .order_by("-version").first())


def _shares(tenant, part):
    return list(SharedAssessment.objects.filter(tenant=tenant, part=part).prefetch_related("events").order_by("-created_at"))


def state(rec, shares) -> dict:
    """Disclosure state of a part (information sharing only)."""
    approved = next((s for s in shares if s.status == SA.APPROVED), None)
    shared = next((s for s in shares if s.status == SA.SHARED), None)
    if approved:
        return {"code": "approved", "label": "Approved for client sharing (not yet shared)"}
    if shared:
        newer = rec is not None and rec.version > shared.recommendation_version
        return {"code": "shared", "label": "Shared with client" + (" (a newer internal version exists)" if newer else "")}
    if rec is None:
        return {"code": "not_assessed", "label": "No recommendation yet"}
    if shares and shares[0].status == SA.WITHDRAWN and shares[0].recommendation_version == rec.version:
        return {"code": "withdrawn", "label": "Withdrawn from the client"}
    if any(True for _ in rec.reviews.all()):
        return {"code": "engineering_reviewed", "label": "Engineering reviewed (internal)"}
    return {"code": "internal_draft", "label": "Internal draft (not reviewed)"}


def serialise_share(s: SharedAssessment, internal: bool = True) -> dict:
    out = {"id": str(s.pk), "status": s.status, "status_label": s.get_status_display(), "recommendation_version": s.recommendation_version,
           "snapshot": s.snapshot, "released_prices": s.released_prices, "shared_at": s.shared_at, "withdrawn_at": s.withdrawn_at,
           "withdrawn_reason": s.withdrawn_reason, "created_at": s.created_at}
    if internal:
        out.update({"approved_by": s.approved_by_name, "shared_by": s.shared_by_name,
                    "events": [{"event": e.event, "note": e.note, "actor": e.actor_name, "at": e.created_at} for e in s.events.all()]})
    return out


def _approval_block(request, part, rec) -> str | None:
    if not workspace_enabled(request.tenant):
        return "Client sharing is not switched on for this company (Aries Admin, AI management)."
    if rec is None:
        return "There is no recommendation to share yet."
    reviews = sorted(rec.reviews.all(), key=lambda r: r.created_at)
    if not reviews:
        return "The latest recommendation version has not been engineering-reviewed."
    if rec.created_by_id == request.user.id:
        return "You generated this recommendation version: another assigned Aries Engineer must approve it for client sharing."
    last = reviews[-1]  # post-UAT D-20: only a positive, independent review of a current version can be shared
    if last.decision not in (RD.FURTHER_STUDY, RD.CORRECTED) or not last.independent:
        return (f"The latest review of version {rec.version} is '{last.get_decision_display()}'"
                + ("" if last.independent else " by the engineer who generated it")
                + ": only a version approved for further study or corrected by an independent engineer can be shared.")
    if part.review_state in (SparePart.Review.PENDING, SparePart.Review.INFO_REQUESTED, SparePart.Review.DECLINED):
        return "This part is a client submission that Aries has not accepted into the engineering workflow."
    blockers = RS.approval_blockers(part, rec)
    if blockers:
        return blockers[0]
    return None


def confidential_terms(part) -> list[str]:
    """Aries-only passport values (manufacturing specification, process, solution) that a client summary must not repeat."""
    from apps.passports.confidential import ARIES_ONLY_RL2

    rev = getattr(part, "passport", None) and part.passport.revisions.order_by("-revision_number").first()
    rl2 = ((rev.content or {}).get("rl2") or {}) if rev else {}
    out = []

    def walk(v):
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, str) and len(v.strip()) >= 4:
            out.append(v.strip())
    for k in ARIES_ONLY_RL2:
        walk(rl2.get(k))
    return out


def part_view(request, part) -> dict:
    rec = _latest_rec(request.tenant, part)
    shares = _shares(request.tenant, part)
    block = _approval_block(request, part, rec)
    return {"workspace_enabled": workspace_enabled(request.tenant), "sharing_permitted": sharing_permitted(request.tenant),
            "state": state(rec, shares),
            "latest_recommendation": ({"id": str(rec.pk), "version": rec.version, "review_state": RS.review_state(list(rec.reviews.all().order_by("created_at"))),
                                       "created_by_name": display_name(rec.created_by)} if rec else None),
            "can_approve": has_capability(request, "ai.share") and block is None, "approve_block": block,
            "preview": client_safe(part, rec, "") if rec else None,
            "shares": [serialise_share(s) for s in shares], "options": R.OPTIONS, "statement": STATEMENT}


def _event(request, s: SharedAssessment, event: str, note: str = "") -> None:
    DisclosureEvent.objects.create(tenant=s.tenant, created_by=request.user, shared=s, part_id=s.part_id, event=event,
                                   note=note[:500], actor_name=display_name(request.user))


def approve(request, part, data: dict) -> SharedAssessment:
    rec = Recommendation.objects.filter(tenant=request.tenant, part=part, pk=data.get("recommendation")).prefetch_related("reviews").first()
    if rec is None:
        raise DomainError("not_found", "Recommendation not found for this part.", http_status=404)
    latest = Recommendation.objects.filter(tenant=request.tenant, part=part).aggregate(m=Max("version"))["m"]
    if rec.version != latest:
        raise DomainError("recommendation_superseded", f"Version {rec.version} has been superseded by version {latest}.", http_status=409)
    block = _approval_block(request, part, rec)
    if block:
        raise DomainError("self_approval" if "another assigned" in block else "not_shareable", block,
                          http_status=403 if "another assigned" in block else 409)
    summary = str(data.get("summary") or "").strip()
    if not summary:
        raise DomainError("summary_required", "Write the client summary that will be shared.", http_status=400)
    if len(summary) > 2000:
        raise DomainError("too_long", "The client summary is limited to 2000 characters.", http_status=400)
    hits = [t for t in confidential_terms(part) if t.lower() in summary.lower()]
    if hits:
        raise DomainError("summary_confidential", "The client summary repeats Aries-confidential manufacturing information from the "
                          "passport (manufacturing specification, process or solution). Remove it before sharing.", http_status=400)
    prices = _prices(data.get("released_prices"))
    if SharedAssessment.objects.filter(tenant=request.tenant, part=part, status=SA.APPROVED).exists():
        raise DomainError("approval_pending", "An approved result is waiting to be shared: share or withdraw it first.", http_status=409)
    s = SharedAssessment.objects.create(
        tenant=request.tenant, created_by=request.user, part=part, project_id=part.project_id, recommendation=rec,
        recommendation_version=rec.version, feasibility_version=rec.feasibility_version, cost_comparison_version=rec.cost_comparison_version,
        snapshot=client_safe(part, rec, summary), released_prices=prices, approved_by=request.user, approved_by_name=display_name(request.user))
    _event(request, s, "approved", f"Recommendation version {rec.version}" + (f"; {len(prices)} quoted price(s) released" if prices else ""))
    record(request, "ai_disclosure.approved", obj=part, data={"shared_assessment": str(s.pk), "recommendation_version": rec.version,
                                                             "released_prices": len(prices)})
    return s


def _share_for(request, part, sid) -> SharedAssessment:
    s = SharedAssessment.objects.filter(tenant=request.tenant, part=part, pk=sid).first()
    if s is None:
        raise DomainError("not_found", "Shared assessment not found for this part.", http_status=404)
    return s


@transaction.atomic
def share(request, part, sid) -> SharedAssessment:
    s = _share_for(request, part, sid)
    if s.status != SA.APPROVED:
        raise DomainError("transition_not_allowed", "Only a result approved for client sharing can be shared.", http_status=409)
    if not workspace_enabled(request.tenant):
        raise DomainError("not_shareable", "Client sharing is not switched on for this company.", http_status=409)
    latest = Recommendation.objects.filter(tenant=request.tenant, part=part).aggregate(m=Max("version"))["m"]
    if latest != s.recommendation_version:
        raise DomainError("recommendation_superseded", "A newer recommendation version exists: withdraw this approval and approve "
                          "the latest reviewed version.", http_status=409)
    for old in SharedAssessment.objects.select_for_update().filter(tenant=request.tenant, part=part, status=SA.SHARED):
        old.status = SA.SUPERSEDED
        old.save(update_fields=["status", "updated_at"])
        _event(request, old, "superseded", f"Replaced by version {s.recommendation_version}")
    s.status, s.shared_at, s.shared_by_name = SA.SHARED, timezone.now(), display_name(request.user)
    s.save(update_fields=["status", "shared_at", "shared_by_name", "updated_at"])
    _event(request, s, "shared")
    record(request, "ai_disclosure.shared", obj=part, data={"shared_assessment": str(s.pk), "recommendation_version": s.recommendation_version})
    _notify_client(part, f"Assessment results available: {part.part_number}",
                   f"Aries Engineering shared assessment results for {part.part_number} {part.name}."[:500])
    return s


@transaction.atomic
def withdraw(request, part, sid, reason: str) -> SharedAssessment:
    s = _share_for(request, part, sid)
    if s.status not in (SA.APPROVED, SA.SHARED):
        raise DomainError("transition_not_allowed", "This result is already withdrawn or superseded.", http_status=409)
    reason = (reason or "").strip()
    if not reason:
        raise DomainError("reason_required", "Give a reason for the withdrawal.", http_status=400)
    was_shared = s.status == SA.SHARED
    s.status, s.withdrawn_at, s.withdrawn_reason = SA.WITHDRAWN, timezone.now(), reason[:500]
    s.save(update_fields=["status", "withdrawn_at", "withdrawn_reason", "updated_at"])
    _event(request, s, "withdrawn", reason)
    record(request, "ai_disclosure.withdrawn", obj=part, data={"shared_assessment": str(s.pk), "was_shared": was_shared, "reason": reason[:500]})
    if was_shared:
        _notify_client(part, f"Assessment results withdrawn: {part.part_number}", reason[:500])
    return s


def _notify_client(part, title: str, body: str) -> None:
    users = {m.user for m in Membership.objects.filter(tenant_id=part.tenant_id, role=Role.CLIENT_ADMIN, is_active=True,
                                                       user__is_active=True).select_related("user")}
    name = Tenant.objects.filter(pk=part.tenant_id).values_list("name", flat=True).first() or ""
    Notification.objects.bulk_create([Notification(recipient=u, title=title[:200], body=body, link=f"/ai/my-parts/{part.pk}",
                                                   organisation_name=name) for u in users])


def queue(request, parts) -> dict:
    recs, shares = {}, {}
    for rec in Recommendation.objects.filter(tenant=request.tenant, part__in=parts).prefetch_related("reviews").order_by("part_id", "-version"):
        recs.setdefault(rec.part_id, rec)
    for s in SharedAssessment.objects.filter(tenant=request.tenant, part__in=parts).order_by("-created_at"):
        shares.setdefault(s.part_id, []).append(s)
    open_requests = _open_requests(request.tenant)
    rows, counts = [], {}
    for p in parts:
        st = state(recs.get(p.pk), shares.get(p.pk, []))
        counts[st["code"]] = counts.get(st["code"], 0) + 1
        shared = next((s for s in shares.get(p.pk, []) if s.status == SA.SHARED), None)
        req = open_requests.get(p.pk)
        rows.append({"id": str(p.pk), "part_number": p.part_number, "name": p.name, "state": st,
                     "recommendation_version": recs[p.pk].version if p.pk in recs else None,
                     "shared_version": shared.recommendation_version if shared else None, "shared_at": shared.shared_at if shared else None,
                     "open_request": {"reference": req.reference, "status_label": req.get_status_display()} if req else None})
    return {"parts": rows, "counts": counts, "workspace_enabled": workspace_enabled(request.tenant), "statement": STATEMENT}


# ------------------------------------------------------------------ client workspace (shared snapshots only)

def _open_requests(tenant) -> dict:
    out = {}
    for r in ClientRequest.objects.filter(tenant=tenant, kind=K.ASSESSMENT, status__in=SR.OPEN).order_by("-created_at"):
        out.setdefault(r.part_id, r)
    return out


def client_status(part_id, has_internal: bool, shares: list) -> dict:
    shared = next((s for s in shares if s.status == SA.SHARED), None)
    if shared:
        return {"code": "available", "label": "Results available", "shared_at": shared.shared_at}
    if any(s.status == SA.APPROVED for s in shares):
        return {"code": "preparing", "label": "Being prepared for sharing", "shared_at": None}
    if shares and shares[0].status == SA.WITHDRAWN:
        return {"code": "withdrawn", "label": "Results withdrawn", "shared_at": None}
    if has_internal:
        return {"code": "in_assessment", "label": "Under engineering assessment", "shared_at": None}
    return {"code": "not_assessed", "label": "Not yet assessed", "shared_at": None}


def _client_parts(tenant, request=None):
    from apps.projects.scoping import restrict

    ids = set(SharedAssessment.objects.filter(tenant=tenant).values_list("part_id", flat=True))
    scope = (lambda qs: restrict(request, qs, "project", own="submitted_by")) if request is not None else (lambda qs: qs)
    return list(scope(lifecycle_parts(SparePart.objects.filter(tenant=tenant))).order_by("part_number")) + \
        list(scope(SparePart.objects.filter(tenant=tenant, review_state__in=SparePart.NOT_IN_LIFECYCLE, pk__in=ids)).order_by("part_number"))


def client_overview(request) -> dict:
    out = {"access": access(request)}
    if not (out["access"]["enabled"] and out["access"]["allowed"]):
        return {**out, "parts": [], "counts": {}}
    parts = _client_parts(request.tenant, request)
    internal = set(FeasibilityAssessment.objects.filter(tenant=request.tenant, part__in=parts).values_list("part_id", flat=True))
    shares = {}
    for s in SharedAssessment.objects.filter(tenant=request.tenant, part__in=parts).order_by("-created_at"):
        shares.setdefault(s.part_id, []).append(s)
    reqs = _open_requests(request.tenant)
    rows, counts = [], {}
    for p in parts:
        st = client_status(p.pk, p.pk in internal, shares.get(p.pk, []))
        counts[st["code"]] = counts.get(st["code"], 0) + 1
        shared = next((s for s in shares.get(p.pk, []) if s.status == SA.SHARED), None)
        req = reqs.get(p.pk)
        rows.append({"id": str(p.pk), "part_number": p.part_number, "name": p.name, "status": st,
                     "outcome": shared.snapshot.get("outcome", {}).get("label") if shared else None,
                     "open_request": {"id": str(req.pk), "reference": req.reference, "status_label": req.get_status_display()} if req else None})
    return {**out, "parts": rows, "counts": counts}


def _client_part(request, pk) -> SparePart:
    from apps.projects.scoping import restrict

    part = restrict(request, SparePart.objects.filter(tenant=request.tenant), "project", own="submitted_by").filter(pk=pk).first()
    if part is None:
        raise DomainError("not_found", "Part not found.", http_status=404)
    return part


def client_shared(request, part) -> SharedAssessment | None:
    return SharedAssessment.objects.filter(tenant=request.tenant, part=part, status=SA.SHARED).first()


def client_view_of(s: SharedAssessment, prices: bool) -> dict:
    out = {"id": str(s.pk), "shared_at": s.shared_at, "recommendation_version": s.recommendation_version, **s.snapshot}
    out["released_prices"] = s.released_prices if prices else []
    out["prices_hidden"] = bool(s.released_prices) and not prices
    return out


def client_part(request, pk) -> dict:
    require_workspace(request)
    part = _client_part(request, pk)
    acc = access(request)
    shares = list(SharedAssessment.objects.filter(tenant=request.tenant, part=part).order_by("-created_at"))
    has_internal = FeasibilityAssessment.objects.filter(tenant=request.tenant, part=part).exists()
    shared = next((s for s in shares if s.status == SA.SHARED), None)
    # history the client may see: when results were shared, superseded or withdrawn (never internal approvals or reviewers)
    history = []
    for s in shares:
        if s.shared_at:
            later = " — replaced by a newer shared result" if s.status == SA.SUPERSEDED else ""
            history.append({"event": "shared", "label": f"Results shared (assessment version {s.recommendation_version}){later}", "at": s.shared_at})
        if s.status == SA.WITHDRAWN and s.shared_at:
            history.append({"event": "withdrawn", "label": f"Results withdrawn: {s.withdrawn_reason}", "at": s.withdrawn_at})
    requests = [{"id": str(r.pk), "reference": r.reference, "status": r.status, "status_label": r.get_status_display(),
                 "created_at": r.created_at, "remarks": r.remarks}
                for r in ClientRequest.objects.filter(tenant=request.tenant, part=part, kind=K.ASSESSMENT).order_by("-created_at")[:20]]
    record(request, "ai_workspace.part_viewed", obj=part, data={"shared_assessment": str(shared.pk) if shared else None})
    return {"access": acc, "part": {"id": str(part.pk), "part_number": part.part_number, "name": part.name},
            "status": client_status(part.pk, has_internal, shares),
            "shared": client_view_of(shared, acc["can_see_prices"]) if shared else None,
            "history": sorted(history, key=lambda h: h["at"], reverse=True), "requests": requests}


def request_assessment(request, pk, data: dict) -> ClientRequest:
    require_workspace(request)
    part = _client_part(request, pk)
    reason = str(data.get("reason") or "assessment")
    if reason not in REQUEST_REASONS:
        raise DomainError("invalid_reason", "Choose assessment, reassessment or new information.", http_status=400)
    remarks = str(data.get("remarks") or "").strip()
    if len(remarks) > 2000:
        raise DomainError("too_long", "Remarks are limited to 2000 characters.", http_status=400)
    if ClientRequest.objects.filter(tenant=request.tenant, part=part, kind=K.ASSESSMENT, status__in=SR.OPEN).exists():
        raise DomainError("request_open", "An assessment request for this part is already open: add a message to it instead.", http_status=409)
    return SR.create_request(request, kind=K.ASSESSMENT, part=part, part_number=part.part_number, part_name=part.name[:200],
                             remarks=f"{REQUEST_REASONS[reason]}.\n{remarks}".strip(), project=part.project)


def client_dashboard(request) -> dict:
    """The company's own dashboard, built only from what was shared with it and its own requests."""
    require_workspace(request)
    parts = _client_parts(request.tenant, request)
    ov = client_overview(request)
    shared = list(SharedAssessment.objects.filter(tenant=request.tenant, status=SA.SHARED))
    suit = {k: {"title": t, "potentially_suitable": 0, "not_qualified": 0, "excluded": 0} for k, t in R.OPTIONS.items()}
    gaps = 0
    for s in shared:
        for k, o in (s.snapshot.get("options") or {}).items():
            if k in suit and o.get("suitability") in suit[k]:
                suit[k][o["suitability"]] += 1
        gaps += len(s.snapshot.get("evidence_gaps") or [])
    by_quarter = {}  # parts with results shared in the quarter (a re-share of the same part counts once)
    for s in SharedAssessment.objects.filter(tenant=request.tenant, shared_at__isnull=False):
        by_quarter.setdefault(f"{s.shared_at.year}-Q{(s.shared_at.month - 1) // 3 + 1}", set()).add(s.part_id)
    by_quarter = {q: len(v) for q, v in by_quarter.items()}
    reqs = ClientRequest.objects.filter(tenant=request.tenant, kind=K.ASSESSMENT)
    return {"access": ov["access"], "parts_in_scope": len(parts), "status_counts": ov["counts"], "results_available": len(shared),
            "option_suitability": suit, "evidence_gaps": gaps,
            "released_quotes": sum(len(s.released_prices) for s in shared) if ov["access"]["can_see_prices"] else None,
            "requests": {"open": reqs.filter(status__in=SR.OPEN).count(), "total": reqs.count()},
            "shared_by_quarter": [{"quarter": q, "shared": n} for q, n in sorted(by_quarter.items())], "statement": STATEMENT}


def client_report(request, pk) -> tuple[bytes, str]:
    """Client-facing PDF of the shared result only (the internal assessment reports stay Aries-internal)."""
    from apps.reports.services import _run

    require_workspace(request)
    part = _client_part(request, pk)
    s = client_shared(request, part)
    if s is None:
        raise DomainError("not_shared", "No assessment results have been shared for this part.", http_status=404)
    v = client_view_of(s, has_capability(request, "ai.prices"))
    e = html.escape
    rows = "".join(f"<tr><td>{e(o['title'])}</td><td>{e(o['suitability_label'])}</td><td>{e(o['technical_status'])}</td><td>"
                   + "<br>".join(("✔ " if q["met"] else "✘ ") + e(q["label"]) for q in o["requirements"]) + "</td></tr>"
                   for o in v["options"].values())
    prices = "".join(f"<tr><td>{e(p['option_title'])}</td><td>{e(p['currency'])} {e(p['amount'])}</td><td>{p['lead_time_days'] if p['lead_time_days'] is not None else '—'}</td>"
                     f"<td>{e(p['valid_until'] or '—')}</td><td>{e(p['quote_reference'] or '—')}</td></tr>" for p in v["released_prices"])
    gaps = "".join(f"<li>{e(g)}</li>" for g in v["evidence_gaps"]) or "<li>None recorded</li>"
    company = Tenant.objects.filter(pk=request.tenant.pk).values_list("name", flat=True).first() or ""
    doc = f"""<!doctype html><html><head><meta charset="utf-8"><style>
body {{ font-family: Arial, sans-serif; font-size: 10pt; color: #1f2933; }} h1 {{ font-size: 15pt; margin: 0 0 4px; }}
h2 {{ font-size: 11.5pt; margin: 16px 0 6px; border-bottom: 1px solid #cbd2d9; }} .note {{ background: #eef6f6; padding: 6px 8px; }}
table {{ border-collapse: collapse; width: 100%; }} th, td {{ border: 1px solid #d9e2ec; padding: 4px 6px; text-align: left; vertical-align: top; }}
th {{ background: #f0f4f8; }}</style></head><body>
<h1>Spare Parts Intelligence: {e(v['part_number'])} {e(v['part_name'])}</h1>
<div>{e(company)} · shared {e(timezone.localtime(s.shared_at).strftime('%d %b %Y'))} · assessment version {v['recommendation_version']} (assessed {e(v['assessed_on'])})</div>
<p class="note">{e(STATEMENT)}</p>
<h2>Summary from Aries Engineering</h2><p>{e(v['summary'])}</p>
<h2>Outcome</h2><p>{e(v['outcome']['label'])}</p>
<h2>Manufacturing options</h2><table><thead><tr><th>Option</th><th>Suitability</th><th>Technical status</th><th>Mandatory requirements</th></tr></thead><tbody>{rows}</tbody></table>
<h2>Evidence gaps (information that would help)</h2><ul>{gaps}</ul>
{f'<h2>Quoted prices released to you</h2><table><thead><tr><th>Option</th><th>Price</th><th>Lead time (days)</th><th>Valid until</th><th>Quote reference</th></tr></thead><tbody>{prices}</tbody></table>' if prices else ''}
</body></html>"""
    footer = ('<div style="font-size:7pt;width:100%;padding:0 12mm;color:#52606d">Client information · not an approval or release'
              ' · page <span class="pageNumber"></span> of <span class="totalPages"></span></div>')
    workdir = Path(tempfile.mkdtemp(prefix="client-assessment-"))
    try:
        (workdir / "report.html").write_text(doc, encoding="utf-8")
        result = _run({"mode": "pdf", "html": str(workdir / "report.html"), "out": str(workdir / "report.pdf"), "footer": footer}, workdir)
        if not result.get("ok"):
            raise DomainError("report_render_failed", "The report could not be rendered. Try again later.", http_status=503)
        body = (workdir / "report.pdf").read_bytes()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    record(request, "ai_workspace.report_downloaded", obj=part, data={"shared_assessment": str(s.pk), "prices": bool(v["released_prices"])})
    return body, f"assessment-{part.part_number}-v{s.recommendation_version}.pdf"


# ------------------------------------------------------------------ Aries Admin: AI management dashboard (aggregates only)

def _money_add(bucket: dict, other: dict) -> None:
    for cur, v in (other or {}).items():
        bucket[cur] = str(Decimal(bucket.get(cur, "0")) + Decimal(str(v)))


def _bare_row(t) -> dict:
    zero = {"preliminary": 0, "information_requested": 0, "reviewed": 0, "pending": 0, "with_recommendation": 0}
    return {"id": str(t.pk), "company": t.name, "workspace_enabled": False, "sharing_permitted": sharing_permitted(t),
            "external_ai_permitted": t.slug in settings.AI_ALLOWED_COMPANIES, "inventory": {"parts": None, "imported": 0},
            "classification": {"verified": 0, "ai_suggested": 0}, "feasibility": {"assessed": 0, "additive": {}, "conventional": {}},
            "reviews": zero, "savings": {"estimated": {}, "verified": {}}, "trend": [], "disclosure": {"shared": 0, "awaiting_share": 0},
            "open_requests": 0}


def admin_dashboard(request) -> dict:
    companies, totals = [], {"imported": 0, "classified": 0, "feasibility": 0, "pending_reviews": 0, "shared": 0, "open_requests": 0,
                             "estimated": {}, "verified": {}}
    for t in Tenant.objects.filter(kind=Tenant.Kind.CLIENT).order_by("name"):
        with tenant_context(t):
            imported = list(lifecycle_parts(SparePart.objects.filter(tenant=t)).only("id", "field_provenance", "category"))
            enabled = workspace_enabled(t)
            if not imported and not enabled:  # nothing to aggregate: listed for client access only
                companies.append(_bare_row(t))
                continue
            ids = [p.pk for p in imported]
            classified = sum(1 for p in imported if ((p.field_provenance or {}).get("category") or {}).get("verified_by"))
            suggested = PartAssessment.objects.filter(tenant=t, part_id__in=ids, status=PartAssessment.Status.OK).values("part_id").distinct().count()
            latest_fa = {}
            for fa in FeasibilityAssessment.objects.filter(tenant=t, part_id__in=ids).order_by("part_id", "-version"):
                latest_fa.setdefault(fa.part_id, fa)
            feas = {"assessed": len(latest_fa), "additive": {}, "conventional": {}}
            for fa in latest_fa.values():
                for k, st in (("additive", fa.additive_status), ("conventional", fa.conventional_status)):
                    feas[k][st] = feas[k].get(st, 0) + 1
            latest_rec = {}
            for rec in Recommendation.objects.filter(tenant=t, part_id__in=ids).prefetch_related("reviews").order_by("part_id", "-version"):
                latest_rec.setdefault(rec.part_id, rec)
            review = {"preliminary": 0, "information_requested": 0, "reviewed": 0}
            for rec in latest_rec.values():
                code = RS.review_state(list(rec.reviews.all().order_by("created_at")))["code"]
                review["reviewed" if code not in review or code == "reviewed" else code] += 1
            runs = list(AssessmentRun.objects.filter(tenant=t, status__in=[AssessmentRun.Status.COMPLETED, AssessmentRun.Status.COMPLETED_WITH_ERRORS])
                        .order_by("number"))
            last = runs[-1].summary if runs else {}
            sav = (last or {}).get("savings") or {}
            trend = [{"run": r.number, "quarter": r.quarter, "finished_at": r.finished_at, "assessed": (r.summary or {}).get("assessed", 0),
                      "estimated": ((r.summary or {}).get("savings") or {}).get("estimated", {}),
                      "verified": ((r.summary or {}).get("savings") or {}).get("verified", {})} for r in runs[-8:]]
            shared = SharedAssessment.objects.filter(tenant=t, status=SA.SHARED).count()
            awaiting = SharedAssessment.objects.filter(tenant=t, status=SA.APPROVED).count()
            open_req = ClientRequest.objects.filter(tenant=t, kind=K.ASSESSMENT, status__in=SR.OPEN).count()
            row = {"id": str(t.pk), "company": t.name, "workspace_enabled": enabled, "sharing_permitted": sharing_permitted(t),
                   "external_ai_permitted": t.slug in settings.AI_ALLOWED_COMPANIES,
                   "inventory": {"parts": SparePart.objects.filter(tenant=t).count(), "imported": len(imported)},
                   "classification": {"verified": classified, "ai_suggested": suggested},
                   "feasibility": feas, "reviews": {**review, "pending": review["preliminary"] + review["information_requested"],
                                                    "with_recommendation": len(latest_rec)},
                   "savings": {"estimated": sav.get("estimated", {}), "verified": sav.get("verified", {})},
                   "trend": trend, "disclosure": {"shared": shared, "awaiting_share": awaiting}, "open_requests": open_req}
        companies.append(row)
        totals["imported"] += len(imported)
        totals["classified"] += classified
        totals["feasibility"] += feas["assessed"]
        totals["pending_reviews"] += row["reviews"]["pending"]
        totals["shared"] += shared
        totals["open_requests"] += open_req
        _money_add(totals["estimated"], row["savings"]["estimated"])
        _money_add(totals["verified"], row["savings"]["verified"])
    record(request, "ai_management.viewed", obj_type="ai_management", obj_id="dashboard", data={"companies": len(companies)})
    return {"companies": companies, "totals": totals, "usage": service.usage_summary(tenant=None),
            "ai": {k: v for k, v in service.ai_status(None).items() if k != "reason"},
            "note": "Aggregate counts only: no part numbers, descriptions, drawings, files, prices per part or engineering records. "
                    "Estimated savings are provisional; verified savings meet every mandatory requirement with current quotations."}
