"""Structured part-form values and material change in a manufacturing enquiry (CN-003, BR-033). The original part and
passport never change; a proposed material goes to a separate clone held for Aries review; the request stays an
enquiry; suitability is never assumed. PostgreSQL with RLS."""
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.parts.models import SparePart
from apps.servicerequests.models import ClientRequest
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Membership

from .conftest import login
from .test_registration_access import PDF

BASE = {"request_type": "manufacturing", "quantity": 2, "required_date": "2030-01-01", "delivery_location": "Site A",
        "priority": "routine", "remarks": "Spare for overhaul."}


@pytest.fixture
def on(settings, world):
    settings.CLIENT_PART_SUBMISSIONS_ENABLED = True
    return world


@pytest.fixture
def part(on):
    eng = login(on["op_eng"], on["a"])
    proj = eng.post("/api/v1/projects/", {"code": "P1", "name": "Pumps"}, format="json").json()
    p = eng.post("/api/v1/parts/", {"part_number": "IMP-1", "name": "Impeller", "project": proj["id"], "original_material": "CF8M",
                                     "equipment_reference": "Cooling pump CP-3", "manufacturer": "KSB", "application": "Cooling water pump",
                                     "dimensions": "120.0 x 34.0 mm (Ø x H)"}, format="json").json()
    eng.post("/api/v1/files/", {"part": p["id"], "file": SimpleUploadedFile("d.pdf", PDF), "category": "drawing"}, format="multipart")
    passport = eng.post("/api/v1/passports/", {"part": p["id"]}, format="json").json()
    return {**p, "passport": passport, "project_id": proj["id"]}


def snapshot(on, part):
    eng = login(on["op_eng"], on["a"])
    p = eng.get(f"/api/v1/parts/{part['id']}/").json()
    rev = eng.get(f"/api/v1/passports/{part['passport']['id']}/revisions/1/").json()
    files = eng.get(f"/api/v1/files/?part={part['id']}").json()["results"]
    return ({k: p[k] for k in ("original_material", "updated_at", "dimensions", "review_state")}, rev["content"], rev["updated_at"],
            [(f["id"], f["version_count"]) for f in files])


# ------------------------------------------------------------------ structured part fields

def test_field_values_are_company_and_project_scoped(on, part):
    login(on["op_eng"], on["a"])  # values exist in company A only
    a = login(on["a_admin"]).get("/api/v1/parts/field-values/").json()
    assert a["equipment_reference"] == ["Cooling pump CP-3"] and a["manufacturer"] == ["KSB"] and a["original_material"] == ["CF8M"]
    b = login(on["b_admin"]).get("/api/v1/parts/field-values/").json()
    assert b == {"equipment_reference": [], "manufacturer": [], "application": [], "original_material": []}
    # project-limited engineer without the part's project sees no values from it
    eng = login(on["op_eng"], on["a"])
    p2 = eng.post("/api/v1/projects/", {"code": "P2", "name": "x"}, format="json").json()
    mid = Membership.objects.get(user=on["op_eng"], tenant=on["a"]).pk
    login(on["op_admin"]).put(f"/api/v1/clients/{on['a'].pk}/engineers/{mid}/access/", {"scope": "projects", "project_ids": [p2["id"]]}, format="json")
    assert login(on["op_eng"], on["a"]).get("/api/v1/parts/field-values/").json()["manufacturer"] == []


def test_custom_dimension_text_and_other_values_are_preserved(on, part):
    eng = login(on["op_eng"], on["a"])
    assert part["dimensions"] == "120.0 x 34.0 mm (Ø x H)"
    r = eng.patch(f"/api/v1/parts/{part['id']}/", {"name": "Impeller (closed)"}, format="json").json()
    assert r["dimensions"] == "120.0 x 34.0 mm (Ø x H)" and r["original_material"] == "CF8M"  # untouched values kept exactly
    r = eng.patch(f"/api/v1/parts/{part['id']}/", {"manufacturer": "Bespoke Works Ltd", "original_material": "Special grade X-9"}, format="json").json()
    assert r["manufacturer"] == "Bespoke Works Ltd" and r["original_material"] == "Special grade X-9"
    assert r["field_provenance"]["manufacturer"]["source"] == "aries"
    # criticality keeps the existing approved choices only
    assert eng.patch(f"/api/v1/parts/{part['id']}/", {"criticality": "very_high"}, format="json").status_code == 400
    opts = eng.get("/api/v1/passport-field-options/").json()
    assert any(o["value"] == "KSB" for o in opts["lists"]["manufacturers"])


# ------------------------------------------------------------------ material change in a manufacturing enquiry

def test_original_material_request_is_unchanged(on, part):
    r = login(on["a_admin"]).post("/api/v1/requests/", {**BASE, "part": part["id"]}, format="json")
    assert r.status_code == 201, r.content
    body = r.json()
    assert body["material_option"] == "original" and body["original_material"] == "CF8M" and body["linked_part"] is None
    assert body["kind"] == "enquiry"


