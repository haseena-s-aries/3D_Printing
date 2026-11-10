"""Row-level security; queue visible to the worker role (SQL Server: apps.tenancy.mssql)."""
from django.db import migrations

from apps.tenancy import mssql
from apps.tenancy.rls import SecuritySQL, enable_tenant_rls, immutable_rows  # noqa: F401


class Migration(migrations.Migration):
    dependencies = [("jobs", "0001_initial")]

    operations = [
        enable_tenant_rls("jobs_job"),
        SecuritySQL(
            sql="""
                DO $do$ BEGIN
                  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_worker') THEN
                    EXECUTE 'CREATE POLICY worker_queue ON jobs_job TO app_worker USING (true) WITH CHECK (true)';
                  END IF;
                END $do$;
            """,
            reverse_sql="DROP POLICY IF EXISTS worker_queue ON jobs_job;",
            mssql_forwards=lambda se: mssql.set_policy(se, "jobs_job", "rls_tenant_or_worker"),
            mssql_backwards=lambda se: mssql.set_policy(se, "jobs_job", "rls_tenant"),
        ),
    ]
