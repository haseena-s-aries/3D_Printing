"""Company self-registration (CN-002) and single-use email tokens.

CompanyRegistration belongs to the OPERATOR tenant (forced RLS): public endpoints and Aries Admins work on it inside the
operator context, and no client tenant exists until an Aries Admin approves. The registrant's password is stored only
as a Django password hash; the user account is created when the email link is opened AND the same password is entered,
so neither the mailbox owner alone nor the person who typed the address alone can activate an account.

EmailToken holds only a SHA-256 hash of each random token; tokens are purpose-bound, expiring and single-use.
"""
from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel
from apps.tenancy.owned import TenantOwnedModel


class CompanyRegistration(TenantOwnedModel):
    """A self-registration: a new client company (kind=company) or an Aries staff account (kind=staff). Both follow the
    same steps: email verification with the chosen password, then an Aries Admin approves or rejects."""

    class Kind(models.TextChoices):
        COMPANY = "company", "Client company"
        STAFF = "staff", "Aries staff account"

    class Status(models.TextChoices):
        UNVERIFIED = "unverified", "Email not verified"
        PENDING = "pending", "Pending Aries approval"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        WITHDRAWN = "withdrawn", "Withdrawn"

    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.COMPANY)
    # Aries staff requests: the role asked for (the approving Aries Admin may grant another staff role)
    requested_role = models.CharField(max_length=32, blank=True)
    company_name = models.CharField(max_length=200)
    normalized_name = models.CharField(max_length=200, db_index=True)
    trade_licence_number = models.CharField(max_length=80)
    licence_authority = models.CharField(max_length=120, blank=True)
    country = models.CharField(max_length=80)
    city = models.CharField(max_length=120, blank=True)
    state = models.CharField(max_length=80, blank=True, help_text="Emirate, state or province")
    address = models.CharField(max_length=300, blank=True, help_text="Location / street address")
    contact_name = models.CharField(max_length=150)
    job_title = models.CharField(max_length=120, blank=True)
    email = models.EmailField(db_index=True)
    phone = models.CharField(max_length=40)
    password_hash = models.CharField(max_length=256)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.UNVERIFIED)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    decision_message = models.CharField(max_length=500, blank=True, help_text="Shown to the registrant.")
    internal_note = models.CharField(max_length=1000, blank=True, help_text="Aries only.")
    client_tenant = models.ForeignKey("tenancy.Tenant", null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["email"], condition=models.Q(status__in=["unverified", "pending"]),
                                               name="one_open_registration_per_email")]


class EmailToken(TimeStampedModel):
    class Purpose(models.TextChoices):
        VERIFY_REGISTRATION = "verify_registration", "Verify registration email"
        PASSWORD_RESET = "password_reset", "Password reset"

    purpose = models.CharField(max_length=32, choices=Purpose.choices)
    token_hash = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    registration_id = models.UUIDField(null=True, blank=True, db_index=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["purpose", "user"])]
