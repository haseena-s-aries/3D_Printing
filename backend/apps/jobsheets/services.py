"""Draft manufacturing job sheets (CN-004, J1-J8 as approved 26 Oct 2026).

All functions run inside the client's tenant context and inside `staff_access()`, opened only after the caller has been
checked as authorised Aries staff (assigned to the client and, for project-limited staff, the part's project).
"""
from contextlib import contextmanager

from django.db import IntegrityError, connection, transaction
from django.utils import timezone
from rest_framework import serializers

from apps.audit.service import record
from apps.core.exceptions import DomainError
from apps.parts.submissions import same
from apps.passports.content import AcceptanceRowSerializer, ManufacturingSpecSerializer, ProcessParameterSerializer
from apps.passports.models import PassportRevision
from apps.policies import seams
from apps.servicerequests.models import ClientRequest, RequestEvent
from apps.tenancy import mssql
from apps.tenancy.context import JOBSHEET_SETTING, write_setting

from .models import JobSheet, JobSheetRevision

S = ClientRequest.Status
K = ClientRequest.Kind
# An enquiry must have been acknowledged by Aries, and still be open, before a job sheet is prepared.
PREPARABLE = {S.ACKNOWLEDGED, S.INFORMATION_REQUESTED, S.INFORMATION_PROVIDED, S.ANSWERED, S.SCHEDULED, S.IN_PROGRESS}

# BR-026 specification fields carried on the job sheet (the job number is the job sheet's own job reference)
SPEC_FIELDS = ["material", "feedstock", "machine", "layer_thickness", "support_strategy", "build_orientation", "inert_gas",
               "heat_treatment", "post_processing", "machining", "printing_hours", "post_processing_hours"]
QUALITY_FIELDS = ["applicable_standards", "dimensional_tolerances", "ndt", "inspection_test_plan", "mtc_required", "test_coupons",
                  "mechanical_acceptance"]
# J5: when the material changes these depend on the material and need engineering revalidation
MATERIAL_DEPENDENT = ["spec.material", "spec.feedstock", "spec.layer_thickness", "spec.heat_treatment", "spec.post_processing",
                      "spec.printing_hours", "spec.post_processing_hours", "process_parameters", "quality.mechanical_acceptance",
                      "quality.test_coupons"]


@contextmanager
def staff_access():
    """Open the restrictive job-sheet RLS policy for this transaction block (callers have checked authorisation)."""
    with transaction.atomic():
        write_setting(JOBSHEET_SETTING, "on")
        try:
            yield
        finally:
            write_setting(JOBSHEET_SETTING, None)


class QualitySerializer(serializers.Serializer):
    applicable_standards = serializers.CharField(required=False, allow_blank=True, max_length=500)
    dimensional_tolerances = serializers.CharField(required=False, allow_blank=True, max_length=500)
    ndt = serializers.CharField(required=False, allow_blank=True, max_length=500)
    inspection_test_plan = serializers.CharField(required=False, allow_blank=True, max_length=1000)
    mtc_required = serializers.BooleanField(required=False, allow_null=True)
    test_coupons = serializers.CharField(required=False, allow_blank=True, max_length=500)
    mechanical_acceptance = AcceptanceRowSerializer(many=True, required=False)


class JobSheetContentSerializer(serializers.Serializer):
    spec = ManufacturingSpecSerializer(required=False)
    process_parameters = ProcessParameterSerializer(many=True, required=False)
    quality = QualitySerializer(required=False)
    engineering_notes = serializers.CharField(required=False, allow_blank=True, max_length=4000)
    deviation_reasons = serializers.DictField(child=serializers.CharField(max_length=500, allow_blank=True), required=False)


def _filled(v) -> bool:
    return v not in (None, "", [], {})


def flatten(content: dict) -> dict:
    """{"spec.material": ..., "quality.ndt": ..., "process_parameters": [...]} for comparison and provenance."""
    flat = {}
    for f in SPEC_FIELDS:
        flat[f"spec.{f}"] = (content.get("spec") or {}).get(f)
    for f in QUALITY_FIELDS:
        flat[f"quality.{f}"] = (content.get("quality") or {}).get(f)
    flat["process_parameters"] = content.get("process_parameters") or []
    return flat


