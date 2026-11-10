"""Row-level security for job sheets (SQL Server: apps.tenancy.mssql).

1. Tenant isolation like every business table.
2. A RESTRICTIVE policy: rows are visible only while `app.jobsheet_access` is 'on'. Only the job-sheet service turns it
   on, after checking that the caller is authorised Aries staff (apps.jobsheets.services.staff_access). Client-facing
   queries never set it, so a missed filter still returns nothing (CN-004 J6).
3. Revisions are immutable (append-only history, J8 foundation).
4. A sequence for provisional JS-DRAFT references (J1); sequences are not tenant data.
"""
from django.db import migrations

from apps.tenancy import mssql
from apps.tenancy.rls import SecuritySQL, enable_tenant_rls, immutable_rows

ACCESS = "current_setting('app.jobsheet_access', true) = 'on'"


def staff_only(table: str) -> migrations.RunSQL:
    return SecuritySQL(
        sql=f"CREATE POLICY jobsheet_staff_only ON {table} AS RESTRICTIVE USING ({ACCESS}) WITH CHECK ({ACCESS});",
        reverse_sql=f"DROP POLICY IF EXISTS jobsheet_staff_only ON {table};",
        # SQL Server allows one filter predicate per table: tenant AND staff access in one function
        mssql_forwards=lambda se: mssql.set_policy(se, table, "rls_jobsheet"),
        mssql_backwards=lambda se: mssql.set_policy(se, table, "rls_tenant"),
    )


class Migration(migrations.Migration):
    dependencies = [("jobsheets", "0001_initial")]

    operations = [
        enable_tenant_rls("jobsheets_jobsheet"),
        enable_tenant_rls("jobsheets_jobsheetrevision"),
        staff_only("jobsheets_jobsheet"),
        staff_only("jobsheets_jobsheetrevision"),
        immutable_rows("jobsheets_jobsheetrevision", "jobsheet_revision"),
        SecuritySQL("CREATE SEQUENCE IF NOT EXISTS jobsheet_draft_seq;", "DROP SEQUENCE IF EXISTS jobsheet_draft_seq;",
                    mssql_forwards=lambda se: se.execute("IF OBJECT_ID(N'dbo.jobsheet_draft_seq', N'SO') IS NULL "
                                                         "CREATE SEQUENCE dbo.jobsheet_draft_seq AS bigint START WITH 1", params=None),
                    mssql_backwards=lambda se: se.execute("DROP SEQUENCE IF EXISTS dbo.jobsheet_draft_seq", params=None)),
    ]
