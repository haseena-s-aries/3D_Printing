"""Edit-request API (CN-006): /edit-requests/. Tenant RLS and project scope (via the part) apply to every query;
roles and reviewer authority are enforced server-side in services."""
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field, inline_serializer
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.exceptions import DomainError
from apps.parts.models import SparePart
from apps.parts.submissions import display_name
from apps.passports.models import DigitalPassport
from apps.projects.scoping import restrict
from apps.tenancy.permissions import has_capability
from apps.tenancy.viewsets import TenantModelViewSet
from apps.passports.confidential import aries_reader, is_aries_only

from . import fields as F
from . import services
from .models import EditRequest

ROLE_NAMES = {"operator_engineer": "Aries Engineer", "client_admin": "Client Administrator", "client_engineer": "Client Engineer",
              "client_user": "Client User"}


class EditEventSerializer(serializers.Serializer):
    action = serializers.CharField()
    from_status = serializers.CharField()
    to_status = serializers.CharField()
    note = serializers.CharField()
    side = serializers.CharField()
    user = serializers.CharField()
    created_at = serializers.DateTimeField()


class ChangeSerializer(serializers.Serializer):
    field = serializers.CharField()
    label = serializers.CharField()
    original = serializers.JSONField(allow_null=True)
    proposed = serializers.JSONField(allow_null=True)
    current = serializers.JSONField(allow_null=True, help_text="Value in the target now")
    drifted = serializers.BooleanField(help_text="The target value changed since the request was made")


class EditRequestSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    data_class_label = serializers.CharField(source="get_data_class_display", read_only=True)
    part_number = serializers.CharField(source="part.part_number", read_only=True)
    part_name = serializers.CharField(source="part.name", read_only=True)
    project = serializers.SerializerMethodField()
    passport_number = serializers.SerializerMethodField()
    changes = serializers.SerializerMethodField()
    requester = serializers.SerializerMethodField()
    requester_role_label = serializers.SerializerMethodField()
    reviewer_name = serializers.SerializerMethodField()
    events = serializers.SerializerMethodField()
    allowed_actions = serializers.SerializerMethodField()

    class Meta:
        model = EditRequest
        fields = ["id", "reference", "target_type", "part", "part_number", "part_name", "project", "passport", "passport_number",
                  "base_revision_number", "base_revision_status", "base_updated_at", "data_class", "data_class_label", "status",
                  "status_label", "changes", "reason", "evidence_files", "requester", "requester_role", "requester_role_label",
                  "requester_side", "created_at", "submitted_at", "reviewer_name", "decision_reason", "decided_at", "applied_at",
                  "applied_revision_number", "application_result", "events", "allowed_actions"]

    def get_project(self, obj) -> str:
        return f"{obj.part.project.code} · {obj.part.project.name}" if obj.part.project_id else ""

    def get_passport_number(self, obj) -> str:
        return obj.passport.passport_number if obj.passport_id else ""

    @extend_schema_field(ChangeSerializer(many=True))
    def get_changes(self, obj):
        if obj.passport_id:
            rev = services.latest_revision(obj.passport)
            cur = lambda f: F.content_value(rev.content if rev else {}, f)  # noqa: E731
        else:
            cur = lambda f: F.part_value(obj.part, f)  # noqa: E731
        rows = [{**c, "current": cur(c["field"]), "drifted": not F.same(cur(c["field"]), c["original"])} for c in obj.changes]
        if obj.passport_id and not aries_reader(self.context.get("request")):  # D-18
            rows = [{**r, "original": None, "proposed": None, "current": None, "restricted": True} if is_aries_only(r["field"]) else r
                    for r in rows]
        return rows

    def get_requester(self, obj) -> str:
        return display_name(obj.created_by)

    def get_requester_role_label(self, obj) -> str:
        return ROLE_NAMES.get(obj.requester_role, obj.requester_role)

    def get_reviewer_name(self, obj) -> str:
        return display_name(obj.reviewer) if obj.reviewer_id else ""

    @extend_schema_field(EditEventSerializer(many=True))
    def get_events(self, obj):
        return [{"action": e.action, "from_status": e.from_status, "to_status": e.to_status, "note": e.note, "side": e.side,
                 "user": display_name(e.created_by), "created_at": e.created_at} for e in obj.events.select_related("created_by")]

    def get_allowed_actions(self, obj) -> list[str]:
        request = self.context["request"]
        mine = obj.created_by_id == request.user.pk
        reviewer = has_capability(request, "edits.review") and not mine
        S = EditRequest.Status
        acts = []
        if mine and obj.status in services.EDITABLE:
            acts += ["update", "submit"]
        if mine and obj.status in (S.DRAFT, S.SUBMITTED, S.CORRECTIONS, S.CONFLICT):
            acts.append("withdraw")
        if mine and obj.status == S.CONFLICT:
            acts.append("rebase")
        if reviewer and obj.status == S.SUBMITTED:
            acts.append("start_review")
        if reviewer and obj.status in services.REVIEWABLE:
            acts += ["approve", "reject", "request_corrections"]
        return acts


