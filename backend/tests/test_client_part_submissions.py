"""Requirement update 2026-10: client spare-part submissions held for Aries review, field provenance, and controlled
passport values (PostgreSQL with RLS). Client submissions never carry engineering approval, publication or manufacturing
eligibility, and clients never change Aries-controlled records or engineering files."""
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection

from apps.servicerequests.models import Notification
from apps.tenancy.context import USER_SETTING, write_setting
from apps.tenancy.models import Membership

from .conftest import login
from .test_registration_access import PDF

SUBMISSION = {"part_number": "", "unknown_fields": ["part_number", "original_material"], "name": "Seal housing",
              "equipment_reference": "Sea-water pump SWP-2", "manufacturer": "Unknown OEM", "application": "Sea-water pump",
              "dimensions": "120 x 80 x 40 mm", "description": "Cracked housing, photos attached."}


@pytest.fixture
def on(settings, world):
    settings.CLIENT_PART_SUBMISSIONS_ENABLED = True
    # CN-003: an ordinary Client User submits only with the Client Administrator's permission
    Membership.objects.filter(user=world["a_user"], tenant=world["a"]).update(part_submission_allowed=True)


def titles(user):
    write_setting(USER_SETTING, user.pk)
    return list(Notification.objects.filter(recipient=user).values_list("title", flat=True))


def submit(user, **extra):
    r = login(user).post("/api/v1/parts/", {**SUBMISSION, **extra}, format="json")
    assert r.status_code == 201, r.content
    return r.json()


def test_disabled_by_default(world):
    r = login(world["a_admin"]).post("/api/v1/parts/", SUBMISSION, format="json")
    assert r.status_code == 403
    assert "parts.submit" not in login(world["a_admin"]).session_payload["capabilities"]


def test_client_admin_creates_a_pending_company_record(world, on):
    part = submit(world["a_admin"])
    assert part["origin"] == "client" and part["review_state"] == "pending_review" and part["submission_kind"] == "record"
    assert part["status"] == "draft" and part["passport_id"] is None and part["manufacturing_eligibility"] is None
    assert part["part_number"].startswith("TBC-")  # provisional number, OQ-14
    assert set(part["unknown_fields"]) == {"part_number", "original_material"}
    prov = part["field_provenance"]
    assert prov["name"]["source"] == "client" and prov["name"]["verified_by"] is None
    assert "original_material" not in prov  # left empty
    # the assigned Aries Engineer is notified, the other company is not involved
    assert any("Seal housing" in t for t in titles(world["op_eng"]))
    assert login(world["b_admin"]).get(f"/api/v1/parts/{part['id']}/").status_code == 404


def test_client_users_create_proposals_and_part_number_is_required_unless_unknown(world, on):
    assert submit(world["a_user"], part_number="CU-1", unknown_fields=[])["submission_kind"] == "proposal"
    assert submit(world["a_eng"], part_number="CE-1", unknown_fields=[])["submission_kind"] == "proposal"
    r = login(world["a_user"]).post("/api/v1/parts/", {**SUBMISSION, "unknown_fields": []}, format="json")
    assert r.status_code == 400 and "part_number" in r.json()["error"]["details"]
    # procurement and auditors are not submitters
    assert login(world["a_proc"]).post("/api/v1/parts/", SUBMISSION, format="json").status_code == 403


def test_clients_cannot_set_aries_classifications(world, on):
    r = login(world["a_admin"]).post("/api/v1/parts/", {**SUBMISSION, "criticality": "critical"}, format="json")
    assert r.status_code == 403 and r.json()["error"]["code"] == "aries_controlled_field"
    r = login(world["a_admin"]).post("/api/v1/parts/", {**SUBMISSION, "status": "active"}, format="json")
    assert r.status_code == 403


