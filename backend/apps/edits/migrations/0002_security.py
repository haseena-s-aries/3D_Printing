"""Row-level security; append-only history; closed requests (applied, rejected, withdrawn) frozen. PostgreSQL only."""
from django.db import migrations

from apps.tenancy.rls import enable_tenant_rls, immutable_rows


class Migration(migrations.Migration):
    dependencies = [("edits", "0001_initial")]

    operations = [
        enable_tenant_rls("edits_editrequest"),
        enable_tenant_rls("edits_editrequestevent"),
        immutable_rows("edits_editrequestevent", "edit_request_event"),
        immutable_rows("edits_editrequest", "edit_request_closed", when_old="OLD.status IN ('applied', 'rejected', 'withdrawn')"),
    ]
