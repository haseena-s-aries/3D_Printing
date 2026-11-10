"""W2 security items: A) single-use download/preview links, B) invitations without account enumeration."""
import hashlib
import os
import re
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core import mail, signing
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.files.models import LinkRedemption
from apps.files.services import LINK_SALT
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Invitation, Membership

from .conftest import PASSWORD, login
from .test_files import PDF_BYTES, upload

User = get_user_model()


# ---- A. single-use links ---------------------------------------------------------------------------------------

@pytest.fixture
def pdf(world):
    eng = login(world["op_eng"], world["a"])
    part = eng.post("/api/v1/parts/", {"part_number": "SU-1", "name": "Bracket"}, format="json").json()
    return upload(eng, part["id"], "spec.pdf", PDF_BYTES).json()


def new_link(c, f, variant):
    r = c.post(f"/api/v1/files/{f['id']}/versions/1/download-link/", {"variant": variant}, format="json")
    assert r.status_code == 200, r.content
    return r.json()["url"].replace("http://testserver", "")


@pytest.mark.parametrize("variant", ["original", "preview"])
def test_links_work_once(world, pdf, client, variant):
    admin = login(world["a_admin"])
    url = new_link(admin, pdf, variant)
    first = client.get(url)
    assert first.status_code == 200 and b"".join(first.streaming_content) == PDF_BYTES
    # (responses are not close()d: in the test client that fires request_finished and closes the DB connection)
    again = client.get(url)
    assert again.status_code == 410 and again.json()["error"]["code"] == "link_used"
    assert client.get(new_link(admin, pdf, variant)).status_code == 200  # a fresh link works


def test_redemptions_are_tenant_scoped(world, pdf, client):
    client.get(new_link(login(world["a_admin"]), pdf, "original"))
    with tenant_context(world["a"]):
        assert LinkRedemption.objects.count() == 1
    with tenant_context(world["b"]):
        assert LinkRedemption.objects.count() == 0  # RLS


def test_links_without_nonce_are_refused(world, pdf, client):
    admin = login(world["a_admin"])
    data = signing.loads(new_link(admin, pdf, "original").rstrip("/").rsplit("/", 1)[1], salt=LINK_SALT)
    data.pop("n")
    legacy = signing.dumps(data, salt=LINK_SALT, compress=True)
    assert client.get(f"/api/v1/downloads/{legacy}/").json()["error"]["code"] == "link_invalid"


# ---- B. invitations --------------------------------------------------------------------------------------------

def invite(admin, email, role="client_user"):
    return admin.post("/api/v1/invitations/", {"email": email, "role": role}, format="json")


def token_of(r):
    """The token from the emailed link (tests run with DEBUG off, so the API never returns it)."""
    assert r.status_code == 201, r.content
    sent = [m for m in mail.outbox if m.to == [r.json()["email"]]][-1]
    return re.search(r"/invite/(\S+)", sent.body).group(1)


def test_invitation_response_is_identical_whether_or_not_the_account_exists(world):
    User.objects.create_user(email="loner@example.test", password=PASSWORD)  # account without any organisation
    admin = login(world["a_admin"])
    shapes = set()
    # op.admin is operator staff without any membership in client A (op.eng is already visible there as assigned staff)
    for email in ("op.admin@example.test", "b.eng@example.test", "loner@example.test", "brand.new@example.test"):
        r = invite(admin, email)
        assert r.status_code == 201, (email, r.content)
        body = r.json()
        shapes.add((tuple(sorted(body)), body["role"], body["state"]))
    assert len(shapes) == 1  # same status, same fields, same values
    # nothing changed for existing accounts, and every address was emailed
    assert not Membership.objects.filter(tenant=world["a"], user__email__in=["op.admin@example.test", "b.eng@example.test", "loner@example.test"]).exists()
    assert sorted(m.to[0] for m in mail.outbox) == ["b.eng@example.test", "brand.new@example.test", "loner@example.test", "op.admin@example.test"]


