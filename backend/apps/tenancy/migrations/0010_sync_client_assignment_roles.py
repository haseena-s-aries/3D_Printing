"""One-off: client-company assignments of Aries staff take the role the person holds in the Aries organisation
(Engineer / QA / Support). Before this, changing the role on the Users page left the assignments with the old role, so
the person kept working inside the client company under it (role changes made before propagate_operator_role existed).
Same rule as tenancy.api.propagate_operator_role: active assignments only; the edit-reviewer flag is for engineers only."""
from django.db import migrations

ASSIGNABLE = ["operator_engineer", "operator_qa", "operator_support"]


def sync(apps, schema_editor):
    Membership = apps.get_model("tenancy", "Membership")
    for home in Membership.objects.filter(tenant__kind="operator", role__in=ASSIGNABLE, is_active=True):
        stale = (Membership.objects.filter(user_id=home.user_id, tenant__kind="client", role__in=ASSIGNABLE, is_active=True)
                 .exclude(role=home.role))
        if home.role == "operator_engineer":
            stale.update(role=home.role)
        else:
            stale.update(role=home.role, edit_reviewer=False)


class Migration(migrations.Migration):
    dependencies = [("tenancy", "0009_operator_manager_role")]
    operations = [migrations.RunPython(sync, migrations.RunPython.noop)]
