"""Draft manufacturing job sheets (CN-004, J1-J8 approved with amendments). Internal to Aries; clients see only
progress; one immutable passport revision as template; append-only revisions; QA/issue/release gated. PostgreSQL + RLS."""
import pytest
from django.db import connection, transaction

from apps.jobsheets.models import JobSheet, JobSheetRevision
from apps.passports.models import PassportRevision
from apps.servicerequests.models import RequestEnvelope
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Membership

from .conftest import make_user, login

BASE = {"request_type": "manufacturing", "quantity": 2, "required_date": "2030-01-01", "delivery_location": "Site A",
        "priority": "routine", "remarks": "Spare for overhaul."}
RL2 = {"manufacturing_solution": "L-PBF, stress relieved", "material_selection": "SS 316L", "ndt": "Visual; Dye penetrant (PT)",
       "applicable_standards": "ASTM F3184", "mtc_required": True,
       "mechanical_acceptance": [{"property": "tensile", "requirement": "≥ 485", "unit": "MPa", "standard": "ISO 6892-1"}],
       "manufacturing_spec": {"job_number": "OLD-1", "material": "316L", "feedstock": "316L powder 15-45 µm", "machine": "EOS M290",
                              "layer_thickness": "40 µm", "heat_treatment": "Stress relief 650 °C / 2 h", "printing_hours": 11.5,
                              "process_parameters": [{"name": "Laser power", "value": "285", "unit": "W"}]}}


@pytest.fixture
def on(settings, world):
    settings.CLIENT_PART_SUBMISSIONS_ENABLED = True
    from apps.tenancy.models import Role

    world["op_qa"] = make_user("op.qa@example.test", world["operator"], Role.OPERATOR_QA)
    Membership.objects.create(user=world["op_qa"], tenant=world["a"], role=Role.OPERATOR_QA)
    return world


@pytest.fixture
def enquiry(on):
    w = on
    eng = login(w["op_eng"], w["a"])
    proj = eng.post("/api/v1/projects/", {"code": "P1", "name": "Pumps"}, format="json").json()
    part = eng.post("/api/v1/parts/", {"part_number": "IMP-9", "name": "Impeller", "project": proj["id"], "original_material": "CF8M"},
                    format="json").json()
    passport = eng.post("/api/v1/passports/", {"part": part["id"], "initial_content": {"rl2": RL2}}, format="json").json()
    req = login(w["a_admin"]).post("/api/v1/requests/", {**BASE, "part": part["id"]}, format="json").json()
    with tenant_context(w["operator"]):
        env = RequestEnvelope.objects.get(reference=req["reference"])
    return {"part": part, "passport": passport, "request": req, "env": env, "project": proj}


def url(env, tail=""):
    return f"/api/v1/operator/requests/{env.pk}/jobsheet/{tail}"


def ack(w, env):
    r = login(w["op_eng"], w["a"]).post(f"/api/v1/operator/requests/{env.pk}/act/", {"action": "acknowledge"}, format="json")
    assert r.status_code == 200


def test_requires_acknowledged_enquiry_then_links_enquiry_part_and_passport_revision(on, enquiry):
    eng = login(on["op_eng"], on["a"])
    r = eng.post(url(enquiry["env"]), {}, format="json")
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_acknowledged"
    ack(on, enquiry["env"])
    r = eng.post(url(enquiry["env"]), {"job_reference": "A-2026-0457", "manufacturing_method": "L-PBF (laser powder bed fusion)"}, format="json")
    assert r.status_code == 201, r.content
    js = r.json()
    assert js["enquiry_reference"] == enquiry["request"]["reference"] and js["part_number"] == "IMP-9"
    assert js["passport_number"] == enquiry["passport"]["passport_number"] and js["passport_revision_number"] == 1
    assert js["passport_revision_status"] == "draft" and js["draft_reference"].startswith("JS-DRAFT-")
    assert js["job_reference"] == "A-2026-0457" and js["revision_number"] == 1 and js["status"] == "draft"
    # prefill: values from an unapproved passport draft are "proposed", empty ones "missing"; never "verified"
    assert js["content"]["spec"]["machine"] == "EOS M290" and js["sources"]["spec.machine"] == "proposed"
    assert js["sources"]["spec.machining"] == "missing"
    assert "verified" not in js["sources"].values()
    assert "job_number" not in js["content"]["spec"]  # the job reference is the job sheet's own
    assert js["deviations"] == [] and js["gates"]["release_to_production"] == "OQ-36"
    assert eng.post(url(enquiry["env"]), {}, format="json").json()["error"]["code"] == "job_sheet_exists"


