"""Per-company consent for Aries Admin inventory thumbnails (Option A, ADMIN_THUMBNAIL_CONSENT_ENABLED).

What it allows: when a client company's own Client Administrator has allowed it, the Aries Admin inventory grid shows that
company's existing sanitized photo thumbnails (480 px JPEG, EXIF/GPS removed, made at upload) of client-visible
photographs. Nothing else: no original photographs, CAD, STEP, GLB, drawings, documents, file ids or storage URLs.

How it is enforced:
- Default OFF. The decision is an append-only `AdminThumbnailConsent` row in the client's tenant (RLS, immutable rows),
  recorded only by that company's Client Administrator (`files.admin_thumbnail_consent`); the Aries Admin has no
  membership in client companies and no such capability, so it cannot grant consent on the client's behalf.
- The administrative summary issues, per row on the returned page, a signed short-lived token bound to the Aries Admin
  user, the company, the thumbnail derivative and the consent row it was issued under. The thumbnail route re-checks
  every request inside the company's tenant context: signature and expiry, same user, consent still the latest decision
  and granted, derivative still a thumbnail of a client-visible photograph of that company. A revocation therefore blocks
  every previously issued link at once; responses are `private, no-store`.
- Every grant and revocation is audited in the company's trail and in the Aries trail; every thumbnail served is audited
  in the company's trail, and the number issued per summary in the Aries trail.
- A second, contract-based route for QA-confirmed Aries scanning photos is in apps.files.thumbnail_provenance
  (ADMIN_THUMBNAIL_PROVENANCE_ENABLED). Tokens say which route ("r": "c" consent, "a" contract) they were issued under.
- An explicit "Not allowed" can be recorded even when nothing was allowed before: it is the company's objection, which
  also holds the contract route until an independent review is documented.
Full client records stay closed (OQ-37 unchanged).
"""
from django.conf import settings
from django.core import signing
from django.db.models import F, Max
from django.http import FileResponse
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.service import record
from apps.core.exceptions import DomainError
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Tenant
from apps.tenancy.permissions import HasCapability

from .models import AdminThumbnailConsent, Derivative, EngineeringFile
from .storage import get_storage

TERMS_VERSION = "admin-thumbnails-v2"
TERMS = ("Aries Admin may see small, low-resolution thumbnails of our released spare-part photographs in the Aries "
         "administrative inventory, whoever took or uploaded them. Thumbnails have all metadata (EXIF, GPS) removed. Aries "
         "Admin does not get original photographs, CAD or 3D models, drawings, documents or full part records. Every "
         "thumbnail viewed is recorded in our audit trail. We can withdraw this at any time; withdrawal takes effect "
         "immediately. Photographs Aries captured during contracted scanning work can also follow a separate contract "
         "route, shown on this page; recording \"Not allowed\" puts that route on hold until Aries documents an "
         "independent review.")
SALT = "admin-inventory-thumbnail"
NOT_AVAILABLE = ("thumbnail_not_available", "No thumbnail is available.")
# latest decision first: by sequence number (timestamps can tie); decisions from before the number existed sort as older
ORDER = (F("sequence").desc(nulls_last=True), "-created_at")


def next_sequence(qs) -> int:
    """Next number in an append-only series (a concurrent duplicate fails on the unique constraint instead of tying)."""
    return (qs.aggregate(n=Max("sequence"))["n"] or 0) + 1


def enabled() -> bool:
    return bool(getattr(settings, "ADMIN_THUMBNAIL_CONSENT_ENABLED", False))


def current(tenant) -> AdminThumbnailConsent | None:
    """The company's latest decision (call inside its tenant context)."""
    return AdminThumbnailConsent.objects.filter(tenant=tenant).order_by(*ORDER).first()


def active_grant(tenant) -> AdminThumbnailConsent | None:
    c = current(tenant) if enabled() else None
    return c if c and c.decision == AdminThumbnailConsent.Decision.GRANTED else None


def eligible_thumbnails(tenant) -> dict:
    """{part_id: derivative_id}: the newest client-visible photograph of each part that has a thumbnail."""
    out = {}
    for part_id, d_id in (Derivative.objects.filter(tenant=tenant, kind=Derivative.Kind.THUMB,
                                                   file_version__file__kind=EngineeringFile.Kind.IMAGE,
                                                   file_version__file__client_visible=True)
                          .order_by("file_version__file__part_id", "-file_version__file__created_at", "-file_version__version_number")
                          .values_list("file_version__file__part_id", "id")):
        out.setdefault(part_id, d_id)
    return out


def issue(user, tenant, derivative_id, basis: dict) -> str:
    """basis: {"r": "c", "c": consent id} (client consent) or {"r": "a", ...} (contract route, thumbnail_provenance)."""
    return signing.dumps({"u": str(user.pk), "t": str(tenant.pk), "d": str(derivative_id), **basis}, salt=SALT, compress=True)


def _operator_tenant():
    return Tenant.objects.filter(kind=Tenant.Kind.OPERATOR).order_by("created_at").first()


def _state(tenant) -> dict:
    history = [{"decision": c.decision, "label": c.get_decision_display(), "by": c.decided_by_name, "role": c.decided_by_role,
                "at": c.created_at.isoformat(), "note": c.note, "terms_version": c.terms_version}
               for c in AdminThumbnailConsent.objects.filter(tenant=tenant).order_by(*ORDER)[:50]]
    from . import thumbnail_provenance  # the contract route builds on this module

    return {"allowed": bool(history) and history[0]["decision"] == AdminThumbnailConsent.Decision.GRANTED,
            "decided": bool(history), "terms": TERMS, "terms_version": TERMS_VERSION, "history": history,
            "contract": thumbnail_provenance.state_payload(tenant, client_view=True) if thumbnail_provenance.enabled() else {"enabled": False}}


