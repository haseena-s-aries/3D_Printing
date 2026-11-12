"""Passport approval (decision of 12 Nov 2026), the Aries approval queue, client messages waiting for an Aries reply, and the
Aries Manager's user list."""
import pytest

from apps.tenancy.context import tenant_context
from apps.tenancy.models import Membership, Role

from .conftest import login, make_user
from .test_service_requests import catalog, envelope_for, manufacturing, unread  # noqa: F401


@pytest.fixture
def ap(world):
    w = world
    w["op_eng2"] = make_user("op.eng2@example.test", w["operator"], Role.OPERATOR_ENGINEER)
    Membership.objects.create(user=w["op_eng2"], tenant=w["a"], role=Role.OPERATOR_ENGINEER)
    w["op_mgr"] = make_user("op.mgr@example.test", w["operator"], Role.OPERATOR_MANAGER)
    eng = login(w["op_eng"], w["a"])
    part = eng.post("/api/v1/parts/", {"part_number": "AP-1", "name": "Bracket"}, format="json").json()
    passport = eng.post("/api/v1/passports/", {"part": part["id"]}, format="json").json()
    return {"w": w, "eng": eng, "p": passport, "url": f"/api/v1/passports/{passport['id']}"}


def test_submit_locks_the_draft_and_notifies_approvers(ap):
    w, eng, url = ap["w"], ap["eng"], ap["url"]
    r = eng.post(f"{url}/revisions/1/submit/", {}, format="json")
    assert r.status_code == 200, r.content
    assert r.json()["status"] == "submitted" and r.json()["submitted_by_email"] == "op.eng@example.test"
    assert eng.get(f"{url}/").json()["publication_state"] == "submitted"
    assert eng.patch(f"{url}/revisions/1/", {"change_summary": "x"}, format="json").json()["error"]["code"] == "revision_not_editable"
    assert eng.post(f"{url}/revisions/", {}, format="json").json()["error"]["code"] == "revision_awaiting_approval"
    assert eng.post(f"{url}/revisions/1/submit/", {}, format="json").json()["error"]["code"] == "revision_not_draft"
    for user in ("op_admin", "op_mgr", "op_eng2"):
        assert any("waiting for approval" in t for t in unread(w[user])), user
    assert not any("waiting for approval" in t for t in unread(w["op_eng"]))  # not the submitter


def test_project_engineer_approves_but_never_the_submitter_or_a_client(ap):
    w, eng, url = ap["w"], ap["eng"], ap["url"]
    eng.post(f"{url}/revisions/1/submit/", {}, format="json")
    r = eng.post(f"{url}/revisions/1/approve/", {}, format="json")
    assert r.status_code == 403 and r.json()["error"]["code"] == "separation_of_duties"
    assert login(w["a_admin"]).post(f"{url}/revisions/1/approve/", {}, format="json").status_code == 403
    ok = login(w["op_eng2"], w["a"]).post(f"{url}/revisions/1/approve/", {}, format="json")
    assert ok.status_code == 200, ok.content
    assert ok.json()["status"] == "approved" and ok.json()["approved_by_email"] == "op.eng2@example.test"
    p = eng.get(f"{url}/").json()
    assert (p["publication_state"], p["manufacturing_eligibility"]) == ("engineering_approved", "not_eligible")
    assert any("Passport approved" in t for t in unread(w["op_eng"]))
    # approved revisions stay immutable; a new revision supersedes it once approved
    assert eng.patch(f"{url}/revisions/1/", {"change_summary": "x"}, format="json").status_code == 409
    assert eng.post(f"{url}/revisions/", {"change_summary": "rev 2"}, format="json").status_code == 201
    assert eng.get(f"{url}/").json()["publication_state"] == "revision_in_progress"
    eng.post(f"{url}/revisions/2/submit/", {}, format="json")
    login(w["op_eng2"], w["a"]).post(f"{url}/revisions/2/approve/", {}, format="json")
    statuses = {r["revision_number"]: r["status"] for r in eng.get(f"{url}/revisions/").json()}
    assert statuses == {1: "superseded", 2: "approved"}


def test_send_back_needs_a_note_and_returns_to_draft(ap):
    w, eng, url = ap["w"], ap["eng"], ap["url"]
    eng.post(f"{url}/revisions/1/submit/", {}, format="json")
    eng2 = login(w["op_eng2"], w["a"])
    assert eng2.post(f"{url}/revisions/1/return/", {}, format="json").json()["error"]["code"] == "note_required"
    r = eng2.post(f"{url}/revisions/1/return/", {"note": "Add the material certificate."}, format="json")
    assert r.json()["status"] == "draft" and r.json()["review_note"] == "Add the material certificate."
    assert eng.get(f"{url}/").json()["publication_state"] == "draft"
    assert any("sent back" in t for t in unread(w["op_eng"]))
    assert eng.patch(f"{url}/revisions/1/", {"change_summary": "fixed"}, format="json").status_code == 200
    assert eng.post(f"{url}/revisions/1/submit/", {}, format="json").json()["review_note"] == ""


