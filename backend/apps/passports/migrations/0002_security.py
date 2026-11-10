"""Row-level security and immutable approved/superseded revisions. PostgreSQL only."""
from django.db import migrations

from apps.tenancy.rls import enable_tenant_rls, immutable_rows  # noqa: F401


class Migration(migrations.Migration):
    dependencies = [("passports", "0001_initial")]

    operations = [
        enable_tenant_rls("passports_digitalpassport"),
        enable_tenant_rls("passports_passportrevision"),
        immutable_rows(
            "passports_passportrevision", "approved_revision",
            when_old="OLD.status IN ('approved', 'superseded')",
            allow_update=(
                "OLD.status = 'approved' AND NEW.status = 'superseded'"
                " AND NEW.content = OLD.content AND NEW.revision_number = OLD.revision_number"
                " AND NEW.passport_id = OLD.passport_id AND NEW.tenant_id = OLD.tenant_id"
                " AND NEW.approved_by_id IS NOT DISTINCT FROM OLD.approved_by_id"
                " AND NEW.approved_at IS NOT DISTINCT FROM OLD.approved_at"
            ),
        ),
    ]
