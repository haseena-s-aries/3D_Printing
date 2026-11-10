"""Inventory import API (CN-007 Phase 1).

/inventory-imports/ inside a client company: upload (preview), mapping changes, rows, commit, discard, history and
the data-quality summary. Tenant RLS applies to every query; project-limited Aries Engineers see batches of their
projects (and their own). /admin/inventory-imports/ gives the Aries Admin read-only summaries across companies and
lets them discard an open preview; it never imports or shows row contents.
"""
from django.db import connection
from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import parsers, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.service import record
from apps.core.exceptions import DomainError
from apps.parts.submissions import display_name
from apps.projects.scoping import allowed_project_ids
from apps.tenancy import mssql
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Tenant
from apps.tenancy.permissions import HasCapability
from apps.tenancy.viewsets import TenantModelViewSet

from . import mapping as M
from . import services
from .models import InventoryImport, InventoryImportRow


class InventoryImportSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    project_name = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    committed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = InventoryImport
        fields = ["id", "reference", "status", "status_label", "file_name", "file_kind", "file_size", "file_sha256", "sheet_name",
                  "header_row", "headers", "preset", "mapping", "project", "project_name", "importer_side", "row_count", "counts",
                  "analysed_at", "apply_updates", "result", "created_at", "created_by_name", "committed_at", "committed_by_name"]
        read_only_fields = fields

    def get_project_name(self, obj) -> str:
        return f"{obj.project.code} · {obj.project.name}" if obj.project_id else ""

    def get_created_by_name(self, obj) -> str:
        return display_name(obj.created_by)

    def get_committed_by_name(self, obj) -> str:
        return display_name(obj.committed_by) if obj.committed_by_id else ""


class ImportRowSerializer(serializers.ModelSerializer):
    outcome_label = serializers.CharField(source="get_outcome_display", read_only=True)
    part_number = serializers.SerializerMethodField()

    class Meta:
        model = InventoryImportRow
        fields = ["id", "row_number", "source", "values", "outcome", "outcome_label", "messages", "flags", "part", "part_number",
                  "changes", "conflicts", "applied"]
        read_only_fields = fields

    def get_part_number(self, obj) -> str:
        return obj.part.part_number if obj.part_id else ""


class InventoryImportViewSet(TenantModelViewSet):
    model = InventoryImport
    serializer_class = InventoryImportSerializer
    audit_type = "inventory_import"
    parser_classes = [parsers.MultiPartParser, parsers.FormParser, parsers.JSONParser]
    capabilities = {k: "inventory.import" for k in ("list", "retrieve", "create", "partial_update", "update", "rows",
                                                    "commit", "discard", "options_", "quality")}

    def get_queryset(self):
        qs = super().get_queryset().select_related("project", "created_by", "committed_by")
        if getattr(self, "swagger_fake_view", False):
            return qs
        allowed = allowed_project_ids(self.request)
        if allowed is not None:
            qs = qs.filter(Q(project__in=allowed) | Q(created_by=self.request.user))
        return qs

    @extend_schema(request=inline_serializer("InventoryImportUpload", {
        "file": serializers.FileField(), "project": serializers.UUIDField(required=False, allow_null=True),
        "preset": serializers.CharField(required=False, allow_blank=True)}), responses={201: InventoryImportSerializer})
    def create(self, request, *args, **kwargs):
        upload = request.FILES.get("file")
        if upload is None:
            raise DomainError("file_required", "Choose an Excel (.xlsx) or CSV file.", http_status=400)
        batch = services.create(request, upload, request.data.get("project") or None, request.data.get("preset") or "")
        return Response(self.get_serializer(batch).data, status=201)

    @extend_schema(request=inline_serializer("InventoryImportMapping", {
        "mapping": serializers.DictField(child=serializers.CharField(allow_blank=True)),
        "project": serializers.UUIDField(required=False, allow_null=True)}), responses=InventoryImportSerializer)
    def partial_update(self, request, *args, **kwargs):
        batch = self.get_object()
        project = request.data["project"] if "project" in request.data else "__keep__"
        batch = services.update_mapping(request, batch, request.data.get("mapping") or {}, project)
        return Response(self.get_serializer(batch).data)

    def update(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)

    @extend_schema(parameters=[OpenApiParameter("outcome", str), OpenApiParameter("flag", str)], responses=ImportRowSerializer(many=True))
    @action(detail=True, methods=["get"])
    def rows(self, request, pk=None):
        batch = self.get_object()
        qs = batch.rows.select_related("part")
        if request.query_params.get("outcome"):
            qs = qs.filter(outcome=request.query_params["outcome"])
        if request.query_params.get("flag"):
            flag = request.query_params["flag"]
            if mssql.is_mssql(connection):  # JSON array membership: no JSONField `contains` lookup on SQL Server
                qs = qs.extra(where=["EXISTS (SELECT 1 FROM OPENJSON(imports_inventoryimportrow.flags) f WHERE f.[value] = %s)"],
                              params=[flag])
            else:
                qs = qs.filter(flags__contains=[flag])
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(ImportRowSerializer(page, many=True).data)

    @extend_schema(request=inline_serializer("InventoryImportCommit", {
        "confirm": serializers.BooleanField(), "apply_updates": serializers.BooleanField(required=False)}),
        responses=InventoryImportSerializer)
    @action(detail=True, methods=["post"])
    def commit(self, request, pk=None):
        if request.data.get("confirm") is not True:
            raise DomainError("confirmation_required", "Confirm the import after reviewing the preview.", http_status=400)
        batch = services.commit(request, self.get_object(), request.data.get("apply_updates") is True)
        return Response(self.get_serializer(batch).data)

    @extend_schema(request=None, responses=InventoryImportSerializer)
    @action(detail=True, methods=["post"])
    def discard(self, request, pk=None):
        return Response(self.get_serializer(services.discard(request, self.get_object())).data)

    @extend_schema(responses=inline_serializer("InventoryImportOptions", {
        "targets": serializers.ListField(child=serializers.DictField()), "presets": serializers.ListField(child=serializers.DictField()),
        "flags": serializers.DictField(), "max_rows": serializers.IntegerField(), "max_bytes": serializers.IntegerField()}))
    @action(detail=False, methods=["get"], url_path="options", url_name="options", pagination_class=None)
    def options_(self, request):
        from django.conf import settings

        return Response({
            "targets": [{"field": f, "label": lbl, "required": req, "max_length": n, "note": note} for f, (lbl, req, n, note) in M.TARGETS.items()],
            "presets": [{"key": k, "label": v["label"], "columns": v["columns"]} for k, v in M.PRESETS.items()],
            "flags": {c: {"label": lbl, "level": lv} for c, (lbl, lv) in M.FLAGS.items()},
            "max_rows": settings.IMPORT_MAX_ROWS, "max_bytes": settings.IMPORT_MAX_BYTES})

    @extend_schema(responses=dict)
    @action(detail=False, methods=["get"], pagination_class=None)
    def quality(self, request):
        """Data-quality summary over this company's imported parts (live), plus conflicts left by committed imports."""
        return Response(services.quality(request))


