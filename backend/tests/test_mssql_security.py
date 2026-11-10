"""SQL Server only: the parts of apps.tenancy.mssql that the shared database-level tests (test_rls_postgres,
test_security_regression) cannot see: connection-scoped context reset, notification deletes, guard coverage after
migrations, collation, and the job-sheet sequence."""
import pytest
from django.core.signals import request_finished, request_started
from django.db import DatabaseError, connection, transaction

from apps.servicerequests.models import Notification
from apps.tenancy import mssql
from apps.tenancy.context import ALL_SETTINGS, SETTING, USER_SETTING, read_setting, reset_session_context, set_tenant_context, tenant_context, write_setting

pytestmark = pytest.mark.skipif(connection.vendor != "microsoft", reason="SQL Server security implementation")


def test_context_is_cleared_when_a_request_ends(world, monkeypatch):
    """SESSION_CONTEXT survives commit and rollback: the request hooks clear it so the next request on a reused connection
    starts with no tenant (fail closed)."""
    receivers = [r[1]() for r in request_started.receivers] + [r[1]() for r in request_finished.receivers]
    assert receivers.count(reset_session_context) == 2
    write_setting(SETTING, world["a"].pk)
    write_setting(USER_SETTING, world["a_admin"].pk)
    assert read_setting(SETTING) == world["a"].pk.hex
    # between two requests the connection is outside any transaction (here: the test's own transaction is hidden)
    monkeypatch.setattr(connection, "in_atomic_block", False)
    reset_session_context()
    monkeypatch.undo()
    assert all(read_setting(k) is None for k in ALL_SETTINGS)


def test_tenant_context_restores_the_previous_tenant_even_after_an_error(world):
    with tenant_context(world["a"]):
        with pytest.raises(RuntimeError), tenant_context(world["b"]):
            raise RuntimeError("boom")
        assert read_setting(SETTING) == world["a"].pk.hex  # B's context did not survive the error


def test_notifications_cannot_be_deleted_even_by_their_recipient(world):
    user, tenant = world["a_admin"], world["a"]
    with tenant_context(tenant):
        n = Notification.objects.create(recipient=user, title="t", body="b")
    with transaction.atomic():
        set_tenant_context(tenant.pk)
        write_setting(USER_SETTING, user.pk)
        assert Notification.objects.filter(pk=n.pk).count() == 1  # the recipient reads it
        with pytest.raises(DatabaseError), transaction.atomic():
            Notification.objects.filter(pk=n.pk).delete()  # no delete policy on PostgreSQL: blocked here too
        write_setting(USER_SETTING, world["a_user"].pk)
        assert Notification.objects.filter(pk=n.pk).count() == 0  # another user of the same company sees nothing


def test_every_immutability_guard_writes_every_current_column(db):
    """INSTEAD OF UPDATE triggers list the columns they write; post_migrate rebuilds them so none is silently dropped."""
    with connection.cursor() as cur:
        cur.execute("SELECT g.name, g.table_name, OBJECT_DEFINITION(t.object_id) FROM dbo.app_immutable_guard g "
                    "JOIN sys.triggers t ON t.name = g.name + '_guard' AND t.parent_id = OBJECT_ID('dbo.' + g.table_name)")
        guards = cur.fetchall()
        assert len(guards) >= 30
        for name, table, definition in guards:
            cur.execute("SELECT c.name FROM sys.columns c WHERE c.object_id = OBJECT_ID(%s) AND c.is_identity = 0 AND c.is_computed = 0 "
                        "AND c.column_id NOT IN (SELECT ic.column_id FROM sys.indexes x JOIN sys.index_columns ic ON ic.object_id = x.object_id "
                        "AND ic.index_id = x.index_id WHERE x.object_id = c.object_id AND x.is_primary_key = 1)", [f"dbo.{table}"])
            missing = [c for (c,) in cur.fetchall() if f"[{c}] = y.[{c}]" not in definition]
            assert not missing, f"{name} guard does not write {missing}"
    assert mssql.refresh_guards(connection) == len(guards)


def test_database_collation_is_case_sensitive(db):
    with connection.cursor() as cur:
        cur.execute("SELECT CAST(DATABASEPROPERTYEX(DB_NAME(), 'Collation') AS nvarchar(100)), CASE WHEN N'A' = N'a' THEN 1 ELSE 0 END")
        collation, equal = cur.fetchone()
    assert collation.endswith("_CS_AS_SC") and equal == 0


def test_jobsheet_draft_sequence(db):
    with connection.cursor() as cur:
        cur.execute("SELECT NEXT VALUE FOR dbo.jobsheet_draft_seq")
        a = cur.fetchone()[0]
        cur.execute("SELECT NEXT VALUE FOR dbo.jobsheet_draft_seq")
        assert cur.fetchone()[0] == a + 1
