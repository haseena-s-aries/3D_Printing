"""Data for the assistant, always with the same visibility as the screens (nothing the person could not open there):

- Aries Admin and Aries Manager in the Aries workspace: everything. Every client request; spare parts, passports, client
  companies, users and registrations of every company, as the summaries their screens show (no file content).
- Aries Engineers, QA and support: requests through the request queue's own rule (assigned clients and projects;
  `_visible_envelopes`), spare parts and passports of their assigned clients limited to their assigned projects.
- Members of a client company (and Aries staff working inside one): that company's records, limited exactly as the
  dashboard summary and the request list limit them (project-scoped members: their projects, and what they submitted).
"""
from dataclasses import dataclass

from django.db.models import Q

from apps.parts.models import SparePart
from apps.passports.models import DigitalPassport
from apps.projects.scoping import allowed_project_ids, allowed_project_ids_for, restrict
from apps.servicerequests import services as svc
from apps.servicerequests.models import ClientRequest, Quotation, RequestEnvelope
from apps.tenancy.context import tenant_context
from apps.tenancy.models import OPERATOR_ROLES, Membership, Role, Tenant
from apps.tenancy.permissions import has_capability

FULL_ROLES = {Role.OPERATOR_ADMIN, Role.OPERATOR_MANAGER}
LIMIT = 8


@dataclass(frozen=True)
class Scope:
    tenant: Tenant
    role: str
    full: bool           # Aries Admin / Manager in the Aries workspace: may search everything
    staff: bool          # Aries staff who handle requests (in the Aries workspace or inside a client company)
    client_member: bool  # a member of the client company they are in, who may view its requests
    in_client: bool      # working inside a client company
    users: bool          # may see the people of their organisation

    @property
    def audience(self) -> set[str]:
        if self.full:
            return {"admin", "aries"}
        return {"aries"} if self.role in OPERATOR_ROLES else {"client"}


def scope_of(request) -> Scope:
    m = request.membership
    tenant = m.tenant
    operator = tenant.kind == Tenant.Kind.OPERATOR
    full = operator and m.role in FULL_ROLES
    return Scope(tenant=tenant, role=m.role, full=full,
                 staff=full or (m.role in OPERATOR_ROLES and has_capability(request, "requests.handle")),
                 client_member=not operator and m.role not in OPERATOR_ROLES and has_capability(request, "requests.view"),
                 in_client=not operator, users=has_capability(request, "users.view"))


def _row(title, subtitle="", link=None, **extra) -> dict:
    return {"title": title, "subtitle": subtitle, "link": link, **extra}


def _terms_q(terms, fields) -> Q:
    """Every term must match one of the fields."""
    q = Q()
    for t in terms:
        one = Q()
        for f in fields:
            one |= Q(**{f"{f}__icontains": t})
        q &= one
    return q


# ------------------------------------------------------------------ requests

def _status_label(status: str) -> str:
    try:
        return ClientRequest.Status(status).label
    except ValueError:
        return status.replace("_", " ")


def _kind_label(kind: str) -> str:
    try:
        return ClientRequest.Kind(kind).label
    except ValueError:
        return kind


