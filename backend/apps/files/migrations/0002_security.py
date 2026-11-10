"""Row-level security and immutable originals/derivatives. PostgreSQL only."""
from django.db import migrations

from apps.tenancy.rls import enable_tenant_rls, immutable_rows  # noqa: F401


class Migration(migrations.Migration):
    dependencies = [("files", "0001_initial")]

    operations = [
        enable_tenant_rls("files_engineeringfile"),
        enable_tenant_rls("files_fileversion"),
        enable_tenant_rls("files_derivative"),
        immutable_rows("files_fileversion", "file_version"),
        immutable_rows("files_derivative", "derivative"),
    ]