class AdminThumbnailConsentView(APIView):
    """The company's own decision: read and change it (Client Administrator only)."""
    permission_classes = [HasCapability]
    capabilities = {"get": "files.admin_thumbnail_consent", "post": "files.admin_thumbnail_consent"}

    @extend_schema(responses=inline_serializer("AdminThumbnailConsent", {
        "allowed": serializers.BooleanField(), "terms": serializers.CharField(), "terms_version": serializers.CharField(),
        "history": serializers.ListField(child=serializers.DictField())}))
    def get(self, request):
        return Response(_state(request.membership.tenant))

    @extend_schema(request=inline_serializer("AdminThumbnailDecision", {
        "allow": serializers.BooleanField(), "confirm_terms_version": serializers.CharField(required=False),
        "note": serializers.CharField(required=False, allow_blank=True)}))
    def post(self, request):
        tenant = request.membership.tenant
        allow = request.data.get("allow")
        if not isinstance(allow, bool):
            raise DomainError("invalid", "State whether Aries Admin may see thumbnails (allow: true or false).", http_status=400)
        if allow and request.data.get("confirm_terms_version") != TERMS_VERSION:
            raise DomainError("terms_not_confirmed", "Confirm the wording of what is shared before allowing thumbnails.", http_status=400)
        before = current(tenant)
        decision = AdminThumbnailConsent.Decision.GRANTED if allow else AdminThumbnailConsent.Decision.REVOKED
        if before is not None and before.decision == decision:
            raise DomainError("unchanged", "Thumbnails are already " + ("allowed." if allow else "not allowed."), http_status=409)
        name = request.user.get_full_name().strip() or request.user.email
        c = AdminThumbnailConsent.objects.create(tenant=tenant, created_by=request.user, decision=decision, decided_by_name=name,
                                                 sequence=next_sequence(AdminThumbnailConsent.objects.filter(tenant=tenant)),
                                                 decided_by_role=request.membership.role, terms_version=TERMS_VERSION,
                                                 note=str(request.data.get("note", ""))[:300])
        action = "files.admin_thumbnails_allowed" if allow else "files.admin_thumbnails_revoked"
        data = {"terms_version": TERMS_VERSION, "consent": str(c.pk), "role": request.membership.role}
        record(request, action, obj=c, data=data)
        op = _operator_tenant()
        if op is not None:  # Aries is told of the decision in its own trail
            with tenant_context(op):
                record(request, action, tenant=op, obj_type="tenant", obj_id=str(tenant.pk), data={**data, "company": tenant.name})
        return Response(_state(tenant), status=201)


class AdminThumbnailView(APIView):
    """One sanitized thumbnail for the Aries Admin inventory grid, by a token issued with the administrative summary."""
    permission_classes = [HasCapability]
    capabilities = {"get": "inventory.admin_overview"}

    @extend_schema(responses={(200, "image/jpeg"): bytes})
    def get(self, request, token):
        if not enabled():
            raise DomainError(*NOT_AVAILABLE, http_status=404)
        try:
            claim = signing.loads(token, salt=SALT, max_age=settings.ADMIN_THUMBNAIL_LINK_SECONDS)
        except signing.BadSignature:  # includes SignatureExpired
            raise DomainError(*NOT_AVAILABLE, http_status=404)
        if claim.get("u") != str(request.user.pk):
            raise DomainError(*NOT_AVAILABLE, http_status=404)
        tenant = Tenant.objects.filter(pk=claim.get("t"), kind=Tenant.Kind.CLIENT).first()
        if tenant is None:
            raise DomainError(*NOT_AVAILABLE, http_status=404)
        with tenant_context(tenant):
            d, basis = None, {}
            if claim.get("r", "c") == "c":
                grant = active_grant(tenant)
                if grant is not None and str(grant.pk) == claim.get("c"):
                    d = (Derivative.objects.select_related("file_version__file__part")
                         .filter(pk=claim.get("d"), tenant=tenant, kind=Derivative.Kind.THUMB,
                                 file_version__file__kind=EngineeringFile.Kind.IMAGE, file_version__file__client_visible=True).first())
                    basis = {"route": "consent", "consent": str(grant.pk)}
            elif claim.get("r") == "a":
                from . import thumbnail_provenance

                if thumbnail_provenance.enabled():
                    d, _ = thumbnail_provenance.check_contract_claim(tenant, claim)
                    basis = {"route": "contract", "authorization": claim.get("a"), "origin_confirmation": claim.get("p")}
            if d is None:
                raise DomainError(*NOT_AVAILABLE, http_status=404)
            part = d.file_version.file.part
            record(request, "inventory.admin_thumbnail_viewed", tenant=tenant, obj_type="part", obj_id=str(part.pk),
                   data={"by": "Aries Admin", "part_number": part.part_number, **basis})
        resp = FileResponse(get_storage().open(d.storage_key), content_type="image/jpeg")
        resp["Cache-Control"] = "private, no-store, max-age=0"
        resp["Pragma"] = "no-cache"
        resp["X-Content-Type-Options"] = "nosniff"
        resp["Content-Disposition"] = "inline"
        resp["Referrer-Policy"] = "no-referrer"
        return resp
