"""Project-level access, enforced server-side on every client-data query.

- Aries staff (CN-002 D4) and, since 2 Nov 2026, Client Users: with an access row of scope "projects" they see only the records
  of their active project assignments; with scope "company" (or, for assignments made before these rules, no row) the whole
  company. Records without a project are not visible to project-scoped Aries staff; a project-scoped Client User still sees
  what they submitted or requested themselves (`own`).
- Client Administrators: always every project of their company, including projects created later (no row is consulted).
- Tenant isolation and RLS apply to everyone in every case.
The access rows are `EngineerAccess` / `ProjectAssignment` (named for their first use; keyed by user and company, any role).
Callers pass the ORM path from their model to the project (e.g. "project", "part__project").
"""
from django.db.models import Q

from apps.tenancy.models import OPERATOR_ROLES, Role

# client roles whose project access the Client Administrator manages (legacy client roles behave as Client Users)
CLIENT_SCOPED_ROLES = {Role.CLIENT_USER, Role.CLIENT_ENGINEER, Role.PROCUREMENT, Role.AUDITOR}

from .models import EngineerAccess, ProjectAssignment


def allowed_project_ids(request) -> set | None:
    """None = not restricted; otherwise the set of project ids this member may see in the current tenant."""
    m = getattr(request, "membership", None)
    if m is None or m.tenant.kind != "client" or (m.role not in OPERATOR_ROLES and m.role not in CLIENT_SCOPED_ROLES):
        return None
    cached = getattr(request, "_allowed_projects", "unset")
    if cached != "unset":
        return cached
    request._allowed_projects = allowed_project_ids_for(m.tenant_id, m.user_id)
    return request._allowed_projects


def allowed_project_ids_for(tenant_id, user_id) -> set | None:
    """Same rule for a given client tenant and Aries staff or Client User (must run inside that tenant's RLS context)."""
    access = EngineerAccess.objects.filter(tenant_id=tenant_id, user_id=user_id).first()
    if access is None or access.scope == EngineerAccess.Scope.COMPANY:
        return None
    return set(ProjectAssignment.objects.filter(tenant_id=tenant_id, user_id=user_id, is_active=True)
               .values_list("project_id", flat=True))


def restrict(request, qs, path: str, own: str | None = None):
    """Limit qs to the caller's projects. `own` is the path to the creating user (e.g. "submitted_by"): a project-scoped
    Client User also keeps what they submitted or requested themselves, even without a project. Not applied to Aries staff."""
    ids = allowed_project_ids(request)
    if ids is None:
        return qs
    q = Q(**{f"{path}__in": ids})
    if own and request.membership.role in CLIENT_SCOPED_ROLES:
        q |= Q(**{own: request.user})
    return qs.filter(q)


def start_project_scoped(tenant, user, created_by=None) -> bool:
    """New Aries staff and new Client Users start with access to no projects (must run in the tenant's RLS context).
    A row kept from an earlier membership of the same person is left as it is. Returns True when a row was created."""
    _access, created = EngineerAccess.objects.get_or_create(tenant=tenant, user=user,
                                                            defaults={"scope": EngineerAccess.Scope.PROJECTS, "created_by": created_by})
    return created


def project_allowed(request, project_id) -> bool:
    ids = allowed_project_ids(request)
    return ids is None or (project_id is not None and project_id in ids)
