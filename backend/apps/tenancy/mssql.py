"""SQL Server implementation of the database security controls (the PostgreSQL ones are in rls.py).

PostgreSQL                                   SQL Server
forced RLS policy on app.tenant_id           security policy rls_<table>: FILTER + BLOCK AFTER INSERT/UPDATE predicates on
                                             SESSION_CONTEXT(N'app.tenant_id'); applies to every user, dbo included
worker_queue policy for role app_worker      predicate rls_tenant_or_worker: USER_NAME() = 'app_worker' (EXECUTE AS USER)
restrictive jobsheet_staff_only              predicate rls_jobsheet: tenant AND SESSION_CONTEXT(N'app.jobsheet_access') = 'on'
per-user notification policies               predicate rls_user on recipient_id; deletes blocked (no PostgreSQL policy)
BEFORE UPDATE/DELETE immutability trigger    INSTEAD OF UPDATE, DELETE trigger <name>_guard: refuses with RAISERROR (the
                                             transaction stays usable, so Django savepoints behave as on PostgreSQL)
sequence / nextval                           CREATE SEQUENCE / NEXT VALUE FOR

Predicate functions are schema-bound, fail closed (no context: no rows) and are created once. Immutability guards are
recorded in app_immutable_guard and rebuilt from the current columns after every migrate (post_migrate), because an
INSTEAD OF UPDATE trigger must list the columns it writes.
"""
import re

VENDOR = "microsoft"
WORKER = "app_worker"

# mssql-django stores UUIDField as char(32) (hex, no dashes); the context holds the same form (context.write_setting)
CTX = "CAST(SESSION_CONTEXT(N'{key}') AS char(32))"
FUNCTIONS = {
    "rls_tenant": f"SELECT 1 AS ok WHERE @key = {CTX.format(key='app.tenant_id')}",
    "rls_tenant_or_worker": f"SELECT 1 AS ok WHERE @key = {CTX.format(key='app.tenant_id')} OR USER_NAME() = N'{WORKER}'",
    "rls_jobsheet": (f"SELECT 1 AS ok WHERE @key = {CTX.format(key='app.tenant_id')} "
                     "AND CAST(SESSION_CONTEXT(N'app.jobsheet_access') AS nvarchar(10)) = N'on'"),
    "rls_user": f"SELECT 1 AS ok WHERE @key = {CTX.format(key='app.user_id')}",
    "rls_never": "SELECT 1 AS ok WHERE @key IS NULL AND 1 = 0",
}


def is_mssql(connection) -> bool:
    return connection.vendor == VENDOR


def _exec(schema_editor, sql: str) -> None:
    schema_editor.execute(sql, params=None)


def ensure_base(schema_editor) -> None:
    """Predicate functions, the worker user (no login) and the guard registry; idempotent."""
    for name, body in FUNCTIONS.items():
        _exec(schema_editor, f"IF OBJECT_ID(N'dbo.{name}', N'IF') IS NULL EXEC(N'CREATE FUNCTION dbo.{name}(@key char(32)) "
                             f"RETURNS TABLE WITH SCHEMABINDING AS RETURN {body.replace(chr(39), chr(39) * 2)}')")
    _exec(schema_editor, f"IF USER_ID(N'{WORKER}') IS NULL CREATE USER [{WORKER}] WITHOUT LOGIN")
    _exec(schema_editor, "IF OBJECT_ID(N'dbo.app_immutable_guard', N'U') IS NULL CREATE TABLE dbo.app_immutable_guard ("
                         "name nvarchar(100) NOT NULL PRIMARY KEY, table_name nvarchar(128) NOT NULL, "
                         "when_old nvarchar(max) NOT NULL, allow_update nvarchar(max) NOT NULL)")


def set_policy(schema_editor, table: str, predicate: str, column: str = "tenant_id", *, insert=True, update=True,
               block_delete=False) -> None:
    """(Re)create the table's single security policy: filter + block predicates with the same function."""
    ensure_base(schema_editor)
    name = f"rls_{table}"
    fn = f"dbo.{predicate}([{column}])"
    parts = [f"ADD FILTER PREDICATE {fn} ON dbo.[{table}]"]
    if insert:
        parts.append(f"ADD BLOCK PREDICATE {fn} ON dbo.[{table}] AFTER INSERT")
    if update:
        parts.append(f"ADD BLOCK PREDICATE {fn} ON dbo.[{table}] AFTER UPDATE")
    if block_delete:
        parts.append(f"ADD BLOCK PREDICATE dbo.rls_never([{column}]) ON dbo.[{table}] BEFORE DELETE")
    _exec(schema_editor, f"IF OBJECT_ID(N'dbo.{name}', N'SP') IS NOT NULL DROP SECURITY POLICY dbo.[{name}]")
    _exec(schema_editor, f"CREATE SECURITY POLICY dbo.[{name}] {', '.join(parts)} WITH (STATE = ON, SCHEMABINDING = ON)")


def drop_policy(schema_editor, table: str) -> None:
    _exec(schema_editor, f"IF OBJECT_ID(N'dbo.rls_{table}', N'SP') IS NOT NULL DROP SECURITY POLICY dbo.[rls_{table}]")


