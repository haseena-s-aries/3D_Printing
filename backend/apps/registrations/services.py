"""Company registration, email verification, Aries approval and password reset (CN-002).

Security properties:
- Public responses never reveal whether an email address or company already exists.
- Tokens: 32 random bytes, only the SHA-256 hash is stored, purpose-bound, expiring, single-use (row lock on redemption).
- Verification needs the emailed link AND the password chosen at registration (no pre-registration takeover).
- No client tenant or membership exists before an Aries Admin approves; approval always creates a NEW organisation.
- Every step is audited in the operator tenant (and in the new client tenant on approval).
"""
import hashlib
import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import serializers

from apps.audit.service import record
from apps.core import mail
from apps.core.exceptions import DomainError
from apps.servicerequests.models import Notification
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Membership, Role, Tenant
from apps.tenancy.profile import PHONE, PHONE_ERROR, profile_from_registration

from .models import CompanyRegistration, EmailToken

User = get_user_model()
OPEN = [CompanyRegistration.Status.UNVERIFIED, CompanyRegistration.Status.PENDING]
INVALID_LINK = ("link_invalid", "This link is invalid or has expired. Request a new one.")
LEGAL_SUFFIXES = {"llc", "l l c", "fze", "fzco", "fz llc", "ltd", "limited", "inc", "co", "company", "est", "establishment",
                  "plc", "gmbh", "sa", "llp", "pvt", "private", "corp", "corporation", "group"}


def token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def operator_tenant() -> Tenant:
    t = Tenant.objects.filter(kind=Tenant.Kind.OPERATOR).first()
    if t is None:
        raise DomainError("operator_missing", "The platform operator organisation is not configured.", http_status=500)
    return t


def normalize_company(name: str) -> str:
    words = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower()).split()
    while words and words[-1] in LEGAL_SUFFIXES:
        words.pop()
    return " ".join(words)


def _new_token(purpose: str, lifetime: timedelta, *, user=None, registration_id=None) -> str:
    raw = secrets.token_urlsafe(32)
    EmailToken.objects.create(purpose=purpose, token_hash=token_hash(raw), user=user, registration_id=registration_id,
                              expires_at=timezone.now() + lifetime)
    return raw


def _retire_tokens(purpose: str, *, user=None, registration_id=None) -> None:
    qs = EmailToken.objects.filter(purpose=purpose, used_at__isnull=True)
    qs = qs.filter(user=user) if user is not None else qs.filter(registration_id=registration_id)
    qs.update(used_at=timezone.now())


def _valid_token(raw: str, purpose: str, *, lock: bool = False) -> EmailToken:
    qs = EmailToken.objects.filter(token_hash=token_hash(raw or ""), purpose=purpose, used_at__isnull=True,
                                   expires_at__gt=timezone.now())
    tok = (qs.select_for_update() if lock else qs).first()
    if tok is None:
        raise DomainError(*INVALID_LINK, http_status=400)
    return tok


def _link(path: str) -> str:
    return f"{settings.WEB_BASE_URL.rstrip('/')}{path}"


def _audit_operator(action: str, *, request=None, actor=None, reg=None, data=None):
    op = operator_tenant()
    with tenant_context(op):
        record(request if request is not None and getattr(request, "membership", None) else None, action, actor=actor,
               tenant=op, obj_type="companyregistration", obj_id=str(reg.pk) if reg else "", data=data or {})


def _require_enabled():
    if not settings.PUBLIC_REGISTRATION_ENABLED:
        raise DomainError("registration_disabled", "Company registration is not available yet. Please contact Aries.", http_status=403)


def _what(reg: CompanyRegistration) -> str:
    """How a registration is named in messages: the company, or the staff account request."""
    return reg.company_name if reg.kind == CompanyRegistration.Kind.COMPANY else "your Aries staff account"


STAFF_ROLE_NAMES = {Role.OPERATOR_MANAGER: "Aries Manager", Role.OPERATOR_ENGINEER: "Aries Engineer", Role.OPERATOR_QA: "Aries QA",
                    Role.OPERATOR_SUPPORT: "Aries Support"}


def staff_role_name(role: str) -> str:
    return STAFF_ROLE_NAMES.get(role, role)


