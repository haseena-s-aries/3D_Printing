"""Manufacturing order flow (decision of 13 Nov 2026): publish makes a part orderable; each order passes the
engineering check, QA check (another person), release by an Aries Admin/Manager, production, QA inspection and delivery."""
import pytest

from apps.passports.models import DigitalPassport
from apps.servicerequests.models import ClientRequest
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Membership, Role

from .conftest import login, make_user
from .test_service_requests import TOMORROW, envelope_for, unread


@pytest.fixture
def order(world):
    w = world
    w["op_qa"] = make_user("op.qa@example.test", w["operator"], Role.OPERATOR_QA)
    Membership.objects.create(user=w["op_qa"], tenant=w["a"], role=Role.OPERATOR_QA)
    w["op_mgr"] = make_user("op.mgr@example.test", w["operator"], Role.OPERATOR_MANAGER)
    eng = login(w["op_eng"], w["a"])
    part = eng.post("/api/v1/parts/", {"part_number": "MF-1", "name": "Valve seat"}, format="json").json()
    passport = eng.post("/api/v1/passports/", {"part": part["id"]}, format="json").json()
    with tenant_context(w["a"]):
        DigitalPassport.objects.filter(pk=passport["id"]).update(publication_state="published", manufacturing_eligibility="eligible_subject_to_authorisation")
    body = {"request_type": "manufacturing", "part": part["id"], "quantity": 1, "required_date": TOMORROW,
            "delivery_location": "Site A", "services": ["Additive manufacturing"], "priority": "routine"}
    ref = login(w["a_admin"]).post("/api/v1/requests/", body, format="json").json()
    assert ref["kind"] == "manufacturing_request", ref
    env = envelope_for(w, ref["reference"])

    def act(user, action, message="", tenant=None):
        return login(user, tenant).post(f"/api/v1/operator/requests/{env.pk}/act/", {"action": action, "message": message}, format="json")
    return {"ref": ref, "env": env, "act": act, "passport": passport}


def test_full_order_chain_with_roles(world, order):
    act, w = order["act"], world
    assert act(w["op_eng"], "acknowledge").json()["status"] == "acknowledged"
    assert act(w["op_qa"], "engineering_check").status_code == 403  # engineers only
    assert act(w["op_eng"], "engineering_check").json()["status"] == "engineering_checked"
    assert act(w["op_admin"], "qa_approve").status_code == 403  # QA only
    assert act(w["op_qa"], "qa_approve").json()["status"] == "qa_approved"
    r = act(w["op_eng"], "release")
    assert r.status_code == 403 and r.json()["error"]["code"] == "role_not_allowed"
    assert act(w["op_mgr"], "release").json()["status"] == "released"
    assert act(w["op_eng"], "start_production").json()["status"] == "in_production"
    assert act(w["op_qa"], "inspection_failed").status_code == 400  # what was wrong is required
    failed = act(w["op_qa"], "inspection_failed", "Surface porosity, reprint").json()
    assert failed["status"] == "in_production" and failed["events"][-1]["event"] == "inspection_failed"
    assert act(w["op_qa"], "inspection_passed").json()["status"] == "inspected"
    assert act(w["op_admin"], "deliver").json()["status"] == "completed"
    detail = login(w["a_admin"]).get(f"/api/v1/requests/{order['ref']['id']}/").json()
    assert [e["event"] for e in detail["events"]] == ["submitted", "acknowledged", "engineering_checked", "qa_approved", "released",
                                                      "in_production", "inspection_failed", "inspected", "completed"]
    titles = unread(w["a_admin"])
    assert any("released for production" in t for t in titles) and any("inspection found issues" in t for t in titles)


def test_qa_check_is_never_by_the_engineering_checker(world, order, settings):
    settings.FOUR_ROLE_MODEL_ENABLED = True
    act, w = order["act"], world
    m = Membership.objects.get(user=w["op_eng"], tenant=w["operator"])
    m.qa_permitted = True  # an engineer with the QA permission...
    m.save()
    act(w["op_eng"], "acknowledge")
    act(w["op_eng"], "engineering_check")
    r = act(w["op_eng"], "qa_approve")
    assert r.status_code == 403 and r.json()["error"]["code"] == "separation_of_duties"  # ...cannot QA their own check
    assert act(w["op_qa"], "qa_approve").status_code == 200


def test_operator_detail_reports_my_steps(world, order):
    env = order["env"]
    assert login(world["op_qa"], world["a"]).get(f"/api/v1/operator/requests/{env.pk}/").json()["my_steps"] == ["qa"]
    assert login(world["op_mgr"]).get(f"/api/v1/operator/requests/{env.pk}/").json()["my_steps"] == ["admin"]


def _complete_passport(world):
    eng = login(world["op_eng"], world["a"])
    part = eng.post("/api/v1/parts/", {"part_number": "MF-2", "name": "Bush"}, format="json").json()
    passport = eng.post("/api/v1/passports/", {"part": part["id"]}, format="json").json()
    with tenant_context(world["a"]):
        DigitalPassport.objects.filter(pk=passport["id"]).update(publication_state="complete")
    return part, passport


