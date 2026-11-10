"""D-13: engineering notes (revision content.notes) are readable only with passports.view_engineering_notes.

Other roles never receive the note text from any passport/revision response and only see
`engineering_review_pending`. Notes are stored and returned exactly as written; approved revisions stay immutable.
"""
import pytest
from django.db import DatabaseError, transaction

from apps.passports.models import PassportRevision
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Membership, Role
from apps.tenancy.permissions import CAPABILITIES

from .conftest import login, make_user

TOKEN = "C-01-SECRET-MATERIAL-TOKEN"
NOTES = (f"ENGINEERING VALIDATION DRAFT - not an approval.\n"
         f"C-01: Material conflict: Grade A vs Grade B ({TOKEN}).\n"
         "C-06: Dimensional discrepancy: STEP 50.0 mm vs drawing 48 mm.\n"
         "  indented line kept   \n"
         "<script>alert('x')</script> & <b>not html</b>")


@pytest.fixture
def notes_world(world):
    a = world["a"]
    world["a_auditor"] = make_user("a.auditor@example.test", a, Role.AUDITOR)
    world["op_qa"] = make_user("op.qa@example.test", world["operator"], Role.OPERATOR_QA)
    Membership.objects.create(user=world["op_qa"], tenant=a, role=Role.OPERATOR_QA)
    world["op_support"] = make_user("op.support@example.test", world["operator"], Role.OPERATOR_SUPPORT)
    Membership.objects.create(user=world["op_support"], tenant=a, role=Role.OPERATOR_SUPPORT)
    eng = login(world["op_eng"], a)
    part = eng.post("/api/v1/parts/", {"part_number": "TST-0001", "name": "Synthetic part A"}, format="json").json()
    r = eng.post("/api/v1/passports/", {"part": part["id"], "initial_content": {"rl1": {"cad_3d_available": True}, "notes": NOTES}},
                 format="json")
    assert r.status_code == 201, r.content
    world["passport"] = r.json()["id"]
    plain = eng.post("/api/v1/parts/", {"part_number": "TST-0002", "name": "Synthetic part B"}, format="json").json()
    world["plain_passport"] = eng.post("/api/v1/passports/", {"part": plain["id"]}, format="json").json()["id"]
    return world


def responses(client, pid):
    """Every passport/revision read that carries revision content."""
    return {
        "detail": client.get(f"/api/v1/passports/{pid}/"),
        "list": client.get("/api/v1/passports/"),
        "revisions": client.get(f"/api/v1/passports/{pid}/revisions/"),
        "revision": client.get(f"/api/v1/passports/{pid}/revisions/1/"),
    }


def revision_payloads(rs, pid):
    detail = rs["detail"].json()["current_revision"]
    listed = next(p for p in rs["list"].json()["results"] if p["id"] == pid)["current_revision"]
    return [detail, listed, rs["revisions"].json()[0], rs["revision"].json()]


AUTHORISED = ["op_eng", "a_admin", "a_eng", "a_auditor", "op_qa"]
RESTRICTED = ["a_user", "a_proc", "op_support"]


@pytest.mark.parametrize("who", AUTHORISED)
def test_authorised_roles_read_notes_exactly_as_stored(notes_world, who):
    w = notes_world
    rs = responses(login(w[who], w["a"]), w["passport"])
    assert all(r.status_code == 200 for r in rs.values()), {k: r.status_code for k, r in rs.items()}
    for rev in revision_payloads(rs, w["passport"]):
        assert rev["content"]["notes"] == NOTES  # verbatim: line breaks, indentation, markup characters
        assert rev["notes_restricted"] is False and rev["engineering_review_pending"] is True


@pytest.mark.parametrize("who", RESTRICTED)
def test_restricted_roles_never_receive_note_text(notes_world, who):
    w = notes_world
    rs = responses(login(w[who], w["a"]), w["passport"])
    assert all(r.status_code == 200 for r in rs.values())
    for r in rs.values():
        assert TOKEN not in r.content.decode()  # not in any response body, in any form
    for rev in revision_payloads(rs, w["passport"]):
        assert "notes" not in rev["content"]
        assert rev["notes_restricted"] is True and rev["engineering_review_pending"] is True
        assert rev["content"]["rl1"]["cad_3d_available"] is True  # the rest of the content is unaffected


