"""Tenant context for row-level security.

Every tenant-owned table has a forced RLS policy comparing tenant_id with the setting app.tenant_id. When the setting is
empty, the policy matches no rows (fail closed).

PostgreSQL: a transaction-local setting (set_config(..., true)), reset by the end of the transaction.
SQL Server: SESSION_CONTEXT, which belongs to the connection and survives commit and rollback. It is therefore always
restored by tenant_context(), and reset at the start and end of every request (reset_session_context) and of every test.
"""
import uuid
from contextlib import contextmanager

from django.db import connection, connections, transaction

from . import mssql

SETTING = "app.tenant_id"
USER_SETTING = "app.user_id"
JOBSHEET_SETTING = "app.jobsheet_access"
ALL_SETTINGS = (SETTING, USER_SETTING, JOBSHEET_SETTING)


def _mssql_value(value):
    """SQL Server stores UUIDs as char(32) hex (mssql-django), so ids are kept in that form for the predicates."""
    if not value:
        return None
    try:
        return uuid.UUID(str(value)).hex
    except ValueError:
        return str(value)


def write_setting(key: str, value, conn=None) -> None:
    conn = conn or connection
    with conn.cursor() as cur:
        if mssql.is_mssql(conn):
            cur.execute("EXEC sp_set_session_context @key = %s, @value = %s, @read_only = 0", [key, _mssql_value(value)])
        else:
            cur.execute("select set_config(%s, %s, true)", [key, str(value) if value else ""])


def read_setting(key: str, conn=None) -> str | None:
    conn = conn or connection
    with conn.cursor() as cur:
        if mssql.is_mssql(conn):
            cur.execute("SELECT NULLIF(CAST(SESSION_CONTEXT(%s) AS nvarchar(100)), N'')", [key])
        else:
            cur.execute("select nullif(current_setting(%s, true), '')", [key])
        return cur.fetchone()[0]


def set_tenant_context(tenant_id) -> None:
    if not connection.in_atomic_block:
        raise RuntimeError("tenant context must be set inside a transaction (ATOMIC_REQUESTS or transaction.atomic)")
    write_setting(SETTING, tenant_id)


def set_user_context(user_id) -> None:
    """Transaction-local user id for per-user row-level security (in-app notifications)."""
    if not connection.in_atomic_block:
        raise RuntimeError("user context must be set inside a transaction")
    write_setting(USER_SETTING, user_id)


def current_tenant_id() -> str | None:
    return read_setting(SETTING)


def reset_session_context(**_kwargs) -> None:
    """SQL Server only: clear every security setting on open connections (request start and end, tests). Fail closed:
    a connection that cannot be reset is closed."""
    for conn in connections.all(initialized_only=True):
        if not mssql.is_mssql(conn) or conn.connection is None or conn.in_atomic_block:
            continue
        try:
            for key in ALL_SETTINGS:
                write_setting(key, None, conn)
        except Exception:  # noqa: BLE001 - never reuse a connection whose context is unknown
            conn.close()


@contextmanager
def tenant_context(tenant):
    """Run a block under one tenant's context, restoring the previous context afterwards."""
    tenant_id = getattr(tenant, "pk", tenant)
    with transaction.atomic():
        previous = current_tenant_id()
        set_tenant_context(tenant_id)
        try:
            yield
        finally:
            set_tenant_context(previous)
