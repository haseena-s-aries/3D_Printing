"""Row-level security for the review history, append-only review events, and permanent clone lineage. PostgreSQL only."""
from django.db import migrations

from apps.tenancy.rls import enable_tenant_rls, immutable_rows


class Migration(migrations.Migration):
    dependencies = [("parts", "0004_clone_lineage")]

    operations = [
        enable_tenant_rls("parts_sparepartreviewevent"),
        immutable_rows("parts_sparepartreviewevent", "part_review_event"),
        # Once a part is a clone, its link to the source and the source snapshot can never change (BR-033 lineage).
        immutable_rows("parts_sparepart", "part_lineage", when_old="OLD.source_part_id IS NOT NULL",
                       allow_update="NEW.source_part_id IS NOT DISTINCT FROM OLD.source_part_id "
                                    "AND NEW.source_part_number = OLD.source_part_number "
                                    "AND NEW.source_snapshot = OLD.source_snapshot "
                                    "AND NEW.source_revision_number IS NOT DISTINCT FROM OLD.source_revision_number"),
    ]
