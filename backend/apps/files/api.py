"""Engineering files: upload (STEP, DWG, PDF), versions, derivatives and controlled downloads.

Downloads use short-lived links bound to the requesting user, membership and tenant (HYB-012).
The link is re-validated on use: membership still active, object still present in that tenant.
Watermarking (BR-027) is not implemented yet: its policy and feasibility are open (OQ-33).
"""
from datetime import timedelta
from urllib.parse import quote

from django.conf import settings
from django.http import FileResponse, HttpResponseRedirect
from django.utils import timezone
from drf_spectacular.utils import extend_schema, extend_schema_field, inline_serializer
from rest_framework import parsers, serializers, status
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.service import record
from apps.core.exceptions import DomainError
from apps.parts.models import SparePart
from apps.passports.models import DigitalPassport
from apps.projects.scoping import project_allowed, restrict
from apps.tenancy.context import set_tenant_context
from apps.tenancy.models import Membership, Tenant
from apps.tenancy.permissions import has_capability
from apps.tenancy.viewsets import TenantModelViewSet, TenantScopedRelatedField

from .models import Derivative, EngineeringFile, FileVersion
from .services import make_link_token, read_link_token, redeem_link, store_version
from .storage import get_storage

# D1: what a client organisation may add itself (supporting documents and photographs).
CLIENT_KINDS = {EngineeringFile.Kind.PDF, EngineeringFile.Kind.IMAGE}
CLIENT_CATEGORIES = {EngineeringFile.Category.PHOTO, EngineeringFile.Category.OTHER}


def is_client_supplied(ef: EngineeringFile) -> bool:
    """A supporting document added by the client organisation (not by Aries staff); everything else is Aries-controlled."""
    from apps.tenancy.membership_policy import is_operator_staff

    return (ef.kind in CLIENT_KINDS and ef.category in CLIENT_CATEGORIES and ef.created_by_id is not None
            and not is_operator_staff(ef.created_by))


class DerivativeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Derivative
        fields = ["id", "kind", "size_bytes", "sha256", "generator", "created_at"]


class ConversionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["not_requested", "queued", "running", "succeeded", "failed", "not_available"])
    error_code = serializers.CharField(required=False, allow_null=True)
    reason = serializers.CharField(required=False)


class FileVersionSerializer(serializers.ModelSerializer):
    derivatives = DerivativeSerializer(many=True, read_only=True)
    conversion = serializers.SerializerMethodField()
    uploaded_by = serializers.SerializerMethodField()
    passport_revision_number = serializers.SerializerMethodField(help_text="Passport revision in force when this version was uploaded.")

    class Meta:
        model = FileVersion
        fields = ["id", "version_number", "original_filename", "size_bytes", "sha256", "detected_format", "page_count",
                  "content_type", "note", "passport_revision", "passport_revision_number", "derivatives", "conversion",
                  "uploaded_by", "created_at"]

    def get_uploaded_by(self, obj) -> str:
        # CAD-010: uploader shown with each version
        return obj.created_by.email if obj.created_by_id else ""

    def get_passport_revision_number(self, obj) -> int | None:
        return obj.passport_revision.revision_number if obj.passport_revision_id else None

    @extend_schema_field(ConversionSerializer(allow_null=True))
    def get_conversion(self, obj):
        if obj.file.kind == EngineeringFile.Kind.DWG:
            return {"status": "not_available", "reason": "DWG preview converter not selected yet (OQ-27)."}
        if obj.file.kind != EngineeringFile.Kind.STEP:
            return None
        from apps.jobs.models import Job

        job = Job.objects.filter(tenant_id=obj.tenant_id, kind="cad.step_to_glb", payload__file_version=str(obj.pk)).order_by("-created_at").first()
        if job is None:
            return {"status": "not_requested"}
        return {"status": job.status, "error_code": job.error_code or None}


def is_client_member(request) -> bool:
    m = getattr(request, "membership", None)
    return m is not None and not m.role.startswith("operator_")


def client_version_number(ef: EngineeringFile) -> int | None:
    """The one version of an Aries document a client may see (post-UAT D-02); None when nothing is released.
    Client-supplied documents are the client's own: their newest version."""
    if is_client_supplied(ef):
        return ef.versions.order_by("-version_number").values_list("version_number", flat=True).first()
    return ef.released_version if ef.client_visible else None


