"""Cross-tenant isolation through the API and role-based permissions."""
import pytest
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.tenancy.context import tenant_context

from .conftest import login


def create_part(c, number="P-100", **extra):
    r = c.post("/api/v1/parts/", {"part_number": number, "name": "Bearing holder", **extra}, format="json")
    assert r.status_code == 201, r.content
    return r.json()


def test_parts_are_tenant_scoped(world):
    op_in_a = login(world["op_eng"], world["a"])
    part_a = create_part(op_in_a, "A-100")
    b_admin = login(world["b_admin"])
    assert b_admin.get("/api/v1/parts/").json()["results"] == []
    assert b_admin.get(f"/api/v1/parts/{part_a['id']}/").status_code == 404  # not 403: no existence leak
    assert b_admin.patch(f"/api/v1/parts/{part_a['id']}/", {"name": "x"}, format="json").status_code in (403, 404)
    a_user = login(world["a_user"])
    assert [p["part_number"] for p in a_user.get("/api/v1/parts/").json()["results"]] == ["A-100"]


def _assign_engineer_to_b(world):
    from apps.tenancy.models import Membership

    Membership.objects.create(user=world["op_eng"], tenant=world["b"], role="operator_engineer")
    return login(world["op_eng"], world["b"])


def test_same_part_number_allowed_in_different_tenants(world):
    create_part(login(world["op_eng"], world["a"]), "SAME-1")
    create_part(_assign_engineer_to_b(world), "SAME-1")


def test_aries_admin_has_no_engineering_edit(world):
    # CN-002: platform administration is separate from engineering edits (no parts, projects or passports).
    admin = login(world["op_admin"])
    assert admin.post("/api/v1/parts/", {"part_number": "ADM-1", "name": "x"}, format="json").status_code == 403
    assert admin.post("/api/v1/projects/", {"code": "ADM", "name": "x"}, format="json").status_code == 403


def test_tenant_field_in_body_is_ignored(world):
    c = login(world["op_eng"], world["a"])
    part = create_part(c, "A-200", tenant=str(world["b"].pk))
    with tenant_context(world["a"]):
        from apps.parts.models import SparePart

        assert SparePart.objects.get(pk=part["id"]).tenant_id == world["a"].pk


def test_cross_tenant_related_object_rejected(world):
    a = login(world["op_eng"], world["a"])
    proj_a = a.post("/api/v1/projects/", {"code": "PRJ-A", "name": "A project"}, format="json").json()
    eng_b = _assign_engineer_to_b(world)
    r = eng_b.post("/api/v1/parts/", {"part_number": "X1", "name": "x", "project": proj_a["id"]}, format="json")
    assert r.status_code == 400  # other tenant's project does not exist for this caller


def test_client_admin_cannot_manage_projects(world):
    # CN-002 D2: Aries Engineers manage digitisation projects; clients view them and submit requests.
    r = login(world["a_admin"]).post("/api/v1/projects/", {"code": "C-1", "name": "x"}, format="json")
    assert r.status_code == 403


@pytest.mark.parametrize("who,expected", [("a_user", 403), ("a_proc", 403), ("a_admin", 403), ("op_eng", 201)])
def test_part_creation_requires_role(world, who, expected):
    tenant = world["a"] if who == "op_eng" else None
    c = login(world[who], tenant)
    r = c.post("/api/v1/parts/", {"part_number": f"R-{who}", "name": "x"}, format="json")
    assert r.status_code == expected
    if expected == 403:
        assert r.json()["error"]["code"] == "permission_denied"


