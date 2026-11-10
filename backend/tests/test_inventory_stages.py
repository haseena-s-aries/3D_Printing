"""Inventory stages (review / in digitisation / published) derived from separate stored dimensions, and the Aries Admin
administrative overview across companies (read-only, audited, no confidential access). PostgreSQL with RLS."""
import pytest

from apps.audit.models import AuditEvent
from apps.parts.models import SparePart
from apps.passports.models import DigitalPassport
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Membership

from .conftest import login


@pytest.fixture
def stock(settings, world):
    settings.CLIENT_PART_SUBMISSIONS_ENABLED = True
    w = world
    eng = login(w["op_eng"], w["a"])
    proj = eng.post("/api/v1/projects/", {"code": "P1", "name": "Pumps"}, format="json").json()
    made = {}
    for n in ("ARIES-1", "ARIES-2", "PUB-1"):
        made[n] = eng.post("/api/v1/parts/", {"part_number": n, "name": n, "project": proj["id"]}, format="json").json()
    pub_pp = eng.post("/api/v1/passports/", {"part": made["PUB-1"]["id"]}, format="json").json()
    with tenant_context(w["a"]):  # stored state set directly: there is no publication API (OQ-35)
        DigitalPassport.objects.filter(pk=pub_pp["id"]).update(publication_state="published")
    sub = {"name": "x", "equipment_reference": "e", "manufacturer": "m", "application": "a", "description": "d"}
    made["SUB-1"] = login(w["a_admin"]).post("/api/v1/parts/", {**sub, "part_number": "SUB-1", "project": proj["id"]}, format="json").json()
    made["SUB-2"] = login(w["a_admin"]).post("/api/v1/parts/", {**sub, "part_number": "SUB-2", "project": proj["id"]}, format="json").json()
    made["SUB-3"] = login(w["a_admin"]).post("/api/v1/parts/", {**sub, "part_number": "SUB-3", "project": proj["id"]}, format="json").json()
    eng.post(f"/api/v1/parts/{made['SUB-2']['id']}/review/", {"decision": "accept"}, format="json")
    eng.post(f"/api/v1/parts/{made['SUB-3']['id']}/review/", {"decision": "decline", "message": "dup"}, format="json")
    # company B
    Membership.objects.create(user=w["op_eng"], tenant=w["b"], role="operator_engineer")
    login(w["op_eng"], w["b"]).post("/api/v1/parts/", {"part_number": "B-ONLY", "name": "b"}, format="json")
    return {"project": proj, **made}


def numbers(c, **q):
    qs = "&".join(f"{k}={v}" for k, v in q.items())
    return sorted(x["part_number"] for x in c.get(f"/api/v1/parts/?page_size=100&{qs}").json()["results"])


def test_stages_are_derived_and_separate(world, stock):
    c = login(world["a_admin"])
    assert numbers(c, catalog="review") == ["SUB-1"]
    assert numbers(c, catalog="in_digitisation") == ["ARIES-1", "ARIES-2", "SUB-2"]
    assert numbers(c, catalog="published") == ["PUB-1"]
    assert numbers(c, catalog="declined") == ["SUB-3"]
    assert len(numbers(c)) == 6  # All parts: every authorised record, including declined
    counts = c.get("/api/v1/parts/stage-counts/").json()
    assert counts == {"all": 6, "review": 1, "in_digitisation": 3, "published": 1, "declined": 1}
    # counts follow the other filters but ignore the stage itself
    assert c.get("/api/v1/parts/stage-counts/?search=SUB&catalog=published").json()["all"] == 3
    # stored dimensions untouched by listing
    with tenant_context(world["a"]):
        assert SparePart.objects.get(part_number="SUB-2").review_state == "accepted"
        assert DigitalPassport.objects.filter(publication_state="published").count() == 1


def test_counts_respect_tenant_and_project_scope(world, stock):
    assert login(world["b_admin"]).get("/api/v1/parts/stage-counts/").json()["all"] == 1
    eng = login(world["op_eng"], world["a"])
    p2 = eng.post("/api/v1/projects/", {"code": "P2", "name": "x"}, format="json").json()
    mid = Membership.objects.get(user=world["op_eng"], tenant=world["a"]).pk
    login(world["op_admin"]).put(f"/api/v1/clients/{world['a'].pk}/engineers/{mid}/access/", {"scope": "projects", "project_ids": [p2["id"]]}, format="json")
    assert login(world["op_eng"], world["a"]).get("/api/v1/parts/stage-counts/").json()["all"] == 0


def test_admin_overview_across_companies_is_summary_only_and_audited(world, stock):
    admin = login(world["op_admin"])
    r = admin.get("/api/v1/admin/inventory/?page_size=100")
    assert r.status_code == 200, r.content
    body = r.json()
    by = {x["part_number"]: x for x in body["results"]}
    assert {"ARIES-1", "SUB-1", "PUB-1", "B-ONLY"} <= set(by)
    assert by["SUB-1"]["client_name"] == "Client A Energy" and by["SUB-1"]["stage"] == "review"
    assert by["PUB-1"]["stage"] == "published" and by["PUB-1"]["passport_number"].startswith("DP-")
    assert by["ARIES-1"]["assigned_engineers"] and by["ARIES-1"]["project"] == "P1"
    assert body["totals"]["review"] == 1 and body["totals"]["all"] == 7
    assert body["detail_access"]["enabled"] is False and body["detail_access"]["decision"] == "OQ-37"
    # summary fields only: no notes, file names, content or download links
    text = str(body)
    for forbidden in ("notes", "download", "sha256", "content", "original_filename"):
        assert forbidden not in text
    # filters
    a_id = str(world["a"].pk)
    assert {x["client_name"] for x in admin.get(f"/api/v1/admin/inventory/?client={a_id}").json()["results"]} == {"Client A Energy"}
    assert [x["part_number"] for x in admin.get("/api/v1/admin/inventory/?review_state=open").json()["results"]] == ["SUB-1"]
    assert [x["part_number"] for x in admin.get("/api/v1/admin/inventory/?publication=published").json()["results"]] == ["PUB-1"]
    pid = stock["project"]["id"]
    assert all(x["project"] == "P1" for x in admin.get(f"/api/v1/admin/inventory/?project={pid}").json()["results"])
    # audited in the Aries trail and in each company's own trail
    with tenant_context(world["operator"]):
        assert AuditEvent.objects.filter(action="inventory.admin_overview_viewed").exists()
    with tenant_context(world["a"]):
        assert AuditEvent.objects.filter(action="inventory.admin_summary_viewed").exists()


def test_only_aries_admin_gets_the_overview_and_no_extra_rights(world, stock):
    for who, tenant in (("op_eng", world["operator"]), ("a_admin", None), ("b_admin", None), ("op_eng", world["a"])):
        assert login(world[who], tenant).get("/api/v1/admin/inventory/").status_code == 403
    admin = login(world["op_admin"])
    # no engineering edits, no client record, no CAD originals through the normal endpoints
    assert admin.post("/api/v1/parts/", {"part_number": "X", "name": "x"}, format="json").status_code == 403
    assert admin.get(f"/api/v1/parts/{stock['ARIES-1']['id']}/").status_code == 404
    assert admin.post(f"/api/v1/parts/{stock['SUB-1']['id']}/review/", {"decision": "accept"}, format="json").status_code in (403, 404)
    assert "inventory.admin_overview" in admin.session_payload["capabilities"]
    assert "parts.manage" not in admin.session_payload["capabilities"]
    assert "passports.edit_draft" not in admin.session_payload["capabilities"]
