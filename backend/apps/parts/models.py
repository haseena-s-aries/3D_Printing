from django.conf import settings
from django.db import models

from apps.tenancy.owned import TenantOwnedModel


class SparePart(TenantOwnedModel):
    """Spare-part master record (FR-04, BR-001). The system UUID is the unique identifier;
    part_number is the client/OEM number, unique within a tenant. Numbering scheme OQ-14 is open."""

    class Category(models.TextChoices):
        MECHANICAL = "mechanical", "Mechanical"
        ELECTRICAL = "electrical", "Electrical"
        ELECTRONIC = "electronic", "Electronic"
        OTHER = "other", "Other"
        # CN-007: imported inventory is not classified until someone assesses it (never defaulted to "mechanical").
        UNKNOWN = "unknown", "Not classified"

    class Criticality(models.TextChoices):
        CRITICAL = "critical", "Critical"
        NON_CRITICAL = "non_critical", "Non-critical"
        UNKNOWN = "unknown", "Not assessed"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ACTIVE = "active", "Active"
        OBSOLETE = "obsolete", "Obsolete"

    project = models.ForeignKey("projects.Project", null=True, blank=True, on_delete=models.SET_NULL, related_name="parts")
    part_number = models.CharField(max_length=80)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=16, choices=Category.choices, default=Category.MECHANICAL)
    criticality = models.CharField(max_length=16, choices=Criticality.choices, default=Criticality.UNKNOWN)
    original_material = models.CharField(max_length=120, blank=True)
    dimensions = models.CharField(max_length=120, blank=True, help_text="Overall size as recorded, e.g. Ø102 x 60 mm")
    application = models.CharField(max_length=200, blank=True)
    equipment_reference = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    manufacturer = models.CharField(max_length=200, blank=True, help_text="Manufacturer / OEM as known")

    # Client submissions (requirement update 2026-10, access-test only; FR-04 names the Engineer as actor, so client
    # records are held for Aries review and never become engineering-approved by themselves).
    class Origin(models.TextChoices):
        ARIES = "aries", "Aries Engineering"
        CLIENT = "client", "Client submission"

    class Review(models.TextChoices):
        NOT_REQUIRED = "not_required", "Not required"
        PENDING = "pending_review", "Pending Aries review"
        INFO_REQUESTED = "info_requested", "More information requested"
        ACCEPTED = "accepted", "Accepted into engineering workflow"
        DECLINED = "declined", "Declined"

    class SubmissionKind(models.TextChoices):
        RECORD = "record", "Client record"  # Client Administrator
        PROPOSAL = "proposal", "New-part proposal"  # other client users
        CLONE = "clone", "Clone of an existing part"  # BR-033 customisation: new product linked to the original

    origin = models.CharField(max_length=8, choices=Origin.choices, default=Origin.ARIES)
    review_state = models.CharField(max_length=16, choices=Review.choices, default=Review.NOT_REQUIRED)
    submission_kind = models.CharField(max_length=10, choices=SubmissionKind.choices, blank=True)
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)
    # Fields the submitter marked "Unknown / not available" (e.g. part_number, original_material).
    unknown_fields = models.JSONField(default=list, blank=True)
    # Per-field provenance: {field: {source: client|aries, entered_by, entered_at, verified_by, verified_at}}.
    field_provenance = models.JSONField(default=dict, blank=True)

    # Lineage of a clone (BR-033): permanent link to the source part plus what the source looked like at clone time.
    source_part = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="clones")
    source_part_number = models.CharField(max_length=80, blank=True)
    source_passport_number = models.CharField(max_length=40, blank=True)
    source_revision_number = models.PositiveIntegerField(null=True, blank=True)
    source_snapshot = models.JSONField(default=dict, blank=True)
    proposed_material = models.CharField(max_length=120, blank=True)
    material_change_reason = models.TextField(blank=True)
    client_remarks = models.TextField(blank=True)

    # CN-007 customer inventory identifiers, kept apart from engineering-verified passport specifications.
    plant = models.CharField(max_length=80, blank=True)
    functional_location = models.CharField(max_length=80, blank=True)
    equipment_tag = models.CharField(max_length=60, blank=True)
    customer_abc_class = models.CharField(max_length=20, blank=True, help_text=(
        "Customer ABC indicator exactly as supplied. Its meaning is not confirmed; never used as engineering criticality."))
    manufacturer_reference = models.CharField(max_length=60, blank=True, help_text=(
        "Customer/ERP manufacturer reference code as supplied. Not an OEM part number."))
    oem_part_number = models.CharField(max_length=80, blank=True, help_text="Actual OEM part number, only when known and verified.")
    manufacturer_normalized = models.CharField(max_length=200, blank=True, help_text=(
        "Cleaned manufacturer name for matching (spacing and case); the original stays in `manufacturer`."))
    # Last import that wrote this part: {batch, reference, row, values: {field: value}, imported_at, imported_by}.
    # Re-imports compare against these values to tell untouched imported data from later edits.
    import_record = models.JSONField(default=dict, blank=True)

    OPEN_REVIEW = (Review.PENDING, Review.INFO_REQUESTED)
    # Parts that may go through the engineering lifecycle (passport, intelligence, feasibility, cost, recommendation, review,
    # sharing) whatever their origin: Aries-created, client record/proposal or clone once accepted, imported, or created from a
    # scanning request (post-UAT D-01). Client submissions still waiting for Aries review, and declined ones, are excluded.
    NOT_IN_LIFECYCLE = (Review.PENDING, Review.INFO_REQUESTED, Review.DECLINED)

    @property
    def in_lifecycle(self) -> bool:
        return self.review_state not in self.NOT_IN_LIFECYCLE and self.status != self.Status.OBSOLETE

    class Meta:
        ordering = ["part_number"]
        constraints = [models.UniqueConstraint(fields=["tenant", "part_number"], name="uniq_part_number_per_tenant")]

    def __str__(self):
        return f"{self.part_number} {self.name}"


class SparePartReviewEvent(TenantOwnedModel):
    """Review history of a client submission or clone, visible to the client and the reviewers (append-only)."""

    class Action(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        CLONED = "cloned", "Clone requested"
        INFO_REQUESTED = "info_requested", "Corrections requested"
        RESUBMITTED = "resubmitted", "Resubmitted"
        ACCEPTED = "accepted", "Accepted for engineering work"
        DECLINED = "declined", "Rejected"
        VERIFIED = "verified", "Values verified"

    part = models.ForeignKey(SparePart, on_delete=models.CASCADE, related_name="review_events")
    action = models.CharField(max_length=16, choices=Action.choices)
    note = models.TextField(blank=True)
    side = models.CharField(max_length=8, choices=[("client", "Client"), ("aries", "Aries")])

    class Meta:
        ordering = ["created_at"]


def lifecycle_parts(qs):
    """Restrict a SparePart queryset to the parts in the engineering lifecycle (see SparePart.NOT_IN_LIFECYCLE)."""
    return qs.exclude(review_state__in=SparePart.NOT_IN_LIFECYCLE).exclude(status=SparePart.Status.OBSOLETE)
