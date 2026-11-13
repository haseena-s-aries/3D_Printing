"""Decision of 13 Nov 2026: Aries-prepared passports need no approval (marked complete); client submissions (new parts and
clones) are approved by an Aries Admin / Manager (Aries approval queue) or an Aries Engineer. Also: the legacy passport
approval queue for revisions submitted before that decision, client messages waiting for an Aries reply, and the Aries
Manager's user list."""
import pytest

from apps.tenancy.context import tenant_context
from apps.tenancy.models import Membership, Role

from .conftest import login, make_user
from .test_service_requests import catalog, envelope_for, manufacturing, unread  # noqa: F401


RL1_FULL = {"cad_3d_available": True, "drawings_2d_available": True, "original_material_grade": "316", "material_identification_method": "pmi",
            "technical_description": "x", "part_size": "Ø45", "application": "pump", "atmosphere": "corrosive", "motion": "static", "ip_status": "active"}


def fill(eng, url, rev=1):
    from .test_w1_passport_workspace import RL2_FULL

    r = eng.patch(f"{url}/revisions/{rev}/", {"content": {"rl1": RL1_FULL, "rl2": RL2_FULL}}, format="json")
    assert r.status_code == 200, r.content


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




# ------------------------------------------------------------------ decision of 13 Nov 2026

