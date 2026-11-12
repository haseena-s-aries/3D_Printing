"""Organisation scoping for operator staff: offered workspaces, assignment-limited intake queue, administrator
oversight (summaries and aggregate overview only) and cross-tenant isolation of detailed records."""
from datetime import date, timedelta

import pytest
from rest_framework.test import APIClient

from apps.tenancy.models import Membership

from .conftest import PASSWORD, login, make_user

LATER = (date.today() + timedelta(days=10)).isoformat()


@pytest.fixture
def requests_ab(world):
    """One enquiry in client A and one in client B. Parts are created by operator staff assigned to each client."""
    from apps.accounts.models import User

    tmp = User.objects.create_user(email="tmp.eng@example.test", password=PASSWORD)  # assigned to client B only
    Membership.objects.create(user=tmp, tenant=world["operator"], role="operator_engineer")
    Membership.objects.create(user=tmp, tenant=world["b"], role="operator_engineer")
    out = {}
    for key, eng in (("a", login(world["op_eng"], world["a"])), ("b", login(tmp, world["b"]))):
        part = eng.post("/api/v1/parts/", {"part_number": f"SC-{key.upper()}", "name": f"Part {key}"}, format="json").json()
        r = login(world[f"{key}_admin"]).post("/api/v1/requests/", {"request_type": "manufacturing", "part": part["id"], "quantity": 1,
                                                                     "required_date": LATER, "delivery_location": "Store"}, format="json")
        assert r.status_code == 201, r.content
        out[key] = r.json()["reference"]
    return out


def refs(c):
    return {(r["client_name"], r["reference"]) for r in c.get("/api/v1/operator/requests/").json()}


def test_engineer_sees_only_assigned_clients_in_the_queue(world, requests_ab):
    eng = login(world["op_eng"], world["a"])  # assigned to client A only
    rows = eng.get("/api/v1/operator/requests/").json()
    assert {r["client_name"] for r in rows} == {"Client A Energy"} and all(r["assigned"] for r in rows)
    # the same from the operator organisation context
    assert {r["client_name"] for r in login(world["op_eng"], world["operator"]).get("/api/v1/operator/requests/").json()} == {"Client A Energy"}


def test_administrator_sees_opens_and_answers_every_clients_requests(world, requests_ab):
    """Decision of 12 Nov 2026: Aries Admins and Managers answer client requests without being assigned to the client."""
    admin = login(world["op_admin"])
    rows = admin.get("/api/v1/operator/requests/").json()
    assert {r["client_name"] for r in rows} == {"Client A Energy", "Client B Marine"}
    assert all(r["assigned"] for r in rows)
    for r in rows:
        assert admin.get(f"/api/v1/operator/requests/{r['id']}/").status_code == 200
        assert admin.post(f"/api/v1/operator/requests/{r['id']}/act/", {"action": "acknowledge"}, format="json").status_code == 200
    # an unassigned engineer still cannot open them
    other = make_user("other.eng@example.test", world["operator"], "operator_engineer")
    assert login(other).get(f"/api/v1/operator/requests/{rows[0]['id']}/").json()["error"]["code"] == "not_assigned"


def test_clients_never_reach_the_operator_queue_or_overview(world, requests_ab):
    for who in ("a_admin", "a_user", "b_admin"):
        c = login(world[who])
        assert c.get("/api/v1/operator/requests/").status_code == 403
        assert c.get("/api/v1/operator/overview/").status_code == 403


def test_operator_overview_is_aggregate_and_admin_only(world, requests_ab):
    rows = login(world["op_admin"]).get("/api/v1/operator/overview/").json()
    by = {r["slug"]: r for r in rows}
    assert by["client-a"]["counts"]["parts"] == 1 and by["client-a"]["counts"]["open_requests"] == 1
    assert by["client-a"]["counts"]["awaiting_acknowledgement"] == 1 and by["client-a"]["counts"]["assigned_staff"] == 1
    assert set(by["client-a"]) == {"id", "name", "slug", "status", "hosting_model", "counts"}  # no records
    assert login(world["op_eng"], world["operator"]).get("/api/v1/operator/overview/").status_code == 403


def test_assigned_engineer_is_not_offered_the_operator_organisation(world, client):
    # one client assignment: signs straight into it, without choosing
    r = client.post("/api/v1/auth/token/", {"email": "op.eng@example.test", "password": PASSWORD}, format="json")
    assert r.status_code == 200 and r.json()["session"]["tenant"]["slug"] == "client-a"
    c = login(world["op_eng"], world["a"])
    assert {m["tenant"]["slug"] for m in c.get("/api/v1/auth/memberships/").json()} == {"client-a"}
    # the operator identity is preserved: explicit sign-in still works and the queue is reachable from the client
    assert login(world["op_eng"], world["operator"]).get("/api/v1/auth/me/").status_code == 200
    assert c.get("/api/v1/operator/requests/").status_code == 200
    # administrators keep the operator organisation
    assert {m["tenant"]["slug"] for m in login(world["op_admin"]).get("/api/v1/auth/memberships/").json()} == {"operator"}


def test_switching_changes_every_query_to_the_new_organisation(world, client):
    Membership.objects.create(user=world["op_eng"], tenant=world["b"], role="operator_engineer")
    a = login(world["op_eng"], world["a"])
    a.post("/api/v1/parts/", {"part_number": "ONLY-A", "name": "a"}, format="json")
    r = a.post("/api/v1/auth/switch/", {"tenant": "client-b", "refresh": a.refresh_token}, format="json")
    assert r.status_code == 200
    b = APIClient()
    b.credentials(HTTP_AUTHORIZATION=f"Bearer {r.json()['access']}")
    assert b.get("/api/v1/auth/me/").json()["tenant"]["slug"] == "client-b"
    assert b.get("/api/v1/parts/", {"search": "ONLY-A"}).json()["count"] == 0
    assert b.get("/api/v1/dashboard/summary/").json()["parts"]["total"] == 0
    # switching to an organisation without membership is refused
    assert b.post("/api/v1/auth/switch/", {"tenant": "operator-nope"}, format="json").status_code == 403
