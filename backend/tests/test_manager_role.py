"""Aries Manager (operator_manager): platform administration like the Aries Admin, without the audit trail, and never
over an Aries Admin (only an Admin creates, approves, changes or deactivates another Admin)."""
import pytest

from apps.accounts.models import User
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Membership, Role, Tenant

from .conftest import login, make_user
from .test_registration_access import NEW_PASSWORD, STAFF, anon, enabled, link_token, registrations, staff_request, unread_titles  # noqa: F401


@pytest.fixture
def mw(world):
    world["op_mgr"] = make_user("op.mgr@example.test", world["operator"], Role.OPERATOR_MANAGER)
    world["op_mgr2"] = make_user("op.mgr2@example.test", world["operator"], Role.OPERATOR_MANAGER)
    return world


def mid(user, tenant) -> str:
    return str(Membership.objects.get(user=user, tenant=tenant).pk)


def test_manager_has_admin_capabilities_except_audit(mw):
    caps = set(login(mw["op_mgr"]).get("/api/v1/auth/me/").json()["capabilities"])
    admin_caps = set(login(mw["op_admin"]).get("/api/v1/auth/me/").json()["capabilities"])
    assert {"registrations.review", "users.view", "users.manage", "clients.view", "clients.manage", "assignments.manage"} <= caps
    assert "audit.view" in admin_caps and "audit.view" not in caps
    assert caps == admin_caps - {"audit.view"}
    assert login(mw["op_mgr"]).get("/api/v1/audit-events/").status_code == 403


def test_manager_creates_staff_but_never_an_admin(mw):
    mgr = login(mw["op_mgr"])
    ok = mgr.post("/api/v1/users/", {"email": "new.eng@example.test", "role": "operator_engineer", "password": "x" * 16}, format="json")
    assert ok.status_code == 201, ok.content
    ok = mgr.post("/api/v1/users/", {"email": "new.mgr@example.test", "role": "operator_manager", "password": "x" * 16}, format="json")
    assert ok.status_code == 201, ok.content
    bad = mgr.post("/api/v1/users/", {"email": "new.admin@example.test", "role": "operator_admin", "password": "x" * 16}, format="json")
    assert bad.status_code == 403 and bad.json()["error"]["code"] == "role_not_allowed"
    assert not User.objects.filter(email="new.admin@example.test").exists()
    # the Aries Admin can still create another Admin
    r = login(mw["op_admin"]).post("/api/v1/users/", {"email": "second.admin@example.test", "role": "operator_admin", "password": "x" * 16},
                                   format="json")
    assert r.status_code == 201, r.content


def test_manager_cannot_change_or_deactivate_an_admin_or_promote_to_admin(mw):
    mgr, op = login(mw["op_mgr"]), mw["operator"]
    for body in ({"is_active": False}, {"role": "operator_engineer"}):
        r = mgr.patch(f"/api/v1/users/{mid(mw['op_admin'], op)}/", body, format="json")
        assert r.status_code == 404, body  # Aries Admins are not even listed for a Manager
    r = mgr.patch(f"/api/v1/users/{mid(mw['op_eng'], op)}/", {"role": "operator_admin"}, format="json")
    assert r.status_code == 403 and r.json()["error"]["code"] == "role_not_allowed"
    # other staff, including another manager, are managed by the manager
    assert mgr.patch(f"/api/v1/users/{mid(mw['op_eng'], op)}/", {"role": "operator_qa"}, format="json").status_code == 200
    assert mgr.patch(f"/api/v1/users/{mid(mw['op_mgr2'], op)}/", {"is_active": False}, format="json").status_code == 200
    rows = {r["email"]: r for r in mgr.get("/api/v1/users/").json()["results"]}
    assert "op.admin@example.test" not in rows and rows["op.eng@example.test"]["can_manage"] is True
    # the Admin manages managers
    assert login(mw["op_admin"]).patch(f"/api/v1/users/{mid(mw['op_mgr'], op)}/", {"role": "operator_engineer"},
                                       format="json").status_code == 200


def _verified_staff_request(mailoutbox, role, email):
    assert staff_request({**STAFF, "email": email, "requested_role": role}).status_code == 202
    token = link_token(mailoutbox[-1], "register/verify")
    assert anon().post(f"/api/v1/public/registrations/verify/{token}/", {"password": NEW_PASSWORD}, format="json").status_code == 200
    return next(r for r in registrations() if r.email == email)


def test_manager_can_be_requested_and_approved_and_approves_staff(mw, enabled, mailoutbox):  # noqa: F811
    offered = {o["value"]: o["label"] for o in anon().get("/api/v1/public/registration-config/").json()["staff_roles"]}
    assert offered["operator_manager"] == "Aries Manager" and "operator_admin" not in offered
    op = Tenant.objects.get(kind="operator")

    reg = _verified_staff_request(mailoutbox, "operator_manager", "mia@aries-staff.test")
    assert any("New Aries staff request" in t for t in unread_titles(mw["op_mgr"]))  # managers are notified too
    r = login(mw["op_mgr"]).post(f"/api/v1/registrations/{reg.pk}/approve/", {}, format="json")
    assert r.status_code == 200, r.content
    with tenant_context(op):
        assert Membership.objects.get(user__email="mia@aries-staff.test", tenant=op).role == "operator_manager"

    for role in ("operator_engineer", "operator_qa", "operator_support"):
        reg = _verified_staff_request(mailoutbox, role, f"{role}@aries-staff.test")
        bad = login(mw["op_mgr"]).post(f"/api/v1/registrations/{reg.pk}/approve/", {"role": "operator_admin"}, format="json")
        assert bad.status_code == 400 and bad.json()["error"]["code"] == "role_not_allowed"
        assert login(mw["op_mgr"]).post(f"/api/v1/registrations/{reg.pk}/approve/", {}, format="json").status_code == 200
        with tenant_context(op):
            assert Membership.objects.get(user__email=f"{role}@aries-staff.test", tenant=op).role == role
