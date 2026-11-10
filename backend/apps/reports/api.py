"""Report endpoints on passports: /passports/{id}/reports/ (list, generate), .../reports/{rid}/pdf/ (download),
.../reports/{rid}/pages/{n}/ (preview image). Mixed into PassportViewSet, so tenant isolation and project scope
(get_object) apply. Variant permissions are enforced here, server-side (CN-005 R5)."""
from django.http import HttpResponse
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.exceptions import DomainError
from apps.parts.submissions import display_name
from apps.tenancy.permissions import has_capability

from . import services
from .models import PassportReport, PassportReportEvent


class ReportEventSerializer(serializers.ModelSerializer):
    user = serializers.SerializerMethodField()

    class Meta:
        model = PassportReportEvent
        fields = ["action", "user", "created_at"]

    def get_user(self, obj) -> str:
        return display_name(obj.created_by)


class ReportSerializer(serializers.ModelSerializer):
    generated_by = serializers.SerializerMethodField()
    events = ReportEventSerializer(many=True, read_only=True)
    can_download = serializers.SerializerMethodField()
    superseded = serializers.SerializerMethodField()
    template = serializers.SerializerMethodField(help_text="standard, internal or mts")
    template_label = serializers.SerializerMethodField()
    can_preview = serializers.SerializerMethodField()
    withdrawal = serializers.SerializerMethodField(help_text="null, or {at, by, reason?}: the reason is shown to Aries only")
    replaced_by = serializers.SerializerMethodField()
    replaces = serializers.SerializerMethodField()

    class Meta:
        model = PassportReport
        fields = ["id", "number", "template", "template_label", "variant", "revision_number", "revision_status", "views_status", "attachments", "page_count",
                  "size_bytes", "pdf_sha256", "content_sha256", "watermarked", "created_at", "generated_by", "events",
                  "can_download", "can_preview", "superseded", "withdrawal", "replaced_by", "replaces"]

    def get_template(self, obj) -> str:
        # Reports generated before templates existed are immutable; their audience identifies the layout used.
        return "internal" if obj.variant == PassportReport.Variant.INTERNAL and obj.template == "standard" else obj.template

    def get_template_label(self, obj) -> str:
        return PassportReport.Template(self.get_template(obj)).label

    def get_generated_by(self, obj) -> str:
        return display_name(obj.created_by)

    def get_can_download(self, obj) -> bool:
        return not hasattr(obj, "withdrawal") and can(self.context["request"], obj, "download")

    def get_can_preview(self, obj) -> bool:
        return not hasattr(obj, "withdrawal") and can(self.context["request"], obj, "preview")

    def get_withdrawal(self, obj) -> dict | None:
        w = getattr(obj, "withdrawal", None)
        if w is None:
            return None
        out = {"at": w.created_at, "by": display_name(w.created_by)}
        if has_capability(self.context["request"], "reports.withdraw") or has_capability(self.context["request"], "reports.view_internal"):
            out |= {"reason": w.reason, "file_state": w.file_state, "file_state_label": w.get_file_state_display()}
        return out

    def get_replaced_by(self, obj) -> str | None:
        r = getattr(obj, "replacement", None)
        return r.replacement.number if r else None

    def get_replaces(self, obj) -> str | None:
        r = getattr(obj, "replaces", None)
        return r.withdrawn.number if r else None

    def get_superseded(self, obj) -> bool:
        return obj.revision_number < self.context.get("latest_revision", obj.revision_number)


def can(request, report: PassportReport, what: str) -> bool:
    if report.variant == PassportReport.Variant.INTERNAL:
        return has_capability(request, "reports.view_internal")
    return has_capability(request, "reports.download_client" if what == "download" else "reports.preview_client")


REPORT_REQUEST = inline_serializer("ReportGenerate", {
    "template": serializers.ChoiceField(choices=PassportReport.Template.choices, required=False),
    "variant": serializers.ChoiceField(choices=PassportReport.Variant.choices, required=False,
                                       help_text="Deprecated: client = standard template, internal = internal template."),
    "revision": serializers.IntegerField(required=False, allow_null=True),
    "attachments": serializers.ListField(child=serializers.JSONField(), required=False,
                                         help_text="In page order: file ids, or {file, version} to pin a version (default latest)."),
    "model": serializers.JSONField(required=False, allow_null=True, help_text=(
        "{file, version}: the STEP model whose views are printed (default: newest converted; client reports: released only)")),
    "replaces": serializers.UUIDField(required=False, allow_null=True, help_text="A withdrawn report this one replaces")})


def _build_args(request) -> dict:
    template = request.data.get("template") or {"client": "standard", "internal": "internal"}.get(request.data.get("variant"), "")
    if template not in PassportReport.Template.values:
        raise DomainError("invalid_template", "Choose a report template: standard, internal or mts.", http_status=400)
    items = request.data.get("attachments") or []
    if not isinstance(items, list) or len(items) > 50:
        raise DomainError("invalid_attachment", "Attach at most 50 documents.", http_status=400)
    model = request.data.get("model") or None  # post-UAT D-03: {"file": <STEP file id>, "version": n} whose views are printed
    if model is not None and not isinstance(model, dict):
        raise DomainError("invalid_model", "Choose the model as {file, version}.", http_status=400)
    return {"template": template, "revision_number": request.data.get("revision"), "attachment_items": items, "model": model}