def test_proposed_material_creates_a_linked_clone_and_stays_an_enquiry(on, part):
    before = snapshot(on, part)
    r = login(on["a_admin"]).post("/api/v1/requests/", {**BASE, "part": part["id"], "material_option": "proposed",
                                                       "proposed_material": "Duplex 2205", "new_part_number": "IMP-1-DX",
                                                       "material_change_reason": "Better chloride resistance."}, format="json")
    assert r.status_code == 201, r.content
    body = r.json()
    assert body["kind"] == "enquiry"
    assert body["original_material"] == "CF8M" and body["proposed_material"] == "Duplex 2205"
    assert body["linked_part_number"] == "IMP-1-DX" and body["part"] == part["id"]
    assert "Material change proposed: CF8M → Duplex 2205" in body["events"][0]["message"]
    clone = login(on["a_admin"]).get(f"/api/v1/parts/{body['linked_part']}/").json()
    assert clone["source_part"] == part["id"] and clone["review_state"] == "pending_review" and clone["proposed_material"] == "Duplex 2205"
    assert clone["passport_id"] is None and clone["manufacturing_eligibility"] is None
    assert snapshot(on, part) == before  # original part, its passport and files unchanged
    # Aries sees the material change on the request
    with tenant_context(on["a"]):
        req = ClientRequest.objects.get(pk=body["id"])
        assert req.linked_part.part_number == "IMP-1-DX" and req.material_change_reason == "Better chloride resistance."


def test_material_change_validation(on, part):
    c = login(on["a_admin"])
    r = c.post("/api/v1/requests/", {**BASE, "part": part["id"], "material_option": "proposed", "proposed_material": "Duplex 2205"}, format="json")
    assert r.status_code == 400 and "material_change_reason" in r.json()["error"]["details"]
    r = c.post("/api/v1/requests/", {**BASE, "part": part["id"], "material_option": "proposed", "proposed_material": "cf8m",
                                     "material_change_reason": "x"}, format="json")
    assert r.status_code == 400 and r.json()["error"]["code"] == "same_material"
    r = c.post("/api/v1/requests/", {**BASE, "part": part["id"], "material_option": "proposed", "proposed_material": "Duplex 2205",
                                     "material_change_reason": "x", "new_part_number": "IMP-1"}, format="json")
    assert r.status_code == 400 and r.json()["error"]["code"] == "duplicate_part_number"
    with tenant_context(on["a"]):
        assert ClientRequest.objects.count() == 0  # atomic: no request without its clone
        assert SparePart.objects.count() == 1


def test_link_existing_clone_and_cross_company_denied(on, part):
    clone = login(on["a_admin"]).post(f"/api/v1/parts/{part['id']}/clone/", {"part_number": "IMP-1-AL", "proposed_material": "AlSi10Mg",
                                                                          "material_change_reason": "Weight"}, format="json").json()
    other = login(on["a_admin"]).post("/api/v1/parts/", {"part_number": "UNRELATED", "name": "x", "equipment_reference": "e",
                                                         "manufacturer": "m", "application": "a", "description": "d"}, format="json").json()
    c = login(on["a_admin"])
    bad = c.post("/api/v1/requests/", {**BASE, "part": part["id"], "material_option": "proposed", "proposed_material": "AlSi10Mg",
                                       "material_change_reason": "Weight", "linked_part": other["id"]}, format="json")
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_linked_part"
    ok = c.post("/api/v1/requests/", {**BASE, "part": part["id"], "material_option": "proposed", "proposed_material": "AlSi10Mg",
                                      "material_change_reason": "Weight", "linked_part": clone["id"]}, format="json")
    assert ok.status_code == 201 and ok.json()["linked_part_number"] == "IMP-1-AL"
    # company B cannot request against company A's part
    r = login(on["b_admin"]).post("/api/v1/requests/", {**BASE, "part": part["id"], "material_option": "proposed",
                                                       "proposed_material": "AlSi10Mg", "material_change_reason": "x",
                                                       "new_part_number": "STEAL-1"}, format="json")
    assert r.status_code == 404


def test_requesters_without_part_permission_record_the_proposal_only(on, part):
    proc = login(on["a_proc"])  # procurement may send enquiries but not create parts
    r = proc.post("/api/v1/requests/", {**BASE, "part": part["id"], "material_option": "proposed", "proposed_material": "Duplex 2205",
                                        "material_change_reason": "Supplier advice", "new_part_number": "IMP-1-P"}, format="json")
    assert r.status_code == 403
    r = proc.post("/api/v1/requests/", {**BASE, "part": part["id"], "material_option": "proposed", "proposed_material": "Duplex 2205",
                                        "material_change_reason": "Supplier advice"}, format="json")
    assert r.status_code == 201 and r.json()["linked_part"] is None and r.json()["proposed_material"] == "Duplex 2205"
    assert "No cloned part linked yet" in r.json()["events"][0]["message"]


def test_material_change_never_creates_a_manufacturing_request(on, part):
    """Even if a part were published and eligible, a material change is an enquiry (gates stay closed, OQ-36)."""
    from apps.passports.models import DigitalPassport

    with tenant_context(on["a"]):
        DigitalPassport.objects.filter(part_id=part["id"]).update(publication_state="published", manufacturing_eligibility="eligible")
    c = login(on["a_admin"])
    assert c.post("/api/v1/requests/", {**BASE, "part": part["id"]}, format="json").json()["kind"] == "manufacturing_request"
    r = c.post("/api/v1/requests/", {**BASE, "part": part["id"], "material_option": "proposed", "proposed_material": "Duplex 2205",
                                     "material_change_reason": "x", "new_part_number": "IMP-1-D2"}, format="json").json()
    assert r["kind"] == "enquiry"
    clone = c.get(f"/api/v1/parts/{r['linked_part']}/").json()
    assert clone["manufacturing_eligibility"] is None and clone["publication_state"] is None
