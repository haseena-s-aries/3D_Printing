"""Tenant-aware JWT authentication (HYB-010, MOB-006).

Each access token carries the membership it was issued for (claim `mid`) and its tenant (`tid`).
On every request the membership is re-loaded and checked: active membership, active tenant,
active user, matching tenant. The tenant is then set as the PostgreSQL row-level security context.
The client can never choose the tenant through headers or request bodies.
"""
from rest_framework import exceptions
from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.tenancy.context import set_tenant_context, set_user_context
from apps.tenancy.models import Membership, Tenant


def load_membership(user, mid, tid):
    try:
        m = Membership.objects.select_related("tenant").get(pk=mid, user=user)
    except (Membership.DoesNotExist, ValueError, TypeError):
        raise exceptions.AuthenticationFailed("Membership is no longer valid.", code="membership_invalid")
    if not m.is_active or str(m.tenant_id) != str(tid):
        raise exceptions.AuthenticationFailed("Membership is no longer valid.", code="membership_invalid")
    if m.tenant.status != Tenant.Status.ACTIVE:
        raise exceptions.AuthenticationFailed("This organisation is suspended.", code="tenant_suspended")
    from apps.tenancy import admin_workspace

    if not admin_workspace.usable(m):  # Aries Admin company workspaces exist only while ADMIN_WORKSPACE_ENABLED is on
        raise exceptions.AuthenticationFailed("Membership is no longer valid.", code="membership_invalid")
    return m


class TenantJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        user, token = result
        if not user.is_active:
            raise exceptions.AuthenticationFailed("User is inactive.", code="user_inactive")
        membership = load_membership(user, token.get("mid"), token.get("tid"))
        request._request.membership = membership
        request._request.tenant = membership.tenant
        set_tenant_context(membership.tenant_id)
        set_user_context(user.pk)
        return user, token
