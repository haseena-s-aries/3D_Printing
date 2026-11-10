"""Bulk inventory import batches and their rows (CN-007 Phase 1).

A batch holds one uploaded Excel/CSV file's rows exactly as supplied (cell text per source column), the column mapping
and the analysis of every row against the company's existing parts. Nothing touches spare parts until the batch is
committed; committing creates or updates parts and freezes the batch. The uploaded file itself is not kept: its name,
size and SHA-256 identify it, and the rows preserve the original values.
"""
from django.conf import settings
from django.db import models

from apps.tenancy.owned import TenantOwnedModel


class InventoryImport(TenantOwnedModel):
    class Status(models.TextChoices):
        PREVIEW = "preview", "Preview (nothing imported yet)"
        COMMITTED = "committed", "Imported"
        DISCARDED = "discarded", "Discarded"

    reference = models.CharField(max_length=24)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PREVIEW)
    file_name = models.CharField(max_length=255)
    file_kind = models.CharField(max_length=8)  # xlsx or csv
    file_size = models.PositiveIntegerField()
    file_sha256 = models.CharField(max_length=64)
    sheet_name = models.CharField(max_length=120, blank=True)
    header_row = models.PositiveIntegerField(default=1)
    headers = models.JSONField(default=list)
    preset = models.CharField(max_length=40, blank=True)
    mapping = models.JSONField(default=dict)  # {target field: source header}
    project = models.ForeignKey("projects.Project", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    importer_side = models.CharField(max_length=8)  # aries or client
    row_count = models.PositiveIntegerField(default=0)
    counts = models.JSONField(default=dict)  # outcome -> rows; flag -> rows
    analysed_at = models.DateTimeField(null=True, blank=True)
    apply_updates = models.BooleanField(default=False)
    committed_at = models.DateTimeField(null=True, blank=True)
    committed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    result = models.JSONField(default=dict)  # what the commit actually did

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["tenant", "reference"], name="uniq_import_reference")]


class InventoryImportRow(TenantOwnedModel):
    class Outcome(models.TextChoices):
        NEW = "new", "New part"
        UNCHANGED = "unchanged", "Already up to date"
        UPDATE = "update", "Update available"
        CONFLICT = "conflict", "Conflict: kept as is"
        ERROR = "error", "Error: not importable"

    batch = models.ForeignKey(InventoryImport, on_delete=models.CASCADE, related_name="rows")
    row_number = models.PositiveIntegerField()  # spreadsheet row number
    source = models.JSONField(default=dict)  # {source header: cell text} exactly as supplied
    values = models.JSONField(default=dict)  # {target field: cleaned value}
    outcome = models.CharField(max_length=10, choices=Outcome.choices, default=Outcome.NEW)
    messages = models.JSONField(default=list)  # [{level, code, text}]
    flags = models.JSONField(default=list)  # data-quality flag codes
    part = models.ForeignKey("parts.SparePart", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    changes = models.JSONField(default=dict)  # {field: {current, incoming}} for updates
    conflicts = models.JSONField(default=dict)  # {field: {current, last_imported, incoming}}
    applied = models.CharField(max_length=10, blank=True)  # created, updated, unchanged, skipped (after commit)
    final = models.BooleanField(default=False)

    class Meta:
        ordering = ["row_number"]