def staff_role_options() -> list[str]:
    """Aries staff roles a person may request (never Aries Admin). In the four-role model QA is a permission of an Aries
    Engineer: a QA request is granted as Engineer with the QA permission. Requests are approved by an Aries Admin or an
    Aries Manager (registrations.review); an Aries Admin account is never granted through a request."""
    from apps.tenancy.permissions import four_roles

    if four_roles():
        return [Role.OPERATOR_MANAGER, Role.OPERATOR_ENGINEER, Role.OPERATOR_QA]
    return [Role.OPERATOR_MANAGER, Role.OPERATOR_ENGINEER, Role.OPERATOR_QA, Role.OPERATOR_SUPPORT]


# ---------------------------------------------------------------- registration

class RegistrationInput(serializers.Serializer):
    company_name = serializers.CharField(max_length=200)
    trade_licence_number = serializers.CharField(max_length=80)
    # Same company profile and rules as Aries Admin client creation (apps/tenancy/profile.py).
    licence_authority = serializers.CharField(max_length=120)
    country = serializers.CharField(max_length=80)
    state = serializers.CharField(max_length=80)
    city = serializers.CharField(max_length=120, required=False, allow_blank=True)
    address = serializers.CharField(max_length=300)
    contact_name = serializers.CharField(max_length=150)
    job_title = serializers.CharField(max_length=120)
    email = serializers.EmailField()
    phone = serializers.RegexField(PHONE, max_length=40, error_messages={"invalid": PHONE_ERROR})
    password = serializers.CharField(trim_whitespace=False, write_only=True)
    password_confirm = serializers.CharField(trim_whitespace=False, write_only=True)
    accept_terms = serializers.BooleanField()
    website = serializers.CharField(required=False, allow_blank=True)  # honeypot: humans leave it empty

    def validate_accept_terms(self, value):
        if not value:
            raise serializers.ValidationError("You must accept the terms to register.")
        return value

    def validate(self, attrs):
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError({"password_confirm": "The passwords do not match."})
        if not normalize_company(attrs["company_name"]):
            raise serializers.ValidationError({"company_name": "Enter the company's legal name."})
        probe = User(email=attrs["email"], first_name=attrs["contact_name"])
        try:
            validate_password(attrs["password"], user=probe)
        except ValidationError as e:
            raise serializers.ValidationError({"password": list(e.messages)})
        return attrs


def submit_registration(request, data: dict) -> None:
    """Always returns the same way; what happens depends on facts the caller is not told."""
    _require_enabled()
    if data.get("website"):  # honeypot filled: accept silently, do nothing
        return
    email = data["email"].strip().lower()
    op = operator_tenant()
    with transaction.atomic(), tenant_context(op):
        if User.objects.filter(email__iexact=email).exists():
            mail.send(email, "Digital Passport: registration attempt for your address",
                      "Someone tried to register a company with this email address, but an account already exists for it.\n"
                      f"Sign in at {_link('/login')} or reset your password at {_link('/forgot-password')}.\n"
                      "If this was not you, no action is needed.")
            _audit_operator("registration.existing_account", request=request)
            return
        reg = CompanyRegistration.objects.select_for_update().filter(email=email, status__in=OPEN).first()
        if reg is not None and reg.status == CompanyRegistration.Status.PENDING:
            mail.send(email, "Digital Passport: registration already under review",
                      f"A registration for {reg.company_name} with this address is already waiting for Aries approval.")
            _audit_operator("registration.duplicate_pending", request=request, reg=reg)
            return
        fields = {k: data.get(k, "") for k in ("company_name", "trade_licence_number", "licence_authority", "country", "state",
                                               "city", "address", "contact_name", "job_title", "phone")}
        fields.update(normalized_name=normalize_company(data["company_name"]), password_hash=make_password(data["password"]))
        if reg is None:
            reg = CompanyRegistration.objects.create(tenant=op, email=email, **fields)
        else:  # still unverified: the latest submission replaces it and earlier links stop working
            for k, v in fields.items():
                setattr(reg, k, v)
            reg.save()
            _retire_tokens(EmailToken.Purpose.VERIFY_REGISTRATION, registration_id=reg.pk)
        raw = _new_token(EmailToken.Purpose.VERIFY_REGISTRATION, timedelta(hours=settings.REGISTRATION_TOKEN_HOURS),
                         registration_id=reg.pk)
        mail.send(email, "Digital Passport: verify your email address",
                  f"Thank you for registering {reg.company_name}.\n\n"
                  f"Open this link to verify your email address (valid {settings.REGISTRATION_TOKEN_HOURS} hours, single use):\n"
                  f"{_link('/register/verify/' + raw)}\n\n"
                  "You will be asked for the password you chose. After verification Aries reviews the registration.\n"
                  "If you did not register, ignore this message.")
        _audit_operator("registration.submitted", request=request, reg=reg)


