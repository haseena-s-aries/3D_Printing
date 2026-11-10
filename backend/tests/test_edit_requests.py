"""Controlled edit requests and reviewer decisions (CN-006). PostgreSQL with RLS."""
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, transaction

from apps.edits.models import EditRequest, EditRequestEvent
from apps.parts.models import SparePart
from apps.passports.models import DigitalPassport, PassportRevision
from apps.servicerequests.models import Notification
from apps.tenancy.context import USER_SETTING, tenant_context, write_setting
from apps.tenancy.models import Membership, Role

from .conftest import login, make_user
from .test_registration_access import PDF

CONTENT = {"rl1": {"part_size": "Ø45 x 40.5 mm", "original_material_grade": "AISI 316L"},
           "rl2": {"ndt": "Visual", "manufacturing_spec": {"machine": "EOS M290"}}, "notes": "CONFIDENTIAL-NOTE"}


@pytest.fixture
def env(settings, world):
    settings.EDIT_REQUESTS_ENABLED = True
    settings.CLIENT_PART_SUBMISSIONS_ENABLED = True
    w = world
    w["op_rev"] = make_user("op.rev@example.test", w["operator"], Role.OPERATOR_ENGINEER)
    Membership.objects.create(user=w["op_rev"], tenant=w["a"], role=Role.OPERATOR_ENGINEER, edit_reviewer=True)
    eng = login(w["op_eng"], w["a"])
    proj = eng.post("/api/v1/projects/", {"code": "P1", "name": "Pumps"}, format="json").json()
    part = eng.post("/api/v1/parts/", {"part_number": "ER-1", "name": "Impeller", "project": proj["id"], "description": "d"}, format="json").json()
    passport = eng.post("/api/v1/passports/", {"part": part["id"], "initial_content": CONTENT}, format="json").json()
    stp = (Path(__file__).parent / "fixtures" / "sleeve_d45_h40_5_synthetic.stp").read_bytes()
    step = eng.post("/api/v1/files/", {"part": part["id"], "category": "3d_model", "file": SimpleUploadedFile("m.stp", stp)}, format="multipart")
    assert step.status_code == 201, step.content
    return {"project": proj, "part": part, "passport": passport, "step": step.json()}


def req(client, part, changes, passport=None, submit=True, reason="Nameplate shows a different value", **extra):
    body = {"part": part, "changes": changes, "reason": reason, "submit": submit, **extra}
    if passport:
        body["passport"] = passport
    return client.post("/api/v1/edit-requests/", body, format="json")


def act(client, rid, what, note=""):
    return client.post(f"/api/v1/edit-requests/{rid}/{what}/", {"note": note}, format="json")


def titles(user):
    write_setting(USER_SETTING, user.pk)
    return list(Notification.objects.filter(recipient=user).values_list("title", "body"))


def test_client_request_reviewed_and_applied_to_aries_master_data(world, env):
    c = login(world["a_admin"])
    r = req(c, env["part"]["id"], [{"field": "name", "proposed": "Closed impeller"}])
    assert r.status_code == 201, r.content
    er = r.json()
    assert er["status"] == "submitted" and er["reference"].startswith("ER-") and er["data_class"] == "aries_master"
    assert er["changes"][0]["original"] == "Impeller" and er["requester_role_label"] == "Client Administrator"
    assert any("Edit request submitted" in t for t, _ in titles(world["op_rev"]))  # the authorised reviewer
    assert not any("Edit request submitted" in t for t, _ in titles(world["op_eng"]))  # not an authorised reviewer
    rev = login(world["op_rev"], world["a"])
    assert [x["reference"] for x in rev.get("/api/v1/edit-requests/?queue=review").json()["results"]] == [er["reference"]]
    assert act(rev, er["id"], "start-review").json()["status"] == "under_review"
    done = act(rev, er["id"], "approve", "Confirmed on the nameplate").json()
    assert done["status"] == "applied" and done["reviewer_name"] and "previous values are kept" in done["application_result"]
    assert done["changes"][0]["current"] == "Closed impeller" and done["changes"][0]["original"] == "Impeller"  # response shows the target now
    part = rev.get(f"/api/v1/parts/{env['part']['id']}/").json()
    assert part["name"] == "Closed impeller" and part["field_provenance"]["name"]["verified_by"]
    assert [e["action"] for e in done["events"]] == ["created", "submitted", "review_started", "approved", "applied"]
    assert any("approved and applied" in t for t, _ in titles(world["a_admin"]))
    with tenant_context(world["a"]):
        from apps.audit.models import AuditEvent

        assert {"edit_request.submitted", "edit_request.approved", "edit_request.applied"} <= set(AuditEvent.objects.values_list("action", flat=True))


