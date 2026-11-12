"""REST API for client service requests, the operator intake queue and in-app notifications.

Client side (current client tenant, RLS): /requests/ list, create (manufacturing enquiry/request or digitisation),
detail with history and attachments, reply, withdraw, attachment upload and download.
Operator side: /operator/requests/ lists the operator-tenant envelopes; detail and actions are allowed only for
operator staff with an ACTIVE assignment (membership) to the request's client, and run in that client's tenant
context. Operator administrators see the intake list; opening a client's request needs that assignment.
Notifications: /notifications/ for the signed-in user only (per-user RLS).
"""
import hashlib
from datetime import date

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse
from django.utils import timezone
from drf_spectacular.utils import extend_schema, extend_schema_field, inline_serializer
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.service import record
from apps.jobsheets.api import JobSheetActionsMixin
from apps.core.exceptions import DomainError
from apps.files.storage import ObjectExists, get_storage
from apps.files.validation import validate_upload
from apps.parts.models import SparePart
from apps.passports.models import DigitalPassport
from apps.projects.models import Project
from apps.tenancy.context import tenant_context
from apps.projects.scoping import allowed_project_ids, allowed_project_ids_for, project_allowed
from apps.tenancy.models import OPERATOR_ROLES, Membership, Role, Tenant
from apps.tenancy.permissions import HasCapability

from . import services as svc
from .models import ClientRequest, Notification, RequestAttachment, RequestEnvelope, RequestEvent

SERVICES = ["Additive manufacturing", "Machining and finishing", "Heat treatment", "Dimensional inspection report",
            "Material test certificate", "Packaging and dispatch"]
MAX_ATTACHMENTS = 10
K = ClientRequest.Kind


class EventSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()

    class Meta:
        model = RequestEvent
        fields = ["id", "event", "from_status", "to_status", "message", "author_side", "author_name", "created_at"]

    def get_author_name(self, obj) -> str:
        u = obj.author
        if obj.author_side == RequestEvent.Side.OPERATOR:
            if self.context.get("operator"):
                return (f"{u.first_name} {u.last_name}".strip() or u.email) if u else "Aries Engineering"
            return "Aries Engineering"
        return (f"{u.first_name} {u.last_name}".strip() or u.email) if u else "Client"


class AttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = RequestAttachment
        fields = ["id", "original_filename", "kind", "detected_format", "content_type", "size_bytes", "sha256", "created_at"]


class RequestSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    requested_by_email = serializers.SerializerMethodField()
    events = EventSerializer(many=True, read_only=True)
    attachments = AttachmentSerializer(many=True, read_only=True)
    project_code = serializers.SerializerMethodField()
    linked_part_number = serializers.SerializerMethodField()
    responsible = serializers.SerializerMethodField(help_text="Responsible Aries Engineer (clients see only that one is assigned)")
    handover = serializers.SerializerMethodField(help_text="Scanning-to-passport handover: deliverables and passport (D-15)")

    class Meta:
        model = ClientRequest
        fields = ["id", "reference", "kind", "kind_label", "status", "status_label", "priority", "part", "passport",
                  "passport_revision_number", "part_number", "part_name", "quantity", "required_date", "delivery_location",
                  "services", "remarks", "client_reference", "material_option", "original_material", "proposed_material",
                  "material_change_reason", "linked_part", "linked_part_number", "job_progress", "site_location", "equipment", "part_description", "reason",
                  "preferred_date", "contact_name", "contact_phone", "contact_email", "quotation_reference", "project",
                  "project_code", "created_part", "acknowledged_at", "closed_reason", "requested_by_email", "responsible", "handover", "created_at",
                  "updated_at", "events", "attachments"]
        read_only_fields = fields

    def get_responsible(self, obj) -> dict | None:
        if not obj.assigned_to_id:
            return None
        if self.context.get("operator"):
            u = obj.assigned_to
            return {"id": str(u.pk), "name": u.get_full_name() or u.email, "email": u.email, "assigned_at": obj.assigned_at}
        return {"name": "Aries Engineering (engineer assigned)", "assigned_at": obj.assigned_at}

    def get_handover(self, obj) -> dict | None:
        if obj.kind != K.DIGITISATION:
            return None
        operator = self.context.get("operator")
        rows = []
        for d in obj.deliverables.select_related("file").all():
            visible = operator or (d.file_id is not None and d.file.client_visible)
            rows.append({"kind": d.kind, "kind_label": d.get_kind_display(), "title": d.title, "note": d.note if operator else "",
                         "file": str(d.file_id) if d.file_id and visible else None, "file_version": d.file_version if visible else None,
                         "file_released": bool(d.file_id and d.file.client_visible), "recorded_at": d.created_at})
        return {"deliverables": rows, "handed_over_at": obj.handed_over_at,
                "passport": str(obj.handover_passport_id) if obj.handover_passport_id else None,
                "passport_number": obj.handover_passport.passport_number if obj.handover_passport_id else None,
                "created_part": str(obj.created_part_id) if obj.created_part_id else None,
                "note": "Recording a deliverable states what was produced; scan meshes and point clouds are not production-ready CAD."}

    def get_linked_part_number(self, obj) -> str | None:
        return obj.linked_part.part_number if obj.linked_part_id else None

    def get_requested_by_email(self, obj) -> str | None:
        return obj.requested_by.email if obj.requested_by else None

    def get_project_code(self, obj) -> str | None:
        return obj.project.code if obj.project_id else None


