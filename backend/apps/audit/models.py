from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class AuditEvent(TimeStampedModel):
    """Append-only, tenant-isolated audit record (BR-054, HYB-015).
    UPDATE and DELETE are blocked by a database trigger; reads are limited by row-level security."""

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.PROTECT, related_name="+")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    actor_email = models.CharField(max_length=254, blank=True)
    actor_role = models.CharField(max_length=32, blank=True)
    action = models.CharField(max_length=80, db_index=True)
    object_type = models.CharField(max_length=60, blank=True)
    object_id = models.CharField(max_length=64, blank=True, db_index=True)
    request_id = models.CharField(max_length=64, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    data = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