def test_users_endpoint_scoped_and_role_limited(world):
    a_admin = login(world["a_admin"])
    emails = {u["email"] for u in a_admin.get("/api/v1/users/").json()["results"]}
    assert "b.admin@example.test" not in emails and "a.eng@example.test" in emails
    # client admins invite instead of creating accounts (W2), and cannot grant operator roles either way
    r = a_admin.post("/api/v1/users/", {"email": "new@example.test", "role": "client_engineer", "password": "Another-Long-Pass-77"}, format="json")
    assert r.status_code == 403 and r.json()["error"]["code"] == "invitation_required"
    assert a_admin.post("/api/v1/invitations/", {"email": "new@example.test", "role": "operator_admin"}, format="json").status_code == 403
    a_eng_membership = next(u["id"] for u in a_admin.get("/api/v1/users/").json()["results"] if u["email"] == "a.eng@example.test")
    assert login(world["b_admin"]).get(f"/api/v1/users/{a_eng_membership}/").status_code == 404
    assert login(world["a_user"]).get("/api/v1/users/").status_code == 403


def test_cannot_change_own_role(world):
    a_admin = login(world["a_admin"])
    me = a_admin.get("/api/v1/auth/me/").json()["membership"]["id"]
    r = a_admin.patch(f"/api/v1/users/{me}/", {"is_active": False}, format="json")
    assert r.status_code == 400 and r.json()["error"]["code"] == "cannot_change_self"


def test_clients_only_for_operator_admin(world):
    assert login(world["a_admin"]).get("/api/v1/clients/").status_code == 403
    assert login(world["op_eng"], world["operator"]).get("/api/v1/clients/").status_code == 403
    op = login(world["op_admin"])
    r = op.post("/api/v1/clients/", {"name": "Client C", "slug": "client-c", "trade_licence_number": "TL-C",
                                     "licence_authority": "Synthetic Authority", "country": "United Arab Emirates", "state": "Dubai",
                                     "address": "Synthetic Street 1", "contact_name": "C Admin", "contact_title": "Manager",
                                     "contact_email": "c.admin@example.test", "contact_phone": "+971 50 000 0001",
                                     "invite_contact": False}, format="json")
    assert r.status_code == 201
    m = op.post(f"/api/v1/clients/{r.json()['id']}/members/", {"email": "c.admin@example.test", "role": "client_admin",
                                                                "password": "Client-C-Admin-Pass-1"}, format="json")
    assert m.status_code == 201
    r = APIClient().post("/api/v1/auth/token/", {"email": "c.admin@example.test", "password": "Client-C-Admin-Pass-1"}, format="json")
    assert r.status_code == 200 and r.json()["session"]["tenant"]["slug"] == "client-c"


def test_operator_assignment_requires_operator_staff(world):
    op = login(world["op_admin"])
    r = op.post(f"/api/v1/clients/{world['b'].pk}/members/", {"email": "a.eng@example.test", "role": "operator_engineer"}, format="json")
    assert r.status_code == 400 and r.json()["error"]["code"] == "not_operator_staff"
    # Same payload shape as the web form: empty password and names for an existing user (review defect D-1)
    r = op.post(f"/api/v1/clients/{world['b'].pk}/members/", {"email": "op.eng@example.test", "role": "operator_engineer",
                                                              "first_name": "", "last_name": "", "password": ""}, format="json")
    assert r.status_code == 201
    # A new user still needs a real password
    r = op.post(f"/api/v1/clients/{world['b'].pk}/members/", {"email": "new.person@example.test", "role": "client_user", "password": ""}, format="json")
    assert r.status_code == 400 and r.json()["error"]["code"] == "password_required"


def test_audit_events_written_and_isolated(world):
    c = login(world["op_eng"], world["a"])
    part = create_part(c, "AUD-1")
    a_admin = login(world["a_admin"])
    actions = [e["action"] for e in a_admin.get("/api/v1/audit-events/", {"object_id": part["id"]}).json()["results"]]
    assert actions == ["spare_part.created"]
    assert login(world["b_admin"]).get("/api/v1/audit-events/", {"object_id": part["id"]}).json()["results"] == []
    with tenant_context(world["b"]):
        assert not AuditEvent.objects.filter(object_id=part["id"]).exists()
    assert login(world["a_user"]).get("/api/v1/audit-events/").status_code == 403