def test_public_invitation_view_does_not_reveal_account_existence(world, client):
    admin = login(world["a_admin"])
    keys = {tuple(sorted(client.get(f"/api/v1/invitation-acceptance/{token_of(invite(admin, e))}/").json())) for e in ("b.eng@example.test", "new.one@example.test")}
    assert keys == {("email", "expires_at", "organisation", "role")}


def test_only_a_hash_of_the_token_is_stored(world):
    r = invite(login(world["a_admin"]), "hash.check@example.test")
    token = token_of(r)
    inv = Invitation.objects.get(pk=r.json()["id"])
    assert inv.token_hash == hashlib.sha256(token.encode()).hexdigest() and token not in inv.token_hash


def test_new_address_accepts_and_signs_in(world, client):
    token = token_of(invite(login(world["a_admin"]), "fresh@example.test", "client_engineer"))
    r = client.post(f"/api/v1/invitation-acceptance/{token}/", {"first_name": "Fresh", "password": "Fresh-Person-Pass-1"}, format="json")
    assert r.status_code == 200 and r.json()["organisation"] == "Client A Energy"
    s = client.post("/api/v1/auth/token/", {"email": "fresh@example.test", "password": "Fresh-Person-Pass-1"}, format="json")
    assert s.status_code == 200 and s.json()["session"]["membership"]["role"] == "client_engineer"
    # single use
    assert client.post(f"/api/v1/invitation-acceptance/{token}/", {"password": "Fresh-Person-Pass-1"}, format="json").json()["error"]["code"] == "invitation_invalid"
    with tenant_context(world["a"]):
        assert AuditEvent.objects.filter(action="invitation.accepted", actor_email="fresh@example.test").exists()


def test_weak_password_for_new_address_is_rejected(world, client):
    token = token_of(invite(login(world["a_admin"]), "weak@example.test"))
    r = client.post(f"/api/v1/invitation-acceptance/{token}/", {"password": "short"}, format="json")
    assert r.status_code == 400 and "password" in r.json()["error"]["details"]
    assert not User.objects.filter(email="weak@example.test").exists()


@pytest.mark.parametrize("who", ["op_admin", "b_eng"], ids=["operator-staff", "other-client-user"])
def test_operator_staff_and_other_organisation_accounts_cannot_join_by_invitation(world, client, who):
    user = world[who]
    token = token_of(invite(login(world["a_admin"]), user.email))
    r = client.post(f"/api/v1/invitation-acceptance/{token}/", {"password": PASSWORD}, format="json")
    assert r.status_code == 403 and r.json()["error"]["code"] == "invitation_not_applicable"
    assert not Membership.objects.filter(user=user, tenant=world["a"], role="client_user").exists()
    with tenant_context(world["operator"]):
        assert AuditEvent.objects.filter(action="invitation.acceptance_refused", actor_email=user.email).exists()  # operator side
    with tenant_context(world["a"]):
        assert not AuditEvent.objects.filter(action="invitation.acceptance_refused").exists()  # nothing for the inviter to see


def test_existing_account_must_prove_its_password(world, client):
    User.objects.create_user(email="loner@example.test", password=PASSWORD)
    token = token_of(invite(login(world["a_admin"]), "loner@example.test"))
    wrong = client.post(f"/api/v1/invitation-acceptance/{token}/", {"password": "Not-The-Password-1"}, format="json")
    assert wrong.status_code == 400 and wrong.json()["error"]["code"] == "invitation_invalid"
    assert client.post(f"/api/v1/invitation-acceptance/{token}/", {"password": PASSWORD}, format="json").status_code == 200
    assert Membership.objects.filter(user__email="loner@example.test", tenant=world["a"]).exists()