def client_may_open(ef: EngineeringFile, version_number: int) -> bool:
    if is_client_supplied(ef):
        return True
    return ef.client_visible and ef.released_version == version_number


class EngineeringFileSerializer(serializers.ModelSerializer):
    file = serializers.FileField(write_only=True, allow_empty_file=True, help_text="STEP (.stp/.step), DWG (.dwg) or PDF (.pdf)")
    note = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=300)
    latest_version = serializers.SerializerMethodField()
    version_count = serializers.SerializerMethodField()

    class Meta:
        model = EngineeringFile
        fields = ["id", "part", "passport", "kind", "category", "title", "file", "note", "client_visible", "released_version",
                  "latest_version", "version_count", "created_at", "updated_at"]
        read_only_fields = ["id", "latest_version", "version_count", "created_at", "updated_at"]
        extra_kwargs = {"kind": {"required": False}, "title": {"required": False, "allow_blank": True, "help_text": "Defaults to the file name."},
                        "client_visible": {"required": False, "help_text": (
                            "Client users may see this document. Set by Aries Engineers only. Aries uploads start hidden until an "
                            "Aries Engineer releases them (post-UAT D-02); client-supplied documents start visible. Setting it to "
                            "true releases the newest version; false withdraws the document from clients.")},
                        "released_version": {"required": False, "help_text": (
                            "The version released to clients (Aries Engineers). Clients see and open only this version.")}}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        TenantScopedRelatedField.limit(self, "part", SparePart)
        TenantScopedRelatedField.limit(self, "passport", DigitalPassport)

    @extend_schema_field(FileVersionSerializer(allow_null=True))
    def get_latest_version(self, obj):
        request = self.context.get("request")
        if request is not None and is_client_member(request):  # clients: the released version only (D-02)
            n = client_version_number(obj)
            v = obj.versions.filter(version_number=n).first() if n else None
        else:
            v = obj.versions.order_by("-version_number").first()
        return FileVersionSerializer(v).data if v else None

    def get_version_count(self, obj) -> int:
        request = self.context.get("request")
        if request is not None and is_client_member(request) and not is_client_supplied(obj):
            return 1 if client_version_number(obj) else 0
        return obj.versions.count()

    def validate(self, attrs):
        passport, part = attrs.get("passport"), attrs.get("part")
        if passport and part and passport.part_id != part.pk:
            raise serializers.ValidationError({"passport": "The passport belongs to a different spare part."})
        return attrs


class LinkRequestSerializer(serializers.Serializer):
    variant = serializers.ChoiceField(
        choices=["original", "preview", "glb", "pdf", "svg"], default="original",
        help_text="original: download the preserved file. preview: view a PDF in the browser (BR-039, DRW-003); "
                  "allowed for the same roles that may view 3D derivatives. glb/pdf/svg: viewer derivatives.")


