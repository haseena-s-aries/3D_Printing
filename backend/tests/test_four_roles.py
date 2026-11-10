"""Four core roles (FOUR_ROLE_MODEL_ENABLED; AccessTest/FOUR-ROLE-MODEL.md).

Aries Admin, Aries Engineer, Client Admin, Client User. QA (CanPerformQA), engineering review (CanReviewEngineering =
edit_reviewer) and contract review (CanReviewContract) are permissions an Aries Admin gives selected Aries Engineers; Client
Users get feature permissions. Nobody verifies their own work, project and company scope still apply, objection review keeps
its separately designated authority, legacy roles keep their rights until mapped and are no longer assigned."""
import json

import pytest
from django.core.management import call_command

from apps.audit.models import AuditEvent
from apps.servicerequests.models import Notification
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Membership, Role
from apps.tenancy.permissions import capabilities_for

from .conftest import login, make_user
from .test_files import upload
from .test_thumbnail_provenance import auth_event, claim, contract_url, object_and_activate, origin, pv, qa, record_auth  # noqa: F401
from .test_w2_catalog import jpeg_with_gps

QUEUE = "/api/v1/files/origin-claims/"


@pytest.fixture
def fr(pv, settings):
    settings.FOUR_ROLE_MODEL_ENABLED = True
    return pv


def membership(user, tenant):
    return Membership.objects.get(user=user, tenant=tenant)


def access_url(w, m):
    return f"/api/v1/clients/{w['a'].pk}/engineers/{m.pk}/access/"


def grant_qa(fr, email="op.eng2@example.test", on=True, scope="company", project_ids=()):
    w = fr["w"]
    m = Membership.objects.get(user__email=email, tenant=w["a"])
    return fr["admin"].put(access_url(w, m), {"scope": scope, "project_ids": list(project_ids), "qa_permitted": on}, format="json")


def caps(client):
    return set(client.get("/api/v1/auth/me/").json()["capabilities"])


# ----------------------------------------------------------------------------------------------------- Aries side
def test_engineer_without_qa_permission_sees_and_does_no_qa(fr):
    claim(fr)
    assert "files.origin_confirm" not in caps(fr["eng2"])
    assert fr["eng2"].get(QUEUE).status_code == 403
    r = qa(fr, who="eng2")
    assert r.status_code == 403 and r.json()["error"]["code"] == "permission_denied"
    assert fr["eng2"].get(origin(None, fr["photos"]["SC-100"])).json()["can"]["confirm"] is False


def test_admin_grants_qa_and_the_engineer_verifies_independently(fr):
    claim(fr)
    r = grant_qa(fr)
    assert r.status_code == 200 and r.json()["qa_permitted"] is True
    assert "files.origin_confirm" in caps(fr["eng2"])  # same session: rights are recomputed per request
    assert [x["part_number"] for x in fr["eng2"].get(QUEUE).json()["results"]] == ["SC-100"]
    r = qa(fr, who="eng2")
    assert r.status_code == 201 and r.json()["state"] == "confirmed"
    assert r.json()["history"][0]["role"] == "Aries Engineer (QA)"
    w = fr["w"]
    with tenant_context(w["a"]):
        ev = AuditEvent.objects.get(action="membership.permissions_changed")
        assert ev.data["changes"] == {"qa_permitted": True} and ev.actor_email == "op.admin@example.test"
    with tenant_context(w["operator"]):
        assert AuditEvent.objects.filter(action="membership.permissions_changed", data__client="client-a").count() == 1
    assert Notification.objects.filter(recipient__email="op.eng2@example.test", body__contains="QA: given").exists()


