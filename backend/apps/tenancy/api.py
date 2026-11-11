"""Client (tenant) management and user management.

Memberships and tenants are not row-level-security tables (they are needed to resolve the tenant
at sign-in), so every query here is explicitly scoped and covered by cross-tenant tests.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.service import record
from apps.core.exceptions import DomainError

from . import membership_policy as policy
from .membership_policy import CLIENT_ASSIGNABLE_OPERATOR_ROLES
from .context import tenant_context
from .models import Membership, Role, Tenant
from .permissions import HasCapability
from .profile import CompanyProfileSerializer, contact_status, profile_of

User = get_user_model()


class ClientSerializer(serializers.ModelSerializer):
    member_count = serializers.SerializerMethodField()
    profile_complete = serializers.SerializerMethodField(help_text="All required company-profile fields are filled in.")

    class Meta:
        model = Tenant
        fields = ["id", "name", "slug", "status", "hosting_model", "region_code", "member_count", "profile_complete",
                  "created_at", "updated_at"]
        read_only_fields = ["id", "slug", "member_count", "profile_complete", "created_at", "updated_at"]
        extra_kwargs = {"region_code": {"help_text": "Informational only; region and residency rules are open (OQ-71)."},
                        "slug": {"help_text": "Short identifier used at sign-in; set at creation and not changed afterwards."}}

    def get_member_count(self, obj) -> int:
        from . import admin_workspace

        return admin_workspace.without_workspaces(obj.memberships.filter(is_active=True)).count()

    def get_profile_complete(self, obj) -> bool:
        return profile_of(obj)["complete"]


class ClientCreateSerializer(CompanyProfileSerializer):
    """Aries Admin creation of a client organisation: the same company profile as self-registration, plus the
    Aries-controlled short identifier and hosting configuration."""

    slug = serializers.RegexField(r"^[a-z0-9][a-z0-9-]{1,58}[a-z0-9]$", max_length=60, error_messages={
        "invalid": "Use 3-60 lowercase letters, numbers and hyphens (not at the start or end)."})
    hosting_model = serializers.ChoiceField(choices=Tenant.HostingModel.choices, default=Tenant.HostingModel.SHARED)
    region_code = serializers.CharField(max_length=40, required=False, allow_blank=True)
    invite_contact = serializers.BooleanField(default=True, help_text=(
        "Email the primary contact an invitation to become Client Administrator. The contact is not active or verified "
        "until they accept the emailed link."))

    def validate_slug(self, value):
        if Tenant.objects.filter(slug=value).exists():
            raise serializers.ValidationError("This short identifier is already used.")
        return value


class MemberSerializer(serializers.Serializer):
    """A user's membership in the current tenant (or a target client tenant for operator admins)."""

    id = serializers.UUIDField(read_only=True)
    email = serializers.EmailField()
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    role = serializers.ChoiceField(choices=Role.choices)
    is_active = serializers.BooleanField(required=False, default=True)
    password = serializers.CharField(write_only=True, required=False, allow_blank=True, trim_whitespace=False,
                                     help_text="Initial password for a new user; ignored for existing users. Invitation flow is a later item.")
    created_at = serializers.DateTimeField(read_only=True)
    managed_by = serializers.ChoiceField(choices=[policy.OPERATOR_OWNED, policy.ORGANISATION_OWNED], read_only=True,
                                         help_text="operator: platform operator staff, managed only by operator administrators.")
    can_manage = serializers.BooleanField(read_only=True, help_text="Whether the caller may change or deactivate this membership.")
    part_submission_allowed = serializers.BooleanField(read_only=True, help_text=(
        "Client Users only: the Client Administrator allows this person to submit and clone spare parts (CN-003)."))
    inventory_import_allowed = serializers.BooleanField(read_only=True, help_text=(
        "Client Administrators only: an Aries Admin allows bulk inventory import (CN-007)."))
    technical_access = serializers.BooleanField(read_only=True, help_text="Client Users: technical submissions (four-role model).")
    procurement_access = serializers.BooleanField(read_only=True, help_text="Client Users: procurement activities.")
    audit_access = serializers.BooleanField(read_only=True, help_text="Client Users: read-only audit trail.")
    document_access = serializers.ChoiceField(choices=Membership.DocumentAccess.choices, read_only=True,
                                              help_text="Client Users: none, previews only, or full documents.")
    contract_reviewer = serializers.BooleanField(read_only=True, help_text=(
        "Aries Engineers in the Aries organisation: CanReviewContract, set by an Aries Admin."))
    qa_permitted = serializers.BooleanField(read_only=True, help_text="Aries Engineers: CanPerformQA, set by an Aries Admin.")
    engineering_authoring = serializers.BooleanField(read_only=True, help_text="Aries Engineers: CanAuthorEngineering, set by an Aries Admin.")
    legacy_role = serializers.BooleanField(read_only=True, help_text="A role of the earlier model, kept until the membership is mapped.")

    def to_representation(self, m):
        from .permissions import LEGACY_ROLES

        actor = self.context.get("actor")
        return {"id": str(m.pk), "email": m.user.email, "first_name": m.user.first_name, "last_name": m.user.last_name,
                "role": m.role, "is_active": m.is_active, "created_at": m.created_at,
                "managed_by": policy.owner_of(m), "can_manage": bool(actor) and policy.can_manage(actor, m),
                "part_submission_allowed": m.part_submission_allowed, "inventory_import_allowed": m.inventory_import_allowed,
                "technical_access": m.technical_access, "procurement_access": m.procurement_access, "audit_access": m.audit_access,
                "document_access": m.document_access, "contract_reviewer": m.contract_reviewer, "qa_permitted": m.qa_permitted,
                "engineering_authoring": m.engineering_authoring, "legacy_role": m.role in LEGACY_ROLES}


