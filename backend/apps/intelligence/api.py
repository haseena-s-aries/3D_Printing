"""Part intelligence API (CN-007 Phase 2). Aries-internal: clients hold none of these capabilities.

- GET  /parts/<id>/intelligence/                 rule-based analysis, AI availability and the part's AI suggestions
- POST /parts/<id>/intelligence/assess/          request an AI suggestion {tier: lite|flash|pro}
- POST /parts/<id>/intelligence/classification/  record the engineer-verified category {category, note, assessment?}
- GET  /intelligence/overview/                   imported parts of this company with analysis and latest suggestion
- POST /intelligence/assess-batch/               AI suggestions for up to 10 imported parts {tier, parts: [ids]}
- GET  /admin/intelligence-usage/                Aries Admin: AI calls, tokens and estimated cost per company and model
"""
from django.conf import settings
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exceptions import DomainError, error_response
from apps.parts.models import SparePart, lifecycle_parts
from apps.projects.scoping import restrict
from apps.tenancy.permissions import HasCapability

from . import cost_service, feasibility_service, recommendation_service, runs, service

BATCH_MAX = 10


def _part(request, pk) -> SparePart:
    part = restrict(request, SparePart.objects.filter(tenant=request.tenant), "project").filter(pk=pk).first()
    if part is None:
        raise DomainError("not_found", "Part not found.", http_status=404)
    if request.method not in ("GET", "HEAD", "OPTIONS") and not part.in_lifecycle:
        raise DomainError("part_not_in_lifecycle", "This part is a client submission that Aries has not accepted (or it is declined or "
                          "obsolete). Accept it into the engineering workflow before assessing it.", http_status=409)
    return part


def _refused(e: service.Refused) -> Response:
    return error_response(e.error_code, str(e.detail), e.status_code)


class PartIntelligenceView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"get": "intelligence.view"}

    @extend_schema(responses=dict)
    def get(self, request, pk):
        return Response(service.part_view(request, _part(request, pk)))


class PartAssessView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"post": "intelligence.assess"}

    @extend_schema(request=inline_serializer("PartAssessRequest", {"tier": serializers.ChoiceField(choices=service.TIERS, required=False)}),
                   responses=dict)
    def post(self, request, pk):
        part = _part(request, pk)
        try:
            a, reused = service.assess(request, part, request.data.get("tier") or "lite")
        except service.Refused as e:
            return _refused(e)
        return Response({"assessment": service.serialise(a), "reused": reused}, status=200 if reused else 201)


class PartClassificationView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"post": "intelligence.classify"}

    @extend_schema(request=inline_serializer("PartClassificationRequest", {
        "category": serializers.CharField(help_text="Spare-part category value (mechanical, electrical, electronic, other, unknown)"), "note": serializers.CharField(required=False, allow_blank=True),
        "assessment": serializers.UUIDField(required=False, allow_null=True)}), responses=dict)
    def post(self, request, pk):
        part = service.record_classification(request, _part(request, pk), request.data.get("category", ""),
                                             str(request.data.get("note") or ""), request.data.get("assessment") or None)
        return Response(service.part_view(request, part))


class IntelligenceOverviewView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"get": "intelligence.view"}

    @extend_schema(responses=dict)
    def get(self, request):
        return Response(service.overview(request))


class IntelligenceBatchView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"post": "intelligence.assess"}

    @extend_schema(request=inline_serializer("IntelligenceBatchRequest", {
        "tier": serializers.ChoiceField(choices=service.TIERS, required=False),
        "parts": serializers.ListField(child=serializers.UUIDField(), max_length=BATCH_MAX)}), responses=dict)
    def post(self, request):
        ids = request.data.get("parts") or []
        if not isinstance(ids, list) or not ids or len(ids) > BATCH_MAX:
            raise DomainError("invalid_parts", f"Choose 1 to {BATCH_MAX} parts.", http_status=400)
        tier = request.data.get("tier") or "lite"
        results = []
        for pk in ids:
            try:
                part = _part(request, pk)
            except DomainError as e:
                results.append({"part": str(pk), "part_number": "", "error": {"code": e.error_code, "message": str(e.detail)}})
                continue
            try:
                a, reused = service.assess(request, part, tier)
                results.append({"part": str(part.pk), "part_number": part.part_number, "reused": reused, "assessment": service.serialise(a)})
            except service.Refused as e:  # stop at the first limit; what ran so far is kept
                results.append({"part": str(part.pk), "part_number": part.part_number, "error": {"code": e.error_code, "message": str(e.detail)}})
                break
            except DomainError as e:
                results.append({"part": str(part.pk), "part_number": part.part_number, "error": {"code": e.error_code, "message": str(e.detail)}})
        return Response({"results": results})


