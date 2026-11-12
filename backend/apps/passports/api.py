"""Digital passport drafts and revisions.

Decided (BRD v0.4): operator creates passports (OQ-05); evidence level, publication state and
manufacturing eligibility are separate fields (PUB-001..PUB-003); approved revisions are immutable.
Submit / approve / send back follow apps.passports.approval (decision of 12 Nov 2026); manufacturing authorisation
(OQ-36) stays open and the eligibility field stays read-only.
"""
from django.db import IntegrityError, transaction
from django.db.models import Max, Q
from django.utils import timezone
from drf_spectacular.utils import extend_schema, extend_schema_field, inline_serializer
from rest_framework import serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.service import record
from apps.core.exceptions import DomainError
from apps.parts.models import SparePart
from apps.policies import seams
from apps.projects.scoping import project_allowed, restrict
from apps.tenancy.permissions import HasCapability, has_capability
from apps.tenancy.viewsets import TenantModelViewSet, TenantScopedRelatedField

from . import approval
from .confidential import aries_reader, client_content
from .content import RevisionContentSerializer, captured_level, completeness
from .models import DigitalPassport, PassportRevision
from .options import field_options
from apps.reports.api import ReportActionsMixin


class LevelCompletenessSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    done = serializers.IntegerField()
    missing = serializers.ListField(child=serializers.CharField())
    complete = serializers.BooleanField()


class CompletenessSerializer(serializers.Serializer):
    rl1 = LevelCompletenessSerializer()
    rl2 = LevelCompletenessSerializer()
    rl3 = LevelCompletenessSerializer()


NOTES_CAPABILITY = "passports.view_engineering_notes"


def _has_notes(revision) -> bool:
    return bool(str((revision.content or {}).get("notes") or "").strip())


class RevisionSerializer(serializers.ModelSerializer):
    """Revision content. The engineering notes (`content.notes`) are returned only to roles with
    passports.view_engineering_notes; for other roles they are omitted from every response (fail closed when no
    request is in the context) and only `engineering_review_pending` tells that notes exist."""

    content = RevisionContentSerializer(required=False)
    editable = serializers.SerializerMethodField()
    completeness = serializers.SerializerMethodField()
    created_by_email = serializers.SerializerMethodField()
    updated_by_email = serializers.SerializerMethodField()
    submitted_by_email = serializers.SerializerMethodField()
    approved_by_email = serializers.SerializerMethodField()
    notes_restricted = serializers.SerializerMethodField(
        help_text="True when this revision holds engineering notes that your role may not read; they are omitted from content.")
    engineering_review_pending = serializers.SerializerMethodField(
        help_text="True when engineering notes are recorded for this revision. No engineer verification or resolution "
                  "status is stored, so the review is reported as pending. The notes themselves are never assessed.")

    class Meta:
        model = PassportRevision
        fields = ["id", "revision_number", "status", "content", "change_summary", "editable", "completeness",
                  "notes_restricted", "engineering_review_pending",
                  "created_by_email", "updated_by_email", "submitted_by_email", "approved_by_email", "review_note",
                  "submitted_at", "approved_at", "created_at", "updated_at"]
        read_only_fields = ["id", "revision_number", "status", "editable", "completeness", "created_by_email",
                            "updated_by_email", "submitted_by_email", "approved_by_email", "review_note",
                            "submitted_at", "approved_at", "created_at", "updated_at"]

    def _may_read_notes(self) -> bool:
        request = self.context.get("request")
        return request is not None and has_capability(request, NOTES_CAPABILITY)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not self._may_read_notes() and isinstance(data.get("content"), dict):
            data["content"].pop("notes", None)
        if isinstance(data.get("content"), dict) and not self.context.get("approver") and not aries_reader(self.context.get("request")):
            data["content"] = client_content(data["content"])  # D-18: Aries manufacturing specification stays internal
        return data

    def get_notes_restricted(self, obj) -> bool:
        return _has_notes(obj) and not self._may_read_notes()

    def get_engineering_review_pending(self, obj) -> bool:
        return _has_notes(obj)

    def get_editable(self, obj) -> bool:
        return obj.status == PassportRevision.Status.DRAFT

    @extend_schema_field(CompletenessSerializer)
    def get_completeness(self, obj):
        return completeness(obj.content)

    def get_created_by_email(self, obj) -> str:
        return obj.created_by.email if obj.created_by_id else ""

    def get_updated_by_email(self, obj) -> str:
        return obj.updated_by.email if obj.updated_by_id else ""

    def get_submitted_by_email(self, obj) -> str:
        return obj.submitted_by.email if obj.submitted_by_id else ""

    def get_approved_by_email(self, obj) -> str:
        return obj.approved_by.email if obj.approved_by_id else ""


class PartSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    part_number = serializers.CharField()
    name = serializers.CharField()
    category = serializers.CharField()


class PolicyStatusSerializer(serializers.Serializer):
    decision = serializers.CharField()
    enabled = serializers.BooleanField()
    reason = serializers.CharField()


class PassportSerializer(serializers.ModelSerializer):
    part_summary = serializers.SerializerMethodField()
    current_revision = serializers.SerializerMethodField()
    policy = serializers.SerializerMethodField()
    initial_content = RevisionContentSerializer(write_only=True, required=False)

    class Meta:
        model = DigitalPassport
        fields = ["id", "part", "part_summary", "passport_number", "title", "publication_state", "evidence_level",
                  "manufacturing_eligibility", "data_captured", "current_revision", "policy", "initial_content", "created_at", "updated_at"]
        read_only_fields = ["id", "publication_state", "evidence_level", "manufacturing_eligibility", "data_captured",
                            "current_revision", "policy", "created_at", "updated_at"]
        extra_kwargs = {"passport_number": {"required": False, "allow_blank": True,
                                            "help_text": "Optional. A provisional number is generated if blank (numbering scheme OQ-14 is open)."},
                        "title": {"required": False, "allow_blank": True, "help_text": "Defaults to the spare-part name."}}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        TenantScopedRelatedField.limit(self, "part", SparePart)
        if self.instance is not None and not isinstance(self.instance, (list, tuple)) and "part" in self.fields:
            self.fields["part"].read_only = True

    @extend_schema_field(PartSummarySerializer)
    def get_part_summary(self, obj):
        p = obj.part
        return {"id": str(p.pk), "part_number": p.part_number, "name": p.name, "category": p.category}

    @extend_schema_field(RevisionSerializer(allow_null=True))
    def get_current_revision(self, obj):
        rev = obj.revisions.order_by("-revision_number").first()
        return RevisionSerializer(rev, context=self.context).data if rev else None

    @extend_schema_field(serializers.DictField(child=PolicyStatusSerializer()))
    def get_policy(self, obj):
        # Shown to UIs so that gated actions are rendered as disabled with the reason.
        return seams.status()

    def validate_part(self, part):
        if DigitalPassport.objects.filter(part=part).exists():
            raise serializers.ValidationError("This spare part already has a digital passport.")
        return part


def refresh_data_captured(passport, content) -> None:
    """Keep the stored data-capture level in step with the current revision (catalog filter). It never touches
    evidence_level, publication_state or manufacturing_eligibility."""
    level = captured_level(content or {})
    if passport.data_captured != level:
        passport.data_captured = level
        passport.save(update_fields=["data_captured", "updated_at"])


def next_passport_number(tenant) -> str:
    year = timezone.now().year
    prefix = f"DP-{year}-"
    count = DigitalPassport.objects.filter(tenant=tenant, passport_number__startswith=prefix).count()
    return f"{prefix}{count + 1:05d}"