def test_no_self_approval_and_no_unauthorised_approval(world, env):
    rev = login(world["op_rev"], world["a"])
    own = req(rev, env["part"]["id"], [{"field": "description", "proposed": "new"}]).json()
    r = act(rev, own["id"], "approve")
    assert r.status_code == 403 and r.json()["error"]["code"] == "self_approval"
    other = req(login(world["a_admin"]), env["part"]["id"], [{"field": "description", "proposed": "x2"}]).json()
    assert act(login(world["op_eng"], world["a"]), other["id"], "approve").status_code == 403  # engineer without authority
    assert act(login(world["a_admin"]), other["id"], "approve").status_code == 403  # client cannot approve
    assert act(login(world["op_admin"]), other["id"], "approve").status_code in (403, 404)  # Aries Admin is not an approver
    assert "edits.review" not in login(world["op_admin"]).session_payload["capabilities"]
    assert "edits.review" not in login(world["op_eng"], world["a"]).session_payload["capabilities"]


def test_client_descriptive_data_on_client_submission(world, env):
    c = login(world["a_admin"])
    sub = c.post("/api/v1/parts/", {"part_number": "SUB-9", "name": "x", "equipment_reference": "e", "manufacturer": "m",
                                     "application": "a", "description": "d", "project": env["project"]["id"]}, format="json").json()
    er = req(c, sub["id"], [{"field": "manufacturer", "proposed": "KSB"}]).json()
    assert er["data_class"] == "client_descriptive"
    rev = login(world["op_rev"], world["a"])
    assert act(rev, er["id"], "approve").json()["status"] == "applied"
    p = rev.get(f"/api/v1/parts/{sub['id']}/").json()
    assert p["manufacturer"] == "KSB" and p["field_provenance"]["manufacturer"]["source"] == "client"


def test_passport_draft_becomes_new_revision_and_original_is_kept(world, env):
    eng = login(world["op_eng"], world["a"])
    pid = env["passport"]["id"]
    er = req(eng, env["part"]["id"], [{"field": "rl1.part_size", "proposed": "Ø46 x 40.5 mm"}], passport=pid).json()
    assert er["data_class"] == "passport_draft" and er["base_revision_number"] == 1
    done = act(login(world["op_rev"], world["a"]), er["id"], "approve").json()
    assert done["status"] == "applied" and done["applied_revision_number"] == 2
    revs = eng.get(f"/api/v1/passports/{pid}/revisions/").json()
    by = {r["revision_number"]: r for r in revs}
    assert by[1]["status"] == "superseded" and by[1]["content"]["rl1"]["part_size"] == "Ø45 x 40.5 mm"
    assert by[2]["status"] == "draft" and by[2]["content"]["rl1"]["part_size"] == "Ø46 x 40.5 mm"
    assert by[2]["content"]["rl2"]["manufacturing_spec"]["machine"] == "EOS M290"  # other content carried over
    p = eng.get(f"/api/v1/passports/{pid}/").json()
    assert p["manufacturing_eligibility"] == "not_eligible" and p["publication_state"] == "draft" and p["evidence_level"] == "none"


