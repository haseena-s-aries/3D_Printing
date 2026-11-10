"""Job-sheet endpoints on the Aries intake API: /operator/requests/{envelope}/jobsheet/...

Access: operator-organisation session, capability jobsheets.view (read) or jobsheets.prepare (write), active assignment
to the client and, for project-limited staff, the part's project (inherited from OperatorRequestViewSet._envelope/_load).
Clients have no route here, and the database hides job-sheet rows from every non-job-sheet query (restrictive RLS).
"""
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.audit.service import record
from apps.core.exceptions import DomainError
from apps.parts.submissions import display_name
from apps.tenancy.context import tenant_context

from . import services


def aries_audit(request, action: str, data: dict) -> None:
    """Confidential job-sheet detail goes to the Aries (operator) audit trail only, whatever workspace the engineer is
    signed into; the client's audit trail never receives job references or specification content."""
    from apps.servicerequests.services import operator_tenant

    op = operator_tenant()
    with tenant_context(op):
        record(request, action, obj_type="jobsheet", obj_id=str(data.pop("job_sheet")), tenant=op, data=data)
from .models import JobSheet, JobSheetRevision


class RevisionSummarySerializer(serializers.ModelSerializer):
    author = serializers.SerializerMethodField()

    class Meta:
        model = JobSheetRevision
        fields = ["revision_number", "job_reference", "manufacturing_method", "change_summary", "author", "created_at"]

    def get_author(self, obj) -> str:
        return display_name(obj.created_by)


class DeviationSerializer(serializers.Serializer):
    field = serializers.CharField()
    passport = serializers.JSONField(allow_null=True)
    job = serializers.JSONField(allow_null=True)
    reason = serializers.CharField(allow_blank=True)


class JobSheetSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    draft_reference = serializers.CharField()
    job_reference = serializers.CharField(allow_blank=True)
    status = serializers.CharField()
    enquiry_reference = serializers.CharField()
    part_id = serializers.UUIDField()
    part_number = serializers.CharField()
    source_part_number = serializers.CharField(allow_blank=True)
    passport_number = serializers.CharField(allow_blank=True)
    passport_revision_number = serializers.IntegerField(allow_null=True)
    passport_revision_status = serializers.CharField(allow_blank=True)
    original_material = serializers.CharField(allow_blank=True)
    proposed_material = serializers.CharField(allow_blank=True)
    manufacturing_method = serializers.CharField(allow_blank=True)
    revision_number = serializers.IntegerField()
    content = serializers.JSONField()
    sources = serializers.DictField(child=serializers.CharField())
    template = serializers.JSONField()
    deviations = DeviationSerializer(many=True)
    revalidation_required = serializers.ListField(child=serializers.CharField())
    revisions = RevisionSummarySerializer(many=True)
    created_by = serializers.CharField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    cancelled_reason = serializers.CharField(allow_blank=True)
    gates = serializers.DictField(child=serializers.CharField(),
                                  help_text="Disabled actions and the decision that blocks them (J4, OQ-36)")


GATES = {"submit_for_qa": "OQ-36", "issue": "OQ-36", "release_to_production": "OQ-36"}


def represent(js: JobSheet, number: int | None = None) -> dict:
    revisions = list(js.revisions.select_related("created_by").order_by("-revision_number"))
    current = next((r for r in revisions if r.revision_number == (number or js.current_revision)), revisions[0])
    material_change = bool(js.proposed_material)
    return {
        "id": js.pk, "draft_reference": js.draft_reference, "job_reference": current.job_reference, "status": js.status,
        "enquiry_reference": js.enquiry.reference, "part_id": js.part_id, "part_number": js.part.part_number,
        "source_part_number": js.source_part.part_number if js.source_part_id else "", "passport_number": js.passport_number,
        "passport_revision_number": js.passport_revision_number, "passport_revision_status": js.passport_revision_status,
        "original_material": js.original_material, "proposed_material": js.proposed_material,
        "manufacturing_method": current.manufacturing_method, "revision_number": current.revision_number,
        "content": current.content, "sources": current.sources, "template": js.template,
        "deviations": services.deviations(js, current.content),
        "revalidation_required": [k for k in services.MATERIAL_DEPENDENT if material_change and current.sources.get(k) == "revalidate"],
        "revisions": revisions, "created_by": display_name(js.created_by),
        "created_at": js.created_at, "updated_at": js.updated_at, "cancelled_reason": js.cancelled_reason, "gates": GATES,
    }


