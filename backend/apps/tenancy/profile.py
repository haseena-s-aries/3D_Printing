"""Company profile: the single definition used by company self-registration and by Aries Admin client creation.

The profile is stored on the client Tenant. A self-registration keeps its own submitted copy as the application record;
on approval the submitted values are copied to the Tenant once, and from then on only the Tenant profile is current.
"""
from django.utils import timezone
from rest_framework import serializers

from .models import Invitation, Membership, Tenant

# (tenant field, label, registration field)
FIELDS = [
    ("name", "Registered company name", "company_name"),
    ("trade_licence_number", "Trade licence number", "trade_licence_number"),
    ("licence_authority", "Trade licence issuing authority", "licence_authority"),
    ("country", "Country", "country"),
    ("state", "Emirate / state", "state"),
    ("city", "City", "city"),
    ("address", "Location / address", "address"),
    ("contact_name", "Primary contact name", "contact_name"),
    ("contact_title", "Contact designation", "job_title"),
    ("contact_email", "Email address", "email"),
    ("contact_phone", "Phone number", "phone"),
]
LABELS = {f: label for f, label, _ in FIELDS}
OPTIONAL = {"city"}
REQUIRED = [f for f, _, _ in FIELDS if f not in OPTIONAL]
PHONE = r"^\+?[0-9 ()\-]{7,30}$"
PHONE_ERROR = "Enter a phone number with digits, spaces or + only."


class CompanyProfileSerializer(serializers.Serializer):
    """Profile input. `partial=True` is used for administrative updates of existing organisations."""

    name = serializers.CharField(max_length=200)
    trade_licence_number = serializers.CharField(max_length=80)
    licence_authority = serializers.CharField(max_length=120)
    country = serializers.CharField(max_length=80)
    state = serializers.CharField(max_length=80)
    city = serializers.CharField(max_length=120, required=False, allow_blank=True)
    address = serializers.CharField(max_length=300)
    contact_name = serializers.CharField(max_length=150)
    contact_title = serializers.CharField(max_length=120)
    contact_email = serializers.EmailField()
    contact_phone = serializers.RegexField(PHONE, max_length=40, error_messages={"invalid": PHONE_ERROR})

    def validate_contact_email(self, value):
        return value.strip().lower()


def profile_from_registration(reg) -> dict:
    """The values a registrant submitted, under the Tenant field names (nothing added or guessed)."""
    return {f: (getattr(reg, r, "") or "") for f, _, r in FIELDS if f != "name"}


def profile_of(tenant: Tenant) -> dict:
    values = {f: getattr(tenant, f, "") or "" for f, _, _ in FIELDS}
    missing = [f for f in REQUIRED if not values[f].strip()]
    return {"values": values, "labels": LABELS, "required": REQUIRED, "missing": missing, "complete": not missing}


def contact_status(tenant: Tenant, registration=None) -> dict:
    """How the primary contact's access stands. Never reports a verification that did not happen."""
    email = (tenant.contact_email or "").lower()
    if registration is not None and registration.user_id:
        verified = registration.email_verified_at is not None
        return {"state": "registered", "email": registration.email, "email_verified": verified,
                "label": "Verified by self-registration" if verified else "Self-registration not verified",
                "verified_at": registration.email_verified_at}
    if not email:
        return {"state": "none", "email": "", "email_verified": False, "label": "No contact email recorded", "verified_at": None}
    member = Membership.objects.filter(tenant=tenant, user__email__iexact=email).select_related("user").first()
    inv = Invitation.objects.filter(tenant=tenant, email__iexact=email).order_by("-created_at").first()
    if inv is not None and inv.status == Invitation.Status.ACCEPTED:
        return {"state": "accepted", "email": email, "email_verified": True, "label": "Invitation accepted (email confirmed by link)",
                "verified_at": inv.accepted_at}
    if inv is not None and inv.status == Invitation.Status.PENDING:
        expired = inv.expires_at <= timezone.now()
        return {"state": "invitation_expired" if expired else "invited", "email": email, "email_verified": False,
                "label": "Invitation expired; not activated" if expired else "Invited as Client Administrator; awaiting acceptance (email not verified)",
                "verified_at": None}
    if member is not None:
        return {"state": "account_created", "email": email, "email_verified": False,
                "label": "Account added directly by Aries; email verification not recorded", "verified_at": None}
    return {"state": "not_invited", "email": email, "email_verified": False, "label": "Contact not invited; no account",
            "verified_at": None}