def test_client_a_cannot_create_or_modify_client_b_parts(world, on):
    b_part = submit(world["b_admin"], part_number="B-1", unknown_fields=[])
    a = login(world["a_admin"])
    assert a.patch(f"/api/v1/parts/{b_part['id']}/", {"name": "hijack"}, format="json").status_code == 404
    assert a.post(f"/api/v1/parts/{b_part['id']}/resubmit/", {}, format="json").status_code == 404
    # a tenant id in the body is ignored: the record lands in the caller's own company
    mine = submit(world["a_admin"], part_number="A-1", unknown_fields=[], tenant=str(world["b"].pk))
    assert login(world["b_admin"]).get(f"/api/v1/parts/{mine['id']}/").status_code == 404
    # a project of company B cannot be linked
    from apps.projects.models import Project
    from apps.tenancy.context import tenant_context

    with tenant_context(world["b"]):
        bp = Project.objects.create(tenant=world["b"], code="BP", name="B project")
    r = a.post("/api/v1/parts/", {**SUBMISSION, "project": str(bp.pk)}, format="json")
    assert r.status_code == 400


def test_clients_cannot_edit_aries_records_or_reviewed_submissions(world, on):
    eng = login(world["op_eng"], world["a"])
    aries_part = eng.post("/api/v1/parts/", {"part_number": "AR-1", "name": "Impeller"}, format="json").json()
    assert aries_part["origin"] == "aries" and aries_part["field_provenance"]["name"]["source"] == "aries"
    r = login(world["a_admin"]).patch(f"/api/v1/parts/{aries_part['id']}/", {"name": "x"}, format="json")
    assert r.status_code == 403 and r.json()["error"]["code"] == "aries_controlled_record"

    part = submit(world["a_user"], part_number="CU-2", unknown_fields=[])
    # another client user may not change someone else's proposal; the Client Administrator may
    other = Membership.objects.get(user=world["a_eng"], tenant=world["a"])
    assert other.role == "client_engineer"
    r = login(world["a_eng"]).patch(f"/api/v1/parts/{part['id']}/", {"name": "x"}, format="json")
    assert r.status_code == 403 and r.json()["error"]["code"] == "not_your_submission"
    assert login(world["a_admin"]).patch(f"/api/v1/parts/{part['id']}/", {"manufacturer": "KSB"}, format="json").status_code == 200

    eng.post(f"/api/v1/parts/{part['id']}/review/", {"decision": "accept"}, format="json")
    r = login(world["a_user"]).patch(f"/api/v1/parts/{part['id']}/", {"name": "x"}, format="json")
    assert r.status_code == 403 and r.json()["error"]["code"] == "submission_locked"