def requests(request, scope: Scope, *, terms=(), statuses=None, open_only=False, ref=None, limit=LIMIT) -> list[dict]:
    """Requests the person can open, newest first. `ref`: an intake number (ARQ-...) or a client reference (MR/DR/AR-...)."""
    if scope.staff:
        from apps.servicerequests.api import (
            _visible_envelopes,  # the request queue's own visibility rule
        )

        op = svc.operator_tenant()
        with tenant_context(op):
            qs = RequestEnvelope.objects.all().order_by("-submitted_at")
            if ref:
                qs = qs.filter(Q(intake_number__iexact=ref) | Q(reference__iexact=ref))
            if statuses:
                qs = qs.filter(status__in=statuses)
            if open_only:
                qs = qs.filter(status__in=svc.OPEN)
            if terms:
                qs = qs.filter(_terms_q(terms, ["intake_number", "reference", "client_name", "part_number", "part_name"]))
        rows = _visible_envelopes(request, op, qs)
        return [_row(f"{e.intake_number or e.reference} · {e.client_name}",
                     " · ".join(x for x in (_kind_label(e.kind), _status_label(e.status), e.part_number, e.part_name) if x),
                     f"/incoming/{e.pk}", status=e.status, kind=e.kind, client_id=str(e.client_tenant_id),
                     request_id=str(e.request_id), client=e.client_name, number=e.intake_number or e.reference)
                for e in (rows if limit is None else rows[:limit])]
    if scope.client_member:
        qs = ClientRequest.objects.filter(tenant=scope.tenant).order_by("-created_at")
        ids = allowed_project_ids(request)  # the request list's rule (ClientRequestViewSet)
        if ids is not None:
            qs = qs.filter(Q(project_id__in=ids) | Q(part__project_id__in=ids) | Q(requested_by=request.user))
        if ref:
            qs = qs.filter(reference__iexact=ref)
        if statuses:
            qs = qs.filter(status__in=statuses)
        if open_only:
            qs = qs.filter(status__in=svc.OPEN)
        if terms:
            qs = qs.filter(_terms_q(terms, ["reference", "part_number", "part_name", "client_reference"]))
        qs = qs if limit is None else qs[:limit]
        return [_row(f"{r.reference}", " · ".join(x for x in (r.get_kind_display(), r.get_status_display(), r.part_number, r.part_name) if x),
                     f"/requests/{r.pk}", status=r.status, kind=r.kind, client_id=str(scope.tenant.pk), request_id=str(r.pk),
                     client=scope.tenant.name, number=r.reference) for r in qs]
    return []


def quotation_state(client_id: str, request_id: str) -> str | None:
    """The latest quotation's status for a request (sent / accepted / rejected / withdrawn / superseded), or None."""
    with tenant_context(client_id):
        q = Quotation.objects.filter(request_id=request_id).order_by("-number").first()
        return q.status if q else None


def passport_state(client_id: str, request_id: str) -> tuple[str, str] | None:
    """(publication state, eligibility) of the requested part's passport now."""
    with tenant_context(client_id):
        cr = ClientRequest.all_objects.filter(pk=request_id).select_related("part").first()
        if cr is None or cr.part_id is None:
            return None
        p = DigitalPassport.objects.filter(part_id=cr.part_id).first()
        return (p.get_publication_state_display(), p.get_manufacturing_eligibility_display()) if p else None


# ------------------------------------------------------------------ parts and passports

def _client_scopes(request, scope: Scope):
    """(tenant, project ids or None, link-able) for each company whose parts the person may see."""
    if scope.in_client:
        yield scope.tenant, "restrict", True
        return
    if scope.full:
        for t in Tenant.objects.filter(kind=Tenant.Kind.CLIENT).order_by("name"):
            yield t, None, False
        return
    if scope.staff:
        ids = Membership.objects.filter(user=request.user, role__in=OPERATOR_ROLES, is_active=True,
                                        tenant__kind=Tenant.Kind.CLIENT).values_list("tenant_id", flat=True)
        for t in Tenant.objects.filter(pk__in=list(ids)).order_by("name"):
            with tenant_context(t):
                allowed = allowed_project_ids_for(t.pk, request.user.pk)
            yield t, allowed, False


def _parts_qs(request, tenant, allowed):
    qs = SparePart.objects.filter(tenant=tenant)
    if allowed == "restrict":
        return restrict(request, qs, "project", own="submitted_by")
    return qs if allowed is None else qs.filter(project_id__in=allowed)


def _passports_qs(request, tenant, allowed):
    qs = DigitalPassport.objects.filter(tenant=tenant)
    if allowed == "restrict":
        return restrict(request, qs, "part__project", own="part__submitted_by")
    return qs if allowed is None else qs.filter(part__project_id__in=allowed)


def parts(request, scope: Scope, *, terms=(), limit=LIMIT) -> list[dict]:
    out = []
    for t, allowed, linkable in _client_scopes(request, scope):
        with tenant_context(t):
            qs = _parts_qs(request, t, allowed).select_related("passport").order_by("part_number")
            if terms:
                qs = qs.filter(_terms_q(terms, ["part_number", "name", "manufacturer", "original_material"]))
            for p in qs[: LIMIT if limit is None else limit]:
                pp = getattr(p, "passport", None)
                sub = f"{pp.passport_number} · {pp.get_publication_state_display()}" if pp else "No passport"
                link = f"/parts/{p.pk}" if linkable else (f"/admin/inventory?view=parts&search={p.part_number}" if scope.full else None)
                out.append(_row(f"{p.part_number} · {p.name}", f"{t.name} · {sub}" if not scope.in_client else sub, link))
        if limit is not None and len(out) >= limit:
            break
    return out if limit is None else out[:limit]


