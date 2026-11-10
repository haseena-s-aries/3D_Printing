"""Row-level security on AI suggestions; suggestions never change once stored; a usage log row may change only while
the call is in progress (outcome 'started'). PostgreSQL only. The usage log holds no part text, so it has no tenant RLS."""
from django.db import migrations

from apps.tenancy.rls import enable_tenant_rls, immutable_rows


class Migration(migrations.Migration):
    dependencies = [("intelligence", "0001_initial")]

    operations = [
        enable_tenant_rls("intelligence_partassessment"),
        immutable_rows("intelligence_partassessment", "part_assessment"),
        immutable_rows("intelligence_aiusagelog", "ai_usage_log", when_old="OLD.outcome <> 'started'"),
    ]