def test_review_workflow_request_info_resubmit_accept_and_passport(world, on):
    part = submit(world["a_user"])
    eng = login(world["op_eng"], world["a"])
    # no passport before acceptance
    r = eng.post("/api/v1/passports/", {"part": part["id"]}, format="json")
    assert r.status_code == 409 and r.json()["error"]["code"] == "part_not_accepted"
    assert eng.post(f"/api/v1/parts/{part['id']}/review/", {"decision": "request_info"}, format="json").status_code == 400
    r = eng.post(f"/api/v1/parts/{part['id']}/review/", {"decision": "request_info", "message": "Send the nameplate photo."}, format="json")
    assert r.json()["review_state"] == "info_requested" and r.json()["review_note"] == "Send the nameplate photo."
    assert r.json()["submission_revision"] == 2  # "send back" opens the next revision (decision of 13 Nov 2026)
    assert any("Sent back for changes" in t for t in titles(world["a_user"]))
    assert any("Sent back for changes" in t for t in titles(world["a_admin"]))

    user = login(world["a_user"])
    assert user.patch(f"/api/v1/parts/{part['id']}/", {"original_material": "CF8M", "unknown_fields": ["part_number"]},
                      format="json").status_code == 200
    photo = user.post("/api/v1/files/", {"part": part["id"], "file": SimpleUploadedFile("nameplate.pdf", PDF), "category": "photo"},
                      format="multipart")
    assert photo.status_code == 201, photo.content
    r = user.post(f"/api/v1/parts/{part['id']}/resubmit/", {"message": "Photo attached."}, format="json")
    assert r.json()["review_state"] == "pending_review"
    assert any("resubmitted" in t for t in titles(world["op_eng"]))

    proj = eng.post("/api/v1/projects/", {"code": "SCAN-1", "name": "Scan"}, format="json").json()
    r = eng.post(f"/api/v1/parts/{part['id']}/review/", {"decision": "accept", "project": proj["id"],
                                                         "verified_fields": ["name", "original_material"], "message": "OK"}, format="json")
    body = r.json()
    assert body["review_state"] == "accepted" and body["project"] == proj["id"] and body["reviewed_by_name"]
    # approved (decision of 13 Nov 2026): the passport draft is created for Aries to complete; nothing is published or
    # made eligible
    assert body["status"] == "draft" and body["passport_id"] and body["evidence_level"] == "none"
    assert body["publication_state"] == "draft" and body["manufacturing_eligibility"] == "not_eligible"
    prov = body["field_provenance"]
    assert prov["original_material"]["source"] == "client" and prov["original_material"]["verified_by"]
    assert prov["project"]["source"] == "aries"
    assert prov["dimensions"]["verified_by"] is None  # not verified, still shown as client-supplied
    assert eng.post("/api/v1/passports/", {"part": part["id"]}, format="json").status_code == 400  # one passport per part, already created
    passport = eng.get(f"/api/v1/passports/{body['passport_id']}/")
    assert passport.json()["manufacturing_eligibility"] == "not_eligible" and passport.json()["publication_state"] != "published"
    assert passport.json()["current_revision"]["content"]["rl1"]["original_material_grade"] == "CF8M"  # prefilled from the submission
    # clients cannot review or accept their own submissions
    other = submit(world["a_admin"], part_number="X-9", unknown_fields=[])
    assert login(world["a_admin"]).post(f"/api/v1/parts/{other['id']}/review/", {"decision": "accept"}, format="json").status_code == 403


def test_decline_and_aries_edits_mark_values_as_aries(world, on):
    part = submit(world["a_admin"], part_number="D-1", unknown_fields=[])
    eng = login(world["op_eng"], world["a"])
    r = eng.patch(f"/api/v1/parts/{part['id']}/", {"dimensions": "Ø120 x 40 mm"}, format="json")
    assert r.json()["field_provenance"]["dimensions"]["source"] == "aries"
    assert eng.post(f"/api/v1/parts/{part['id']}/review/", {"decision": "decline"}, format="json").status_code == 400
    r = eng.post(f"/api/v1/parts/{part['id']}/review/", {"decision": "decline", "message": "Duplicate of AR-1."}, format="json")
    assert r.json()["review_state"] == "declined"
    assert eng.post("/api/v1/passports/", {"part": part["id"]}, format="json").status_code == 409
    assert eng.post(f"/api/v1/parts/{part['id']}/review/", {"decision": "accept"}, format="json").status_code == 409


