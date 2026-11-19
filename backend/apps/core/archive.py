"""Archived records (decision of 19 Nov 2026).

The platform has no hard deletes, so single items inside companies that stay (spare parts, requests) are *archived*: an
Aries Admin or Manager hides them, nothing is erased, the audit trail stays complete and the item can be restored. The
default manager hides archived rows from every ordinary query (lists, counts, dashboards, queues), so no screen needs to
know about archiving; `all_objects` sees everything (restore, the Archive screen, uniqueness checks). Related lookups
(`request.part`, `part.passport`) use Django's base manager and still resolve archived rows.
"""
from django.db import models


class ActiveManager(models.Manager):
    """Rows that are not archived."""

    def get_queryset(self):
        return super().get_queryset().filter(archived_at__isnull=True)


class ActivePassportManager(models.Manager):
    """Passports whose spare part is not archived (a passport is archived with its part)."""

    def get_queryset(self):
        return super().get_queryset().filter(part__archived_at__isnull=True)
