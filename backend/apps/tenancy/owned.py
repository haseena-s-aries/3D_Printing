from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class TenantOwnedModel(TimeStampedModel):
    """Base for every tenant-owned business table. Each concrete table also gets a forced
    PostgreSQL row-level security policy in its migrations (apps.tenancy.rls)."""

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.PROTECT, related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        abstract = True