def test_publish_makes_the_part_orderable_and_unpublish_stops_it(world):
    part, passport = _complete_passport(world)
    root = f"/api/v1/operator/passports/{world['a'].pk}/{passport['id']}/"
    admin = login(world["op_admin"])
    r = admin.post(root, {"action": "publish"}, format="json").json()
    assert r == {"passport_state": "published", "manufacturing_eligibility": "eligible_subject_to_authorisation"}
    body = {"request_type": "manufacturing", "part": part["id"], "quantity": 1, "required_date": TOMORROW,
            "delivery_location": "Site A", "services": ["Additive manufacturing"], "priority": "routine"}
    client = login(world["a_admin"])
    assert client.post("/api/v1/requests/", body, format="json").json()["kind"] == "manufacturing_request"
    assert admin.post(root, {"action": "suspend_ordering", "reason": "Material change"}, format="json").json()["manufacturing_eligibility"] == "suspended"
    assert client.post("/api/v1/requests/", body, format="json").json()["kind"] == "enquiry"  # suspended: only an enquiry
    assert admin.post(root, {"action": "allow_ordering"}, format="json").json()["manufacturing_eligibility"] == "eligible_subject_to_authorisation"
    assert admin.post(root, {"action": "unpublish", "reason": "Rework"}, format="json").json()["manufacturing_eligibility"] == "not_eligible"
    assert admin.post(root, {"action": "suspend_ordering"}, format="json").status_code == 409  # not published
    assert login(world["op_eng"]).post(root, {"action": "suspend_ordering"}, format="json").status_code == 403  # register is admin-only
    with tenant_context(world["a"]):
        assert ClientRequest.objects.filter(kind="manufacturing_request").count() == 1


def test_send_reply_is_not_offered_on_orders_and_an_answered_order_can_continue(world, order):
    act, w = order["act"], world
    act(w["op_eng"], "acknowledge")
    r = act(w["op_eng"], "respond", "We will start soon")
    assert r.status_code == 409  # orders use "message", which keeps the status
    assert act(w["op_eng"], "message", "We will start soon").json()["status"] == "acknowledged"
    with tenant_context(w["a"]):  # an order answered before this change can still go to the engineering check
        ClientRequest.objects.filter(pk=order["ref"]["id"]).update(status="answered")
    assert act(w["op_eng"], "engineering_check").json()["status"] == "engineering_checked"


def test_order_shows_the_ordered_passport_revision_to_aries_staff(world, order):
    from apps.audit.models import AuditEvent

    env = order["env"]
    url = f"/api/v1/operator/requests/{env.pk}/passport/"
    for user, tenant in ((world["op_qa"], None), (world["op_eng"], world["a"]), (world["op_mgr"], None)):
        d = login(user, tenant).get(url)
        assert d.status_code == 200, d.content
        body = d.json()
        assert body["passport_id"] == order["passport"]["id"] and body["part_number"] == "MF-1"
        assert body["ordered_revision_number"] == 1 and body["revision"]["revision_number"] == 1
        assert {"files", "reports", "evidence_files", "revision"} <= set(body)
    assert login(world["op_qa"]).get(f"{url}files/00000000-0000-0000-0000-000000000000/").status_code == 404
    assert login(world["a_admin"]).get(url).status_code == 403  # Aries staff only
    with tenant_context(world["a"]):
        assert AuditEvent.objects.filter(action="passport.viewed_by_aries", data__request=order["ref"]["reference"]).exists()


def test_request_shows_full_part_details_even_without_a_passport(world, order):
    env = order["env"]
    body = login(world["op_qa"]).get(f"/api/v1/operator/requests/{env.pk}/passport/").json()
    assert body["has_passport"] is True and body["part"]["part_number"] == "MF-1" and body["part"]["name"] == "Valve seat"
    # an enquiry on a part that has no passport yet still shows the part and its files
    eng = login(world["op_eng"], world["a"])
    part = eng.post("/api/v1/parts/", {"part_number": "NP-9", "name": "Gland", "manufacturer": "OEM Ltd", "dimensions": "Ø20 x 5 mm"},
                    format="json").json()
    req = login(world["a_admin"]).post("/api/v1/requests/", {"request_type": "manufacturing", "part": part["id"], "quantity": 1,
                                                             "required_date": TOMORROW, "delivery_location": "Site A",
                                                             "services": ["Additive manufacturing"], "priority": "routine"},
                                       format="json").json()
    assert req["kind"] == "enquiry"
    e2 = envelope_for(world, req["reference"])
    d = login(world["op_admin"]).get(f"/api/v1/operator/requests/{e2.pk}/passport/").json()
    assert d["has_passport"] is False and d["part"]["manufacturer"] == "OEM Ltd" and d["part"]["dimensions"] == "Ø20 x 5 mm"
    assert d["files"] == [] and d["reports"] == []
    assert login(world["op_eng"], world["a"]).get(f"/api/v1/operator/requests/{e2.pk}/passport/reports/00000000-0000-0000-0000-000000000000/").status_code == 404