class StaffRequestInput(serializers.Serializer):
    """Public request for an Aries staff account (Engineer, QA or Support); an Aries Admin approves it."""

    full_name = serializers.CharField(max_length=150)
    job_title = serializers.CharField(max_length=120, required=False, allow_blank=True)
    email = serializers.EmailField()
    phone = serializers.RegexField(PHONE, max_length=40, required=False, allow_blank=True, error_messages={"invalid": PHONE_ERROR})
    requested_role = serializers.CharField(max_length=32)
    password = serializers.CharField(trim_whitespace=False, write_only=True)
    password_confirm = serializers.CharField(trim_whitespace=False, write_only=True)
    accept_terms = serializers.BooleanField()
    website = serializers.CharField(required=False, allow_blank=True)  # honeypot

    def validate_accept_terms(self, value):
        if not value:
            raise serializers.ValidationError("You must accept the terms to register.")
        return value

    def validate_requested_role(self, value):
        if value not in staff_role_options():
            raise serializers.ValidationError("Choose one of the offered roles.")
        return value

    def validate(self, attrs):
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError({"password_confirm": "The passwords do not match."})
        if not attrs["full_name"].strip():
            raise serializers.ValidationError({"full_name": "Enter your name."})
        try:
            validate_password(attrs["password"], user=User(email=attrs["email"], first_name=attrs["full_name"]))
        except ValidationError as e:
            raise serializers.ValidationError({"password": list(e.messages)})
        return attrs


def submit_staff_request(request, data: dict) -> None:
    """Same steps and the same no-disclosure responses as a company registration."""
    _require_enabled()
    if data.get("website"):
        return
    email = data["email"].strip().lower()
    op = operator_tenant()
    with transaction.atomic(), tenant_context(op):
        if User.objects.filter(email__iexact=email).exists():
            mail.send(email, "Digital Passport: account request for your address",
                      "Someone asked for an Aries staff account with this email address, but an account already exists for it.\n"
                      f"Sign in at {_link('/login')} or reset your password at {_link('/forgot-password')}.\n"
                      "If this was not you, no action is needed.")
            _audit_operator("registration.existing_account", request=request)
            return
        reg = CompanyRegistration.objects.select_for_update().filter(email=email, status__in=OPEN).first()
        if reg is not None and reg.status == CompanyRegistration.Status.PENDING:
            mail.send(email, "Digital Passport: request already under review",
                      "A request with this address is already waiting for Aries approval.")
            _audit_operator("registration.duplicate_pending", request=request, reg=reg)
            return
        fields = {"kind": CompanyRegistration.Kind.STAFF, "requested_role": data["requested_role"],
                  "contact_name": data["full_name"].strip(), "job_title": data.get("job_title", ""), "phone": data.get("phone", ""),
                  "company_name": "", "normalized_name": "", "trade_licence_number": "", "licence_authority": "", "country": "",
                  "state": "", "city": "", "address": "", "password_hash": make_password(data["password"])}
        if reg is None:
            reg = CompanyRegistration.objects.create(tenant=op, email=email, **fields)
        else:  # still unverified: the latest submission replaces it and earlier links stop working
            for k, v in fields.items():
                setattr(reg, k, v)
            reg.save()
            _retire_tokens(EmailToken.Purpose.VERIFY_REGISTRATION, registration_id=reg.pk)
        raw = _new_token(EmailToken.Purpose.VERIFY_REGISTRATION, timedelta(hours=settings.REGISTRATION_TOKEN_HOURS),
                         registration_id=reg.pk)
        mail.send(email, "Digital Passport: verify your email address",
                  f"Thank you for requesting an Aries staff account ({staff_role_name(reg.requested_role)}).\n\n"
                  f"Open this link to verify your email address (valid {settings.REGISTRATION_TOKEN_HOURS} hours, single use):\n"
                  f"{_link('/register/verify/' + raw)}\n\n"
                  "You will be asked for the password you chose. After verification an Aries Admin reviews the request.\n"
                  "If you did not ask for this, ignore this message.")
        _audit_operator("registration.submitted", request=request, reg=reg)


