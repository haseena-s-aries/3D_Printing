"""Start due quarterly assessment runs (CN-007 Phase 6). Run daily from the host scheduler (cron / Task Scheduler);
idempotent: at most one scheduled run per company, quarter and scope. The worker processes the queued runs."""
from django.core.management.base import BaseCommand

from apps.intelligence.runs import run_due_schedules


class Command(BaseCommand):
    help = "Start due quarterly inventory assessment runs."

    def handle(self, *args, **options):
        started = run_due_schedules()
        self.stdout.write("\n".join(started) if started else "No assessment run due.")