def test_expired_revoked_and_replaced_invitations_are_invalid(world, client):
    admin = login(world["a_admin"])
    r1 = invite(admin, "x1@example.test")
    Invitation.objects.filter(pk=r1.json()["id"]).update(expires_at=timezone.now() - timedelta(minutes=1))
    assert client.get(f"/api/v1/invitation-acceptance/{token_of(r1)}/").json()["error"]["code"] == "invitation_invalid"
    r2 = invite(admin, "x2@example.test")
    assert admin.post(f"/api/v1/invitations/{r2.json()['id']}/revoke/").json()["state"] == "revoked"
    assert client.get(f"/api/v1/invitation-acceptance/{token_of(r2)}/").status_code == 400
    old = token_of(invite(admin, "x3@example.test"))
    new = token_of(invite(admin, "x3@example.test"))  # re-inviting replaces the old link
    assert old != new
    assert client.get(f"/api/v1/invitation-acceptance/{old}/").status_code == 400
    assert client.get(f"/api/v1/invitation-acceptance/{new}/").status_code == 200


def test_invitation_rules_and_isolation(world):
    admin = login(world["a_admin"])
    assert invite(admin, "x@example.test", "operator_engineer").status_code == 403
    assert invite(admin, "x@example.test", "operator_admin").status_code == 403
    assert invite(admin, "a.user@example.test").json()["error"]["code"] == "already_member"
    r = invite(admin, "only.a@example.test")
    b = login(world["b_admin"])
    assert all(i["email"] != "only.a@example.test" for i in b.get("/api/v1/invitations/").json()["results"])
    assert b.post(f"/api/v1/invitations/{r.json()['id']}/revoke/").status_code == 404


def test_link_hidden_when_not_in_development_mode(world, settings):
    settings.INVITATION_LINK_IN_RESPONSE = False
    r = invite(login(world["a_admin"]), "prod.mode@example.test")
    assert r.status_code == 201 and r.json()["invite_url"] is None
    assert "prod.mode@example.test" in mail.outbox[-1].to and "/invite/" in mail.outbox[-1].body


def test_link_never_returned_without_debug_even_if_the_setting_is_on(world, settings):
    settings.DEBUG, settings.INVITATION_LINK_IN_RESPONSE = False, True  # mistakenly enabled in production
    admin = login(world["a_admin"])
    r = invite(admin, "misconfigured@example.test")
    assert r.status_code == 201 and r.json()["invite_url"] is None
    token = token_of(r)
    assert token not in r.content.decode() and token not in admin.get("/api/v1/invitations/").content.decode()
    settings.DEBUG = True  # development: shown only when both are on
    dev = invite(admin, "dev.mode@example.test")
    assert dev.json()["invite_url"].endswith("/invite/" + token_of(dev))


def test_settings_force_the_link_off_without_debug():
    env = {**os.environ, "DJANGO_DEBUG": "false", "INVITATION_LINK_IN_RESPONSE": "true", "DJANGO_SECRET_KEY": "x" * 50}
    out = subprocess.run([sys.executable, "-c", "import django, os; os.environ['DJANGO_SETTINGS_MODULE']='config.settings'; "
                          "from django.conf import settings; print(settings.INVITATION_LINK_IN_RESPONSE)"],
                         cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


def test_expired_invitation_cannot_be_accepted(world, client):
    r = invite(login(world["a_admin"]), "late@example.test")
    Invitation.objects.filter(pk=r.json()["id"]).update(expires_at=timezone.now() - timedelta(seconds=1))
    p = client.post(f"/api/v1/invitation-acceptance/{token_of(r)}/", {"password": "Late-Person-Pass-1"}, format="json")
    assert p.status_code == 400 and p.json()["error"]["code"] == "invitation_invalid"
    assert not User.objects.filter(email="late@example.test").exists()


def test_accepted_invitation_grants_only_its_own_organisation_and_role(world, client):
    token = token_of(invite(login(world["a_admin"]), "scoped@example.test", "client_user"))
    assert client.post(f"/api/v1/invitation-acceptance/{token}/", {"password": "Scoped-Person-Pass-1"}, format="json").status_code == 200
    user = User.objects.get(email="scoped@example.test")
    assert [(m.tenant_id, m.role) for m in Membership.objects.filter(user=user)] == [(world["a"].pk, "client_user")]
    other = client.post("/api/v1/auth/token/", {"email": "scoped@example.test", "password": "Scoped-Person-Pass-1", "tenant": world["b"].slug}, format="json")
    assert other.status_code in (400, 401, 403)
    assert not user.is_staff and not user.is_superuser