class MemberUpdateSerializer(serializers.Serializer):
    """Changes allowed on an existing membership. Strict types: "false" is false, unknown roles are rejected."""

    role = serializers.ChoiceField(choices=Role.choices, required=False)
    is_active = serializers.BooleanField(required=False)
    part_submission_allowed = serializers.BooleanField(required=False)
    inventory_import_allowed = serializers.BooleanField(required=False, help_text=(
        "Client Administrators only; set by an Aries Admin (CN-007 bulk inventory import)."))
    technical_access = serializers.BooleanField(required=False)
    procurement_access = serializers.BooleanField(required=False)
    audit_access = serializers.BooleanField(required=False)
    document_access = serializers.ChoiceField(choices=Membership.DocumentAccess.choices, required=False)
    contract_reviewer = serializers.BooleanField(required=False, help_text=(
        "CanReviewContract for an Aries Engineer in the Aries organisation; Aries Admin only. Objection review still needs the "
        "deployment-designated authority."))
    qa_permitted = serializers.BooleanField(required=False, help_text=(
        "CanPerformQA for an Aries Engineer; Aries Admin only. In client companies it is also set under Engineers & Access."))
    engineering_authoring = serializers.BooleanField(required=False, help_text=(
        "CanAuthorEngineering for an Aries Engineer (engineering work); Aries Admin only. Independent of QA permission."))


CLIENT_FEATURES = ["technical_access", "procurement_access", "audit_access", "document_access"]
# Fields reported in membership audit events (before / after).
AUDITED = ["role", "is_active", "part_submission_allowed", "inventory_import_allowed", *CLIENT_FEATURES, "contract_reviewer",
           "qa_permitted", "engineering_authoring", "edit_reviewer"]
# Aries Engineer permissions, set only by an Aries Admin (label used in notifications)
ENGINEER_PERMISSIONS = {"qa_permitted": "QA", "engineering_authoring": "engineering work", "contract_reviewer": "contract review"}


def snapshot(m: Membership) -> dict:
    return {f: getattr(m, f) for f in AUDITED}


def _require_four_roles(field: str) -> None:
    from .permissions import four_roles

    if not four_roles():
        raise DomainError("not_available", f"{field} is part of the four-role model, which is not enabled.", http_status=400)


def add_member(request, tenant: Tenant, data: dict) -> Membership:
    role = data["role"]
    email = data["email"].strip().lower()
    user = User.objects.filter(email=email).first()
    policy.check_add(request.membership, tenant, user, role)
    if user is None:
        password = data.get("password")
        if not password:
            raise DomainError("password_required", "A password is required for a new user.", http_status=400)
        try:
            validate_password(password)
        except Exception as e:  # django ValidationError
            raise serializers.ValidationError({"password": list(getattr(e, "messages", [str(e)]))})
        user = User.objects.create_user(email=email, password=password, first_name=data.get("first_name", ""),
                                        last_name=data.get("last_name", ""))
    if Membership.objects.filter(user=user, tenant=tenant).exists():
        raise DomainError("already_member", "This user already belongs to the organisation.", http_status=400)
    return Membership.objects.create(user=user, tenant=tenant, role=role, is_active=data.get("is_active", True),
                                     created_by=request.user)