class RequestListSerializer(RequestSerializer):
    class Meta(RequestSerializer.Meta):
        fields = [f for f in RequestSerializer.Meta.fields if f not in ("events", "attachments")]
        read_only_fields = fields


class ManufacturingInput(serializers.Serializer):
    part = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1, max_value=100000)
    required_date = serializers.DateField()
    delivery_location = serializers.CharField(max_length=300)
    services = serializers.ListField(child=serializers.ChoiceField(choices=SERVICES), required=False, default=list)
    priority = serializers.ChoiceField(choices=ClientRequest.Priority.choices, default=ClientRequest.Priority.ROUTINE)
    remarks = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")
    client_reference = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    material_option = serializers.ChoiceField(choices=["original", "proposed"], default="original")
    proposed_material = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    material_change_reason = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")
    linked_part = serializers.UUIDField(required=False, allow_null=True, help_text="An existing clone of this part to link")
    new_part_number = serializers.CharField(max_length=80, required=False, allow_blank=True, default="",
                                            help_text="Create a clone with this number for the proposed material")

    def validate(self, attrs):
        if attrs["material_option"] == "proposed":
            errors = {}
            if not attrs["proposed_material"].strip():
                errors["proposed_material"] = "Enter the proposed material."
            if not attrs["material_change_reason"].strip():
                errors["material_change_reason"] = "Give the reason for the material change."
            if errors:
                raise serializers.ValidationError(errors)
        return attrs

    def validate_required_date(self, value):
        if value < date.today():
            raise serializers.ValidationError("The required date cannot be in the past.")
        return value


class DigitisationInput(serializers.Serializer):
    site_location = serializers.CharField(max_length=300)
    equipment = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    part_description = serializers.CharField(max_length=2000)
    reason = serializers.ChoiceField(choices=ClientRequest.Reason.choices)
    preferred_date = serializers.DateField(required=False, allow_null=True)
    contact_name = serializers.CharField(max_length=150)
    contact_phone = serializers.CharField(max_length=60, required=False, allow_blank=True, default="")
    contact_email = serializers.EmailField(required=False, allow_blank=True, default="")
    priority = serializers.ChoiceField(choices=ClientRequest.Priority.choices, default=ClientRequest.Priority.ROUTINE)
    remarks = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")
    client_reference = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    project = serializers.UUIDField(required=False, allow_null=True, default=None, help_text="Optional project of your organisation (D-05)")

    def validate_preferred_date(self, value):
        if value and value < date.today():
            raise serializers.ValidationError("The preferred date cannot be in the past.")
        return value


