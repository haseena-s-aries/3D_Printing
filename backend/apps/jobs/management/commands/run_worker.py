"""Run the background worker.

  python manage.py run_worker --once         process at most one job and exit (scale-to-zero job runs)
  python manage.py run_worker --drain        process until the queue is empty, then exit
  python manage.py run_worker                loop forever, sleeping when idle
"""
import logging
import time

from django.core.management.base import BaseCommand

from apps.jobs.queue import run_one

log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Process queued background jobs (CAD conversion)."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--drain", action="store_true")
        parser.add_argument("--sleep", type=float, default=5.0)

    def handle(self, *args, once=False, drain=False, sleep=5.0, **kw):
        from django.conf import settings

        from apps.core.startup import log_startup

        log_startup("Worker")
        if not getattr(settings, "WORKER_DB_ROLE", ""):
            log.warning("WORKER_DB_ROLE is not set: queued jobs are not visible to the worker and stay 'Queued'. "
                        "Set WORKER_DB_ROLE=app_worker for the worker only (service environment).")
        processed = 0
        while True:
            status = run_one()
            if status is not None:
                processed += 1
                self.stdout.write(f"job finished: {status}")
            if once or (drain and status is None):
                break
            if status is None:
                time.sleep(sleep)
        self.stdout.write(f"processed {processed} job(s)")