class EngineeringFileViewSet(TenantModelViewSet):
    model = EngineeringFile
    serializer_class = EngineeringFileSerializer
    audit_type = "engineering_file"
    parser_classes = [parsers.MultiPartParser, parsers.FormParser, parsers.JSONParser]
    capabilities = {"list": "files.view", "retrieve": "files.view", "create": "files.upload",
                    "partial_update": "files.upload", "update": "files.upload",
                    "versions": "files.view", "download_link": "files.view", "thumbnail": "files.view"}

    def _write_capability(self) -> str:
        # Aries Engineers write engineering files; clients may only add/manage supporting documents (checked per file).
        # Other client users may attach photos/PDFs to their own open part submissions only (_check_own_submission).
        if has_capability(self.request, "files.upload"):
            return "files.upload"
        if has_capability(self.request, "files.upload_supporting"):
            return "files.upload_supporting"
        return "parts.submit"

    def _submission_uploader(self) -> bool:
        return not has_capability(self.request, "files.upload") and not has_capability(self.request, "files.upload_supporting")

    def _check_own_submission(self, part, ef: EngineeringFile | None = None) -> None:
        own = (part is not None and part.origin == SparePart.Origin.CLIENT and part.review_state in SparePart.OPEN_REVIEW
               and part.submitted_by_id == self.request.user.pk)
        if not own or (ef is not None and ef.created_by_id != self.request.user.pk):
            raise DomainError("submission_files_only", "You can add photographs and PDF documents only to your own spare-part "
                              "submissions while they wait for Aries review.", http_status=403)

    def get_permissions(self):
        writing = self.action in ("create", "update", "partial_update") or (self.action == "versions" and self.request.method == "POST")
        if writing:
            self.capabilities = {**self.capabilities, self.action: self._write_capability()}
        return super().get_permissions()

    def get_queryset(self):
        qs = restrict(self.request, super().get_queryset().select_related("part", "passport"), "part__project", own="part__submitted_by")
        m = getattr(self.request, "membership", None)
        if m is not None and not m.role.startswith("operator_"):  # CN-005: clients never see unreleased documents
            qs = qs.filter(client_visible=True)
        for field in ("part", "passport", "kind", "category"):
            value = self.request.query_params.get(field)
            if value:
                qs = qs.filter(**{field: value})
        return qs

    def _supporting_only(self) -> bool:
        return not has_capability(self.request, "files.upload")

    def _check_client_supplied(self, ef: EngineeringFile) -> None:
        """Clients may change only supporting documents their organisation added, never Aries-controlled files."""
        if self._supporting_only() and not is_client_supplied(ef):
            raise DomainError("aries_controlled_file", "This engineering file is controlled by Aries and cannot be changed by "
                              "your organisation. Add a supporting document instead.", http_status=403)
        if self._submission_uploader():
            self._check_own_submission(ef.part, ef)

    def perform_create(self, serializer):
        upload = serializer.validated_data.pop("file")
        note = serializer.validated_data.pop("note", "")
        from .validation import validate_upload

        part = serializer.validated_data.get("part")
        if part is not None and not project_allowed(self.request, part.project_id):
            raise DomainError("not_found", "Spare part not found.", http_status=status.HTTP_404_NOT_FOUND)
        kind = serializer.validated_data.get("kind") or validate_upload(upload).kind
        if self._submission_uploader():
            self._check_own_submission(part)
        if self._supporting_only():
            category = serializer.validated_data.get("category") or EngineeringFile.Category.OTHER
            # post-UAT D-14: a client that has CAD submits it with its spare-part submission while it waits for Aries review;
            # after acceptance the CAD is managed by Aries like every engineering file
            open_submission = (part is not None and part.origin == SparePart.Origin.CLIENT and part.review_state in SparePart.OPEN_REVIEW)
            if kind in (EngineeringFile.Kind.STEP, EngineeringFile.Kind.DWG) and open_submission:
                category = EngineeringFile.Category.MODEL_3D if kind == EngineeringFile.Kind.STEP else EngineeringFile.Category.DRAWING
            elif kind not in CLIENT_KINDS or category not in CLIENT_CATEGORIES:
                raise DomainError("supporting_documents_only", "Your organisation can add supporting documents (PDF) and photographs, "
                                  "and STEP or DWG files to a spare-part submission while it waits for Aries review. Other engineering "
                                  "master documents are managed by Aries.", http_status=403)
            serializer.validated_data["category"] = category
        title = serializer.validated_data.get("title") or upload.name
        if self._supporting_only():  # client-supplied documents are the client's own
            visible = True
        else:  # never visible automatically: Aries PDFs stay hidden unless the engineer releases them now
            visible = bool(serializer.validated_data.get("client_visible", False))  # D-02: never visible automatically
        serializer.validated_data["client_visible"] = visible
        serializer.validated_data.pop("released_version", None)
        ef = serializer.save(tenant=self.request.tenant, created_by=self.request.user, kind=kind, title=title)
        store_version(self.request, ef, upload, note=note)
        if visible:  # released (or client-supplied): the first version is the one clients see
            ef.released_version = 1
            ef.save(update_fields=["released_version", "updated_at"])
        record(self.request, "engineering_file.created", obj=ef, data={"kind": kind, "category": ef.category,
                                                                        "client_supplied": self._supporting_only(), "client_visible": visible})

    def perform_update(self, serializer):
        self._check_client_supplied(serializer.instance)
        serializer.validated_data.pop("file", None)
        serializer.validated_data.pop("note", None)
        for locked in ("kind", "part"):
            serializer.validated_data.pop(locked, None)
        if self._supporting_only():
            serializer.validated_data.pop("client_visible", None)
            serializer.validated_data.pop("released_version", None)
        else:
            self._release_rules(serializer)
        if self._supporting_only() and serializer.validated_data.get("category", EngineeringFile.Category.OTHER) not in CLIENT_CATEGORIES:
            raise DomainError("supporting_documents_only", "Supporting documents can only be filed as photographs or other.", http_status=403)
        super().perform_update(serializer)

    @extend_schema(request={"multipart/form-data": inline_serializer("VersionUpload", {
        "file": serializers.FileField(), "note": serializers.CharField(required=False)})},
        responses={200: FileVersionSerializer(many=True), 201: FileVersionSerializer})
    def _release_rules(self, serializer):
        """Release (client_visible true and/or released_version n) or withdraw (client_visible false), audited (D-02)."""
        ef, v = serializer.instance, serializer.validated_data
        numbers = set(ef.versions.values_list("version_number", flat=True))
        visible = v.get("client_visible", ef.client_visible)
        released = v.get("released_version", ef.released_version)
        if not visible:
            released = None
        elif "released_version" not in v and (not ef.client_visible or released is None):
            released = max(numbers) if numbers else None  # releasing without a version releases the newest
        if visible and released not in numbers:
            raise DomainError("invalid_version", "Release an existing version of this document.", http_status=400)
        v["client_visible"], v["released_version"] = visible, released
        if (visible, released) != (ef.client_visible, ef.released_version):
            # visibility toggles keep their established audit action; a change of the released version alone has its own
            action = ("engineering_file.client_visibility_changed" if visible != ef.client_visible else "engineering_file.version_released")
            record(self.request, action, obj=ef, data={"client_visible": visible, "released_version": released,
                                                       "previous_version": ef.released_version})

    @action(detail=True, methods=["get", "post"])
    def versions(self, request, pk=None):
        ef = self.get_object()
        if request.method == "GET":
            qs = ef.versions.order_by("-version_number")
            if is_client_member(request):
                qs = qs.filter(version_number=client_version_number(ef) or 0)
            return Response(FileVersionSerializer(qs, many=True).data)
        self._check_client_supplied(ef)
        upload = request.FILES.get("file")
        if upload is None:
            raise DomainError("file_required", "Choose a file to upload.", http_status=400)
        fv = store_version(request, ef, upload, note=str(request.data.get("note", "")))
        return Response(FileVersionSerializer(fv).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=LinkRequestSerializer, responses={200: inline_serializer("DownloadLink", {
        "url": serializers.CharField(), "expires_at": serializers.DateTimeField(), "filename": serializers.CharField()})})
    @action(detail=True, methods=["post"], url_path=r"versions/(?P<number>\d+)/download-link")
    def download_link(self, request, pk=None, number=None):
        ef = self.get_object()
        fv = ef.versions.filter(version_number=int(number)).first()
        if fv is None or (is_client_member(request) and not client_may_open(ef, fv.version_number)):
            raise DomainError("not_found", "Version not found.", http_status=404)
        s = LinkRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        variant = s.validated_data["variant"]
        if variant == "original":
            if not has_capability(request, "files.download_original"):
                raise DomainError("permission_denied", "Your role cannot download engineering originals.", http_status=403)
            key, filename, object_id = fv.storage_key, fv.original_filename, fv.pk
        elif variant == "preview":
            # In-browser viewing of PDF documents and photographs. Same roles as derivative viewing; served inline.
            if ef.kind not in (EngineeringFile.Kind.PDF, EngineeringFile.Kind.IMAGE):
                raise DomainError("preview_not_available", "In-browser preview is available for PDF documents and photographs only.", http_status=400)
            if not has_capability(request, "files.download_derivative"):
                raise DomainError("permission_denied", "Your role cannot preview documents.", http_status=403)
            key, filename, object_id = fv.storage_key, fv.original_filename, fv.pk
        else:
            if not has_capability(request, "files.download_derivative"):
                raise DomainError("permission_denied", "Your role cannot view derivatives.", http_status=403)
            d = fv.derivatives.filter(kind=variant).first()
            if d is None:
                raise DomainError("derivative_not_available", f"No {variant.upper()} derivative is available for this version.", http_status=404)
            key, filename, object_id = d.storage_key, f"{fv.original_filename.rsplit('.', 1)[0]}.{variant}", d.pk
        seconds = settings.DOWNLOAD_LINK_SECONDS
        token = make_link_token(request, storage_key=key, filename=filename, variant=variant, object_id=str(object_id))
        record(request, "file.download_link_issued", obj=fv, data={"variant": variant, "expires_in": seconds})
        # Public links must use the frontend/IIS origin. The API is also reachable on the
        # internal backend port, but that port is not the browser-facing application URL.
        url = f"{settings.WEB_BASE_URL.rstrip('/')}/api/v1/downloads/{quote(token, safe='')}/"
        return Response({"url": url, "expires_at": timezone.now() + timedelta(seconds=seconds), "filename": filename})


    @extend_schema(responses={(200, "image/jpeg"): bytes})
    @action(detail=True, methods=["get"], url_path=r"versions/(?P<number>\d+)/thumbnail")
    def thumbnail(self, request, pk=None, number=None):
        """Small, metadata-free JPEG of a photograph for lists and catalogs. Authenticated with the caller's own
        token (tenant-scoped and RLS-checked like every file endpoint). Not audited, like other list views; full
        images are opened through audited preview links."""
        from apps.tenancy import admin_workspace

        if admin_workspace.file_content_blocked(request.membership):
            raise DomainError(*admin_workspace.BLOCKED, http_status=403)
        ef = self.get_object()
        if is_client_member(request) and not client_may_open(ef, int(number)):
            raise DomainError("thumbnail_not_available", "No thumbnail is available for this version.", http_status=404)
        d = Derivative.objects.filter(file_version__file=ef, file_version__version_number=int(number), kind=Derivative.Kind.THUMB).first()
        if d is None:
            raise DomainError("thumbnail_not_available", "No thumbnail is available for this version.", http_status=404)
        resp = FileResponse(get_storage().open(d.storage_key), content_type="image/jpeg")
        resp["Cache-Control"] = "private, max-age=300"
        resp["X-Content-Type-Options"] = "nosniff"
        return resp