class PassportViewSet(ReportActionsMixin, TenantModelViewSet):
    model = DigitalPassport
    serializer_class = PassportSerializer
    audit_type = "passport"
    capabilities = {"list": "passports.view", "retrieve": "passports.view", "create": "passports.edit_draft",
                    "update": "passports.edit_draft", "partial_update": "passports.edit_draft",
                    "revisions": "passports.view", "revision_detail": "passports.view",
                    "submit_revision": "passports.edit_draft", "approve_revision": "passports.approve",
                    "return_revision": "passports.approve",
                    # CN-005 reports: variant rules are checked in apps.reports.api / services (server-side)
                    "reports": "passports.view", "report_pdf": "passports.view", "report_page": "passports.view", "report_withdraw": "reports.withdraw",
                    "report_preview": "passports.view"}

    def get_queryset(self):
        qs = restrict(self.request, super().get_queryset().select_related("part"), "part__project", own="part__submitted_by")
        q = self.request.query_params.get("search", "").strip()
        if q:
            qs = qs.filter(Q(passport_number__icontains=q) | Q(title__icontains=q) | Q(part__part_number__icontains=q))
        return qs

    def get_permissions(self):
        # Writing revisions needs edit rights; reading needs view rights.
        if self.action == "revisions" and self.request.method == "POST":
            self.capabilities = {**self.capabilities, "revisions": "passports.edit_draft"}
        if self.action == "revision_detail" and self.request.method in ("PATCH", "PUT"):
            self.capabilities = {**self.capabilities, "revision_detail": "passports.edit_draft"}
        return super().get_permissions()

    def perform_create(self, serializer):
        tenant, user = self.request.tenant, self.request.user
        initial = serializer.validated_data.pop("initial_content", {}) or {}
        self._check_notes_write(self.request, initial)
        part = serializer.validated_data["part"]
        if not project_allowed(self.request, part.project_id):
            raise DomainError("not_found", "Spare part not found.", http_status=status.HTTP_404_NOT_FOUND)
        if part.review_state in (*part.OPEN_REVIEW, part.Review.DECLINED):
            # A client submission enters the engineering workflow only once an Aries Engineer accepts it.
            raise DomainError("part_not_accepted", "Accept this client submission into the engineering workflow before "
                              "creating its digital passport.")
        number =(serializer.validated_data.pop("passport_number", "") or "").strip()
        title = serializer.validated_data.get("title") or serializer.validated_data["part"].name
        for attempt in range(3):
            try:
                with transaction.atomic():
                    passport = serializer.save(tenant=tenant, created_by=user, title=title,
                                               passport_number=number or next_passport_number(tenant))
                    PassportRevision.objects.create(tenant=tenant, created_by=user, passport=passport,
                                                    revision_number=1, content=initial, change_summary="Initial draft")
                    refresh_data_captured(passport, initial)
                break
            except IntegrityError:
                if number or attempt == 2:
                    raise DomainError("duplicate_passport_number", "This passport number is already used.")
        record(self.request, "passport.created", obj=passport, data={"passport_number": passport.passport_number})

    @staticmethod
    def _check_notes_write(request, content):
        """Only roles that may read the engineering notes may write them (a blind write could overwrite notes)."""
        if "notes" in (content or {}) and not has_capability(request, NOTES_CAPABILITY):
            raise DomainError("permission_denied", "Your role cannot edit engineering notes.", http_status=403)

    def _revision(self, passport, rev):
        try:
            return passport.revisions.get(revision_number=int(rev))
        except (PassportRevision.DoesNotExist, ValueError):
            raise DomainError("not_found", "Revision not found.", http_status=status.HTTP_404_NOT_FOUND)

    @extend_schema(request=RevisionSerializer, responses={200: RevisionSerializer(many=True), 201: RevisionSerializer})
    @action(detail=True, methods=["get", "post"])
    def revisions(self, request, pk=None):
        passport = self.get_object()
        if request.method == "GET":
            return Response(RevisionSerializer(passport.revisions.order_by("-revision_number"), many=True, context={"request": request}).data)
        if passport.revisions.filter(status=PassportRevision.Status.DRAFT).exists():
            raise DomainError("draft_exists", "A draft revision already exists. Edit it instead of creating another.")
        if passport.revisions.filter(status=PassportRevision.Status.SUBMITTED).exists():
            raise DomainError("revision_awaiting_approval", "A revision is waiting for approval. Approve it or send it back first.")
        latest = passport.revisions.order_by("-revision_number").first()
        number = (passport.revisions.aggregate(m=Max("revision_number"))["m"] or 0) + 1
        rev = PassportRevision.objects.create(
            tenant=request.tenant, created_by=request.user, passport=passport, revision_number=number,
            content=dict(latest.content) if latest else {}, change_summary=str(request.data.get("change_summary", ""))[:500])
        if passport.revisions.filter(status=PassportRevision.Status.APPROVED).exists():
            passport.publication_state = DigitalPassport.PublicationState.REVISION_IN_PROGRESS
            passport.save(update_fields=["publication_state", "updated_at"])
        record(request, "passport.revision_created", obj=rev, data={"revision_number": number})
        return Response(RevisionSerializer(rev, context={"request": request}).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=RevisionSerializer, responses={200: RevisionSerializer})
    @action(detail=True, methods=["get", "patch"], url_path=r"revisions/(?P<rev>\d+)")
    def revision_detail(self, request, pk=None, rev=None):
        passport = self.get_object()
        revision = self._revision(passport, rev)
        if request.method == "GET":
            return Response(RevisionSerializer(revision, context={"request": request}).data)
        if revision.status != PassportRevision.Status.DRAFT:
            raise DomainError("revision_not_editable", "Only draft revisions can be edited. Approved revisions are immutable.")
        s = RevisionSerializer(revision, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        data = s.validated_data
        changed = []
        if "content" in data:
            # Each level is saved by its own form: merge per level instead of replacing the whole content.
            incoming = data["content"]
            self._check_notes_write(request, incoming)
            self._check_evidence(passport, incoming.get("rl3"))
            revision.content = {**(revision.content or {}), **incoming}
            changed = sorted(f"content.{k}" for k in incoming)
        if "change_summary" in data:
            revision.change_summary = data["change_summary"]
            changed.append("change_summary")
        revision.updated_by = request.user
        revision.save(update_fields=["content", "change_summary", "updated_by", "updated_at"])
        if revision.revision_number == passport.revisions.aggregate(m=Max("revision_number"))["m"]:
            refresh_data_captured(passport, revision.content)
        record(request, "passport.revision_updated", obj=revision, data={"fields": changed})
        return Response(RevisionSerializer(revision, context={"request": request}).data)

    @staticmethod
    def _check_evidence(passport, rl3):
        """R-L3 evidence may only point at files of this passport (tenant scope is also enforced by RLS)."""
        if not rl3 or not rl3.get("evidence"):
            return
        from apps.files.models import EngineeringFile

        ids = {v for v in rl3["evidence"].values() if v}
        found = {str(i) for i in EngineeringFile.objects.filter(pk__in=ids, passport=passport).values_list("pk", flat=True)}
        missing = sorted(k for k, v in rl3["evidence"].items() if v and v not in found)
        if missing:
            raise DomainError("evidence_file_invalid", "Evidence must be a file attached to this passport.",
                              details={"evidence": missing}, http_status=400)

    @extend_schema(request=None, responses={200: RevisionSerializer})
    @action(detail=True, methods=["post"], url_path=r"revisions/(?P<rev>\d+)/submit")
    def submit_revision(self, request, pk=None, rev=None):
        passport = self.get_object()
        revision = approval.submit(request, passport, self._revision(passport, rev))
        return Response(RevisionSerializer(revision, context={"request": request}).data)

    @extend_schema(request=None, responses={200: RevisionSerializer})
    @action(detail=True, methods=["post"], url_path=r"revisions/(?P<rev>\d+)/approve")
    def approve_revision(self, request, pk=None, rev=None):
        passport = self.get_object()
        revision = approval.approve(request, passport, self._revision(passport, rev))
        return Response(RevisionSerializer(revision, context={"request": request}).data)

    @extend_schema(request=inline_serializer("RevisionReturnInput", {"note": serializers.CharField()}), responses={200: RevisionSerializer})
    @action(detail=True, methods=["post"], url_path=r"revisions/(?P<rev>\d+)/return")
    def return_revision(self, request, pk=None, rev=None):
        passport = self.get_object()
        revision = approval.send_back(request, passport, self._revision(passport, rev), str(request.data.get("note", "")))
        return Response(RevisionSerializer(revision, context={"request": request}).data)


class FieldOptionSerializer(serializers.Serializer):
    value = serializers.CharField()
    group = serializers.CharField(required=False)


class FieldOptionsSerializer(serializers.Serializer):
    version = serializers.CharField()
    provisional = serializers.BooleanField()
    decision = serializers.CharField()
    lists = serializers.DictField(child=FieldOptionSerializer(many=True))
    units = serializers.DictField(child=serializers.ListField(child=serializers.CharField()))


class PassportFieldOptionsView(APIView):
    """Provisional controlled value lists for the R-L1/R-L2 forms (OQ-16). Values are suggestions with Other / specify."""

    permission_classes = [HasCapability]
    capabilities = {"get": "passports.view"}

    @extend_schema(responses=FieldOptionsSerializer)
    def get(self, request):
        return Response(field_options())
