"""Development-only demo data: operator tenant, operator staff, one demo client with users.

Refuses to run unless DJANGO_DEBUG is on. Passwords come from DEMO_PASSWORD or are generated and printed.
  python manage.py seed_demo
"""
import os
import secrets

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import User
from apps.tenancy.models import Membership, Role, Tenant

USERS = [
    ("operator", "admin@operator.demo", Role.OPERATOR_ADMIN, "Olivia", "Operator"),
    ("operator", "engineer@operator.demo", Role.OPERATOR_ENGINEER, "Ethan", "Engineer"),
    ("demo-client", "admin@client.demo", Role.CLIENT_ADMIN, "Chloe", "Client-Admin"),
    ("demo-client", "user@client.demo", Role.CLIENT_USER, "Umar", "Client-User"),
]


class Command(BaseCommand):
    help = "Create development demo tenants and users (DEBUG only)."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo is for development only (DJANGO_DEBUG must be true).")
        password = os.environ.get("DEMO_PASSWORD") or ("Demo-" + secrets.token_urlsafe(12))
        with transaction.atomic():
            op, _ = Tenant.objects.get_or_create(slug="operator", defaults={"name": "Platform Operator (demo)", "kind": Tenant.Kind.OPERATOR})
            client, _ = Tenant.objects.get_or_create(slug="demo-client", defaults={"name": "Demo Client Energy"})
            tenants = {"operator": op, "demo-client": client}
            for slug, email, role, first, last in USERS:
                user, created = User.objects.get_or_create(email=email, defaults={"first_name": first, "last_name": last, "username": email})
                if created or os.environ.get("DEMO_PASSWORD"):
                    user.set_password(password)
                    user.save()
                Membership.objects.get_or_create(user=user, tenant=tenants[slug], defaults={"role": role})
            eng = User.objects.get(email="engineer@operator.demo")
            Membership.objects.get_or_create(user=eng, tenant=client, defaults={"role": Role.OPERATOR_ENGINEER})
        self.stdout.write(self.style.SUCCESS("Demo data ready (development only)."))
        for _, email, role, *_ in USERS:
            self.stdout.write(f"  {email:28s} {role}")
        self.stdout.write("  engineer@operator.demo is also assigned to demo-client (select it at sign-in).")
        self.stdout.write(f"  password: {password}")
