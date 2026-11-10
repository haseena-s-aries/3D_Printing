"""Safety pre-flight before the regression suite: connects ONLY with the explicitly given test configuration (DB_* variables
set by Test-Py314Compatibility.ps1) and refuses to continue unless it is a separate, scoped, case-sensitive test database.
Reads only; changes nothing."""
import os
import sys

import pyodbc

db, login = os.environ["DB_NAME"], os.environ["DB_USER"]
conn = (f"DRIVER={{{os.environ['DB_DRIVER']}}};SERVER={os.environ['DB_HOST']};DATABASE={db};UID={login};PWD={os.environ['DB_PASSWORD']};"
        f"Encrypt=yes;LongAsMax=yes" + (";TrustServerCertificate=yes" if os.environ.get("DB_TRUST_SERVER_CERTIFICATE") == "true" else ""))
problems = []
with pyodbc.connect(conn, timeout=15) as cn:
    c = cn.cursor()
    name, sysadmin, owner = c.execute("SELECT DB_NAME(), IS_SRVROLEMEMBER('sysadmin'), IS_MEMBER('db_owner')").fetchone()
    collation, rcsi = c.execute("SELECT CAST(DATABASEPROPERTYEX(DB_NAME(), 'Collation') AS nvarchar(128)), is_read_committed_snapshot_on "
                                "FROM sys.databases WHERE name = DB_NAME()").fetchone()
    prod_access = c.execute("SELECT HAS_DBACCESS(N'DigitalPassport')").fetchone()[0]
    tables = [r[0] for r in c.execute("SELECT name FROM sys.tables WHERE is_ms_shipped = 0").fetchall()]
print(f"connected to {name} as {login}: sysadmin={sysadmin} db_owner={owner} collation={collation} rcsi={rcsi} "
      f"DigitalPassport access={prod_access} user tables={len(tables)}")
if name.lower() != db.lower() or name.lower() == "digitalpassport":
    problems.append(f"connected database is {name!r}, not the requested separate test database")
if sysadmin == 1:
    problems.append("the test login is sysadmin; use a login scoped to the test database only")
if prod_access == 1:
    problems.append("the test login can open DigitalPassport; it must not")
if owner != 1:
    problems.append("the test login must be db_owner of the TEST database (the suite applies migrations there)")
if not collation or "_CS_" not in collation:
    problems.append(f"collation {collation} is not case-sensitive (create the test database with 00-create-py314-test-database.sql)")
app_tables = {"django_migrations", "app_immutable_guard"}
foreign = [t for t in tables if "_" not in t and t not in app_tables]
if tables and "django_migrations" not in tables:
    problems.append(f"the database already contains tables that are not this application's ({len(tables)} tables, no django_migrations)")
if foreign:
    problems.append(f"unexpected tables: {foreign[:5]}")
for p in problems:
    print("REFUSED:", p)
sys.exit(1 if problems else 0)
