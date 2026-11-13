"""Client Clone Part workflow (BR-033 customisation, CN-003): a clone is a new part linked permanently to its source,
held Pending Aries review, with nothing inherited that implies approval. The source part, its files and its passport
are never modified. PostgreSQL with RLS."""
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connection, transaction

from apps.parts.models import SparePart, SparePartReviewEvent
from apps.servicerequests.models import Notification
from apps.tenancy.context import USER_SETTING, tenant_context, write_setting
from apps.tenancy.models import Membership

from .conftest import login
from .test_registration_access import PDF

CLONE = {"part_number": "IMP-200-AL", "proposed_material": "AlSi10Mg", "material_change_reason": "Lighter part for the new pump skid",
         "description": "Same impeller in aluminium.", "client_remarks": "Needed for the Q1 overhaul."}


@pytest.fixture
def on(settings, world):
    settings.CLIENT_PART_SUBMISSIONS_ENABLED = True
    return world


@pytest.fixture
def source(on):
    """An Aries-scanned part with a STEP file and a passport draft in client A, project P1."""
    w = on
    eng = login(w["op_eng"], w["a"])
    proj = eng.post("/api/v1/projects/", {"code": "P1", "name": "Pump scans"}, format="json").json()
    part = eng.post("/api/v1/parts/", {"part_number": "IMP-200", "name": "Impeller", "project": proj["id"],
                                        "original_material": "AISI 316L", "dimensions": "Ø200 x 60 mm",
                                        "description": "Closed impeller.", "criticality": "critical"}, format="json").json()
    f = eng.post("/api/v1/files/", {"part": part["id"], "file": SimpleUploadedFile("impeller.pdf", PDF), "category": "drawing", "client_visible": "true"},
                 format="multipart").json()
    passport = eng.post("/api/v1/passports/", {"part": part["id"], "initial_content": {"rl1": {"original_material_grade": "AISI 316L"}}},
                        format="json").json()
    return {"project": proj, "part": part, "file": f, "passport": passport}


def titles(user):
    write_setting(USER_SETTING, user.pk)
    return list(Notification.objects.filter(recipient=user).values_list("title", flat=True))


def do_clone(user, source_id, **extra):
    return login(user).post(f"/api/v1/parts/{source_id}/clone/", {**CLONE, **extra}, format="json")


def test_client_clones_an_aries_scanned_part(on, source):
    before = login(on["op_eng"], on["a"]).get(f"/api/v1/parts/{source['part']['id']}/").json()
    rev_before = login(on["op_eng"], on["a"]).get(f"/api/v1/passports/{source['passport']['id']}/revisions/1/").json()
    r = do_clone(on["a_admin"], source["part"]["id"])
    assert r.status_code == 201, r.content
    c = r.json()
    # 1, 2: separate record with its own number, lineage stored
    assert c["id"] != source["part"]["id"] and c["part_number"] == "IMP-200-AL"
    assert c["source_part"] == source["part"]["id"] and c["source_part_number"] == "IMP-200"
    assert c["source_passport_number"] == source["passport"]["passport_number"] and c["source_revision_number"] == 1
    assert c["submission_kind"] == "clone" and c["origin"] == "client" and c["review_state"] == "pending_review"
    assert c["submitted_by_name"] and c["submitted_at"]
    # 3: material change with reason; original material is kept as the inherited reference
    assert c["proposed_material"] == "AlSi10Mg" and c["material_change_reason"].startswith("Lighter")
    assert c["original_material"] == "AISI 316L" and c["field_provenance"]["original_material"]["source"] == "inherited"
    assert c["field_provenance"]["proposed_material"]["source"] == "client"
    changes = {x["field"]: x for x in c["clone_changes"]}
    assert changes["material"]["changed"] and changes["material"]["original"] == "AISI 316L"
    assert changes["description"]["changed"] and not changes["name"]["changed"]
    # nothing that implies approval is inherited
    assert c["passport_id"] is None and c["manufacturing_eligibility"] is None and c["evidence_level"] is None
    assert c["criticality"] == "unknown" and c["status"] == "draft" and c["documents"]["total"] == 0
    assert c["project"] == source["project"]["id"]  # same project, so the same engineers review it
    # 4: the original is unchanged (fields, timestamps, files, passport)
    after = login(on["op_eng"], on["a"]).get(f"/api/v1/parts/{source['part']['id']}/").json()
    for k in ("part_number", "name", "original_material", "description", "criticality", "status", "updated_at",
              "passport_id", "documents", "review_state"):
        assert after[k] == before[k], k
    eng = login(on["op_eng"], on["a"])
    assert len(eng.get(f"/api/v1/files/{source['file']['id']}/versions/").json()) == 1
    rev = eng.get(f"/api/v1/passports/{source['passport']['id']}/revisions/1/").json()
    assert rev["content"] == rev_before["content"] and rev["updated_at"] == rev_before["updated_at"]
    # 5: relationship is listed and searchable
    assert [p["part_number"] for p in login(on["a_user"]).get(f"/api/v1/parts/?source_part={source['part']['id']}").json()["results"]] == ["IMP-200-AL"]
    assert any(p["part_number"] == "IMP-200-AL" for p in login(on["a_user"]).get("/api/v1/parts/?search=IMP-200").json()["results"])
    # not in the published catalog
    assert login(on["a_user"]).get("/api/v1/parts/?catalog=published").json()["count"] == 0
    # 6: assigned engineer notified; history and audit recorded
    assert any("Clone waiting for approval" in t for t in titles(on["op_eng"]))
    hist = login(on["a_admin"]).get(f"/api/v1/parts/{c['id']}/history/").json()
    assert [h["action"] for h in hist] == ["cloned"] and hist[0]["note"] == "Needed for the Q1 overhaul."
    with tenant_context(on["a"]):
        from apps.audit.models import AuditEvent

        assert AuditEvent.objects.filter(action="spare_part.cloned").count() == 1


