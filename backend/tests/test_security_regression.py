"""Security regression (Phase 1 batch 9): guards that must keep holding as new models and endpoints are added."""
import pytest
from django.apps import apps
from django.db import connection

from apps.audit.models import AuditEvent
from apps.parts.models import SparePart
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Membership, Tenant

from .conftest import PASSWORD, login
from .test_files import PDF_BYTES, download, upload

# Tables with a tenant column that are deliberately NOT under RLS: memberships are read across tenants at login
# and invitations are looked up by token at acceptance (both before any tenant context exists). Both are only
# exposed through explicitly tenant-scoped API querysets, covered by tests.
RLS_EXEMPT = {"tenancy_membership", "tenancy_invitation"}


def tenant_tables():
    return sorted(
        m._meta.db_table for m in apps.get_models()
        if any(f.name == "tenant" for f in m._meta.concrete_fields) and m._meta.db_table not in RLS_EXEMPT
    )


def test_every_tenant_table_has_forced_rls_and_policy(db):
    tables = tenant_tables()
    assert len(tables) >= 9
    with connection.cursor() as cur:
        for t in tables:
            if connection.vendor == "microsoft":  # an enabled security policy filtering and blocking on the tenant
                cur.execute("SELECT p.is_enabled, pr.predicate_definition FROM sys.security_predicates pr "
                            "JOIN sys.security_policies p ON p.object_id = pr.object_id "
                            "WHERE pr.target_object_id = OBJECT_ID(%s) AND pr.predicate_type_desc = 'FILTER'", [f"dbo.{t}"])
                row = cur.fetchone()
                assert row and row[0] and any(f"[dbo].[{fn}]([tenant_id])" in row[1]
                                              for fn in ("rls_tenant", "rls_tenant_or_worker", "rls_jobsheet")), f"{t} lacks a tenant policy"
                cur.execute("SELECT COUNT(*) FROM sys.security_predicates pr WHERE pr.target_object_id = OBJECT_ID(%s) "
                            "AND pr.predicate_type_desc = 'BLOCK' AND pr.operation_desc IN ('AFTER INSERT', 'AFTER UPDATE')", [f"dbo.{t}"])
                assert cur.fetchone()[0] == 2, f"{t} lacks insert/update block predicates"
                continue
            cur.execute("select relrowsecurity, relforcerowsecurity from pg_class where relname = %s", [t])
            assert cur.fetchone() == (True, True), f"{t} lacks forced RLS"
            cur.execute("select count(*) from pg_policies where tablename = %s and qual like %s", [t, "%app.tenant_id%"])
            assert cur.fetchone()[0] >= 1, f"{t} lacks a tenant policy"


def test_login_does_not_reveal_whether_an_account_exists(world, client):
    unknown = client.post("/api/v1/auth/token/", {"email": "nobody@example.test", "password": "x"}, format="json")
    wrong = client.post("/api/v1/auth/token/", {"email": "a.admin@example.test", "password": "x"}, format="json")
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["error"]["code"] == wrong.json()["error"]["code"]
    assert unknown.json()["error"]["message"] == wrong.json()["error"]["message"]


def test_inactive_user_cannot_login(world, client):
    world["a_user"].is_active = False
    world["a_user"].save()
    r = client.post("/api/v1/auth/token/", {"email": "a.user@example.test", "password": PASSWORD}, format="json")
    assert r.status_code == 401


def test_operator_staff_limited_to_assigned_client_tenants(world, client):
    # op_eng is assigned to client A only; client B data stays invisible and B cannot be selected at login
    with tenant_context(world["b"]):
        part_b = SparePart.objects.create(tenant=world["b"], part_number="B-77", name="Pump")
    op_in_a = login(world["op_eng"], world["a"])
    assert op_in_a.get(f"/api/v1/parts/{part_b.pk}/").status_code == 404
    assert op_in_a.get("/api/v1/parts/", {"search": "B-77"}).json()["results"] == []
    r = client.post("/api/v1/auth/token/", {"email": "op.eng@example.test", "password": PASSWORD, "tenant": "client-b"}, format="json")
    assert r.status_code == 403


