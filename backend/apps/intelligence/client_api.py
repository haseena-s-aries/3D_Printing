"""CN-007 role-based AI access API (AI_CLIENT_ACCESS_ENABLED). Rules: apps.intelligence.disclosure.

Aries Engineer (assigned, in scope; ai.share):
- GET  /parts/<id>/disclosures/                         disclosure state, sharing history, client-safe preview
- POST /parts/<id>/disclosures/                         approve the latest reviewed version for client sharing
- POST /parts/<id>/disclosures/<sid>/share/             share an approved result with the client
- POST /parts/<id>/disclosures/<sid>/withdraw/          withdraw an approved or shared result {reason}
- GET  /intelligence/disclosures/                       disclosure state of every imported part in scope
Client (ai.workspace, company switched on, member access):
- GET  /client-intelligence/                            access and the company's parts with client status
- GET  /client-intelligence/dashboard/                  the company's own dashboard (shared results and requests only)
- GET  /client-intelligence/parts/<id>/                 shared result, history and assessment requests of a part
- POST /client-intelligence/parts/<id>/request/         request an assessment / reassessment (ai.request)
- GET  /client-intelligence/parts/<id>/report.pdf       client-facing report of the shared result (ai.reports)
- GET/PUT /client-intelligence/members/                 Client Admin: members' access (ai.members)
Aries Admin (ai.management, operator tenant):
- GET  /admin/ai-management/                            aggregates per client company, AI usage and cost
- PUT  /admin/ai-management/clients/<id>/               switch a client company's workspace {enabled, note}
"""
from django.http import HttpResponse
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exceptions import DomainError
from apps.tenancy.models import Tenant
from apps.tenancy.permissions import HasCapability

from . import disclosure as D
from .api import _imported_parts, _part


class PartDisclosuresView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"get": "ai.share", "post": "ai.share"}

    @extend_schema(responses=dict)
    def get(self, request, pk):
        return Response(D.part_view(request, _part(request, pk)))

    @extend_schema(request=inline_serializer("DisclosureApproveRequest", {
        "recommendation": serializers.UUIDField(), "summary": serializers.CharField(),
        "released_prices": serializers.ListField(child=serializers.DictField(), required=False)}), responses=dict)
    def post(self, request, pk):
        part = _part(request, pk)
        s = D.approve(request, part, request.data)
        return Response({"shared_assessment": D.serialise_share(s), **D.part_view(request, part)}, status=201)


class DisclosureActionView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"post": "ai.share"}
    action_name = ""

    @extend_schema(request=inline_serializer("DisclosureActionRequest", {"reason": serializers.CharField(required=False)}), responses=dict)
    def post(self, request, pk, sid):
        part = _part(request, pk)
        if self.action_name == "share":
            D.share(request, part, sid)
        else:
            D.withdraw(request, part, sid, str(request.data.get("reason") or ""))
        return Response(D.part_view(request, part))


class DisclosureQueueView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"get": "ai.share"}

    @extend_schema(responses=dict)
    def get(self, request):
        return Response(D.queue(request, _imported_parts(request)))


class ClientIntelligenceView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"get": "ai.workspace"}

    @extend_schema(responses=dict)
    def get(self, request):
        return Response(D.client_overview(request))


class ClientDashboardView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"get": "ai.workspace"}

    @extend_schema(responses=dict)
    def get(self, request):
        return Response(D.client_dashboard(request))


class ClientPartView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"get": "ai.workspace"}

    @extend_schema(responses=dict)
    def get(self, request, pk):
        return Response(D.client_part(request, pk))


class ClientRequestAssessmentView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"post": "ai.request"}

    @extend_schema(request=inline_serializer("AssessmentRequestRequest", {
        "reason": serializers.ChoiceField(choices=list(D.REQUEST_REASONS)), "remarks": serializers.CharField(required=False, allow_blank=True)}),
        responses=dict)
    def post(self, request, pk):
        r = D.request_assessment(request, pk, request.data)
        return Response({"id": str(r.pk), "reference": r.reference, "status": r.status, "status_label": r.get_status_display()}, status=201)


class ClientReportView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"get": "ai.reports"}

    @extend_schema(responses={(200, "application/pdf"): bytes})
    def get(self, request, pk):
        body, name = D.client_report(request, pk)
        resp = HttpResponse(body, content_type="application/pdf")
        resp["Content-Disposition"] = f"attachment; filename={name}"
        return resp


class ClientMembersView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"get": "ai.members", "put": "ai.members"}

    @extend_schema(responses=dict)
    def get(self, request):
        if not D.workspace_enabled(request.tenant):
            raise DomainError("ai_workspace_off", "Spare Parts Intelligence is not enabled for your company.", http_status=403)
        return Response({"members": D.members(request)})

    @extend_schema(request=inline_serializer("WorkspaceMemberRequest", {"user": serializers.UUIDField(), "allowed": serializers.BooleanField()}),
                   responses=dict)
    def put(self, request):
        if not D.workspace_enabled(request.tenant):
            raise DomainError("ai_workspace_off", "Spare Parts Intelligence is not enabled for your company.", http_status=403)
        return Response({"members": D.set_member(request, request.data.get("user"), bool(request.data.get("allowed")))})


class AdminAIManagementView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"get": "ai.management"}

    @extend_schema(responses=dict)
    def get(self, request):
        return Response(D.admin_dashboard(request))


class AdminClientWorkspaceView(APIView):
    permission_classes = [HasCapability]
    capabilities = {"put": "ai.management"}

    @extend_schema(request=inline_serializer("ClientWorkspaceRequest", {"enabled": serializers.BooleanField(),
                                                                        "note": serializers.CharField(required=False, allow_blank=True)}),
                   responses=dict)
    def put(self, request, pk):
        client = Tenant.objects.filter(pk=pk, kind=Tenant.Kind.CLIENT).first()
        if client is None:
            raise DomainError("not_found", "Client company not found.", http_status=404)
        return Response(D.set_workspace(request, client, bool(request.data.get("enabled")), str(request.data.get("note") or "")))