def test_part_number_must_be_new_and_reason_is_mandatory(on, source):
    sid = source["part"]["id"]
    r = do_clone(on["a_admin"], sid, part_number="imp-200")  # case-insensitive duplicate of the source
    assert r.status_code == 400 and r.json()["error"]["code"] == "duplicate_part_number"
    r = do_clone(on["a_admin"], sid, part_number="")
    assert r.status_code == 400
    r = do_clone(on["a_admin"], sid, material_change_reason="")
    assert r.status_code == 400 and r.json()["error"]["code"] == "reason_required"
    # same material needs no reason; a clone without material change is allowed
    assert do_clone(on["a_admin"], sid, part_number="IMP-200-B", proposed_material="aisi 316l", material_change_reason="").status_code == 201
    assert do_clone(on["a_admin"], sid, part_number="IMP-200-AL").status_code == 201
    assert do_clone(on["a_eng"], sid, part_number="IMP-200-AL").json()["error"]["code"] == "duplicate_part_number"
    # editing an open clone keeps the rule
    c = login(on["a_admin"]).get("/api/v1/parts/?search=IMP-200-AL").json()["results"][0]
    r = login(on["a_admin"]).patch(f"/api/v1/parts/{c['id']}/", {"proposed_material": "Ti-6Al-4V", "material_change_reason": ""}, format="json")
    assert r.status_code == 400


def test_lineage_cannot_be_changed_even_in_the_database(on, source):
    c = do_clone(on["a_admin"], source["part"]["id"]).json()
    with tenant_context(on["a"]):
        part = SparePart.objects.get(pk=c["id"])
        part.source_part_number = "OTHER"
        with pytest.raises(Exception) as exc, transaction.atomic():
            part.save(update_fields=["source_part_number"])
        assert "immutable_record" in str(exc.value)
        ev = SparePartReviewEvent.objects.filter(part=part).first()
        ev.note = "rewritten"
        with pytest.raises(Exception), transaction.atomic():
            ev.save()


def test_who_may_clone(on, source):
    sid = source["part"]["id"]
    assert do_clone(on["a_eng"], sid, part_number="E-1").status_code == 201  # Client Engineer by role
    assert do_clone(on["a_user"], sid, part_number="U-1").status_code == 403  # Client User without permission
    assert do_clone(on["a_proc"], sid, part_number="P-1").status_code == 403
    # the Client Administrator grants the permission; then the Client User may clone
    m = Membership.objects.get(user=on["a_user"], tenant=on["a"])
    r = login(on["a_admin"]).patch(f"/api/v1/users/{m.pk}/", {"part_submission_allowed": True}, format="json")
    assert r.status_code == 200 and r.json()["part_submission_allowed"] is True
    assert do_clone(on["a_user"], sid, part_number="U-1").status_code == 201
    # not applicable to other roles
    me = Membership.objects.get(user=on["a_eng"], tenant=on["a"])
    assert login(on["a_admin"]).patch(f"/api/v1/users/{me.pk}/", {"part_submission_allowed": True}, format="json").status_code == 400
    # Aries staff do not use the client clone path
    assert login(on["op_eng"], on["a"]).post(f"/api/v1/parts/{sid}/clone/", CLONE, format="json").status_code == 403