class DownloadView(APIView):
    """Redeems a download link. No bearer header needed (links are used by browsers and apps),
    but the signed token binds the request to a user, membership and tenant, and expires quickly."""

    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(responses={200: bytes}, tags=["files"])
    def get(self, request, token):
        data = read_link_token(token, max_age=settings.DOWNLOAD_LINK_SECONDS)
        membership = Membership.objects.select_related("tenant", "user").filter(
            pk=data["m"], user_id=data["u"], tenant_id=data["t"], is_active=True,
            tenant__status=Tenant.Status.ACTIVE, user__is_active=True).first()
        if membership is None:
            raise DomainError("link_invalid", "This download link is no longer valid.", http_status=403)
        set_tenant_context(membership.tenant_id)  # RLS: the object must exist in the link's tenant
        preview = data["v"] == "preview"
        model = FileVersion if data["v"] in ("original", "preview") else Derivative
        obj = model.objects.filter(pk=data["o"], storage_key=data["k"]).first()
        if obj is None:
            raise DomainError("not_found", "File not found.", http_status=404)
        if not membership.role.startswith("operator_"):  # D-02: a withdrawal also revokes links issued before it
            fv = obj if isinstance(obj, FileVersion) else obj.file_version
            if not client_may_open(fv.file, fv.version_number):
                raise DomainError("link_invalid", "This document is no longer released to your organisation.", http_status=403)
        redeem_link(data, membership.user)  # single use: every authorisation check above has already passed
        request.membership, request.tenant = membership, membership.tenant
        request.user = membership.user
        action = "file.previewed" if preview else "file.downloaded"
        record(request, action, obj=obj, data={"variant": data["v"]}, actor=membership.user, tenant=membership.tenant)
        storage = get_storage()
        content_type = obj.content_type if preview else None
        direct = storage.signed_url(data["k"], data["f"], seconds=60, inline=preview, content_type=content_type)
        if direct:
            return HttpResponseRedirect(direct)
        resp = FileResponse(storage.open(data["k"]), as_attachment=not preview, filename=data["f"], content_type=content_type)
        resp["X-Content-Type-Options"] = "nosniff"
        resp["Cache-Control"] = "no-store"
        resp["X-Content-SHA256"] = getattr(obj, "sha256", "")
        return resp
