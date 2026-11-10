"""Registration, email verification, password reset (public, rate-limited) and Aries Admin review endpoints."""
from django.conf import settings
from django.http import Http404
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.core import mail
from apps.core.exceptions import DomainError
from apps.tenancy.permissions import HasCapability

from . import services as svc
from .models import CompanyRegistration

GENERIC = "If the details can be used, we have sent an email with the next step. Check your inbox (and spam folder)."


class EmailInput(serializers.Serializer):
    email = serializers.EmailField()


class PublicView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]


class RegistrationConfigView(PublicView):
    throttle_classes = []

    @extend_schema(tags=["registration"], responses={200: inline_serializer("RegistrationConfig", {
        "registration_enabled": serializers.BooleanField(), "dev_outbox": serializers.BooleanField()})})
    def get(self, request):
        return Response({"registration_enabled": settings.PUBLIC_REGISTRATION_ENABLED, "dev_outbox": settings.DEV_OUTBOX_VIEW})


class RegistrationSubmitView(PublicView):
    throttle_scope = "register"

    @extend_schema(tags=["registration"], request=svc.RegistrationInput,
                   responses={202: inline_serializer("RegistrationSubmitted", {"status": serializers.CharField(), "message": serializers.CharField()})})
    def post(self, request):
        svc._require_enabled()
        s = svc.RegistrationInput(data=request.data)
        s.is_valid(raise_exception=True)
        svc.submit_registration(request, s.validated_data)
        return Response({"status": "submitted", "message": GENERIC}, status=status.HTTP_202_ACCEPTED)


class RegistrationResendView(PublicView):
    throttle_scope = "register"

    @extend_schema(tags=["registration"], request=EmailInput,
                   responses={202: inline_serializer("ResendOut", {"status": serializers.CharField(), "message": serializers.CharField()})})
    def post(self, request):
        s = EmailInput(data=request.data)
        s.is_valid(raise_exception=True)
        svc.resend_verification(request, s.validated_data["email"])
        return Response({"status": "submitted", "message": GENERIC}, status=status.HTTP_202_ACCEPTED)


class RegistrationVerifyView(PublicView):
    throttle_scope = "verify"

    @extend_schema(tags=["registration"], responses={200: inline_serializer("VerificationInfo", {
        "company_name": serializers.CharField(), "email": serializers.EmailField()})})
    def get(self, request, token):
        return Response(svc.verification_info(token))

    @extend_schema(tags=["registration"], request=inline_serializer("VerifyIn", {"password": serializers.CharField()}),
                   responses={200: inline_serializer("VerifyOut", {"status": serializers.CharField(), "company_name": serializers.CharField()})})
    def post(self, request, token):
        reg = svc.verify_registration(request, token, str(request.data.get("password", "")))
        return Response({"status": "pending_approval", "company_name": reg.company_name})


class PasswordResetRequestView(PublicView):
    throttle_scope = "password_reset"

    @extend_schema(tags=["auth"], request=EmailInput,
                   responses={202: inline_serializer("PasswordResetOut", {"status": serializers.CharField(), "message": serializers.CharField()})})
    def post(self, request):
        s = EmailInput(data=request.data)
        s.is_valid(raise_exception=True)
        svc.request_password_reset(request, s.validated_data["email"])
        return Response({"status": "submitted", "message": GENERIC}, status=status.HTTP_202_ACCEPTED)


class PasswordResetView(PublicView):
    throttle_scope = "verify"

    @extend_schema(tags=["auth"], responses={200: inline_serializer("PasswordResetInfo", {"email": serializers.EmailField()})})
    def get(self, request, token):
        return Response(svc.reset_info(token))

    @extend_schema(tags=["auth"], operation_id="v1_public_password_reset_confirm",
                   request=inline_serializer("PasswordResetSet", {"password": serializers.CharField()}),
                   responses={200: inline_serializer("PasswordResetDone", {"status": serializers.CharField()})})
    def post(self, request, token):
        password = str(request.data.get("password", ""))
        if password != str(request.data.get("password_confirm", password)):
            raise serializers.ValidationError({"password_confirm": "The passwords do not match."})
        svc.complete_password_reset(token, password)
        return Response({"status": "password_changed"})


class DevOutboxView(PublicView):
    """DEBUG-only development outbox (file email backend). 404 everywhere else."""

    throttle_classes = []

    @extend_schema(tags=["registration"], responses={200: dict})
    def get(self, request):
        if not settings.DEV_OUTBOX_VIEW:
            raise Http404
        return Response({"notice": "Development outbox: emails are written to local files, nothing is delivered.",
                         "messages": mail.outbox_messages()})


class RegistrationSerializer(serializers.ModelSerializer):
    reviewed_by_email = serializers.SerializerMethodField()
    client_slug = serializers.SerializerMethodField()
    client_id = serializers.SerializerMethodField()
    possible_duplicates = serializers.SerializerMethodField()

    class Meta:
        model = CompanyRegistration
        fields = ["id", "company_name", "trade_licence_number", "licence_authority", "country", "state", "city", "address", "contact_name",
                  "job_title", "email", "phone", "status", "email_verified_at", "reviewed_by_email", "reviewed_at",
                  "decision_message", "internal_note", "client_id", "client_slug", "possible_duplicates", "created_at", "updated_at"]
        read_only_fields = fields

    def get_reviewed_by_email(self, obj) -> str:
        return obj.reviewed_by.email if obj.reviewed_by_id else ""

    def get_client_slug(self, obj) -> str:
        return obj.client_tenant.slug if obj.client_tenant_id else ""

    def get_client_id(self, obj) -> str:
        return str(obj.client_tenant_id) if obj.client_tenant_id else ""

    def get_possible_duplicates(self, obj) -> list[dict]:
        return svc.duplicate_hints(obj) if obj.status in svc.OPEN else []


class DecisionInput(serializers.Serializer):
    organisation_name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    message = serializers.CharField(max_length=500, required=False, allow_blank=True)
    internal_note = serializers.CharField(max_length=1000, required=False, allow_blank=True)


class RegistrationViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Aries Admins review company registrations (operator organisation only)."""

    serializer_class = RegistrationSerializer
    permission_classes = [HasCapability]
    capabilities = {"list": "registrations.review", "retrieve": "registrations.review",
                    "approve": "registrations.review", "reject": "registrations.review"}

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return CompanyRegistration.objects.none()
        qs = CompanyRegistration.objects.filter(tenant=self.request.tenant).select_related("reviewed_by", "client_tenant")
        state = self.request.query_params.get("status")
        return qs.filter(status=state) if state else qs.exclude(status=CompanyRegistration.Status.UNVERIFIED)

    @extend_schema(request=DecisionInput, responses={200: RegistrationSerializer})
    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        reg = self.get_object()
        s = DecisionInput(data=request.data)
        s.is_valid(raise_exception=True)
        svc.approve(request, reg, s.validated_data.get("organisation_name", ""))
        reg.refresh_from_db()
        return Response(RegistrationSerializer(reg).data)

    @extend_schema(request=DecisionInput, responses={200: RegistrationSerializer})
    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        reg = self.get_object()
        s = DecisionInput(data=request.data)
        s.is_valid(raise_exception=True)
        message = (s.validated_data.get("message") or "").strip()
        if not message:
            raise DomainError("message_required", "Enter the message the registrant will see.", http_status=400)
        svc.reject(request, reg, message, s.validated_data.get("internal_note", ""))
        reg.refresh_from_db()
        return Response(RegistrationSerializer(reg).data)
