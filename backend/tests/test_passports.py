"""Passport drafts, revisions, immutability through the API, and policy-gated actions."""
from apps.passports.models import PassportRevision
from apps.tenancy.context import tenant_context

from .conftest import login


def setup_part(world, number="HOLDER-013"):
    c = login(world["op_eng"], world["a"])
    part = c.post("/api/v1/parts/", {"part_number": number, "name": "Holder", "dimensions": "Ø102 x 60 mm"}, format="json").json()
    return c, part


def test_create_passport_draft_with_first_revision(world):
    c, part = setup_part(world)
    r = c.post("/api/v1/passports/", {"part": part["id"], "initial_content": {"rl1": {"cad_3d_available": True, "motion": "static"}}}, format="json")
    assert r.status_code == 201, r.content
    p = r.json()
    assert p["passport_number"].startswith("DP-") and p["title"] == "Holder"
    assert p["publication_state"] == "draft" and p["evidence_level"] == "none"
    assert p["manufacturing_eligibility"] == "not_eligible"
    assert p["current_revision"]["revision_number"] == 1 and p["current_revision"]["status"] == "draft"
    assert p["current_revision"]["content"]["rl1"]["motion"] == "static"
    assert all(not v["enabled"] for v in p["policy"].values())
    # part now shows its passport
    assert c.get(f"/api/v1/parts/{part['id']}/").json()["passport_id"] == p["id"]


def test_one_passport_per_part(world):
    c, part = setup_part(world)
    assert c.post("/api/v1/passports/", {"part": part["id"]}, format="json").status_code == 201
    r = c.post("/api/v1/passports/", {"part": part["id"]}, format="json")
    assert r.status_code == 400


def test_state_fields_read_only(world):
    c, part = setup_part(world)
    p = c.post("/api/v1/passports/", {"part": part["id"]}, format="json").json()
    c.patch(f"/api/v1/passports/{p['id']}/", {"publication_state": "published", "evidence_level": "R-L3",
                                              "manufacturing_eligibility": "eligible"}, format="json")
    p2 = c.get(f"/api/v1/passports/{p['id']}/").json()
    assert (p2["publication_state"], p2["evidence_level"], p2["manufacturing_eligibility"]) == ("draft", "none", "not_eligible")


def test_rl1_choices_validated(world):
    c, part = setup_part(world)
    p = c.post("/api/v1/passports/", {"part": part["id"]}, format="json").json()
    r = c.patch(f"/api/v1/passports/{p['id']}/revisions/1/", {"content": {"rl1": {"motion": "flying"}}}, format="json")
    assert r.status_code == 400 and r.json()["error"]["code"] == "validation_error"


def test_edit_draft_then_new_revision_rules(world):
    c, part = setup_part(world)
    p = c.post("/api/v1/passports/", {"part": part["id"]}, format="json").json()
    r = c.patch(f"/api/v1/passports/{p['id']}/revisions/1/", {"content": {"rl1": {"part_size": "Ø102 x 60 mm"}}, "change_summary": "sizes"}, format="json")
    assert r.status_code == 200 and r.json()["content"]["rl1"]["part_size"] == "Ø102 x 60 mm"
    # a second draft is refused while one exists
    assert c.post(f"/api/v1/passports/{p['id']}/revisions/", {}, format="json").json()["error"]["code"] == "draft_exists"


def test_approved_revision_cannot_be_edited_via_api(world):
    c, part = setup_part(world)
    p = c.post("/api/v1/passports/", {"part": part["id"]}, format="json").json()
    with tenant_context(world["a"]):  # simulate a future approval (approval itself is disabled, OQ-35)
        PassportRevision.objects.filter(passport_id=p["id"], revision_number=1).update(status="approved")
    r = c.patch(f"/api/v1/passports/{p['id']}/revisions/1/", {"change_summary": "x"}, format="json")
    assert r.status_code == 409 and r.json()["error"]["code"] == "revision_not_editable"
    r = c.post(f"/api/v1/passports/{p['id']}/revisions/", {"change_summary": "rev 2"}, format="json")
    assert r.status_code == 201 and r.json()["revision_number"] == 2 and r.json()["status"] == "draft"


def test_a_draft_cannot_be_approved_before_it_is_submitted(world):
    """Approval itself is covered in test_passport_approval.py (decision of 12 Nov 2026)."""
    c, part = setup_part(world)
    p = c.post("/api/v1/passports/", {"part": part["id"]}, format="json").json()
    r = c.post(f"/api/v1/passports/{p['id']}/revisions/1/approve/", {}, format="json")
    assert r.status_code == 409 and r.json()["error"]["code"] == "revision_not_submitted"


def test_client_roles_can_view_but_not_create_passports(world):
    c, part = setup_part(world)
    p = c.post("/api/v1/passports/", {"part": part["id"]}, format="json").json()
    a_user = login(world["a_user"])
    assert a_user.get(f"/api/v1/passports/{p['id']}/").status_code == 200
    assert a_user.post("/api/v1/passports/", {"part": part["id"]}, format="json").status_code == 403
    assert a_user.patch(f"/api/v1/passports/{p['id']}/revisions/1/", {"change_summary": "x"}, format="json").status_code == 403
    assert login(world["b_admin"]).get(f"/api/v1/passports/{p['id']}/").status_code == 404
