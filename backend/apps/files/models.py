from django.conf import settings
from django.db import models

from apps.tenancy.owned import TenantOwnedModel


class EngineeringFile(TenantOwnedModel):
    """A logical document of a spare part: STEP, DWG or PDF engineering files, or a part photograph (JPEG/PNG,
    BR-006 "original part image"). Content lives in versions."""

    class Kind(models.TextChoices):
        STEP = "step", "STEP 3D model"
        DWG = "dwg", "DWG drawing"
        PDF = "pdf", "PDF document"
        IMAGE = "image", "Photograph"
        SCAN = "scan", "3D scan data (mesh / point cloud)"  # post-UAT D-09: source data, never production-ready CAD

    class Category(models.TextChoices):
        MODEL_3D = "3d_model", "Interactive 3D model"
        DRAWING = "drawing", "Engineering drawing"
        SPECIFICATION = "specification", "Manufacturing specification"
        INSPECTION = "inspection", "Inspection and quality"
        CERTIFICATE = "certificate", "Certification"
        PHOTO = "photo", "Photographs"
        OTHER = "other", "Other"
        # CN-005 report attachments: supporting document classes. Uploading never verifies a document's content.
        MATERIAL_CERTIFICATE = "mat_cert", "Material certificate"
        MECHANICAL_TEST = "mech_test", "Mechanical test report"
        CHEMICAL_ANALYSIS = "chem_analysis", "Chemical analysis report"
        LAB_TEST = "lab_test", "Laboratory test report"
        SCAN_SOURCE = "scan_source", "3D scan source data"

    part = models.ForeignKey("parts.SparePart", on_delete=models.PROTECT, related_name="files")
    passport = models.ForeignKey("passports.DigitalPassport", null=True, blank=True, on_delete=models.PROTECT, related_name="files")
    kind = models.CharField(max_length=8, choices=Kind.choices)
    category = models.CharField(max_length=16, choices=Category.choices, default=Category.OTHER)
    title = models.CharField(max_length=200)
    # CN-005: whether client users may see this document (files list, previews, client-facing reports). Documents that
    # existed before this flag keep their visibility (migration sets True). Aries-uploaded PDFs start hidden until an
    # Aries Engineer releases them; a document never becomes client-visible automatically.
    client_visible = models.BooleanField(default=False)
    # Post-UAT D-02: the version released to the client. Clients see and open only this version of an Aries document; a newer
    # upload stays Aries-only until an Aries Engineer releases it. Client-supplied documents are the client's own (all versions).
    released_version = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class FileVersion(TenantOwnedModel):
    """Immutable original upload (CAD-005, CAD-009, CAD-010). A database trigger blocks UPDATE and DELETE."""

    file = models.ForeignKey(EngineeringFile, on_delete=models.PROTECT, related_name="versions")
    version_number = models.PositiveIntegerField()
    original_filename = models.CharField(max_length=255)
    size_bytes = models.BigIntegerField()
    sha256 = models.CharField(max_length=64)
    detected_format = models.CharField(max_length=40)
    content_type = models.CharField(max_length=100)
    storage_key = models.CharField(max_length=500, unique=True)
    passport_revision = models.ForeignKey("passports.PassportRevision", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    note = models.CharField(max_length=300, blank=True)
    page_count = models.PositiveIntegerField(null=True, blank=True)  # PDFs (checked at upload)

    class Meta:
        ordering = ["file", "-version_number"]
        constraints = [models.UniqueConstraint(fields=["file", "version_number"], name="uniq_file_version")]


class Derivative(TenantOwnedModel):
    """Generated viewing file (e.g. GLB from STEP). Linked to its source version, inherits its
    access rules, stored apart from originals (CAD-006, AZC-004). Immutable once written."""

    class Kind(models.TextChoices):
        GLB = "glb", "GLB 3D derivative"
        PDF = "pdf", "PDF preview"
        SVG = "svg", "SVG preview"
        THUMB = "thumb", "Thumbnail (JPEG, metadata removed)"

    file_version = models.ForeignKey(FileVersion, on_delete=models.PROTECT, related_name="derivatives")
    kind = models.CharField(max_length=8, choices=Kind.choices)
    storage_key = models.CharField(max_length=500, unique=True)
    size_bytes = models.BigIntegerField()
    sha256 = models.CharField(max_length=64)
    generator = models.CharField(max_length=120)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["file_version", "kind"], name="uniq_derivative_kind")]


class LinkRedemption(TenantOwnedModel):
    """Marks a download/preview link as used. Links are single-use: the unique nonce makes a second
    redemption fail atomically (W2 security item A). One small row per download."""

    nonce = models.CharField(max_length=40, unique=True)
    variant = models.CharField(max_length=12)
    object_id = models.CharField(max_length=64)

    class Meta:
        ordering = ["-created_at"]


class AdminThumbnailConsent(TenantOwnedModel):
    """A client company's decision to let the Aries Admin see its sanitized photo thumbnails in the administrative
    inventory (ADMIN_THUMBNAIL_CONSENT_ENABLED). Append-only: each grant or revocation is a new row, and a database trigger
    blocks UPDATE and DELETE. The latest row is the company's current decision; no row means not allowed (default OFF).
    Only the company's own Client Administrator records a decision; the Aries Admin has no membership in the company and
    no capability to do so. Thumbnail links issued to the Aries Admin carry the id of the grant they were issued under, so
    a revocation (or any later decision) invalidates them at once."""

    class Decision(models.TextChoices):
        GRANTED = "granted", "Allowed"
        REVOKED = "revoked", "Not allowed"

    decision = models.CharField(max_length=8, choices=Decision.choices)
    decided_by_name = models.CharField(max_length=200)
    decided_by_role = models.CharField(max_length=40)
    # the version of the wording the representative confirmed (kept with the decision)
    terms_version = models.CharField(max_length=40)
    note = models.CharField(max_length=300, blank=True)
    # Order of decisions within the company (1, 2, ...). Timestamps can tie on fast clocks, so "latest" is decided by
    # this number; decisions recorded before it existed have none and sort as older than every numbered one.
    sequence = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = [models.F("sequence").desc(nulls_last=True), "-created_at"]
        constraints = [models.UniqueConstraint(fields=["tenant", "sequence"], name="uniq_thumbnail_consent_sequence")]