def test_approved_revision_is_never_mutated(world, env):
    pid = env["passport"]["id"]
    with tenant_context(world["a"]):  # stored state only; there is no approval API (OQ-35)
        PassportRevision.objects.filter(passport_id=pid).update(status="approved")
    c = login(world["a_admin"])
    er = req(c, env["part"]["id"], [{"field": "rl1.original_material_grade", "proposed": "CF8M"}], passport=pid).json()
    assert er["data_class"] == "passport_new_revision"
    done = act(login(world["op_rev"], world["a"]), er["id"], "approve").json()
    assert done["applied_revision_number"] == 2
    with tenant_context(world["a"]):
        r1 = PassportRevision.objects.get(passport_id=pid, revision_number=1)
        r2 = PassportRevision.objects.get(passport_id=pid, revision_number=2)
        assert r1.status == "approved" and r1.content["rl1"]["original_material_grade"] == "AISI 316L"
        assert r2.status == "draft" and r2.content["rl1"]["value_sources"]["original_material_grade"] == "client_submitted"
        r1.content = {"tampered": True}
        with pytest.raises(Exception), transaction.atomic():
            r1.save()


def test_stale_conflict_then_rebase(world, env):
    c = login(world["a_admin"])
    er = req(c, env["part"]["id"], [{"field": "name", "proposed": "Client name"}]).json()
    eng = login(world["op_eng"], world["a"])
    eng.patch(f"/api/v1/parts/{env['part']['id']}/", {"name": "Engineer name"}, format="json")  # newer data
    rev = login(world["op_rev"], world["a"])
    done = act(rev, er["id"], "approve").json()
    assert done["status"] == "conflict" and "Part name" in done["application_result"]
    assert eng.get(f"/api/v1/parts/{env['part']['id']}/").json()["name"] == "Engineer name"  # never silently overwritten
    assert done["changes"][0]["drifted"] is True and done["changes"][0]["current"] == "Engineer name"
    rb = act(c, er["id"], "rebase").json()
    assert rb["status"] == "submitted" and rb["changes"][0]["original"] == "Engineer name"
    assert act(rev, er["id"], "approve").json()["status"] == "applied"
    # unrelated changes since the request do not block it
    er2 = req(c, env["part"]["id"], [{"field": "application", "proposed": "Cooling"}]).json()
    eng.patch(f"/api/v1/parts/{env['part']['id']}/", {"description": "changed later"}, format="json")
    r = act(rev, er2["id"], "approve").json()
    assert r["status"] == "applied" and "left as they are" in r["application_result"]


def test_corrections_rejection_and_immutable_history(world, env):
    c = login(world["a_admin"])
    er = req(c, env["part"]["id"], [{"field": "dimensions", "proposed": "45"}]).json()
    rev = login(world["op_rev"], world["a"])
    assert act(rev, er["id"], "request-corrections").status_code == 400  # note required
    cr = act(rev, er["id"], "request-corrections", "Give units").json()
    assert cr["status"] == "corrections_requested" and "update" in c.get(f"/api/v1/edit-requests/{er['id']}/").json()["allowed_actions"]
    assert c.patch(f"/api/v1/edit-requests/{er['id']}/", {"changes": [{"field": "dimensions", "proposed": "Ø45 x 40 mm"}]}, format="json").status_code == 200
    assert act(c, er["id"], "submit").json()["status"] == "submitted"
    assert act(rev, er["id"], "reject").status_code == 400
    rj = act(rev, er["id"], "reject", "Drawing says otherwise").json()
    assert rj["status"] == "rejected" and rj["decision_reason"] == "Drawing says otherwise"
    assert [e["action"] for e in rj["events"]][-3:] == ["updated", "resubmitted", "rejected"]
    with tenant_context(world["a"]):
        obj = EditRequest.objects.get(pk=er["id"])
        obj.reason = "rewritten"
        with pytest.raises(Exception), transaction.atomic():
            obj.save()
        ev = EditRequestEvent.objects.filter(request_id=er["id"]).first()
        with pytest.raises(Exception), transaction.atomic():
            ev.delete()


