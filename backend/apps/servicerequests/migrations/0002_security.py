"""Row-level security for service requests (tenant policy) and notifications (per-user policy). SQL Server: apps.tenancy.mssql."""
from django.db import migrations

from apps.tenancy import mssql
from apps.tenancy.rls import SecuritySQL, enable_tenant_rls

USER_EXPR = "recipient_id = NULLIF(current_setting('app.user_id', true), '')::uuid"


class Migration(migrations.Migration):
    dependencies = [("servicerequests", "0001_initial")]

    operations = [
        enable_tenant_rls("servicerequests_clientrequest"),
        enable_tenant_rls("servicerequests_requestevent"),
        enable_tenant_rls("servicerequests_requestattachment"),
        enable_tenant_rls("servicerequests_requestenvelope"),
        SecuritySQL(
            sql=f"""
                ALTER TABLE servicerequests_notification ENABLE ROW LEVEL SECURITY;
                ALTER TABLE servicerequests_notification FORCE ROW LEVEL SECURITY;
                -- each user reads and marks only their own notifications
                CREATE POLICY notification_read ON servicerequests_notification FOR SELECT USING ({USER_EXPR});
                CREATE POLICY notification_mark ON servicerequests_notification FOR UPDATE USING ({USER_EXPR}) WITH CHECK ({USER_EXPR});
                -- the application creates notifications for other users (no RETURNING: UUID keys are set client-side)
                CREATE POLICY notification_create ON servicerequests_notification FOR INSERT WITH CHECK (true);
            """,
            reverse_sql="""
                DROP POLICY IF EXISTS notification_read ON servicerequests_notification;
                DROP POLICY IF EXISTS notification_mark ON servicerequests_notification;
                DROP POLICY IF EXISTS notification_create ON servicerequests_notification;
                ALTER TABLE servicerequests_notification NO FORCE ROW LEVEL SECURITY;
                ALTER TABLE servicerequests_notification DISABLE ROW LEVEL SECURITY;
            """,
            # read and mark only your own; inserts for other users allowed; no deletes (PostgreSQL has no DELETE policy)
            mssql_forwards=lambda se: mssql.set_policy(se, "servicerequests_notification", "rls_user", "recipient_id",
                                                       insert=False, block_delete=True),
            mssql_backwards=lambda se: mssql.drop_policy(se, "servicerequests_notification"),
        ),
    ]