def update_member(request, m: Membership, data: dict) -> Membership:
    """Single path for membership changes (Users page and the operator's Clients page)."""
    s = MemberUpdateSerializer(data=data)
    s.is_valid(raise_exception=True)
    role, is_active = s.validated_data.get("role"), s.validated_data.get("is_active")
    allowed = s.validated_data.get("part_submission_allowed")
    importing = s.validated_data.get("inventory_import_allowed")
    features = {f: s.validated_data[f] for f in CLIENT_FEATURES if f in s.validated_data}
    reviewer = s.validated_data.get("contract_reviewer")
    qa = s.validated_data.get("qa_permitted")
    authoring = s.validated_data.get("engineering_authoring")
    policy.check_update(request.membership, m, role=role, is_active=is_active)
    if features:
        _require_four_roles("Client User feature permissions")
        if (role or m.role) != Role.CLIENT_USER:
            raise DomainError("not_applicable", "Feature permissions apply to Client Users only; Client Admins have every client "
                              "feature by role.", http_status=400)
    if reviewer is not None:
        _require_four_roles("Contract review permission")
        if not policy.is_platform_admin(request.membership):
            raise DomainError("not_permitted", "Only an Aries Admin can give or remove contract review permission.", http_status=403)
        if (role or m.role) != Role.OPERATOR_ENGINEER or m.tenant.kind != Tenant.Kind.OPERATOR:
            raise DomainError("not_applicable", "Contract review permission is given to Aries Engineers in the Aries organisation.",
                              http_status=400)
    for value, what in ((qa, "QA permission"), (authoring, "Engineering work permission")):
        if value is None:
            continue
        _require_four_roles(what)
        if not policy.is_platform_admin(request.membership):
            raise DomainError("not_permitted", f"Only an Aries Admin can give or remove {what[0].lower() + what[1:]}.", http_status=403)
        if (role or m.role) != Role.OPERATOR_ENGINEER:
            raise DomainError("not_engineer", f"{what} is given to Aries Engineers only.", http_status=400)
    if importing is not None:
        if request.membership.role != Role.OPERATOR_ADMIN:
            raise DomainError("not_permitted", "Only an Aries Admin can allow inventory import.", http_status=403)
        if (role or m.role) != Role.CLIENT_ADMIN:
            raise DomainError("not_applicable", "Inventory import can be allowed for Client Administrators only.", http_status=400)
    if allowed is not None and (role or m.role) != Role.CLIENT_USER:
        raise DomainError("not_applicable", "Part-submission permission applies to Client Users only; Client "
                          "Administrators and Client Engineers have it by role.", http_status=400)
    before = snapshot(m)
    m.role = role or m.role
    m.is_active = m.is_active if is_active is None else is_active
    if allowed is not None:
        m.part_submission_allowed = allowed
    if importing is not None:
        m.inventory_import_allowed = importing
    for f, v in features.items():
        setattr(m, f, v)
    if reviewer is not None:
        m.contract_reviewer = reviewer
    if qa is not None:
        m.qa_permitted = qa
    if authoring is not None:
        m.engineering_authoring = authoring
    m.save(update_fields=["role", "is_active", "part_submission_allowed", "inventory_import_allowed", *CLIENT_FEATURES,
                          "contract_reviewer", "qa_permitted", "engineering_authoring", "updated_at"])
    for f, label in ENGINEER_PERMISSIONS.items():
        if getattr(m, f) != before[f]:
            _notify_permission(m, f"{label[0].upper() + label[1:]} permission " + ("given" if getattr(m, f) else "removed"), m.tenant.name)
    return m, before


def _notify_permission(m: Membership, title: str, company: str) -> None:
    from apps.servicerequests.models import Notification

    Notification.objects.create(recipient=m.user, title=title, body=f"Changed by an Aries Admin ({company}).", link="/",
                                organisation_name=company)


def propagate_operator_role(request, m: Membership, old_role: str) -> list[str]:
    """When an Aries Admin changes an Aries staff member's role in the Aries organisation (Users page) between
    Engineer, QA and Support, the person's active client assignments take the same role, so every company shows one
    role for them. A role that cannot be held in a client company (Aries Admin) leaves the assignments unchanged; a
    single assignment can still be changed on that client's Client Users tab. Each change is audited in the client and
    in the Aries organisation; the edit-reviewer flag (engineers only) is cleared when the role is no longer Engineer.
    Returns the names of the companies changed."""
    if (m.tenant.kind != Tenant.Kind.OPERATOR or m.role == old_role or old_role not in CLIENT_ASSIGNABLE_OPERATOR_ROLES
            or m.role not in CLIENT_ASSIGNABLE_OPERATOR_ROLES):
        return []
    changed = []
    clients = Tenant.objects.filter(kind=Tenant.Kind.CLIENT, memberships__user=m.user).distinct()
    for client in clients:
        with tenant_context(client):
            a = (Membership.objects.select_related("user", "tenant")
                 .filter(user=m.user, tenant=client, is_active=True, role__in=CLIENT_ASSIGNABLE_OPERATOR_ROLES).first())
            if a is None or a.role == m.role:
                continue
            before = snapshot(a)
            a.role = m.role
            fields = ["role", "updated_at"]
            if a.role != Role.OPERATOR_ENGINEER and a.edit_reviewer:
                a.edit_reviewer = False
                fields.append("edit_reviewer")
            a.save(update_fields=fields)
            data = {"before": before, "after": snapshot(a), "by_operator": True, "from_aries_role_change": True}
            record(request, "membership.updated", obj=a, tenant=client, data=data)
        record(request, "membership.updated", obj=a, data={"client": client.slug, **data})
        changed.append(client.name)
    if changed:
        from apps.servicerequests.models import Notification

        Notification.objects.create(recipient=m.user, title=f"Role changed: {Role(m.role).label}",
                                    body=f"Your role is now {Role(m.role).label} in the Aries organisation and in: {', '.join(changed)}.",
                                    link="/", organisation_name=m.tenant.name)
    return changed


