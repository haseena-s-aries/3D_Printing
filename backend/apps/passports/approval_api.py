"""Aries organisation: passport revisions waiting for approval across client companies (Aries Admin and Aries Manager).

Approvers must see the evidence itself: while a revision is waiting for approval, the approver can list the part's
engineering files and preview / download them or open the 3D model (business decision of 12 Nov 2026: reviewing the
documents is part of approving). Only files of the passport's spare part, only while a revision is submitted, every
opening audited in the client company's trail.

Each company is read inside its own tenant context (row-level security applies), the same way as the operator
overview; nothing is copied out of a company. Approve / send back run apps.passports.approval inside that company.
Aries Engineers approve from the passport inside the client company instead.
"""
from django.http import FileResponse
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


def _evidence_files(revision: PassportRevision) -> dict:
    """R-L3 evidence references (file ids) with their titles, so the approver sees document names instead of ids.
    Metadata only: file content stays behind the usual download rules."""
    from apps.files.models import EngineeringFile

    ids = [v for v in ((revision.content or {}).get("rl3") or {}).get("evidence", {}).values() if v]
    return {str(f.pk): {"title": f.title, "category": f.get_category_display(), "kind": f.kind}
            for f in EngineeringFile.objects.filter(pk__in=ids)}


def _part_files(request, passport: DigitalPassport) -> list:
    from apps.files.api import EngineeringFileSerializer
    from apps.files.models import EngineeringFile

    qs = EngineeringFile.objects.filter(part=passport.part).order_by("category", "title")
    return EngineeringFileSerializer(qs, many=True, context={"request": request}).data


def _reports(passport: DigitalPassport) -> list:
    """Generated passport reports (newest first), so the approver can read the report the engineer produced."""
    from apps.reports.models import PassportReport

    out = []
    for r in PassportReport.objects.filter(passport=passport).select_related("created_by").order_by("-created_at"):
        out.append({"id": str(r.pk), "number": r.number, "variant": r.variant, "variant_label": r.get_variant_display(),
                    "template": r.get_template_display(), "revision_number": r.revision_number, "revision_status": r.revision_status,
                    "created_at": r.created_at, "created_by_email": r.created_by.email if r.created_by_id else "",
                    "withdrawn": hasattr(r, "withdrawal")})
    return out


def stream_report(request, t: Tenant, passport: DigitalPassport, report_id, audit: dict):
    """One generated report of the passport as inline PDF; logged as a preview in the client company. Call inside its
    tenant context. Shared by the approval queue and the Aries passport register (apps.passports.operator_api)."""
    from django.http import HttpResponse

    from apps.reports import services as report_services
    from apps.reports.models import PassportReport, PassportReportEvent

    report = PassportReport.objects.filter(pk=report_id, passport=passport).first()
    if report is None:
        raise DomainError("not_found", "Report not found for this passport.", http_status=404)
    pdf = report_services.read_pdf(report)  # refuses withdrawn reports and missing files
    PassportReportEvent.objects.create(tenant=t, created_by=request.user, report=report, action=PassportReportEvent.Action.PREVIEWED)
    record(request, "passport_report.previewed", obj=report, tenant=t, data={"number": report.number, "variant": report.variant, **audit})
    resp = HttpResponse(pdf, content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="{report.number}.pdf"'
    resp["Cache-Control"] = "no-store"
    return resp


def open_part_file(request, t: Tenant, passport: DigitalPassport, file_id, variant: str, audit: dict) -> tuple:
    """(storage key, file name, content type) of one engineering file of the passport's spare part, audited in the client
    company: `preview` (PDF or photo), `original` (download) or `glb` (3D model of a STEP file). Call inside its tenant context."""
    from apps.files.models import Derivative, EngineeringFile

    if variant not in ("preview", "original", "glb"):
        raise DomainError("invalid_variant", "Choose preview, original or glb.", http_status=400)
    ef = EngineeringFile.objects.filter(pk=file_id, part=passport.part).first()
    fv = ef.versions.order_by("-version_number").first() if ef else None
    if fv is None:
        raise DomainError("not_found", "File not found for this passport.", http_status=404)
    if variant == "glb":
        d = fv.derivatives.filter(kind=Derivative.Kind.GLB).first()
        if d is None:
            raise DomainError("derivative_not_available", "No 3D model is available for this file yet.", http_status=404)
        key, name, ctype, obj = d.storage_key, f"{fv.original_filename.rsplit('.', 1)[0]}.glb", "model/gltf-binary", d
    else:
        if variant == "preview" and ef.kind not in (EngineeringFile.Kind.PDF, EngineeringFile.Kind.IMAGE):
            raise DomainError("preview_not_available", "In-browser preview is available for PDF documents and photographs only.",
                              http_status=400)
        key, name, ctype, obj = fv.storage_key, fv.original_filename, fv.content_type or None, fv
    record(request, "file.previewed" if variant != "original" else "file.downloaded", obj=obj, tenant=t,
           data={"variant": variant, "passport": passport.passport_number, **audit})
    return key, name, ctype


def file_response(key, name, ctype, attachment: bool):
    from apps.files.storage import get_storage

    resp = FileResponse(get_storage().open(key), as_attachment=attachment, filename=name, content_type=ctype)
    resp["X-Content-Type-Options"] = "nosniff"
    resp["Cache-Control"] = "no-store"
    return resp


class PassportApprovalReportView(APIView):
    """One generated report of the passport as PDF (inline), for the approver; logged as a preview in the client company."""

    permission_classes = [HasCapability]
    capabilities = {"get": "passports.approve"}

    @extend_schema(tags=["passports"], responses={(200, "application/pdf"): bytes})
    def get(self, request, client_id, passport_id, report_id):
        _require_platform_approver(request)
        t = _client(client_id)
        with tenant_context(t):
            passport, revision = _submitted(passport_id)
            return stream_report(request, t, passport, report_id, {"for_approval": True})


class PassportApprovalFileView(APIView):
    """Content of one engineering file of the passport's spare part, for the approver: `variant=preview` (PDF or photo,
    inline), `original` (download) or `glb` (the 3D model derivative of a STEP file)."""

    permission_classes = [HasCapability]
    capabilities = {"get": "passports.approve"}

    @extend_schema(tags=["passports"], responses={(200, "application/octet-stream"): bytes})
    def get(self, request, client_id, passport_id, file_id):
        _require_platform_approver(request)
        variant = request.query_params.get("variant", "preview")
        t = _client(client_id)
        with tenant_context(t):
            passport, revision = _submitted(passport_id)
            key, name, ctype = open_part_file(request, t, passport, file_id, variant,
                                              {"for_approval": True, "revision_number": revision.revision_number})
        return file_response(key, name, ctype, variant == "original")


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
                    "revision": RevisionSerializer(revision, context={"request": request, "approver": True}).data,
                    "evidence_files": _evidence_files(revision), "files": _part_files(request, passport),
                    "reports": _reports(passport)}
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