class AdminIntelligenceUsageView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"get": "intelligence.usage_admin"}

    @extend_schema(responses=dict)
    def get(self, request):
        return Response({"ai": {k: v for k, v in service.ai_status(None).items() if k != "reason"},
                         "allowed_companies": len(settings.AI_ALLOWED_COMPANIES),
                         "usage": service.usage_summary(tenant=None)})


# ------------------------------------------------------------------ CN-007 Phase 3: manufacturing feasibility
# - GET  /parts/<id>/feasibility/                       assessment versions, reviews and AI availability
# - POST /parts/<id>/feasibility/assess/                run the screening {tier: null (rules only) | lite | flash | pro}
# - POST /parts/<id>/feasibility/<aid>/reviews/         technical review entry (not formal approval)
# - GET  /intelligence/feasibility/                     imported parts of this company with their latest assessment
# - POST /intelligence/feasibility/assess-batch/        screening for up to 10 imported parts {tier, parts: [ids]}

TIER_FIELD = serializers.ChoiceField(choices=service.TIERS, required=False, allow_null=True,
                                     help_text="Omit or null for rules only; lite (default AI), flash or pro on request.")


class PartFeasibilityView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"get": "intelligence.view"}

    @extend_schema(responses=dict)
    def get(self, request, pk):
        return Response(feasibility_service.part_view(request, _part(request, pk)))


class PartFeasibilityAssessView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"post": "intelligence.assess"}

    @extend_schema(request=inline_serializer("FeasibilityAssessRequest", {"tier": TIER_FIELD}), responses=dict)
    def post(self, request, pk):
        part = _part(request, pk)
        try:
            a, reused = feasibility_service.run(request, part, request.data.get("tier") or None)
        except service.Refused as e:
            return _refused(e)
        return Response({"assessment": feasibility_service.serialise(a), "reused": reused}, status=200 if reused else 201)


class FeasibilityReviewView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"post": "intelligence.review"}

    @extend_schema(request=inline_serializer("FeasibilityReviewRequest", {
        "alternative": serializers.CharField(help_text="oem, additive, conventional or overall"),
        "decision": serializers.CharField(help_text="confirmed, corrected, rejected, more_information_required or finding"),
        "corrected_status": serializers.CharField(required=False, allow_blank=True),
        "findings": serializers.CharField(required=False, allow_blank=True),
        "note": serializers.CharField(required=False, allow_blank=True),
        "evidence_references": serializers.ListField(child=serializers.DictField(), required=False)}), responses=dict)
    def post(self, request, pk, aid):
        part = _part(request, pk)
        r = feasibility_service.review(request, part, aid, request.data)
        return Response({"review": feasibility_service.serialise_review(r), **feasibility_service.part_view(request, part)}, status=201)


def _imported_parts(request):
    return list(restrict(request, lifecycle_parts(SparePart.objects.filter(tenant=request.tenant)), "project")
                .order_by("part_number"))


class FeasibilityOverviewView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"get": "intelligence.view"}

    @extend_schema(responses=dict)
    def get(self, request):
        return Response({"ai": service.ai_status(request.tenant), **feasibility_service.overview(request, _imported_parts(request))})


class FeasibilityBatchView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"post": "intelligence.assess"}

    @extend_schema(request=inline_serializer("FeasibilityBatchRequest", {
        "tier": TIER_FIELD, "parts": serializers.ListField(child=serializers.UUIDField(), max_length=BATCH_MAX)}), responses=dict)
    def post(self, request):
        ids = request.data.get("parts") or []
        if not isinstance(ids, list) or not ids or len(ids) > BATCH_MAX:
            raise DomainError("invalid_parts", f"Choose 1 to {BATCH_MAX} parts.", http_status=400)
        tier = request.data.get("tier") or None
        results = []
        for pk in ids:
            try:
                part = _part(request, pk)
                a, reused = feasibility_service.run(request, part, tier)
                results.append({"part": str(part.pk), "part_number": part.part_number, "reused": reused, "assessment_id": str(a.pk),
                                "version": a.version, "ai_status": a.ai_status, "oem": a.oem_status, "additive": a.additive_status,
                                "conventional": a.conventional_status})
            except service.Refused as e:  # stop at the first limit; what ran so far is kept
                results.append({"part": str(pk), "error": {"code": e.error_code, "message": str(e.detail)}})
                break
            except DomainError as e:
                results.append({"part": str(pk), "error": {"code": e.error_code, "message": str(e.detail)}})
        return Response({"results": results})


