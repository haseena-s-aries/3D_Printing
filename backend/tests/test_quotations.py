"""Quotations to the client (decision of 18 Nov 2026): the Aries Admin or Manager quotes the chosen route; the client sees
only the method, price, delivery days and validity, accepts or rejects; release waits for the acceptance."""
from datetime import date, timedelta

from apps.servicerequests.models import Quotation
from apps.tenancy.context import tenant_context

from .conftest import login
from .test_manufacturing_flow import order  # noqa: F401 - fixture


def _prepare(world, order):
    est = f"/api/v1/operator/requests/{order['env'].pk}/estimate/"
    login(world["op_eng"], world["a"]).post(est, {"action": "manual"}, format="json")
    return est


def test_quotation_needs_a_chosen_route_and_an_admin(world, order):
    w = world
    est = _prepare(w, order)
    act = order["act"]
    act(w["op_eng"], "acknowledge")
    r = login(w["op_mgr"]).post(est, {"action": "quote", "price": "500", "delivery_days": 9}, format="json")
    assert r.status_code == 409 and r.json()["error"]["code"] == "route_not_chosen"
    login(w["op_mgr"]).post(est, {"action": "choose", "route": "additive", "note": "Fastest"}, format="json")
    assert login(w["op_eng"], w["a"]).post(est, {"action": "quote", "price": "500", "delivery_days": 9}, format="json").status_code == 403
    for bad in ({"price": "0", "delivery_days": 9}, {"price": "500", "delivery_days": 0},
                {"price": "500", "delivery_days": 9, "valid_until": (date.today() - timedelta(days=1)).isoformat()}):
        assert login(w["op_mgr"]).post(est, {"action": "quote", **bad}, format="json").status_code == 400
    d = login(w["op_mgr"]).post(est, {"action": "quote", "price": "1234.5", "delivery_days": 9, "note": "Price incl. delivery"},
                                format="json").json()
    q = d["quotation"]
    assert q["status"] == "sent" and q["method"] == "3D printing" and q["price"] == "1234.50" and q["route"] == "additive"


def test_client_sees_only_the_quotation_and_accepts_or_rejects(world, order):
    w = world
    est = _prepare(w, order)
    order["act"](w["op_eng"], "acknowledge")
    login(w["op_mgr"]).post(est, {"action": "choose", "route": "conventional"}, format="json")
    login(w["op_mgr"]).post(est, {"action": "quote", "price": "800", "delivery_days": 12}, format="json")
    client = login(w["a_admin"])
    rq = f"/api/v1/requests/{order['ref']['id']}/"
    detail = client.get(rq).json()
    q = detail["quotation"]
    assert set(q) == {"number", "method", "price", "currency", "delivery_days", "valid_until", "note", "status", "status_label",
                      "expired", "sent_at", "decided_at", "client_note"}  # no route key, breakdown, rates, margin or other routes
    assert q["method"] == "Conventional manufacturing" and q["price"] == "800.00" and q["delivery_days"] == 12
    assert "estimate" not in str(detail).lower() and "margin" not in str(detail).lower()
    assert detail["events"][-1]["event"] == "quotation_sent"
    assert client.post(f"{rq}quotation/", {"decision": "reject"}, format="json").json()["error"]["code"] == "reason_required"
    r = client.post(f"{rq}quotation/", {"decision": "reject", "note": "Too expensive"}, format="json").json()
    assert r["quotation"]["status"] == "rejected" and r["quotation"]["client_note"] == "Too expensive"
    assert client.post(f"{rq}quotation/", {"decision": "accept"}, format="json").status_code == 409  # nothing open
    # Aries sends a revised quotation; the old one is superseded
    login(w["op_mgr"]).post(est, {"action": "quote", "price": "700", "delivery_days": 12}, format="json")
    r = client.post(f"{rq}quotation/", {"decision": "accept"}, format="json").json()
    assert r["quotation"]["number"] == 2 and r["quotation"]["status"] == "accepted"
    with tenant_context(w["a"]):
        assert list(Quotation.objects.order_by("number").values_list("status", flat=True)) == ["superseded", "accepted"]
    assert login(w["a_user"]).post(f"{rq}quotation/", {"decision": "accept"}, format="json").status_code in (403, 404)


def test_expired_quotation_cannot_be_accepted_and_withdraw(world, order):
    w = world
    est = _prepare(w, order)
    order["act"](w["op_eng"], "acknowledge")
    login(w["op_mgr"]).post(est, {"action": "choose", "route": "conventional"}, format="json")
    login(w["op_mgr"]).post(est, {"action": "quote", "price": "800", "delivery_days": 12}, format="json")
    with tenant_context(w["a"]):
        Quotation.objects.update(valid_until=date.today() - timedelta(days=1))
    rq = f"/api/v1/requests/{order['ref']['id']}/"
    assert login(w["a_admin"]).get(rq).json()["quotation"]["expired"] is True
    assert login(w["a_admin"]).post(f"{rq}quotation/", {"decision": "accept"}, format="json").json()["error"]["code"] == "quotation_expired"
    d = login(w["op_admin"]).post(est, {"action": "withdraw_quote", "note": "Prices changed"}, format="json").json()
    assert d["quotation"]["status"] == "withdrawn"


def test_release_needs_the_accepted_quotation_for_the_chosen_route(world, order):
    w = world
    est = _prepare(w, order)
    act = order["act"]
    act(w["op_eng"], "acknowledge")
    act(w["op_eng"], "engineering_check")
    act(w["op_qa"], "qa_approve")
    mgr = login(w["op_mgr"])
    mgr.post(est, {"action": "choose", "route": "conventional"}, format="json")
    mgr.post(est, {"action": "quote", "price": "800", "delivery_days": 12}, format="json")
    assert act(w["op_mgr"], "release").json()["error"]["code"] == "quotation_not_accepted"  # client has not decided
    login(w["a_admin"]).post(f"/api/v1/requests/{order['ref']['id']}/quotation/", {"decision": "accept"}, format="json")
    mgr.post(est, {"action": "choose", "route": "additive"}, format="json")  # the route changed after the acceptance
    assert act(w["op_mgr"], "release").json()["error"]["code"] == "quotation_not_accepted"  # quote the new route first
    mgr.post(est, {"action": "choose", "route": "conventional"}, format="json")
    assert act(w["op_mgr"], "release").json()["status"] == "released"
