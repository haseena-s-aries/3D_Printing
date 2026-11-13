from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.tenancy.owned import TenantOwnedModel


class DigitalPassport(TenantOwnedModel):
    """One passport per spare part (BR-003). State fields are stored separately (PUB-001..PUB-003);
    their transition rules are open (OQ-35, OQ-36) and cannot be changed through the API in Phase 1."""

    class PublicationState(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        ENGINEERING_APPROVED = "engineering_approved", "Engineering approved"
        # Prepared by Aries (scan, Aries-created part, or completed after a client submission was approved): no approval
        # step; the Aries Engineer marks the revision complete (decision of 13 Nov 2026).
        COMPLETE = "complete", "Complete"
        PUBLISHED = "published", "Published"
        REVISION_IN_PROGRESS = "revision_in_progress", "Revision in progress"
        ARCHIVED = "archived", "Archived"

    class EvidenceLevel(models.TextChoices):
        NONE = "none", "Not assessed"
        RL1 = "R-L1", "R-L1"
        RL2 = "R-L2", "R-L2"
        RL3 = "R-L3", "R-L3"

    class Eligibility(models.TextChoices):
        NOT_ELIGIBLE = "not_eligible", "Not eligible"
        SUBJECT_TO_AUTHORISATION = "eligible_subject_to_authorisation", "Eligible subject to authorisation"
        ELIGIBLE = "eligible", "Eligible"
        SUSPENDED = "suspended", "Suspended"

    part = models.OneToOneField("parts.SparePart", on_delete=models.PROTECT, related_name="passport")
    passport_number = models.CharField(max_length=60)
    title = models.CharField(max_length=200)
    publication_state = models.CharField(max_length=24, choices=PublicationState.choices, default=PublicationState.DRAFT)
    evidence_level = models.CharField(max_length=8, choices=EvidenceLevel.choices, default=EvidenceLevel.NONE)
    manufacturing_eligibility = models.CharField(max_length=40, choices=Eligibility.choices, default=Eligibility.NOT_ELIGIBLE)

    class DataCaptured(models.TextChoices):
        NONE = "none", "Not complete"
        RL1 = "rl1", "R-L1 data complete"
        RL2 = "rl2", "R-L1 and R-L2 data complete"
        RL3 = "rl3", "R-L1 to R-L3 data complete"

    # Highest level whose data (and every lower level's) is fully captured in the current revision. Stored so the
    # catalog can filter on it server-side. Guidance only: it never changes evidence_level, publication or
    # eligibility, which stay gated (OQ-35, OQ-36).
    data_captured = models.CharField(max_length=8, choices=DataCaptured.choices, default=DataCaptured.NONE, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["tenant", "passport_number"], name="uniq_passport_number_per_tenant")]

    def __str__(self):
        return self.passport_number


class PassportRevision(TenantOwnedModel):
    """Versioned passport content. Approved and superseded revisions are immutable (enforced by a
    database trigger; the only permitted change is approved -> superseded). One draft at a time."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        APPROVED = "approved", "Approved"
        SUPERSEDED = "superseded", "Superseded"

    passport = models.ForeignKey(DigitalPassport, on_delete=models.PROTECT, related_name="revisions")
    revision_number = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    content = models.JSONField(default=dict, blank=True)
    change_summary = models.CharField(max_length=500, blank=True)
    # BR-034: who last changed the draft (the audit trail keeps every change)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)
    # Why an approver sent the revision back to draft (apps.passports.approval); cleared when it is submitted again.
    review_note = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["passport", "-revision_number"]
        constraints = [
            models.UniqueConstraint(fields=["passport", "revision_number"], name="uniq_revision_number"),
            models.UniqueConstraint(fields=["passport"], condition=Q(status="draft"), name="one_draft_revision_per_passport"),
        ]

    def __str__(self):
        return f"{self.passport_id} rev {self.revision_number}"