class EditFieldSerializer(serializers.Serializer):
    field = serializers.CharField()
    label = serializers.CharField()
    current = serializers.JSONField(allow_null=True)
    kind = serializers.CharField()
    choices = serializers.ListField(child=serializers.CharField())


class EditRequestViewSet(TenantModelViewSet):
    model = EditRequest
    serializer_class = EditRequestSerializer
    audit_type = "edit_request"
    capabilities = {"list": "edits.request", "retrieve": "edits.request", "create": "edits.request", "partial_update": "edits.request",
                    "update": "edits.request", "fields": "edits.request", "submit": "edits.request", "withdraw": "edits.request",
                    "rebase": "edits.request", "start_review": "edits.review", "approve": "edits.review", "reject": "edits.review",
                    "request_corrections": "edits.review"}

    def get_permissions(self):
        # reviewers may list and open requests even without the requester capability
        if self.action in ("list", "retrieve") and has_capability(self.request, "edits.review"):
            self.capabilities = {**self.capabilities, self.action: "edits.review"}
        return super().get_permissions()

    def get_queryset(self):
        qs = restrict(self.request, super().get_queryset().select_related("part", "part__project", "passport", "created_by", "reviewer"),
                      "part__project")
        p = self.request.query_params
        if p.get("queue") == "review":
            qs = qs.filter(status__in=services.REVIEWABLE).exclude(created_by=self.request.user)
        elif p.get("queue") == "mine":
            qs = qs.filter(created_by=self.request.user)
        for f in ("status", "part", "passport"):
            if p.get(f):
                qs = qs.filter(**{f: p[f]})
        return qs

    def _target(self, data):
        parts = restrict(self.request, SparePart.objects.filter(tenant=self.request.tenant), "project", own="submitted_by")
        part = parts.filter(pk=data.get("part")).first() if data.get("part") else None
        if part is None:
            raise DomainError("not_found", "Spare part not found.", http_status=404)
        passport = None
        if data.get("passport"):
            passport = DigitalPassport.objects.filter(tenant=self.request.tenant, pk=data["passport"], part=part).first()
            if passport is None:
                raise DomainError("not_found", "Digital passport not found.", http_status=404)
        return part, passport

    @extend_schema(parameters=[OpenApiParameter("part", str), OpenApiParameter("passport", str)], responses=EditFieldSerializer(many=True))
    @action(detail=False, methods=["get"], pagination_class=None)
    def fields(self, request):
        """Fields that may be requested for this part or passport, with current values."""
        part, passport = self._target(request.query_params)
        return Response(services.available_fields(part, passport, request))

    @extend_schema(request=inline_serializer("EditRequestCreate", {
        "part": serializers.UUIDField(), "passport": serializers.UUIDField(required=False, allow_null=True),
        "changes": serializers.ListField(child=serializers.DictField()), "reason": serializers.CharField(),
        "evidence_files": serializers.ListField(child=serializers.UUIDField(), required=False),
        "submit": serializers.BooleanField(required=False)}), responses={201: EditRequestSerializer})
    def create(self, request, *args, **kwargs):
        part, passport = self._target(request.data)
        er = services.create(request, part, passport, request.data)
        return Response(self.get_serializer(er).data, status=201)

    @extend_schema(request=inline_serializer("EditRequestUpdate", {
        "changes": serializers.ListField(child=serializers.DictField(), required=False), "reason": serializers.CharField(required=False),
        "evidence_files": serializers.ListField(child=serializers.UUIDField(), required=False)}), responses=EditRequestSerializer)
    def partial_update(self, request, *args, **kwargs):
        return Response(self.get_serializer(services.update(request, self.get_object(), request.data)).data)

    def update(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)

    def _act(self, request, fn, *args):
        er = fn(request, self.get_object(), *args)
        # the apply step writes through its own locked instances: show the target as it is now
        er.part.refresh_from_db()
        return Response(self.get_serializer(er).data)

    NOTE = inline_serializer("EditDecision", {"note": serializers.CharField(required=False, allow_blank=True)})

    @extend_schema(request=None, responses=EditRequestSerializer)
    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        return self._act(request, services.submit)

    @extend_schema(request=NOTE, responses=EditRequestSerializer)
    @action(detail=True, methods=["post"])
    def withdraw(self, request, pk=None):
        return self._act(request, services.withdraw, str(request.data.get("note") or ""))

    @extend_schema(request=None, responses=EditRequestSerializer)
    @action(detail=True, methods=["post"])
    def rebase(self, request, pk=None):
        return self._act(request, services.rebase)

    @extend_schema(request=None, responses=EditRequestSerializer)
    @action(detail=True, methods=["post"], url_path="start-review")
    def start_review(self, request, pk=None):
        return self._act(request, services.start_review)

    @extend_schema(request=NOTE, responses=EditRequestSerializer)
    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return self._act(request, services.approve, str(request.data.get("note") or ""))

    @extend_schema(request=NOTE, responses=EditRequestSerializer)
    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        return self._act(request, services.reject, str(request.data.get("note") or ""))

    @extend_schema(request=NOTE, responses=EditRequestSerializer)
    @action(detail=True, methods=["post"], url_path="request-corrections")
    def request_corrections(self, request, pk=None):
        return self._act(request, services.request_corrections, str(request.data.get("note") or ""))
