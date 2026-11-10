"""Row-level security on import batches and rows; closed batches and their final rows cannot change. PostgreSQL only."""
from django.db import migrations

from apps.tenancy.rls import enable_tenant_rls, immutable_rows


class Migration(migrations.Migration):
    dependencies = [("imports", "0001_initial")]

    operations = [
        enable_tenant_rls("imports_inventoryimport"),
        enable_tenant_rls("imports_inventoryimportrow"),
        immutable_rows("imports_inventoryimport", "inventory_import_closed", when_old="OLD.status IN ('committed', 'discarded')"),
        immutable_rows("imports_inventoryimportrow", "inventory_import_row_final", when_old="OLD.final"),
    ]