class MessageInput(serializers.Serializer):
    message = serializers.CharField(max_length=2000, allow_blank=True, required=False, default="")


HANDOVER_ACTIONS = ("create_project", "link_project", "assign", "record_deliverable", "hand_over")


class OperatorActionInput(serializers.Serializer):
    action = serializers.ChoiceField(choices=sorted([*svc.OPERATOR_ACTIONS, *HANDOVER_ACTIONS]))
    message = serializers.CharField(max_length=2000, allow_blank=True, required=False, default="")
    engineer = serializers.UUIDField(required=False, allow_null=True, help_text="assign: the responsible Aries Engineer (user id)")
    project = serializers.UUIDField(required=False, allow_null=True, help_text="link_project: an existing project of the company")
    deliverable_kind = serializers.CharField(required=False, allow_blank=True, default="")
    title = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    file = serializers.UUIDField(required=False, allow_null=True)
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    quotation_reference = serializers.CharField(max_length=80, allow_blank=True, required=False)


def _store_attachment(request, obj: ClientRequest, upload) -> RequestAttachment:
    if obj.status not in svc.OPEN:
        raise DomainError("request_closed", "Attachments can only be added to open requests.", http_status=409)
    if obj.attachments.count() >= MAX_ATTACHMENTS:
        raise DomainError("too_many_attachments", f"A request can have at most {MAX_ATTACHMENTS} attachments.", http_status=400)
    v = validate_upload(upload)  # same checks as engineering uploads: type, size, content signature, image decoding
    n = obj.attachments.count() + 1
    key = f"tenants/{obj.tenant_id}/requests/{obj.pk}/a{n}-{timezone.now():%Y%m%d%H%M%S%f}.{v.ext}"
    upload.seek(0)
    digest = hashlib.sha256()

    def chunks():
        for c in upload.chunks():
            digest.update(c)
            yield c

    try:
        size, sha = get_storage().save_new(key, chunks())
    except ObjectExists:
        raise DomainError("version_conflict", "Please upload the file again.", http_status=409)
    att = RequestAttachment.objects.create(tenant=obj.tenant, created_by=request.user, request=obj, original_filename=v.safe_name,
                                          kind=v.kind, detected_format=v.detected_format, content_type=v.content_type,
                                          size_bytes=size, sha256=sha, storage_key=key)
    record(request, "request.attachment_added", obj=att, tenant=obj.tenant, data={"reference": obj.reference, "sha256": sha})
    return att


def _attachment_response(att: RequestAttachment):
    resp = FileResponse(get_storage().open(att.storage_key), as_attachment=True, filename=att.original_filename,
                        content_type=att.content_type)
    resp["X-Content-Type-Options"] = "nosniff"
    resp["Cache-Control"] = "no-store"
    resp["X-Content-SHA256"] = att.sha256
    return resp


class ClientRequestViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """The current client organisation's requests."""

    permission_classes = [HasCapability]
    capabilities = {"list": "requests.view", "retrieve": "requests.view", "create": "requests.create",
                    "reply": "requests.create", "withdraw": "requests.create", "attachments": "requests.create",
                    "attachment": "requests.view", "form_options": "requests.view"}
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_serializer_class(self):
        return RequestListSerializer if self.action == "list" else RequestSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ClientRequest.objects.none()
        qs = ClientRequest.objects.filter(tenant=self.request.tenant).select_related("requested_by", "project")
        ids = allowed_project_ids(self.request)  # project-scoped Client Users (2 Nov 2026); Client Admins see every request
        if ids is not None:
            qs = qs.filter(Q(project_id__in=ids) | Q(part__project_id__in=ids) | Q(requested_by=self.request.user))
        for field in ("kind", "status"):
            if self.request.query_params.get(field):
                qs = qs.filter(**{field: self.request.query_params[field]})
        if self.action == "retrieve":
            qs = qs.prefetch_related("events__author", "attachments")
        return qs

    @extend_schema(responses={200: inline_serializer("RequestOptions", {
        "services": serializers.ListField(child=serializers.CharField())})})
    @action(detail=False, methods=["get"], url_path="form-options")
    def form_options(self, request):
        return Response({"services": SERVICES})

    @extend_schema(request=inline_serializer("RequestCreate", {
        "request_type": serializers.ChoiceField(choices=["manufacturing", "digitisation"])}), responses={201: RequestSerializer})
    def create(self, request, *args, **kwargs):
        kind = request.data.get("request_type")
        if kind == "manufacturing":
            s = ManufacturingInput(data=request.data)
            s.is_valid(raise_exception=True)
            d = dict(s.validated_data)
            part = SparePart.objects.filter(tenant=request.tenant, pk=d.pop("part")).first()
            if part is None:
                raise DomainError("not_found", "Spare part not found.", http_status=404)
            passport = DigitalPassport.objects.filter(part=part).first()
            revision = passport.revisions.order_by("-revision_number").values_list("revision_number", flat=True).first() if passport else None
            req_kind, _ = svc.classify(part)  # server-side; never trusts the browser
            with transaction.atomic():
                material = svc.material_change(request, part, d)
                if material.get("material_option") == "proposed":
                    req_kind = K.ENQUIRY  # a material change is always an enquiry: suitability is not assessed yet
                obj = svc.create_request(request, kind=req_kind, part=part, passport=passport, passport_revision_number=revision,
                                         part_number=part.part_number, part_name=part.name,
                                         publication_state_at_submission=passport.publication_state if passport else "",
                                         eligibility_at_submission=passport.manufacturing_eligibility if passport else "",
                                         **d, **material)
        elif kind == "digitisation":
            s = DigitisationInput(data=request.data)
            s.is_valid(raise_exception=True)
            d = dict(s.validated_data)
            project_id = d.pop("project", None)
            if project_id:
                project = Project.objects.filter(tenant=request.tenant, pk=project_id).first()
                if project is None or not project_allowed(request, project.pk):
                    raise DomainError("validation_error", "Choose one of your organisation's projects.", details={"project": ["Not found."]},
                                      http_status=400)
                d["project"] = project
            obj = svc.create_request(request, kind=K.DIGITISATION, **d)
        else:
            raise DomainError("validation_error", "Choose a request type.", details={"request_type": ["manufacturing or digitisation"]})
        return Response(RequestSerializer(obj).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=MessageInput, responses={200: RequestSerializer})
    @action(detail=True, methods=["post"])
    def reply(self, request, pk=None):
        s = MessageInput(data=request.data)
        s.is_valid(raise_exception=True)
        obj = svc.client_message(request, self.get_object(), s.validated_data["message"])
        return Response(RequestSerializer(obj).data)

    @extend_schema(request=MessageInput, responses={200: RequestSerializer})
    @action(detail=True, methods=["post"])
    def withdraw(self, request, pk=None):
        s = MessageInput(data=request.data)
        s.is_valid(raise_exception=True)
        obj = svc.withdraw(request, self.get_object(), s.validated_data["message"])
        return Response(RequestSerializer(obj).data)

    @extend_schema(request={"multipart/form-data": inline_serializer("RequestAttachmentUpload", {"file": serializers.FileField()})},
                   responses={201: AttachmentSerializer})
    @action(detail=True, methods=["post"])
    def attachments(self, request, pk=None):
        upload = request.FILES.get("file")
        if upload is None:
            raise DomainError("file_required", "Choose a file to upload.", http_status=400)
        att = _store_attachment(request, self.get_object(), upload)
        return Response(AttachmentSerializer(att).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={(200, "application/octet-stream"): bytes})
    @action(detail=True, methods=["get"], url_path=r"attachments/(?P<aid>[0-9a-f-]+)")
    def attachment(self, request, pk=None, aid=None):
        att = RequestAttachment.objects.filter(request=self.get_object(), pk=aid).first()
        if att is None:
            raise DomainError("not_found", "Attachment not found.", http_status=404)
        record(request, "request.attachment_downloaded", obj=att, data={"reference": att.request.reference})
        return _attachment_response(att)