def test_isolation_and_project_scope(world, env):
    er = req(login(world["a_admin"]), env["part"]["id"], [{"field": "name", "proposed": "n2"}]).json()
    b = login(world["b_admin"])
    assert b.get(f"/api/v1/edit-requests/{er['id']}/").status_code == 404
    assert req(b, env["part"]["id"], [{"field": "name", "proposed": "hijack"}]).status_code == 404
    assert b.get("/api/v1/edit-requests/").json()["count"] == 0
    eng = login(world["op_eng"], world["a"])
    p2 = eng.post("/api/v1/projects/", {"code": "P2", "name": "x"}, format="json").json()
    mid = Membership.objects.get(user=world["op_rev"], tenant=world["a"]).pk
    login(world["op_admin"]).put(f"/api/v1/clients/{world['a'].pk}/engineers/{mid}/access/", {"scope": "projects", "project_ids": [p2["id"]], "edit_reviewer": True},
                                 format="json")
    rev = login(world["op_rev"], world["a"])
    assert rev.get(f"/api/v1/edit-requests/{er['id']}/").status_code == 404
    assert act(rev, er["id"], "approve").status_code == 404


def test_protected_fields_cad_and_confidential_data(world, env):
    c = login(world["a_admin"])
    pid = env["passport"]["id"]
    for field in ("tenant", "origin", "source_part", "review_state", "status", "notes", "rl3.evidence", "rl1.value_sources"):
        r = req(c, env["part"]["id"], [{"field": field, "proposed": "x"}], passport=pid if "." in field or field == "notes" else None)
        assert r.status_code == 400 and r.json()["error"]["code"] == "field_not_editable", field
    fields = [f["field"] for f in c.get(f"/api/v1/edit-requests/fields/?part={env['part']['id']}&passport={pid}").json()]
    assert "notes" not in fields and not any("evidence" in f for f in fields)
    # evidence documents are references only and must belong to the part
    f = c.post("/api/v1/files/", {"part": env["part"]["id"], "file": SimpleUploadedFile("photo.pdf", PDF), "category": "other"}, format="multipart").json()
    er = req(c, env["part"]["id"], [{"field": "description", "proposed": "see photo"}], evidence_files=[f["id"]]).json()
    assert er["evidence_files"][0]["title"] == "photo.pdf"
    # no request can change files; the STEP master keeps one version
    assert len(c.get(f"/api/v1/files/{env['step']['id']}/versions/").json()) == 1
    # notification bodies carry field names only
    for _, body in titles(world["op_rev"]):
        assert "CONFIDENTIAL-NOTE" not in body and "EOS M290" not in body
    # values that are invalid for the passport are refused
    bad = req(c, env["part"]["id"], [{"field": "rl1.motion", "proposed": "spinning"}], passport=pid)
    assert bad.status_code == 400


def test_permissions_to_request(world, env):
    assert req(login(world["a_user"]), env["part"]["id"], [{"field": "name", "proposed": "x"}]).status_code == 403
    Membership.objects.filter(user=world["a_user"], tenant=world["a"]).update(part_submission_allowed=True)
    assert req(login(world["a_user"]), env["part"]["id"], [{"field": "name", "proposed": "x"}]).status_code == 201
    assert req(login(world["a_proc"]), env["part"]["id"], [{"field": "name", "proposed": "x"}]).status_code == 403
    assert req(login(world["a_admin"]), env["part"]["id"], [{"field": "name", "proposed": "Impeller"}]).json()["error"]["code"] == "no_change"
    assert req(login(world["a_admin"]), env["part"]["id"], [{"field": "name", "proposed": "y"}], reason="").status_code == 400


def test_disabled_by_default(settings, world, env):
    settings.EDIT_REQUESTS_ENABLED = False
    assert req(login(world["a_admin"]), env["part"]["id"], [{"field": "name", "proposed": "x"}]).status_code == 403
    with tenant_context(world["a"]):
        assert SparePart.objects.get(pk=env["part"]["id"]).name == "Impeller"
        assert DigitalPassport.objects.get(pk=env["passport"]["id"]).manufacturing_eligibility == "not_eligible"
