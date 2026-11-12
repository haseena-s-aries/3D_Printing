"""tenancy 0010: client assignments left with an old role (role changed before propagation existed) are repaired."""
import importlib

from django.apps import apps as django_apps

from apps.tenancy.models import Membership

sync = importlib.import_module("apps.tenancy.migrations.0010_sync_client_assignment_roles").sync


def test_stale_client_assignment_takes_the_aries_role(world):
    eng, op, a = world["op_eng"], world["operator"], world["a"]
    Membership.objects.filter(user=eng, tenant=op).update(role="operator_qa")  # changed without propagation
    Membership.objects.filter(user=eng, tenant=a).update(edit_reviewer=True)
    sync(django_apps, None)
    m = Membership.objects.get(user=eng, tenant=a)
    assert (m.role, m.edit_reviewer) == ("operator_qa", False)
    # Aries Admins and client roles are untouched
    assert Membership.objects.get(user=world["op_admin"], tenant=op).role == "operator_admin"
    assert Membership.objects.get(user=world["a_admin"], tenant=a).role == "client_admin"
