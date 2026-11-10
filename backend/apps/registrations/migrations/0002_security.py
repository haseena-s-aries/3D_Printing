"""Forced row-level security for company registrations (operator tenant only). PostgreSQL only.

EmailToken has no tenant: rows are only ever looked up server-side by the SHA-256 hash of a token the requester holds."""
from django.db import migrations

from apps.tenancy.rls import enable_tenant_rls


class Migration(migrations.Migration):
    dependencies = [("registrations", "0001_initial")]

    operations = [enable_tenant_rls("registrations_companyregistration")]
