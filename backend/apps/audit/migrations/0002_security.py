"""Row-level security and append-only audit trail. PostgreSQL only."""
from django.db import migrations

from apps.tenancy.rls import enable_tenant_rls, immutable_rows  # noqa: F401


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_initial")]

    operations = [
        enable_tenant_rls("audit_auditevent"),
        immutable_rows("audit_auditevent", "audit_event"),
    ]
