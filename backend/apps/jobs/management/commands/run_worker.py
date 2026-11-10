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
