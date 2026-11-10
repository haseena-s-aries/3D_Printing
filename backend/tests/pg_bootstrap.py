"""pytest plugin (loaded with -p before pytest-django configures Django).

Tests always run against PostgreSQL (row-level security cannot be tested on SQLite).
- CI: set TEST_DATABASE_URL to a PostgreSQL server where roles app_user and app_worker exist.
- Local: if TEST_DATABASE_URL is not set, start the bundled local PostgreSQL (scripts/localdb.py).
"""
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

if os.environ.get("DB_ENGINE") == "mssql":
    # SQL Server: DB_* variables (and DB_TEST_NAME, an existing database used with --reuse-db) are set by the caller,
    # see SqlServerDev/tools/run_tests.py
    pass
else:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        from scripts.localdb import start

        url, _srv = start(test_mode=True)
    os.environ["DATABASE_URL"] = url
os.environ.setdefault("DJANGO_DEBUG", "true")
os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-secret-key-not-for-production-use-0123456789")
# one storage folder per database engine: tests wipe it, so concurrent SQL Server and PostgreSQL runs must not share it
os.environ["LOCAL_STORAGE_ROOT"] = str(BACKEND / (".storage-test-mssql" if os.environ.get("DB_ENGINE") == "mssql" else ".storage-test"))
os.environ.setdefault("LOGIN_THROTTLE", "1000/min")
for _scope in ("REGISTER", "VERIFY", "PASSWORD_RESET"):  # public flows; a dedicated test checks the limit
    os.environ.setdefault(f"{_scope}_THROTTLE", "1000/min")
os.environ["FAST_PASSWORD_HASHER_FOR_TESTS"] = "1"

import logging as _logging

_logging.getLogger("pgserver").setLevel(_logging.CRITICAL)
_logging.getLogger("pgserver").propagate = False
