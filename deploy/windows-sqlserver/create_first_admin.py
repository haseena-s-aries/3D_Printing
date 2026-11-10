"""Create the Aries organisation and its first Aries Admin in an empty database (run once on the server).

  $env:FIRST_ADMIN_EMAIL = "you@yourcompany.com"; $env:FIRST_ADMIN_PASSWORD = "<a strong password, 12+ characters>"
  python manage.py shell -c "exec(open(r'C:\\DigitalPassport\\deploy\\create_first_admin.py', encoding='utf-8').read())"
  Remove-Item Env:FIRST_ADMIN_PASSWORD

Idempotent: an existing user or membership is left as it is (the password is set only for a new user). Prints no password.
"""
import os

from django.contrib.auth.password_validation import validate_password
from django.db import transaction

from apps.accounts.models import User
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Membership, Role, Tenant

email = os.environ["FIRST_ADMIN_EMAIL"].strip().lower()
password = os.environ["FIRST_ADMIN_PASSWORD"]
with transaction.atomic():
    aries, created_org = Tenant.objects.get_or_create(slug="aries", defaults={"name": "Aries (Platform Operator)", "kind": Tenant.Kind.OPERATOR})
    user = User.objects.filter(email=email).first()
    if user is None:
        user = User(email=email, username=email, first_name="Aries", last_name="Admin")
        validate_password(password, user)
        user.set_password(password)
        user.save()
    with tenant_context(aries):
        m, created_m = Membership.objects.get_or_create(user=user, tenant=aries, defaults={"role": Role.OPERATOR_ADMIN})
print(f"Aries organisation {'created' if created_org else 'exists'}; {email}: membership {m.role} {'created' if created_m else 'exists'}")