# ---- operator intake ---------------------------------------------------------------------------------------------

class EnvelopeSerializer(serializers.ModelSerializer):
    kind_label = serializers.SerializerMethodField()
    status_label = serializers.SerializerMethodField()
    assigned = serializers.SerializerMethodField(help_text="True when the caller is assigned to this client and can open it")

    class Meta:
        model = RequestEnvelope
        fields = ["id", "intake_number", "reference", "client_tenant", "client_name", "kind", "kind_label", "status", "status_label", "priority",
                  "project_ref", "assigned_to",
                  "part_number", "part_name", "quantity", "required_date", "submitted_at", "updated_at", "assigned"]

    def get_kind_label(self, obj) -> str:
        return ClientRequest.Kind(obj.kind).label

    def get_status_label(self, obj) -> str:
        return ClientRequest.Status(obj.status).label

    def get_assigned(self, obj) -> bool:
        return str(obj.client_tenant_id) in self.context.get("assigned", set())


class OperatorRequestSerializer(RequestSerializer):
    client_name = serializers.SerializerMethodField()
    part_summary = serializers.SerializerMethodField()
    intake_number = serializers.SerializerMethodField(help_text="Platform-wide Aries intake number (unique across companies)")
    engineer_candidates = serializers.SerializerMethodField()
    company_projects = serializers.SerializerMethodField()
    created_part_files = serializers.SerializerMethodField(help_text="Files of the part created for the request (deliverable pinning)")

    class Meta(RequestSerializer.Meta):
        fields = [*RequestSerializer.Meta.fields, "client_name", "part_summary", "intake_number", "engineer_candidates", "company_projects",
                  "created_part_files"]
        read_only_fields = fields

    def get_client_name(self, obj) -> str:
        return self.context.get("client_name", "")

    def get_intake_number(self, obj) -> str:
        return self.context.get("intake_number", "")

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_engineer_candidates(self, obj):
        """Active Aries Engineers of this company allowed for the request's project (for the assign action)."""
        pid = svc.request_project_id(obj)
        out = []
        for m in Membership.objects.filter(tenant_id=obj.tenant_id, role=Role.OPERATOR_ENGINEER, is_active=True).select_related("user"):
            allowed = allowed_project_ids_for(obj.tenant_id, m.user_id)
            if allowed is None or pid in allowed:
                out.append({"id": str(m.user_id), "name": m.user.get_full_name() or m.user.email, "email": m.user.email})
        return out

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_created_part_files(self, obj):
        from apps.files.models import EngineeringFile

        if not obj.created_part_id:
            return []
        return [{"id": str(f.pk), "title": f.title, "kind": f.kind, "client_visible": f.client_visible}
                for f in EngineeringFile.objects.filter(tenant_id=obj.tenant_id, part_id=obj.created_part_id).order_by("title")]

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_company_projects(self, obj):
        return [{"id": str(p.pk), "code": p.code, "name": p.name} for p in Project.objects.filter(tenant_id=obj.tenant_id).order_by("code")]

    @extend_schema_field(serializers.DictField(allow_null=True))
    def get_part_summary(self, obj):
        p = obj.part
        if not p:
            return None
        passport = DigitalPassport.objects.filter(part=p).first()
        return {"id": str(p.pk), "dimensions": p.dimensions, "material": p.original_material, "criticality": p.criticality,
                "passport_id": str(passport.pk) if passport else None, "passport_number": passport.passport_number if passport else None,
                "publication_state": passport.publication_state if passport else None,
                "manufacturing_eligibility": passport.manufacturing_eligibility if passport else None}


def _operator_staff(request):
    """The caller must be operator staff: an active operator-role membership in the operator organisation."""
    op = svc.operator_tenant()
    if not Membership.objects.filter(user=request.user, tenant=op, role__in=OPERATOR_ROLES, is_active=True).exists():
        raise DomainError("permission_denied", "Only operator staff can open the intake queue.", http_status=403)
    return op