def resend_verification(request, email: str) -> None:
    _require_enabled()
    email = (email or "").strip().lower()
    op = operator_tenant()
    with transaction.atomic(), tenant_context(op):
        reg = CompanyRegistration.objects.filter(email=email, status=CompanyRegistration.Status.UNVERIFIED).first()
        if reg is None:
            return
        _retire_tokens(EmailToken.Purpose.VERIFY_REGISTRATION, registration_id=reg.pk)
        raw = _new_token(EmailToken.Purpose.VERIFY_REGISTRATION, timedelta(hours=settings.REGISTRATION_TOKEN_HOURS),
                         registration_id=reg.pk)
        mail.send(email, "Digital Passport: verify your email address",
                  f"Open this link to verify your email address for {_what(reg)} (single use):\n{_link('/register/verify/' + raw)}")
        _audit_operator("registration.verification_resent", request=request, reg=reg)


def verification_info(raw: str) -> dict:
    tok = _valid_token(raw, EmailToken.Purpose.VERIFY_REGISTRATION)
    with tenant_context(operator_tenant()):
        reg = CompanyRegistration.objects.filter(pk=tok.registration_id, status=CompanyRegistration.Status.UNVERIFIED).first()
    if reg is None:
        raise DomainError(*INVALID_LINK, http_status=400)
    return {"company_name": _what(reg), "email": reg.email, "kind": reg.kind}


def verify_registration(request, raw: str, password: str) -> CompanyRegistration:
    op = operator_tenant()
    with transaction.atomic(), tenant_context(op):
        tok = _valid_token(raw, EmailToken.Purpose.VERIFY_REGISTRATION, lock=True)
        reg = CompanyRegistration.objects.select_for_update().filter(pk=tok.registration_id,
                                                                      status=CompanyRegistration.Status.UNVERIFIED).first()
        if reg is None:
            raise DomainError(*INVALID_LINK, http_status=400)
        if not check_password(password or "", reg.password_hash):
            # The token is not consumed: the mailbox owner may simply have mistyped (attempts are rate-limited).
            raise DomainError("password_mismatch", "The password does not match the one chosen at registration.", http_status=400)
        tok.used_at = timezone.now()
        tok.save(update_fields=["used_at", "updated_at"])
        if User.objects.filter(email__iexact=reg.email).exists():
            reg.status = CompanyRegistration.Status.WITHDRAWN
            reg.save(update_fields=["status", "updated_at"])
            raise DomainError("registration_not_possible", "This registration cannot be completed. Please contact Aries.", http_status=409)
        first, _, last = reg.contact_name.strip().partition(" ")
        user = User(email=reg.email, first_name=first[:150], last_name=last[:150])
        user.password = reg.password_hash  # already hashed; the plain password was never stored
        user.save()
        reg.user, reg.status, reg.email_verified_at, reg.password_hash = user, CompanyRegistration.Status.PENDING, timezone.now(), ""
        reg.save(update_fields=["user", "status", "email_verified_at", "password_hash", "updated_at"])
        record(None, "registration.verified", actor=user, tenant=op, obj=reg)
        admins = [m.user for m in Membership.objects.filter(tenant=op, role__in=[Role.OPERATOR_ADMIN, Role.OPERATOR_MANAGER], is_active=True,
                                                             user__is_active=True).select_related("user")]
        if reg.kind == CompanyRegistration.Kind.STAFF:
            title = f"New Aries staff request: {reg.contact_name} ({staff_role_name(reg.requested_role)})"
            body = f"{reg.contact_name} <{reg.email}> verified their email. Review and approve or reject."
        else:
            title = f"New company registration: {reg.company_name}"
            body = f"{reg.contact_name} ({reg.country}) verified their email. Review and approve or reject."
        Notification.objects.bulk_create([Notification(recipient=u, title=title, body=body, link=f"/registrations/{reg.pk}",
                                                       organisation_name=op.name) for u in admins])
    mail.send(reg.email, "Digital Passport: registration received",
              f"Your email address is verified. The request for {_what(reg)} is now waiting for Aries approval.\n"
              f"You can sign in at {_link('/login')} to see its status.")
    return reg


def registration_of(user) -> CompanyRegistration | None:
    with tenant_context(operator_tenant()):
        return CompanyRegistration.objects.filter(user=user).order_by("-created_at").first()


