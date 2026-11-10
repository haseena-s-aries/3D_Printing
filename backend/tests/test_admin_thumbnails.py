"""Per-company consent for Aries Admin inventory thumbnails (ADMIN_THUMBNAIL_CONSENT_ENABLED, Option A): default OFF, only
the company's own Client Administrator decides, the Aries Admin gets only sanitized thumbnails of client-visible photos
through tokens bound to user, company, thumbnail and consent, every request is re-checked (revocation is immediate),
company isolation holds, originals stay unreachable, and every decision and view is audited."""
import io

import pytest
from django.db import DatabaseError, transaction
from PIL import Image

from apps.audit.models import AuditEvent
from apps.files.admin_thumbnails import TERMS_VERSION
from apps.files.models import AdminThumbnailConsent, Derivative, FileVersion
from apps.files.storage import get_storage
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Role

from .conftest import login, make_user
from .test_files import upload
from .test_w2_catalog import jpeg_with_gps

CONSENT = "/api/v1/company/admin-thumbnail-consent/"


@pytest.fixture
def th(world, settings):
    settings.ADMIN_THUMBNAIL_CONSENT_ENABLED = True
    eng = login(world["op_eng"], world["a"])
    photo_part = eng.post("/api/v1/parts/", {"part_number": "PH-100", "name": "Pump impeller"}, format="json").json()
    plain_part = eng.post("/api/v1/parts/", {"part_number": "NO-200", "name": "Bearing cover"}, format="json").json()
    hidden_part = eng.post("/api/v1/parts/", {"part_number": "HD-300", "name": "Seal housing"}, format="json").json()
    photo = upload(eng, photo_part["id"], "impeller.jpg", jpeg_with_gps(), category="photo").json()
    hidden = upload(eng, hidden_part["id"], "seal.jpg", jpeg_with_gps(), category="photo", client_visible="false").json()
    # company B has its own photographed part
    b_eng_op = make_user("op.eng.b@example.test", world["operator"], Role.OPERATOR_ENGINEER)
    from apps.tenancy.models import Membership
    Membership.objects.create(user=b_eng_op, tenant=world["b"], role=Role.OPERATOR_ENGINEER)
    beng = login(b_eng_op, world["b"])
    b_part = beng.post("/api/v1/parts/", {"part_number": "BP-900", "name": "Valve seat"}, format="json").json()
    b_photo = upload(beng, b_part["id"], "valve.jpg", jpeg_with_gps(), category="photo").json()
    return {"eng": eng, "admin": login(world["op_admin"]), "a_admin": login(world["a_admin"]), "b_admin": login(world["b_admin"]),
            "photo": photo, "hidden": hidden, "b_photo": b_photo, "world": world}


def rows(admin, **params):
    r = admin.get("/api/v1/admin/inventory/", {"page_size": 200, **params})
    assert r.status_code == 200, r.content
    return {x["part_number"]: x for x in r.json()["results"]}, {c["name"]: c for c in r.json()["clients"]}


def allow(c, yes=True):
    return c.post(CONSENT, {"allow": yes, **({"confirm_terms_version": TERMS_VERSION} if yes else {})}, format="json")


def fetch(c, token):
    return c.get(f"/api/v1/admin/inventory/thumbnails/{token}/")


def test_switched_off_means_no_consent_endpoint_and_no_previews(th, settings):
    settings.ADMIN_THUMBNAIL_CONSENT_ENABLED = False
    assert th["a_admin"].get(CONSENT).status_code == 403
    r, _ = rows(th["admin"])
    assert all(x["preview"] is None for x in r.values())
    assert fetch(th["admin"], "anything").status_code == 404


def test_default_off_admin_receives_no_thumbnail(th):
    assert th["a_admin"].get(CONSENT).json()["allowed"] is False
    r, clients = rows(th["admin"])
    assert r["PH-100"]["preview"] is None and clients["Client A Energy"]["thumbnails_allowed"] is False


def test_only_the_client_admin_can_decide(th):
    w = th["world"]
    assert allow(th["admin"]).status_code == 403  # the Aries Admin cannot grant on the client's behalf
    for u in ("a_eng", "a_user", "a_proc"):
        assert allow(login(w[u])).status_code == 403
    assert allow(login(w["op_eng"], w["a"])).status_code == 403  # nor an assigned Aries Engineer
    r = th["a_admin"].post(CONSENT, {"allow": True}, format="json")
    assert r.status_code == 400 and r.json()["error"]["code"] == "terms_not_confirmed"
    assert th["a_admin"].get(CONSENT).json()["allowed"] is False