class JobSheetActionsMixin:
    """Mixed into OperatorRequestViewSet (which provides _envelope and _load)."""

    def _get(self, enquiry):
        js = JobSheet.objects.select_related("enquiry", "part", "source_part", "created_by").filter(enquiry=enquiry).first()
        if js is None:
            raise DomainError("not_found", "No job sheet for this enquiry yet.", http_status=404)
        return js

    @extend_schema(methods=["GET"], responses=JobSheetSerializer)
    @extend_schema(methods=["POST"], request=inline_serializer("JobSheetPrepare", {
        "job_reference": serializers.CharField(required=False, allow_blank=True),
        "manufacturing_method": serializers.CharField(required=False, allow_blank=True)}), responses={201: JobSheetSerializer})
    @extend_schema(methods=["PATCH"], request=inline_serializer("JobSheetSave", {
        "job_reference": serializers.CharField(required=False, allow_blank=True),
        "manufacturing_method": serializers.CharField(required=False, allow_blank=True),
        "content": services.JobSheetContentSerializer(required=False),
        "change_summary": serializers.CharField(required=False, allow_blank=True)}), responses=JobSheetSerializer)
    @action(detail=True, methods=["get", "post", "patch"])
    def jobsheet(self, request, pk=None):
        """Draft job sheet of a manufacturing enquiry: read, prepare (POST) or save a new revision (PATCH)."""
        env = self._envelope(request, pk)
        with tenant_context(env.client_tenant_id), services.staff_access():
            enquiry = self._load(env)
            if request.method == "POST":
                js = services.prepare(request, enquiry, job_reference=str(request.data.get("job_reference") or ""),
                                      manufacturing_method=str(request.data.get("manufacturing_method") or ""))
                event = "jobsheet.created"
            elif request.method == "PATCH":
                js = services.save_revision(request, self._get(enquiry), request.data)
                event = "jobsheet.revision_saved"
            else:
                js, event = self._get(enquiry), None
            data = JobSheetSerializer(represent(js)).data
        if event:  # full detail in the Aries audit trail
            aries_audit(request, event, {"client": env.client_name, "enquiry": data["enquiry_reference"], "job_sheet": data["id"],
                                         "revision": data["revision_number"], "job_reference": data["job_reference"],
                                         "draft_reference": data["draft_reference"]})
        return Response(data, status=201 if request.method == "POST" else 200)

    @extend_schema(responses=JobSheetSerializer)
    @action(detail=True, methods=["get"], url_path=r"jobsheet/revisions/(?P<number>\d+)")
    def jobsheet_revision(self, request, pk=None, number=None):
        env = self._envelope(request, pk)
        with tenant_context(env.client_tenant_id), services.staff_access():
            js = self._get(self._load(env))
            if not js.revisions.filter(revision_number=int(number)).exists():
                raise DomainError("not_found", "Revision not found.", http_status=404)
            return Response(JobSheetSerializer(represent(js, int(number))).data)

    @extend_schema(request=inline_serializer("JobSheetCancel", {"reason": serializers.CharField()}), responses=JobSheetSerializer)
    @action(detail=True, methods=["post"], url_path="jobsheet/cancel")
    def jobsheet_cancel(self, request, pk=None):
        env = self._envelope(request, pk)
        with tenant_context(env.client_tenant_id), services.staff_access():
            js = services.cancel(request, self._get(self._load(env)), str(request.data.get("reason") or ""))
            data = JobSheetSerializer(represent(js)).data
        aries_audit(request, "jobsheet.cancelled", {"client": env.client_name, "job_sheet": data["id"]})
        return Response(data)

    @extend_schema(request=None, responses={409: None}, operation_id="v1_operator_requests_jobsheet_gate")
    @action(detail=True, methods=["post"], url_path=r"jobsheet/(?P<gate>submit|issue|release)")
    def jobsheet_gate(self, request, pk=None, gate=None):
        """QA submission, issue and production release: disabled until OQ-36 is decided (J4)."""
        self._envelope(request, pk)
        services.gated({"submit": "jobsheet_submit_for_qa", "issue": "jobsheet_issue", "release": "production_release"}[gate])
