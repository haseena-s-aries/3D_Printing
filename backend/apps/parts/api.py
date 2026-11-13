"""Spare parts and the digital inventory catalog (BR-010, BR-011).

The list is the catalog: search, filters, sorting and server-side pagination, all inside the caller's tenant (the
queryset is tenant-scoped and every table is under forced RLS). Per-part summaries (documents, 3D, thumbnail,
revision, data captured, last activity) are computed in the same query.
"""
from django.db.models import Count, Exists, OuterRef, Q, Subquery, UUIDField
from django.db.models.functions import Coalesce, Greatest
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field, extend_schema_view, inline_serializer
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.audit.service import record
from apps.core.exceptions import DomainError

from apps.files.models import Derivative, EngineeringFile, FileVersion
from apps.passports.models import DigitalPassport, PassportRevision
from apps.projects.models import Project
from apps.projects.scoping import project_allowed, restrict
from apps.tenancy.permissions import has_capability
from apps.tenancy.viewsets import TenantModelViewSet, TenantScopedRelatedField

from . import submissions
from apps.imports.mapping import clean_manufacturer
from .models import SparePart, SparePartReviewEvent

ORDERING = {"part_number": "part_number", "-part_number": "-part_number", "name": "name", "-name": "-name",
            "last_activity": "last_activity", "-last_activity": "-last_activity", "created": "created_at", "-created": "-created_at"}
DATA_LEVELS = {"rl1": ["rl1", "rl2", "rl3"], "rl2": ["rl2", "rl3"], "rl3": ["rl3"]}


def stage_q(stage: str) -> Q | None:
    """Inventory stages, derived from two separate stored dimensions (never written by this filter):
    review_state (client submissions) and the passport's publication_state.
    - review: client-submitted or cloned part awaiting Aries review (Pending / Corrections requested)
    - in_digitisation: not published; Aries-maintained or accepted into the engineering workflow
    - published: passport officially published
    - declined: rejected submissions (listed under All only)"""
    published = Q(passport__publication_state=DigitalPassport.PublicationState.PUBLISHED)
    return {
        "published": published,
        "in_digitisation": ~published & Q(review_state__in=[SparePart.Review.NOT_REQUIRED, SparePart.Review.ACCEPTED]),
        "review": Q(review_state__in=SparePart.OPEN_REVIEW),
        "declined": Q(review_state=SparePart.Review.DECLINED),
    }.get(stage)


STAGES = ["review", "in_digitisation", "published", "declined"]


INVENTORY_FIELDS = ["plant", "functional_location", "equipment_tag", "customer_abc_class", "manufacturer_reference", "oem_part_number"]


class DocumentCountsSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    step = serializers.IntegerField()
    dwg = serializers.IntegerField()
    pdf = serializers.IntegerField()
    image = serializers.IntegerField()


class ThumbnailRefSerializer(serializers.Serializer):
    file = serializers.UUIDField()
    version = serializers.IntegerField()


class RevisionRefSerializer(serializers.Serializer):
    number = serializers.IntegerField()
    status = serializers.CharField()


class ProvenanceEntrySerializer(serializers.Serializer):
    source = serializers.ChoiceField(choices=["client", "aries", "inherited"],
                                     help_text="inherited: copied unchanged from the source part of a clone (reference only)")
    entered_by = serializers.CharField(allow_blank=True)
    entered_at = serializers.DateTimeField(allow_null=True)
    verified_by = serializers.CharField(allow_null=True)
    verified_at = serializers.DateTimeField(allow_null=True)


class CloneChangeSerializer(serializers.Serializer):
    field = serializers.CharField()
    original = serializers.CharField(allow_blank=True)
    clone = serializers.CharField(allow_blank=True)
    changed = serializers.BooleanField()


class ReviewEventSerializer(serializers.ModelSerializer):
    author = serializers.SerializerMethodField()

    class Meta:
        model = SparePartReviewEvent
        fields = ["id", "action", "note", "side", "author", "created_at"]

    def get_author(self, obj) -> str:
        return submissions.display_name(obj.created_by)


