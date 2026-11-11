"""Membership administration boundaries (W1 security fix, docs/web-review/w1-results.md §6).

Operator-owned staff are managed only by operator administrators; client administrators manage only their own
organisation's client users. All checks go through the API against PostgreSQL with RLS."""
import pytest
from django.db import transaction

from apps.audit.models import AuditEvent
from apps.tenancy.context import set_user_context, tenant_context
from apps.tenancy.models import Membership

from .conftest import PASSWORD, login
from .test_w2_security import token_of


def mid(user, tenant) -> str:
    return str(Membership.objects.get(user=user, tenant=tenant).pk)


def state(user, tenant):
    m = Membership.objects.get(user=user, tenant=tenant)
    return m.role, m.is_active


# ---- client administrator vs operator staff -------------------------------------------------------------------

@pytest.mark.parametrize("body", [
    {"role": "client_user"},
    {"role": "operator_qa"},
    {"is_active": False},
    {"is_active": "false"},          # crafted string boolean
    {"role": "operator_engineer", "is_active": False},
], ids=["to-client-role", "to-other-operator-role", "deactivate", "deactivate-string", "same-role-deactivate"])
def test_client_admin_cannot_modify_operator_staff(world, body):
    admin = login(world["a_admin"])
    before = state(world["op_eng"], world["a"])
    for method in (admin.patch, admin.put):
        r = method(f"/api/v1/users/{mid(world['op_eng'], world['a'])}/", body, format="json")
        assert r.status_code == 403, r.content
        assert r.json()["error"]["code"] == "operator_staff_managed_by_operator"
    assert state(world["op_eng"], world["a"]) == before


def test_users_list_marks_operator_staff_as_not_manageable(world):
    rows = {r["email"]: r for r in login(world["a_admin"]).get("/api/v1/users/").json()["results"]}
    assert rows["op.eng@example.test"]["managed_by"] == "operator" and rows["op.eng@example.test"]["can_manage"] is False
    assert rows["a.user@example.test"]["managed_by"] == "organisation" and rows["a.user@example.test"]["can_manage"] is True
    assert rows["a.admin@example.test"]["can_manage"] is False  # own membership


def test_client_admin_cannot_create_or_attach_accounts_directly(world):
    """Since W2 client admins invite; direct creation is refused whatever the address (no enumeration)."""
    admin = login(world["a_admin"])
    codes = set()
    for email in ("op.eng@example.test", "op.admin@example.test", "b.eng@example.test", "brand.new@example.test"):
        r = admin.post("/api/v1/users/", {"email": email, "role": "client_user", "password": "Long-Enough-Pass-123"}, format="json")
        assert r.status_code == 403, email
        codes.add((r.json()["error"]["code"], r.json()["error"]["message"]))
    assert codes == {("invitation_required", "Invite people by email instead (Users → Invite user).")}
    assert not Membership.objects.filter(tenant=world["a"], user__email__in=["op.eng@example.test", "b.eng@example.test"],
                                         role="client_user").exists()


# ---- client administrator vs another organisation, elevated roles, own privileges ------------------------------

def test_client_admin_cannot_reach_another_organisations_memberships(world):
    admin = login(world["a_admin"])
    for target in (mid(world["b_eng"], world["b"]), mid(world["op_admin"], world["operator"])):
        assert admin.patch(f"/api/v1/users/{target}/", {"is_active": False}, format="json").status_code == 404
        assert admin.get(f"/api/v1/users/{target}/").status_code == 404
    # The operator's client-administration endpoint is not available to client admins at all
    r = admin.patch(f"/api/v1/clients/{world['b'].pk}/members/{mid(world['b_eng'], world['b'])}/", {"is_active": False}, format="json")
    assert r.status_code == 403
    assert state(world["b_eng"], world["b"]) == ("client_engineer", True)
    assert state(world["op_admin"], world["operator"]) == ("operator_admin", True)


