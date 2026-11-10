"""Row-level security and immutability for reports and their history (PostgreSQL only)."""
from django.db import migrations

from apps.tenancy.rls import enable_tenant_rls, immutable_rows


class Migration(migrations.Migration):
    dependencies = [("reports", "0001_initial")]

    operations = [
        enable_tenant_rls("reports_passportreport"),
        enable_tenant_rls("reports_passportreportevent"),
        immutable_rows("reports_passportreport", "passport_report"),
        immutable_rows("reports_passportreportevent", "passport_report_event"),
    ]
