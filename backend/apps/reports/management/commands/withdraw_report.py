"""Record the withdrawal of an existing report from the command line (operational containment, e.g. a report whose file was
already moved to quarantine before the withdrawal feature existed). Same append-only record and audit event as the API;
the actor must hold an Aries Engineer membership in the company. Usage:
  manage.py withdraw_report --tenant <slug> --number <RPT-...> --reason "..." --actor <email> [--file-state quarantined --file-note "..."]
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction

from apps.audit.service import record
from apps.reports.models import PassportReport, PassportReportWithdrawal
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Membership, Role, Tenant


class Command(BaseCommand):
    help = "Record the withdrawal of a generated report (append-only)."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", required=True)
        parser.add_argument("--number", required=True)
        parser.add_argument("--reason", required=True)
        parser.add_argument("--actor", required=True, help="email of an Aries Engineer member of the company")
        parser.add_argument("--file-state", default=PassportReportWithdrawal.FileState.RETAINED, choices=PassportReportWithdrawal.FileState.values)
        parser.add_argument("--file-note", default="")

    def handle(self, *args, tenant, number, reason, actor, file_state, file_note, **_):
        if len(reason.strip()) < 10:
            raise CommandError("Give the reason for the withdrawal (at least 10 characters).")
        t = Tenant.objects.get(slug=tenant)
        user = get_user_model().objects.get(email=actor)
        if not Membership.objects.filter(user=user, tenant=t, role=Role.OPERATOR_ENGINEER).exists():
            raise CommandError(f"{actor} is not an Aries Engineer in {tenant}.")
        with tenant_context(t):
            report = PassportReport.objects.get(number=number)
            try:
                with transaction.atomic():
                    w = PassportReportWithdrawal.objects.create(tenant=t, created_by=user, report=report, reason=reason.strip()[:2000],
                                                                file_state=file_state, file_note=file_note[:300])
            except IntegrityError:
                raise CommandError(f"{number} is already withdrawn.")
            record(None, "passport_report.withdrawn", obj=report, actor=user, tenant=t, data={
                "number": report.number, "variant": report.variant, "revision": report.revision_number, "reason": w.reason,
                "file_state": file_state, "file_note": file_note[:300], "via": "withdraw_report command"})
        self.stdout.write(f"{number} withdrawn ({w.get_file_state_display()}).")