def test_consent_on_shows_sanitized_thumbnail_and_audits(th):
    r = allow(th["a_admin"])
    assert r.status_code == 201 and r.json()["allowed"] is True and r.json()["history"][0]["role"] == "client_admin"
    rs, clients = rows(th["admin"])
    assert clients["Client A Energy"]["thumbnails_allowed"] is True and clients["Client B Marine"]["thumbnails_allowed"] is False
    assert rs["NO-200"]["preview"] is None  # no photo: neutral fallback
    assert rs["HD-300"]["preview"] is None  # photo not released to the client: never shown
    assert rs["BP-900"]["preview"] is None  # company B has not allowed it
    token = rs["PH-100"]["preview"]["token"]
    assert set(rs["PH-100"]["preview"]) == {"token", "route"} and rs["PH-100"]["preview"]["route"] == "consent" and th["photo"]["id"] not in token
    t = fetch(th["admin"], token)
    assert t.status_code == 200 and t["Content-Type"] == "image/jpeg"
    assert "no-store" in t["Cache-Control"] and "private" in t["Cache-Control"] and t["X-Content-Type-Options"] == "nosniff"
    body = b"".join(t.streaming_content)
    with Image.open(io.BytesIO(body)) as img:
        assert max(img.size) <= 480 and not img.getexif()  # the sanitized thumbnail, not the original
    w = th["world"]
    with tenant_context(w["a"]):
        fv = FileVersion.objects.get(pk=th["photo"]["latest_version"]["id"])
        assert Derivative.objects.get(file_version=fv, kind="thumb").size_bytes == len(body)
        assert AuditEvent.objects.filter(tenant=w["a"], action="files.admin_thumbnails_allowed").count() == 1
        assert AuditEvent.objects.filter(tenant=w["a"], action="inventory.admin_thumbnail_viewed", data__part_number="PH-100").count() == 1
    with get_storage().open(fv.storage_key) as fh:
        assert fh.read() != body
    with tenant_context(w["operator"]):
        assert AuditEvent.objects.filter(tenant=w["operator"], action="files.admin_thumbnails_allowed", object_id=str(w["a"].pk)).count() == 1
        assert AuditEvent.objects.filter(tenant=w["operator"], action="inventory.admin_overview_viewed",
                                         data__thumbnails_issued=1).exists()


def test_revocation_blocks_previously_issued_links_immediately(th):
    allow(th["a_admin"])
    token = rows(th["admin"])[0]["PH-100"]["preview"]["token"]
    assert fetch(th["admin"], token).status_code == 200
    r = allow(th["a_admin"], False)
    assert r.status_code == 201 and r.json()["allowed"] is False
    assert fetch(th["admin"], token).status_code == 404
    assert rows(th["admin"])[0]["PH-100"]["preview"] is None
    allow(th["a_admin"])  # allowing again does not revive links issued under the earlier grant
    assert fetch(th["admin"], token).status_code == 404
    assert fetch(th["admin"], rows(th["admin"])[0]["PH-100"]["preview"]["token"]).status_code == 200
    assert allow(th["a_admin"]).status_code == 409


def test_tokens_are_bound_expire_and_cannot_be_forged(th, settings):
    allow(th["a_admin"])
    token = rows(th["admin"])[0]["PH-100"]["preview"]["token"]
    w = th["world"]
    other_admin = login(make_user("op.admin2@example.test", w["operator"], Role.OPERATOR_ADMIN))
    assert fetch(other_admin, token).status_code == 404  # bound to the user it was issued to
    assert fetch(th["admin"], token[:-2] + ("AA" if not token.endswith("AA") else "BB")).status_code == 404
    for c in (th["a_admin"], th["b_admin"], login(w["op_eng"], w["a"]), login(w["a_eng"])):
        assert fetch(c, token).status_code == 403  # only the Aries Admin role may use the route at all
    settings.ADMIN_THUMBNAIL_LINK_SECONDS = -1
    assert fetch(th["admin"], token).status_code == 404  # expired


def test_company_isolation_and_originals_stay_closed(th):
    allow(th["a_admin"])
    admin = th["admin"]
    assert th["b_admin"].get(CONSENT).json()["allowed"] is False  # A's decision is not B's
    for f in (th["photo"], th["b_photo"]):
        assert admin.get(f"/api/v1/files/{f['id']}/versions/1/thumbnail/").status_code == 404
        assert admin.get(f"/api/v1/files/{f['id']}/").status_code == 404
        assert admin.post(f"/api/v1/files/{f['id']}/versions/1/download-link/", {"variant": "original"}, format="json").status_code == 404
        assert admin.post(f"/api/v1/files/{f['id']}/versions/1/download-link/", {"variant": "preview"}, format="json").status_code == 404
    # company B cannot read company A's photo by any route
    assert th["b_admin"].get(f"/api/v1/files/{th['photo']['id']}/versions/1/thumbnail/").status_code == 404
    _, clients = rows(admin)
    assert all(c.get("thumbnails_allowed") is not None for c in clients.values())
    r, _ = rows(admin)
    assert r["PH-100"]["documents"] == 1 and "file" not in str(r["PH-100"]["preview"])


def test_decisions_are_append_only(th):
    allow(th["a_admin"])
    w = th["world"]
    with tenant_context(w["a"]):
        c = AdminThumbnailConsent.objects.get(tenant=w["a"])
        with pytest.raises(DatabaseError), transaction.atomic():
            AdminThumbnailConsent.objects.filter(pk=c.pk).update(decision="revoked")
        with pytest.raises(DatabaseError), transaction.atomic():
            AdminThumbnailConsent.objects.filter(pk=c.pk).delete()
    with tenant_context(w["b"]):
        assert not AdminThumbnailConsent.objects.filter(pk=c.pk).exists()  # row-level security