def enable_tenant_rls(schema_editor, table: str) -> None:
    set_policy(schema_editor, table, "rls_tenant")
    _exec(schema_editor, f"GRANT SELECT, INSERT, UPDATE ON dbo.[{table}] TO [{WORKER}]")


# ------------------------------------------------------------------ immutability guards

def translate(expr: str) -> str:
    """PostgreSQL trigger condition -> T-SQL over the deleted (d) and inserted (i) rows."""
    e = re.sub(r"\bOLD\.", "d.", re.sub(r"\bNEW\.", "i.", expr.strip()))
    if e.lower() == "true":
        return "1 = 1"
    if e.lower() == "false":
        return "1 = 0"
    if re.fullmatch(r"[di]\.\w+", e):  # bare boolean column (bit)
        return f"{e} = 1"
    return e


def immutable_rows(schema_editor, table: str, name: str, when_old: str, allow_update: str) -> None:
    ensure_base(schema_editor)
    w, a = translate(when_old).replace("'", "''"), translate(allow_update).replace("'", "''")
    _exec(schema_editor, f"DELETE FROM dbo.app_immutable_guard WHERE name = N'{name}'")
    _exec(schema_editor, f"INSERT INTO dbo.app_immutable_guard (name, table_name, when_old, allow_update) "
                         f"VALUES (N'{name}', N'{table}', N'{w}', N'{a}')")
    if schema_editor.collect_sql:  # sqlmigrate: the trigger is generated from the live columns at migrate time
        schema_editor.collected_sql.append(f"-- INSTEAD OF UPDATE, DELETE trigger dbo.[{name}_guard] on dbo.[{table}] (built at migrate)")
        return
    build_guard(schema_editor.connection, name)


def drop_guard(schema_editor, name: str) -> None:
    _exec(schema_editor, f"IF OBJECT_ID(N'dbo.[{name}_guard]', N'TR') IS NOT NULL DROP TRIGGER dbo.[{name}_guard]")
    _exec(schema_editor, f"IF OBJECT_ID(N'dbo.app_immutable_guard', N'U') IS NOT NULL DELETE FROM dbo.app_immutable_guard WHERE name = N'{name}'")


def build_guard(connection, name: str) -> None:
    """(Re)create one INSTEAD OF trigger from its registry row and the table's current columns."""
    with connection.cursor() as cur:
        cur.execute("SELECT table_name, when_old, allow_update FROM dbo.app_immutable_guard WHERE name = %s", [name])
        table, when_old, allow_update = cur.fetchone()
        cur.execute("SELECT c.name, c.is_identity, c.is_computed FROM sys.columns c WHERE c.object_id = OBJECT_ID(%s) ORDER BY c.column_id",
                    [f"dbo.{table}"])
        cols = cur.fetchall()
        cur.execute("SELECT c.name FROM sys.indexes x JOIN sys.index_columns ic ON ic.object_id = x.object_id AND ic.index_id = x.index_id "
                    "JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id "
                    "WHERE x.object_id = OBJECT_ID(%s) AND x.is_primary_key = 1", [f"dbo.{table}"])
        pk = [r[0] for r in cur.fetchall()]
        on = " AND ".join(f"x.[{k}] = y.[{k}]" for k in pk)  # target row x, incoming row y
        on_di = " AND ".join(f"d.[{k}] = i.[{k}]" for k in pk)
        sets = ", ".join(f"[{c}] = y.[{c}]" for c, ident, comp in cols if c not in pk and not ident and not comp)
        trig = f"{name}_guard"
        cur.execute(f"""CREATE OR ALTER TRIGGER dbo.[{trig}] ON dbo.[{table}] INSTEAD OF UPDATE, DELETE AS
BEGIN
  SET NOCOUNT ON; SET XACT_ABORT OFF;
  IF NOT EXISTS (SELECT 1 FROM inserted)
  BEGIN
    IF EXISTS (SELECT 1 FROM deleted d WHERE {when_old})
    BEGIN RAISERROR(N'immutable_record: {name} rows cannot be deleted', 16, 1); RETURN; END;
    DELETE x FROM dbo.[{table}] x JOIN deleted y ON {on};
    RETURN;
  END;
  IF EXISTS (SELECT 1 FROM deleted d JOIN inserted i ON {on_di} WHERE ({when_old}) AND NOT ({allow_update}))
  BEGIN RAISERROR(N'immutable_record: {name} rows cannot be modified', 16, 1); RETURN; END;
  UPDATE x SET {sets} FROM dbo.[{table}] x JOIN inserted y ON {on};
END""")


def refresh_guards(connection) -> int:
    """Rebuild every immutability guard from the current columns (after migrate). Returns the number rebuilt."""
    with connection.cursor() as cur:
        cur.execute("SELECT CASE WHEN OBJECT_ID(N'dbo.app_immutable_guard', N'U') IS NULL THEN 0 ELSE 1 END")
        if not cur.fetchone()[0]:
            return 0
        cur.execute("SELECT name FROM dbo.app_immutable_guard ORDER BY name")
        names = [r[0] for r in cur.fetchall()]
    for n in names:
        build_guard(connection, n)
    return len(names)