class EngineerAccessInput(serializers.Serializer):
    scope = serializers.ChoiceField(choices=["company", "projects"])
    project_ids = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)
    edit_reviewer = serializers.BooleanField(required=False, help_text=(
        "CanReviewEngineering (CN-006, provisional): authorise this Aries Engineer to decide edit requests in this client company."))
    qa_permitted = serializers.BooleanField(required=False, help_text=(
        "CanPerformQA (four-role model): this Aries Engineer may confirm or reject photo-origin claims (never their own) in this "
        "client company, within their project scope."))
    engineering_authoring = serializers.BooleanField(required=False, help_text=(
        "CanAuthorEngineering (four-role model): engineering work in this client company. Independent of QA permission."))


def _engineer_access_rows(client: Tenant) -> list[dict]:
    """Aries staff assigned to this client with their scope (read inside the client's tenant context)."""
    from apps.projects.models import EngineerAccess, ProjectAssignment

    rows = []
    for m in client.memberships.select_related("user").filter(role__in=CLIENT_ASSIGNABLE_OPERATOR_ROLES):
        access = EngineerAccess.objects.filter(tenant=client, user=m.user).first()
        projects = list(ProjectAssignment.objects.filter(tenant=client, user=m.user, is_active=True)
                        .select_related("project").values("project_id", "project__code", "project__name"))
        rows.append({"membership_id": str(m.pk), "email": m.user.email, "name": f"{m.user.first_name} {m.user.last_name}".strip(),
                     "role": m.role, "is_active": m.is_active, "edit_reviewer": m.edit_reviewer, "qa_permitted": m.qa_permitted,
                     "engineering_authoring": m.engineering_authoring, "scope": access.scope if access else EngineerAccess.Scope.COMPANY,
                     "projects": [{"id": str(p["project_id"]), "code": p["project__code"], "name": p["project__name"]} for p in projects]})
    return rows


class ClientViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                    mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """Operator administrators manage client organisations (operator tenant only)."""

    serializer_class = ClientSerializer
    permission_classes = [HasCapability]
    capabilities = {"list": "clients.view", "retrieve": "clients.view", "create": "clients.manage", "profile": "clients.manage",
                    "update": "clients.manage", "partial_update": "clients.manage", "members": "clients.manage",
                    "member_detail": "clients.manage", "details": "clients.view", "projects": "assignments.manage",
                    "engineer_access": "assignments.manage"}

    def get_queryset(self):
        return Tenant.objects.filter(kind=Tenant.Kind.CLIENT)

    @extend_schema(request=ClientCreateSerializer, responses={201: ClientSerializer})
    def create(self, request, *args, **kwargs):
        """Create a client organisation directly (no registration approval step). The primary contact is invited, never
        activated or marked verified here."""
        from .invitations import issue_invitation

        s = ClientCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = dict(s.validated_data)
        invite = data.pop("invite_contact")
        with transaction.atomic():
            client = Tenant.objects.create(kind=Tenant.Kind.CLIENT, **data)
            record(request, "client.created", obj=client, data={"slug": client.slug, "route": "aries_admin"})
            with tenant_context(client):
                record(request, "client.created", obj=client, tenant=client, data={"route": "aries_admin"})
            if invite:
                issue_invitation(request, client, client.contact_email, Role.CLIENT_ADMIN)
        return Response(ClientSerializer(client).data, status=status.HTTP_201_CREATED)

    def perform_update(self, serializer):
        client = serializer.save()
        record(self.request, "client.updated", obj=client, data={"fields": sorted(serializer.validated_data)})

    @extend_schema(request=CompanyProfileSerializer, responses={200: dict})
    @action(detail=True, methods=["patch"])
    def profile(self, request, pk=None):
        """Administrative update of the company profile (partial). Only the fields sent change; blank values are refused
        for required fields. Identifiers, users and engineering records are not touched."""
        client = self.get_object()
        s = CompanyProfileSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        changed = sorted(f for f, v in s.validated_data.items() if getattr(client, f) != v)
        for f in changed:
            setattr(client, f, s.validated_data[f])
        if changed:
            client.save(update_fields=[*changed, "updated_at"])
            record(request, "client.profile_updated", obj=client, data={"fields": changed})
            with tenant_context(client):
                record(request, "client.profile_updated", obj=client, tenant=client, data={"fields": changed, "by_operator": True})
        return Response(profile_of(client))

    @extend_schema(request=MemberSerializer, responses={200: MemberSerializer(many=True), 201: MemberSerializer})
    @action(detail=True, methods=["get", "post"])
    def members(self, request, pk=None):
        client = self.get_object()
        out = MemberSerializer(context={"actor": request.membership})
        if request.method == "GET":
            from . import admin_workspace

            return Response([out.to_representation(m) for m in admin_workspace.without_workspaces(client.memberships.select_related("user", "tenant"))])
        s = MemberSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic():
            m = add_member(request, client, s.validated_data)
            record(request, "membership.created", obj=m, data={"client": client.slug, "role": m.role})
            with tenant_context(client):
                record(request, "membership.created", obj=m, tenant=client, data={"role": m.role, "by_operator": True})
                from apps.projects.scoping import CLIENT_SCOPED_ROLES, start_project_scoped

                if m.role in CLIENT_ASSIGNABLE_OPERATOR_ROLES or m.role in CLIENT_SCOPED_ROLES:
                    # Project-based assignment (2 Nov 2026): Aries staff newly assigned to a company see only the projects the
                    # Aries Admin assigns them (Engineers & Access); new Client Users only the projects their Client
                    # Administrator assigns them (Users page). Company-wide access is always an explicit grant. A scope row kept
                    # from an earlier membership of the same person is left as it is.
                    if start_project_scoped(client, m.user, request.user):
                        record(request, "assignment.scope_changed", obj=m, tenant=client,
                               data={"user": m.user.email, "scope": "projects", "projects": [], "by_operator": True, "initial": True})
        return Response(out.to_representation(m), status=status.HTTP_201_CREATED)

    @extend_schema(responses={200: dict})
    @action(detail=True, methods=["get"])
    def details(self, request, pk=None):
        """Audited company overview for Aries Admins: registration record, people, Aries staff scopes and aggregate
        counts. Read inside the client's own tenant context; no part, passport or document content is returned."""
        from apps.parts.models import SparePart
        from apps.passports.models import DigitalPassport
        from apps.projects.models import Project
        from apps.registrations.models import CompanyRegistration

        client = self.get_object()
        with tenant_context(request.tenant):
            reg = CompanyRegistration.objects.select_related("reviewed_by").filter(client_tenant=client).first()
        registration = None if reg is None else {
            "company_name": reg.company_name, "trade_licence_number": reg.trade_licence_number,
            "licence_authority": reg.licence_authority, "country": reg.country, "state": reg.state, "city": reg.city,
            "address": reg.address,
            "contact_name": reg.contact_name, "job_title": reg.job_title, "email": reg.email, "phone": reg.phone,
            "email_verified_at": reg.email_verified_at, "approved_at": reg.reviewed_at,
            "approved_by": reg.reviewed_by.email if reg.reviewed_by_id else ""}
        with tenant_context(client):
            counts = {"projects": Project.objects.count(), "parts": SparePart.objects.count(),
                      "passports": DigitalPassport.objects.count()}
            staff = _engineer_access_rows(client)
            record(request, "client.details_viewed", obj=client, tenant=client, data={"by_operator": True})
        record(request, "client.details_viewed", obj=client)
        people = [{"email": m.user.email, "role": m.role, "is_active": m.is_active}
                  for m in client.memberships.select_related("user").exclude(role__in=CLIENT_ASSIGNABLE_OPERATOR_ROLES | {Role.OPERATOR_ADMIN})]
        approved_reg = reg if reg is not None and reg.status == CompanyRegistration.Status.APPROVED else None
        return Response({"id": str(client.pk), "name": client.name, "slug": client.slug, "status": client.status,
                         "hosting_model": client.hosting_model, "region_code": client.region_code,
                         "origin": "self_registration" if approved_reg else "aries_admin",
                         "profile": profile_of(client), "contact": contact_status(client, approved_reg),
                         "created_at": client.created_at, "registration": registration, "people": people,
                         "aries_staff": staff, "counts": counts})

    @extend_schema(methods=["GET"], responses={200: dict})
    @extend_schema(methods=["POST"], request=inline_serializer("ClientProjectCreate", {
        "code": serializers.CharField(max_length=40), "name": serializers.CharField(max_length=200),
        "description": serializers.CharField(required=False, allow_blank=True)}), responses={201: dict})
    @action(detail=True, methods=["get", "post"])
    def projects(self, request, pk=None):
        """GET: project codes and names of a client, so Aries Admins can assign engineers to projects. POST: the Aries Admin
        creates a project directly in the client company (no engineer with company-wide access needed); engineers are then
        assigned to it under Engineers & Access. Audited in both organisations."""
        from apps.projects.api import ProjectSerializer
        from apps.projects.models import Project

        client = self.get_object()
        if request.method == "POST":
            with transaction.atomic(), tenant_context(client):
                ser = ProjectSerializer(data=request.data, context={"tenant": client})
                ser.is_valid(raise_exception=True)
                p = ser.save(tenant=client, created_by=request.user)
                record(request, "project.created", obj=p, tenant=client, data={"code": p.code, "by_operator": True})
            record(request, "project.created", obj=p, data={"code": p.code, "client": client.slug})
            return Response({"id": str(p.pk), "code": p.code, "name": p.name, "status": p.status, "description": p.description},
                            status=status.HTTP_201_CREATED)
        with tenant_context(client):
            rows = [{"id": str(p.pk), "code": p.code, "name": p.name, "status": p.status} for p in Project.objects.order_by("code")]
        return Response(rows)

    @extend_schema(request=EngineerAccessInput, responses={200: dict})
    @action(detail=True, methods=["get", "put"], url_path=r"engineers/(?P<mid>[0-9a-f-]+)/access")
    def engineer_access(self, request, pk=None, mid=None):
        """Company-wide or project-limited access of one assigned Aries staff member (CN-002 D4). Audited in both
        organisations; the engineer is notified. Nobody can change their own access."""
        from apps.projects.models import EngineerAccess, Project, ProjectAssignment
        from apps.servicerequests.models import Notification

        client = self.get_object()
        m = Membership.objects.select_related("user").filter(pk=mid, tenant=client, role__in=CLIENT_ASSIGNABLE_OPERATOR_ROLES).first()
        if m is None:
            raise DomainError("not_found", "Assigned Aries staff member not found.", http_status=status.HTTP_404_NOT_FOUND)
        if request.method == "GET":
            with tenant_context(client):
                row = next(r for r in _engineer_access_rows(client) if r["membership_id"] == str(m.pk))
            return Response(row)
        if m.user_id == request.user.pk:
            raise DomainError("cannot_assign_self", "You cannot change your own access.", http_status=400)
        s = EngineerAccessInput(data=request.data)
        s.is_valid(raise_exception=True)
        scope, wanted = s.validated_data["scope"], set(s.validated_data.get("project_ids") or [])
        with transaction.atomic(), tenant_context(client):
            projects = {p.pk: p for p in Project.objects.filter(pk__in=wanted)}
            if len(projects) != len(wanted):
                raise DomainError("project_not_found", "One or more projects do not belong to this client.", http_status=400)
            if scope == "projects" and not projects:
                raise DomainError("projects_required", "Select at least one project, or give company-wide access.", http_status=400)
            access, _ = EngineerAccess.objects.get_or_create(tenant=client, user=m.user, defaults={"created_by": request.user})
            access.scope, access.updated_by = scope, request.user
            access.save(update_fields=["scope", "updated_by", "updated_at"])
            before = snapshot(m)
            if "edit_reviewer" in s.validated_data:
                if s.validated_data["edit_reviewer"] and m.role != "operator_engineer":
                    raise DomainError("not_engineer", "Only Aries Engineers can be authorised as edit reviewers.", http_status=400)
                m.edit_reviewer = s.validated_data["edit_reviewer"]
                m.save(update_fields=["edit_reviewer", "updated_at"])
            for f, what in (("qa_permitted", "QA permission"), ("engineering_authoring", "Engineering work permission")):
                if f not in s.validated_data:
                    continue
                _require_four_roles(what)
                if m.role != Role.OPERATOR_ENGINEER:
                    raise DomainError("not_engineer", f"{what} is given to Aries Engineers only.", http_status=400)
                setattr(m, f, s.validated_data[f])
                m.save(update_fields=[f, "updated_at"])
            keep = set(projects) if scope == "projects" else set()
            for pa in ProjectAssignment.objects.filter(tenant=client, user=m.user):
                active = pa.project_id in keep
                if pa.is_active != active:
                    pa.is_active = active
                    pa.save(update_fields=["is_active", "updated_at"])
            existing = set(ProjectAssignment.objects.filter(tenant=client, user=m.user).values_list("project_id", flat=True))
            for pid in keep - existing:
                ProjectAssignment.objects.create(tenant=client, user=m.user, project=projects[pid], created_by=request.user)
            data = {"user": m.user.email, "scope": scope, "projects": sorted(projects[p].code for p in keep),
                    "edit_reviewer": m.edit_reviewer, "qa_permitted": m.qa_permitted, "engineering_authoring": m.engineering_authoring}
            granted = {f: getattr(m, f) for f in ("edit_reviewer", "qa_permitted", "engineering_authoring") if getattr(m, f) != before[f]}
            if granted:  # permission changes get their own event, so grants and revocations are easy to find
                record(request, "membership.permissions_changed", obj=m, tenant=client,
                       data={"user": m.user.email, "changes": granted, "by_operator": True})
            record(request, "assignment.scope_changed", obj=m, tenant=client, data={**data, "by_operator": True})
            row = next(r for r in _engineer_access_rows(client) if r["membership_id"] == str(m.pk))
        record(request, "assignment.scope_changed", obj=m, data={**data, "client": client.slug})
        if granted:
            record(request, "membership.permissions_changed", obj=m, data={"user": m.user.email, "changes": granted, "client": client.slug})
        what = "all projects" if scope == "company" else ", ".join(data["projects"])
        if granted:
            labels = {"edit_reviewer": "engineering review (edit requests)", "qa_permitted": "QA", "engineering_authoring": "engineering work"}
            what += ". " + "; ".join(f"{labels[f]}: {'given' if v else 'removed'}" for f, v in granted.items())
        Notification.objects.create(recipient=m.user, title=f"Assignment updated: {client.name}", body=f"Your access: {what}.",
                                    link="/", organisation_name=client.name)
        return Response(row)

    @extend_schema(request=MemberUpdateSerializer, responses={200: MemberSerializer})
    @action(detail=True, methods=["patch"], url_path=r"members/(?P<mid>[0-9a-f-]+)")
    def member_detail(self, request, pk=None, mid=None):
        """Operator administrators change or deactivate a membership in a client organisation, including operator
        staff assignments, which client administrators cannot manage."""
        client = self.get_object()
        m = Membership.objects.select_related("user", "tenant").filter(pk=mid, tenant=client).first()
        if m is None:
            raise DomainError("not_found", "Membership not found.", http_status=status.HTTP_404_NOT_FOUND)
        with transaction.atomic():
            m, before = update_member(request, m, request.data)
            after = snapshot(m)
            record(request, "membership.updated", obj=m, data={"client": client.slug, "before": before, "after": after})
            with tenant_context(client):
                record(request, "membership.updated", obj=m, tenant=client, data={"before": before, "after": after, "by_operator": True})
        return Response(MemberSerializer(context={"actor": request.membership}).to_representation(m))


class UserViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                  mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """Members of the current tenant. Identified by membership id."""

    serializer_class = MemberSerializer
    permission_classes = [HasCapability]
    capabilities = {"list": "users.view", "retrieve": "users.view", "create": "users.manage",
                    "update": "users.manage", "partial_update": "users.manage", "project_access": "users.manage",
                    "projects": "users.manage"}

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Membership.objects.none()
        from . import admin_workspace

        return admin_workspace.without_workspaces(Membership.objects.filter(tenant=self.request.tenant).select_related("user", "tenant"))

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "actor": getattr(self.request, "membership", None)}

    def create(self, request, *args, **kwargs):
        # Organisation administrators invite people (POST /invitations/); only platform administrators create
        # accounts directly. Direct creation would reveal whether an address already has an account.
        if not policy.is_platform_admin(request.membership):
            raise DomainError("invitation_required", "Invite people by email instead (Users → Invite user).", http_status=403)
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        m = add_member(request, request.tenant, s.validated_data)
        record(request, "membership.created", obj=m, data={"role": m.role})
        return Response(s.to_representation(m), status=status.HTTP_201_CREATED)

    @extend_schema(request=MemberUpdateSerializer, responses={200: MemberSerializer})
    def update(self, request, *args, **kwargs):
        m = self.get_object()  # tenant-scoped: another organisation's membership id gives 404
        with transaction.atomic():
            m, before = update_member(request, m, request.data)
            record(request, "membership.updated", obj=m, data={"before": before, "after": snapshot(m)})
            propagate_operator_role(request, m, before["role"])
        return Response(self.get_serializer().to_representation(m))

    @extend_schema(request=MemberUpdateSerializer, responses={200: MemberSerializer})
    def partial_update(self, request, *args, **kwargs):
        return self.update(request, *args, **kwargs)

    # ---- project access of Client Users (2 Nov 2026), managed by the Client Administrator --------------------------------

    def _client_company(self, request):
        if request.tenant.kind != Tenant.Kind.CLIENT:
            raise DomainError("not_client_company", "Project access is managed inside a client company.", http_status=400)

    @staticmethod
    def _project_access_row(m) -> dict:
        from apps.projects.models import EngineerAccess, ProjectAssignment

        access = EngineerAccess.objects.filter(tenant_id=m.tenant_id, user_id=m.user_id).first()
        projects = list(ProjectAssignment.objects.filter(tenant_id=m.tenant_id, user_id=m.user_id, is_active=True)
                        .select_related("project").order_by("project__code"))
        scope = access.scope if access else EngineerAccess.Scope.COMPANY
        return {"membership_id": str(m.pk), "scope": scope, "explicit": access is not None,
                "projects": [{"id": str(pa.project_id), "code": pa.project.code, "name": pa.project.name} for pa in projects] if scope == "projects" else []}

    @extend_schema(responses={200: dict})
    @action(detail=False, methods=["get"], url_path="project-access")
    def project_access(self, request):
        """Project access of every Client User of this company. Client Administrators always see all projects (not listed)."""
        from apps.projects.scoping import CLIENT_SCOPED_ROLES

        self._client_company(request)
        return Response({str(m.pk): self._project_access_row(m)
                         for m in Membership.objects.filter(tenant=request.tenant, role__in=CLIENT_SCOPED_ROLES)})

    @extend_schema(request=inline_serializer("ClientUserProjects", {
        "scope": serializers.ChoiceField(choices=["company", "projects"]),
        "project_ids": serializers.ListField(child=serializers.UUIDField(), required=False)}), responses={200: dict})
    @action(detail=True, methods=["get", "put"])
    def projects(self, request, pk=None):
        """GET / PUT the projects one Client User may see: "company" (all projects, also later ones; an explicit, revocable grant)
        or "projects" with a list (empty = no project access). Only Client Users; Client Administrators always have every
        project and Aries staff access is managed by the Aries Admin. Audited; the user is notified."""
        from apps.projects.models import EngineerAccess, Project, ProjectAssignment
        from apps.projects.scoping import CLIENT_SCOPED_ROLES
        from apps.servicerequests.models import Notification

        self._client_company(request)
        m = self.get_object()
        if m.role not in CLIENT_SCOPED_ROLES:
            raise DomainError("not_client_user", "Project access is set for Client Users only. Client Administrators always see every "
                              "project; Aries staff access is managed by the Aries Admin.", http_status=400)
        if request.method == "GET":
            return Response(self._project_access_row(m))
        if m.user_id == request.user.pk:
            raise DomainError("cannot_assign_self", "You cannot change your own access.", http_status=400)
        scope = request.data.get("scope")
        if scope not in ("company", "projects"):
            raise DomainError("invalid_scope", "Choose all company projects or selected projects.", http_status=400)
        wanted = {str(x) for x in (request.data.get("project_ids") or [])} if scope == "projects" else set()
        with transaction.atomic():
            projects = {str(p.pk): p for p in Project.objects.filter(tenant=request.tenant, pk__in=wanted)}
            if len(projects) != len(wanted):
                raise DomainError("project_not_found", "One or more projects do not belong to this company.", http_status=400)
            before = self._project_access_row(m)
            access, _ = EngineerAccess.objects.get_or_create(tenant=request.tenant, user=m.user, defaults={"created_by": request.user})
            access.scope, access.updated_by = scope, request.user
            access.save(update_fields=["scope", "updated_by", "updated_at"])
            for pa in ProjectAssignment.objects.filter(tenant=request.tenant, user=m.user):
                active = str(pa.project_id) in projects
                if pa.is_active != active:
                    pa.is_active = active
                    pa.save(update_fields=["is_active", "updated_at"])
            existing = {str(x) for x in ProjectAssignment.objects.filter(tenant=request.tenant, user=m.user).values_list("project_id", flat=True)}
            for pid in set(projects) - existing:
                ProjectAssignment.objects.create(tenant=request.tenant, user=m.user, project=projects[pid], created_by=request.user)
            after = self._project_access_row(m)
            record(request, "client_user.project_access_changed", obj=m, data={
                "user": m.user.email, "before": {"scope": before["scope"], "projects": [p["code"] for p in before["projects"]]},
                "after": {"scope": after["scope"], "projects": [p["code"] for p in after["projects"]]}})
        what = "all projects of the company" if scope == "company" else (", ".join(p["code"] for p in after["projects"]) or "no projects")
        Notification.objects.create(recipient=m.user, title=f"Project access updated: {request.tenant.name}", body=f"Your access: {what}.",
                                    link="/", organisation_name=request.tenant.name)
        return Response(after)


class OwnCompanyProfileView(APIView):
    """The signed-in Client Administrator's own company profile, read only (post-UAT 2.2). Changes to the registered company
    profile stay with the Aries Admin (/clients/{id}/profile/) until a client-side edit policy is decided."""
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: dict})
    def get(self, request):
        m = getattr(request, "membership", None)
        if m is None or m.role != Role.CLIENT_ADMIN or request.tenant.kind != Tenant.Kind.CLIENT:
            raise DomainError("permission_denied", "Only the Client Administrator can view the company profile.", http_status=403)
        return Response({**profile_of(request.tenant), "editable": False,
                         "edit_note": "To change the registered company details, contact Aries; the Aries Admin updates them."})