def approve(request, reg: CompanyRegistration, organisation_name: str = "", role: str = "") -> Tenant:
    if reg.status != CompanyRegistration.Status.PENDING:
        raise DomainError("registration_not_pending", "Only registrations pending approval can be approved.", http_status=409)
    if reg.user_id == request.user.pk:
        raise DomainError("separation_of_duties", "You cannot approve your own registration.", http_status=403)
    if reg.kind == CompanyRegistration.Kind.STAFF:
        return approve_staff(request, reg, role or reg.requested_role)
    name = (organisation_name or reg.company_name).strip()
    base = slugify(name)[:50] or "client"
    slug, n = base, 1
    while Tenant.objects.filter(slug=slug).exists():
        n += 1
        slug = f"{base}-{n}"
    with transaction.atomic():
        # The submitted company profile becomes the organisation's profile (copied once; the registration stays as the
        # application record). The contact's email was verified by the registration itself.
        client = Tenant.objects.create(name=name, slug=slug, kind=Tenant.Kind.CLIENT, **profile_from_registration(reg))
        m = Membership.objects.create(user=reg.user, tenant=client, role=Role.CLIENT_ADMIN, created_by=request.user)
        reg.status, reg.reviewed_by, reg.reviewed_at, reg.client_tenant = (CompanyRegistration.Status.APPROVED, request.user,
                                                                           timezone.now(), client)
        reg.save(update_fields=["status", "reviewed_by", "reviewed_at", "client_tenant", "updated_at"])
        record(request, "registration.approved", obj=reg, data={"client": slug})
        record(request, "client.created", obj=client, data={"slug": slug, "from_registration": str(reg.pk)})
        with tenant_context(client):
            record(request, "client.created", obj=client, tenant=client, data={"from_registration": str(reg.pk)})
            record(request, "membership.created", obj=m, tenant=client, data={"role": m.role, "first_client_admin": True})
        Notification.objects.create(recipient=reg.user, title=f"{name} is approved",
                                    body="Your organisation is active. You are its Client Administrator.", link="/",
                                    organisation_name=name)
    mail.send(reg.email, "Digital Passport: your organisation is approved",
              f"{name} has been approved by Aries. Sign in at {_link('/login')} as Client Administrator.\n"
              "You can then invite colleagues from the Users page.")
    return client


