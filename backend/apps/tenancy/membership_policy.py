"""Who may add, change or deactivate a membership. Every membership write goes through these checks.

Ownership:
- Operator-owned: any membership with an operator role, any membership in the operator tenant, and any account of
  operator staff (a user with an active operator-tenant membership). Only operator administrators, acting from the
  operator organisation, manage these.
- Organisation-owned: client-role memberships of client users in a client tenant. The client's own administrators
  manage these (and operator administrators may, as platform administrators).

Operator assignments to client organisations (OQ-02) are ordinary memberships managed by operator administrators.
Support-access grants with purpose and expiry (ACC-001) are a different mechanism that is not implemented: consent
rules are open (OQ-37). Nothing here grants or models them.
"""
from django.contrib.auth import get_user_model

from apps.core.exceptions import DomainError

from .models import CLIENT_ROLES, OPERATOR_ROLES, Membership, Role, Tenant

User = get_user_model()

# Operator roles that may be assigned inside a client organisation (fulfilment and support work, OQ-02).
# Operator administration itself always happens in the operator organisation.
CLIENT_ASSIGNABLE_OPERATOR_ROLES = {Role.OPERATOR_ENGINEER, Role.OPERATOR_QA, Role.OPERATOR_SUPPORT}

OPERATOR_OWNED = "operator"
ORGANISATION_OWNED = "organisation"


def is_operator_staff(user) -> bool:
    return user is not None and Membership.objects.filter(user=user, tenant__kind=Tenant.Kind.OPERATOR, is_active=True).exists()


def owner_of(m: Membership) -> str:
    if m.role in OPERATOR_ROLES or m.tenant.kind == Tenant.Kind.OPERATOR or is_operator_staff(m.user):
        return OPERATOR_OWNED
    return ORGANISATION_OWNED


def is_platform_admin(actor: Membership) -> bool:
    return actor.role == Role.OPERATOR_ADMIN and actor.tenant.kind == Tenant.Kind.OPERATOR


def roles_assignable(actor: Membership, tenant: Tenant) -> set:
    """Roles this actor may assign in `tenant`. With the four-role model, legacy roles are never assigned again (existing
    memberships keep them until mapped)."""
    from .permissions import LEGACY_ROLES, four_roles

    roles = _roles_assignable(actor, tenant)
    return roles - LEGACY_ROLES if four_roles() else roles


def _roles_assignable(actor: Membership, tenant: Tenant) -> set:
    if tenant.kind == Tenant.Kind.OPERATOR:
        return set(OPERATOR_ROLES) if is_platform_admin(actor) else set()
    if is_platform_admin(actor):
        return set(CLIENT_ROLES) | CLIENT_ASSIGNABLE_OPERATOR_ROLES
    if actor.role == Role.CLIENT_ADMIN and actor.tenant_id == tenant.pk:
        return set(CLIENT_ROLES)
    return set()


def _deny(code: str, message: str, status: int = 403):
    raise DomainError(code, message, http_status=status)


def can_manage(actor: Membership, target: Membership) -> bool:
    """Whether `actor` may change or deactivate `target` (used for checks and to tell the UI)."""
    if target.pk == actor.pk:
        return False
    if owner_of(target) == OPERATOR_OWNED:
        return is_platform_admin(actor)
    return is_platform_admin(actor) or (actor.role == Role.CLIENT_ADMIN and actor.tenant_id == target.tenant_id)


def check_update(actor: Membership, target: Membership, *, role: str | None, is_active: bool | None) -> None:
    if target.pk == actor.pk:
        _deny("cannot_change_self", "You cannot change your own role or deactivate yourself.", 400)
    if not can_manage(actor, target):
        if owner_of(target) == OPERATOR_OWNED:
            _deny("operator_staff_managed_by_operator", "Platform operator staff are managed by the operator's administrators.")
        _deny("permission_denied", "You cannot manage this membership.")
    if role is not None and role != target.role:
        if role not in roles_assignable(actor, target.tenant):
            _deny("role_not_allowed", "This role cannot be assigned here.")
        # A membership keeps its role family: client users cannot be turned into operator staff or vice versa.
        if (role in OPERATOR_ROLES) != (target.role in OPERATOR_ROLES):
            _deny("role_family_change", "Operator and client roles cannot be exchanged; add a separate membership instead.")


def check_add(actor: Membership, tenant: Tenant, user, role: str) -> None:
    if role not in roles_assignable(actor, tenant):
        _deny("role_not_allowed", "This role cannot be assigned here.")
    if user is not None and user.pk == actor.user_id and tenant.pk != actor.tenant_id:
        # No self-assignment (CN-002 D9): an administrator cannot give their own account access to a client.
        _deny("cannot_assign_self", "You cannot assign your own account to an organisation.", 400)
    if role in OPERATOR_ROLES and tenant.kind == Tenant.Kind.CLIENT and not is_operator_staff(user):
        _deny("not_operator_staff", "Only existing operator staff can be assigned operator roles in a client organisation.", 400)
    if user is None or is_platform_admin(actor):
        return
    # A client administrator may add new people, or people who belong only to this organisation. Accounts owned by the
    # operator or by another organisation are added by the platform operator. One message for both, so the response
    # does not reveal which organisation an address belongs to.
    elsewhere = Membership.objects.filter(user=user).exclude(tenant=tenant).exists()
    if elsewhere or is_operator_staff(user):
        _deny("user_not_addable", "This account cannot be added by your organisation. Ask the platform operator to add it.")