def test_cross_client_clone_is_denied(on, source):
    r = do_clone(on["b_admin"], source["part"]["id"])
    assert r.status_code == 404
    with tenant_context(on["a"]):
        assert not SparePart.objects.filter(part_number="IMP-200-AL").exists()
    with tenant_context(on["b"]):
        assert not SparePart.objects.filter(part_number="IMP-200-AL").exists()


def test_open_submissions_cannot_be_cloned(on, source):
    pending = login(on["a_admin"]).post("/api/v1/parts/", {"part_number": "NEW-1", "name": "x", "equipment_reference": "e",
                                                           "manufacturer": "m", "application": "a", "description": "d"}, format="json").json()
    r = do_clone(on["a_admin"], pending["id"], part_number="NEW-1-B")
    assert r.status_code == 409 and r.json()["error"]["code"] == "source_not_accepted"


def test_review_corrections_accept_and_gates_stay_closed(on, source):
    c = do_clone(on["a_admin"], source["part"]["id"]).json()
    eng = login(on["op_eng"], on["a"])
    # 7: correction request, client correction and resubmission, acceptance
    eng.post(f"/api/v1/parts/{c['id']}/review/", {"decision": "request_info", "message": "Confirm operating temperature."}, format="json")
    client = login(on["a_admin"])
    assert client.patch(f"/api/v1/parts/{c['id']}/", {"client_remarks": "Max 80 °C."}, format="json").status_code == 200
    assert client.post(f"/api/v1/parts/{c['id']}/resubmit/", {"message": "Added temperature."}, format="json").json()["review_state"] == "pending_review"
    assert eng.post("/api/v1/passports/", {"part": c["id"]}, format="json").json()["error"]["code"] == "part_not_accepted"
    acc = eng.post(f"/api/v1/parts/{c['id']}/review/", {"decision": "accept", "message": "Assess AlSi10Mg in R-L2."}, format="json").json()
    assert acc["review_state"] == "accepted"
    hist = client.get(f"/api/v1/parts/{c['id']}/history/").json()
    assert [h["action"] for h in hist] == ["cloned", "info_requested", "resubmitted", "accepted"]
    assert hist[1]["side"] == "aries" and hist[1]["author"] and hist[1]["note"] == "Confirm operating temperature."
    # 10: approval creates the clone's own passport draft (not eligible, not published; the source passport is not copied,
    # only the clone's known values are prefilled) and sends the manufacturing request automatically (decision of 13 Nov 2026)
    passport = eng.get(f"/api/v1/passports/{acc['passport_id']}/").json()
    assert passport["manufacturing_eligibility"] == "not_eligible" and passport["publication_state"] == "draft"
    assert passport["evidence_level"] == "none"
    rev = eng.get(f"/api/v1/passports/{passport['id']}/revisions/1/").json()
    assert rev["content"]["rl1"]["proposed_material"] == "AlSi10Mg" and "rl2" not in rev["content"]
    reqs = client.get("/api/v1/requests/").json()["results"]
    auto = [r for r in reqs if r["part_number"] == c["part_number"]]
    assert len(auto) == 1 and auto[0]["status"] == "submitted"
    assert any("sent to Aries automatically" in t or "approved" in t for t in titles(on["a_admin"]))
    # passports prepared by Aries need no approval: the engineer marks the revision complete
    assert eng.post(f"/api/v1/passports/{passport['id']}/revisions/1/submit/", {}, format="json").json()["error"]["code"] == "approval_not_needed"
    assert eng.post(f"/api/v1/passports/{passport['id']}/revisions/1/complete/", {}, format="json").json()["error"]["code"] == "passport_incomplete"
    from .test_passport_approval import fill
    fill(eng, f"/api/v1/passports/{passport['id']}")
    r = eng.post(f"/api/v1/passports/{passport['id']}/revisions/1/complete/", {}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert eng.get(f"/api/v1/passports/{passport['id']}/").json()["publication_state"] == "complete"
    # client cannot modify the accepted clone or review it
    assert client.patch(f"/api/v1/parts/{c['id']}/", {"name": "x"}, format="json").status_code == 403
    assert client.post(f"/api/v1/parts/{c['id']}/review/", {"decision": "accept"}, format="json").status_code == 403


def test_reject_with_reason(on, source):
    c = do_clone(on["a_admin"], source["part"]["id"]).json()
    eng = login(on["op_eng"], on["a"])
    assert eng.post(f"/api/v1/parts/{c['id']}/review/", {"decision": "decline"}, format="json").status_code == 400
    r = eng.post(f"/api/v1/parts/{c['id']}/review/", {"decision": "decline", "message": "Material unsuitable for sea water."}, format="json")
    assert r.json()["review_state"] == "declined"
    assert any("declined" in t for t in titles(on["a_admin"]))


def test_project_restricted_engineer(on, source):
    admin = login(on["op_admin"])
    eng = login(on["op_eng"], on["a"])
    p2 = eng.post("/api/v1/projects/", {"code": "P2", "name": "Other"}, format="json").json()
    c = do_clone(on["a_admin"], source["part"]["id"]).json()  # in P1
    mid = Membership.objects.get(user=on["op_eng"], tenant=on["a"]).pk
    admin.put(f"/api/v1/clients/{on['a'].pk}/engineers/{mid}/access/", {"scope": "projects", "project_ids": [p2["id"]]}, format="json")
    eng = login(on["op_eng"], on["a"])
    assert eng.get(f"/api/v1/parts/{c['id']}/").status_code == 404
    assert eng.post(f"/api/v1/parts/{c['id']}/review/", {"decision": "accept"}, format="json").status_code == 404
    admin.put(f"/api/v1/clients/{on['a'].pk}/engineers/{mid}/access/", {"scope": "projects", "project_ids": [source["project"]["id"]]}, format="json")
    eng = login(on["op_eng"], on["a"])
    assert eng.post(f"/api/v1/parts/{c['id']}/review/", {"decision": "accept"}, format="json").status_code == 200


def test_clients_still_cannot_touch_source_cad(on, source):
    do_clone(on["a_admin"], source["part"]["id"])
    client = login(on["a_admin"])
    fid = source["file"]["id"]
    assert client.patch(f"/api/v1/files/{fid}/", {"title": "x"}, format="json").status_code == 403
    assert client.post(f"/api/v1/files/{fid}/versions/", {"file": SimpleUploadedFile("v2.pdf", PDF)}, format="multipart").status_code == 403
    # source files remain readable as references
    assert client.get(f"/api/v1/files/?part={source['part']['id']}").json()["count"] == 1


def test_disabled_switch_blocks_cloning(settings, world, source):
    settings.CLIENT_PART_SUBMISSIONS_ENABLED = False
    assert do_clone(world["a_admin"], source["part"]["id"]).status_code == 403


def test_duplicate_number_race_is_atomic(on, source):
    with tenant_context(on["a"]):
        SparePart.objects.create(tenant=on["a"], part_number="RACE-1", name="x")
        with pytest.raises(IntegrityError), transaction.atomic():
            SparePart.objects.create(tenant=on["a"], part_number="RACE-1", name="y")
    assert do_clone(on["a_admin"], source["part"]["id"], part_number="RACE-1").status_code == 400


def material_of(assessment):
    """The material evidence item the additive screening used."""
    return next(e for e in assessment["additive"]["evidence"] if e["key"] == "material")


def test_clone_feasibility_assesses_the_proposed_material(on, source, settings):
    """A clone with a material change is assessed with the proposed material (labelled as a proposed, unverified change),
    never silently with the original's material; the original's assessment is not affected (UAT Case C, D-13)."""
    settings.PART_INTELLIGENCE_ENABLED = True
    eng = login(on["op_eng"], on["a"])
    orig_v1 = eng.post(f"/api/v1/parts/{source['part']['id']}/feasibility/assess/", {}, format="json").json()["assessment"]
    c = do_clone(on["a_admin"], source["part"]["id"]).json()
    eng.post(f"/api/v1/parts/{c['id']}/review/", {"decision": "accept", "message": "Assess AlSi10Mg."}, format="json")
    v1 = eng.post(f"/api/v1/parts/{c['id']}/feasibility/assess/", {}, format="json").json()["assessment"]
    mat = material_of(v1)
    assert mat["value"] == "AlSi10Mg" and mat["state"] == "recorded"
    assert "Proposed material change from AISI 316L" in mat["note"] and "not assessed or approved" in mat["note"]
    assert "AISI 316L" not in mat["value"]
    # an engineer-recorded proposed material in the clone's passport takes precedence and changes the inputs (new version)
    passport = {"id": eng.get(f"/api/v1/parts/{c['id']}/").json()["passport_id"]}  # created on approval
    eng.patch(f"/api/v1/passports/{passport['id']}/revisions/1/", {"content": {"rl1": {"proposed_material": "AlSi10Mg (EN AC-43000)"}}}, format="json")
    v2 = eng.post(f"/api/v1/parts/{c['id']}/feasibility/assess/", {}, format="json").json()
    assert v2["reused"] is False and v2["assessment"]["version"] == 2
    assert material_of(v2["assessment"])["value"] == "AlSi10Mg (EN AC-43000)"
    # the original keeps its own, unchanged assessment and material
    orig = eng.get(f"/api/v1/parts/{source['part']['id']}/feasibility/").json()["assessments"]
    assert [a["id"] for a in orig] == [orig_v1["id"]] and material_of(orig[0])["value"] == "AISI 316L"


def test_clone_with_modified_dimensions_requires_revised_geometry(world, settings):
    """Post-UAT Case C: a clone whose dimensions differ from the original needs its own CAD or drawing before either route."""
    from apps.intelligence import feasibility as F

    with tenant_context(world["a"]):
        src = SparePart.objects.create(tenant=world["a"], part_number="ORIG-1", name="Impeller", dimensions="160 x 160 x 75 mm",
                                       original_material="CF8M")
        clone = SparePart.objects.create(tenant=world["a"], part_number="ORIG-1-M1", name="Impeller (modified)", origin="client",
                                         review_state="accepted", submission_kind="clone", source_part=src,
                                         source_snapshot={"dimensions": "160 x 160 x 75 mm"}, dimensions="170 x 170 x 90 mm")
        same = SparePart.objects.create(tenant=world["a"], part_number="ORIG-1-M2", name="Impeller (material only)", origin="client",
                                        review_state="accepted", submission_kind="clone", source_part=src,
                                        source_snapshot={"dimensions": "160 x 160 x 75 mm"}, dimensions="160 x 160 x 75 mm")
        from apps.intelligence import service

        out = F.assess(clone, service.analyse(clone), [], None)
        assert any(c["code"] == "geometry_revision_required" for c in out["additive"]["constraints"])
        assert out["additive"]["status"] == "specialist_assessment" and out["additive"]["next_actions"][0] == F.GEOMETRY_ACTION
        assert F.GEOMETRY_ACTION in out["next_actions"]
        with_cad = F.assess(clone, service.analyse(clone), [{"kind": "step", "category": "3d_model", "title": "Clone CAD D170"}], None)
        assert not any(c["code"] == "geometry_revision_required" for c in with_cad["additive"]["constraints"])
        unchanged = F.assess(same, service.analyse(same), [], None)
        assert not any(c["code"] == "geometry_revision_required" for c in unchanged["additive"]["constraints"])


def test_clone_can_go_to_another_project_of_the_company(on, source):
    """Post-UAT D-21: the clone keeps the source project by default or goes to another project the requester may use."""
    eng = login(on["op_eng"], on["a"])
    other = eng.post("/api/v1/projects/", {"code": "P2", "name": "Modified pumps"}, format="json").json()
    default = do_clone(on["a_admin"], source["part"]["id"], part_number="IMP-200-A").json()
    assert default["project"] == source["project"]["id"]
    moved = do_clone(on["a_admin"], source["part"]["id"], part_number="IMP-200-B", project=other["id"])
    assert moved.status_code == 201, moved.content
    assert moved.json()["project"] == other["id"]
    assert (moved.json()["field_provenance"].get("project") or {}).get("source") == "client"
    bad = do_clone(on["a_admin"], source["part"]["id"], part_number="IMP-200-C", project="00000000-0000-0000-0000-000000000000")
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_project"