def _template_content(rl2: dict) -> dict:
    spec = {f: (rl2.get("manufacturing_spec") or {}).get(f) for f in SPEC_FIELDS}
    return {"spec": {k: v for k, v in spec.items() if _filled(v)},
            "process_parameters": (rl2.get("manufacturing_spec") or {}).get("process_parameters") or [],
            "quality": {f: rl2.get(f) for f in QUALITY_FIELDS if _filled(rl2.get(f))}}


def _next_draft_reference() -> str:
    with connection.cursor() as cur:
        cur.execute("SELECT NEXT VALUE FOR dbo.jobsheet_draft_seq" if mssql.is_mssql(connection) else "select nextval('jobsheet_draft_seq')")
        n = cur.fetchone()[0]
    return f"JS-DRAFT-{timezone.now().year}-{n:05d}"


def _check_job_reference(js: JobSheet | None, value: str) -> str:
    value = (value or "").strip()
    if value.upper().startswith("JS-DRAFT"):
        raise DomainError("invalid_job_reference", "JS-DRAFT references are provisional; enter the Aries job number.",
                          details={"job_reference": ["Enter the Aries job number."]}, http_status=400)
    return value


def _save_job_reference(js: JobSheet, value: str) -> None:
    js.job_reference = value
    try:
        with transaction.atomic():
            js.save(update_fields=["job_reference", "updated_at"])
    except IntegrityError:
        raise DomainError("duplicate_job_reference", "This Aries job number is already used on another job sheet.",
                          details={"job_reference": ["Already used."]}, http_status=400)


def prepare(request, enquiry: ClientRequest, *, job_reference: str = "", manufacturing_method: str = "") -> JobSheet:
    """Create the draft job sheet for an acknowledged manufacturing enquiry (one per enquiry)."""
    if enquiry.kind not in (K.ENQUIRY, K.MANUFACTURING):
        raise DomainError("not_manufacturing", "Job sheets are prepared for manufacturing enquiries only.", http_status=409)
    if enquiry.status not in PREPARABLE:
        raise DomainError("not_acknowledged", "Acknowledge the enquiry before preparing a job sheet (closed enquiries cannot "
                          "get one).", http_status=409)
    if JobSheet.objects.filter(enquiry=enquiry).exists():
        raise DomainError("job_sheet_exists", "This enquiry already has a job sheet.", http_status=409)
    if enquiry.part_id is None:
        raise DomainError("no_part", "The enquiry has no spare part.", http_status=409)
    material_change = enquiry.material_option == "proposed"
    part = enquiry.linked_part if material_change and enquiry.linked_part_id else enquiry.part
    revision = None
    if enquiry.passport_id and enquiry.passport_revision_number:
        revision = PassportRevision.objects.filter(passport_id=enquiry.passport_id,
                                                   revision_number=enquiry.passport_revision_number).first()
    template = _template_content((revision.content or {}).get("rl2") or {}) if revision else {}
    verified = revision is not None and revision.status == PassportRevision.Status.APPROVED
    content = {"spec": dict(template.get("spec") or {}), "process_parameters": list(template.get("process_parameters") or []),
               "quality": dict(template.get("quality") or {}), "engineering_notes": "", "deviation_reasons": {}}
    sources = {k: ("verified" if verified else "proposed") if _filled(v) else "missing" for k, v in flatten(content).items()}
    original_material = enquiry.original_material or (enquiry.part.original_material if enquiry.part_id else "")
    if material_change:
        content["spec"]["material"] = enquiry.proposed_material
        sources["spec.material"] = "client_proposal"
        for k in MATERIAL_DEPENDENT:
            if k != "spec.material":
                sources[k] = "revalidate"
    job_reference = _check_job_reference(None, job_reference)
    js = JobSheet(tenant=enquiry.tenant, created_by=request.user, enquiry=enquiry, part=part,
                  source_part=enquiry.part if part.pk != enquiry.part_id else None, passport_id=enquiry.passport_id,
                  passport_number=enquiry.passport.passport_number if enquiry.passport_id else "",
                  passport_revision_number=revision.revision_number if revision else None,
                  passport_revision_status=revision.status if revision else "", template=template,
                  draft_reference=_next_draft_reference(), manufacturing_method=(manufacturing_method or "").strip()[:120],
                  original_material=original_material, proposed_material=enquiry.proposed_material if material_change else "")
    js.save()
    if job_reference:
        _save_job_reference(js, job_reference)
    JobSheetRevision.objects.create(tenant=enquiry.tenant, created_by=request.user, job_sheet=js, revision_number=1,
                                    job_reference=js.job_reference, manufacturing_method=js.manufacturing_method,
                                    content=content, sources=sources, change_summary="Draft prepared from the enquiry")
    enquiry.job_progress = "preparing"
    enquiry.save(update_fields=["job_progress", "updated_at"])
    RequestEvent.objects.create(tenant=enquiry.tenant, created_by=request.user, request=enquiry, event="job_preparation",
                                to_status=enquiry.status, author=request.user, author_side=RequestEvent.Side.OPERATOR,
                                message="Aries has started preparing the manufacturing documentation for this enquiry. "
                                        "This is not a manufacturing order or release.")
    # client-tenant audit carries no confidential detail; the full record goes to the operator audit
    record(request, "jobsheet.created", obj=js, tenant=enquiry.tenant, data={"enquiry": enquiry.reference})
    return js