@pytest.mark.parametrize("who", ["op_admin", "op_mgr"])
def test_admin_and_manager_approve_from_the_aries_queue(ap, who):
    w, eng, p = ap["w"], ap["eng"], ap["p"]
    eng.post(f"{ap['url']}/revisions/1/submit/", {}, format="json")
    c = login(w[who])
    rows = c.get("/api/v1/operator/passport-approvals/").json()
    assert [(r["passport_number"], r["client_name"], r["revision_number"]) for r in rows] == [(p["passport_number"], "Client A Energy", 1)]
    detail_url = f"/api/v1/operator/passport-approvals/{w['a'].pk}/{p['id']}/"
    detail = c.get(detail_url).json()
    assert detail["revision"]["status"] == "submitted" and detail["submitted_by_email"] == "op.eng@example.test"
    assert detail["evidence_files"] == {}  # R-L3 evidence references are resolved to document names (none attached here)
    assert c.post(detail_url, {"decision": "return"}, format="json").json()["error"]["code"] == "note_required"
    r = c.post(detail_url, {"decision": "approve"}, format="json")
    assert r.status_code == 200 and r.json() == {"status": "approved", "passport_state": "engineering_approved"}
    assert c.get("/api/v1/operator/passport-approvals/").json() == []
    assert c.get(detail_url).status_code == 404  # nothing waiting any more


def test_approval_queue_is_for_admin_and_manager_only(ap):
    w = ap["w"]
    ap["eng"].post(f"{ap['url']}/revisions/1/submit/", {}, format="json")
    assert login(w["op_eng"], w["operator"]).get("/api/v1/operator/passport-approvals/").status_code == 403
    assert login(w["a_admin"]).get("/api/v1/operator/passport-approvals/").status_code == 403
    caps = set(login(w["op_mgr"]).get("/api/v1/auth/me/").json()["capabilities"])
    assert "passports.approve" in caps and "audit.view" not in caps


def test_client_message_marks_the_request_as_waiting_for_an_aries_reply(world, catalog):  # noqa: F811
    client = login(world["a_admin"])
    ref = manufacturing(client, catalog["part"]["id"]).json()
    env = envelope_for(world, ref["reference"])
    assert env.awaiting_reply and env.last_client_activity == "submitted"
    op = login(world["op_admin"])
    rows = op.get("/api/v1/operator/requests/", {"awaiting": "true"}).json()
    assert [r["reference"] for r in rows] == [ref["reference"]]
    act = lambda action, message="": op.post(f"/api/v1/operator/requests/{env.pk}/act/", {"action": action, "message": message}, format="json")
    assert act("acknowledge").json()["status"] == "acknowledged"
    assert not envelope_for(world, ref["reference"]).awaiting_reply
    client.post(f"/api/v1/requests/{ref['id']}/reply/", {"message": "Any update on the delivery date?"}, format="json")
    env = envelope_for(world, ref["reference"])
    assert env.awaiting_reply and env.last_client_activity == "client_message"
    assert any(ref["reference"] in t for t in unread(world["op_admin"]))
    assert act("respond", "Next week.").json()["status"] == "answered"
    assert not envelope_for(world, ref["reference"]).awaiting_reply


def test_manager_user_list_does_not_show_aries_admins(ap):
    w = ap["w"]
    emails = {r["email"] for r in login(w["op_mgr"]).get("/api/v1/users/").json()["results"]}
    assert "op.admin@example.test" not in emails and "op.eng@example.test" in emails
    admin_mid = str(Membership.objects.get(user=w["op_admin"], tenant=w["operator"]).pk)
    assert login(w["op_mgr"]).get(f"/api/v1/users/{admin_mid}/").status_code == 404
    assert "op.mgr@example.test" in {r["email"] for r in login(w["op_admin"]).get("/api/v1/users/").json()["results"]}


def test_aries_sends_a_message_without_changing_the_status(world, catalog):  # noqa: F811
    client = login(world["a_admin"])
    ref = manufacturing(client, catalog["part"]["id"]).json()
    env = envelope_for(world, ref["reference"])
    op = login(world["op_admin"])
    act = lambda action, message="": op.post(f"/api/v1/operator/requests/{env.pk}/act/", {"action": action, "message": message}, format="json")
    assert act("message", "Too early").json()["error"]["code"] == "transition_not_allowed"  # acknowledge first
    act("acknowledge")
    act("request_information", "Which certificate?")
    client.post(f"/api/v1/requests/{ref['id']}/reply/", {"message": "And can you deliver by Friday?"}, format="json")
    assert act("message").json()["error"]["code"] == "message_required"
    r = act("message", "We are checking the certificate and the date.").json()
    assert r["status"] == "information_provided" and r["events"][-1]["event"] == "operator_message"
    assert not envelope_for(world, ref["reference"]).awaiting_reply
    assert any("new message from Aries" in t for t in unread(world["a_admin"]))