def test_engineers_review_only_authorised_clients_and_projects(world, on):
    admin = login(world["op_admin"])
    eng = login(world["op_eng"], world["a"])
    p1 = eng.post("/api/v1/projects/", {"code": "P1", "name": "x"}, format="json").json()
    p2 = eng.post("/api/v1/projects/", {"code": "P2", "name": "x"}, format="json").json()
    in_p2 = submit(world["a_admin"], part_number="S-2", unknown_fields=[], project=p2["id"])
    no_project = submit(world["a_admin"], part_number="S-0", unknown_fields=[])
    mid = Membership.objects.get(user=world["op_eng"], tenant=world["a"]).pk
    admin.put(f"/api/v1/clients/{world['a'].pk}/engineers/{mid}/access/", {"scope": "projects", "project_ids": [p1["id"]]}, format="json")
    eng = login(world["op_eng"], world["a"])
    assert eng.post(f"/api/v1/parts/{in_p2['id']}/review/", {"decision": "accept"}, format="json").status_code == 404
    assert eng.post(f"/api/v1/parts/{no_project['id']}/review/", {"decision": "accept"}, format="json").status_code == 404
    # cannot link a project outside the assignment when accepting
    in_p1 = submit(world["a_admin"], part_number="S-1", unknown_fields=[], project=p1["id"])
    r = eng.post(f"/api/v1/parts/{in_p1['id']}/review/", {"decision": "accept", "project": p2["id"]}, format="json")
    assert r.status_code == 400
    # the Aries Admin (no engineering capability) and engineers of other companies cannot review
    assert admin.post(f"/api/v1/parts/{in_p1['id']}/review/", {"decision": "accept"}, format="json").status_code in (403, 404)
    Membership.objects.create(user=world["op_admin"], tenant=world["b"], role="operator_engineer")
    assert login(world["op_admin"], world["b"]).post(f"/api/v1/parts/{in_p1['id']}/review/", {"decision": "accept"},
                                                     format="json").status_code == 404


def test_submission_files_are_limited_and_aries_masters_stay_protected(world, on):
    eng = login(world["op_eng"], world["a"])
    aries_part = eng.post("/api/v1/parts/", {"part_number": "AR-2", "name": "Impeller"}, format="json").json()
    master = eng.post("/api/v1/files/", {"part": aries_part["id"], "file": SimpleUploadedFile("m.pdf", PDF), "category": "drawing", "client_visible": "true"},
                      format="multipart").json()
    user = login(world["a_user"])
    # a client user may not add files to Aries parts or other people's submissions, CAD to their own open submission is allowed since D-14
    assert user.post("/api/v1/files/", {"part": aries_part["id"], "file": SimpleUploadedFile("u.pdf", PDF)},
                     format="multipart").status_code == 403
    other = submit(world["a_admin"], part_number="O-1", unknown_fields=[])
    assert user.post("/api/v1/files/", {"part": other["id"], "file": SimpleUploadedFile("u.pdf", PDF)},
                     format="multipart").status_code == 403
    mine = submit(world["a_user"], part_number="M-1", unknown_fields=[])
    step = user.post("/api/v1/files/", {"part": mine["id"], "file": SimpleUploadedFile("x.stp", b"ISO-10303-21;\n")}, format="multipart")
    assert step.status_code == 201 and step.json()["category"] == "3d_model"  # post-UAT D-14: CAD with the own open submission
    # nobody on the client side can rename or re-version the Aries master file
    for who in ("a_user", "a_admin", "a_eng"):
        c = login(world[who])
        assert c.patch(f"/api/v1/files/{master['id']}/", {"title": "x"}, format="json").status_code == 403
        assert c.post(f"/api/v1/files/{master['id']}/versions/", {"file": SimpleUploadedFile("v2.pdf", PDF)},
                      format="multipart").status_code == 403
    assert len(eng.get(f"/api/v1/files/{master['id']}/versions/").json()) == 1


# ------------------------------------------------------------------ passport controlled values

