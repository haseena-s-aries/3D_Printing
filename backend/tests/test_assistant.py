"""The in-app assistant (apps.assistant): rule-based answers with the screens' visibility. The Aries Admin and Aries
Manager search everything; everyone else only what they can open."""
from apps.tenancy.models import Role

from .conftest import login, make_user
from .test_org_scoping import (
    requests_ab,  # noqa: F401 - fixture: one manufacturing request in client A and one in client B
)

URL = "/api/v1/assistant/"


def ask(client, message, **context):
    r = client.post(URL, {"message": message, "context": context}, format="json")
    assert r.status_code == 200, r.content
    return r.json()


def text(answer) -> str:
    return answer["answer"] + " " + " ".join(f"{i['title']} {i['subtitle']}" for i in answer["items"])


def test_admin_and_manager_have_full_access(world, requests_ab):  # noqa: F811
    manager = make_user("op.manager@example.test", world["operator"], Role.OPERATOR_MANAGER)
    for who in (login(world["op_admin"]), login(manager)):
        assert who.get(URL).json()["full_access"] is True
        assert ask(who, "how many open requests?")["answer"] == "2 open request(s)."
        found = text(ask(who, "show requests from client b marine"))
        assert "Client B Marine" in found and "Client A Energy" not in found
        assert "Client A Energy" in text(ask(who, "find client a"))  # companies
        assert "a.user@example.test" in text(ask(who, "search users a.user"))  # people of any organisation
        assert "SC-B" in text(ask(who, "show parts SC-B"))  # spare parts of any company (summary)


def test_an_engineer_sees_only_the_assigned_client(world, requests_ab):  # noqa: F811
    eng = login(world["op_eng"], world["operator"])  # assigned to client A only
    assert eng.get(URL).json()["full_access"] is False
    assert ask(eng, "how many open requests")["answer"] == "1 open request(s)."
    assert "Client B" not in text(ask(eng, "show all requests"))
    assert "Client B" not in text(ask(eng, "client b marine")) and "SC-B" not in text(ask(eng, "SC-B"))
    assert ask(eng, "search users a.user")["items"] == []  # no people search outside their own role


def test_a_client_sees_only_its_own_requests_and_next_steps(world, requests_ab):  # noqa: F811
    a, b = login(world["a_admin"]), login(world["b_admin"])
    own = ask(a, f"what is the status of {requests_ab['a']}")  # client references restart per company (MR-2026-00001 in both)
    assert "SC-A" in text(own) and "SC-B" not in text(own) and "Next: Aries acknowledges it." in own["answer"]
    assert "SC-A" not in text(ask(b, f"where is {requests_ab['a']}"))
    intake_a = next(r["intake_number"] for r in login(world["op_admin"]).get("/api/v1/operator/requests/").json()
                    if r["client_name"] == "Client A Energy")
    assert "can't find" in ask(b, f"status of {intake_a}")["answer"]  # another company's request
    assert ask(a, "how many open requests do i have")["answer"] == "1 open request(s)."


def test_what_next_for_aries_uses_the_request_flow(world, requests_ab):  # noqa: F811
    admin = login(world["op_admin"])
    row = next(r for r in admin.get("/api/v1/operator/requests/").json() if r["client_name"] == "Client A Energy")
    assert "acknowledge it" in ask(admin, f"what's next for {row['intake_number']}")["answer"]
    admin.post(f"/api/v1/operator/requests/{row['id']}/act/", {"action": "acknowledge"}, format="json")
    # the open request page is the context; this request is an enquiry (its part has no published passport)
    answer = ask(admin, "what should i do next?", path=f"/incoming/{row['id']}")["answer"]
    assert "manufacturing enquiry" in answer and "can never be released" in answer
    assert "it is an enquiry" in ask(admin, f"why can't I release {row['intake_number']}")["answer"]


def test_next_steps_of_a_manufacturing_order():
    from apps.assistant.engine import next_step
    from apps.assistant.lookups import Scope

    aries = Scope(tenant=None, role="operator_admin", full=True, staff=True, client_member=False, in_client=False, users=True)
    client = Scope(tenant=None, role="client_admin", full=False, staff=False, client_member=True, in_client=True, users=True)
    order = {"kind": "manufacturing_request", "client_id": "", "request_id": ""}
    expected = {"acknowledged": "engineering check", "engineering_checked": "QA check", "released": "start production",
                "in_production": "inspection", "inspected": "delivery", "completed": "nothing more to do"}
    for status, step in expected.items():
        assert step in " ".join(next_step({**order, "status": status}, aries)), status
    assert "(Aries QA" in next_step({**order, "status": "engineering_checked"}, aries)[0]
    assert "(Aries" not in next_step({**order, "status": "engineering_checked"}, client)[0]  # clients see no Aries roles
    assert "send your answer" in next_step({**order, "status": "information_requested"}, client)[0]


def test_passports_are_found_only_by_who_may_open_them(world, requests_ab):  # noqa: F811
    eng = login(world["op_eng"], world["a"])
    part = eng.get("/api/v1/parts/").json()["results"][0]
    passport = eng.post("/api/v1/passports/", {"part": part["id"]}, format="json").json()
    number = passport["passport_number"]
    assert number in text(ask(login(world["a_admin"]), f"show {number}"))
    assert "can't find" in ask(login(world["b_admin"]), f"show {number}")["answer"]
    assert number in text(ask(login(world["op_admin"]), f"passport {number}"))


def test_how_to_answers_follow_the_role_and_tolerate_typos(world):
    client, admin = login(world["a_admin"]), login(world["op_admin"])
    assert "Request 3D scanning of a part" in ask(client, "how do i request 3d scaning")["answer"]
    assert "Accept or reject a quotation" in ask(client, "how to accept the quatation")["answer"]
    assert "Archive a spare part" in ask(admin, "how do I archive a part?")["answer"]
    assert "Click Archive on the part" not in ask(client, "how do I archive a part?")["answer"]  # an Aries Admin task
    assert "R-L1, R-L2 and R-L3" in ask(client, "what is rl2")["answer"]
    unknown = ask(client, "zzqx blorf")
    assert "didn't understand" in unknown["answer"] and unknown["suggestions"]


def test_the_assistant_needs_a_signed_in_user(db):
    from rest_framework.test import APIClient

    assert APIClient().post(URL, {"message": "hello"}, format="json").status_code == 401
