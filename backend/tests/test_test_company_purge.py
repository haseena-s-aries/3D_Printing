"""Test companies (decision of 19 Nov 2026): marking, queueing for deletion (suspends at once, restorable) and the
privileged purge that erases a queued company completely while leaving every other company and the Aries staff alone."""
from io import StringIO
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import CommandError, call_command
from django.db import connection, transaction

from apps.accounts.models import User
from apps.audit.models import AuditEvent
from apps.servicerequests.models import RequestEnvelope
from apps.tenancy import purge
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Membership, Tenant

from .conftest import PASSWORD, login
from .test_files import PDF_BYTES, upload
from .test_manufacturing_flow import order  # noqa: F401 - fixture


@pytest.fixture(autouse=True)
def _fresh_throttle():
    from django.core.cache import cache

    cache.clear()  # the sign-in throttle counts the deliberately refused sign-in below
    yield
    cache.clear()


def _queue(world, name=None):
    admin = login(world["op_admin"])
    cid = world["a"].pk
    assert admin.post(f"/api/v1/clients/{cid}/test-company/", {"is_test": True}, format="json").status_code == 200
    r = admin.post(f"/api/v1/clients/{cid}/request-deletion/", {"confirm_name": name or world["a"].name}, format="json")
    return admin, r


def test_only_a_marked_test_company_can_be_queued_and_the_name_must_be_typed(world):
    admin = login(world["op_admin"])
    cid = world["a"].pk
    r = admin.post(f"/api/v1/clients/{cid}/request-deletion/", {"confirm_name": world["a"].name}, format="json")
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_test_company"  # real companies are never deleted here
    assert login(world["op_eng"]).post(f"/api/v1/clients/{cid}/test-company/", {"is_test": True}, format="json").status_code == 403
    assert login(world["a_admin"]).post(f"/api/v1/clients/{cid}/test-company/", {"is_test": True}, format="json").status_code in (403, 404)
    assert admin.post(f"/api/v1/clients/{cid}/test-company/", {"is_test": True}, format="json").json()["is_test"] is True
    r = admin.post(f"/api/v1/clients/{cid}/request-deletion/", {"confirm_name": "client a"}, format="json")
    assert r.status_code == 400 and r.json()["error"]["code"] == "confirmation_mismatch"
    _admin, r = _queue(world)
    assert r.status_code == 200 and r.json()["status"] == "suspended" and r.json()["deletion_requested_at"]
    assert admin.post(f"/api/v1/clients/{cid}/request-deletion/", {"confirm_name": world["a"].name}, format="json").status_code == 409


def test_queued_company_is_suspended_at_once_and_can_be_restored(world):
    _queue(world)
    from rest_framework.test import APIClient

    c = APIClient()
    r = c.post("/api/v1/auth/token/", {"email": world["a_admin"].email, "password": PASSWORD, "tenant": world["a"].slug}, format="json")
    assert r.status_code >= 400  # nobody signs in to a company queued for deletion
    admin = login(world["op_admin"])
    rows = {c_["slug"]: c_ for c_ in admin.get("/api/v1/clients/").json()["results"]}
    assert rows[world["a"].slug]["deletion_requested_at"] and rows[world["b"].slug]["deletion_requested_at"] is None
    back = admin.post(f"/api/v1/clients/{world['a'].pk}/restore/", format="json").json()
    assert back["status"] == "active" and back["deletion_requested_at"] is None
    assert login(world["a_admin"]).get("/api/v1/parts/").status_code == 200
    assert admin.post(f"/api/v1/clients/{world['a'].pk}/restore/", format="json").status_code == 409  # not queued any more
    assert admin.post(f"/api/v1/clients/{world['a'].pk}/test-company/", {"is_test": False}, format="json").json()["is_test"] is False


def _rich_company(world, order):  # noqa: F811
    """Company A with parts, passports, a request with an estimate and a quotation, files, audit rows, users and notifications."""
    w = world
    eng = login(w["op_eng"], w["a"])
    part = eng.post("/api/v1/parts/", {"part_number": "FILE-1", "name": "With a file"}, format="json").json()
    assert upload(eng, part["id"], "datasheet.pdf", PDF_BYTES).status_code == 201
    est = f"/api/v1/operator/requests/{order['env'].pk}/estimate/"
    order["act"](w["op_eng"], "acknowledge")
    eng.post(est, {"action": "manual"}, format="json")
    login(w["op_mgr"]).post(est, {"action": "choose", "route": "conventional"}, format="json")
    login(w["op_mgr"]).post(est, {"action": "quote", "price": "500", "delivery_days": 9}, format="json")


def _tables_with_rows(tenant):
    out = {}
    with tenant_context(tenant):
        for m in purge.company_models():
            n = m._base_manager.filter(tenant_id=tenant.pk).count()
            if n:
                out[m._meta.label] = n
    return out