class AdminImportsView(APIView):
    """Aries Admin: import summaries per client company (no row contents, no part data), and discarding open previews."""

    permission_classes = [HasCapability]
    capabilities = {"get": "inventory.import_admin", "post": "inventory.import_admin"}

    @extend_schema(parameters=[OpenApiParameter("client", str)], responses=dict)
    def get(self, request):
        clients = Tenant.objects.filter(kind=Tenant.Kind.CLIENT).order_by("name")
        if request.query_params.get("client"):
            clients = clients.filter(pk=request.query_params["client"])
        out = []
        for t in clients:
            with tenant_context(t):
                batches = list(InventoryImport.objects.filter(tenant=t).select_related("created_by", "committed_by", "project")[:50])
                if request.query_params.get("client"):
                    record(request, "inventory_import.admin_summary_viewed", tenant=t, obj_type="tenant", obj_id=str(t.pk),
                           data={"by_operator": True})
            if not batches and not request.query_params.get("client"):
                continue
            out.append({"client_id": str(t.pk), "client_name": t.name, "imports": [{
                "id": str(b.pk), "reference": b.reference, "status": b.status, "status_label": b.get_status_display(),
                "file_name": b.file_name, "row_count": b.row_count, "outcomes": (b.counts or {}).get("outcomes", {}),
                "result": b.result, "importer_side": b.importer_side, "created_by": display_name(b.created_by), "created_at": b.created_at,
                "committed_at": b.committed_at, "project": b.project.code if b.project_id else ""} for b in batches]})
        record(request, "inventory_import.admin_summary_viewed", obj_type="tenant",
               obj_id=request.query_params.get("client", ""), data={"client": request.query_params.get("client", "")})
        return Response({"clients": out})

    @extend_schema(request=inline_serializer("AdminImportDiscard", {"client": serializers.UUIDField(), "import": serializers.UUIDField()}),
                   responses=dict)
    def post(self, request):
        client = Tenant.objects.filter(kind=Tenant.Kind.CLIENT, pk=request.data.get("client")).first()
        if client is None:
            raise DomainError("not_found", "Client company not found.", http_status=404)
        with tenant_context(client):
            batch = InventoryImport.objects.filter(tenant=client, pk=request.data.get("import")).first()
            if batch is None:
                raise DomainError("not_found", "Import not found.", http_status=404)
            services.discard(request, batch, tenant=client)
        record(request, "inventory_import.discarded", obj_type="inventoryimport", obj_id=str(batch.pk),
               data={"client": client.slug, "reference": batch.reference, "by_operator": True})
        return Response({"status": batch.status, "reference": batch.reference})
