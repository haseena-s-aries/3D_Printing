"""Invitations (W2 security item B: no account enumeration through membership administration).

- Client administrators invite by email and role. The response is identical whether or not the address already
  has an account, and nothing is changed for that account until its owner accepts.
- The invitee opens the emailed link. An existing account proves ownership with its password; a new address sets
  a password and creates the account. Errors at acceptance are generic.
- Operator staff and accounts that belong to another organisation cannot join through an invitation (W1 rule:
  those are added by the platform operator). The refusal is shown only to the account owner and audited on the
  operator side, not in the inviting organisation.
- Only a SHA-256 hash of the token is stored; tokens are single-use and expire.

Email delivery uses Django's email backend (console in development; a production provider is not provisioned).
Showing the link to the inviting administrator is a development aid, controlled by INVITATION_LINK_IN_RESPONSE,
and must stay off where real email is configured, otherwise the inviter could act as the invitee.
"""
import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.audit.service import record
from apps.core.exceptions import DomainError, error_response

from . import membership_policy as policy
from .context import tenant_context
from .models import OPERATOR_ROLES, Invitation, Membership, Role, Tenant
from .permissions import HasCapability

User = get_user_model()
INVALID = ("invitation_invalid", "This invitation cannot be accepted with these details. It may have expired or been withdrawn.")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def accept_url(token: str) -> str:
    return f"{settings.WEB_BASE_URL.rstrip('/')}/invite/{token}"


def issue_invitation(request, tenant: Tenant, email: str, role: str) -> tuple[Invitation, str]:
    """Create (replacing any pending one) and email an invitation; only the token hash is stored. Audited in the
    caller's tenant and, when an Aries Admin invites into a client organisation, in that organisation too."""
    token = secrets.token_urlsafe(32)
    with transaction.atomic():
        Invitation.objects.filter(tenant=tenant, email=email, status=Invitation.Status.PENDING).update(status=Invitation.Status.REVOKED)
        inv = Invitation.objects.create(tenant=tenant, email=email, role=role, token_hash=token_hash(token), invited_by=request.user,
                                        expires_at=timezone.now() + timedelta(days=settings.INVITATION_DAYS))
        cross = getattr(request, "tenant", None) is not None and request.tenant.pk != tenant.pk
        record(request, "invitation.created", obj_type="invitation", obj_id=inv.pk,
               data={"email": email, "role": role, **({"client": tenant.slug} if cross else {})})
        if cross:
            with tenant_context(tenant):
                record(request, "invitation.created", tenant=tenant, obj_type="invitation", obj_id=inv.pk,
                       data={"email": email, "role": role, "by_operator": True})
    send_mail(
        subject=f"Invitation to {tenant.name} on the Digital Passport Platform",
        message=(f"You have been invited to join {tenant.name} as {Role(role).label}.\n\n"
                 f"Open this link to accept: {accept_url(token)}\n\n"
                 f"The link expires on {inv.expires_at:%d %b %Y %H:%M} UTC. If you did not expect this, ignore this email."),
        from_email=settings.DEFAULT_FROM_EMAIL, recipient_list=[email], fail_silently=True,
    )
    return inv, token


class InvitationSerializer(serializers.ModelSerializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=Role.choices)
    state = serializers.SerializerMethodField(help_text="pending, expired, accepted or revoked")
    invite_url = serializers.SerializerMethodField(help_text="Development only (INVITATION_LINK_IN_RESPONSE); emailed otherwise.")

    class Meta:
        model = Invitation
        fields = ["id", "email", "role", "state", "expires_at", "created_at", "accepted_at", "invite_url"]
        read_only_fields = ["id", "state", "expires_at", "created_at", "accepted_at", "invite_url"]

    def get_state(self, obj) -> str:
        if obj.status == Invitation.Status.PENDING and obj.expires_at <= timezone.now():
            return "expired"
        return obj.status

    def get_invite_url(self, obj) -> str | None:
        token = self.context.get("token")
        # Both checks, at request time: a mistakenly enabled setting never exposes links when DEBUG is off.
        return accept_url(token) if token and settings.DEBUG and settings.INVITATION_LINK_IN_RESPONSE else None


class InvitationViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    """Invitations of the current organisation. Creating one never reveals whether the address has an account."""

    serializer_class = InvitationSerializer
    permission_classes = [HasCapability]
    capabilities = {"list": "users.manage", "create": "users.manage", "revoke": "users.manage"}

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Invitation.objects.none()
        return Invitation.objects.filter(tenant=self.request.tenant)[:100] if self.action == "list" else Invitation.objects.filter(tenant=self.request.tenant)

    def create(self, request, *args, **kwargs):
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        tenant, actor = request.tenant, request.membership
        email, role = s.validated_data["email"].strip().lower(), s.validated_data["role"]
        # Invitations add organisation members; operator staff are assigned directly by operator administrators.
        if role not in policy.roles_assignable(actor, tenant) or (tenant.kind == Tenant.Kind.CLIENT and role in OPERATOR_ROLES):
            raise DomainError("role_not_allowed", "This role cannot be assigned here.", http_status=403)
        # Membership of this organisation is visible to its administrators anyway, so this reveals nothing new.
        if Membership.objects.filter(tenant=tenant, user__email__iexact=email).exists():
            raise DomainError("already_member", "This person is already a member of your organisation.", http_status=400)
        inv, token = issue_invitation(request, tenant, email, role)
        return Response(InvitationSerializer(inv, context={"token": token}).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses={200: InvitationSerializer})
    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        inv = self.get_object()
        if inv.status != Invitation.Status.PENDING:
            raise DomainError("invitation_not_pending", "Only pending invitations can be withdrawn.", http_status=400)
        inv.status = Invitation.Status.REVOKED
        inv.save(update_fields=["status", "updated_at"])
        record(request, "invitation.revoked", obj_type="invitation", obj_id=inv.pk, data={"email": inv.email})
        return Response(InvitationSerializer(inv).data)


class AcceptSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    password = serializers.CharField(trim_whitespace=False, write_only=True)


def _pending(token: str) -> Invitation:
    inv = Invitation.objects.select_related("tenant").filter(token_hash=token_hash(token), status=Invitation.Status.PENDING,
                                                               expires_at__gt=timezone.now(), tenant__status=Tenant.Status.ACTIVE).first()
    if inv is None:
        raise DomainError(*INVALID, http_status=400)
    return inv


class InvitationAcceptView(APIView):
    """Public: view (GET) and accept (POST) an invitation by its token. Rate-limited like sign-in."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    @extend_schema(tags=["auth"], responses={200: inline_serializer("InvitationInfo", {
        "organisation": serializers.CharField(), "role": serializers.CharField(), "email": serializers.EmailField(),
        "expires_at": serializers.DateTimeField()})})
    def get(self, request, token):
        inv = _pending(token)
        # Nothing about whether the address already has an account.
        return Response({"organisation": inv.tenant.name, "role": inv.role, "email": inv.email, "expires_at": inv.expires_at})

    @extend_schema(tags=["auth"], request=AcceptSerializer, responses={200: inline_serializer("InvitationAccepted", {
        "status": serializers.CharField(), "organisation": serializers.CharField()})})
    def post(self, request, token):
        s = AcceptSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic():
            inv = _pending(token)
            # Lock, then re-check: a concurrent acceptance that committed first leaves nothing pending here.
            if not Invitation.objects.select_for_update().filter(pk=inv.pk, status=Invitation.Status.PENDING).exists():
                raise DomainError(*INVALID, http_status=400)
            user = User.objects.filter(email__iexact=inv.email).first()
            if user is not None:
                if not user.is_active or not user.check_password(s.validated_data["password"]):
                    raise DomainError(*INVALID, http_status=400)
                elsewhere = Membership.objects.filter(user=user).exclude(tenant=inv.tenant).exists()
                if policy.is_operator_staff(user) or elsewhere:
                    operator = Tenant.objects.filter(kind=Tenant.Kind.OPERATOR).first()
                    if operator:
                        with tenant_context(operator):
                            record(None, "invitation.acceptance_refused", actor=user, tenant=operator, obj_type="invitation",
                                   obj_id=inv.pk, data={"organisation": inv.tenant.slug})
                    # Returned, not raised, so the audit record above is kept.
                    return error_response("invitation_not_applicable",
                                          "This account cannot join an organisation through an invitation. Ask the platform operator.", 403)
                if Membership.objects.filter(user=user, tenant=inv.tenant).exists():
                    raise DomainError(*INVALID, http_status=400)
            else:
                try:
                    validate_password(s.validated_data["password"])
                except ValidationError as e:
                    raise serializers.ValidationError({"password": list(e.messages)})
                user = User.objects.create_user(email=inv.email, password=s.validated_data["password"],
                                                first_name=s.validated_data.get("first_name", ""), last_name=s.validated_data.get("last_name", ""))
            m = Membership.objects.create(user=user, tenant=inv.tenant, role=inv.role, created_by=inv.invited_by)
            from apps.projects.scoping import CLIENT_SCOPED_ROLES, start_project_scoped

            if m.role in CLIENT_SCOPED_ROLES:  # 2 Nov 2026: the Client Administrator then assigns projects (Users page)
                with tenant_context(inv.tenant):
                    start_project_scoped(inv.tenant, user, inv.invited_by)
            inv.status, inv.accepted_at = Invitation.Status.ACCEPTED, timezone.now()
            inv.save(update_fields=["status", "accepted_at", "updated_at"])
            with tenant_context(inv.tenant):
                record(None, "invitation.accepted", actor=user, tenant=inv.tenant, obj=m, data={"role": m.role})
        return Response({"status": "accepted", "organisation": inv.tenant.name})