def test_purge_erases_the_company_completely_and_nothing_else(world, order):  # noqa: F811
    w = world
    _rich_company(w, order)
    login(w["b_admin"]).get("/api/v1/parts/")  # some activity (audit) in company B too
    before_a, before_b = _tables_with_rows(w["a"]), _tables_with_rows(w["b"])
    assert {"parts.SparePart", "audit.AuditEvent", "servicerequests.Quotation", "intelligence.ManufacturingEstimate",
            "files.FileVersion", "tenancy.Membership"} <= set(before_a)
    storage = Path(settings.LOCAL_STORAGE_ROOT) / "tenants" / str(w["a"].pk)
    assert storage.exists()
    op_eng_pk, a_admin_pk = w["op_eng"].pk, w["a_admin"].pk
    _queue(w)
    client = Tenant.objects.get(pk=w["a"].pk)

    result = purge.purge(client)

    assert result["rows"] >= sum(before_a.values()) + 1  # every table row, plus the request summary kept in the Aries organisation
    assert not Tenant.objects.filter(pk=w["a"].pk).exists()
    assert not storage.exists() and result["files"] >= 1  # the uploaded file is gone from storage
    assert not User.objects.filter(pk=a_admin_pk).exists()  # people who belonged only to that company
    assert User.objects.filter(pk=op_eng_pk).exists()  # Aries staff are never deleted
    assert Membership.objects.filter(user_id=op_eng_pk, tenant__kind="operator").exists()
    assert _tables_with_rows(w["b"]) == before_b  # another company is untouched
    assert User.objects.filter(pk=w["b_admin"].pk).exists()
    with tenant_context(w["operator"]):
        assert not RequestEnvelope.objects.filter(client_tenant_id=w["a"].pk).exists()
        e = AuditEvent.objects.get(action="tenant.purged")  # one audit event remains, in the Aries organisation
        assert e.data["slug"] == w["a"].slug and e.data["requested_by"] == "op.admin@example.test"
    with connection.cursor() as cur:
        cur.execute("SELECT relforcerowsecurity FROM pg_class WHERE relname = 'servicerequests_notification'")
        assert cur.fetchone()[0] is True  # notifications are protected again
    # the guards are back on: the audit trail is immutable again
    with tenant_context(w["b"]):
        with pytest.raises(Exception, match="immutable_record"), transaction.atomic():
            AuditEvent.objects.filter(tenant=w["b"]).delete()


def test_a_failed_purge_changes_nothing_and_leaves_the_guards_on(world, order, monkeypatch):  # noqa: F811
    w = world
    _rich_company(w, order)
    before = _tables_with_rows(w["a"])
    _queue(w)
    client = Tenant.objects.get(pk=w["a"].pk)

    def boom(*a, **k):
        raise RuntimeError("storage unavailable")
    monkeypatch.setattr(purge, "_delete_users", boom)
    with pytest.raises(RuntimeError):
        purge.purge(client)
    assert Tenant.objects.filter(pk=w["a"].pk).exists() and _tables_with_rows(w["a"]) == before
    with connection.cursor() as cur:  # every guard enabled again ('O' = enabled), notifications forced under RLS again
        cur.execute("SELECT count(*) FROM pg_trigger WHERE tgname ~ '_guard$' AND NOT tgisinternal AND tgenabled <> 'O'")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT relforcerowsecurity FROM pg_class WHERE relname = 'servicerequests_notification'")
        assert cur.fetchone()[0] is True


def test_purge_refuses_a_company_that_is_not_queued(world):
    from apps.core.exceptions import DomainError

    for company in (world["a"], world["operator"]):  # an ordinary company, and the Aries organisation itself
        with pytest.raises(DomainError) as e:
            purge.purge(company)
        assert e.value.error_code == "not_queued"
        assert Tenant.objects.filter(pk=company.pk).exists()


def test_command_lists_asks_and_erases(world, order, monkeypatch):  # noqa: F811
    w = world
    _rich_company(w, order)
    out = StringIO()
    call_command("purge_test_companies", "--dry-run", stdout=out)
    assert "No test company is queued" in out.getvalue()
    _queue(w)
    out = StringIO()
    call_command("purge_test_companies", "--dry-run", stdout=out)
    text = out.getvalue()
    assert w["a"].name in text and "Dry run: nothing was erased." in text and Tenant.objects.filter(pk=w["a"].pk).exists()
    with pytest.raises(CommandError):
        call_command("purge_test_companies", "--slug", "no-such-company", stdout=StringIO())
    monkeypatch.setattr("builtins.input", lambda *_: "no")
    with pytest.raises(CommandError, match="Cancelled"):
        call_command("purge_test_companies", stdout=StringIO())
    assert Tenant.objects.filter(pk=w["a"].pk).exists()
    monkeypatch.setattr("builtins.input", lambda *_: "ERASE")
    out = StringIO()
    call_command("purge_test_companies", stdout=out)
    assert "erased" in out.getvalue() and not Tenant.objects.filter(pk=w["a"].pk).exists()
    assert Tenant.objects.filter(pk=w["b"].pk).exists()