@pytest.mark.parametrize("who", ["b_admin", "b_eng"])
def test_other_tenant_sees_neither_passport_nor_notes(notes_world, who):
    w = notes_world
    c = login(w[who], w["b"])
    pid = w["passport"]
    for path in (f"/api/v1/passports/{pid}/", f"/api/v1/passports/{pid}/revisions/", f"/api/v1/passports/{pid}/revisions/1/"):
        r = c.get(path)
        assert r.status_code == 404 and TOKEN not in r.content.decode()
    listed = c.get("/api/v1/passports/")
    assert TOKEN not in listed.content.decode() and all(p["id"] != pid for p in listed.json()["results"])


def test_no_notes_means_no_pending_review(notes_world):
    w = notes_world
    for who in ("a_user", "a_eng"):
        rev = login(w[who], w["a"]).get(f"/api/v1/passports/{w['plain_passport']}/revisions/1/").json()
        assert rev["engineering_review_pending"] is False and rev["notes_restricted"] is False


def test_unauthenticated_gets_nothing(notes_world):
    from rest_framework.test import APIClient

    r = APIClient().get(f"/api/v1/passports/{notes_world['passport']}/revisions/1/")
    assert r.status_code == 401 and TOKEN not in r.content.decode()


def test_notes_preserved_through_reads_and_other_edits(notes_world):
    w = notes_world
    for who in AUTHORISED + RESTRICTED:
        responses(login(w[who], w["a"]), w["passport"])
    eng = login(w["op_eng"], w["a"])
    r = eng.patch(f"/api/v1/passports/{w['passport']}/revisions/1/", {"content": {"rl1": {"part_size": "Ø40 x 30 mm"}}}, format="json")
    assert r.status_code == 200 and r.json()["content"]["notes"] == NOTES
    with tenant_context(w["a"]):
        stored = PassportRevision.objects.get(passport_id=w["passport"], revision_number=1).content
    assert stored["notes"] == NOTES and stored["rl1"]["part_size"] == "Ø40 x 30 mm"
    # the history view (all revisions) keeps the notes for authorised roles and hides them for others
    assert eng.get(f"/api/v1/passports/{w['passport']}/revisions/").json()[0]["content"]["notes"] == NOTES
    assert "notes" not in login(w["a_user"], w["a"]).get(f"/api/v1/passports/{w['passport']}/revisions/").json()[0]["content"]


def test_approved_revision_notes_are_immutable(notes_world):
    w = notes_world
    with tenant_context(w["a"]):  # simulate a future approval (approval itself is disabled, OQ-35)
        PassportRevision.objects.filter(passport_id=w["passport"], revision_number=1).update(status="approved")
    eng = login(w["op_eng"], w["a"])
    r = eng.patch(f"/api/v1/passports/{w['passport']}/revisions/1/", {"content": {"notes": "rewritten"}}, format="json")
    assert r.status_code == 409 and r.json()["error"]["code"] == "revision_not_editable"
    with tenant_context(w["a"]):
        with pytest.raises(DatabaseError), transaction.atomic():
            PassportRevision.objects.filter(passport_id=w["passport"], revision_number=1).update(content={"notes": "rewritten"})
        assert PassportRevision.objects.get(passport_id=w["passport"], revision_number=1).content["notes"] == NOTES
    # a new draft starts from the approved content, notes included
    r = eng.post(f"/api/v1/passports/{w['passport']}/revisions/", {"change_summary": "rev 2"}, format="json")
    assert r.status_code == 201 and r.json()["content"]["notes"] == NOTES


def test_every_editing_role_may_read_notes():
    # Editors must be able to see what they would overwrite.
    assert CAPABILITIES["passports.edit_draft"] <= CAPABILITIES["passports.view_engineering_notes"]


def test_notes_write_refused_without_read_capability(notes_world, monkeypatch):
    w = notes_world
    monkeypatch.setitem(CAPABILITIES, "passports.view_engineering_notes", {Role.CLIENT_ADMIN})
    eng = login(w["op_eng"], w["a"])
    r = eng.patch(f"/api/v1/passports/{w['passport']}/revisions/1/", {"content": {"notes": "overwrite"}}, format="json")
    assert r.status_code == 403 and r.json()["error"]["code"] == "permission_denied"
    r = eng.patch(f"/api/v1/passports/{w['passport']}/revisions/1/", {"content": {"rl1": {"motion": "static"}}}, format="json")
    assert r.status_code == 200 and "notes" not in r.json()["content"]
    with tenant_context(w["a"]):
        assert PassportRevision.objects.get(passport_id=w["passport"], revision_number=1).content["notes"] == NOTES


def test_session_capabilities_expose_the_notes_capability(notes_world):
    w = notes_world
    assert "passports.view_engineering_notes" in login(w["a_eng"], w["a"]).session_payload["capabilities"]
    assert "passports.view_engineering_notes" not in login(w["a_user"], w["a"]).session_payload["capabilities"]
