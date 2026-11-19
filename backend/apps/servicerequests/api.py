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
    quotation = serializers.SerializerMethodField()
    handover = serializers.SerializerMethodField(help_text="Scanning-to-passport handover: deliverables and passport (D-15)")

    class Meta:
        model = ClientRequest
        fields = ["id", "reference", "kind", "kind_label", "status", "status_label", "priority", "part", "passport",
                  "passport_revision_number", "part_number", "part_name", "quantity", "required_date", "delivery_location",
                  "services", "remarks", "client_reference", "material_option", "original_material", "proposed_material",
                  "material_change_reason", "linked_part", "linked_part_number", "job_progress", "site_location", "equipment", "part_description", "reason",
                  "preferred_date", "contact_name", "contact_phone", "contact_email", "quotation_reference", "project",
                  "project_code", "created_part", "acknowledged_at", "closed_reason", "requested_by_email", "responsible", "handover", "created_at",
                  "updated_at", "events", "attachments", "quotation"]
        read_only_fields = fields

    @extend_schema_field(serializers.DictField(allow_null=True, help_text="The quotation in force: method, price, delivery days, validity "
                                                "and status only (never the cost breakdown)."))
    def get_quotation(self, obj) -> dict | None:
        from .quotations import client_view, current

        return client_view(current(obj))

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
    action = serializers.ChoiceField(choices=sorted([*svc.OPERATOR_ACTIONS, *HANDOVER_ACTIONS, "message"]))
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
                    "attachment": "requests.view", "form_options": "requests.view", "quotation": "requests.view"}
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

    @extend_schema(request=inline_serializer("QuotationDecision", {"decision": serializers.ChoiceField(choices=["accept", "reject"]),
                                                                  "note": serializers.CharField(required=False, allow_blank=True)}),
                   responses={200: RequestSerializer})
    @action(detail=True, methods=["post"])
    def quotation(self, request, pk=None):
        from .quotations import decide

        obj = self.get_object()
        decide(request, obj, str(request.data.get("decision", "")), str(request.data.get("note", "") or ""))
        return Response(RequestSerializer(self.get_object()).data)

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
                  "project_ref", "assigned_to", "awaiting_reply", "last_client_activity", "last_client_activity_at",
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


def _quotation_operator(obj) -> dict | None:
    from .quotations import current, operator_view

    return operator_view(current(obj))


def _production_route(obj) -> dict | None:
    """The chosen production route of a manufacturing request (Aries view only; the client sees the route name in the
    release step of its history, never the estimated cost)."""
    if obj.kind == K.ENQUIRY or obj.kind == K.MANUFACTURING:
        from apps.intelligence.estimate import chosen_route

        return chosen_route(obj)
    return None


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


def _visible_envelopes(request, op, qs, limit=None) -> list:
    """The request envelopes this Aries staff member may see, from `qs` (built in the operator tenant). Admins and Managers:
    all. Engineers, QA and support: the clients they are actively assigned to; while they work inside one client company
    (chosen in the top bar) only that company (decision of 16 Nov 2026); project-limited staff only the requests of their
    assigned projects (CN-002 D4), with the same rule as the request detail. Shared by the queue and the dashboard."""
    admin = _is_operator_admin(request.user, op)
    with tenant_context(op):
        if not admin:
            qs = qs.filter(client_tenant_id__in=_assigned_clients(request.user))
            current = getattr(request, "membership", None)
            if current is not None and current.tenant.kind == Tenant.Kind.CLIENT:
                qs = qs.filter(client_tenant_id=current.tenant_id)
        rows = list(qs[:limit] if limit else qs)
    if admin:
        return rows
    scope, live = {}, {}
    for r in rows:
        if r.client_tenant_id not in scope:
            with tenant_context(r.client_tenant_id):  # the access rows live in the client's row-level-security context
                allowed = allowed_project_ids_for(r.client_tenant_id, request.user.pk)
                scope[r.client_tenant_id] = allowed
                if allowed is not None:  # the request's project now (its part may have moved into a project since)
                    ids = [x.request_id for x in rows if x.client_tenant_id == r.client_tenant_id]
                    for cr in ClientRequest.objects.filter(pk__in=ids):
                        live[cr.pk] = svc.request_project_id(cr)
    return [r for r in rows if scope[r.client_tenant_id] is None or live.get(r.request_id, r.project_ref) in scope[r.client_tenant_id]]


