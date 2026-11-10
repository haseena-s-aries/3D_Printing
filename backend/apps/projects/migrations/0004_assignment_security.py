"""Forced row-level security for engineer access scopes and project assignments (client tenant). PostgreSQL only."""
from django.db import migrations

from apps.tenancy.rls import enable_tenant_rls


class Migration(migrations.Migration):
    dependencies = [("projects", "0003_engineeraccess_projectassignment")]

    operations = [
        enable_tenant_rls("projects_engineeraccess"),
        enable_tenant_rls("projects_projectassignment"),
    ]