def test_controlled_custom_and_unit_values_round_trip_and_history_is_kept(world):
    eng = login(world["op_eng"], world["a"])
    part = eng.post("/api/v1/parts/", {"part_number": "RT-1", "name": "x"}, format="json").json()
    legacy = {"rl1": {"part_size": "120.0 x 34.0 mm (Ø x H)", "original_material_grade": "AISI 316 (sample)"}}
    passport = eng.post("/api/v1/passports/", {"part": part["id"], "initial_content": legacy}, format="json").json()
    pid = passport["id"]
    rl1 = {"original_material_grade": "Duplex 2205", "material_identification_method": "pmi", "part_size": "120 x 80 x 40 mm",
           "application": "My bespoke skid", "atmosphere": "corrosive", "operating_environment": "Offshore / marine splash zone",
           "motion": "rotating", "rpm": "1450", "cad_3d_available": True, "drawings_2d_available": False,
           "not_applicable": {"ip_status": "Not relevant for this client"}}
    rl2 = {"manufacturing_process": "L-PBF (laser powder bed fusion)", "material_selection": "Special alloy XYZ",
           "applicable_standards": "ASTM F3184; ISO/ASTM 52904; Client spec CS-12", "ndt": "Visual; Dye penetrant (PT); Helium leak",
           "dimensional_tolerances": "ISO 2768-mK", "mtc_required": True,
           "mechanical_acceptance": [{"property": "tensile", "requirement": "≥ 485", "unit": "MPa", "standard": "ISO 6892-1"}],
           "manufacturing_spec": {"layer_thickness": "40 µm", "heat_treatment": "Stress relief 650 °C / 2 h", "printing_hours": 11.5,
                                  "process_parameters": [{"name": "Laser power", "value": "285", "unit": "W"}]}}
    r = eng.patch(f"/api/v1/passports/{pid}/revisions/1/", {"content": {"rl1": rl1, "rl2": rl2}}, format="json")
    assert r.status_code == 200, r.content
    back = eng.get(f"/api/v1/passports/{pid}/revisions/1/").json()["content"]
    # stored exactly as sent: no conversion or reinterpretation (unsent nullable hours come back as null, as before)
    spec = back["rl2"].pop("manufacturing_spec")
    assert back["rl1"] == rl1 and back["rl2"] == {k: v for k, v in rl2.items() if k != "manufacturing_spec"}
    assert {k: spec[k] for k in rl2["manufacturing_spec"]} == rl2["manufacturing_spec"]
    assert "operating_environment" not in back and "ip_status" not in r.json()["completeness"]["rl1"]["missing"]
    # new optional keys do not change what completeness requires
    assert r.json()["completeness"]["rl1"]["total"] == 11  # 10 BR-006 fields + rpm for rotating parts
    # a choice field still refuses values outside its list
    bad = eng.patch(f"/api/v1/passports/{pid}/revisions/1/", {"content": {"rl1": {"motion": "oscillating"}}}, format="json")
    assert bad.status_code == 400
    # earlier revisions are preserved when a new one is started
    eng.patch(f"/api/v1/passports/{pid}/revisions/1/", {"change_summary": "x"}, format="json")
    revs = eng.get(f"/api/v1/passports/{pid}/revisions/").json()
    assert len(revs) == 1 and revs[0]["content"]["rl1"]["rpm"] == "1450"


def test_field_options_are_provisional_and_readable_by_all_roles(world):
    for who, tenant in (("a_user", None), ("op_eng", world["a"])):
        r = login(world[who], tenant).get("/api/v1/passport-field-options/")
        assert r.status_code == 200
        body = r.json()
        assert body["provisional"] is True and body["decision"] == "OQ-16"
        assert any(o["value"] == "AISI 316L" for o in body["lists"]["material_grades"])
        assert "°C" in body["units"]["temperature"]
        assert "criticality" not in " ".join(body["lists"])  # no AMSL classes are invented


def test_aries_admins_are_told_when_no_engineer_can_review(world, on):
    admin = login(world["op_admin"])
    eng = login(world["op_eng"], world["a"])
    p1 = eng.post("/api/v1/projects/", {"code": "P1", "name": "x"}, format="json").json()
    mid = Membership.objects.get(user=world["op_eng"], tenant=world["a"]).pk
    admin.put(f"/api/v1/clients/{world['a'].pk}/engineers/{mid}/access/", {"scope": "projects", "project_ids": [p1["id"]]}, format="json")
    submit(world["a_admin"], part_number="NP-1", unknown_fields=[])  # no project: the project-limited engineer cannot see it
    assert not any("NP-1" in t for t in titles(world["op_eng"]))
    assert any("NP-1" in t and "waiting for approval" in t for t in titles(world["op_admin"]))  # Admins/Managers approve too
