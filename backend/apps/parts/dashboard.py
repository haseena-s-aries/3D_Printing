"""Dashboard summary for the current organisation (W2). Facts only, from this tenant's own records: parts,
passports, documents, 3D conversion status and recent activity. No manufacturing or order statistics: production
and ordering do not exist yet (OQ-36)."""
from django.db.models import Count, Q
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.files.models import Derivative, EngineeringFile
from apps.jobs.models import Job
from apps.passports.models import DigitalPassport, PassportRevision
from apps.projects.scoping import restrict
from apps.tenancy.permissions import HasCapability

from .api import SparePartSerializer, client_role, with_summaries
from .models import SparePart


def counts(qs, field, keys):
    found = dict(qs.values_list(field).annotate(n=Count("pk")).values_list(field, "n"))
    return {k: found.get(k, 0) for k in keys}


class DashboardSummaryView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"get": "parts.view"}

    @extend_schema(tags=["dashboard"], responses={200: inline_serializer("DashboardSummary", {
        "parts": serializers.DictField(), "passports": serializers.DictField(), "documents": serializers.DictField(),
        "conversions": serializers.DictField(), "recent_parts": SparePartSerializer(many=True)})})
    def get(self, request):
        tenant = request.tenant
        parts = restrict(request, SparePart.objects.filter(tenant=tenant), "project", own="submitted_by")
        passports = restrict(request, DigitalPassport.objects.filter(tenant=tenant), "part__project", own="part__submitted_by")
        files = restrict(request, EngineeringFile.objects.filter(tenant=tenant), "part__project", own="part__submitted_by")
        client = client_role(request)
        vis = {"files__client_visible": True} if client else {}  # D-16: clients count only documents released to them
        if client:
            files = files.filter(client_visible=True)

        def parts_with(**f):
            return parts.filter(**f, **vis).distinct().count()

        # Latest conversion job per STEP version
        latest = {}
        for fv, status in Job.objects.filter(tenant=tenant, kind="cad.step_to_glb").order_by("created_at").values_list("payload__file_version", "status"):
            latest[fv] = status
        step_versions = {str(v) for v in files.filter(kind="step").values_list("versions__pk", flat=True) if v}
        conv = {s: 0 for s in ("queued", "running", "succeeded", "failed", "not_requested")}
        for fv in step_versions:
            conv[latest.get(fv, "not_requested")] = conv.get(latest.get(fv, "not_requested"), 0) + 1
        failed_ids = [fv for fv in step_versions if latest.get(fv) == "failed"]
        failed = [{"file": str(f.pk), "title": f.title, "part": str(f.part_id), "part_number": f.part.part_number,
                   "passport": str(f.passport_id) if f.passport_id else None}
                  for f in files.filter(versions__pk__in=failed_ids).select_related("part").distinct()[:5]]

        data = {
            "parts": {
                "total": parts.count(),
                "with_passport": parts.filter(passport__isnull=False).count(),
                "by_category": counts(parts, "category", ["mechanical", "electrical", "electronic", "other"]),
            },
            "passports": {
                "total": passports.count(),
                "open_drafts": PassportRevision.objects.filter(tenant=tenant, status=PassportRevision.Status.DRAFT).count(),
                "by_publication": counts(passports, "publication_state", [c for c, _ in DigitalPassport.PublicationState.choices]),
                "by_evidence_level": counts(passports, "evidence_level", [c for c, _ in DigitalPassport.EvidenceLevel.choices]),
                "by_data_captured": counts(passports, "data_captured", [c for c, _ in DigitalPassport.DataCaptured.choices]),
            },
            "documents": {
                "total": files.count(),
                "by_kind": counts(files, "kind", [c for c, _ in EngineeringFile.Kind.choices]),
                "by_category": counts(files, "category", [c for c, _ in EngineeringFile.Category.choices]),
                "parts_with_3d": parts.filter(files__versions__derivatives__kind=Derivative.Kind.GLB, **vis).distinct().count(),
                "parts_with_drawing": parts_with(files__category="drawing"),
                "parts_with_specification": parts_with(files__category="specification"),
                "parts_with_photo": parts_with(files__kind="image"),
                "parts_without_documents": parts.exclude(pk__in=files.values("part_id")).count(),
            },
            "conversions": {**conv, "failed_items": failed},
            "recent_parts": SparePartSerializer(with_summaries(parts.select_related("passport", "project"), client=client).order_by("-last_activity")[:8],
                                                many=True, context={"request": request, "tenant": tenant}).data,
        }
        return Response(data)
