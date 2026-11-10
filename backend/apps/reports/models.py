"""Digital Passport PDF reports (CN-005, R1-R8 approved 26 Oct 2026).

A report is an immutable PDF generated from one passport revision in one variant:
- client: identification, materials, dimensions, CAD views, quality requirements, permitted document references;
- internal: additionally the Aries manufacturing specification (BR-026/BR-041) and solution. Aries-confidential.
Engineering notes, job sheets and original STEP/DWG files are never included. Generation, previews and downloads are
recorded as append-only events and in the audit trail.
"""
from django.db import models

from apps.tenancy.owned import TenantOwnedModel


class PassportReport(TenantOwnedModel):
    class Variant(models.TextChoices):
        CLIENT = "client", "Client-facing"
        INTERNAL = "internal", "Aries internal"

    class Template(models.TextChoices):
        STANDARD = "standard", "Standard Digital Passport"
        INTERNAL = "internal", "Aries Internal Engineering Report"
        MTS = "mts", "Manufacturing & Test Specification"

    # Audience follows the template: Standard = client-facing; Internal and MTS = Aries-confidential.
    TEMPLATE_VARIANT = {"standard": "client", "internal": "internal", "mts": "internal"}

    passport = models.ForeignKey("passports.DigitalPassport", on_delete=models.PROTECT, related_name="reports")
    template = models.CharField(max_length=10, choices=Template.choices, default=Template.STANDARD)
    revision_number = models.PositiveIntegerField()
    revision_status = models.CharField(max_length=16)
    variant = models.CharField(max_length=8, choices=Variant.choices)
    number = models.CharField(max_length=80)  # provisional RPT-<passport>-R<rev>-<seq>[-INT] (R7)
    model_file_version = models.ForeignKey("files.FileVersion", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    views_status = models.CharField(max_length=300, blank=True)
    # Attached documents in page order, pinned to exact immutable versions:
    # [{order, file, version, version_id, title, category, sha256, pages, first_page, client_visible}]
    attachments = models.JSONField(default=list, blank=True)
    content_sha256 = models.CharField(max_length=64)  # fingerprint of the data printed
    storage_key = models.CharField(max_length=500, unique=True)
    pdf_sha256 = models.CharField(max_length=64)
    size_bytes = models.PositiveIntegerField()
    page_count = models.PositiveIntegerField()
    watermarked = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["tenant", "number"], name="uniq_report_number_per_tenant")]


class PassportReportEvent(TenantOwnedModel):
    """Generation, preview and download history (who, when; the report carries revision and variant)."""

    class Action(models.TextChoices):
        GENERATED = "generated", "Generated"
        PREVIEWED = "previewed", "Previewed"
        DOWNLOADED = "downloaded", "Downloaded"

    report = models.ForeignKey(PassportReport, on_delete=models.PROTECT, related_name="events")
    action = models.CharField(max_length=12, choices=Action.choices)

    class Meta:
        ordering = ["-created_at"]


class PassportReportWithdrawal(TenantOwnedModel):
    """Withdrawal of a generated report (append-only, one per report). The report row and its history stay unchanged; from
    the moment this row exists no role receives the PDF or a page image. The reason is Aries-internal; clients see only
    that the report was withdrawn and when. The stored PDF is retained for audit until an authorised disposal."""

    class FileState(models.TextChoices):
        RETAINED = "retained", "Retained in storage (no access)"
        QUARANTINED = "quarantined", "Moved to quarantine outside application storage"

    report = models.OneToOneField(PassportReport, on_delete=models.PROTECT, related_name="withdrawal")
    reason = models.TextField()
    file_state = models.CharField(max_length=12, choices=FileState.choices, default=FileState.RETAINED)
    file_note = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-created_at"]


class PassportReportReplacement(TenantOwnedModel):
    """A report generated to replace a withdrawn one (append-only)."""

    withdrawn = models.OneToOneField(PassportReport, on_delete=models.PROTECT, related_name="replacement")
    replacement = models.OneToOneField(PassportReport, on_delete=models.PROTECT, related_name="replaces")

    class Meta:
        ordering = ["-created_at"]
