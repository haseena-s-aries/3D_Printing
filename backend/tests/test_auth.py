"""Authentication end to end: login per tenant, token binding, refresh, logout, revocation."""
from apps.tenancy.models import Membership, Tenant

from .conftest import PASSWORD, login


def test_login_returns_tokens_and_session(world, client):
    r = client.post("/api/v1/auth/token/", {"email": "a.admin@example.test", "password": PASSWORD}, format="json")
    assert r.status_code == 200
    body = r.json()
    assert body["access"] and body["refresh"]
    assert body["session"]["tenant"]["slug"] == "client-a"
    assert "users.manage" in body["session"]["capabilities"]
    assert "clients.manage" not in body["session"]["capabilities"]


def test_wrong_password_rejected_with_error_envelope(world, client):
    r = client.post("/api/v1/auth/token/", {"email": "a.admin@example.test", "password": "nope"}, format="json")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_credentials"
    assert r.json()["error"]["request_id"]


def test_multi_tenant_user_must_select_tenant(world, client):
    from apps.tenancy.models import Membership

    Membership.objects.create(user=world["op_eng"], tenant=world["b"], role="operator_engineer")
    r = client.post("/api/v1/auth/token/", {"email": "op.eng@example.test", "password": PASSWORD}, format="json")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "tenant_selection_required"
    # assigned engineers choose among their client workspaces; the Platform Operator organisation is not offered
    assert {t["slug"] for t in r.json()["error"]["details"]["tenants"]} == {"client-a", "client-b"}
    c = login(world["op_eng"], world["a"])
    assert c.get("/api/v1/auth/me/").json()["tenant"]["slug"] == "client-a"


def test_cannot_login_to_tenant_without_membership(world, client):
    r = client.post("/api/v1/auth/token/", {"email": "a.admin@example.test", "password": PASSWORD, "tenant": "client-b"}, format="json")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "no_active_membership"


def test_unauthenticated_requests_refused(world, client):
    for url in ("/api/v1/parts/", "/api/v1/passports/", "/api/v1/users/", "/api/v1/auth/me/"):
        assert client.get(url).status_code == 401


def test_tampered_token_refused(world):
    c = login(world["a_admin"])
    token = c._credentials["HTTP_AUTHORIZATION"].split()[1]
    c.credentials(HTTP_AUTHORIZATION="Bearer " + token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB"))
    assert c.get("/api/v1/auth/me/").status_code == 401


def test_deactivated_membership_revokes_existing_token(world):
    c = login(world["a_eng"])
    assert c.get("/api/v1/parts/").status_code == 200
    Membership.objects.filter(user=world["a_eng"], tenant=world["a"]).update(is_active=False)
    r = c.get("/api/v1/parts/")
    assert r.status_code == 401 and r.json()["error"]["code"] == "authentication_failed"


def test_suspended_tenant_blocks_access(world):
    c = login(world["a_eng"])
    Tenant.objects.filter(pk=world["a"].pk).update(status=Tenant.Status.SUSPENDED)
    assert c.get("/api/v1/parts/").status_code == 401


def test_refresh_rotates_and_rechecks_membership(world, client):
    c = login(world["a_eng"])
    r = client.post("/api/v1/auth/refresh/", {"refresh": c.refresh_token}, format="json")
    assert r.status_code == 200 and r.json()["access"]
    # old refresh token is blacklisted after rotation
    assert client.post("/api/v1/auth/refresh/", {"refresh": c.refresh_token}, format="json").status_code == 401
    Membership.objects.filter(user=world["a_eng"], tenant=world["a"]).update(is_active=False)
    assert client.post("/api/v1/auth/refresh/", {"refresh": r.json()["refresh"]}, format="json").status_code == 401


def test_logout_blacklists_refresh(world, client):
    c = login(world["a_eng"])
    assert c.post("/api/v1/auth/logout/", {"refresh": c.refresh_token}, format="json").status_code == 204
    assert client.post("/api/v1/auth/refresh/", {"refresh": c.refresh_token}, format="json").status_code == 401


def test_health_needs_no_auth(db, client):
    r = client.get("/api/health/")
    assert r.status_code == 200 and r.json() == {"status": "ok", "database": "ok"}
    assert r["X-Request-ID"]