def approve_staff(request, reg: CompanyRegistration, role: str) -> Tenant:
    """Grant the Aries staff account: a membership of the Aries organisation with the approved role (a QA request in
    the four-role model becomes Aries Engineer with the QA permission). Never Aries Admin."""
    from apps.tenancy.permissions import four_roles

    if role not in staff_role_options():
        raise DomainError("role_not_allowed", "Choose Aries Manager, Engineer, QA or Support for a staff account.", http_status=400)
    op = operator_tenant()
    qa_permission = four_roles() and role == Role.OPERATOR_QA
    granted = Role.OPERATOR_ENGINEER if qa_permission else role
    with transaction.atomic(), tenant_context(op):
        m = Membership.objects.create(user=reg.user, tenant=op, role=granted, qa_permitted=qa_permission, created_by=request.user)
        reg.status, reg.reviewed_by, reg.reviewed_at = CompanyRegistration.Status.APPROVED, request.user, timezone.now()
        reg.save(update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"])
        record(request, "registration.approved", obj=reg, data={"kind": "staff", "requested_role": reg.requested_role, "role": granted,
                                                                  "qa_permitted": qa_permission})
        record(request, "membership.created", obj=m, data={"role": granted, "qa_permitted": qa_permission, "from_registration": str(reg.pk)})
        label = staff_role_name(role)
        Notification.objects.create(recipient=reg.user, title=f"Your account is approved: {label}",
                                    body="An Aries Admin will assign you to client companies and projects.", link="/",
                                    organisation_name=op.name)
    mail.send(reg.email, "Digital Passport: your account is approved",
              f"Your Aries staff account is approved as {label}. Sign in at {_link('/login')}.\n"
              "An Aries Admin assigns you to client companies and projects.")
    return op


def reject(request, reg: CompanyRegistration, message: str, note: str = "") -> None:
    if reg.status not in OPEN:
        raise DomainError("registration_not_open", "This registration has already been decided.", http_status=409)
    if reg.user_id and reg.user_id == request.user.pk:
        raise DomainError("separation_of_duties", "You cannot decide your own registration.", http_status=403)
    reg.status, reg.reviewed_by, reg.reviewed_at = CompanyRegistration.Status.REJECTED, request.user, timezone.now()
    reg.decision_message, reg.internal_note, reg.password_hash = message[:500], note[:1000], ""
    reg.save(update_fields=["status", "reviewed_by", "reviewed_at", "decision_message", "internal_note", "password_hash", "updated_at"])
    _retire_tokens(EmailToken.Purpose.VERIFY_REGISTRATION, registration_id=reg.pk)
    record(request, "registration.rejected", obj=reg)
    mail.send(reg.email, "Digital Passport: registration not approved",
              f"The request for {_what(reg)} was not approved.\n{message}\nPlease contact Aries for details.")


def duplicate_hints(reg: CompanyRegistration) -> list[dict]:
    """Possible duplicates, for Aries Admins only (never shown to registrants)."""
    hints = []
    if reg.kind == CompanyRegistration.Kind.STAFF:
        return hints
    for t in Tenant.objects.filter(kind=Tenant.Kind.CLIENT):
        if normalize_company(t.name) == reg.normalized_name:
            hints.append({"kind": "existing_organisation", "name": t.name, "slug": t.slug})
    others = CompanyRegistration.objects.exclude(pk=reg.pk).exclude(status=CompanyRegistration.Status.WITHDRAWN)
    for o in others.filter(trade_licence_number__iexact=reg.trade_licence_number)[:5]:
        hints.append({"kind": "same_trade_licence", "name": o.company_name, "status": o.status})
    for o in others.filter(normalized_name=reg.normalized_name).exclude(trade_licence_number__iexact=reg.trade_licence_number)[:5]:
        hints.append({"kind": "same_company_name", "name": o.company_name, "status": o.status})
    domain = reg.email.rsplit("@", 1)[-1]
    if domain and Membership.objects.filter(tenant__kind=Tenant.Kind.CLIENT, user__email__iendswith="@" + domain).exists():
        hints.append({"kind": "same_email_domain", "name": domain})
    return hints


# ---------------------------------------------------------------- password reset

def _audit_user(user, action: str) -> None:
    tenants = {m.tenant for m in Membership.objects.filter(user=user, is_active=True).select_related("tenant")} or {operator_tenant()}
    for t in tenants:
        with tenant_context(t):
            record(None, action, actor=user, tenant=t, obj_type="user", obj_id=str(user.pk))


def request_password_reset(request, email: str) -> None:
    user = User.objects.filter(email__iexact=(email or "").strip(), is_active=True).first()
    if user is None:
        return
    with transaction.atomic():
        _retire_tokens(EmailToken.Purpose.PASSWORD_RESET, user=user)
        raw = _new_token(EmailToken.Purpose.PASSWORD_RESET, timedelta(minutes=settings.PASSWORD_RESET_TOKEN_MINUTES), user=user)
        _audit_user(user, "auth.password_reset_requested")
    mail.send(user.email, "Digital Passport: reset your password",
              f"Open this link to choose a new password (valid {settings.PASSWORD_RESET_TOKEN_MINUTES} minutes, single use):\n"
              f"{_link('/reset-password/' + raw)}\n\nIf you did not ask for this, ignore this message; your password is unchanged.")


def reset_info(raw: str) -> dict:
    tok = _valid_token(raw, EmailToken.Purpose.PASSWORD_RESET)
    return {"email": tok.user.email}


def complete_password_reset(raw: str, password: str) -> None:
    from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

    with transaction.atomic():
        tok = _valid_token(raw, EmailToken.Purpose.PASSWORD_RESET, lock=True)
        user = tok.user
        try:
            validate_password(password, user=user)
        except ValidationError as e:
            raise serializers.ValidationError({"password": list(e.messages)})
        user.set_password(password)
        user.save(update_fields=["password"])
        tok.used_at = timezone.now()
        tok.save(update_fields=["used_at", "updated_at"])
        _retire_tokens(EmailToken.Purpose.PASSWORD_RESET, user=user)
        for ot in OutstandingToken.objects.filter(user=user):  # sign out every session
            BlacklistedToken.objects.get_or_create(token=ot)
        _audit_user(user, "auth.password_reset_completed")
    mail.send(user.email, "Digital Passport: password changed",
              "Your password was changed and all sessions were signed out. If this was not you, contact Aries immediately.")
