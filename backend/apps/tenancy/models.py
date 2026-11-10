from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class Tenant(TimeStampedModel):
    """A client organisation, or the platform operator itself (kind=operator)."""

    class Kind(models.TextChoices):
        OPERATOR = "operator", "Platform operator"
        CLIENT = "client", "Client organisation"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"

    class HostingModel(models.TextChoices):
        SHARED = "shared", "Shared Azure platform"
        DEDICATED = "dedicated", "Dedicated Azure deployment"

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=60, unique=True)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.CLIENT)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    hosting_model = models.CharField(max_length=16, choices=HostingModel.choices, default=HostingModel.SHARED)
    # Informational only. Region and residency rules are open (OQ-71); nothing is enforced from this value yet.
    region_code = models.CharField(max_length=40, blank=True)

    # Company profile (one record for both creation routes: self-registration copies it here on approval; Aries Admins
    # enter it directly). Blank means "not provided"; older organisations may be incomplete and are never back-filled
    # with invented values. Field rules live in apps/tenancy/profile.py.
    trade_licence_number = models.CharField(max_length=80, blank=True)
    licence_authority = models.CharField(max_length=120, blank=True)
    country = models.CharField(max_length=80, blank=True)
    state = models.CharField(max_length=80, blank=True, help_text="Emirate, state or province")
    city = models.CharField(max_length=120, blank=True)
    address = models.CharField(max_length=300, blank=True, help_text="Location / street address")
    contact_name = models.CharField(max_length=150, blank=True)
    contact_title = models.CharField(max_length=120, blank=True, help_text="Designation of the primary contact")
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=40, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Role(models.TextChoices):
    OPERATOR_ADMIN = "operator_admin", "Operator administrator"
    OPERATOR_ENGINEER = "operator_engineer", "Operator engineer"
    OPERATOR_QA = "operator_qa", "Operator QA"
    OPERATOR_SUPPORT = "operator_support", "Operator support"
    CLIENT_ADMIN = "client_admin", "Client administrator"
    CLIENT_ENGINEER = "client_engineer", "Client engineer"
    CLIENT_USER = "client_user", "Client user"
    PROCUREMENT = "procurement", "Procurement"
    AUDITOR = "auditor", "Auditor"


OPERATOR_ROLES = {Role.OPERATOR_ADMIN, Role.OPERATOR_ENGINEER, Role.OPERATOR_QA, Role.OPERATOR_SUPPORT}
CLIENT_ROLES = {Role.CLIENT_ADMIN, Role.CLIENT_ENGINEER, Role.CLIENT_USER, Role.PROCUREMENT, Role.AUDITOR}


class Membership(TimeStampedModel):
    """A user's role in one tenant. Operator staff may hold assignments in client tenants
    (OQ-02: access for support and fulfilment with authorisation and audit)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=32, choices=Role.choices)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    # Client consent terms for operator access are open (OQ-37). Recorded if supplied; not enforced.
    consent_reference = models.CharField(max_length=200, blank=True)
    # CN-003: an ordinary Client User may submit or clone spare parts only when the Client Administrator allows it.
    # Client Administrators and Client Engineers are authorised by role.
    part_submission_allowed = models.BooleanField(default=False)
    # CN-006 (provisional): an Aries Engineer explicitly authorised by the Aries Admin to decide edit requests in this
    # client company. Formal engineering approval authority (OQ-35) is unresolved; this is not passport approval.
    edit_reviewer = models.BooleanField(default=False)
    # CN-007: a Client Administrator may bulk-import inventory only when an Aries Admin explicitly allows it.
    inventory_import_allowed = models.BooleanField(default=False)
    # Four core roles (FOUR_ROLE_MODEL_ENABLED). Aries Engineer permissions, set only by an Aries Admin:
    # CanPerformQA on an assignment to a client company (photo-origin confirmation, job-sheet QA review), and
    # CanReviewContract on the engineer's Aries-organisation membership (contract verification; objection review still needs
    # the deployment-designated authority). CanReviewEngineering is edit_reviewer above.
    qa_permitted = models.BooleanField(default=False)
    contract_reviewer = models.BooleanField(default=False)
    # CanAuthorEngineering: engineering work (parts, passport drafts, engineering files, intelligence, job-sheet drafts, imports).
    # On for Aries Engineers as before; off for converted Aries QA memberships, so QA and authoring are controlled separately.
    engineering_authoring = models.BooleanField(default=True)
    # Client User feature permissions, set by the Client Admin or the Aries Admin (part_submission_allowed is the first).
    technical_access = models.BooleanField(default=False)
    procurement_access = models.BooleanField(default=False)
    audit_access = models.BooleanField(default=False)

    class DocumentAccess(models.TextChoices):
        NONE = "none", "No document access"
        PREVIEW = "preview", "Previews only"
        FULL = "full", "Full documents"

    document_access = models.CharField(max_length=10, choices=DocumentAccess.choices, default=DocumentAccess.PREVIEW)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "tenant"], name="uniq_membership_user_tenant")]
        ordering = ["tenant__name", "user__email"]

    def __str__(self):
        return f"{self.user} @ {self.tenant} ({self.role})"


class Invitation(TimeStampedModel):
    """Invitation to join an organisation (W2 security item B). Client administrators invite by email instead of
    creating accounts, and the response never depends on whether the address already has an account. Only the
    address owner, holding the emailed link, can accept. Only a SHA-256 hash of the token is stored."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        REVOKED = "revoked", "Revoked"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="invitations")
    email = models.EmailField()
    role = models.CharField(max_length=32, choices=Role.choices)
    token_hash = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    expires_at = models.DateTimeField()
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["tenant", "email"], condition=models.Q(status="pending"),
                                               name="one_pending_invitation_per_email")]