REPORT_RELATED = ("created_by", "withdrawal__created_by", "replacement__replacement", "replaces__withdrawn")


class ReportActionsMixin:
    def _report(self, passport, rid):
        report = PassportReport.objects.filter(passport=passport, pk=rid).first()
        if report is None:
            raise DomainError("not_found", "Report not found.", http_status=404)
        return report

    @extend_schema(methods=["GET"], responses=ReportSerializer(many=True))
    @extend_schema(methods=["POST"], request=REPORT_REQUEST, responses={201: ReportSerializer})
    @action(detail=True, methods=["get", "post"], pagination_class=None)
    def reports(self, request, pk=None):
        """List the reports you may see, or generate a new one (client-facing or Aries-internal)."""
        passport = self.get_object()
        latest = passport.revisions.order_by("-revision_number").values_list("revision_number", flat=True).first() or 0
        ctx = {"request": request, "latest_revision": latest}
        if request.method == "POST":
            replaces = None
            if request.data.get("replaces"):
                if not services._is_uuid(str(request.data["replaces"])):
                    raise DomainError("invalid_replacement", "Name the withdrawn report to replace by its id.", http_status=400)
                replaces = self._report(passport, str(request.data["replaces"]))
            report = services.generate(request, passport, **_build_args(request), replaces=replaces)
            report = PassportReport.objects.select_related(*REPORT_RELATED).get(pk=report.pk)
            return Response(ReportSerializer(report, context=ctx).data, status=201)
        if not (has_capability(request, "reports.preview_client") or has_capability(request, "reports.view_internal")):
            raise DomainError("permission_denied", "Your role cannot view passport reports.", http_status=403)
        qs = passport.reports.select_related(*REPORT_RELATED).prefetch_related("events__created_by")
        if not has_capability(request, "reports.view_internal"):
            qs = qs.filter(variant=PassportReport.Variant.CLIENT)
        return Response(ReportSerializer(qs, many=True, context=ctx).data)

    @extend_schema(request=REPORT_REQUEST, responses={(200, "application/pdf"): bytes})
    @action(detail=True, methods=["post"], url_path="reports/preview")
    def report_preview(self, request, pk=None):
        """The complete assembled PDF (template + attachments in order) as it would be generated; nothing is stored.
        Same rights as generating; audited."""
        passport = self.get_object()
        pdf = services.preview(request, passport, **_build_args(request))
        resp = HttpResponse(pdf, content_type="application/pdf")
        resp["Content-Disposition"] = 'inline; filename="report-preview.pdf"'
        resp["Cache-Control"] = "no-store"
        return resp

    @extend_schema(responses={(200, "application/pdf"): bytes})
    @action(detail=True, methods=["get"], url_path=r"reports/(?P<rid>[0-9a-f-]+)/pdf")
    def report_pdf(self, request, pk=None, rid=None):
        """Download the PDF (Client Administrator / Client Engineer for client reports; Aries Engineer / QA)."""
        passport = self.get_object()
        report = self._report(passport, rid)
        if not can(request, report, "download"):
            raise DomainError("permission_denied", "Your role can preview this report but not download it.", http_status=403)
        pdf = services.read_pdf(report)  # refuses withdrawn reports and missing files before anything is logged
        services.log(request, report, PassportReportEvent.Action.DOWNLOADED)
        resp = HttpResponse(pdf, content_type="application/pdf")
        resp["Content-Disposition"] = f'attachment; filename="{report.number}.pdf"'
        resp["Cache-Control"] = "no-store"
        return resp

    @extend_schema(responses={(200, "image/png"): bytes})
    @action(detail=True, methods=["get"], url_path=r"reports/(?P<rid>[0-9a-f-]+)/pages/(?P<page>\d+)")
    def report_page(self, request, pk=None, rid=None, page=None):
        """Preview image of one page; preview-only roles never receive the PDF file."""
        passport = self.get_object()
        report = self._report(passport, rid)
        if not can(request, report, "preview"):
            raise DomainError("permission_denied", "Your role cannot view this report.", http_status=403)
        png = services.page_png(report, int(page))  # refuses withdrawn reports and missing files before anything is logged
        if int(page) == 1:
            services.log(request, report, PassportReportEvent.Action.PREVIEWED)
        resp = HttpResponse(png, content_type="image/png")
        resp["Cache-Control"] = "no-store"
        return resp

    @extend_schema(request=inline_serializer("ReportWithdraw", {"reason": serializers.CharField()}), responses=ReportSerializer)
    @action(detail=True, methods=["post"], url_path=r"reports/(?P<rid>[0-9a-f-]+)/withdraw")
    def report_withdraw(self, request, pk=None, rid=None):
        """Withdraw a report (Aries Engineer with engineering authoring; Aries Admin in an Aries Admin workspace). Mandatory
        reason. Record, number and history are kept; PDF and page images are refused to every role from then on."""
        passport = self.get_object()
        report = self._report(passport, rid)
        services.withdraw(request, report, request.data.get("reason", ""))
        report = PassportReport.objects.select_related(*REPORT_RELATED).prefetch_related("events__created_by").get(pk=report.pk)
        latest = passport.revisions.order_by("-revision_number").values_list("revision_number", flat=True).first() or 0
        return Response(ReportSerializer(report, context={"request": request, "latest_revision": latest}).data)