def _is_operator_admin(user, op) -> bool:
    return Membership.objects.filter(user=user, tenant=op, role__in=[Role.OPERATOR_ADMIN, Role.OPERATOR_MANAGER], is_active=True).exists()


def _assigned_clients(user) -> set[str]:
    return {str(t) for t in Membership.objects.filter(user=user, role__in=OPERATOR_ROLES, is_active=True,
                                                      tenant__kind=Tenant.Kind.CLIENT).values_list("tenant_id", flat=True)}


class OperatorRequestViewSet(JobSheetActionsMixin, viewsets.GenericViewSet):
    permission_classes = [HasCapability]
    capabilities = {"list": "requests.handle", "retrieve": "requests.handle", "act": "requests.handle", "attachment": "requests.handle",
                    # CN-004 draft job sheets: Aries Engineers prepare; QA has read access; gates stay closed
                    "jobsheet": "jobsheets.view", "jobsheet_revision": "jobsheets.view", "jobsheet_cancel": "jobsheets.prepare",
                    "jobsheet_gate": "jobsheets.prepare"}
    serializer_class = EnvelopeSerializer

    def get_permissions(self):
        if self.action == "jobsheet" and self.request.method in ("POST", "PATCH"):
            self.capabilities = {**self.capabilities, "jobsheet": "jobsheets.prepare"}
        return super().get_permissions()

    def get_queryset(self):
        return RequestEnvelope.objects.none()

    def _envelope(self, request, pk):
        op = _operator_staff(request)
        with tenant_context(op):
            env = RequestEnvelope.objects.filter(pk=pk).first()
        if env is None:
            raise DomainError("not_found", "Request not found.", http_status=404)
        if str(env.client_tenant_id) not in _assigned_clients(request.user):
            raise DomainError("not_assigned", "You are not assigned to this client organisation.", http_status=403)
        return env

    def _load(self, env):
        obj = ClientRequest.objects.select_related("requested_by", "project", "part").prefetch_related("events__author", "attachments").filter(pk=env.request_id).first()
        if obj is None:
            raise DomainError("not_found", "Request not found.", http_status=404)
        # Project-limited Aries staff (CN-002 D4) open only requests of their assigned projects.
        allowed = allowed_project_ids_for(env.client_tenant_id, self.request.user.pk)
        project_id = svc.request_project_id(obj)  # same rule as the intake list (D-05)
        if allowed is not None and project_id not in allowed:
            raise DomainError("not_assigned_project", "This request belongs to a project you are not assigned to.", http_status=403)
        return obj

    def list(self, request):
        op = _operator_staff(request)
        p = request.query_params
        assigned = _assigned_clients(request.user)
        with tenant_context(op):
            qs = RequestEnvelope.objects.all()
            if not _is_operator_admin(request.user, op):
                # engineers, QA and support see only the clients they are actively assigned to
                qs = qs.filter(client_tenant_id__in=assigned)
            for field in ("kind", "status", "client_tenant", "priority"):
                if p.get(field):
                    qs = qs.filter(**{field: p[field]})
            if p.get("open") == "true":
                qs = qs.filter(status__in=svc.OPEN)
            if p.get("mine") == "true":
                qs = qs.filter(assigned_to=request.user)
            rows = list(qs[:500])
        if not _is_operator_admin(request.user, op):
            scope = {}
            for r in rows:  # project-limited engineers list only what they can open (CN-002 D4); project-less requests included
                if r.client_tenant_id not in scope:
                    with tenant_context(r.client_tenant_id):  # the access rows live in the client's row-level-security context
                        scope[r.client_tenant_id] = allowed_project_ids_for(r.client_tenant_id, request.user.pk)
            rows = [r for r in rows if scope[r.client_tenant_id] is None or r.project_ref in scope[r.client_tenant_id]]
        return Response(EnvelopeSerializer(rows, many=True, context={"assigned": assigned}).data)

    @extend_schema(responses={200: OperatorRequestSerializer})
    def retrieve(self, request, pk=None):
        env = self._envelope(request, pk)
        with tenant_context(env.client_tenant_id):
            obj = self._load(env)
            data = OperatorRequestSerializer(obj, context={"client_name": env.client_name, "intake_number": env.intake_number, "operator": True}).data
            record(request, "request.viewed_by_operator", obj=obj, tenant=env.client_tenant, data={"reference": obj.reference})
        return Response(data)

    @extend_schema(request=OperatorActionInput, responses={200: OperatorRequestSerializer})
    @action(detail=True, methods=["post"])
    def act(self, request, pk=None):
        s = OperatorActionInput(data=request.data)
        s.is_valid(raise_exception=True)
        env = self._envelope(request, pk)
        with tenant_context(env.client_tenant_id):
            obj = self._load(env)
            if "quotation_reference" in s.validated_data:
                obj.quotation_reference = s.validated_data["quotation_reference"]
                obj.save(update_fields=["quotation_reference", "updated_at"])
            v = s.validated_data
            if v["action"] == "create_project":
                obj = create_project_from_request(request, obj)
            elif v["action"] == "link_project":
                obj = svc.link_project(request, obj, v.get("project"))
            elif v["action"] == "assign":
                obj = svc.assign(request, obj, v.get("engineer"))
            elif v["action"] == "record_deliverable":
                obj = svc.record_deliverable(request, obj, v["deliverable_kind"], v["title"], v.get("file"), v["note"])
            elif v["action"] == "hand_over":
                obj = svc.hand_over(request, obj)
            else:
                obj = svc.operator_action(request, obj, s.validated_data["action"], s.validated_data["message"])
            obj = self._load(env)  # fresh history (the earlier prefetch predates this action)
            data = OperatorRequestSerializer(obj, context={"client_name": env.client_name, "intake_number": env.intake_number, "operator": True}).data
        return Response(data)

    @extend_schema(responses={(200, "application/octet-stream"): bytes})
    @action(detail=True, methods=["get"], url_path=r"attachments/(?P<aid>[0-9a-f-]+)")
    def attachment(self, request, pk=None, aid=None):
        env = self._envelope(request, pk)
        from apps.tenancy import admin_workspace

        if admin_workspace.file_content_blocked_for(request.user, env.client_tenant):
            raise DomainError(*admin_workspace.BLOCKED, http_status=403)
        with tenant_context(env.client_tenant_id):
            att = RequestAttachment.objects.filter(request_id=env.request_id, pk=aid).first()
            if att is None:
                raise DomainError("not_found", "Attachment not found.", http_status=404)
            record(request, "request.attachment_downloaded", obj=att, tenant=env.client_tenant, data={"by": "operator"})
            return _attachment_response(att)