def test_a_qa_engineer_cannot_verify_their_own_work(fr):
    w = fr["w"]
    grant_qa(fr, email="op.eng@example.test")  # the uploader and claimant also holds QA permission
    assert claim(fr).status_code == 201
    r = qa(fr, who="eng")
    assert r.status_code == 403 and r.json()["error"]["code"] == "self_verification"
    assert fr["eng"].get(origin(None, fr["photos"]["SC-100"])).json()["can"]["confirm"] is False
    assert fr["eng"].get(QUEUE).json()["results"][0]["own_claim"] is True
    # contract work: the recorder can never verify; an engineer with contract review permission can
    eng_op = membership(w["op_eng"], w["operator"])
    assert fr["admin"].patch(f"/api/v1/users/{eng_op.pk}/", {"contract_reviewer": True}, format="json").status_code == 200
    aid = record_auth(fr).json()["authorization"]["id"]
    assert auth_event(fr, aid, "verify", who="admin").json()["error"]["code"] == "self_verification"
    fr["eng_op"] = login(w["op_eng"], w["operator"])
    r = auth_event(fr, aid, "verify", who="eng_op")
    assert r.status_code == 201 and r.json()["status"] == "active"
    assert r.json()["authorization"]["events"][0]["by"].endswith("(Aries Engineer (contract reviewer))")


def test_revoking_qa_permission_takes_effect_on_the_next_request(fr):
    claim(fr)
    grant_qa(fr)
    assert fr["eng2"].get(QUEUE).status_code == 200
    r = grant_qa(fr, on=False)
    assert r.status_code == 200 and r.json()["qa_permitted"] is False
    assert fr["eng2"].get(QUEUE).status_code == 403  # same token, no new sign-in
    assert qa(fr, who="eng2").status_code == 403
    with tenant_context(fr["w"]["a"]):
        changes = [e.data["changes"] for e in AuditEvent.objects.filter(action="membership.permissions_changed").order_by("created_at")]
    assert changes == [{"qa_permitted": True}, {"qa_permitted": False}]


def test_qa_permission_respects_project_and_company_scope(fr):
    w = fr["w"]
    claim(fr)  # SC-100 is in project SCAN-1
    r = grant_qa(fr, scope="projects", project_ids=[fr["p2"]["id"]])  # QA limited to SCAN-2
    assert r.status_code == 200
    assert fr["eng2"].get(QUEUE).json()["results"] == []  # the queue no longer lists other projects' claims
    assert fr["eng2"].get(origin(None, fr["photos"]["SC-100"])).status_code == 404
    assert qa(fr, who="eng2").status_code == 404
    # company scope: QA permission in client A gives nothing in client B (no membership, no sign-in)
    from rest_framework.test import APIClient

    from .conftest import PASSWORD
    r = APIClient().post("/api/v1/auth/token/", {"email": "op.eng2@example.test", "password": PASSWORD, "tenant": "client-b"}, format="json")
    assert r.status_code == 403
    # and the old company-wide QA account still sees everything (legacy role unchanged)
    assert [x["part_number"] for x in fr["qa"].get(QUEUE).json()["results"]] == ["SC-100"]


def test_qa_permission_never_confers_contract_or_objection_authority(fr, settings):
    w = fr["w"]
    eng_op = membership(w["op_eng"], w["operator"])
    fr["admin"].patch(f"/api/v1/users/{eng_op.pk}/", {"qa_permitted": True}, format="json")
    eng_home = login(w["op_eng"], w["operator"])
    assert "jobsheets.qa_review" in caps(eng_home) and not {"contracts.thumbnail_view", "contracts.objection_review"} & caps(eng_home)
    assert eng_home.get(contract_url(fr)).status_code == 403
    # contract review permission without the deployment designation: verification yes, objection review no
    fr["admin"].patch(f"/api/v1/users/{eng_op.pk}/", {"contract_reviewer": True}, format="json")
    assert {"contracts.thumbnail_view", "contracts.thumbnail_verify"} <= caps(eng_home)
    assert "contracts.objection_review" not in caps(eng_home)
    aid = object_and_activate(fr)
    r = eng_home.post(f"{contract_url(fr)}{aid}/events/", {"action": "review", "outcome": "proceed", "note": "x" * 40}, format="json")
    assert r.status_code == 403 and r.json()["error"]["code"] == "no_review_authority"
    # designated as well: still refused here, because this engineer uploaded and claimed a covered photo
    settings.CONTRACT_OBJECTION_REVIEWERS = ["op.gov@example.test", "op.eng@example.test"]
    assert "contracts.objection_review" in caps(eng_home)
    r = eng_home.post(f"{contract_url(fr)}{aid}/events/", {"action": "review", "outcome": "proceed", "note": "x" * 40}, format="json")
    assert r.status_code == 403 and r.json()["error"]["code"] == "not_independent"