def test_unique_aries_job_reference_across_clients(on, enquiry):
    ack(on, enquiry["env"])
    eng = login(on["op_eng"], on["a"])
    assert eng.post(url(enquiry["env"]), {"job_reference": "JS-DRAFT-1"}, format="json").json()["error"]["code"] == "invalid_job_reference"
    eng.post(url(enquiry["env"]), {"job_reference": "A-1"}, format="json")
    # client B with its own enquiry cannot reuse A-1
    Membership.objects.create(user=on["op_eng"], tenant=on["b"], role="operator_engineer")
    engb = login(on["op_eng"], on["b"])
    pb = engb.post("/api/v1/parts/", {"part_number": "B-1", "name": "x"}, format="json").json()
    rb = login(on["b_admin"]).post("/api/v1/requests/", {**BASE, "part": pb["id"]}, format="json").json()
    with tenant_context(on["operator"]):
        envb = RequestEnvelope.objects.get(reference=rb["reference"], client_tenant=on["b"])
    engb.post(f"/api/v1/operator/requests/{envb.pk}/act/", {"action": "acknowledge"}, format="json")
    r = engb.post(url(envb), {"job_reference": "A-1"}, format="json")
    assert r.status_code == 400 and r.json()["error"]["code"] == "duplicate_job_reference"
    with tenant_context(on["b"]):  # rolled back: no half-created job sheet
        from apps.servicerequests.models import ClientRequest

        assert ClientRequest.objects.get(reference=rb["reference"]).job_progress == ""


def test_revisions_deviations_and_passport_untouched(on, enquiry):
    ack(on, enquiry["env"])
    eng = login(on["op_eng"], on["a"])
    eng.post(url(enquiry["env"]), {}, format="json")
    with tenant_context(on["a"]):
        before = PassportRevision.objects.get(passport_id=enquiry["passport"]["id"], revision_number=1)
        before_content, before_updated = dict(before.content), before.updated_at
    r = eng.patch(url(enquiry["env"]), {"job_reference": "A-77", "manufacturing_method": "Hybrid: AM + CNC machining",
                                        "content": {"spec": {"material": "316L", "machine": "EOS M400", "printing_hours": 9.0},
                                                    "engineering_notes": "Use plate B.",
                                                    "deviation_reasons": {"spec.machine": "M290 booked"}},
                                        "change_summary": "Machine and hours"}, format="json")
    assert r.status_code == 200, r.content
    js = r.json()
    assert js["revision_number"] == 2 and js["sources"]["spec.machine"] == "entered" and js["sources"]["spec.feedstock"] == "proposed"
    dev = {d["field"]: d for d in js["deviations"]}
    assert dev["spec.machine"]["passport"] == "EOS M290" and dev["spec.machine"]["job"] == "EOS M400"
    assert dev["spec.machine"]["reason"] == "M290 booked" and "spec.printing_hours" in dev
    assert [x["revision_number"] for x in js["revisions"]] == [2, 1] and js["revisions"][0]["author"]
    with tenant_context(on["operator"]):  # full detail in the Aries audit trail
        from apps.audit.models import AuditEvent

        saved = AuditEvent.objects.filter(action="jobsheet.revision_saved").first()
        assert saved and saved.data["job_reference"] == "A-77" and saved.data["revision"] == 2
    old = eng.get(url(enquiry["env"], "revisions/1/")).json()
    assert old["content"]["spec"]["machine"] == "EOS M290" and old["job_reference"] == ""
    with tenant_context(on["a"]):
        after = PassportRevision.objects.get(passport_id=enquiry["passport"]["id"], revision_number=1)
        assert after.content == before_content and after.updated_at == before_updated
        # revisions are immutable in the database
        from apps.jobsheets.services import staff_access

        with staff_access():
            rev = JobSheetRevision.objects.get(revision_number=1)
            rev.change_summary = "rewritten"
            with pytest.raises(Exception), transaction.atomic():
                rev.save()


def test_material_change_uses_clone_and_marks_revalidation(on, enquiry):
    c = login(on["a_admin"])
    req = c.post("/api/v1/requests/", {**BASE, "part": enquiry["part"]["id"], "material_option": "proposed",
                                       "proposed_material": "Duplex 2205", "material_change_reason": "Chlorides",
                                       "new_part_number": "IMP-9-DX"}, format="json").json()
    with tenant_context(on["operator"]):
        env = RequestEnvelope.objects.get(reference=req["reference"])
    ack(on, env)
    js = login(on["op_eng"], on["a"]).post(url(env), {}, format="json").json()
    assert js["part_number"] == "IMP-9-DX" and js["source_part_number"] == "IMP-9"
    assert js["original_material"] == "CF8M" and js["proposed_material"] == "Duplex 2205"
    assert js["content"]["spec"]["material"] == "Duplex 2205" and js["sources"]["spec.material"] == "client_proposal"
    assert {"spec.feedstock", "spec.heat_treatment", "process_parameters", "quality.mechanical_acceptance"} <= set(js["revalidation_required"])
    assert js["passport_number"] == enquiry["passport"]["passport_number"]  # template = the original's cited revision


