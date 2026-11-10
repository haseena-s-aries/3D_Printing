"""Migration helpers: row-level security policies and immutability triggers.

PostgreSQL runs exactly the statements below. On SQL Server the same operations are implemented by apps.tenancy.mssql
(security policies, INSTEAD OF triggers), so existing migrations work unchanged on both databases."""
from django.db import migrations

from . import mssql

TENANT_EXPR = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


class SecuritySQL(migrations.RunSQL):
    """RunSQL whose PostgreSQL statements run unchanged; on SQL Server `mssql(schema_editor)` runs instead."""

    def __init__(self, sql, reverse_sql=None, mssql_forwards=None, mssql_backwards=None, **kw):
        super().__init__(sql=sql, reverse_sql=reverse_sql, **kw)
        self.mssql_forwards, self.mssql_backwards = mssql_forwards, mssql_backwards

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if mssql.is_mssql(schema_editor.connection):
            if self.mssql_forwards:
                self.mssql_forwards(schema_editor)
            return
        super().database_forwards(app_label, schema_editor, from_state, to_state)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        if mssql.is_mssql(schema_editor.connection):
            if self.mssql_backwards:
                self.mssql_backwards(schema_editor)
            return
        super().database_backwards(app_label, schema_editor, from_state, to_state)


def enable_tenant_rls(table: str) -> migrations.RunSQL:
    """Forced RLS: applies to the table owner too. Grants the worker role access if that role exists."""
    return SecuritySQL(
        sql=f"""
            ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
            ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
            CREATE POLICY tenant_isolation ON {table} USING ({TENANT_EXPR}) WITH CHECK ({TENANT_EXPR});
            DO $do$ BEGIN
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_worker') THEN
                EXECUTE 'GRANT SELECT, INSERT, UPDATE ON {table} TO app_worker';
              END IF;
            END $do$;
        """,
        reverse_sql=f"""
            DROP POLICY IF EXISTS tenant_isolation ON {table};
            ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;
            ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;
        """,
        mssql_forwards=lambda se: mssql.enable_tenant_rls(se, table),
        mssql_backwards=lambda se: mssql.drop_policy(se, table),
    )


def immutable_rows(table: str, name: str, when_old: str = "true", allow_update: str = "false") -> migrations.RunSQL:
    """Block UPDATE and DELETE of rows whose OLD values satisfy `when_old`,
    except updates satisfying `allow_update` (expressions may use OLD and NEW)."""
    fn = f"{name}_guard"
    return SecuritySQL(
        sql=f"""
            CREATE OR REPLACE FUNCTION {fn}() RETURNS trigger LANGUAGE plpgsql AS $fn$
            BEGIN
              IF ({when_old}) THEN
                IF TG_OP = 'DELETE' THEN
                  RAISE EXCEPTION 'immutable_record: {name} rows cannot be deleted' USING ERRCODE = 'P0001';
                END IF;
                IF NOT ({allow_update}) THEN
                  RAISE EXCEPTION 'immutable_record: {name} rows cannot be modified' USING ERRCODE = 'P0001';
                END IF;
              END IF;
              IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
              RETURN NEW;
            END $fn$;
            CREATE TRIGGER {fn} BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION {fn}();
        """,
        reverse_sql=f"DROP TRIGGER IF EXISTS {fn} ON {table}; DROP FUNCTION IF EXISTS {fn}();",
        mssql_forwards=lambda se: mssql.immutable_rows(se, table, name, when_old, allow_update),
        mssql_backwards=lambda se: mssql.drop_guard(se, name),
    )
