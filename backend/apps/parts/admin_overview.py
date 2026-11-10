"""Aries Admin inventory overview: administrative summaries across client companies (read-only, audited).

What it is: a read model built per client company inside that company's tenant context (RLS applies to every query),
returning summary fields only: company, part number and name, project, passport reference and revision, review status,
digitisation stage, publication state, engineering completeness counts, document counts and assigned Aries Engineers.

Thumbnails: each row on the returned page may carry `preview: {"token": ..., "route": ...}` for one sanitized photo
thumbnail, only where the company's own Client Administrator has allowed it (route "consent", apps.files.admin_thumbnails,
default OFF) or, failing that, for QA-confirmed Aries scanning photos under an independently verified, unexpired, in-scope
contract authorization with no unresolved client objection (route "contract", apps.files.thumbnail_provenance). The token
is bound to this user, company, thumbnail and the records it was issued under; every use is re-checked and audited.

What it is not: no engineering edits, no engineering notes, no file names or downloads, no CAD originals, no approval,
publication or manufacturing actions. Opening a full client record stays disabled until the support-access consent
decision OQ-37 (CN-002 D3/U1) is made. Every view is audited in the Aries audit trail and in each company's own trail.
"""
from django.db.models import Count
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.service import record
from apps.files import admin_thumbnails, thumbnail_provenance
from apps.files.models import EngineeringFile
from apps.passports.content import completeness
from apps.passports.models import DigitalPassport, PassportRevision
from apps.projects.models import EngineerAccess, Project, ProjectAssignment
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Membership, Role, Tenant
from apps.tenancy.permissions import HasCapability, authoring_allowed

from .api import STAGES, stage_q
from .models import SparePart
from .submissions import display_name

DETAIL_ACCESS = {"enabled": False, "decision": "OQ-37",
                 "reason": "Opening a full client record needs the client support-access consent decision (OQ-37, CN-002 U1). "
                           "Administrative summaries only."}
PUBLISHED = DigitalPassport.PublicationState.PUBLISHED


def detail_access() -> dict:
    """Opening full client records: closed (OQ-37) unless the Aries Admin super-administrator workspaces are switched on."""
    from apps.tenancy import admin_workspace

    if not admin_workspace.enabled():
        return DETAIL_ACCESS
    return {"enabled": True, "decision": "ADMIN_WORKSPACE (proposed OQ-37 revision, access-test)",
            "reason": "Open record works inside the client company's own workspace; every action is recorded in its audit trail. "
                      "Confidential file content needs a documented decision per company."}


def _engineers(tenant) -> list[tuple[str, set | None]]:
    """Aries Engineers active in this company with their project scope (None = company-wide)."""
    out = []
    for m in Membership.objects.filter(tenant=tenant, role=Role.OPERATOR_ENGINEER, is_active=True).select_related("user"):
        if not authoring_allowed(m):  # QA-only engineers are not responsible for the engineering work
            continue
        access = EngineerAccess.objects.filter(tenant=tenant, user=m.user).first()
        scope = None
        if access and access.scope == EngineerAccess.Scope.PROJECTS:
            scope = set(ProjectAssignment.objects.filter(tenant=tenant, user=m.user, is_active=True).values_list("project_id", flat=True))
        out.append((display_name(m.user), scope))
    return out


def _stage(part, passport) -> str:
    if part.review_state in SparePart.OPEN_REVIEW:
        return "review"
    if part.review_state == SparePart.Review.DECLINED:
        return "declined"
    if passport and passport.publication_state == PUBLISHED:
        return "published"
    return "in_digitisation"


def _digitisation(part, passport) -> str:
    if part.review_state in SparePart.OPEN_REVIEW:
        return "Not started (awaiting Aries review)"
    if part.review_state == SparePart.Review.DECLINED:
        return "Not started (submission rejected)"
    if passport is None:
        return "No passport yet"
    return {"none": "Passport draft · data incomplete", "rl1": "R-L1 data captured", "rl2": "R-L2 data captured",
            "rl3": "R-L3 evidence captured"}.get(passport.data_captured, passport.data_captured)