def passports(request, scope: Scope, *, terms=(), ref=None, limit=LIMIT) -> list[dict]:
    out = []
    for t, allowed, linkable in _client_scopes(request, scope):
        with tenant_context(t):
            qs = _passports_qs(request, t, allowed).select_related("part").order_by("passport_number")
            if ref:
                qs = qs.filter(passport_number__iexact=ref)
            if terms:
                qs = qs.filter(_terms_q(terms, ["passport_number", "title", "part__part_number", "part__name"]))
            for p in qs[:limit or LIMIT]:
                state = f"{p.get_publication_state_display()} · {p.get_manufacturing_eligibility_display()} · {p.get_data_captured_display()}"
                link = f"/passports/{p.pk}" if linkable else ("/passport-register" if scope.full else None)
                out.append(_row(f"{p.passport_number} · {p.part.part_number} {p.part.name}",
                                f"{t.name} · {state}" if not scope.in_client else state, link,
                                publication=p.publication_state, eligibility=p.manufacturing_eligibility))
        if len(out) >= (limit or LIMIT):
            break
    return out[: limit or LIMIT]


def count_parts_passports(request, scope: Scope) -> tuple[int, int]:
    n_parts = n_passports = 0
    for t, allowed, _ in _client_scopes(request, scope):
        with tenant_context(t):
            n_parts += _parts_qs(request, t, allowed).count()
            n_passports += _passports_qs(request, t, allowed).count()
    return n_parts, n_passports


# ------------------------------------------------------------------ companies, people, registrations (Aries Admin / Manager)

def clients(scope: Scope, *, terms=(), limit=LIMIT) -> list[dict]:
    if not scope.full:
        return []
    qs = Tenant.objects.filter(kind=Tenant.Kind.CLIENT).order_by("name")
    if terms:
        qs = qs.filter(_terms_q(terms, ["name", "slug"]))
    return [_row(t.name, f"{t.get_status_display()} · {t.get_hosting_model_display()}", f"/clients/{t.pk}")
            for t in (qs if limit is None else qs[:limit])]


def users(request, scope: Scope, *, terms=(), inactive=None, limit=LIMIT) -> list[dict]:
    """Aries Admin / Manager: people of every organisation; others who may see users: their own organisation's."""
    if not (scope.full or scope.users):
        return []
    qs = Membership.objects.select_related("user", "tenant").order_by("user__email")
    if not scope.full:
        qs = qs.filter(tenant=scope.tenant)
    if terms:
        qs = qs.filter(_terms_q(terms, ["user__email", "user__first_name", "user__last_name", "tenant__name"]))
    if inactive is not None:
        qs = qs.filter(is_active=not inactive)
    out = []
    for m in (qs if limit is None else qs[:limit]):
        name = " ".join(x for x in (m.user.first_name, m.user.last_name) if x)
        link = "/users" if m.tenant_id == scope.tenant.pk else (f"/clients/{m.tenant_id}?tab=users" if m.tenant.kind == Tenant.Kind.CLIENT else "/users")
        out.append(_row(f"{m.user.email}{f' ({name})' if name else ''}",
                        f"{m.tenant.name} · {Role(m.role).label if m.role in Role.values else m.role} · {'Active' if m.is_active else 'Inactive'}", link))
    return out


def registrations(request, scope: Scope, *, terms=(), pending_only=False, limit=LIMIT) -> list[dict]:
    if not (scope.full and has_capability(request, "registrations.review")):
        return []
    from apps.registrations.models import CompanyRegistration

    with tenant_context(svc.operator_tenant()):
        qs = CompanyRegistration.objects.exclude(status=CompanyRegistration.Status.UNVERIFIED).order_by("-created_at")
        if pending_only:
            qs = qs.filter(status=CompanyRegistration.Status.PENDING)
        if terms:
            qs = qs.filter(_terms_q(terms, ["company_name", "contact_name", "email"]))
        return [_row(r.company_name, f"{r.contact_name} · {r.email} · {r.get_status_display()}", f"/registrations/{r.pk}")
                for r in (qs if limit is None else qs[:limit])]
