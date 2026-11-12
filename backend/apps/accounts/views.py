"""Authentication endpoints: token issue (per tenant), refresh, logout, current session."""
import logging

from django.contrib.auth import authenticate
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import exceptions, serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.audit.service import record
from apps.core.exceptions import DomainError
from apps.tenancy.context import tenant_context
from apps.tenancy.models import OPERATOR_ROLES, Membership, Role, Tenant
from apps.tenancy.permissions import capabilities_for, four_roles

from .authentication import load_membership

log = logging.getLogger(__name__)


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(trim_whitespace=False, write_only=True)
    tenant = serializers.SlugField(required=False, allow_blank=True, help_text="Tenant slug; required when the user belongs to more than one tenant.")


def tokens_for(membership: Membership) -> dict:
    refresh = RefreshToken.for_user(membership.user)
    for tok in (refresh, refresh.access_token):
        tok["mid"] = str(membership.pk)
        tok["tid"] = str(membership.tenant_id)
        tok["role"] = membership.role
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


def session_payload(membership: Membership) -> dict:
    from apps.tenancy import admin_workspace

    u = membership.user
    t = membership.tenant
    access = None
    if admin_workspace.is_admin_workspace(membership):  # shown as a banner: administrative access, not engineering sign-off
        op = Tenant.objects.filter(kind=Tenant.Kind.OPERATOR).order_by("created_at").first()
        access = {"admin_workspace": True, "file_decision": admin_workspace.file_decision(t), "aries_slug": op.slug if op else ""}
    elif admin_workspace.enabled() and admin_workspace.is_platform_admin(u) and t.kind == Tenant.Kind.OPERATOR:
        access = {"admin_workspace": False, "can_enter_companies": True, "aries_slug": t.slug}
    return {
        "user": {"id": str(u.pk), "email": u.email, "first_name": u.first_name, "last_name": u.last_name},
        "tenant": {"id": str(t.pk), "name": t.name, "slug": t.slug, "kind": t.kind, "hosting_model": t.hosting_model},
        "membership": {"id": str(membership.pk), "role": membership.role},
        "capabilities": capabilities_for(membership),
        "role_model": "four_roles" if four_roles() else "legacy",  # which roles user management offers
        **({"admin_access": access} if access else {}),
    }


class TokenView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    @extend_schema(request=LoginSerializer, tags=["auth"], responses={200: inline_serializer("TokenPair", {
        "access": serializers.CharField(), "refresh": serializers.CharField(), "session": serializers.DictField()})})
    def post(self, request):
        s = LoginSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        user = authenticate(request, email=s.validated_data["email"].strip().lower(), password=s.validated_data["password"])
        if user is None or not user.is_active:
            log.info("login failed")
            raise DomainError("invalid_credentials", "Email or password is incorrect.", http_status=status.HTTP_401_UNAUTHORIZED)
        from apps.tenancy import admin_workspace

        memberships = list(_active_memberships(user))  # provisions Aries Admin workspaces; hides them while switched off
        slug = s.validated_data.get("tenant")
        if slug:
            memberships = [m for m in memberships if m.tenant.slug == slug]
        elif admin_workspace.is_platform_admin(user):
            # the Aries Admin signs in to the Aries workspace and enters client companies from there
            memberships = [m for m in memberships if m.tenant.kind == Tenant.Kind.OPERATOR and m.role == Role.OPERATOR_ADMIN][:1] or memberships
        else:
            memberships = selectable_workspaces(memberships)
        if not memberships and not slug:
            # A verified registrant whose company is not approved yet (CN-002). Shown only after the password is correct.
            from apps.registrations.services import _what, registration_of

            reg = registration_of(user)
            if reg is not None and reg.status in ("pending", "rejected"):
                pending = reg.status == "pending"
                what = _what(reg)  # the company, or "your Aries staff account"
                raise DomainError(
                    "registration_pending" if pending else "registration_rejected",
                    f"The registration of {what} is waiting for Aries approval." if pending
                    else f"The registration of {what} was not approved.",
                    details={"company_name": what, "kind": reg.kind, "submitted_at": reg.email_verified_at,
                             "message": "" if pending else reg.decision_message},
                    http_status=status.HTTP_403_FORBIDDEN)
        if not memberships:
            raise DomainError("no_active_membership", "This account has no active access to the requested organisation.", http_status=status.HTTP_403_FORBIDDEN)
        if len(memberships) > 1:
            raise DomainError("tenant_selection_required", "Select an organisation to sign in to.",
                              details={"tenants": [{"slug": m.tenant.slug, "name": m.tenant.name} for m in memberships]},
                              http_status=status.HTTP_400_BAD_REQUEST)
        m = memberships[0]
        with tenant_context(m.tenant):
            record(None, "auth.login", actor=user, tenant=m.tenant, obj_type="membership", obj_id=m.pk)
        return Response({**tokens_for(m), "session": session_payload(m)})


