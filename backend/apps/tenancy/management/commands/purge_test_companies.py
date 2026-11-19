"""Permanently erase the test companies that an Aries Admin or Manager queued for deletion in the app.

Run it with the privileged owner login (the one used for `manage.py migrate`; on Windows set DB_USER and DB_PASSWORD for
the session). The application's own login cannot disable the database guards this needs, by design.

    python manage.py purge_test_companies --dry-run     # list what would be erased, change nothing
    python manage.py purge_test_companies               # list, ask for confirmation, erase
    python manage.py purge_test_companies --slug abc    # only one company
    python manage.py purge_test_companies --yes         # no prompt (scheduled runs)

Back up the database first. A company that cannot be erased completely is left untouched (all or nothing).
"""
from django.core.management.base import BaseCommand, CommandError

from apps.tenancy import purge


class Command(BaseCommand):
    help = "Erase the test companies queued for deletion (privileged; run as the database owner)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Only list what would be erased.")
        parser.add_argument("--yes", action="store_true", help="Do not ask for confirmation.")
        parser.add_argument("--slug", action="append", default=[], help="Limit to this company (repeatable).")

    def handle(self, *args, dry_run=False, yes=False, slug=(), **opts):
        companies = list(purge.queued())
        if slug:
            wanted = set(slug)
            missing = wanted - {c.slug for c in companies}
            if missing:
                raise CommandError(f"Not queued for deletion (or not a test company): {', '.join(sorted(missing))}")
            companies = [c for c in companies if c.slug in wanted]
        if not companies:
            self.stdout.write("No test company is queued for deletion.")
            return
        self.stdout.write(self.style.WARNING(f"{len(companies)} test company(ies) queued for deletion:"))
        for c in companies:
            counts = purge.row_counts(c)
            when = c.deletion_requested_at.strftime("%Y-%m-%d %H:%M")
            by = c.deletion_requested_by.email if c.deletion_requested_by_id else "?"
            self.stdout.write(f"\n  {c.name} ({c.slug}), queued {when} by {by}: {sum(counts.values())} rows in {len(counts)} tables")
            for label, n in sorted(counts.items(), key=lambda x: -x[1])[:8]:
                self.stdout.write(f"      {label}: {n}")
        if dry_run:
            self.stdout.write("\nDry run: nothing was erased.")
            return
        if not yes:
            self.stdout.write(self.style.ERROR("\nThis erases the companies above, their users, records, audit rows and files FOR GOOD."))
            if input("Type ERASE to continue: ").strip() != "ERASE":
                raise CommandError("Cancelled; nothing was erased.")
        failed = 0
        for c in companies:
            try:
                result = purge.purge(c, log=self.stdout.write)
            except Exception as exc:  # noqa: BLE001 - one company must not stop the others; its transaction was rolled back
                failed += 1
                self.stderr.write(self.style.ERROR(f"{c.name}: NOT erased, nothing changed ({type(exc).__name__}: {exc})"))
                continue
            self.stdout.write(self.style.SUCCESS(
                f"{result['company']}: erased {result['rows']} rows, {result['users_deleted']} users, {result['files']} files"
                + (f" ({result['users_deactivated']} users kept inactive)" if result["users_deactivated"] else "")))
        if failed:
            raise CommandError(f"{failed} company(ies) could not be erased.")