def test_only_an_aries_admin_assigns_aries_permissions(fr):
    w = fr["w"]
    eng_a = membership(w["op_eng"], w["a"])
    # the client administrator cannot touch Aries staff, and nobody changes their own permissions
    r = fr["a_admin"].patch(f"/api/v1/users/{eng_a.pk}/", {"qa_permitted": True}, format="json")
    assert r.status_code == 403
    admin_m = membership(w["op_admin"], w["operator"])
    assert fr["admin"].patch(f"/api/v1/users/{admin_m.pk}/", {"contract_reviewer": True}, format="json").status_code == 400
    # only Aries Engineers hold these permissions
    a_user = membership(w["a_user"], w["a"])
    r = fr["admin"].patch(f"/api/v1/clients/{w['a'].pk}/members/{a_user.pk}/", {"qa_permitted": True}, format="json")
    assert r.status_code == 400 and r.json()["error"]["code"] == "not_engineer"
    r = fr["admin"].patch(f"/api/v1/clients/{w['a'].pk}/members/{eng_a.pk}/", {"contract_reviewer": True}, format="json")
    assert r.status_code == 400 and r.json()["error"]["code"] == "not_applicable"  # contract review lives in the Aries organisation


def test_switched_off_nothing_changes(pv, settings):
    settings.FOUR_ROLE_MODEL_ENABLED = False
    w = pv["w"]
    m = membership(w["op_eng"], w["a"])
    m.qa_permitted = True
    m.save()
    assert "files.origin_confirm" not in capabilities_for(m)
    r = pv["admin"].put(access_url(w, m), {"scope": "company", "qa_permitted": True}, format="json")
    assert r.status_code == 400 and r.json()["error"]["code"] == "not_available"
    r = login(w["a_admin"]).post("/api/v1/invitations/", {"email": "new.proc@example.test", "role": "procurement"}, format="json")
    assert r.status_code == 201  # legacy roles are still offered while the switch is off


# ----------------------------------------------------------------------------------------------------- client side
def test_client_user_feature_permissions(fr, settings):
    settings.PART_INTELLIGENCE_ENABLED = settings.AI_CLIENT_ACCESS_ENABLED = True  # AI rights are switched features
    w = fr["w"]
    a_admin = fr["a_admin"]
    user = login(w["a_user"])
    m = membership(w["a_user"], w["a"])
    base = caps(user)
    assert {"files.download_derivative", "reports.preview_client"} <= base  # default document access: previews (as before)
    assert not {"audit.view", "requests.create", "files.upload_supporting", "files.download_original"} & base
    assert user.get("/api/v1/audit-events/").status_code == 403

    def set_(**body):
        r = a_admin.patch(f"/api/v1/users/{m.pk}/", body, format="json")
        assert r.status_code == 200, r.content
        return r.json()

    set_(audit_access=True)
    assert user.get("/api/v1/audit-events/").status_code == 200
    assert set_(technical_access=True)["technical_access"] is True
    assert {"files.upload_supporting", "requests.create", "passports.view_engineering_notes"} <= caps(user)
    set_(procurement_access=True)
    assert {"ai.prices", "ai.reports"} <= caps(user)
    set_(document_access="full")
    assert {"files.download_original", "reports.generate_client"} <= caps(user)
    set_(document_access="none", technical_access=False, procurement_access=False, audit_access=False)
    after = caps(user)
    assert not {"files.download_derivative", "reports.preview_client", "audit.view", "requests.create"} & after
    assert user.get("/api/v1/audit-events/").status_code == 403
    with tenant_context(w["a"]):
        ev = AuditEvent.objects.filter(action="membership.updated", object_id=str(m.pk)).latest("created_at")
        assert ev.data["after"]["document_access"] == "none" and ev.data["before"]["document_access"] == "full"
    # nobody sets their own features; features are for Client Users only; other companies cannot touch them
    r = user.patch(f"/api/v1/users/{m.pk}/", {"audit_access": True}, format="json")
    assert r.status_code == 403
    admin_m = membership(w["a_admin"], w["a"])
    r = fr["admin"].patch(f"/api/v1/clients/{w['a'].pk}/members/{admin_m.pk}/", {"technical_access": True}, format="json")
    assert r.status_code == 400 and r.json()["error"]["code"] == "not_applicable"
    assert fr["b_admin"].patch(f"/api/v1/users/{m.pk}/", {"audit_access": True}, format="json").status_code == 404
    # the Aries Admin may set them too
    r = fr["admin"].patch(f"/api/v1/clients/{w['a'].pk}/members/{m.pk}/", {"procurement_access": True}, format="json")
    assert r.status_code == 200 and r.json()["procurement_access"] is True