def test_clients_never_see_job_sheets_only_progress(on, enquiry):
    ack(on, enquiry["env"])
    login(on["op_eng"], on["a"]).post(url(enquiry["env"]), {"job_reference": "SECRET-1"}, format="json")
    for who in ("a_admin", "a_eng", "a_user"):
        c = login(on[who])
        assert c.get(url(enquiry["env"])).status_code == 403
        body = c.get(f"/api/v1/requests/{enquiry['request']['id']}/").json()
        assert body["job_progress"] == "preparing"
        text = str(body)
        assert "SECRET-1" not in text and "EOS M290" not in text and "JS-DRAFT" not in text
        assert any(e["event"] == "job_preparation" for e in body["events"])
    # client audit trail has no confidential detail
    audit = login(on["a_admin"]).get("/api/v1/audit-events/?page_size=200").json()["results"]
    assert not any("SECRET-1" in str(e) or "JS-DRAFT" in str(e) for e in audit)
    # database layer: without the job-sheet access flag the rows are invisible even in the right tenant
    with tenant_context(on["a"]):
        assert JobSheet.objects.count() == 0 and JobSheetRevision.objects.count() == 0
        with connection.cursor() as cur:
            cur.execute("select count(*) from jobsheets_jobsheet")
            assert cur.fetchone()[0] == 0


def test_tenant_and_project_isolation(on, enquiry):
    ack(on, enquiry["env"])
    login(on["op_eng"], on["a"]).post(url(enquiry["env"]), {}, format="json")
    # another company's staff session and an unassigned engineer cannot reach it
    other = make_user("other.eng@example.test", on["operator"], "operator_engineer")
    assert login(other).get(url(enquiry["env"])).json()["error"]["code"] == "not_assigned"
    with tenant_context(on["b"]):
        from apps.jobsheets.services import staff_access

        with staff_access():
            assert JobSheet.objects.count() == 0  # RLS: client B context sees nothing even with the flag
    # project-limited engineer outside P1
    p2 = login(on["op_eng"], on["a"]).post("/api/v1/projects/", {"code": "P2", "name": "x"}, format="json").json()
    mid = Membership.objects.get(user=on["op_eng"], tenant=on["a"]).pk
    login(on["op_admin"]).put(f"/api/v1/clients/{on['a'].pk}/engineers/{mid}/access/", {"scope": "projects", "project_ids": [p2["id"]]}, format="json")
    assert login(on["op_eng"], on["a"]).get(url(enquiry["env"])).json()["error"]["code"] == "not_assigned_project"


def test_roles_and_gates(on, enquiry):
    ack(on, enquiry["env"])
    eng = login(on["op_eng"], on["a"])
    eng.post(url(enquiry["env"]), {}, format="json")
    qa = login(on["op_qa"], on["a"])
    assert qa.get(url(enquiry["env"])).status_code == 200  # QA may read
    assert qa.patch(url(enquiry["env"]), {"content": {"engineering_notes": "x"}}, format="json").status_code == 403
    assert login(on["op_admin"]).get(url(enquiry["env"])).status_code == 403  # Aries Admin: no engineering access
    for gate in ("submit", "issue", "release"):
        r = eng.post(url(enquiry["env"], f"{gate}/"), {}, format="json")
        assert r.status_code == 409 and r.json()["error"]["code"] == "policy_not_configured"
    # the passport stays not eligible; no production order or release exists
    p = eng.get(f"/api/v1/passports/{enquiry['passport']['id']}/").json()
    assert p["manufacturing_eligibility"] == "not_eligible" and p["publication_state"] == "draft"
    r = eng.post(url(enquiry["env"], "cancel/"), {"reason": "Client withdrew"}, format="json").json()
    assert r["status"] == "cancelled"
    assert login(on["a_admin"]).get(f"/api/v1/requests/{enquiry['request']['id']}/").json()["job_progress"] == "cancelled"
    assert eng.patch(url(enquiry["env"]), {"content": {}}, format="json").json()["error"]["code"] == "not_draft"