# ------------------------------------------------------------------ CN-007 Phase 4: cost and lead-time comparison
# - GET  /parts/<id>/cost-comparisons/             versions, technical status (Phase 3), blank template, AI availability
# - POST /parts/<id>/cost-comparisons/calculate/   calculate a scenario without storing it (what-if quantities)
# - POST /parts/<id>/cost-comparisons/             store a new version {scenario, tier?, derived_from?}
# - GET  /intelligence/cost-comparisons/           imported parts of this company with their latest comparison


class PartCostComparisonsView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"get": "intelligence.view", "post": "intelligence.assess"}

    @extend_schema(responses=dict)
    def get(self, request, pk):
        return Response(cost_service.part_view(request, _part(request, pk)))

    @extend_schema(request=inline_serializer("CostComparisonRequest", {
        "scenario": serializers.DictField(help_text="Quantity, reporting currency, exchange rates and the three alternatives' inputs"),
        "tier": TIER_FIELD, "derived_from": serializers.UUIDField(required=False, allow_null=True)}), responses=dict)
    def post(self, request, pk):
        part = _part(request, pk)
        try:
            c, reused = cost_service.create(request, part, request.data.get("scenario") or {}, request.data.get("tier") or None,
                                            request.data.get("derived_from") or None)
        except service.Refused as e:
            return _refused(e)
        return Response({"comparison": cost_service.serialise(c, cost_service.latest_feasibility(part)), "reused": reused},
                        status=200 if reused else 201)


class PartCostPreviewView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"post": "intelligence.view"}

    @extend_schema(request=inline_serializer("CostPreviewRequest", {"scenario": serializers.DictField()}), responses=dict)
    def post(self, request, pk):
        return Response(cost_service.preview(request, _part(request, pk), request.data.get("scenario") or {}))


class CostComparisonOverviewView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"get": "intelligence.view"}

    @extend_schema(responses=dict)
    def get(self, request):
        return Response(cost_service.overview(request, _imported_parts(request)))


# ------------------------------------------------------------------ CN-007 Phase 5: recommendation and engineering review
# - GET  /parts/<id>/recommendations/                   versions, review state, sources, default weights
# - POST /parts/<id>/recommendations/                   new version {weights?, tier?, cost_comparison?}
# - POST /parts/<id>/recommendations/<rid>/reviews/     review decision (not formal approval)
# - GET  /intelligence/recommendations/?state=          engineering review queue (latest version per imported part)


class PartRecommendationsView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"get": "intelligence.view", "post": "intelligence.assess"}

    @extend_schema(responses=dict)
    def get(self, request, pk):
        return Response(recommendation_service.part_view(request, _part(request, pk)))

    @extend_schema(request=inline_serializer("RecommendationRequest", {
        "weights": serializers.DictField(required=False, help_text="cost, lead_time, evidence (applied only after mandatory requirements)"),
        "tier": TIER_FIELD, "cost_comparison": serializers.UUIDField(required=False, allow_null=True)}), responses=dict)
    def post(self, request, pk):
        part = _part(request, pk)
        try:
            rec, reused = recommendation_service.create(request, part, request.data.get("weights") or None,
                                                        request.data.get("tier") or None, request.data.get("cost_comparison") or None)
        except service.Refused as e:
            return _refused(e)
        return Response({"recommendation": recommendation_service.serialise(rec), "reused": reused}, status=200 if reused else 201)


class RecommendationReviewView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"post": "intelligence.review"}

    @extend_schema(request=inline_serializer("RecommendationReviewRequest", {
        "decision": serializers.CharField(help_text="approved_for_further_study, information_requested, corrected or rejected"),
        "option": serializers.CharField(required=False, allow_blank=True), "findings": serializers.CharField(),
        "evidence_references": serializers.ListField(child=serializers.DictField(), required=False)}), responses=dict)
    def post(self, request, pk, rid):
        part = _part(request, pk)
        r = recommendation_service.review(request, part, rid, request.data)
        return Response({"review": recommendation_service.serialise_review(r), **recommendation_service.part_view(request, part)}, status=201)