class AdminInventoryView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"get": "inventory.admin_overview"}

    @extend_schema(parameters=[
        OpenApiParameter("client", str), OpenApiParameter("project", str),
        OpenApiParameter("review_state", str, description="open, pending_review, info_requested, accepted, declined, not_required"),
        OpenApiParameter("publication", str, enum=["published", "not_published"]),
        OpenApiParameter("stage", str, enum=STAGES), OpenApiParameter("search", str),
        OpenApiParameter("page", int), OpenApiParameter("page_size", int)],
        responses=inline_serializer("AdminInventory", {
            "count": serializers.IntegerField(), "page": serializers.IntegerField(), "page_size": serializers.IntegerField(),
            "results": serializers.ListField(child=serializers.DictField()),
            "totals": serializers.DictField(child=serializers.IntegerField()),
            "clients": serializers.ListField(child=serializers.DictField()),
            "all_clients": serializers.ListField(child=serializers.DictField()),
            "projects": serializers.ListField(child=serializers.DictField()),
            "detail_access": serializers.DictField()}))
    def get(self, request):
        p = request.query_params
        clients = Tenant.objects.filter(kind=Tenant.Kind.CLIENT).order_by("name")
        all_clients = [{"id": str(t.pk), "name": t.name, "slug": t.slug} for t in clients]
        if p.get("client"):
            clients = clients.filter(pk=p["client"])
        q = p.get("search", "").strip().lower()
        rows, summaries, projects = [], [], []
        thumbs = {}  # row id -> (company, derivative id, token basis, route)
        totals = {"all": 0, **{k: 0 for k in STAGES}}
        filters = {k: p.get(k) for k in ("client", "project", "review_state", "publication", "stage", "search") if p.get(k)}
        for t in clients:
            with tenant_context(t):
                engineers = _engineers(t)
                projects += [{"id": str(x.pk), "code": x.code, "name": x.name, "client": str(t.pk)}
                             for x in Project.objects.filter(tenant=t).order_by("code")]
                qs = SparePart.objects.filter(tenant=t).select_related("project")
                if p.get("project"):
                    qs = qs.filter(project_id=p["project"])
                if p.get("review_state") == "open":
                    qs = qs.filter(review_state__in=SparePart.OPEN_REVIEW)
                elif p.get("review_state") in SparePart.Review.values:
                    qs = qs.filter(review_state=p["review_state"])
                if p.get("publication") == "published":
                    qs = qs.filter(passport__publication_state=PUBLISHED)
                elif p.get("publication") == "not_published":
                    qs = qs.exclude(passport__publication_state=PUBLISHED)
                if q:
                    qs = qs.filter(part_number__icontains=q) | qs.filter(name__icontains=q)
                counts = {"all": qs.count(), **{k: qs.filter(stage_q(k)).count() for k in STAGES}}
                if p.get("stage") in STAGES:
                    qs = qs.filter(stage_q(p["stage"]))
                parts = list(qs.order_by("-updated_at")[:2000])
                passports = {pp.part_id: pp for pp in DigitalPassport.objects.filter(part_id__in=[x.pk for x in parts])}
                latest = {}
                for rev in PassportRevision.objects.filter(passport_id__in=[pp.pk for pp in passports.values()]).order_by("passport_id", "-revision_number"):
                    latest.setdefault(rev.passport_id, rev)
                docs = dict(EngineeringFile.objects.filter(tenant=t, part_id__in=[x.pk for x in parts]).values("part_id")
                            .annotate(n=Count("id")).values_list("part_id", "n"))
                grant, route, contract = admin_thumbnails.active_grant(t), None, None
                if grant is not None:
                    route, eligible = "consent", admin_thumbnails.eligible_thumbnails(t)
                    thumbs.update({str(x.pk): (t, eligible[x.pk], {"r": "c", "c": str(grant.pk)}, route) for x in parts if x.pk in eligible})
                if thumbnail_provenance.enabled():
                    contract = thumbnail_provenance.contract_state(t)
                    if grant is None and contract["status"] == "active":
                        route, eligible = "contract", thumbnail_provenance.contract_eligible(t, contract)
                        thumbs.update({str(x.pk): (t, eligible[x.pk][0], {"r": "a", **eligible[x.pk][1]}, route)
                                       for x in parts if x.pk in eligible})
                for part in parts:
                    pp = passports.get(part.pk)
                    rev = latest.get(pp.pk) if pp else None
                    c = completeness(rev.content) if rev else None
                    assigned = [n for n, scope in engineers if scope is None or (part.project_id and part.project_id in scope)]
                    rows.append({
                        "id": str(part.pk), "client_id": str(t.pk), "client_name": t.name, "client_slug": t.slug, "part_number": part.part_number,
                        "name": part.name, "project": part.project.code if part.project_id else "",
                        "project_name": part.project.name if part.project_id else "", "origin": part.origin,
                        "review_state": part.review_state, "submission_kind": part.submission_kind,
                        "stage": _stage(part, pp), "digitisation": _digitisation(part, pp),
                        "passport_number": pp.passport_number if pp else "", "revision": rev.revision_number if rev else None,
                        "revision_status": rev.status if rev else "", "publication_state": pp.publication_state if pp else "",
                        "manufacturing_eligibility": pp.manufacturing_eligibility if pp else "",
                        "completeness": {k: {"done": v["done"], "total": v["total"]} for k, v in c.items()} if c else None,
                        "completeness_pct": round(100 * sum(v["done"] for v in c.values()) / sum(v["total"] for v in c.values())) if c else 0,
                        "documents": docs.get(part.pk, 0), "assigned_engineers": assigned,
                        "updated_at": part.updated_at.isoformat(),
                    })
                summaries.append({"id": str(t.pk), "name": t.name, "counts": counts, "thumbnails_allowed": route is not None,
                                  "thumbnail_route": route, "contract_status": contract["status"] if contract else None,
                                  "engineers": [n for n, _ in engineers], "unassigned_review": sum(
                                      1 for r in rows if r["client_id"] == str(t.pk) and r["stage"] == "review" and not r["assigned_engineers"])})
                for k in totals:
                    totals[k] += counts[k]
                # transparency for the client: the company's own audit trail shows the administrative view
                record(request, "inventory.admin_summary_viewed", tenant=t, obj_type="tenant", obj_id=str(t.pk),
                       data={"by": "Aries Admin", "rows": counts["all"], "filters": filters})
        page = max(int(p.get("page", 1) or 1), 1)
        size = min(max(int(p.get("page_size", 25) or 25), 1), 200)
        results = rows[(page - 1) * size: page * size]
        for r in results:  # thumbnail tokens only for the rows actually returned
            hit = thumbs.get(r["id"])
            r["preview"] = {"token": admin_thumbnails.issue(request.user, hit[0], hit[1], hit[2]), "route": hit[3]} if hit else None
        issued = sum(1 for r in results if r["preview"])
        by_route = {k: sum(1 for r in results if r["preview"] and r["preview"]["route"] == k) for k in ("consent", "contract")}
        record(request, "inventory.admin_overview_viewed", obj_type="inventory", obj_id="all",
               data={"clients": len(summaries), "rows": len(rows), "filters": filters, "thumbnails_issued": issued,
                     "thumbnails_by_route": by_route})
        return Response({"count": len(rows), "page": page, "page_size": size, "results": results,
                         "totals": totals, "clients": summaries,
                         "all_clients": all_clients, "projects": projects, "detail_access": detail_access()})
