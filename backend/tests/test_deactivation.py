"""Deactivated people cannot sign in (decision of 20 Nov 2026). An Aries staff member deactivated in the Aries
organisation also loses their assigned client companies, immediately (open sessions too); reactivating restores them."""
from rest_framework.test import APIClient

from apps.tenancy.models import Membership

from .conftest import PASSWORD, login


def _sign_in(email, tenant=None):
    body = {"email": email, "password": PASSWORD, **({"tenant": tenant} if tenant else {})}
    return APIClient().post("/api/v1/auth/token/", body, format="json")


def test_a_deactivated_aries_engineer_cannot_sign_in_anywhere_and_reactivation_restores(world):
    admin = login(world["op_admin"])
    open_session = login(world["op_eng"], world["a"])  # working inside assigned client A
    assert open_session.get("/api/v1/parts/").status_code == 200
    m = Membership.objects.get(user=world["op_eng"], tenant=world["operator"])
    assert admin.patch(f"/api/v1/users/{m.pk}/", {"is_active": False}, format="json").status_code == 200

    r = _sign_in("op.eng@example.test")
    assert r.status_code == 403 and r.json()["error"]["code"] == "no_active_membership"
    assert _sign_in("op.eng@example.test", "client-a").status_code == 403
    assert open_session.get("/api/v1/parts/").status_code == 401  # the open session ends at once
    # the client assignment itself is unchanged
    assert Membership.objects.get(user=world["op_eng"], tenant=world["a"]).is_active

    assert admin.patch(f"/api/v1/users/{m.pk}/", {"is_active": True}, format="json").status_code == 200
    r = _sign_in("op.eng@example.test")
    assert r.status_code == 200 and r.json()["session"]["tenant"]["name"] == "Client A Energy"


def test_a_deactivated_client_user_cannot_sign_in(world):
    m = Membership.objects.get(user=world["a_user"], tenant=world["a"])
    session = login(world["a_user"])
    assert login(world["a_admin"]).patch(f"/api/v1/users/{m.pk}/", {"is_active": False}, format="json").status_code == 200
    assert _sign_in("a.user@example.test").status_code == 403
    assert session.get("/api/v1/parts/").status_code == 401


def test_people_without_an_aries_membership_are_not_affected(world):
    # client staff never had an Aries membership: their access depends only on their own memberships
    assert _sign_in("a.admin@example.test").status_code == 200