@pytest.mark.parametrize("role,status,code", [
    ("operator_admin", 403, "role_not_allowed"),
    ("operator_engineer", 403, "role_not_allowed"),
    ("superuser", 400, "validation_error"),
], ids=["operator-admin", "operator-engineer", "unknown-role"])
def test_client_admin_cannot_grant_elevated_roles(world, role, status, code):
    admin = login(world["a_admin"])
    r = admin.patch(f"/api/v1/users/{mid(world['a_user'], world['a'])}/", {"role": role}, format="json")
    assert r.status_code == status and r.json()["error"]["code"] == code
    r = admin.post("/api/v1/invitations/", {"email": f"new.{role}@example.test", "role": role}, format="json")
    assert r.status_code == status
    assert state(world["a_user"], world["a"]) == ("client_user", True)


def test_client_admin_cannot_change_own_privileges(world):
    admin = login(world["a_admin"])
    own = mid(world["a_admin"], world["a"])
    for body in ({"role": "client_user"}, {"is_active": False}, {"role": "operator_admin"}):
        r = admin.patch(f"/api/v1/users/{own}/", body, format="json")
        assert r.status_code == 400 and r.json()["error"]["code"] == "cannot_change_self"
    assert state(world["a_admin"], world["a"]) == ("client_admin", True)


@pytest.mark.parametrize("who", ["a_eng", "a_user", "a_proc"])
def test_non_admin_client_roles_cannot_manage_users(world, who):
    c = login(world[who])
    assert c.patch(f"/api/v1/users/{mid(world['a_user'], world['a'])}/", {"is_active": False}, format="json").status_code == 403
    assert c.post("/api/v1/users/", {"email": "x@example.test", "role": "client_user", "password": PASSWORD}, format="json").status_code == 403
    assert c.post("/api/v1/invitations/", {"email": "x@example.test", "role": "client_user"}, format="json").status_code == 403
    assert c.get("/api/v1/invitations/").status_code == 403


def test_operator_staff_other_than_admin_cannot_manage_memberships(world):
    eng = login(world["op_eng"], world["a"])  # operator engineer working in client A
    assert eng.patch(f"/api/v1/users/{mid(world['a_user'], world['a'])}/", {"is_active": False}, format="json").status_code == 403
    assert eng.patch(f"/api/v1/clients/{world['a'].pk}/members/{mid(world['a_user'], world['a'])}/", {"is_active": False}, format="json").status_code == 403


# ---- authorised workflows still work ---------------------------------------------------------------------------

def test_client_admin_manages_own_client_users(world, client):
    admin = login(world["a_admin"])
    r = admin.post("/api/v1/invitations/", {"email": "new.colleague@example.test", "role": "client_user"}, format="json")
    assert r.status_code == 201, r.content
    token = token_of(r)  # from the emailed link
    assert client.post(f"/api/v1/invitation-acceptance/{token}/", {"password": "Long-Enough-Pass-123"}, format="json").status_code == 200
    new = next(u["id"] for u in admin.get("/api/v1/users/").json()["results"] if u["email"] == "new.colleague@example.test")
    assert admin.patch(f"/api/v1/users/{new}/", {"role": "client_engineer"}, format="json").json()["role"] == "client_engineer"
    assert admin.patch(f"/api/v1/users/{new}/", {"is_active": False}, format="json").json()["is_active"] is False
    assert admin.patch(f"/api/v1/users/{new}/", {"is_active": True}, format="json").json()["is_active"] is True
    # promote an existing colleague to client administrator, then deactivate another client user
    assert admin.patch(f"/api/v1/users/{mid(world['a_eng'], world['a'])}/", {"role": "client_admin"}, format="json").status_code == 200
    assert admin.patch(f"/api/v1/users/{mid(world['a_user'], world['a'])}/", {"is_active": False}, format="json").status_code == 200
    with tenant_context(world["a"]):
        assert AuditEvent.objects.filter(action="membership.updated", actor_email="a.admin@example.test").count() == 5