class CloneInputSerializer(serializers.Serializer):
    part_number = serializers.CharField(max_length=80)
    name = serializers.CharField(max_length=200, required=False)
    equipment_reference = serializers.CharField(max_length=120, required=False, allow_blank=True)
    manufacturer = serializers.CharField(max_length=200, required=False, allow_blank=True)
    application = serializers.CharField(max_length=200, required=False, allow_blank=True)
    dimensions = serializers.CharField(max_length=120, required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    proposed_material = serializers.CharField(max_length=120, required=False, allow_blank=True)
    material_change_reason = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    client_remarks = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    project = serializers.UUIDField(required=False, allow_null=True, help_text=(
        "Project of the clone (post-UAT D-21); default: the source part's project"))


class PartFieldValuesSerializer(serializers.Serializer):
    equipment_reference = serializers.ListField(child=serializers.CharField())
    manufacturer = serializers.ListField(child=serializers.CharField())
    application = serializers.ListField(child=serializers.CharField())
    original_material = serializers.ListField(child=serializers.CharField())


class SparePartSerializer(serializers.ModelSerializer):
    clone_changes = serializers.SerializerMethodField(help_text="Clones only: original (at clone time) versus clone, per field.")
    part_number = serializers.CharField(max_length=80, allow_blank=True,
                                        help_text="Required, except in a client submission that marks it unknown "
                                                  "(a provisional TBC- number is assigned; OQ-14).")
    unknown_fields = serializers.ListField(child=serializers.ChoiceField(choices=submissions.UNKNOWN_ALLOWED), required=False,
                                           help_text="Fields the submitter marked Unknown / not available.")
    field_provenance = serializers.DictField(child=ProvenanceEntrySerializer(), read_only=True,
                                             help_text="Who entered each value (client or Aries) and whether Aries verified it.")
    submitted_by_name = serializers.SerializerMethodField()
    reviewed_by_name = serializers.SerializerMethodField()
    passport_id = serializers.SerializerMethodField()
    passport_number = serializers.SerializerMethodField()
    publication_state = serializers.SerializerMethodField()
    evidence_level = serializers.SerializerMethodField()
    manufacturing_eligibility = serializers.SerializerMethodField(
        help_text="Stored eligibility state of the passport (read-only; transitions gated, OQ-36). Null without a passport.")
    data_captured = serializers.SerializerMethodField(help_text="Data completeness (guidance only): none, rl1, rl2 or rl3.")
    revision = serializers.SerializerMethodField()
    project_name = serializers.SerializerMethodField()
    documents = serializers.SerializerMethodField()
    has_3d = serializers.SerializerMethodField()
    in_lifecycle = serializers.BooleanField(read_only=True, help_text=(
        "True when the part is in the engineering lifecycle (passport, intelligence, feasibility, cost, recommendation, review, "
        "sharing) whatever its origin; false for client submissions awaiting Aries review, declined or obsolete parts."))
    thumbnail = serializers.SerializerMethodField()
    last_activity = serializers.SerializerMethodField()

    class Meta:
        model = SparePart
        fields = ["id", "project", "project_name", "part_number", "name", "description", "category", "criticality",
                  "original_material", "dimensions", "application", "equipment_reference", "manufacturer", "status",
                  "origin", "review_state", "submission_kind", "submitted_by", "submitted_by_name", "submitted_at", "reviewed_by_name",
                  "reviewed_at", "review_note", "unknown_fields", "field_provenance", "aries_completion_requested", "submission_revision",
                  "source_part", "source_part_number", "source_passport_number", "source_revision_number", "source_snapshot",
                  "proposed_material", "material_change_reason", "client_remarks", "clone_changes",
                  "plant", "functional_location", "equipment_tag", "customer_abc_class", "manufacturer_reference", "oem_part_number",
                  "manufacturer_normalized", "import_record",
                  "passport_id", "passport_number", "publication_state", "evidence_level", "manufacturing_eligibility",
                  "data_captured", "revision",
                  "documents", "has_3d", "in_lifecycle", "thumbnail", "last_activity", "created_at", "updated_at"]
        read_only_fields = ["id", "origin", "review_state", "submission_kind", "submitted_by", "submitted_at", "reviewed_at", "review_note",
                            "submission_revision",
                            "source_part", "source_part_number", "source_passport_number", "source_revision_number",
                            "source_snapshot", "manufacturer_normalized", "import_record", "created_at", "updated_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        TenantScopedRelatedField.limit(self, "project", Project)

    def validate_project(self, project):
        # Project-limited Aries staff may only register parts in their assigned projects (CN-002 D4).
        request = self.context.get("request")
        if request is not None and not project_allowed(request, project.pk if project else None):
            raise serializers.ValidationError("You are not assigned to this project.")
        return project
    @staticmethod
    def _passport(obj):
        try:
            return obj.passport
        except DigitalPassport.DoesNotExist:
            return None

    @extend_schema_field(serializers.UUIDField(allow_null=True))
    def get_passport_id(self, obj):
        p = self._passport(obj)
        return str(p.pk) if p else None

    def get_passport_number(self, obj) -> str | None:
        p = self._passport(obj)
        return p.passport_number if p else None

    def get_publication_state(self, obj) -> str | None:
        p = self._passport(obj)
        return p.publication_state if p else None

    def get_evidence_level(self, obj) -> str | None:
        p = self._passport(obj)
        return p.evidence_level if p else None

    def get_manufacturing_eligibility(self, obj) -> str | None:
        p = self._passport(obj)
        return p.manufacturing_eligibility if p else None

    def get_data_captured(self, obj) -> str | None:
        p = self._passport(obj)
        return p.data_captured if p else None

    @extend_schema_field(RevisionRefSerializer(allow_null=True))
    def get_revision(self, obj):
        number = getattr(obj, "rev_number", None)
        return {"number": number, "status": obj.rev_status} if number else None

    def get_project_name(self, obj) -> str | None:
        return obj.project.name if obj.project_id else None

    @extend_schema_field(DocumentCountsSerializer)
    def get_documents(self, obj):
        return {k: getattr(obj, f"doc_{k}", 0) or 0 for k in ("total", "step", "dwg", "pdf", "image")}

    def get_has_3d(self, obj) -> bool:
        return bool(getattr(obj, "has_3d", False))

    @extend_schema_field(ThumbnailRefSerializer(allow_null=True))
    def get_thumbnail(self, obj):
        from apps.tenancy import admin_workspace

        request = self.context.get("request")
        if request is not None and admin_workspace.file_content_blocked(getattr(request, "membership", None)):
            return None  # photo content closed to the Aries Admin in this company (no decision documented)
        f = getattr(obj, "thumb_file", None)
        return {"file": str(f), "version": obj.thumb_version} if f else None

    @extend_schema_field(serializers.DateTimeField())
    def get_last_activity(self, obj):
        return getattr(obj, "last_activity", None) or obj.updated_at

    @extend_schema_field(CloneChangeSerializer(many=True))
    def get_clone_changes(self, obj):
        return submissions.clone_changes(obj) if obj.source_part_id else []

    def get_submitted_by_name(self, obj) -> str:
        return submissions.display_name(obj.submitted_by) if obj.submitted_by_id else ""

    def get_reviewed_by_name(self, obj) -> str:
        return submissions.display_name(obj.reviewed_by) if obj.reviewed_by_id else ""

    def validate(self, attrs):
        client = self.context.get("client_submission", False)
        inst = self.instance
        if client:  # CN-007 customer inventory identifiers are maintained by Aries or by an authorised import
            for f in INVENTORY_FIELDS:
                attrs.pop(f, None)
        if "manufacturer" in attrs:
            attrs["manufacturer_normalized"] = clean_manufacturer(attrs["manufacturer"])
        if inst is not None and inst.source_part_id:
            proposed = attrs.get("proposed_material", inst.proposed_material)
            reason = attrs.get("material_change_reason", inst.material_change_reason)
            original = (inst.source_snapshot or {}).get("original_material")
            if proposed and not submissions.same(proposed, original) and not str(reason or "").strip():
                raise serializers.ValidationError({"material_change_reason": "Required when a new material is proposed."})
        if client:
            locked = sorted(set(attrs) & set(submissions.ARIES_ONLY_FIELDS))
            if locked:
                raise DomainError("aries_controlled_field", "Criticality and status are set by Aries Engineering.",
                                  details={"fields": locked}, http_status=403)
        unknown = attrs.get("unknown_fields", self.instance.unknown_fields if self.instance else [])
        number = attrs.get("part_number", self.instance.part_number if self.instance else "")
        if not number:
            if client and "part_number" in unknown:
                if self.instance is None:
                    attrs["part_number"] = submissions.provisional_number(self.context.get("tenant"))
                else:
                    attrs.pop("part_number", None)  # keep the provisional number already assigned
            else:
                raise serializers.ValidationError({"part_number": "Enter the part number, or mark it as unknown."})
        return attrs

    def validate_part_number(self, value):
        value = value.strip()
        if not value:
            return value
        qs = SparePart.objects.filter(tenant=self.context.get("tenant"), part_number__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("This part number already exists in your organisation.")
        return value


def client_role(request) -> bool:
    m = getattr(request, "membership", None)
    return m is not None and not m.role.startswith("operator_")


def with_summaries(qs, client: bool = False):
    """Annotate document counts, 3D availability, thumbnail, current revision and last activity per part. For client roles
    only documents released to the client are counted (post-UAT D-16): no metadata about Aries-only files."""
    seen = {"client_visible": True} if client else {}
    fv_seen = {"file_version__file__client_visible": True} if client else {}

    def files(**f):  # correlated count, not a join + GROUP BY (SQL Server cannot group by the subqueries below)
        return Coalesce(Subquery(EngineeringFile.objects.filter(part=OuterRef("pk"), **seen, **f).order_by()
                                 .values("part").annotate(n=Count("pk")).values("n")[:1]), 0)
    by_kind = {k: files(kind=k) for k in ("step", "dwg", "pdf", "image")}
    revisions = PassportRevision.objects.filter(passport__part=OuterRef("pk")).order_by("-revision_number")
    thumbs = Derivative.objects.filter(kind=Derivative.Kind.THUMB, file_version__file__part=OuterRef("pk"), **fv_seen).order_by("-created_at")
    last_file = FileVersion.objects.filter(file__part=OuterRef("pk"), **({"file__client_visible": True} if client else {})
                                           ).order_by("-created_at").values("created_at")[:1]
    last_rev = PassportRevision.objects.filter(passport__part=OuterRef("pk")).order_by("-updated_at").values("updated_at")[:1]
    return qs.annotate(
        doc_total=files(), **{f"doc_{k}": v for k, v in by_kind.items()},
        has_3d=Exists(Derivative.objects.filter(kind=Derivative.Kind.GLB, file_version__file__part=OuterRef("pk"), **fv_seen)),
        thumb_file=Subquery(thumbs.values("file_version__file_id")[:1], output_field=UUIDField()),  # a UUID on every database
        thumb_version=Subquery(thumbs.values("file_version__version_number")[:1]),
        rev_number=Subquery(revisions.values("revision_number")[:1]),
        rev_status=Subquery(revisions.values("status")[:1]),
        # PostgreSQL GREATEST ignores NULLs (parts without passport or files)
        last_activity=Greatest("updated_at", "passport__updated_at", Subquery(last_rev), Subquery(last_file)),
    )


CATALOG_PARAMS = [
    OpenApiParameter("search", str, description="Part number, name, description or passport number"),
    OpenApiParameter("category", str), OpenApiParameter("criticality", str), OpenApiParameter("status", str),
    OpenApiParameter("project", str, description="Project id"),
    OpenApiParameter("evidence_level", str, description="Official evidence level: none, R-L1, R-L2, R-L3 (transitions gated, OQ-35)"),
    OpenApiParameter("data_level", str, description="Data captured at least to: rl1, rl2, rl3; or none (guidance only)"),
    OpenApiParameter("eligibility", str, description="Manufacturing eligibility: not_eligible (includes parts without a passport), "
                     "eligible_subject_to_authorisation, eligible, suspended (MOB-010; read-only state, OQ-36)"),
    OpenApiParameter("catalog", str, enum=STAGES,
                     description="Inventory stage (see stage_q): review = awaiting Aries review; in_digitisation = not published, "
                                 "Aries-maintained or accepted; published; declined. Omit for all parts."),
    OpenApiParameter("has_passport", bool), OpenApiParameter("has_3d", bool),
    OpenApiParameter("review_state", str, description="not_required, pending_review, info_requested, accepted, declined; "
                     "'open' = pending_review or info_requested"),
    OpenApiParameter("origin", str, enum=["aries", "client"]),
    OpenApiParameter("source_part", str, description="Clones of this part"),
    OpenApiParameter("ordering", str, enum=list(ORDERING), description="Default -last_activity"),
]


@extend_schema_view(list=extend_schema(parameters=CATALOG_PARAMS))
class SparePartViewSet(TenantModelViewSet):
    model = SparePart
    serializer_class = SparePartSerializer
    audit_type = "spare_part"
    capabilities = {"list": "parts.view", "retrieve": "parts.view", "create": "parts.manage",
                    "update": "parts.manage", "partial_update": "parts.manage",
                    "review": "parts.review", "resubmit": "parts.submit", "clone": "parts.submit", "history": "parts.view",
                    "field_values": "parts.view", "stage_counts": "parts.view"}

    def _client_submission(self) -> bool:
        """Clients write through the submission rules; Aries Engineers through engineering master-data rules."""
        return not has_capability(self.request, "parts.manage") and has_capability(self.request, "parts.submit")

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update") and self._client_submission():
            self.capabilities = {**self.capabilities, self.action: "parts.submit"}
        return super().get_permissions()

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["client_submission"] = getattr(self.request, "membership", None) is not None and self._client_submission()
        return ctx

    @staticmethod
    def _filled(validated):
        return [k for k, v in validated.items() if k in submissions.PROVENANCE_FIELDS and v not in ("", None)]

    def perform_create(self, serializer):
        v = serializer.validated_data
        if not self._client_submission():
            obj = serializer.save(tenant=self.request.tenant, created_by=self.request.user)
            submissions.stamp(obj, self._filled(v), source="aries", user=self.request.user, verified=True)
            obj.save(update_fields=["field_provenance"])
            record(self.request, "spare_part.created", obj=obj)
            return
        kind = submissions.submission_kind_for(self.request.membership)
        obj = serializer.save(tenant=self.request.tenant, created_by=self.request.user, origin=SparePart.Origin.CLIENT,
                              review_state=SparePart.Review.PENDING, submission_kind=kind, status=SparePart.Status.DRAFT,
                              submitted_by=self.request.user, submitted_at=timezone.now())
        submissions.stamp(obj, self._filled(v), source="client", user=self.request.user)
        obj.save(update_fields=["field_provenance"])
        record(self.request, "spare_part.submitted", obj=obj, data={"kind": kind, "unknown_fields": obj.unknown_fields})
        submissions.log(obj, SparePartReviewEvent.Action.SUBMITTED, self.request.user, side="client")
        submissions.notify_reviewers(obj, "completion" if obj.aries_completion_requested else "submitted", body=obj.description[:300])

    def perform_update(self, serializer):
        client = self._client_submission()
        if client:
            submissions.check_client_may_edit(self.request, serializer.instance)
        before = {f: getattr(serializer.instance, f) for f in submissions.PROVENANCE_FIELDS}
        changed = sorted(serializer.validated_data.keys())
        obj = serializer.save()
        moved = [f for f in submissions.PROVENANCE_FIELDS if getattr(obj, f) != before[f]]
        if moved:
            submissions.stamp(obj, moved, source="client" if client else "aries", user=self.request.user, verified=not client)
            obj.save(update_fields=["field_provenance"])
        record(self.request, "spare_part.updated", obj=obj, data={"fields": changed, "client_submission": client})

    @extend_schema(request=inline_serializer("PartReview", {
        "decision": serializers.ChoiceField(choices=["request_info", "accept", "decline", "verify"]),
        "message": serializers.CharField(required=False, allow_blank=True),
        "project": serializers.UUIDField(required=False, allow_null=True),
        "verified_fields": serializers.ListField(child=serializers.ChoiceField(choices=submissions.PROVENANCE_FIELDS), required=False),
    }), responses=SparePartSerializer)
    @action(detail=True, methods=["post"])
    def review(self, request, pk=None):
        """Aries decision on a client submission: request_info = send back (opens the next revision), accept = approve
        (creates the passport draft; a clone's manufacturing request is sent automatically), decline, or verify
        client-supplied values later. Publication and manufacturing release are not changed."""
        part = self.get_object()
        decision = request.data.get("decision")
        message = str(request.data.get("message") or "")
        fields = request.data.get("verified_fields") or []
        if not isinstance(fields, list) or not set(fields) <= set(submissions.PROVENANCE_FIELDS):
            raise DomainError("invalid_fields", "Unknown field in verified_fields.", http_status=400)
        if decision == "request_info":
            submissions.request_info(request, part, message)
        elif decision == "accept":
            project = None
            if request.data.get("project"):
                project = Project.objects.filter(tenant=request.tenant, pk=request.data["project"]).first()
                if project is None or not project_allowed(request, project.pk):
                    raise DomainError("invalid_project", "Choose one of your assigned projects of this company.", http_status=400)
            submissions.accept(request, part, project=project, verified_fields=fields, note=message)
        elif decision == "decline":
            submissions.decline(request, part, message)
        elif decision == "verify":
            submissions.verify_fields(request, part, fields)
        else:
            raise DomainError("invalid_decision", "decision must be request_info, accept, decline or verify.", http_status=400)
        return Response(self.get_serializer(self.get_queryset().get(pk=part.pk)).data)

    @extend_schema(request=CloneInputSerializer, responses={201: SparePartSerializer})
    @action(detail=True, methods=["post"])
    def clone(self, request, pk=None):
        """Client: clone an accepted part of the own organisation into a new part linked to it (BR-033), e.g. with a
        proposed new material. The source part, its files and passport are not changed; the clone is Pending Aries review."""
        source = self.get_object()  # tenant- and project-scoped: another company's part is 404
        data = CloneInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        part = submissions.clone(request, source, data.validated_data)
        return Response(self.get_serializer(self.get_queryset().get(pk=part.pk)).data, status=201)

    @extend_schema(parameters=[x for x in CATALOG_PARAMS if x.name != "catalog"], responses=inline_serializer("StageCounts", {
        "all": serializers.IntegerField(), **{k: serializers.IntegerField() for k in STAGES}}))
    @action(detail=False, methods=["get"], url_path="stage-counts", pagination_class=None)
    def stage_counts(self, request):
        """Counts per inventory stage for the caller's authorised records, with the same search and filters as the list."""
        base = self.get_queryset().order_by()  # all list filters except the stage itself
        return Response({"all": base.count(), **{k: base.filter(stage_q(k)).count() for k in STAGES}})

    @extend_schema(responses=PartFieldValuesSerializer)
    @action(detail=False, methods=["get"], url_path="field-values", pagination_class=None)
    def field_values(self, request):
        """Values already recorded in this company's parts (equipment, OEM, application, material), for the searchable
        part-form lists. Tenant- and project-scoped like the catalog; never another company's values."""
        base = restrict(request, SparePart.objects.filter(tenant=request.tenant), "project", own="submitted_by")
        out = {}
        for f in ("equipment_reference", "manufacturer", "application", "original_material"):
            values = base.exclude(**{f: ""}).values_list(f, flat=True).distinct().order_by(f)[:500]
            out[f] = sorted({v.strip() for v in values if v and v.strip()}, key=str.lower)
        return Response(out)

    @extend_schema(responses=ReviewEventSerializer(many=True))
    @action(detail=True, methods=["get"], pagination_class=None)
    def history(self, request, pk=None):
        """Review history of a client submission or clone (visible to the client and the reviewers)."""
        part = self.get_object()
        return Response(ReviewEventSerializer(part.review_events.select_related("created_by"), many=True).data)

    @extend_schema(request=inline_serializer("PartResubmit", {"message": serializers.CharField(required=False, allow_blank=True)}),
                   responses=SparePartSerializer)
    @action(detail=True, methods=["post"])
    def resubmit(self, request, pk=None):
        """Client: send an updated submission back to Aries after more information was requested."""
        part = self.get_object()
        submissions.resubmit(request, part, str(request.data.get("message") or ""))
        return Response(self.get_serializer(self.get_queryset().get(pk=part.pk)).data)

    def get_queryset(self):
        qs = with_summaries(restrict(self.request, super().get_queryset().select_related("passport", "project", "submitted_by", "reviewed_by"), "project", own="submitted_by"),
                            client=client_role(self.request))
        p = self.request.query_params
        q = p.get("search", "").strip()
        if q:
            qs = qs.filter(Q(part_number__icontains=q) | Q(name__icontains=q) | Q(description__icontains=q)
                           | Q(passport__passport_number__icontains=q) | Q(source_part_number__icontains=q))
        for field in ("category", "criticality", "status", "project"):
            if p.get(field):
                qs = qs.filter(**{field: p[field]})
        if p.get("evidence_level"):
            qs = qs.filter(passport__evidence_level=p["evidence_level"])
        level = p.get("data_level")
        if level in DATA_LEVELS:
            qs = qs.filter(passport__data_captured__in=DATA_LEVELS[level])
        elif level == "none":
            qs = qs.filter(Q(passport__isnull=True) | Q(passport__data_captured="none"))
        eligibility = p.get("eligibility")
        if eligibility == DigitalPassport.Eligibility.NOT_ELIGIBLE:
            qs = qs.filter(Q(passport__isnull=True) | Q(passport__manufacturing_eligibility=eligibility))
        elif eligibility in DigitalPassport.Eligibility.values:
            qs = qs.filter(passport__manufacturing_eligibility=eligibility)
        if self.action != "stage_counts" and stage_q(p.get("catalog", "")) is not None:
            qs = qs.filter(stage_q(p["catalog"]))
        if p.get("has_passport") in ("true", "false"):
            qs = qs.filter(passport__isnull=p["has_passport"] == "false")
        if p.get("has_3d") == "true":
            qs = qs.filter(has_3d=True)
        if p.get("review_state") == "open":
            qs = qs.filter(review_state__in=SparePart.OPEN_REVIEW)
        elif p.get("review_state") in SparePart.Review.values:
            qs = qs.filter(review_state=p["review_state"])
        if p.get("source_part"):
            qs = qs.filter(source_part=p["source_part"])
        if p.get("origin") in SparePart.Origin.values:
            qs = qs.filter(origin=p["origin"])
        return qs.order_by(ORDERING.get(p.get("ordering", ""), "-last_activity"), "part_number")