def create_project_from_request(request, obj: ClientRequest) -> ClientRequest:
    """Accepted digitisation request -> a project and one draft spare part in the client's organisation (once).
    Passports, files and evidence are then created with the existing engineering functions."""
    if obj.kind != K.DIGITISATION:
        raise DomainError("transition_not_allowed", "Only digitisation requests create projects.", http_status=409)
    if obj.status not in (ClientRequest.Status.ACKNOWLEDGED, ClientRequest.Status.INFORMATION_PROVIDED,
                          ClientRequest.Status.SCHEDULED, ClientRequest.Status.IN_PROGRESS):
        raise DomainError("transition_not_allowed", "Acknowledge the request before creating its project.", http_status=409)
    if obj.created_part_id:
        raise DomainError("already_created", "A draft part already exists for this request.", http_status=409)
    with transaction.atomic():
        # post-UAT D-05: a request that already belongs to a project (chosen by the client or linked by Aries) gets only its part
        project = obj.project or Project.objects.create(tenant=obj.tenant, created_by=request.user, code=obj.reference,
                                                        name=f"Digitisation {obj.reference}"[:200],
                                                        description=f"Created from digitisation request {obj.reference}. Site: {obj.site_location}.")
        part = SparePart.objects.create(tenant=obj.tenant, created_by=request.user, project=project, part_number=f"{obj.reference}-01",
                                        name=(obj.part_description.splitlines() or ["Part to digitise"])[0][:200],
                                        description=obj.part_description, equipment_reference=obj.equipment[:120],
                                        status=SparePart.Status.DRAFT)
        obj.project, obj.created_part = project, part
        obj.save(update_fields=["project", "created_part", "updated_at"])
        RequestEvent.objects.create(tenant=obj.tenant, created_by=request.user, request=obj, event="project_created",
                                    from_status=obj.status, to_status=obj.status, author=request.user,
                                    author_side=RequestEvent.Side.OPERATOR,
                                    message=f"Draft part {part.part_number} created in project {project.code} for this request.")
        record(request, "request.project_created", obj=obj, tenant=obj.tenant, data={"project": project.code, "part": part.part_number})
        svc.notify_client(obj, "project_created", body=f"Project {project.code} created.")
    return obj