def test_only_the_four_roles_are_assigned(fr):
    w = fr["w"]
    a_admin = fr["a_admin"]
    for role in ("client_engineer", "procurement", "auditor"):
        r = a_admin.post("/api/v1/invitations/", {"email": f"new.{role}@example.test", "role": role}, format="json")
        assert r.status_code in (400, 403), (role, r.content)
    assert a_admin.post("/api/v1/invitations/", {"email": "new.user@example.test", "role": "client_user"}, format="json").status_code == 201
    a_user = membership(w["a_user"], w["a"])
    r = a_admin.patch(f"/api/v1/users/{a_user.pk}/", {"role": "procurement"}, format="json")
    assert r.status_code == 403 and r.json()["error"]["code"] == "role_not_allowed"
    qa_user = make_user("op.newqa@example.test", w["operator"], Role.OPERATOR_ENGINEER)
    r = fr["admin"].post(f"/api/v1/clients/{w['a'].pk}/members/", {"email": qa_user.email, "role": "operator_qa"}, format="json")
    assert r.status_code == 403 and r.json()["error"]["code"] == "role_not_allowed"
    r = fr["admin"].post("/api/v1/users/", {"email": "op.x@example.test", "role": "operator_support", "password": "x" * 16}, format="json")
    assert r.status_code == 403
    # existing legacy memberships keep exactly their rights and stay listed as legacy
    eng = membership(w["a_eng"], w["a"])
    listed = {x["email"]: x for x in a_admin.get("/api/v1/users/").json()["results"]}
    assert listed["a.eng@example.test"]["legacy_role"] is True and listed["a.user@example.test"]["legacy_role"] is False
    assert "files.download_original" in capabilities_for(eng)
    assert login(w["a_eng"]).session_payload["role_model"] == "four_roles"


# ----------------------------------------------------------------------------------------------------- mapping
def test_mapping_dry_run_changes_nothing_and_apply_keeps_ids_and_history(fr, tmp_path):
    w = fr["w"]
    before = {m.pk: (m.user_id, m.role) for m in Membership.objects.all()}
    out = tmp_path / "plan.json"
    call_command("four_role_mapping", json=str(out))
    assert {m.pk: (m.user_id, m.role) for m in Membership.objects.all()} == before
    plan = {(r["email"], r["company"]): r for r in json.loads(out.read_text())["rows"]}
    assert plan[("a.eng@example.test", "client-a")]["status"] == "equivalent"
    assert plan[("a.proc@example.test", "client-a")]["status"] == "equivalent"
    data = json.loads(out.read_text())
    assert data["with_differences"] == 0  # no right gained or lost by any membership (R1 resolved)
    qa_row = plan[("op.qa@example.test", "client-a")]
    assert qa_row["gained"] == [] and qa_row["lost"] == [] and qa_row["permissions"]["engineering_authoring"] is False
    eng_caps = capabilities_for(membership(w["a_eng"], w["a"]))
    qa_m = Membership.objects.get(user__email="op.qa@example.test", tenant=w["a"])
    with pytest.raises(Exception):
        call_command("four_role_mapping", apply=True)  # --confirm is required
    call_command("four_role_mapping", apply=True, confirm=True)
    qa_after = Membership.objects.get(pk=qa_m.pk)
    assert qa_after.role == Role.OPERATOR_ENGINEER and qa_after.qa_permitted and not qa_after.engineering_authoring
    assert qa_after.user_id == qa_m.user_id
    eng_after = membership(w["a_eng"], w["a"])
    assert eng_after.role == Role.CLIENT_USER and set(capabilities_for(eng_after)) == set(eng_caps)
    assert not Membership.objects.filter(role__in=["operator_qa", "client_engineer", "procurement"]).exists()
    with tenant_context(w["a"]):
        assert AuditEvent.objects.filter(action="membership.role_mapped").count() == 3  # Client Engineer, Procurement, QA
    # history keeps the role recorded at the time; the mapped QA account still confirms (now as an engineer with QA)
    claim(fr)
    r = qa(fr)
    assert r.status_code == 201 and r.json()["history"][0]["role"] == "Aries Engineer (QA)"
    # ... and gained no engineering authoring
    r = fr["qa"].post("/api/v1/parts/", {"part_number": "QA-NEW", "name": "Should be refused"}, format="json")
    assert r.status_code == 403


