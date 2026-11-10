"""Local PostgreSQL for development and tests, without Docker (uses the `pgserver` package).

Creates two roles that mirror production:
  app_user   - application role: LOGIN, NOT superuser, NO BYPASSRLS (owns tables; forced RLS still applies)
  app_worker - CAD worker role: LOGIN, NOT superuser, NO BYPASSRLS; sees the job queue across tenants only

Usage:
  python scripts/localdb.py            # start (or reuse) the server, create roles and database, update .env
  python scripts/localdb.py --stop     # stop the server
CI and Azure use a normal PostgreSQL server instead; this script is for local machines only.
"""
import argparse
import os
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND / ".pgdata"
APP_DB = "passport"


def ensure_timezone_data():
    """The pgserver Windows build ships without PostgreSQL's share/timezone directory, so only
    'GMT' works and Django's SET TIME ZONE 'UTC' fails. PostgreSQL reads compiled IANA TZif files,
    the same format shipped by the Python `tzdata` package, so we copy them in (dev/test only)."""
    import shutil

    import pgserver
    import tzdata

    target = Path(pgserver.__file__).parent / "pginstall" / "share" / "postgresql" / "timezone"
    if (target / "UTC").exists():
        return
    source = Path(tzdata.__file__).parent / "zoneinfo"
    shutil.copytree(source, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns("*.py", "__pycache__", "*.zi", "*.tab"))


def start(test_mode: bool = False):
    import pgserver

    ensure_timezone_data()
    srv = pgserver.get_server(str(DATA_DIR), cleanup_mode=None)
    srv.psql(
        """
        DO $$ BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
            CREATE ROLE app_user LOGIN PASSWORD 'app_user' NOSUPERUSER NOBYPASSRLS CREATEDB;
          END IF;
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_worker') THEN
            CREATE ROLE app_worker LOGIN PASSWORD 'app_worker' NOSUPERUSER NOBYPASSRLS;
          END IF;
        END $$;
        """
    )
    if test_mode:
        # Tests run as app_user and switch to app_worker with SET ROLE to exercise the worker policy. The grant is
        # NON-inheriting (PostgreSQL 16+): app_user may SET ROLE app_worker, but does not silently receive the
        # worker's cross-tenant queue policy (docs/web-review/db-role-rls-finding.md). An older inheriting grant is
        # replaced; nothing else changes and no data is touched.
        srv.psql(
            """
            DO $$ BEGIN
              IF EXISTS (SELECT 1 FROM pg_auth_members a JOIN pg_roles r ON r.oid = a.member JOIN pg_roles m ON m.oid = a.roleid
                         WHERE r.rolname = 'app_user' AND m.rolname = 'app_worker' AND a.inherit_option) THEN
                REVOKE app_worker FROM app_user;
              END IF;
            END $$;
            GRANT app_worker TO app_user WITH INHERIT FALSE, SET TRUE;
            """
        )
    exists = srv.psql(f"SELECT 1 FROM pg_database WHERE datname = '{APP_DB}';")
    if "1 row" not in exists:
        srv.psql(f"CREATE DATABASE {APP_DB} OWNER app_user;")
    uri = srv.get_uri()
    m = re.match(r"postgresql://[^@]*@([^/]+)/", uri)
    hostport = m.group(1) if m else "127.0.0.1:5432"
    return f"postgresql://app_user:app_user@{hostport}/{APP_DB}", srv


def write_env(url: str):
    env_file = BACKEND / ".env"
    text = env_file.read_text() if env_file.exists() else (BACKEND / ".env.example").read_text()
    if re.search(r"^DATABASE_URL=.*$", text, flags=re.M):
        text = re.sub(r"^DATABASE_URL=.*$", f"DATABASE_URL={url}", text, flags=re.M)
    else:
        text += f"\nDATABASE_URL={url}\n"
    env_file.write_text(text)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stop", action="store_true")
    args = ap.parse_args()
    if args.stop:
        import pgserver

        pgserver.get_server(str(DATA_DIR), cleanup_mode="stop").cleanup()
        print("stopped")
        sys.exit(0)
    url, _ = start(test_mode=os.environ.get("LOCALDB_TEST_MODE") == "1")
    write_env(url)
    print(url)