def test_aries_prepared_passport_needs_no_approval_and_is_marked_complete(ap):
    eng, url = ap["eng"], ap["url"]
    r = eng.post(f"{url}/revisions/1/submit/", {}, format="json")
    assert r.status_code == 409 and r.json()["error"]["code"] == "approval_not_needed"
    assert login(ap["w"]["a_admin"]).post(f"{url}/revisions/1/complete/", {}, format="json").status_code == 403  # Aries only
    # R-L1 and R-L2 must be filled in first; the answer lists what is missing (R-L3 evidence is not required)
    r = eng.post(f"{url}/revisions/1/complete/", {}, format="json")
    assert r.status_code == 409 and r.json()["error"]["code"] == "passport_incomplete"
    missing = r.json()["error"]["details"]["missing"]
    assert "part_size" in missing["rl1"] and "manufacturing_spec.machine" in missing["rl2"] and "rl3" not in missing
    eng.patch(f"{url}/revisions/1/", {"content": {"rl1": RL1_FULL}}, format="json")
    assert set(eng.post(f"{url}/revisions/1/complete/", {}, format="json").json()["error"]["details"]["missing"]) == {"rl2"}
    fill(eng, url)
    r = eng.post(f"{url}/revisions/1/complete/", {}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "approved" and r.json()["approved_by_email"] == "op.eng@example.test"
    assert eng.get(f"{url}/").json()["publication_state"] == "complete"
    assert eng.post(f"{url}/revisions/1/complete/", {}, format="json").json()["error"]["code"] == "revision_not_open"
    # a new revision is a draft until it is completed in turn; the earlier one is superseded
    assert eng.post(f"{url}/revisions/", {"change_summary": "rev 2"}, format="json").status_code == 201
    assert eng.get(f"{url}/").json()["publication_state"] == "revision_in_progress"
    eng.post(f"{url}/revisions/2/complete/", {}, format="json")
    assert {r["revision_number"]: r["status"] for r in eng.get(f"{url}/revisions/").json()} == {1: "superseded", 2: "approved"}


@pytest.fixture
def subs(ap, settings):
    from .test_client_part_submissions import SUBMISSION

    settings.CLIENT_PART_SUBMISSIONS_ENABLED = True
    w = ap["w"]
    Membership.objects.filter(user=w["a_user"], tenant=w["a"]).update(part_submission_allowed=True)
    body = {**SUBMISSION, "part_number": "SH-77", "unknown_fields": [], "original_material": "CF8M"}
    full = login(w["a_user"]).post("/api/v1/parts/", body, format="json").json()
    partial = login(w["a_user"]).post("/api/v1/parts/", {**SUBMISSION, "aries_completion_requested": True}, format="json").json()
    return {**ap, "full": full, "partial": partial}


def test_client_submission_waits_in_the_aries_queue_and_admins_are_notified(subs):
    from .test_client_part_submissions import titles

    w = subs["w"]
    assert subs["full"]["submission_revision"] == 1 and subs["partial"]["aries_completion_requested"] is True
    assert any("SH-77" in t and "waiting for approval" in t for t in titles(w["op_mgr"]))
    assert any("complete the details" in t for t in titles(w["op_admin"]))
    rows = {r["part_id"]: r for r in login(w["op_mgr"]).get("/api/v1/operator/approvals/").json()}
    assert rows[subs["full"]["id"]]["revision"] == 1 and rows[subs["full"]["id"]]["client_name"] == "Client A Energy"
    assert rows[subs["partial"]["id"]]["aries_completion_requested"] is True
    assert login(w["op_eng"], w["operator"]).get("/api/v1/operator/approvals/").status_code == 403  # engineers use the part page
    assert login(w["a_admin"]).get("/api/v1/operator/approvals/").status_code == 403


def test_send_back_opens_the_next_revision_and_only_the_submitter_resubmits(subs):
    w, part = subs["w"], subs["full"]
    base = f"/api/v1/operator/approvals/{w['a'].pk}/{part['id']}/"
    mgr = login(w["op_mgr"])
    assert mgr.post(base, {"decision": "send_back"}, format="json").json()["error"]["code"] == "message_required"
    r = mgr.post(base, {"decision": "send_back", "message": "Add the nameplate photo."}, format="json").json()
    assert r == {"review_state": "info_requested", "revision": 2, "passport_number": ""}
    assert login(w["a_admin"]).post(f"/api/v1/parts/{part['id']}/resubmit/", {}, format="json").json()["error"]["code"] == "not_your_submission"
    assert login(w["a_user"]).post(f"/api/v1/parts/{part['id']}/resubmit/", {}, format="json").json()["review_state"] == "pending_review"
    detail = mgr.get(base).json()
    assert detail["revision"] == 2 and [h["action"] for h in detail["history"]] == ["submitted", "info_requested", "resubmitted"]
    assert detail["fields"]["original_material"] == "CF8M"


@pytest.mark.parametrize("who", ["op_admin", "op_mgr"])
def test_admin_or_manager_approval_creates_the_passport_draft(subs, who):
    w, part = subs["w"], subs["full"]
    r = login(w[who]).post(f"/api/v1/operator/approvals/{w['a'].pk}/{part['id']}/", {"decision": "approve"}, format="json")
    assert r.status_code == 200 and r.json()["review_state"] == "accepted" and r.json()["passport_number"].startswith("DP-")
    p = login(w["op_eng"], w["a"]).get(f"/api/v1/parts/{part['id']}/").json()
    assert p["review_state"] == "accepted" and p["passport_id"] and p["publication_state"] == "draft"
    assert login(w[who]).get(f"/api/v1/operator/approvals/{w['a'].pk}/{part['id']}/").status_code == 404  # no longer waiting


def test_engineer_completes_the_missing_details_and_approves_on_the_part_page(subs):
    w, part = subs["w"], subs["partial"]
    eng = login(w["op_eng"], w["a"])
    assert eng.patch(f"/api/v1/parts/{part['id']}/", {"part_number": "SH-78", "original_material": "CF8M", "unknown_fields": []},
                     format="json").status_code == 200
    r = eng.post(f"/api/v1/parts/{part['id']}/review/", {"decision": "accept"}, format="json").json()
    assert r["review_state"] == "accepted" and r["passport_id"] and r["part_number"] == "SH-78"


def test_approver_opens_the_submitted_documents(subs):
    from .test_files import PDF_BYTES, upload

    w, part = subs["w"], subs["full"]
    f = upload(login(w["a_user"]), part["id"], "photo.pdf", PDF_BYTES, category="photo").json()
    base = f"/api/v1/operator/approvals/{w['a'].pk}/{part['id']}/"
    mgr = login(w["op_mgr"])
    assert [x["id"] for x in mgr.get(base).json()["files"]] == [f["id"]]
    r = mgr.get(f"{base}files/{f['id']}/", {"variant": "preview"})
    assert r.status_code == 200 and b"".join(r.streaming_content).startswith(b"%PDF")


# ------------------------------------------------------------------ legacy: passports submitted before 13 Nov 2026

def _legacy_submitted(ap):
    from django.utils import timezone

    from apps.passports.models import PassportRevision

    with tenant_context(ap["w"]["a"]):
        PassportRevision.objects.filter(passport_id=ap["p"]["id"], revision_number=1).update(
            status="submitted", submitted_by=ap["w"]["op_eng"], submitted_at=timezone.now())


def test_legacy_submitted_passport_is_still_decided_or_completed(ap):
    from .test_files import PDF_BYTES, upload

    w, p = ap["w"], ap["p"]
    _legacy_submitted(ap)
    part_id = ap["eng"].get(f"{ap['url']}/").json()["part"]
    f = upload(ap["eng"], part_id, "mtc.pdf", PDF_BYTES, passport=p["id"], category="certificate").json()
    mgr = login(w["op_mgr"])
    base = f"/api/v1/operator/passport-approvals/{w['a'].pk}/{p['id']}/"
    assert [r["passport_number"] for r in mgr.get("/api/v1/operator/passport-approvals/").json()] == [p["passport_number"]]
    detail = mgr.get(base).json()
    assert [x["id"] for x in detail["files"]] == [f["id"]] and detail["reports"] == []
    assert mgr.get(f"{base}reports/00000000-0000-0000-0000-000000000000/").status_code == 404
    assert mgr.get(f"{base}files/{f['id']}/", {"variant": "preview"}).status_code == 200
    # the submitting engineer can now simply mark it complete (once R-L1 and R-L2 are filled in)
    with tenant_context(w["a"]):
        from apps.passports.models import PassportRevision
        from .test_w1_passport_workspace import RL2_FULL
        PassportRevision.objects.filter(passport_id=p["id"], revision_number=1).update(content={"rl1": RL1_FULL, "rl2": RL2_FULL})
    r = ap["eng"].post(f"{ap['url']}/revisions/1/complete/", {}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert mgr.get("/api/v1/operator/passport-approvals/").json() == []


# ------------------------------------------------------------------ register for Admin / Manager, publish (13 Nov 2026)

def _completed(ap):
    fill(ap["eng"], ap["url"])
    assert ap["eng"].post(f"{ap['url']}/revisions/1/complete/", {}, format="json").status_code == 200


@pytest.mark.parametrize("who", ["op_admin", "op_mgr"])
def test_admin_and_manager_view_any_companys_passport_read_only(ap, who):
    from .test_files import PDF_BYTES, upload

    w, p = ap["w"], ap["p"]
    part_id = ap["eng"].get(f"{ap['url']}/").json()["part"]
    f = upload(ap["eng"], part_id, "mtc.pdf", PDF_BYTES, passport=p["id"], category="certificate").json()
    _completed(ap)
    c = login(w[who])
    rows = c.get("/api/v1/operator/passports/").json()
    row = next(r for r in rows if r["passport_id"] == p["id"])
    assert row["client_name"] == "Client A Energy" and row["passport_state"] == "complete" and row["revision_number"] == 1
    assert c.get("/api/v1/operator/passports/", {"state": "published"}).json() == []
    base = f"/api/v1/operator/passports/{w['a'].pk}/{p['id']}/"
    d = c.get(base).json()
    assert d["revision"]["content"]["rl1"]["part_size"] and [x["id"] for x in d["files"]] == [f["id"]]
    assert d["revisions"][0]["status"] == "approved" and d["revisions"][0]["completed_by_email"] == "op.eng@example.test"
    assert c.get(f"{base}files/{f['id']}/", {"variant": "preview"}).status_code == 200
    with tenant_context(w["a"]):
        from apps.audit.models import AuditEvent
        assert AuditEvent.objects.filter(action="passport.viewed_by_aries").exists()


def test_register_is_for_admin_and_manager_only(ap):
    w = ap["w"]
    assert login(w["op_eng"], w["operator"]).get("/api/v1/operator/passports/").status_code == 403
    assert login(w["a_admin"]).get("/api/v1/operator/passports/").status_code == 403


def test_publish_and_unpublish_by_admin_manager_or_engineer(ap):
    from .test_client_part_submissions import titles

    w, p, eng, url = ap["w"], ap["p"], ap["eng"], ap["url"]
    base = f"/api/v1/operator/passports/{w['a'].pk}/{p['id']}/"
    mgr = login(w["op_mgr"])
    assert mgr.post(base, {"action": "publish"}, format="json").json()["error"]["code"] == "not_complete"  # draft
    _completed(ap)
    assert mgr.post(base, {"action": "publish"}, format="json").json() == {"passport_state": "published"}
    assert any("Passport published" in t for t in titles(w["a_admin"]))
    assert login(w["a_admin"]).get("/api/v1/parts/?catalog=published").json()["count"] == 1  # now in the client's catalog
    # a new revision does not take it out of the catalog; completing it keeps it published
    eng.post(f"{url}/revisions/", {"change_summary": "rev 2"}, format="json")
    assert eng.get(f"{url}/").json()["publication_state"] == "published"
    eng.post(f"{url}/revisions/2/complete/", {}, format="json")
    assert eng.get(f"{url}/").json()["publication_state"] == "published"
    # engineers publish / unpublish inside the company; clients cannot
    assert login(w["a_admin"]).post(f"{url}/unpublish/", {}, format="json").status_code == 403
    r = eng.post(f"{url}/unpublish/", {"reason": "Material certificate expired."}, format="json")
    assert r.status_code == 200 and r.json()["publication_state"] == "complete"
    assert eng.post(f"{url}/publish/", {}, format="json").json()["publication_state"] == "published"
    assert login(w["op_admin"]).post(base, {"action": "unpublish"}, format="json").json() == {"passport_state": "complete"}
