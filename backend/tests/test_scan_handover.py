"""Post-UAT Phase 3 (D-05, D-15): scanning requests carry a project (chosen by the client or linked by Aries), the intake list
applies the same project rule as opening a request, a responsible engineer is assigned, deliverables are recorded append-only
and the scanned part is handed over into the passport workflow. Clients never see staff names (D-12)."""
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.projects.models import EngineerAccess, Project, ProjectAssignment
from apps.servicerequests.models import ScanDeliverable
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Membership, Role

from .conftest import login, make_user
from .test_passport_reports import STEP
from .test_service_requests import TOMORROW, envelope_for

SCAN = {"request_type": "digitisation", "site_location": "Plant 2", "part_description": "Worn bronze impeller", "reason": "obsolete",
        "preferred_date": TOMORROW, "contact_name": "A. Admin"}


def _scoped_engineer(world, email, project=None):
    u = make_user(email, world["operator"], Role.OPERATOR_ENGINEER)
    Membership.objects.create(user=u, tenant=world["a"], role=Role.OPERATOR_ENGINEER)
    with tenant_context(world["a"]):
        EngineerAccess.objects.create(tenant=world["a"], user=u, scope=EngineerAccess.Scope.PROJECTS)
        if project:
            ProjectAssignment.objects.create(tenant=world["a"], user=u, project_id=project, is_active=True)
    return u


def test_intake_list_and_opening_follow_the_same_project_rule(world):
    eng = login(world["op_eng"], world["a"])
    pumps = eng.post("/api/v1/projects/", {"code": "PUMPS", "name": "Pumps"}, format="json").json()
    client = login(world["a_admin"])
    with_project = client.post("/api/v1/requests/", {**SCAN, "project": pumps["id"]}, format="json")
    assert with_project.status_code == 201 and with_project.json()["project_code"] == "PUMPS"
    without = client.post("/api/v1/requests/", SCAN, format="json").json()
    bad = client.post("/api/v1/requests/", {**SCAN, "part_description": "Other part", "project": "00000000-0000-0000-0000-000000000000"},
                      format="json")
    assert bad.status_code == 400, bad.content

    on_pumps = login(_scoped_engineer(world, "eng.pumps@example.test", pumps["id"]), world["operator"])
    elsewhere = login(_scoped_engineer(world, "eng.other@example.test"), world["operator"])
    listed = {r["reference"]: r for r in on_pumps.get("/api/v1/operator/requests/").json()}
    assert with_project.json()["reference"] in listed and without["reference"] not in listed  # D-05: listed = openable
    assert on_pumps.get(f"/api/v1/operator/requests/{listed[with_project.json()['reference']]['id']}/").status_code == 200
    assert elsewhere.get("/api/v1/operator/requests/").json() == []
    company_wide = {r["reference"] for r in login(world["op_eng"], world["operator"]).get("/api/v1/operator/requests/").json()}
    assert {with_project.json()["reference"], without["reference"]} <= company_wide


def test_scanning_to_passport_handover(world):
    client = login(world["a_admin"])
    req = client.post("/api/v1/requests/", SCAN, format="json").json()
    env = envelope_for(world, req["reference"])
    op = login(world["op_eng"], world["operator"])
    act = lambda action, **kw: op.post(f"/api/v1/operator/requests/{env.pk}/act/", {"action": action, **kw}, format="json")  # noqa: E731
    act("acknowledge")
    with tenant_context(world["a"]):
        Project.objects.create(tenant=world["a"], code="EXIST", name="Existing project")
    detail = op.get(f"/api/v1/operator/requests/{env.pk}/").json()
    proj = next(p for p in detail["company_projects"] if p["code"] == "EXIST")
    assert act("link_project", project=proj["id"]).json()["project_code"] == "EXIST"
    assert act("link_project", project=proj["id"]).status_code == 409
    me = next(c for c in detail["engineer_candidates"] if c["email"] == world["op_eng"].email)
    assert act("assign", engineer=world["a_admin"].pk).status_code == 400  # not an Aries Engineer
    r = act("assign", engineer=me["id"])
    assert r.status_code == 200 and r.json()["responsible"]["email"] == world["op_eng"].email
    assert act("record_deliverable", deliverable_kind="scan_data", title="Mesh").status_code == 409  # not scheduled yet
    act("schedule")
    act("start")
    # the part for the scanned item, its CAD and passport are created with the normal engineering functions
    eng = login(world["op_eng"], world["a"])
    part = eng.post("/api/v1/parts/", {"part_number": f"{req['reference']}-01", "name": "Impeller (scanned)", "project": proj["id"]},
                    format="json").json()
    with tenant_context(world["a"]):
        from apps.servicerequests.models import ClientRequest

        ClientRequest.objects.filter(pk=req["id"]).update(created_part_id=part["id"])
    step = eng.post("/api/v1/files/", {"part": part["id"], "category": "3d_model", "file": SimpleUploadedFile("scan-cad.stp", STEP)},
                    format="multipart").json()
    assert act("record_deliverable", deliverable_kind="cad_model", title="Reverse-engineered CAD", file=step["id"]).status_code == 200
    assert act("record_deliverable", deliverable_kind="bogus", title="x").status_code == 400
    assert act("hand_over").status_code == 409  # not completed
    act("complete")
    assert act("hand_over").json()["error"]["code"] == "passport_required"
    passport = eng.post("/api/v1/passports/", {"part": part["id"]}, format="json").json()
    done = act("hand_over").json()
    assert done["handover"]["passport_number"] == passport["passport_number"] and done["handover"]["handed_over_at"]
    assert done["handover"]["deliverables"][0]["file_version"] == 1
    assert act("hand_over").status_code == 409

    mine = client.get(f"/api/v1/requests/{req['id']}/").json()
    assert mine["responsible"]["name"].startswith("Aries Engineering") and "email" not in mine["responsible"]
    assert mine["handover"]["passport_number"] == passport["passport_number"]
    assert mine["handover"]["deliverables"][0]["file"] is None  # the CAD is not released to the client
    names = {e["author_name"] for e in mine["events"] if e["author_side"] == "operator"}
    assert names == {"Aries Engineering"}  # D-12: no staff names for the client
    with tenant_context(world["a"]):
        assert ScanDeliverable.objects.filter(request_id=req["id"]).count() == 1
