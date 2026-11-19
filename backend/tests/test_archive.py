"""Archive and restore single items (decision of 19 Nov 2026): spare parts (with their passport) and client requests are hidden
everywhere, nothing is erased, and an Aries Admin or Manager restores them from the Archive screen."""
import pytest

from apps.parts.models import SparePart
from apps.servicerequests import services as svc
from apps.servicerequests.models import ClientRequest, RequestEnvelope
from apps.tenancy.context import tenant_context

from .conftest import login
from .test_manufacturing_flow import order  # noqa: F401 - fixture
from .test_service_requests import TOMORROW, manufacturing

ARCHIVE = "/api/v1/operator/archive/"


def _part(world, number="ARC-1", name="Archive me"):
    eng = login(world["op_eng"], world["a"])
    part = eng.post("/api/v1/parts/", {"part_number": number, "name": name}, format="json").json()
    passport = eng.post("/api/v1/passports/", {"part": part["id"]}, format="json").json()
    return eng, part, passport


def test_archiving_a_part_hides_it_and_its_passport_everywhere_and_frees_the_number(world):
    eng, part, passport = _part(world)
    client = login(world["a_admin"])
    assert eng.post(f"/api/v1/parts/{part['id']}/archive/", format="json").json() == {"archived": True, "part_number": "ARC-1"}
    for who in (eng, client):
        assert part["id"] not in [p["id"] for p in who.get("/api/v1/parts/").json()["results"]]
        assert who.get(f"/api/v1/parts/{part['id']}/").status_code == 404
    assert passport["id"] not in [p["id"] for p in eng.get("/api/v1/passports/").json()["results"]]
    assert eng.get(f"/api/v1/passports/{passport['id']}/").status_code == 404
    # the part number is free for a new part while the old one is archived
    again = eng.post("/api/v1/parts/", {"part_number": "ARC-1", "name": "Replacement"}, format="json")
    assert again.status_code == 201, again.content
    with tenant_context(world["a"]):  # nothing was erased
        assert SparePart.all_objects.filter(pk=part["id"], archived_at__isnull=False).count() == 1
    # restoring is refused while the number is used, and works once it is not
    admin = login(world["op_admin"])
    body = {"kind": "part", "client_id": str(world["a"].pk), "id": part["id"]}
    r = admin.post(ARCHIVE, body, format="json")
    assert r.status_code == 409 and r.json()["error"]["code"] == "number_in_use"
    assert eng.post(f"/api/v1/parts/{again.json()['id']}/archive/", format="json").status_code == 200
    assert admin.post(ARCHIVE, body, format="json").json() == {"restored": True}
    assert part["id"] in [p["id"] for p in eng.get("/api/v1/parts/").json()["results"]]
    assert eng.get(f"/api/v1/passports/{passport['id']}/").status_code == 200  # the passport came back with its part


def test_who_may_archive_a_part_and_when(world, order):  # noqa: F811
    eng, part, passport = _part(world, "ARC-2")
    url = f"/api/v1/parts/{part['id']}/archive/"
    assert login(world["a_admin"]).post(url, format="json").status_code == 403  # clients never archive
    assert login(world["a_eng"]).post(url, format="json").status_code == 403
    assert login(world["op_qa"], world["a"]).post(url, format="json").status_code == 403
    # a published passport must be unpublished first
    from apps.passports.models import DigitalPassport

    with tenant_context(world["a"]):
        DigitalPassport.objects.filter(pk=passport["id"]).update(publication_state="published")
    r = eng.post(url, format="json")
    assert r.status_code == 409 and r.json()["error"]["code"] == "published"
    with tenant_context(world["a"]):
        DigitalPassport.objects.filter(pk=passport["id"]).update(publication_state="draft")
    # open requests block it: the ordered part of the order fixture has one
    ordered = order["ref"]["part"]
    r = eng.post(f"/api/v1/parts/{ordered}/archive/", format="json")
    assert r.status_code == 409 and r.json()["error"]["code"] == "open_requests"
    assert eng.post(url, format="json").status_code == 200
    assert eng.post(url, format="json").status_code == 404  # already hidden


