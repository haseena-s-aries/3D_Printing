"""Manufacturing job sheets: DRAFT only (CN-004, decisions J1-J8 approved with amendments, 26 Oct 2026).

A job sheet is the per-job manufacturing specification prepared by an Aries Engineer from an acknowledged manufacturing
enquiry. It is linked to the enquiry, the part (the clone when the client proposed another material), and exactly one
passport revision whose content is frozen as the template (J5). Every save is a new immutable revision (J8 foundation).

Confidential to Aries: rows live in the client's tenant (row-level security) and additionally under a restrictive
policy that only matches while the job-sheet service has opened `app.jobsheet_access` for authorised Aries staff, so
no client-facing query can read them (J6). Clients see only `ClientRequest.job_progress`.

Not here (gated or deferred): QA review, issue, production release and eligibility (J4, OQ-36); client-specific variants
(J7, OQ-40); production batches, serials, machine logs, inspection execution, delivery (J8).
"""
from django.db import models
from django.db.models import Q

from apps.tenancy.owned import TenantOwnedModel


class JobSheet(TenantOwnedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        CANCELLED = "cancelled", "Cancelled"
        # Reserved for later decisions; no code path sets them while J4/OQ-36 are open.
        IN_REVIEW = "in_review", "In QA review"
        ISSUED = "issued", "Issued"

    enquiry = models.OneToOneField("servicerequests.ClientRequest", on_delete=models.PROTECT, related_name="job_sheet")
    part = models.ForeignKey("parts.SparePart", on_delete=models.PROTECT, related_name="+")
    source_part = models.ForeignKey("parts.SparePart", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    passport = models.ForeignKey("passports.DigitalPassport", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    passport_number = models.CharField(max_length=40, blank=True)
    passport_revision_number = models.PositiveIntegerField(null=True, blank=True)
    passport_revision_status = models.CharField(max_length=24, blank=True)
    # Frozen copy of the passport revision's R-L2 content at preparation time (the template, J5).
    template = models.JSONField(default=dict, blank=True)
    draft_reference = models.CharField(max_length=30, unique=True)  # JS-DRAFT-YYYY-NNNNN (J1)
    job_reference = models.CharField(max_length=60, blank=True)  # Aries job number, entered manually (J1)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    manufacturing_method = models.CharField(max_length=120, blank=True)
    original_material = models.CharField(max_length=120, blank=True)
    proposed_material = models.CharField(max_length=120, blank=True)
    current_revision = models.PositiveIntegerField(default=1)
    cancelled_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # J1: unique across all Aries job sheets (enforced by the index regardless of tenant RLS)
            models.UniqueConstraint(fields=["job_reference"], condition=~Q(job_reference=""), name="uniq_aries_job_reference"),
        ]


class JobSheetRevision(TenantOwnedModel):
    """Immutable snapshot of a job sheet's content (author = created_by, timestamp = created_at)."""

    job_sheet = models.ForeignKey(JobSheet, on_delete=models.PROTECT, related_name="revisions")
    revision_number = models.PositiveIntegerField()
    job_reference = models.CharField(max_length=60, blank=True)
    manufacturing_method = models.CharField(max_length=120, blank=True)
    content = models.JSONField(default=dict)
    sources = models.JSONField(default=dict, blank=True)  # field -> verified | proposed | missing | revalidate | entered
    change_summary = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-revision_number"]
        constraints = [models.UniqueConstraint(fields=["job_sheet", "revision_number"], name="uniq_jobsheet_revision")]