def test_cross_tenant_ids_in_filters_and_nested_routes(world):
    a = login(world["op_eng"], world["a"])
    part = a.post("/api/v1/parts/", {"part_number": "A-9", "name": "Holder"}, format="json").json()
    p = a.post("/api/v1/passports/", {"part": part["id"]}, format="json").json()
    upload(a, part["id"], "spec.pdf", PDF_BYTES, passport=p["id"])
    b = login(world["b_admin"])
    assert b.get("/api/v1/files/", {"passport": p["id"]}).json()["results"] == []
    assert b.get("/api/v1/files/", {"part": part["id"]}).json()["results"] == []
    assert b.get(f"/api/v1/passports/{p['id']}/revisions/").status_code == 404
    assert b.get(f"/api/v1/passports/{p['id']}/revisions/1/").status_code == 404
    # client admins lack edit capability, so these are refused by role before any lookup (no existence oracle)
    assert b.patch(f"/api/v1/passports/{p['id']}/revisions/1/", {"change_summary": "x"}, format="json").status_code in (403, 404)
    assert b.patch(f"/api/v1/parts/{part['id']}/", {"name": "pwned"}, format="json").status_code in (403, 404)
    assert a.get(f"/api/v1/parts/{part['id']}/").json()["name"] == "Holder"
    # B cannot attach its own file to A's part either
    assert upload(b, part["id"], "x.pdf", PDF_BYTES).status_code == 400


def test_download_link_bound_to_issuing_tenant(world, setup_two_tenants, client):
    a, f = setup_two_tenants
    url = download(a, f["id"]).json()["url"].replace("http://testserver", "")
    # Suspending tenant A invalidates outstanding links even though the token itself is still valid
    Tenant.objects.filter(pk=world["a"].pk).update(status="suspended")
    assert client.get(url).status_code in (403, 404)


@pytest.fixture
def setup_two_tenants(world):
    a = login(world["a_admin"])
    eng = login(world["op_eng"], world["a"])
    part = eng.post("/api/v1/parts/", {"part_number": "DL-1", "name": "Bracket"}, format="json").json()
    f = upload(eng, part["id"], "spec.pdf", PDF_BYTES).json()
    return a, f


def test_audit_log_is_read_only_via_api(world):
    c = login(world["op_admin"])
    events = c.get("/api/v1/audit-events/").json()["results"]
    assert events, "login should have produced an audit event"
    eid = events[0]["id"]
    refused = (403, 404, 405)  # capability check first; the list-only viewset has no detail route at all
    assert c.post("/api/v1/audit-events/", {"action": "forged"}, format="json").status_code in refused
    assert c.patch(f"/api/v1/audit-events/{eid}/", {"action": "forged"}, format="json").status_code in refused
    assert c.delete(f"/api/v1/audit-events/{eid}/").status_code in refused
    with tenant_context(world["operator"]):
        assert AuditEvent.objects.filter(pk=eid).exclude(action="forged").exists()
        assert not AuditEvent.objects.filter(action="forged").exists()


def test_no_delete_endpoints_for_records(world):
    c = login(world["op_eng"], world["a"])
    part = c.post("/api/v1/parts/", {"part_number": "ND-1", "name": "Shaft"}, format="json").json()
    p = c.post("/api/v1/passports/", {"part": part["id"]}, format="json").json()
    assert c.delete(f"/api/v1/parts/{part['id']}/").status_code in (403, 405)
    assert c.delete(f"/api/v1/passports/{p['id']}/").status_code in (403, 405)
    assert c.get(f"/api/v1/parts/{part['id']}/").status_code == 200
    assert c.get(f"/api/v1/passports/{p['id']}/").status_code == 200


def test_errors_use_envelope_without_internals(world):
    c = login(world["a_admin"])
    r = c.get("/api/v1/parts/not-a-uuid/")
    assert r.status_code == 404
    body = r.json()
    assert set(body) == {"error"} and body["error"]["request_id"]
    assert "Traceback" not in r.content.decode()


def test_membership_reactivation_needed_after_deactivation(world, client):
    c = login(world["a_eng"])
    Membership.objects.filter(user=world["a_eng"], tenant=world["a"]).update(is_active=False)
    assert c.get("/api/v1/parts/").status_code == 401
    r = client.post("/api/v1/auth/refresh/", {"refresh": c.refresh_token}, format="json")
    assert r.status_code == 401
