"""Run the API, CAD worker or a management command against the demonstration database (development only).

  python scripts/run_demo.py setup          # migrate passport_demo and seed the showcase dataset
  python scripts/run_demo.py api            # API on 127.0.0.1:8000 using passport_demo and .storage-demo
  python scripts/run_demo.py worker         # CAD worker (as app_worker) for passport_demo
  python scripts/run_demo.py manage <args>  # any manage.py command against passport_demo
Passwords for newly created demo accounts come from DEMO_PASSWORD (or are generated and printed once).
"""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_db  # noqa: E402

BACKEND = demo_db.localdb.BACKEND
PY = sys.executable


def env(worker: bool = False) -> dict:
    app, wk = demo_db.urls()
    e = {**os.environ, "DATABASE_URL": wk if worker else app, "LOCAL_STORAGE_ROOT": str(demo_db.STORAGE), "DJANGO_DEBUG": "true"}
    if worker:
        e["WORKER_DB_ROLE"] = ""
    return e


def manage(*args, worker=False) -> int:
    return subprocess.call([PY, str(BACKEND / "manage.py"), *args], cwd=BACKEND, env=env(worker))


if __name__ == "__main__":
    cmd, rest = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("", [])
    if cmd == "setup":
        sys.exit(manage("migrate", "--noinput") or manage("seed_showcase", *rest))
    if cmd == "api":
        sys.exit(manage("runserver", "127.0.0.1:8000", "--noreload", *rest))
    if cmd == "worker":
        sys.exit(manage("run_worker", *rest, worker=True))
    if cmd == "manage":
        sys.exit(manage(*rest))
    raise SystemExit(__doc__)