def save_revision(request, js: JobSheet, data: dict) -> JobSheet:
    if js.status != JobSheet.Status.DRAFT:
        raise DomainError("not_draft", "Only draft job sheets can be edited.", http_status=409)
    s = JobSheetContentSerializer(data=data.get("content") or {})
    s.is_valid(raise_exception=True)
    previous = js.revisions.order_by("-revision_number").first()
    content = dict(previous.content if previous else {})
    for key, value in s.validated_data.items():  # sections merge field by field; lists and text replace
        content[key] = {**(content.get(key) or {}), **value} if key in ("spec", "quality", "deviation_reasons") else value
    sources = dict(previous.sources if previous else {})
    before, after = flatten(previous.content if previous else {}), flatten(content)
    for k, v in after.items():
        if v != before.get(k):
            sources[k] = "entered" if _filled(v) else "missing"
    if "job_reference" in data:
        ref = _check_job_reference(js, data.get("job_reference") or "")
        if ref != js.job_reference:
            _save_job_reference(js, ref)
    if "manufacturing_method" in data:
        js.manufacturing_method = str(data.get("manufacturing_method") or "").strip()[:120]
    js.current_revision = (previous.revision_number if previous else 0) + 1
    js.save(update_fields=["manufacturing_method", "current_revision", "updated_at"])
    JobSheetRevision.objects.create(tenant=js.tenant, created_by=request.user, job_sheet=js, revision_number=js.current_revision,
                                    job_reference=js.job_reference, manufacturing_method=js.manufacturing_method,
                                    content=content, sources=sources, change_summary=str(data.get("change_summary") or "")[:500])
    record(request, "jobsheet.revision_saved", obj=js, tenant=js.tenant, data={"revision": js.current_revision})
    return js


def cancel(request, js: JobSheet, reason: str) -> JobSheet:
    if js.status != JobSheet.Status.DRAFT:
        raise DomainError("not_draft", "Only draft job sheets can be cancelled.", http_status=409)
    if not reason.strip():
        raise DomainError("reason_required", "Give a reason for cancelling.", http_status=400)
    js.status, js.cancelled_reason = JobSheet.Status.CANCELLED, reason.strip()
    js.save(update_fields=["status", "cancelled_reason", "updated_at"])
    js.enquiry.job_progress = "cancelled"
    js.enquiry.save(update_fields=["job_progress", "updated_at"])
    record(request, "jobsheet.cancelled", obj=js, tenant=js.tenant, data={})
    return js


def gated(action: str):
    """J4: QA submission, issue and production release stay disabled until OQ-36 is decided."""
    seams.require("manufacturing", action)


def deviations(js: JobSheet, content: dict) -> list[dict]:
    """Fields where the job differs from the passport template (J5)."""
    tmpl, now = flatten(js.template or {}), flatten(content)
    reasons = content.get("deviation_reasons") or {}
    out = []
    for k, v in now.items():
        t = tmpl.get(k)
        if (_filled(v) or _filled(t)) and not (same(v, t) if isinstance(v, str) or isinstance(t, str) else v == t):
            out.append({"field": k, "passport": t, "job": v, "reason": reasons.get(k, "")})
    return out