class OperatorRequestViewSet(JobSheetActionsMixin, viewsets.GenericViewSet):
    permission_classes = [HasCapability]
    capabilities = {"list": "requests.handle", "retrieve": "requests.handle", "act": "requests.handle", "attachment": "requests.handle",
                    "passport": "requests.handle", "passport_file": "requests.handle", "passport_report": "requests.handle",
                    "estimate": "requests.handle", "archive": "requests.handle",
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
        # Aries Admins and Managers open and answer every client's requests (decision of 12 Nov 2026); other Aries staff only
        # those of the client organisations they are assigned to. Confidential attachments keep their own rule
        # (admin_workspace.file_content_blocked_for).
        if not _is_operator_admin(request.user, op) and str(env.client_tenant_id) not in _assigned_clients(request.user):
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
            for field in ("kind", "status", "client_tenant", "priority"):
                if p.get(field):
                    qs = qs.filter(**{field: p[field]})
            if p.get("open") == "true":
                qs = qs.filter(status__in=svc.OPEN)
            if p.get("awaiting") == "true":
                qs = qs.filter(awaiting_reply=True)
            if p.get("mine") == "true":
                qs = qs.filter(assigned_to=request.user)
        rows = _visible_envelopes(request, op, qs, limit=500)
        if _is_operator_admin(request.user, op):
            assigned = {str(r.client_tenant_id) for r in rows}  # Admins and Managers can open every request
        return Response(EnvelopeSerializer(rows, many=True, context={"assigned": assigned}).data)

    @extend_schema(responses={200: OperatorRequestSerializer})
    def retrieve(self, request, pk=None):
        env = self._envelope(request, pk)
        with tenant_context(env.client_tenant_id):
            obj = self._load(env)
            data = OperatorRequestSerializer(obj, context={"client_name": env.client_name, "intake_number": env.intake_number, "operator": True}).data
            data["my_steps"] = sorted(svc.staff_roles(request))
            data["production_route"] = _production_route(obj)
            data["quotation"] = _quotation_operator(obj)
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
            elif v["action"] == "message":
                obj = svc.operator_message(request, obj, v["message"])
            else:
                obj = svc.operator_action(request, obj, s.validated_data["action"], s.validated_data["message"])
            obj = self._load(env)  # fresh history (the earlier prefetch predates this action)
            data = OperatorRequestSerializer(obj, context={"client_name": env.client_name, "intake_number": env.intake_number, "operator": True}).data
            data["my_steps"] = sorted(svc.staff_roles(request))
            data["production_route"] = _production_route(obj)
            data["quotation"] = _quotation_operator(obj)
        return Response(data)

    @extend_schema(request=None, responses={200: dict})
    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        """Hide a request from the client's and Aries' lists without erasing anything (Aries Admin or Manager; decision of
        19 Nov 2026). Not while the order is released or in production. Restore from the Archive screen."""
        from apps.tenancy.archive import archive_request

        env = self._envelope(request, pk)
        if "admin" not in svc.staff_roles(request):
            raise DomainError("role_not_allowed", "Only an Aries Admin or Manager can archive a request.", http_status=403)
        with tenant_context(env.client_tenant_id):
            archive_request(request, self._load(env))
        return Response({"archived": True})

    # ---- manufacturing cost estimate (decision of 16 Nov 2026): OEM / conventional / 3D printing compared on cost,
    # manpower and days, for Aries to choose a route. Internal to Aries (never in the client's view of the request).
    @extend_schema(responses={200: dict})
    @action(detail=True, methods=["get", "post"], url_path="estimate")
    def estimate(self, request, pk=None):
        from apps.intelligence import estimate as est
        from apps.intelligence.models import ManufacturingEstimate
        from apps.intelligence.service import ai_status

        env = self._envelope(request, pk)
        roles = svc.staff_roles(request)
        with tenant_context(env.client_tenant_id):
            obj, part, passport = self._order_part(env)
            if request.method == "POST":
                action_ = str(request.data.get("action", ""))
                note = str(request.data.get("note", "") or "")
                if action_ in ("run", "manual", "adjust") and not roles & {"engineer", "admin"}:
                    raise DomainError("role_not_allowed", "Only an Aries Engineer, Admin or Manager can prepare an estimate.", http_status=403)
                if action_ in ("run", "manual"):
                    rev = None
                    if passport is not None:
                        rev = (passport.revisions.filter(revision_number=obj.passport_revision_number).first() if obj.passport_revision_number
                               else None) or passport.revisions.order_by("-revision_number").first()
                    est.run(request, obj, part, rev, use_ai=action_ == "run", tier=str(request.data.get("tier", "lite") or "lite"))
                elif action_ == "adjust":
                    base = ManufacturingEstimate.objects.filter(request=obj).order_by("-version").first()
                    if base is None:
                        raise DomainError("no_estimate", "There is no estimate to correct yet.", http_status=409)
                    est.adjust(request, obj, base, request.data.get("work") or {}, request.data.get("prices") or {}, note)
                elif action_ in ("quote", "withdraw_quote"):
                    from .quotations import send, withdraw

                    if "admin" not in roles:
                        raise DomainError("role_not_allowed", "Only an Aries Admin or Manager sends quotations to the client.", http_status=403)
                    if action_ == "quote":
                        send(request, obj, price=request.data.get("price"), delivery_days=request.data.get("delivery_days"),
                             valid_until=request.data.get("valid_until"), note=note)
                    else:
                        withdraw(request, obj, note)
                elif action_ == "choose":
                    if "admin" not in roles:
                        raise DomainError("role_not_allowed", "Only an Aries Admin or Manager chooses the route.", http_status=403)
                    e = ManufacturingEstimate.objects.filter(request=obj).order_by("-version").first()
                    if e is None:
                        raise DomainError("no_estimate", "Prepare an estimate first.", http_status=409)
                    est.choose(request, e, str(request.data.get("route", "")), note)
                else:
                    raise DomainError("invalid_action", "Choose run, manual, adjust, choose, quote or withdraw_quote.", http_status=400)
            versions = list(ManufacturingEstimate.objects.filter(request=obj).select_related("created_by", "chosen_by").order_by("-version")[:20])
            data = {"latest": est.serialise(versions[0]) if versions else None,
                    "versions": [{"version": v.version, "mode": v.get_mode_display(),
                                  "created_at": v.created_at, "created_by": v.created_by.email if v.created_by_id else "",
                                  "cheapest": v.result.get("cheapest", ""), "chosen_route": v.chosen_route} for v in versions],
                    "ai": {"enabled": ai_status(obj.tenant)["enabled"], "reason": ai_status(obj.tenant)["reason"]},
                    "can_prepare": bool(roles & {"engineer", "admin"}), "can_choose": "admin" in roles,
                    "quotation": _quotation_operator(obj), "status": obj.status,
                    "roles": est.ROLES, "machines": est.MACHINES, "routes": est.ROUTE_LABEL}
        return Response(data)

    # ---- the passport of the ordered part (read-only), so the engineering check, QA check and inspection can be done
    # from the request itself (decision of 16 Nov 2026). Shows the revision the client ordered; audited in the company.
    def _order_part(self, env):
        """(request, spare part, passport or None) of the order; inside the client's tenant context (project rule applies)."""
        obj = self._load(env)
        passport = DigitalPassport.objects.select_related("part", "tenant").filter(pk=obj.passport_id).first() if obj.passport_id else None
        part_id = obj.part_id or (passport.part_id if passport else None) or obj.created_part_id
        part = SparePart.objects.select_related("project", "submitted_by").filter(pk=part_id).first() if part_id else None
        if part is None:
            raise DomainError("not_found", "This request has no spare part.", http_status=404)
        if passport is None:
            passport = DigitalPassport.objects.select_related("part", "tenant").filter(part=part).first()
        return obj, part, passport

    def _blocked(self, request, env):
        from apps.tenancy import admin_workspace

        if admin_workspace.file_content_blocked_for(request.user, env.client_tenant):
            raise DomainError(*admin_workspace.BLOCKED, http_status=403)

    @staticmethod
    def _part_details(part: SparePart) -> dict:
        return {"id": str(part.pk), "part_number": part.part_number, "name": part.name, "description": part.description,
                "category": part.get_category_display(), "criticality": part.get_criticality_display(),
                "original_material": part.original_material, "dimensions": part.dimensions, "application": part.application,
                "equipment_reference": part.equipment_reference, "manufacturer": part.manufacturer,
                "project": part.project.name if part.project_id else "", "origin": part.get_origin_display(),
                "submission_kind": part.get_submission_kind_display() if part.submission_kind else "",
                "submitted_by": part.submitted_by.email if part.submitted_by_id else "", "submitted_at": part.submitted_at,
                "source_part_number": part.source_part_number, "source_passport_number": part.source_passport_number,
                "proposed_material": part.proposed_material, "material_change_reason": part.material_change_reason,
                "client_remarks": part.client_remarks, "created_at": part.created_at, "updated_at": part.updated_at}

    @extend_schema(responses={200: dict})
    @action(detail=True, methods=["get"], url_path="passport")
    def passport(self, request, pk=None):
        """The ordered part (read-only) so engineering, QA and inspection are done from the request itself (decision of
        16 Nov 2026): the spare part's details, its files and, when it has one, the passport revision the client ordered
        (R-L1 / R-L2 / R-L3), reports and 3D model. Audited in the client company."""
        from apps.passports.api import RevisionSerializer
        from apps.passports.approval_api import _evidence_files, _reports, files_of_part
        from apps.passports.operator_api import _row

        env = self._envelope(request, pk)
        with tenant_context(env.client_tenant_id):
            obj, part, p = self._order_part(env)
            base = {"part": self._part_details(part), "files": files_of_part(request, part), "has_passport": p is not None,
                    "client_id": str(env.client_tenant_id), "client_name": env.client_name}
            current = p.revisions.order_by("-revision_number").first() if p else None
            if current is None:
                record(request, "spare_part.viewed_by_aries", obj=part, tenant=env.client_tenant,
                       data={"part": part.part_number, "request": obj.reference})
                return Response({**base, "has_passport": False, "reports": [], "evidence_files": {}})
            ordered = p.revisions.select_related("approved_by").filter(revision_number=obj.passport_revision_number).first() if obj.passport_revision_number else None
            r = ordered or current
            data = {**_row(env.client_tenant, p, r), **base, "passport_state": p.publication_state,
                    "ordered_revision_number": obj.passport_revision_number, "current_revision_number": current.revision_number,
                    "submitted_by_email": r.approved_by.email if r.approved_by_id else "", "submitted_at": r.approved_at,
                    "revision": RevisionSerializer(r, context={"request": request, "approver": True}).data,
                    "evidence_files": _evidence_files(r), "reports": _reports(p)}
            record(request, "passport.viewed_by_aries", obj=p, tenant=env.client_tenant,
                   data={"passport": p.passport_number, "request": obj.reference, "revision_number": r.revision_number})
        return Response(data)

    @extend_schema(responses={(200, "application/octet-stream"): bytes})
    @action(detail=True, methods=["get"], url_path=r"passport/files/(?P<file_id>[0-9a-f-]+)")
    def passport_file(self, request, pk=None, file_id=None):
        from apps.passports.approval_api import file_response, open_file_of_part

        env = self._envelope(request, pk)
        self._blocked(request, env)
        variant = request.query_params.get("variant", "preview")
        with tenant_context(env.client_tenant_id):
            obj, part, p = self._order_part(env)
            audit = {"request": obj.reference, **({"passport": p.passport_number} if p else {})}
            key, name, ctype = open_file_of_part(request, env.client_tenant, part, file_id, variant, audit)
        return file_response(key, name, ctype, variant == "original")

    @extend_schema(responses={(200, "application/pdf"): bytes})
    @action(detail=True, methods=["get"], url_path=r"passport/reports/(?P<report_id>[0-9a-f-]+)")
    def passport_report(self, request, pk=None, report_id=None):
        from apps.passports.approval_api import stream_report

        env = self._envelope(request, pk)
        self._blocked(request, env)
        with tenant_context(env.client_tenant_id):
            obj, part, p = self._order_part(env)
            if p is None:
                raise DomainError("not_found", "This part has no digital passport.", http_status=404)
            return stream_report(request, env.client_tenant, p, report_id, {"request": obj.reference})

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


class OperatorAnalyticsView(APIView):
    """Aries staff dashboard: counts over time for the charts (aggregate counts only, no records).

    Scope: the Aries Admin (clients.view) sees every client organisation; Aries Engineers, QA and support
    (requests.handle) only what they can open themselves: requests through the queue's rule (`_visible_envelopes`), and
    spare parts, passports and approvals of their assigned clients, limited to their assigned projects where their access
    is project-limited. Registrations are counted for the Aries Admin only.

    - ``months``/``series``: per calendar month, the last 12 months oldest first: digital passports created, spare parts
      added, approvals (passport revisions approved and client part submissions accepted), company registrations
      submitted (email verified) and client requests submitted.
    - ``activity``: client requests submitted per day for the last ``weeks`` weeks (rows Monday..Sunday).
    - ``by_status``: client requests (not archived) by status, for the order-flow stages.
    - ``clients``: per client organisation in scope, its weekly activity (requests, parts and passports created), 8 weeks.
    - ``client_assets``: per client organisation in scope, its spare parts, passports and open requests.
    Counts are read inside each client's own tenant context (row-level security applies)."""

    permission_classes = [IsAuthenticated]
    MONTHS, WEEKS, CLIENT_WEEKS = 12, 12, 8

    @extend_schema(responses={200: dict})
    def get(self, request):
        from datetime import datetime, timedelta  # noqa: PLC0415

        from apps.passports.models import DigitalPassport as Passport, PassportRevision  # noqa: PLC0415
        from apps.registrations.models import CompanyRegistration  # noqa: PLC0415
        from apps.tenancy.permissions import has_capability  # noqa: PLC0415

        everything = has_capability(request, "clients.view")
        if not everything and not has_capability(request, "requests.handle"):
            raise DomainError("permission_denied", "Your role does not allow this action.", http_status=403)
        op = svc.operator_tenant()
        if request.tenant.pk != op.pk:
            raise DomainError("permission_denied", "Available in the operator organisation only.", http_status=403)
        now = timezone.localtime()
        today = now.date()
        months, y, m = [], now.year, now.month
        for _ in range(self.MONTHS):
            months.insert(0, (y, m))
            y, m = (y, m - 1) if m > 1 else (y - 1, 12)
        since = timezone.make_aware(datetime(months[0][0], months[0][1], 1))
        series = {k: dict.fromkeys(months, 0) for k in ("passports", "parts", "approvals", "registrations", "requests")}

        def add(name, stamps):
            for dt in stamps:
                k = (timezone.localtime(dt).year, timezone.localtime(dt).month)
                if k in series[name]:
                    series[name][k] += 1

        week0 = today - timedelta(days=today.weekday() + 7 * (self.WEEKS - 1))  # Monday, WEEKS weeks ago
        cweek0 = today - timedelta(days=today.weekday() + 7 * (self.CLIENT_WEEKS - 1))
        activity = [[0] * self.WEEKS for _ in range(7)]
        per_client: dict = {}

        def bump(cid, dt):
            d = timezone.localtime(dt).date()
            if d >= cweek0:
                per_client.setdefault(cid, [0] * self.CLIENT_WEEKS)[min((d - cweek0).days // 7, self.CLIENT_WEEKS - 1)] += 1

        by_status: dict = {}
        open_by_client: dict = {}
        with tenant_context(op):
            envelopes = RequestEnvelope.objects.all()
        for env in _visible_envelopes(request, op, envelopes):
            by_status[env.status] = by_status.get(env.status, 0) + 1
            if env.status in svc.OPEN:
                open_by_client[str(env.client_tenant_id)] = open_by_client.get(str(env.client_tenant_id), 0) + 1
            if env.submitted_at >= since:
                add("requests", [env.submitted_at])
            d = timezone.localtime(env.submitted_at).date()
            if d >= week0:
                activity[d.weekday()][min((d - week0).days // 7, self.WEEKS - 1)] += 1
            bump(str(env.client_tenant_id), env.submitted_at)
        if everything:
            with tenant_context(op):
                add("registrations", CompanyRegistration.objects.filter(created_at__gte=since)
                    .exclude(status=CompanyRegistration.Status.UNVERIFIED).values_list("created_at", flat=True))
            clients = Tenant.objects.filter(kind=Tenant.Kind.CLIENT)
        else:
            ids = _assigned_clients(request.user)
            clients = Tenant.objects.filter(kind=Tenant.Kind.CLIENT, pk__in=ids)
        assets = []
        for t in clients.order_by("name"):
            with tenant_context(t):
                parts_qs, passports_qs = SparePart.objects.all(), Passport.objects.all()
                revisions = PassportRevision.objects.all()
                if not everything:
                    allowed = allowed_project_ids_for(t.pk, request.user.pk)  # None: the whole company
                    if allowed is not None:
                        parts_qs = parts_qs.filter(project_id__in=allowed)
                        passports_qs = passports_qs.filter(part__project_id__in=allowed)
                        revisions = revisions.filter(passport__part__project_id__in=allowed)
                n_parts, n_passports = parts_qs.count(), passports_qs.count()
                parts = list(parts_qs.filter(created_at__gte=since).values_list("created_at", flat=True))
                passports = list(passports_qs.filter(created_at__gte=since).values_list("created_at", flat=True))
                add("parts", parts)
                add("passports", passports)
                add("approvals", revisions.filter(approved_at__gte=since).values_list("approved_at", flat=True))
                add("approvals", parts_qs.filter(review_state=SparePart.Review.ACCEPTED, reviewed_at__gte=since)
                    .values_list("reviewed_at", flat=True))
            for dt in parts + passports:
                bump(str(t.pk), dt)
            assets.append({"id": str(t.pk), "name": t.name, "counts": {"parts": n_parts, "passports": n_passports,
                                                                       "open_requests": open_by_client.get(str(t.pk), 0)}})
        return Response({
            "scope": "all" if everything else "assigned",
            "months": [f"{yy}-{mm:02d}" for yy, mm in months],
            "series": {k: list(v.values()) for k, v in series.items()},
            "activity": {"start": week0.isoformat(), "weeks": self.WEEKS, "days": activity},
            "by_status": by_status,
            "clients": {cid: weeks for cid, weeks in per_client.items() if any(a["id"] == cid for a in assets)},
            "client_assets": assets,
        })


class EstimateRatesView(APIView):
    """Aries' rates for manufacturing cost estimates: every Aries staff member who handles requests reads them; the
    Aries Admin or Manager changes them."""
    permission_classes = [HasCapability]
    capabilities = {"get": "requests.handle", "put": "requests.handle"}

    @extend_schema(responses={200: dict})
    def get(self, request):
        from apps.intelligence import estimate as est

        _operator_staff(request)
        return Response({"rates": est.get_rates(), "defaults": est.DEFAULT_RATES, "roles": est.ROLES, "machines": est.MACHINES,
                         "can_edit": "admin" in svc.staff_roles(request)})

    @extend_schema(request=dict, responses={200: dict})
    def put(self, request):
        from apps.intelligence import estimate as est

        _operator_staff(request)
        if "admin" not in svc.staff_roles(request):
            raise DomainError("role_not_allowed", "Only an Aries Admin or Manager changes the estimate rates.", http_status=403)
        return Response({"rates": est.save_rates(request, request.data.get("rates") or {})})


class OperatorArchiveView(APIView):
    """The Archive screen (Aries Admin or Manager): archived parts and requests of every company, and their restore."""
    permission_classes = [HasCapability]
    capabilities = {"get": "clients.manage", "post": "clients.manage"}

    @extend_schema(responses={200: dict})
    def get(self, request):
        from apps.tenancy.archive import archived_items

        _operator_staff(request)
        return Response(archived_items())

    @extend_schema(request=inline_serializer("ArchiveRestore", {"kind": serializers.ChoiceField(choices=["part", "request"]),
                                                                "action": serializers.ChoiceField(choices=["archive", "restore"], required=False),
                                                                "client_id": serializers.UUIDField(), "id": serializers.UUIDField()}),
                   responses={200: dict})
    def post(self, request):
        from apps.tenancy.archive import archive, restore

        _operator_staff(request)
        client = Tenant.objects.filter(pk=request.data.get("client_id"), kind=Tenant.Kind.CLIENT).first()
        if client is None:
            raise DomainError("not_found", "Company not found.", http_status=404)
        if request.data.get("action") == "archive":  # from the Aries workspace lists; default (no action) restores
            archive(request, str(request.data.get("kind", "")), client, request.data.get("id"))
            return Response({"archived": True})
        restore(request, str(request.data.get("kind", "")), client, request.data.get("id"))
        return Response({"restored": True})