def test_operator_admin_manages_operator_assignments_in_client(world, client):
    op = login(world["op_admin"])
    assignment = mid(world["op_eng"], world["a"])
    eng_in_a = login(world["op_eng"], world["a"])
    url = f"/api/v1/clients/{world['a'].pk}/members/{assignment}/"
    r = op.patch(url, {"role": "operator_qa"}, format="json")
    assert r.status_code == 200 and r.json()["role"] == "operator_qa" and r.json()["managed_by"] == "operator"
    # role family is kept; operator administration is not delegated into client organisations
    assert op.patch(url, {"role": "client_admin"}, format="json").json()["error"]["code"] == "role_family_change"
    assert op.patch(url, {"role": "operator_admin"}, format="json").json()["error"]["code"] == "role_not_allowed"
    assert op.patch(url, {"is_active": False}, format="json").status_code == 200
    assert eng_in_a.get("/api/v1/parts/").status_code == 401  # access to client A ends at once
    with tenant_context(world["a"]):
        assert AuditEvent.objects.filter(action="membership.updated", actor_email="op.admin@example.test").count() == 2
    # a membership id from another organisation cannot be addressed through this client
    other = f"/api/v1/clients/{world['a'].pk}/members/{mid(world['b_eng'], world['b'])}/"
    assert op.patch(other, {"is_active": False}, format="json").status_code == 404


def test_operator_admin_manages_operator_staff_in_operator_organisation(world):
    op = login(world["op_admin"])
    r = op.patch(f"/api/v1/users/{mid(world['op_eng'], world['operator'])}/", {"role": "operator_support"}, format="json")
    assert r.status_code == 200 and r.json()["role"] == "operator_support"
    assert op.patch(f"/api/v1/users/{mid(world['op_eng'], world['operator'])}/", {"role": "client_admin"}, format="json").status_code == 403


# ---- Aries role change on the Users page reaches the client assignments ------------------------------------------

def test_aries_role_change_applies_to_client_assignments(world):
    from apps.servicerequests.models import Notification

    eng, a, b = world["op_eng"], world["a"], world["b"]
    with tenant_context(b):  # inactive assignment in B: left as it is
        Membership.objects.create(user=eng, tenant=b, role="operator_engineer", is_active=False)
    with tenant_context(a):
        Membership.objects.filter(user=eng, tenant=a).update(edit_reviewer=True)
    admin = login(world["op_admin"])
    r = admin.patch(f"/api/v1/users/{mid(eng, world['operator'])}/", {"role": "operator_qa"}, format="json")
    assert r.status_code == 200, r.content
    assert r.json()["role"] == "operator_qa"
    with tenant_context(a):
        ma = Membership.objects.get(user=eng, tenant=a)
        assert (ma.role, ma.is_active, ma.edit_reviewer) == ("operator_qa", True, False)  # reviewer flag is for engineers only
        ev = AuditEvent.objects.filter(action="membership.updated", tenant=a).latest("created_at")
        assert ev.data["from_aries_role_change"] is True and ev.data["before"]["role"] == "operator_engineer"
    with tenant_context(b):
        assert state(eng, b) == ("operator_engineer", False)
    with transaction.atomic():  # notifications are readable by their recipient only (per-user RLS)
        set_user_context(eng.pk)
        note = Notification.objects.filter(recipient=eng, title__startswith="Role changed").values_list("body", flat=True).first()
    assert note and "Client A Energy" in note and "Client B Marine" not in note
    # the client company's own list shows the new role
    rows = {x["email"]: x for x in login(world["a_admin"]).get("/api/v1/users/").json()["results"]}
    assert rows["op.eng@example.test"]["role"] == "operator_qa"


def test_aries_admin_role_is_not_copied_to_client_assignments(world):
    eng, a = world["op_eng"], world["a"]
    admin = login(world["op_admin"])
    r = admin.patch(f"/api/v1/users/{mid(eng, world['operator'])}/", {"role": "operator_admin"}, format="json")
    assert r.status_code == 200, r.content
    with tenant_context(a):
        assert state(eng, a) == ("operator_engineer", True)  # Aries Admin is not a role inside a client company