class ImageOriginEvent(TenantOwnedModel):
    """Recorded origin of one photograph version (ADMIN_THUMBNAIL_PROVENANCE_ENABLED). Append-only, one row per event; a
    database trigger blocks UPDATE and DELETE. The latest row is the version's current origin state; no row means origin
    unknown. The uploading role is never treated as proof of origin, and nothing is classified automatically or in bulk:
    only the Aries Engineer who uploaded that exact version may claim it was captured by Aries during scanning or
    digitisation work (never for a version uploaded by a client member), and only Aries QA, never the claimant, may confirm
    or reject the claim. The claimant or QA may withdraw it. Only a confirmed claim can count towards the contract route
    for Aries Admin thumbnails (apps.files.thumbnail_provenance)."""

    class Event(models.TextChoices):
        CLAIMED = "claimed", "Claimed as captured by Aries"
        CONFIRMED = "confirmed", "Confirmed by Aries QA"
        REJECTED = "rejected", "Rejected by Aries QA"
        WITHDRAWN = "withdrawn", "Claim withdrawn"

    file_version = models.ForeignKey(FileVersion, on_delete=models.PROTECT, related_name="origin_events")
    event = models.CharField(max_length=10, choices=Event.choices)
    # the claim a confirmation, rejection or withdrawal acts on
    claim = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    # scanning job or digitisation reference, where available (historical photos may have none in the application)
    capture_reference = models.CharField(max_length=120, blank=True)
    capture_date = models.DateField(null=True, blank=True)
    note = models.CharField(max_length=500, blank=True)
    actor_name = models.CharField(max_length=200)
    actor_role = models.CharField(max_length=40)
    sequence = models.PositiveIntegerField()  # order of events of this version (1, 2, ...): decides "latest"

    class Meta:
        ordering = ["-sequence"]
        constraints = [models.UniqueConstraint(fields=["file_version", "sequence"], name="uniq_image_origin_sequence")]


class ContractAuthorization(TenantOwnedModel):
    """A claimed contractual authorization for internal Aries Admin viewing of thumbnails of Aries-captured scanning
    photographs of one client company (ADMIN_THUMBNAIL_PROVENANCE_ENABLED). Recorded by an Aries Admin and kept as
    immutable evidence (trigger blocks UPDATE and DELETE): contract reference, the relevant clause excerpt, effective and
    expiry dates and the company or project scope. The signed contract itself is not stored. Recording proves nothing by
    itself: the authorization has no effect until a different authorized Aries person verifies it against the signed
    agreement (ContractAuthorizationEvent), and an explicit client "Not allowed" holds it until an independent review is
    documented."""

    class Scope(models.TextChoices):
        COMPANY = "company", "Whole company"
        PROJECTS = "projects", "Listed projects only"

    contract_reference = models.CharField(max_length=120)
    clause_excerpt = models.TextField()
    effective_from = models.DateField()
    effective_until = models.DateField()
    scope = models.CharField(max_length=10, choices=Scope.choices)
    project_ids = models.JSONField(default=list, blank=True)
    recorded_by_name = models.CharField(max_length=200)
    recorded_by_role = models.CharField(max_length=40)
    note = models.CharField(max_length=500, blank=True)
    sequence = models.PositiveIntegerField()  # order within the company (1, 2, ...): the highest is current

    class Meta:
        ordering = ["-sequence"]
        constraints = [models.UniqueConstraint(fields=["tenant", "sequence"], name="uniq_contract_authorization_sequence")]


class ContractAuthorizationEvent(TenantOwnedModel):
    """Verification history of a ContractAuthorization. Append-only (trigger blocks UPDATE and DELETE). Verification,
    rejection and conflict reviews are made by an authorized Aries person other than the one who recorded the
    authorization; a conflict review names the client's "Not allowed" decision it resolves, so a later client decision
    puts the contract route on hold again."""

    class Event(models.TextChoices):
        VERIFIED = "verified", "Verified against the signed agreement"
        REJECTED = "rejected", "Rejected"
        ENDED = "ended", "Ended"
        CONFLICT_PROCEED = "conflict_proceed", "Client objection reviewed: contract route may proceed"
        CONFLICT_SUSTAINED = "conflict_sustained", "Client objection reviewed: contract route stays blocked"

    authorization = models.ForeignKey(ContractAuthorization, on_delete=models.PROTECT, related_name="events")
    event = models.CharField(max_length=20, choices=Event.choices)
    # for conflict reviews: the client's "Not allowed" decision that was reviewed
    objection = models.ForeignKey(AdminThumbnailConsent, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    # for conflict reviews: the documented authority (CONTRACT_OBJECTION_AUTHORITY) the reviewer acted under. Reviews
    # without one (recorded before the authority existed) never resolve an objection.
    authority_reference = models.CharField(max_length=200, blank=True, default="")
    note = models.TextField()
    actor_name = models.CharField(max_length=200)
    actor_role = models.CharField(max_length=40)
    sequence = models.PositiveIntegerField()  # order of events of this authorization (1, 2, ...)

    class Meta:
        ordering = ["-sequence"]
        constraints = [models.UniqueConstraint(fields=["authorization", "sequence"], name="uniq_contract_event_sequence")]
