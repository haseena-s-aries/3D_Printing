"""Aries organisation: the passport register across client companies, for the Aries Admin and Aries Manager.

Passports live inside each client company. Aries Admins and Managers work from the Aries organisation, so this read model
lists every company's passports and opens one read-only (data, revisions, documents, reports, 3D model), each company read
inside its own tenant context (row-level security applies). Every opening is audited in that company's trail. Publish /
unpublish run apps.passports.approval inside the company (decision of 13 Nov 2026). Editing stays with Aries Engineers.
"""
from django.db.models import Q
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.service import record
from apps.core.exceptions import DomainError
from apps.tenancy import membership_policy as policy
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Tenant
from apps.tenancy.permissions import HasCapability, has_capability

from . import approval
from .api import RevisionSerializer
from .approval_api import _evidence_files, _part_files, _reports, file_response, open_part_file, stream_report
from .content import completeness
from .models import DigitalPassport, PassportRevision


def _require_platform_admin(request) -> None:
    m = getattr(request, "membership", None)
    if m is None or not policy.is_platform_admin(m):
        raise DomainError("permission_denied", "Only an Aries Admin or Aries Manager can open the passport register.", http_status=403)


def _client(client_id) -> Tenant:
    t = Tenant.objects.filter(pk=client_id, kind=Tenant.Kind.CLIENT).first()
    if t is None:
        raise DomainError("not_found", "Client company not found.", http_status=404)
    return t


def _passport(passport_id) -> DigitalPassport:
    p = DigitalPassport.objects.select_related("part", "tenant").filter(pk=passport_id).first()
    if p is None:
        raise DomainError("not_found", "Passport not found.", http_status=404)
    return p


def _current(p: DigitalPassport) -> PassportRevision | None:
    return p.revisions.select_related("approved_by", "submitted_by").order_by("-revision_number").first()


def _row(t: Tenant, p: DigitalPassport, r: PassportRevision | None) -> dict:
    return {"client_id": str(t.pk), "client_name": t.name, "passport_id": str(p.pk), "passport_number": p.passport_number,
            "title": p.title, "part_number": p.part.part_number, "part_name": p.part.name, "passport_state": p.publication_state,
            "passport_state_label": p.get_publication_state_display(), "evidence_level": p.evidence_level,
            "manufacturing_eligibility": p.manufacturing_eligibility, "revision_number": r.revision_number if r else None,
            "revision_status": r.status if r else "", "completeness": completeness(r.content) if r else {}, "updated_at": p.updated_at}


ROWS = inline_serializer("OperatorPassportRow", {
    "client_id": serializers.UUIDField(), "client_name": serializers.CharField(), "passport_id": serializers.UUIDField(),
    "passport_number": serializers.CharField(), "title": serializers.CharField(), "part_number": serializers.CharField(),
    "part_name": serializers.CharField(), "passport_state": serializers.CharField(), "passport_state_label": serializers.CharField(),
    "evidence_level": serializers.CharField(), "manufacturing_eligibility": serializers.CharField(),
    "revision_number": serializers.IntegerField(allow_null=True), "revision_status": serializers.CharField(),
    "completeness": serializers.DictField(), "updated_at": serializers.DateTimeField()}, many=True)


class OperatorPassportListView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"get": "passports.view"}

    @extend_schema(tags=["passports"], responses={200: ROWS})
    def get(self, request):
        _require_platform_admin(request)
        p = request.query_params
        state, search, client = p.get("state", ""), p.get("search", "").strip(), p.get("client", "")
        tenants = Tenant.objects.filter(kind=Tenant.Kind.CLIENT, status=Tenant.Status.ACTIVE).order_by("name")
        if client:
            tenants = tenants.filter(pk=client)
        rows = []
        for t in tenants:
            with tenant_context(t):
                qs = DigitalPassport.objects.select_related("part").order_by("-updated_at")
                if state:
                    qs = qs.filter(publication_state=state)
                if search:
                    qs = qs.filter(Q(passport_number__icontains=search) | Q(title__icontains=search) | Q(part__part_number__icontains=search))
                for passport in qs[:300]:
                    rows.append(_row(t, passport, _current(passport)))
        rows.sort(key=lambda r: str(r["updated_at"]), reverse=True)
        return Response(rows[:500])


class OperatorPassportDetailView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"get": "passports.view", "post": "passports.publish"}

    @extend_schema(tags=["passports"], responses={200: dict})
    def get(self, request, client_id, passport_id):
        _require_platform_admin(request)
        t = _client(client_id)
        with tenant_context(t):
            p = _passport(passport_id)
            r = _current(p)
            if r is None:
                raise DomainError("not_found", "This passport has no revision yet.", http_status=404)
            revisions = [{"revision_number": x.revision_number, "status": x.status, "change_summary": x.change_summary,
                          "completed_by_email": x.approved_by.email if x.approved_by_id else "", "completed_at": x.approved_at,
                          "created_at": x.created_at}
                         for x in p.revisions.select_related("approved_by").order_by("-revision_number")]
            data = {**_row(t, p, r), "change_summary": r.change_summary,
                    "submitted_by_email": r.approved_by.email if r.approved_by_id else "", "submitted_at": r.approved_at,
                    "revision": RevisionSerializer(r, context={"request": request, "approver": True}).data,
                    "evidence_files": _evidence_files(r), "files": _part_files(request, p), "reports": _reports(p),
                    "revisions": revisions, "can_publish": has_capability(request, "passports.publish")}
            record(request, "passport.viewed_by_aries", obj=p, tenant=t, data={"passport": p.passport_number})
        return Response(data)

    @extend_schema(tags=["passports"], request=inline_serializer("PassportPublishDecision", {
        "action": serializers.ChoiceField(choices=["publish", "unpublish"]), "reason": serializers.CharField(required=False)}),
        responses={200: dict})
    def post(self, request, client_id, passport_id):
        _require_platform_admin(request)
        action = str(request.data.get("action", ""))
        if action not in ("publish", "unpublish"):
            raise DomainError("invalid_action", "Choose publish or unpublish.", http_status=400)
        t = _client(client_id)
        with tenant_context(t):
            p = _passport(passport_id)
            if action == "publish":
                approval.publish(request, p)
            else:
                approval.unpublish(request, p, str(request.data.get("reason", "") or ""))
            data = {"passport_state": p.publication_state}
        return Response(data)


class OperatorPassportFileView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"get": "passports.view"}

    @extend_schema(tags=["passports"], responses={(200, "application/octet-stream"): bytes})
    def get(self, request, client_id, passport_id, file_id):
        _require_platform_admin(request)
        variant = request.query_params.get("variant", "preview")
        t = _client(client_id)
        with tenant_context(t):
            key, name, ctype = open_part_file(request, t, _passport(passport_id), file_id, variant, {"by_aries_register": True})
        return file_response(key, name, ctype, variant == "original")


class OperatorPassportReportView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"get": "passports.view"}

    @extend_schema(tags=["passports"], responses={(200, "application/pdf"): bytes})
    def get(self, request, client_id, passport_id, report_id):
        _require_platform_admin(request)
        t = _client(client_id)
        with tenant_context(t):
            return stream_report(request, t, _passport(passport_id), report_id, {"by_aries_register": True})
