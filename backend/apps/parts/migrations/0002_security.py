"""Row-level security. PostgreSQL only."""
from django.db import migrations

from apps.tenancy.rls import enable_tenant_rls, immutable_rows  # noqa: F401


class Migration(migrations.Migration):
    dependencies = [("parts", "0001_initial")]

    operations = [
        enable_tenant_rls("parts_sparepart"),
    ]
