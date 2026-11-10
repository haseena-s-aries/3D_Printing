from django.db import models
from django.utils import timezone

from apps.tenancy.owned import TenantOwnedModel


class Job(TenantOwnedModel):
    """Background job (PostgreSQL-backed queue, ADR-008). Claimed with FOR UPDATE SKIP LOCKED.
    Row-level security: tenant policy for the API; a separate policy lets the app_worker role
    see the queue across tenants, while job processing runs under the job's tenant context."""

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    kind = models.CharField(max_length=60)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED, db_index=True)
    payload = models.JSONField(default=dict)
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=3)
    run_after = models.DateTimeField(default=timezone.now)
    locked_by = models.CharField(max_length=100, blank=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=60, blank=True)
    error_detail = models.TextField(blank=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["status", "run_after"], name="job_queue_idx")]
