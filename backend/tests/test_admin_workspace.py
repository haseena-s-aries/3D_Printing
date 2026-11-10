"""Aries Admin super-administrator workspaces (ADMIN_WORKSPACE_ENABLED; proposed OQ-37 / CN-002 D3 revision, access-test).

The Aries Admin works inside each client company through an audited `operator_admin` membership, so tenant isolation, RLS
and project scoping apply unchanged. It gains engineering-platform operations but no independent sign-off; passport
approval and manufacturing release stay closed; confidential file content stays closed per company until a documented
decision is configured; client roles are unchanged; with the switch off nothing of this exists."""
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.audit.models import AuditEvent
from apps.parts.models import SparePart
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Membership, Role
from apps.tenancy.permissions import ADMIN_WORKSPACE_GRANTS, capabilities_for

from .conftest import PASSWORD, login
from .test_files import upload
from .test_w2_catalog import jpeg_with_gps

SIGN_OFF = {"edits.review", "intelligence.review", "jobsheets.qa_review", "files.origin_confirm", "files.origin_claim"}


@pytest.fixture
def aw(world, settings):
    settings.ADMIN_WORKSPACE_ENABLED = True
    settings.ADMIN_FILE_ACCESS_DECISIONS = ""
    settings.PART_INTELLIGENCE_ENABLED = True
    settings.EDIT_REQUESTS_ENABLED = True
    settings.INVENTORY_IMPORT_ENABLED = True
    settings.CLIENT_PART_SUBMISSIONS_ENABLED = True
    settings.AI_CLIENT_ACCESS_ENABLED = True
    eng = login(world["op_eng"], world["a"])
    part = eng.post("/api/v1/parts/", {"part_number": "AW-100", "name": "Impeller"}, format="json").json()
    step = upload(eng, part["id"], "impeller.step", b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n", category="3d_model")
    photo = upload(eng, part["id"], "impeller.jpg", jpeg_with_gps(), category="photo").json()
    return {"w": world, "eng": eng, "part": part, "photo": photo, "step": step.json() if step.status_code == 201 else None}


def admin_in(world, tenant):
    return login(world["op_admin"], tenant)


def test_switched_off_the_admin_has_no_company_workspace(world, settings):
    settings.ADMIN_WORKSPACE_ENABLED = False
    from rest_framework.test import APIClient
    r = APIClient().post("/api/v1/auth/token/", {"email": "op.admin@example.test", "password": PASSWORD, "tenant": "client-a"}, format="json")
    assert r.status_code == 403
    assert not Membership.objects.filter(user=world["op_admin"], tenant__kind="client").exists()


def test_workspaces_are_created_audited_and_sign_in_stays_in_the_aries_workspace(aw):
    w = aw["w"]
    admin = login(w["op_admin"])
    assert admin.session_payload["tenant"]["slug"] == "operator"
    assert admin.session_payload["admin_access"]["can_enter_companies"] is True
    assert set(Membership.objects.filter(user=w["op_admin"], tenant__kind="client").values_list("tenant__slug", flat=True)) == {"client-a", "client-b"}
    slugs = {m["tenant"]["slug"] for m in admin.get("/api/v1/auth/memberships/").json()}
    assert {"operator", "client-a", "client-b"} <= slugs
    with tenant_context(w["a"]):
        assert AuditEvent.objects.filter(action="admin.workspace_membership_created").count() == 1
    with tenant_context(w["operator"]):
        assert AuditEvent.objects.filter(action="admin.workspace_membership_created").count() == 2
    r = admin.post("/api/v1/auth/switch/", {"tenant": "client-a", "refresh": admin.refresh_token}, format="json")
    access = r.json()["session"]["admin_access"]
    assert r.status_code == 200 and access["admin_workspace"] is True and access["file_decision"] == "" and access["aries_slug"] == "operator"


def test_capabilities_add_operations_but_no_sign_off_or_file_content(aw):
    w = aw["w"]
    login(w["op_admin"])  # provisions the workspaces
    m = Membership.objects.get(user=w["op_admin"], tenant=w["a"])
    caps = set(capabilities_for(m))
    assert {"parts.manage", "passports.edit_draft", "projects.manage", "intelligence.assess", "inventory.import", "jobsheets.prepare",
            "ai.share", "edits.request", "users.manage", "audit.view"} <= caps
    assert not caps & SIGN_OFF
    assert not caps & {"files.download_original", "files.download_derivative", "reports.generate_client", "reports.preview_client",
                       "reports.view_internal", "clients.manage", "inventory.admin_overview"}
    assert ADMIN_WORKSPACE_GRANTS - caps <= {"reports.generate_internal", "reports.view_internal", "reports.generate_client",
                                             "reports.download_client", "reports.preview_client"}  # file content: closed
    assert "parts.manage" not in capabilities_for(Membership.objects.get(user=w["a_admin"]))  # client roles unchanged
    op = set(capabilities_for(Membership.objects.get(user=w["op_admin"], tenant=w["operator"])))
    assert {"jobsheets.view", "jobsheets.prepare"} <= op and "jobsheets.qa_review" not in op and "parts.manage" not in op


def test_admin_operates_inside_one_company_without_touching_another(aw):
    w = aw["w"]
    a = admin_in(w, w["a"])
    proj = a.post("/api/v1/projects/", {"code": "ADM-P", "name": "Admin project"}, format="json")
    assert proj.status_code == 201
    part = a.post("/api/v1/parts/", {"part_number": "ADM-1", "name": "Admin-created part", "project": proj.json()["id"]}, format="json")
    assert part.status_code == 201
    pp = a.post("/api/v1/passports/", {"part": part.json()["id"]}, format="json")
    assert pp.status_code == 201, pp.content
    r = a.patch(f"/api/v1/passports/{pp.json()['id']}/revisions/1/", {"content": {"rl1": {"part_size": "Ø40 x 30 mm"}}}, format="json")
    assert r.status_code == 200, r.content
    assert a.get(f"/api/v1/parts/{aw['part']['id']}/").status_code == 200  # company A's engineer-created part
    with tenant_context(w["b"]):
        assert not SparePart.objects.filter(part_number__in=["ADM-1", "AW-100"]).exists()
    b = admin_in(w, w["b"])
    assert b.get(f"/api/v1/parts/{aw['part']['id']}/").status_code == 404  # company B's session cannot reach A's record
    with tenant_context(w["a"]):
        ev = AuditEvent.objects.filter(action__in=["spare_part.created", "part.created"], actor=w["op_admin"])
        assert ev.exists() or AuditEvent.objects.filter(actor=w["op_admin"], tenant=w["a"]).count() >= 3


def test_independent_sign_off_and_release_gates_hold(aw):
    w = aw["w"]
    a = admin_in(w, w["a"])
    pp = a.post("/api/v1/passports/", {"part": aw["part"]["id"]}, format="json").json()
    r = a.post(f"/api/v1/passports/{pp['id']}/revisions/1/approve/", {}, format="json")
    assert r.status_code in (403, 409)  # passport approval stays closed (OQ-35)
    assert a.post(f"/api/v1/parts/{aw['part']['id']}/feasibility/00000000-0000-0000-0000-000000000000/reviews/", {}, format="json").status_code == 403
    assert a.post(f"/api/v1/parts/{aw['part']['id']}/intelligence/classification/", {"category": "mechanical"}, format="json").status_code == 403
    assert a.post(f"/api/v1/edit-requests/00000000-0000-0000-0000-000000000000/approve/", {"note": "x"}, format="json").status_code in (403, 404)


def test_confidential_file_content_needs_a_documented_decision(aw, settings):
    w = aw["w"]
    a = admin_in(w, w["a"])
    photo = aw["photo"]
    files = a.get(f"/api/v1/files/?part={aw['part']['id']}").json()["results"]
    assert {f["title"] for f in files} >= {photo["title"]}  # metadata visible
    for variant in ("original", "preview"):
        assert a.post(f"/api/v1/files/{photo['id']}/versions/1/download-link/", {"variant": variant}, format="json").status_code == 403
    r = a.get(f"/api/v1/files/{photo['id']}/versions/1/thumbnail/")
    assert r.status_code == 403 and r.json()["error"]["code"] == "file_access_not_authorized"
    assert a.get(f"/api/v1/parts/{aw['part']['id']}/").json()["thumbnail"] is None
    # documented decision for company A only
    settings.ADMIN_FILE_ACCESS_DECISIONS = "client-a=SYN-FILE-DECISION-1"
    a = admin_in(w, w["a"])
    assert a.session_payload["admin_access"]["file_decision"] == "SYN-FILE-DECISION-1"
    assert a.get(f"/api/v1/files/{photo['id']}/versions/1/thumbnail/").status_code == 200
    assert a.post(f"/api/v1/files/{photo['id']}/versions/1/download-link/", {"variant": "original"}, format="json").status_code == 200
    m_b = Membership.objects.get(user=w["op_admin"], tenant=w["b"])
    assert "files.download_original" not in capabilities_for(m_b)


def test_client_roles_and_engineers_unchanged_by_the_switch(aw, settings):
    w = aw["w"]
    on = {who: capabilities_for(Membership.objects.get(user=w[who], tenant=w["a"])) for who in ("a_admin", "a_eng", "a_user", "a_proc", "op_eng")}
    settings.ADMIN_WORKSPACE_ENABLED = False
    off = {who: capabilities_for(Membership.objects.get(user=w[who], tenant=w["a"])) for who in on}
    assert on == off


def test_switching_off_again_closes_existing_workspaces(aw, settings):
    w = aw["w"]
    a = admin_in(w, w["a"])
    assert a.get("/api/v1/parts/").status_code == 200
    settings.ADMIN_WORKSPACE_ENABLED = False
    assert a.get("/api/v1/parts/").status_code == 401  # the membership is no longer usable
    admin = login(w["op_admin"])
    assert admin.post("/api/v1/auth/switch/", {"tenant": "client-a", "refresh": admin.refresh_token}, format="json").status_code == 403
    assert {m["tenant"]["slug"] for m in admin.get("/api/v1/auth/memberships/").json()} == {"operator"}


def test_admin_overview_opens_records_when_enabled(aw, settings):
    w = aw["w"]
    admin = login(w["op_admin"])
    body = admin.get("/api/v1/admin/inventory/", {"page_size": 50}).json()
    assert body["detail_access"]["enabled"] is True and all(r["client_slug"] for r in body["results"])
    settings.ADMIN_WORKSPACE_ENABLED = False
    assert admin.get("/api/v1/admin/inventory/", {"page_size": 50}).json()["detail_access"]["enabled"] is False


def test_platform_settings_are_read_only_for_the_aries_admin_and_hide_secrets(aw, settings):
    settings.GEMINI_API_KEY = "secret-value-never-returned"
    w = aw["w"]
    r = login(w["op_admin"]).get("/api/v1/admin/platform-settings/")
    assert r.status_code == 200 and "secret-value-never-returned" not in r.content.decode()
    keys = {s["key"]: s["on"] for s in r.json()["switches"]}
    assert keys["ADMIN_WORKSPACE_ENABLED"] is True and r.json()["ai"]["provider_configured"] is True
    for who in ("op_eng", "a_admin"):
        assert login(w[who], w["a"] if who == "op_eng" else None).get("/api/v1/admin/platform-settings/").status_code == 403
    assert admin_in(w, w["a"]).get("/api/v1/admin/platform-settings/").status_code == 403  # Aries workspace only


def test_workspaces_are_not_listed_or_counted_as_company_members(aw):
    w = aw["w"]
    admin = login(w["op_admin"])
    assert Membership.objects.filter(user=w["op_admin"], tenant=w["a"]).exists()
    clients = {c["slug"]: c for c in admin.get("/api/v1/clients/").json()["results"]}
    members = admin.get(f"/api/v1/clients/{w['a'].pk}/members/").json()
    assert all(m["role"] != Role.OPERATOR_ADMIN for m in members)
    assert clients["client-a"]["member_count"] == Membership.objects.filter(tenant=w["a"], is_active=True).exclude(role=Role.OPERATOR_ADMIN).count()
    users = login(w["a_admin"]).get("/api/v1/users/").json()
    rows = users["results"] if isinstance(users, dict) else users
    assert all(u.get("role") != Role.OPERATOR_ADMIN for u in rows)  # the company cannot list or deactivate it
    with tenant_context(w["a"]):  # but its creation is in the company's own audit trail
        assert AuditEvent.objects.filter(action="admin.workspace_membership_created").exists()
