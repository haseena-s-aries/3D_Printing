"""Separate local demonstration database (passport_demo) and file store (.storage-demo), development only.

The demo dataset lives apart from the database used by development and the E2E tests (passport), so test runs
never clutter the demonstration and the demonstration never affects tests.

  python scripts/demo_db.py create    # create passport_demo if missing (embedded PostgreSQL from localdb.py)
  python scripts/demo_db.py reset     # DROP passport_demo and delete .storage-demo, then create it empty again
  python scripts/demo_db.py url       # print the app and worker connection URLs
Only the database named passport_demo and the folder .storage-demo can be touched by this script.
Then: python scripts/run_demo.py setup   (migrate + seed), and python scripts/run_demo.py api / worker.
"""
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import localdb  # noqa: E402

DEMO_DB = "passport_demo"
STORAGE = localdb.BACKEND / ".storage-demo"


def urls() -> tuple[str, str]:
    """Same server as the development database (host and port from backend/.env), different database name."""
    text = (localdb.BACKEND / ".env").read_text()
    m = re.search(r"^DATABASE_URL=postgresql://[^@]+@([^/]+)/", text, flags=re.M)
    if not m:
        raise SystemExit("DATABASE_URL not found in backend/.env; run scripts/localdb.py first.")
    host = m.group(1)
    return f"postgresql://app_user:app_user@{host}/{DEMO_DB}", f"postgresql://app_worker:app_worker@{host}/{DEMO_DB}"


def create(srv):
    if "1 row" not in srv.psql(f"SELECT 1 FROM pg_database WHERE datname = '{DEMO_DB}';"):
        srv.psql(f"CREATE DATABASE {DEMO_DB} OWNER app_user;")
        print(f"created database {DEMO_DB}")
    else:
        print(f"database {DEMO_DB} exists")
    STORAGE.mkdir(exist_ok=True)


def reset(srv):
    assert DEMO_DB == "passport_demo" and STORAGE.name == ".storage-demo"  # never anything else
    srv.psql(f"DROP DATABASE IF EXISTS {DEMO_DB} WITH (FORCE);")
    if STORAGE.exists():
        shutil.rmtree(STORAGE)
    print(f"dropped database {DEMO_DB} and removed {STORAGE.name}")
    create(srv)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "create"
    if cmd == "url":
        app, worker = urls()
        print(f"app:    {app}\nworker: {worker}\nstorage: {STORAGE}")
        sys.exit(0)
    if cmd not in ("create", "reset"):
        raise SystemExit(__doc__)
    _, server = localdb.start()
    (reset if cmd == "reset" else create)(server)
    print(urls()[0])