# ---- notifications -----------------------------------------------------------------------------------------------

class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "title", "body", "link", "organisation_name", "read_at", "created_at"]


class NotificationListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: inline_serializer("NotificationList", {
        "unread": serializers.IntegerField(), "results": NotificationSerializer(many=True)})})
    def get(self, request):
        qs = Notification.objects.filter(recipient=request.user)  # also enforced by per-user RLS
        return Response({"unread": qs.filter(read_at__isnull=True).count(), "results": NotificationSerializer(qs[:30], many=True).data})


class NotificationReadView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={204: None})
    def post(self, request, pk=None):
        qs = Notification.objects.filter(recipient=request.user, read_at__isnull=True)
        (qs if pk is None else qs.filter(pk=pk)).update(read_at=timezone.now())
        return Response(status=status.HTTP_204_NO_CONTENT)


class OperatorOverviewView(APIView):
    """Operator administrators: one row per client organisation with aggregate counts only (no records).

    Counts are read inside each client's own tenant context (row-level security applies); open requests come from
    the operator-tenant intake summaries. Nothing here grants access to a client's detailed records."""

    permission_classes = [HasCapability]
    capabilities = {"get": "clients.view"}

    @extend_schema(responses={200: inline_serializer("OperatorOverviewRow", {
        "id": serializers.UUIDField(), "name": serializers.CharField(), "slug": serializers.CharField(),
        "status": serializers.CharField(), "hosting_model": serializers.CharField(),
        "counts": serializers.DictField(child=serializers.IntegerField())}, many=True)})
    def get(self, request):
        from apps.passports.models import DigitalPassport as Passport  # noqa: PLC0415

        op = svc.operator_tenant()
        if request.tenant.pk != op.pk:
            raise DomainError("permission_denied", "Available in the operator organisation only.", http_status=403)
        with tenant_context(op):
            open_by_client = {}
            for cid in RequestEnvelope.objects.filter(status__in=svc.OPEN).values_list("client_tenant_id", flat=True):
                open_by_client[cid] = open_by_client.get(cid, 0) + 1
            waiting = {}
            for cid in RequestEnvelope.objects.filter(status=ClientRequest.Status.SUBMITTED).values_list("client_tenant_id", flat=True):
                waiting[cid] = waiting.get(cid, 0) + 1
        rows = []
        for t in Tenant.objects.filter(kind=Tenant.Kind.CLIENT).order_by("name"):
            members = Membership.objects.filter(tenant=t, is_active=True)
            with tenant_context(t):
                parts, passports = SparePart.objects.count(), Passport.objects.count()
            rows.append({"id": str(t.pk), "name": t.name, "slug": t.slug, "status": t.status, "hosting_model": t.hosting_model,
                         "counts": {"parts": parts, "passports": passports, "open_requests": open_by_client.get(t.pk, 0),
                                    "awaiting_acknowledgement": waiting.get(t.pk, 0),
                                    "client_users": members.exclude(role__in=OPERATOR_ROLES).count(),
                                    "assigned_staff": members.filter(role__in=OPERATOR_ROLES).count()}})
        return Response(rows)