class RefreshView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(request=inline_serializer("RefreshIn", {"refresh": serializers.CharField()}), tags=["auth"],
                   responses={200: inline_serializer("RefreshOut", {"access": serializers.CharField(), "refresh": serializers.CharField()})})
    def post(self, request):
        raw = request.data.get("refresh")
        try:
            old = RefreshToken(raw)
        except (TokenError, TypeError):
            raise DomainError("token_invalid", "Session expired. Please sign in again.", http_status=status.HTTP_401_UNAUTHORIZED)
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.filter(pk=old.get("user_id"), is_active=True).first()
        if user is None:
            raise DomainError("token_invalid", "Session expired. Please sign in again.", http_status=status.HTTP_401_UNAUTHORIZED)
        try:
            m = load_membership(user, old.get("mid"), old.get("tid"))  # membership re-checked on every refresh
        except exceptions.AuthenticationFailed as e:
            raise DomainError("membership_invalid", str(e.detail), http_status=status.HTTP_401_UNAUTHORIZED)
        old.blacklist()
        return Response(tokens_for(m))


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=inline_serializer("LogoutIn", {"refresh": serializers.CharField()}), tags=["auth"], responses={204: None})
    def post(self, request):
        try:
            RefreshToken(request.data.get("refresh")).blacklist()
        except (TokenError, TypeError):
            pass
        record(request, "auth.logout", obj_type="membership", obj_id=request.membership.pk)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["auth"], responses={200: dict})
    def get(self, request):
        return Response(session_payload(request.membership))


def _active_memberships(user):
    from apps.tenancy import admin_workspace

    admin_workspace.ensure_workspaces(user)  # Aries Admin: every active client company (switch on only)
    qs = Membership.objects.select_related("tenant").filter(
        user=user, is_active=True, tenant__status=Tenant.Status.ACTIVE).order_by("tenant__kind", "tenant__name")
    if admin_workspace.enabled() and admin_workspace.is_platform_admin(user):
        return qs
    return qs.exclude(role=Role.OPERATOR_ADMIN, tenant__kind=Tenant.Kind.CLIENT)  # workspaces unusable while switched off


def selectable_workspaces(memberships, keep=None):
    """Organisations offered at sign-in and in the switcher. Operator engineers, QA and support who are assigned to
    client organisations work inside those clients, so the Platform Operator organisation (which holds no client
    records) is not offered to them; their operator identity and access are unchanged. Administrators keep it, and so does
    anyone whose operator membership carries thumbnail-contract duties (Aries QA verifying contract authorizations,
    designated objection reviewers), which exist only in the operator organisation."""
    from apps.tenancy.permissions import capabilities_for

    memberships = list(memberships)
    assigned = any(m.tenant.kind == Tenant.Kind.CLIENT and m.role in OPERATOR_ROLES for m in memberships)
    def offered(m):
        operator_home = m.tenant.kind == Tenant.Kind.OPERATOR and m.role not in (Role.OPERATOR_ADMIN, Role.OPERATOR_MANAGER)
        if operator_home and "contracts.thumbnail_view" in capabilities_for(m):
            return True
        return not (assigned and operator_home) or (keep is not None and m.pk == keep.pk)
    return [m for m in memberships if offered(m)]


class MembershipsView(APIView):
    """The caller's own active memberships (organisation switcher and operator overview, UX-1).

    Counts are read inside each tenant's own context (row-level security applies); only organisations the user
    already belongs to are listed. No new access is granted here."""

    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["auth"], responses={200: inline_serializer("MembershipSummary", {
        "tenant": serializers.DictField(), "role": serializers.CharField(), "current": serializers.BooleanField(),
        "counts": serializers.DictField(child=serializers.IntegerField())}, many=True)})
    def get(self, request):
        from apps.parts.models import SparePart
        from apps.passports.models import DigitalPassport, PassportRevision

        out = []
        with_counts = request.query_params.get("counts") != "0"  # the organisation switcher needs names only
        for m in selectable_workspaces(_active_memberships(request.user), keep=request.membership):
            counts = {}
            if with_counts:
                with tenant_context(m.tenant):
                    counts = {
                        "parts": SparePart.objects.count(),
                        "passports": DigitalPassport.objects.count(),
                        "draft_revisions": PassportRevision.objects.filter(status=PassportRevision.Status.DRAFT).count(),
                    }
            out.append({"tenant": {"id": str(m.tenant_id), "name": m.tenant.name, "slug": m.tenant.slug, "kind": m.tenant.kind,
                                   "hosting_model": m.tenant.hosting_model},
                        "role": m.role, "current": m.pk == request.membership.pk, "counts": counts})
        return Response(out)


class SwitchView(APIView):
    """Switch the session to another organisation the user already belongs to (no password re-entry).

    Issues tokens for that membership and revokes the presented refresh token. Audited in both organisations."""

    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["auth"], request=inline_serializer("SwitchIn", {"tenant": serializers.SlugField(), "refresh": serializers.CharField()}),
                   responses={200: inline_serializer("SwitchOut", {"access": serializers.CharField(), "refresh": serializers.CharField(),
                                                                   "session": serializers.DictField()})})
    def post(self, request):
        slug = str(request.data.get("tenant", ""))
        target = _active_memberships(request.user).filter(tenant__slug=slug).first()
        if target is None:
            raise DomainError("no_active_membership", "This account has no active access to the requested organisation.", http_status=status.HTTP_403_FORBIDDEN)
        try:
            RefreshToken(request.data.get("refresh")).blacklist()
        except (TokenError, TypeError):
            pass
        record(request, "auth.switched_out", obj_type="membership", obj_id=request.membership.pk, data={"to": target.tenant.slug})
        with tenant_context(target.tenant):
            record(None, "auth.switched_in", actor=request.user, tenant=target.tenant, obj_type="membership", obj_id=target.pk,
                   data={"from": request.tenant.slug})
        return Response({**tokens_for(target), "session": session_payload(target)})
