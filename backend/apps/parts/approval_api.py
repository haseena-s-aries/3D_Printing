"""Aries organisation: client submissions waiting for approval across client companies (decision of 13 Nov 2026).

New parts from clients (route 1) and clones with a changed material (route 3) are approved by an Aries Admin or Aries
Manager here, or by an Aries Engineer covering the part on the part page. Each company is read inside its own tenant
context (row-level security applies). Decisions run apps.parts.submissions inside that company: approve (part accepted,
passport draft created, a clone's manufacturing request sent automatically), send back (next submission revision) or
decline. The submitted documents can be opened while the submission waits; every opening is audited in the company.
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

from . import submissions
from .models import SparePart

DETAIL_FIELDS = ["part_number", "name", "description", "category", "original_material", "dimensions", "application",
                 "equipment_reference", "manufacturer", "proposed_material", "material_change_reason", "client_remarks"]


def _require_platform_approver(request) -> None:
    m = getattr(request, "membership", None)
    if m is None or not policy.is_platform_admin(m) or not has_capability(request, "passports.approve"):
        raise DomainError("permission_denied", "Only an Aries Admin or Aries Manager can open the approval queue.", http_status=403)


def _client(client_id) -> Tenant:
    t = Tenant.objects.filter(pk=client_id, kind=Tenant.Kind.CLIENT).first()
    if t is None:
        raise DomainError("not_found", "Client company not found.", http_status=404)
    return t


def _open_part(part_id) -> SparePart:
    part = SparePart.objects.select_related("submitted_by", "project").filter(
        pk=part_id, origin=SparePart.Origin.CLIENT, review_state__in=SparePart.OPEN_REVIEW).first()
    if part is None:
        raise DomainError("not_found", "This submission is not waiting for approval.", http_status=404)
    return part


def _row(t: Tenant, p: SparePart) -> dict:
    return {"client_id": str(t.pk), "client_name": t.name, "part_id": str(p.pk), "part_number": p.part_number, "name": p.name,
            "submission_kind": p.submission_kind, "kind_label": p.get_submission_kind_display() if p.submission_kind else "",
            "review_state": p.review_state, "review_state_label": p.get_review_state_display(),
            "revision": p.submission_revision, "aries_completion_requested": p.aries_completion_requested,
            "unknown_fields": p.unknown_fields or [], "submitted_by_email": p.submitted_by.email if p.submitted_by_id else "",
            "submitted_at": p.submitted_at, "source_part_number": p.source_part_number}


ROWS = inline_serializer("SubmissionApprovalRow", {
    "client_id": serializers.UUIDField(), "client_name": serializers.CharField(), "part_id": serializers.UUIDField(),
    "part_number": serializers.CharField(), "name": serializers.CharField(), "submission_kind": serializers.CharField(),
    "kind_label": serializers.CharField(), "review_state": serializers.CharField(), "review_state_label": serializers.CharField(),
    "revision": serializers.IntegerField(), "aries_completion_requested": serializers.BooleanField(),
    "unknown_fields": serializers.ListField(child=serializers.CharField()), "submitted_by_email": serializers.CharField(),
    "submitted_at": serializers.DateTimeField(), "source_part_number": serializers.CharField()}, many=True)


class SubmissionApprovalQueueView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"get": "passports.approve"}

    @extend_schema(tags=["parts"], responses={200: ROWS})
    def get(self, request):
        _require_platform_approver(request)
        rows = []
        for t in Tenant.objects.filter(kind=Tenant.Kind.CLIENT, status=Tenant.Status.ACTIVE).order_by("name"):
            with tenant_context(t):
                for p in (SparePart.objects.filter(origin=SparePart.Origin.CLIENT, review_state__in=SparePart.OPEN_REVIEW)
                          .select_related("submitted_by").order_by("submitted_at")):
                    rows.append(_row(t, p))
        rows.sort(key=lambda r: (r["review_state"] != SparePart.Review.PENDING, str(r["submitted_at"] or "")))
        return Response(rows)


class SubmissionApprovalDetailView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"get": "passports.approve", "post": "passports.approve"}

    @extend_schema(tags=["parts"], responses={200: dict})
    def get(self, request, client_id, part_id):
        from apps.files.api import EngineeringFileSerializer
        from apps.files.models import EngineeringFile

        _require_platform_approver(request)
        t = _client(client_id)
        with tenant_context(t):
            p = _open_part(part_id)
            files = EngineeringFileSerializer(EngineeringFile.objects.filter(part=p).order_by("category", "title"), many=True,
                                              context={"request": request}).data
            history = [{"action": e.action, "action_label": e.get_action_display(), "side": e.side, "note": e.note,
                        "by": e.created_by.email if e.created_by_id else "", "at": e.created_at}
                       for e in p.review_events.select_related("created_by").order_by("created_at")]
            data = {**_row(t, p), "fields": {f: getattr(p, f) for f in DETAIL_FIELDS},
                    "category_label": p.get_category_display() if p.category else "",
                    "project": p.project.name if p.project_id else "", "review_note": p.review_note,
                    "clone_changes": submissions.clone_changes(p) if p.submission_kind == SparePart.SubmissionKind.CLONE else [],
                    "source_passport_number": p.source_passport_number, "files": files, "history": history}
            record(request, "spare_part.approval_viewed", obj=p, tenant=t, data={"revision": p.submission_revision})
        return Response(data)

    @extend_schema(tags=["parts"], request=inline_serializer("SubmissionDecision", {
        "decision": serializers.ChoiceField(choices=["approve", "send_back", "decline"]), "message": serializers.CharField(required=False)}),
        responses={200: dict})
    def post(self, request, client_id, part_id):
        _require_platform_approver(request)
        decision, message = str(request.data.get("decision", "")), str(request.data.get("message", "") or "")
        if decision not in ("approve", "send_back", "decline"):
            raise DomainError("invalid_decision", "Choose approve, send_back or decline.", http_status=400)
        t = _client(client_id)
        with tenant_context(t):
            p = _open_part(part_id)
            if decision == "approve":
                submissions.accept(request, p, note=message)
            elif decision == "send_back":
                submissions.request_info(request, p, message)
            else:
                submissions.decline(request, p, message)
            p.refresh_from_db()
            passport = getattr(p, "passport", None)
            data = {"review_state": p.review_state, "revision": p.submission_revision,
                    "passport_number": passport.passport_number if passport else ""}
        return Response(data)


class SubmissionApprovalFileView(APIView):
    """A document submitted with the part (preview inline, or the original as a download), while it waits for approval."""

    permission_classes = [HasCapability]
    capabilities = {"get": "passports.approve"}

    @extend_schema(tags=["parts"], responses={(200, "application/octet-stream"): bytes})
    def get(self, request, client_id, part_id, file_id):
        from apps.files.models import EngineeringFile
        from apps.files.storage import get_storage

        _require_platform_approver(request)
        variant = request.query_params.get("variant", "preview")
        if variant not in ("preview", "original"):
            raise DomainError("invalid_variant", "Choose preview or original.", http_status=400)
        t = _client(client_id)
        with tenant_context(t):
            p = _open_part(part_id)
            ef = EngineeringFile.objects.filter(pk=file_id, part=p).first()
            fv = ef.versions.order_by("-version_number").first() if ef else None
            if fv is None:
                raise DomainError("not_found", "File not found for this submission.", http_status=404)
            if variant == "preview" and ef.kind not in (EngineeringFile.Kind.PDF, EngineeringFile.Kind.IMAGE):
                raise DomainError("preview_not_available", "In-browser preview is available for PDF documents and photographs only.",
                                  http_status=400)
            record(request, "file.previewed" if variant == "preview" else "file.downloaded", obj=fv, tenant=t,
                   data={"variant": variant, "for_approval": True, "part": p.part_number})
            key, name, ctype = fv.storage_key, fv.original_filename, fv.content_type or None
        resp = FileResponse(get_storage().open(key), as_attachment=variant == "original", filename=name, content_type=ctype)
        resp["X-Content-Type-Options"] = "nosniff"
        resp["Cache-Control"] = "no-store"
        return resp
