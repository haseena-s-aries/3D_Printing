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


def test_operator_analytics_is_aggregate_and_admin_only(world, requests_ab):
    """Dashboard charts: counts per month / day / status only. The Aries Admin sees every client organisation."""
    d = login(world["op_admin"]).get("/api/v1/operator/analytics/").json()
    assert set(d) == {"scope", "months", "series", "activity", "by_status", "clients", "client_assets"} and d["scope"] == "all"
    assert len(d["months"]) == 12 and all(len(v) == 12 for v in d["series"].values())
    # this month: one part and one manufacturing request in each of clients A and B
    assert d["series"]["parts"][-1] == 2 and d["series"]["requests"][-1] == 2
    assert d["by_status"] == {"submitted": 2}
    assert sum(map(sum, d["activity"]["days"])) == 2 and len(d["activity"]["days"]) == 7
    assert sum(d["clients"][str(world["a"].pk)]) == 2  # its request and its part
    assert {r["name"] for r in d["client_assets"]} == {"Client A Energy", "Client B Marine"}
    assert set(d["client_assets"][0]) == {"id", "name", "counts"}  # no records
    for who in ("a_admin", "b_admin", "a_user"):
        assert login(world[who]).get("/api/v1/operator/analytics/").status_code == 403


def test_operator_analytics_for_engineers_counts_only_their_assigned_clients_and_projects(world, requests_ab):
    """Aries Engineers, QA and support: the same charts over what they can open themselves (the queue's rule)."""
    from apps.projects.models import EngineerAccess
    from apps.tenancy.context import tenant_context

    d = login(world["op_eng"], world["operator"]).get("/api/v1/operator/analytics/").json()  # assigned to client A only
    assert d["scope"] == "assigned"
    assert [r["name"] for r in d["client_assets"]] == ["Client A Energy"]
    assert d["client_assets"][0]["counts"] == {"parts": 1, "passports": 0, "open_requests": 1}
    assert d["series"]["parts"][-1] == 1 and d["series"]["requests"][-1] == 1 and d["by_status"] == {"submitted": 1}
    assert set(d["clients"]) <= {str(world["a"].pk)} and sum(d["series"]["registrations"]) == 0
    # project-limited with no projects: nothing of client A is counted (as in the queue, which lists nothing)
    with tenant_context(world["a"]):
        EngineerAccess.objects.create(tenant=world["a"], user=world["op_eng"], scope=EngineerAccess.Scope.PROJECTS)
    eng = login(world["op_eng"], world["operator"])
    assert eng.get("/api/v1/operator/requests/").json() == []
    d = eng.get("/api/v1/operator/analytics/").json()
    assert d["client_assets"][0]["counts"] == {"parts": 0, "passports": 0, "open_requests": 0}
    assert d["by_status"] == {} and sum(d["series"]["parts"]) == 0 and sum(d["series"]["requests"]) == 0


def test_client_dashboard_analytics_counts_only_the_own_organisation(world, requests_ab):
    for who, other in (("a_admin", "SC-B"), ("b_admin", "SC-A")):
        c = login(world[who])
        d = c.get("/api/v1/dashboard/analytics/").json()
        assert set(d) == {"months", "series", "requests_visible", "activity", "by_status"}
        assert d["series"]["parts"][-1] == 1 and d["series"]["requests"][-1] == 1  # its own part and request, not the other's
        assert d["by_status"] == {"submitted": 1} and d["requests_visible"] is True
        assert other not in str(d)



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


def test_client_dashboard_analytics_for_aries_staff_inside_the_company(world, requests_ab):
    """An Aries Engineer working inside client A counts client A's requests (their queue's scope), never client B's."""
    from apps.projects.models import EngineerAccess
    from apps.tenancy.context import tenant_context

    eng = login(world["op_eng"], world["a"])
    d = eng.get("/api/v1/dashboard/analytics/").json()
    assert d["requests_visible"] is True and d["by_status"] == {"submitted": 1} and "SC-B" not in str(d)
    with tenant_context(world["a"]):  # project-limited with no projects: no requests, as in the queue
        EngineerAccess.objects.create(tenant=world["a"], user=world["op_eng"], scope=EngineerAccess.Scope.PROJECTS)
    d = login(world["op_eng"], world["a"]).get("/api/v1/dashboard/analytics/").json()
    assert d["by_status"] == {} and sum(d["series"]["parts"]) == 0