# ----------------------------------------------------------------------------------------------------- authoring vs QA
def set_access(fr, email, **perms):
    w = fr["w"]
    m = Membership.objects.get(user__email=email, tenant=w["a"])
    r = fr["admin"].put(access_url(w, m), {"scope": "company", **perms}, format="json")
    assert r.status_code == 200, r.content
    return r.json()


def test_engineering_authoring_and_qa_are_independently_controlled(fr):
    from apps.parts.models import SparePart
    from apps.parts.submissions import reviewers

    claim(fr)
    eng2 = fr["eng2"]
    # QA only: verifies, but cannot author
    row = set_access(fr, "op.eng2@example.test", qa_permitted=True, engineering_authoring=False)
    assert row["qa_permitted"] is True and row["engineering_authoring"] is False
    assert eng2.post("/api/v1/parts/", {"part_number": "E2-1", "name": "x"}, format="json").status_code == 403
    assert "files.upload" not in caps(eng2) and "intelligence.view" not in caps(eng2)
    assert qa(fr, who="eng2").status_code == 201
    w = fr["w"]
    with tenant_context(w["a"]):  # QA-only engineers are not notified of client submissions
        part = SparePart.objects.first()
        assert "op.eng2@example.test" not in {u.email for u in reviewers(part)}
    # authoring only: engineering work, no QA
    set_access(fr, "op.eng2@example.test", qa_permitted=False, engineering_authoring=True)
    assert eng2.post("/api/v1/parts/", {"part_number": "E2-2", "name": "x"}, format="json").status_code == 201
    assert "files.origin_confirm" not in caps(eng2) and eng2.get(QUEUE).status_code == 403
    with tenant_context(w["a"]):
        assert "op.eng2@example.test" in {u.email for u in reviewers(SparePart.objects.first())}
    # both off: read access only; revocation applies to the same session
    set_access(fr, "op.eng2@example.test", engineering_authoring=False)
    assert eng2.post("/api/v1/parts/", {"part_number": "E2-3", "name": "x"}, format="json").status_code == 403
    with tenant_context(w["a"]):
        ev = AuditEvent.objects.filter(action="membership.permissions_changed").order_by("created_at")
        assert [e.data["changes"] for e in ev] == [{"qa_permitted": True, "engineering_authoring": False},
                                                   {"qa_permitted": False, "engineering_authoring": True},
                                                   {"engineering_authoring": False}]


def test_qa_only_engineer_still_cannot_review_own_work_and_only_admin_sets_authoring(fr):
    w = fr["w"]
    set_access(fr, "op.eng@example.test", qa_permitted=True)  # uploader and claimant, engineering work still on
    claim(fr)
    r = qa(fr, who="eng")
    assert r.status_code == 403 and r.json()["error"]["code"] == "self_verification"
    eng_a = membership(w["op_eng"], w["a"])
    assert fr["a_admin"].patch(f"/api/v1/users/{eng_a.pk}/", {"engineering_authoring": False}, format="json").status_code == 403
    a_user = membership(w["a_user"], w["a"])
    r = fr["admin"].patch(f"/api/v1/clients/{w['a'].pk}/members/{a_user.pk}/", {"engineering_authoring": True}, format="json")
    assert r.status_code == 400 and r.json()["error"]["code"] == "not_engineer"
    eng_op = membership(w["op_eng"], w["operator"])
    r = fr["admin"].patch(f"/api/v1/users/{eng_op.pk}/", {"engineering_authoring": False}, format="json")
    assert r.status_code == 200 and r.json()["engineering_authoring"] is False
    body = login(w["op_eng"], w["operator"]).get("/api/v1/notifications/").json()  # notifications are readable by their recipient only
    items = body["results"] if isinstance(body, dict) else body
    assert any(n["title"] == "Engineering work permission removed" for n in items)