class RecommendationQueueView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"get": "intelligence.view"}

    @extend_schema(responses=dict)
    def get(self, request):
        return Response(recommendation_service.queue(request, _imported_parts(request), request.query_params.get("state") or None))


# ------------------------------------------------------------------ CN-007 Phase 6: quarterly assessment runs and analytics
# - GET  /intelligence/assessments/                       dashboard: latest completed run, active run, history, schedule
# - POST /intelligence/assessments/                       start a manual run {ai_tier?, idempotency_key?, fault_injection?}
# - GET  /intelligence/assessments/<id>/                  run detail: items, summary, comparison with the previous run
# - POST /intelligence/assessments/<id>/retry/            resume failed parts / a stalled run
# - POST /intelligence/assessments/<id>/cancel/
# - GET  /intelligence/assessments/<id>/report.xlsx|.pdf  reports (project scope applied)
# - GET/PUT /intelligence/assessment-schedule/            quarterly schedule (company-wide access)
# - GET  /admin/assessment-summary/                       Aries Admin: aggregate counts per company, no engineering records


def _run_for(request, pk):
    run = runs.AssessmentRun.objects.filter(tenant=request.tenant, pk=pk).first()
    if run is None:
        raise DomainError("not_found", "Assessment run not found.", http_status=404)
    return run


class AssessmentRunsView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"get": "intelligence.view", "post": "intelligence.assess"}

    @extend_schema(operation_id="v1_intelligence_assessments_dashboard", responses=dict)
    def get(self, request):
        return Response(runs.dashboard(request))

    @extend_schema(request=inline_serializer("AssessmentRunRequest", {
        "ai_tier": serializers.CharField(required=False, allow_blank=True),
        "idempotency_key": serializers.CharField(required=False, allow_blank=True),
        "fault_injection": serializers.DictField(required=False, help_text="Test environments only")}), responses=dict)
    def post(self, request):
        run, existing = runs.start(request, "manual", request.data.get("ai_tier") or "", request.data.get("idempotency_key") or "",
                                   request.data.get("fault_injection") or None)
        return Response({"run": runs.serialise_run(run), "existing": existing}, status=200 if existing else 201)


class AssessmentRunDetailView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"get": "intelligence.view"}

    @extend_schema(responses=dict)
    def get(self, request, pk):
        return Response(runs.run_detail(request, _run_for(request, pk)))


class AssessmentRunActionView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"post": "intelligence.assess"}
    action_name = ""

    @extend_schema(request=None, responses=dict)
    def post(self, request, pk):
        run = _run_for(request, pk)
        run = runs.retry(request, run) if self.action_name == "retry" else runs.cancel(request, run)
        return Response({"run": runs.serialise_run(run)})


class AssessmentReportView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"get": "intelligence.view"}
    fmt = "xlsx"

    @extend_schema(responses={(200, "application/octet-stream"): bytes})
    def get(self, request, pk):
        from django.http import HttpResponse

        from apps.audit.service import record

        from . import assessment_reports
        run = _run_for(request, pk)
        if run.status in runs.AssessmentRun.ACTIVE:
            raise DomainError("run_not_finished", "The run has not finished yet.", http_status=409)
        detail = runs.run_detail(request, run)
        if self.fmt == "xlsx":
            body = assessment_reports.xlsx(detail, request.tenant.name)
            ctype = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        else:
            body, ctype = assessment_reports.pdf(detail, request.tenant.name), "application/pdf"
        record(request, "assessment_run.report_downloaded", obj=run, data={"number": run.number, "format": self.fmt,
                                                                           "parts": len(detail["items"])})
        resp = HttpResponse(body, content_type=ctype)
        resp["Content-Disposition"] = f"attachment; filename=assessment-run-{run.number}-{run.quarter}.{self.fmt}"
        return resp


class AssessmentScheduleView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"get": "intelligence.view", "put": "intelligence.assess"}

    @extend_schema(responses=dict)
    def get(self, request):
        return Response(runs.schedule_view(request))

    @extend_schema(request=inline_serializer("AssessmentScheduleRequest", {
        "enabled": serializers.BooleanField(), "months": serializers.ListField(child=serializers.IntegerField()),
        "day_of_month": serializers.IntegerField(), "ai_tier": serializers.CharField(required=False, allow_blank=True)}), responses=dict)
    def put(self, request):
        return Response(runs.save_schedule(request, request.data))


class AdminAssessmentSummaryView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"get": "intelligence.usage_admin"}

    @extend_schema(responses=dict)
    def get(self, request):
        return Response(runs.admin_summary())
