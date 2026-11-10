"""Controlled edit requests and reviewer decisions (CN-006).

An edit request proposes new values for listed fields of one spare part or of one Digital Passport's current revision.
It records the exact base (part timestamp or passport revision number and timestamp) and each field's original value.
An authorised edit reviewer (never the requester) approves, rejects or asks for corrections. Approval applies the
change in a controlled way: part master data is updated with history kept here; passport changes always become a NEW
draft revision (approved revisions are never touched). If the target changed in a conflicting way, nothing is written
and the request moves to "conflict". Approving an edit is not engineering verification, publication or manufacturing
authorisation (OQ-35/OQ-36).
"""
from django.db import models

from apps.tenancy.owned import TenantOwnedModel


class EditRequest(TenantOwnedModel):
    class Target(models.TextChoices):
        PART = "part", "Spare part"
        PASSPORT = "passport", "Digital Passport"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        UNDER_REVIEW = "under_review", "Under Review"
        CORRECTIONS = "corrections_requested", "Corrections Requested"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        APPLIED = "applied", "Applied"
        CONFLICT = "conflict", "Conflict / Revalidation Required"
        WITHDRAWN = "withdrawn", "Withdrawn"

    class DataClass(models.TextChoices):
        CLIENT_DESCRIPTIVE = "client_descriptive", "Client-owned descriptive data"
        ARIES_MASTER = "aries_master", "Aries-controlled engineering master data"
        PASSPORT_DRAFT = "passport_draft", "Digital Passport draft (applied as a new revision)"
        PASSPORT_NEW_REVISION = "passport_new_revision", "Approved/submitted passport (new proposed revision)"

    reference = models.CharField(max_length=30)  # ER-YYYY-NNNNN per client company
    target_type = models.CharField(max_length=10, choices=Target.choices)
    part = models.ForeignKey("parts.SparePart", on_delete=models.PROTECT, related_name="edit_requests")
    passport = models.ForeignKey("passports.DigitalPassport", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    base_revision_number = models.PositiveIntegerField(null=True, blank=True)
    base_revision_status = models.CharField(max_length=16, blank=True)
    base_updated_at = models.DateTimeField()
    data_class = models.CharField(max_length=24, choices=DataClass.choices)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.DRAFT)
    changes = models.JSONField(default=list)  # [{field, label, original, proposed}]
    reason = models.TextField()
    evidence_files = models.JSONField(default=list, blank=True)  # [{file, title}] existing files of the same part
    requester_role = models.CharField(max_length=32)
    requester_side = models.CharField(max_length=8)  # client | aries
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewer = models.ForeignKey("accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    decision_reason = models.TextField(blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    applied_revision_number = models.PositiveIntegerField(null=True, blank=True)
    application_result = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["tenant", "reference"], name="uniq_edit_request_reference")]


class EditRequestEvent(TenantOwnedModel):
    """Append-only history: who did what, when, with the status transition and note."""

    request = models.ForeignKey(EditRequest, on_delete=models.PROTECT, related_name="events")
    action = models.CharField(max_length=24)
    from_status = models.CharField(max_length=24, blank=True)
    to_status = models.CharField(max_length=24, blank=True)
    note = models.TextField(blank=True)
    side = models.CharField(max_length=8)

    class Meta:
        ordering = ["created_at"]