def test_archiving_a_request_hides_it_for_client_and_aries_and_restores(world, order):  # noqa: F811
    w = world
    env = order["env"]
    ref_id = order["ref"]["id"]
    client = login(w["a_admin"])
    assert ref_id in [r["id"] for r in client.get("/api/v1/requests/").json()["results"]]
    assert login(w["op_eng"], w["a"]).post(f"/api/v1/operator/requests/{env.pk}/archive/", format="json").status_code == 403
    assert login(w["op_qa"], w["a"]).post(f"/api/v1/operator/requests/{env.pk}/archive/", format="json").status_code == 403
    assert login(w["op_mgr"]).post(f"/api/v1/operator/requests/{env.pk}/archive/", format="json").json() == {"archived": True}
    assert ref_id not in [r["id"] for r in client.get("/api/v1/requests/").json()["results"]]
    assert client.get(f"/api/v1/requests/{ref_id}/").status_code == 404
    for who in (login(w["op_admin"]), login(w["op_eng"], w["a"])):
        assert str(env.pk) not in [r["id"] for r in who.get("/api/v1/operator/requests/").json()]
        assert who.get(f"/api/v1/operator/requests/{env.pk}/").status_code == 404
    # the request summary keeps syncing for an archived request (no duplicate summary, still archived)
    with tenant_context(w["a"]):
        obj = ClientRequest.all_objects.get(pk=ref_id)
    with tenant_context(w["operator"]):
        svc.sync_envelope(obj)
        assert RequestEnvelope.all_objects.filter(request_id=ref_id).count() == 1
        assert RequestEnvelope.all_objects.get(request_id=ref_id).archived_at is not None
    rows = login(w["op_admin"]).get(ARCHIVE).json()
    assert [(r["kind"], r["client_name"]) for r in rows] == [("request", "Client A Energy")] and rows[0]["archived_by"] == "op.mgr@example.test"
    assert login(w["op_eng"]).get(ARCHIVE).status_code == 403  # the Archive screen is for Admin and Manager
    assert login(w["op_admin"]).post(ARCHIVE, {"kind": "request", "client_id": str(w["a"].pk), "id": ref_id}, format="json").status_code == 200
    assert ref_id in [r["id"] for r in client.get("/api/v1/requests/").json()["results"]]
    assert str(env.pk) in [r["id"] for r in login(w["op_admin"]).get("/api/v1/operator/requests/").json()]


def test_an_order_in_production_cannot_be_archived(world, order):  # noqa: F811
    w = world
    with tenant_context(w["a"]):
        ClientRequest.objects.filter(pk=order["ref"]["id"]).update(status="in_production")
    r = login(w["op_admin"]).post(f"/api/v1/operator/requests/{order['env'].pk}/archive/", format="json")
    assert r.status_code == 409 and r.json()["error"]["code"] == "in_production"


def test_archiving_does_not_change_anything_else(world):
    """Counts and dashboards follow the hidden rows automatically; other companies are untouched."""
    eng, part, _ = _part(world, "ARC-3")
    other = login(world["b_eng"])
    other.post("/api/v1/parts/", {"part_number": "B-1", "name": "B part"}, format="json")
    before = login(world["b_admin"]).get("/api/v1/parts/").json()["count"]
    eng.post(f"/api/v1/parts/{part['id']}/archive/", format="json")
    assert login(world["b_admin"]).get("/api/v1/parts/").json()["count"] == before
    assert login(world["a_admin"]).get("/api/v1/parts/stage-counts/").json().get("all", 0) == 0  # the only part is archived


def test_the_aries_admin_archives_from_the_workspace_lists_with_the_same_rules(world, order):  # noqa: F811
    """Digital inventory / Incoming requests: the Aries Admin archives without opening the record; same blocks, same audit."""
    _eng, part, _passport = _part(world, "ARC-L1")
    admin = login(world["op_admin"])
    body = {"action": "archive", "kind": "part", "client_id": str(world["a"].pk), "id": part["id"]}
    assert admin.post(ARCHIVE, body, format="json").json() == {"archived": True}
    assert admin.post(ARCHIVE, body, format="json").json()["error"]["code"] == "already_archived"
    assert any(r["id"] == part["id"] for r in admin.get(ARCHIVE).json())
    # a request, from Incoming requests: hidden from the queue, listed in the Archive
    req = {"action": "archive", "kind": "request", "client_id": str(world["a"].pk), "id": str(order["env"].request_id)}
    assert admin.post(ARCHIVE, req, format="json").json() == {"archived": True}
    assert str(order["env"].pk) not in [r["id"] for r in admin.get("/api/v1/operator/requests/").json()]
    assert any(r["kind"] == "request" for r in admin.get(ARCHIVE).json())
    # Aries Engineers, QA and client users cannot use it
    assert login(world["op_eng"], world["operator"]).post(ARCHIVE, body, format="json").status_code == 403
    assert login(world["a_admin"]).post(ARCHIVE, body, format="json").status_code == 403
