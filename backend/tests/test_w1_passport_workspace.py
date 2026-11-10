"""Web batch W1 backend: structured R-L2/R-L3 content, completeness, evidence links, revision authorship,
PDF preview rights and the organisation switcher."""
import pytest

from apps.audit.models import AuditEvent
from apps.tenancy.context import tenant_context

from .conftest import login
from .test_files import PDF_BYTES, STEP_BYTES, upload


@pytest.fixture
def ws(world):
    eng = login(world["op_eng"], world["a"])
    part = eng.post("/api/v1/parts/", {"part_number": "W1-001", "name": "Impeller holder"}, format="json").json()
    p = eng.post("/api/v1/passports/", {"part": part["id"]}, format="json").json()
    return eng, part, p


def patch_rev(client, p, body):
    return client.patch(f"/api/v1/passports/{p['id']}/revisions/1/", body, format="json")


RL2_FULL = {
    "manufacturing_solution": "L-PBF printed, stress relieved, machined bore",
    "material_selection": "SS 316L", "material_category": "superior", "criticality_amsl": "AMSL-2",
    "feedstock": "316L powder 15-45 um", "applicable_standards": "ASTM F3184",
    "mechanical_acceptance": [{"property": "tensile", "requirement": ">= 485", "unit": "MPa", "standard": "ISO 6892-1"}],
    "dimensional_tolerances": "ISO 2768-m", "ndt": "Visual + dye penetrant", "inspection_test_plan": "ITP-001",
    "mtc_required": True, "test_coupons": "3 tensile coupons per build",
    "manufacturing_spec": {"job_number": "J-77", "material": "316L", "feedstock": "Powder lot 22", "machine": "EOS M290",
                           "layer_thickness": "40 um", "support_strategy": "Block", "build_orientation": "Axis vertical",
                           "inert_gas": "Argon", "heat_treatment": "SR 650C 2h", "post_processing": "Bead blast",
                           "machining": "Bore H7", "printing_hours": "11.5", "post_processing_hours": 3,
                           "process_parameters": [{"name": "Laser power", "value": "195", "unit": "W"}]},
}


def test_levels_are_saved_independently_and_merged(ws):
    eng, part, p = ws
    assert patch_rev(eng, p, {"content": {"rl1": {"original_material_grade": "AISI 316"}}}).status_code == 200
    r = patch_rev(eng, p, {"content": {"rl2": RL2_FULL}})
    assert r.status_code == 200, r.content
    content = r.json()["content"]
    assert content["rl1"]["original_material_grade"] == "AISI 316"  # not lost by the R-L2 save
    assert content["rl2"]["manufacturing_spec"]["printing_hours"] == 11.5  # numeric (BR-026)
    assert r.json()["completeness"]["rl2"]["complete"] is True


@pytest.mark.parametrize("rl2,field", [
    ({"material_category": "better"}, "material_category"),
    ({"mechanical_acceptance": [{"property": "colour"}]}, "mechanical_acceptance"),
    ({"manufacturing_spec": {"printing_hours": "eleven"}}, "manufacturing_spec"),
    ({"manufacturing_spec": {"post_processing_hours": -1}}, "manufacturing_spec"),
], ids=["category", "acceptance-property", "hours-text", "hours-negative"])
def test_rl2_validation(ws, rl2, field):
    eng, part, p = ws
    r = patch_rev(eng, p, {"content": {"rl2": rl2}})
    assert r.status_code == 400 and r.json()["error"]["code"] == "validation_error"


def test_rl1_completeness_rules(ws):
    eng, part, p = ws
    r = patch_rev(eng, p, {"content": {"rl1": {"motion": "rotating"}}})
    c = r.json()["completeness"]["rl1"]
    assert "rpm" in c["missing"] and c["total"] == 11  # RPM becomes required for rotating parts (BR-006)
    r = patch_rev(eng, p, {"content": {"rl1": {"motion": "rotating", "not_applicable": {"rpm": "Speed set by the pump OEM"}}}})
    assert "rpm" not in r.json()["completeness"]["rl1"]["missing"]
    r = patch_rev(eng, p, {"content": {"rl1": {"not_applicable": {"rpm": "  "}}}})
    assert r.status_code == 400  # a reason is required


