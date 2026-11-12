"""Aries organisation: passport revisions waiting for approval across client companies (Aries Admin and Aries Manager).

Each company is read inside its own tenant context (row-level security applies), the same way as the operator
overview; nothing is copied out of a company. Approve / send back run apps.passports.approval inside that company.
Aries Engineers approve from the passport inside the client company instead.
"""
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
from .content import completeness
from .models import DigitalPassport, PassportRevision


def _require_platform_approver(request) -> None:
    m = getattr(request, "membership", None)
    if m is None or not policy.is_platform_admin(m) or not has_capability(request, "passports.approve"):
        raise DomainError("permission_denied", "Only an Aries Admin or Aries Manager can open the approval queue.", http_status=403)


def _client(client_id) -> Tenant:
    t = Tenant.objects.filter(pk=client_id, kind=Tenant.Kind.CLIENT).first()
    if t is None:
        raise DomainError("not_found", "Client company not found.", http_status=404)
    return t


def _submitted(passport_id) -> tuple[DigitalPassport, PassportRevision]:
    passport = DigitalPassport.objects.select_related("part", "tenant").filter(pk=passport_id).first()
    revision = passport.revisions.filter(status=PassportRevision.Status.SUBMITTED).first() if passport else None
    if revision is None:
        raise DomainError("not_found", "No revision of this passport is waiting for approval.", http_status=404)
    return passport, revision


def _row(t: Tenant, p: DigitalPassport, r: PassportRevision) -> dict:
    return {"client_id": str(t.pk), "client_name": t.name, "passport_id": str(p.pk), "passport_number": p.passport_number,
            "title": p.title, "part_number": p.part.part_number, "part_name": p.part.name, "revision_number": r.revision_number,
            "change_summary": r.change_summary, "submitted_by_email": r.submitted_by.email if r.submitted_by_id else "",
            "submitted_at": r.submitted_at, "completeness": completeness(r.content)}


ROW = inline_serializer("PassportApprovalRow", {
    "client_id": serializers.UUIDField(), "client_name": serializers.CharField(), "passport_id": serializers.UUIDField(),
    "passport_number": serializers.CharField(), "title": serializers.CharField(), "part_number": serializers.CharField(),
    "part_name": serializers.CharField(), "revision_number": serializers.IntegerField(), "change_summary": serializers.CharField(),
    "submitted_by_email": serializers.CharField(), "submitted_at": serializers.DateTimeField(), "completeness": serializers.DictField()},
    many=True)


class PassportApprovalQueueView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"get": "passports.approve"}

    @extend_schema(tags=["passports"], responses={200: ROW})
    def get(self, request):
        _require_platform_approver(request)
        rows = []
        for t in Tenant.objects.filter(kind=Tenant.Kind.CLIENT, status=Tenant.Status.ACTIVE).order_by("name"):
            with tenant_context(t):
                for r in (PassportRevision.objects.filter(status=PassportRevision.Status.SUBMITTED)
                          .select_related("passport__part", "submitted_by").order_by("submitted_at")):
                    rows.append(_row(t, r.passport, r))
        rows.sort(key=lambda x: x["submitted_at"] or 0)
        return Response(rows)


class PassportApprovalDetailView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"get": "passports.approve", "post": "passports.approve"}

    @extend_schema(tags=["passports"], responses={200: dict})
    def get(self, request, client_id, passport_id):
        _require_platform_approver(request)
        t = _client(client_id)
        with tenant_context(t):
            passport, revision = _submitted(passport_id)
            data = {**_row(t, passport, revision), "passport_state": passport.publication_state,
                    "revision": RevisionSerializer(revision, context={"request": request, "approver": True}).data}
            record(request, "passport.approval_viewed", obj=revision, tenant=t, data={"passport": passport.passport_number})
        return Response(data)

    @extend_schema(tags=["passports"], request=inline_serializer("PassportApprovalDecision", {
        "decision": serializers.ChoiceField(choices=["approve", "return"]), "note": serializers.CharField(required=False)}),
        responses={200: dict})
    def post(self, request, client_id, passport_id):
        _require_platform_approver(request)
        decision = str(request.data.get("decision", ""))
        if decision not in ("approve", "return"):
            raise DomainError("invalid_decision", "Choose approve or return.", http_status=400)
        t = _client(client_id)
        with tenant_context(t):
            passport, revision = _submitted(passport_id)
            if decision == "approve":
                revision = approval.approve(request, passport, revision)
            else:
                revision = approval.send_back(request, passport, revision, str(request.data.get("note", "")))
            data = {"status": revision.status, "passport_state": passport.publication_state}
        return Response(data)
