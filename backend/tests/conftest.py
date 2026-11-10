"""Shared fixtures: tenants, users with roles, and authenticated API clients (real login flow)."""
import shutil
import uuid
from pathlib import Path

import pytest
from django.conf import settings
from django.db import connection
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.tenancy.context import ALL_SETTINGS, tenant_context, write_setting
from apps.tenancy.models import Membership, Role, Tenant

PASSWORD = "Correct-Horse-Battery-9"


def dbid(value) -> str:
    """A UUID as the database stores it, for raw SQL: char(32) hex on SQL Server (mssql-django), text on PostgreSQL."""
    u = uuid.UUID(str(value))
    return u.hex if connection.vendor == "microsoft" else str(u)


@pytest.fixture(autouse=True)
def _clean_session_context(request):
    """SQL Server: SESSION_CONTEXT outlives the test transaction's rollback, so each database test starts and ends with an
    empty context (PostgreSQL's transaction-local settings are reset by the rollback itself)."""
    db = next((f for f in ("transactional_db", "db") if f in request.fixturenames), None)
    if connection.vendor != "microsoft" or db is None:
        yield
        return
    request.getfixturevalue(db)

    def clear():
        for key in ALL_SETTINGS:
            write_setting(key, None)
    clear()
    yield
    clear()


@pytest.fixture(autouse=True)
def _clean_storage():
    root = Path(settings.LOCAL_STORAGE_ROOT)
    shutil.rmtree(root, ignore_errors=True)
    yield
    shutil.rmtree(root, ignore_errors=True)


def make_user(email, tenant, role, **extra):
    user = User.objects.create_user(email=email, password=PASSWORD, first_name=email.split("@")[0], **extra)
    Membership.objects.create(user=user, tenant=tenant, role=role)
    return user


@pytest.fixture
def world(db):
    op = Tenant.objects.create(name="Platform Operator", slug="operator", kind=Tenant.Kind.OPERATOR)
    a = Tenant.objects.create(name="Client A Energy", slug="client-a")
    b = Tenant.objects.create(name="Client B Marine", slug="client-b")
    w = {"operator": op, "a": a, "b": b}
    w["op_admin"] = make_user("op.admin@example.test", op, Role.OPERATOR_ADMIN)
    w["op_eng"] = make_user("op.eng@example.test", op, Role.OPERATOR_ENGINEER)
    # Operator engineer assigned to client A for fulfilment (OQ-02)
    Membership.objects.create(user=w["op_eng"], tenant=a, role=Role.OPERATOR_ENGINEER)
    w["a_admin"] = make_user("a.admin@example.test", a, Role.CLIENT_ADMIN)
    w["a_eng"] = make_user("a.eng@example.test", a, Role.CLIENT_ENGINEER)
    w["a_user"] = make_user("a.user@example.test", a, Role.CLIENT_USER)
    w["a_proc"] = make_user("a.proc@example.test", a, Role.PROCUREMENT)
    w["b_admin"] = make_user("b.admin@example.test", b, Role.CLIENT_ADMIN)
    w["b_eng"] = make_user("b.eng@example.test", b, Role.CLIENT_ENGINEER)
    return w


def login(user, tenant=None) -> APIClient:
    c = APIClient()
    body = {"email": user.email, "password": PASSWORD}
    if tenant is not None:
        body["tenant"] = tenant.slug
    r = c.post("/api/v1/auth/token/", body, format="json")
    assert r.status_code == 200, r.content
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {r.json()['access']}")
    c.session_payload = r.json()["session"]
    c.refresh_token = r.json()["refresh"]
    return c


@pytest.fixture
def as_user():
    return login


@pytest.fixture
def in_tenant():
    return tenant_context