def test_rl3_evidence_links_only_to_files_of_this_passport(ws, world):
    eng, part, p = ws
    pdf = upload(eng, part["id"], "itp.pdf", PDF_BYTES, passport=p["id"], category="inspection").json()
    other_part = eng.post("/api/v1/parts/", {"part_number": "W1-002", "name": "Other"}, format="json").json()
    other_p = eng.post("/api/v1/passports/", {"part": other_part["id"]}, format="json").json()
    foreign = upload(eng, other_part["id"], "x.pdf", PDF_BYTES, passport=other_p["id"]).json()

    r = patch_rev(eng, p, {"content": {"rl3": {"evidence": {"itp": pdf["id"]}}}})
    assert r.status_code == 200
    assert r.json()["completeness"]["rl3"] == {"total": 5, "done": 1, "complete": False,
                                               "missing": ["machine_details", "print_orientation", "dimensional_inspection", "material_test_certificate"]}
    r = patch_rev(eng, p, {"content": {"rl3": {"evidence": {"itp": foreign["id"]}}}})
    assert r.status_code == 400 and r.json()["error"]["code"] == "evidence_file_invalid"
    r = patch_rev(eng, p, {"content": {"rl3": {"evidence": {"invoice": pdf["id"]}}}})
    assert r.status_code == 400


def test_revision_shows_who_created_and_changed_it(ws, world):
    eng, part, p = ws
    r = patch_rev(eng, p, {"change_summary": "Sizes"})
    assert r.json()["created_by_email"] == "op.eng@example.test"
    assert r.json()["updated_by_email"] == "op.eng@example.test"


def test_pdf_preview_for_viewers_inline_and_audited(ws, world, client):
    eng, part, p = ws
    pdf = upload(eng, part["id"], "spec.pdf", PDF_BYTES, passport=p["id"]).json()
    step = upload(eng, part["id"], "part.stp", STEP_BYTES, passport=p["id"]).json()
    user = login(world["a_user"])  # client user: no original download right
    assert user.post(f"/api/v1/files/{pdf['id']}/versions/1/download-link/", {"variant": "original"}, format="json").status_code == 403
    link = user.post(f"/api/v1/files/{pdf['id']}/versions/1/download-link/", {"variant": "preview"}, format="json")
    assert link.status_code == 200, link.content
    r = client.get(link.json()["url"].replace("http://testserver", ""))
    assert r.status_code == 200 and r["Content-Type"] == "application/pdf"
    assert r["Content-Disposition"].startswith("inline")
    assert b"".join(r.streaming_content) == PDF_BYTES
    with tenant_context(world["a"]):
        assert AuditEvent.objects.filter(action="file.previewed", actor_email="a.user@example.test").exists()
    # STEP has no PDF preview; procurement has no viewing right; another tenant cannot see the file
    assert user.post(f"/api/v1/files/{step['id']}/versions/1/download-link/", {"variant": "preview"}, format="json").json()["error"]["code"] == "preview_not_available"
    assert login(world["a_proc"]).post(f"/api/v1/files/{pdf['id']}/versions/1/download-link/", {"variant": "preview"}, format="json").status_code == 403
    assert login(world["b_admin"]).post(f"/api/v1/files/{pdf['id']}/versions/1/download-link/", {"variant": "preview"}, format="json").status_code == 404


def test_versions_show_uploader(ws):
    eng, part, p = ws
    f = upload(eng, part["id"], "spec.pdf", PDF_BYTES, passport=p["id"]).json()
    assert f["latest_version"]["uploaded_by"] == "op.eng@example.test"


def test_memberships_overview_lists_only_own_organisations(world):
    eng = login(world["op_eng"], world["operator"])
    rows = eng.get("/api/v1/auth/memberships/").json()
    assert {r["tenant"]["slug"] for r in rows} == {"operator", "client-a"}
    assert [r["tenant"]["slug"] for r in rows if r["current"]] == ["operator"]
    assert all(set(r["counts"]) == {"parts", "passports", "draft_revisions"} for r in rows)
    assert {r["tenant"]["slug"] for r in login(world["a_user"]).get("/api/v1/auth/memberships/").json()} == {"client-a"}


def test_switch_organisation(world, client):
    eng = login(world["op_eng"], world["operator"])
    r = eng.post("/api/v1/auth/switch/", {"tenant": "client-a", "refresh": eng.refresh_token}, format="json")
    assert r.status_code == 200, r.content
    assert r.json()["session"]["tenant"]["slug"] == "client-a"
    # old refresh token is revoked; the new access token works in client A
    assert client.post("/api/v1/auth/refresh/", {"refresh": eng.refresh_token}, format="json").status_code == 401
    eng.credentials(HTTP_AUTHORIZATION=f"Bearer {r.json()['access']}")
    assert eng.get("/api/v1/auth/me/").json()["tenant"]["slug"] == "client-a"
    # no membership in client B: refused
    assert eng.post("/api/v1/auth/switch/", {"tenant": "client-b"}, format="json").status_code == 403
    with tenant_context(world["a"]):
        assert AuditEvent.objects.filter(action="auth.switched_in").exists()
    with tenant_context(world["operator"]):
        assert AuditEvent.objects.filter(action="auth.switched_out").exists()
