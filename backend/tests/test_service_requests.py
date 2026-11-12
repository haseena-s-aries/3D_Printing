"""Client service requests: enquiry classification, operator intake queue, status workflow, notifications,
3D scanning requests with attachments, tenant isolation and role boundaries (PostgreSQL with RLS)."""
import io
from datetime import date, timedelta

import pytest
from django.db import connection
from PIL import Image

from apps.audit.models import AuditEvent
from apps.parts.models import SparePart
from apps.passports.models import DigitalPassport
from apps.projects.models import Project
from apps.servicerequests.models import ClientRequest, Notification, RequestEnvelope
from apps.tenancy.context import USER_SETTING, tenant_context, write_setting

from .conftest import login

TOMORROW = (date.today() + timedelta(days=14)).isoformat()


@pytest.fixture
def catalog(world):
    eng = login(world["op_eng"], world["a"])
    part = eng.post("/api/v1/parts/", {"part_number": "SR-100", "name": "Pump impeller"}, format="json").json()
    passport = eng.post("/api/v1/passports/", {"part": part["id"]}, format="json").json()
    return {"part": part, "passport": passport}


def manufacturing(c, part_id, **extra):
    body = {"request_type": "manufacturing", "part": part_id, "quantity": 2, "required_date": TOMORROW,
            "delivery_location": "Site A, warehouse 3", "services": ["Additive manufacturing"], "priority": "urgent",
            "remarks": "Spare for breakdown", "client_reference": "PO-123", **extra}
    return c.post("/api/v1/requests/", body, format="json")


def envelope_for(world, ref):
    with tenant_context(world["operator"]):
        return RequestEnvelope.objects.get(reference=ref)


def unread(user):
    write_setting(USER_SETTING, user.pk)  # read as that user (per-user RLS)
    return list(Notification.objects.filter(recipient=user, read_at__isnull=True).values_list("title", flat=True))


def test_draft_part_request_is_an_enquiry_with_reference_and_revision(world, catalog):
    r = manufacturing(login(world["a_admin"]), catalog["part"]["id"])
    assert r.status_code == 201, r.content
    body = r.json()
    assert body["kind"] == "enquiry" and body["status"] == "submitted"
    assert body["reference"] == f"MR-{date.today().year}-00001"
    assert body["passport_revision_number"] == 1 and body["part_number"] == "SR-100"
    env = envelope_for(world, body["reference"])
    assert env.client_tenant_id == world["a"].pk and env.kind == "enquiry" and env.quantity == 2
    # operator admin and the operator engineer assigned to client A are notified
    assert any(body["reference"] in t for t in unread(world["op_admin"]))
    assert any(body["reference"] in t for t in unread(world["op_eng"]))
    second = manufacturing(login(world["a_admin"]), catalog["part"]["id"]).json()
    assert second["reference"].endswith("00002")


def test_published_eligible_part_becomes_a_manufacturing_request_but_has_no_production_actions(world, catalog):
    with tenant_context(world["a"]):  # stored states set directly: there is no approval API (OQ-35/OQ-36)
        DigitalPassport.objects.filter(pk=catalog["passport"]["id"]).update(publication_state="published", manufacturing_eligibility="eligible")
    body = manufacturing(login(world["a_admin"]), catalog["part"]["id"]).json()
    assert body["kind"] == "manufacturing_request"
    op = login(world["op_eng"], world["a"])
    env = envelope_for(world, body["reference"])
    assert op.post(f"/api/v1/operator/requests/{env.pk}/act/", {"action": "acknowledge"}, format="json").status_code == 200
    for forbidden in ("release", "approve", "start_production"):
        assert op.post(f"/api/v1/operator/requests/{env.pk}/act/", {"action": forbidden}, format="json").status_code == 400


def test_operator_workflow_and_client_tracking(world, catalog):
    client = login(world["a_admin"])
    ref = manufacturing(client, catalog["part"]["id"]).json()
    env = envelope_for(world, ref["reference"])
    op = login(world["op_eng"], world["a"])
    act = lambda action, message="": op.post(f"/api/v1/operator/requests/{env.pk}/act/", {"action": action, "message": message}, format="json")
    assert act("respond", "too early").status_code == 409  # must acknowledge first
    assert act("acknowledge").json()["status"] == "acknowledged"
    assert any("acknowledged" in t for t in unread(world["a_admin"]))
    assert act("request_information").status_code == 400  # message required
    assert act("request_information", "Which material certificate do you need?").json()["status"] == "information_requested"
    r = client.post(f"/api/v1/requests/{ref['id']}/reply/", {"message": "EN 10204 3.1"}, format="json")
    assert r.json()["status"] == "information_provided"
    answered = act("respond", "We will prepare an offer offline.").json()
    assert answered["status"] == "answered" and answered["events"][-1]["event"] == "answered"  # fresh history returned
    assert act("close").status_code == 400  # reason required
    assert act("close", "Offer sent offline").json()["status"] == "closed"
    detail = client.get(f"/api/v1/requests/{ref['id']}/").json()
    assert [e["event"] for e in detail["events"]] == ["submitted", "acknowledged", "information_requested", "information_provided", "answered", "closed"]
    assert detail["closed_reason"] == "Offer sent offline"
    assert client.post(f"/api/v1/requests/{ref['id']}/reply/", {"message": "x"}, format="json").status_code == 409
    with tenant_context(world["a"]):
        actions = set(AuditEvent.objects.filter(object_id=ref["id"]).values_list("action", flat=True))
    assert {"request.submitted", "request.acknowledged", "request.answered", "request.closed"} <= actions
    assert envelope_for(world, ref["reference"]).status == "closed"


def test_client_withdraws_before_answer(world, catalog):
    client = login(world["a_admin"])
    ref = manufacturing(client, catalog["part"]["id"]).json()
    assert client.post(f"/api/v1/requests/{ref['id']}/withdraw/", {"message": "Found stock"}, format="json").json()["status"] == "withdrawn"
    assert client.post(f"/api/v1/requests/{ref['id']}/withdraw/", {}, format="json").status_code == 409


def test_roles_and_input_rules(world, catalog):
    user = login(world["a_user"])
    assert manufacturing(user, catalog["part"]["id"]).status_code == 403  # client users browse only
    assert user.get("/api/v1/requests/").status_code == 200
    admin = login(world["a_admin"])
    assert manufacturing(admin, catalog["part"]["id"], required_date="2000-01-01").status_code == 400
    assert manufacturing(admin, catalog["part"]["id"], quantity=0).status_code == 400
    assert manufacturing(admin, catalog["part"]["id"], services=["Invented service"]).status_code == 400
    # client roles cannot reach the operator queue
    assert admin.get("/api/v1/operator/requests/").status_code == 403
    assert user.get("/api/v1/operator/requests/").status_code == 403


def test_tenant_isolation_and_operator_assignment(world, catalog):
    ref = manufacturing(login(world["a_admin"]), catalog["part"]["id"]).json()
    b = login(world["b_admin"])
    assert b.get("/api/v1/requests/").json()["count"] == 0
    assert b.get(f"/api/v1/requests/{ref['id']}/").status_code == 404
    env = envelope_for(world, ref["reference"])
    # the Aries Admin opens and answers every client's requests (decision of 12 Nov 2026); unassigned engineers do not
    op_admin = login(world["op_admin"])
    rows = op_admin.get("/api/v1/operator/requests/").json()
    assert [r["reference"] for r in rows] == [ref["reference"]] and rows[0]["assigned"] is True
    assert op_admin.get(f"/api/v1/operator/requests/{env.pk}/").json()["reference"] == ref["reference"]
    # the assigned engineer opens it from either organisation context
    for ctx in (world["a"], world["operator"]):
        assert login(world["op_eng"], ctx).get(f"/api/v1/operator/requests/{env.pk}/").json()["reference"] == ref["reference"]


def test_notifications_are_private_and_can_be_marked_read(world, catalog):
    manufacturing(login(world["a_admin"]), catalog["part"]["id"])
    eng = login(world["op_eng"], world["a"])
    mine = eng.get("/api/v1/notifications/").json()
    assert mine["unread"] == 1 and mine["results"][0]["link"].startswith("/incoming/")
    other = login(world["op_admin"])
    other_rows = other.get("/api/v1/notifications/").json()["results"]
    assert other.post(f"/api/v1/notifications/{mine['results'][0]['id']}/read/").status_code == 204  # not theirs: no effect
    assert eng.get("/api/v1/notifications/").json()["unread"] == 1
    assert all(r["id"] != mine["results"][0]["id"] for r in other_rows)
    eng.post(f"/api/v1/notifications/{mine['results'][0]['id']}/read/")
    assert eng.get("/api/v1/notifications/").json()["unread"] == 0
    write_setting(USER_SETTING, None)  # database level: without the user's context nothing is visible
    with connection.cursor() as cur:
        cur.execute("select count(*) from servicerequests_notification")
        assert cur.fetchone()[0] == 0


def png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 30), (90, 90, 90)).save(out, format="PNG")
    return out.getvalue()


def test_digitisation_request_with_attachments_project_and_progress(world, catalog):
    client = login(world["a_admin"])
    r = client.post("/api/v1/requests/", {"request_type": "digitisation", "site_location": "Plant 2, pump house",
                                          "equipment": "Cooling pump P-12", "part_description": "Worn bronze impeller\nno drawings",
                                          "reason": "obsolete", "preferred_date": TOMORROW, "contact_name": "A. Admin",
                                          "contact_email": "a.admin@example.test"}, format="json")
    assert r.status_code == 201, r.content
    req = r.json()
    assert req["kind"] == "digitisation" and req["reference"].startswith("DR-")
    up = client.post(f"/api/v1/requests/{req['id']}/attachments/", {"file": io.BytesIO(png())}, format="multipart")
    assert up.status_code == 400  # no filename / type
    from django.core.files.uploadedfile import SimpleUploadedFile
    ok = client.post(f"/api/v1/requests/{req['id']}/attachments/", {"file": SimpleUploadedFile("part.png", png())}, format="multipart")
    assert ok.status_code == 201 and ok.json()["kind"] == "image"
    bad = client.post(f"/api/v1/requests/{req['id']}/attachments/", {"file": SimpleUploadedFile("evil.png", b"<script>x</script>")}, format="multipart")
    assert bad.status_code == 400
    att = ok.json()["id"]
    dl = client.get(f"/api/v1/requests/{req['id']}/attachments/{att}/")
    assert dl.status_code == 200 and dl["X-Content-Type-Options"] == "nosniff" and b"".join(dl.streaming_content) == png()
    assert login(world["b_admin"]).get(f"/api/v1/requests/{req['id']}/attachments/{att}/").status_code == 404

    env = envelope_for(world, req["reference"])
    op = login(world["op_eng"], world["a"])
    act = lambda action, **kw: op.post(f"/api/v1/operator/requests/{env.pk}/act/", {"action": action, **kw}, format="json")
    assert act("respond", message="x").status_code == 409  # enquiry-only action
    assert act("create_project").status_code == 409  # acknowledge first
    assert act("acknowledge", quotation_reference="Q-2026-17 (offline)").json()["quotation_reference"] == "Q-2026-17 (offline)"
    done = act("create_project").json()
    assert done["project_code"] == req["reference"]
    assert act("create_project").status_code == 409  # only once
    with tenant_context(world["a"]):
        part = SparePart.objects.get(part_number=f"{req['reference']}-01")
        assert part.status == "draft" and part.project == Project.objects.get(code=req["reference"])
        assert not DigitalPassport.objects.filter(part=part).exists()  # passports stay an engineering step
    assert act("complete").status_code == 409  # must be in progress
    assert act("schedule").json()["status"] == "scheduled"
    assert act("start").json()["status"] == "in_progress"
    assert act("complete").json()["status"] == "completed"
    assert op.get(f"/api/v1/operator/requests/{env.pk}/attachments/{att}/").status_code == 200
    assert client.post(f"/api/v1/requests/{req['id']}/attachments/", {"file": SimpleUploadedFile("late.png", png())}, format="multipart").status_code == 409
    statuses = [e["to_status"] for e in client.get(f"/api/v1/requests/{req['id']}/").json()["events"]]
    assert statuses[-3:] == ["scheduled", "in_progress", "completed"]


def test_request_rows_are_under_tenant_rls(world, catalog):
    manufacturing(login(world["a_admin"]), catalog["part"]["id"])
    with tenant_context(world["b"]):
        assert ClientRequest.objects.count() == 0
        assert RequestEnvelope.objects.count() == 0
    with tenant_context(world["a"]):
        assert ClientRequest.objects.count() == 1
        assert RequestEnvelope.objects.count() == 0  # the envelope lives in the operator tenant only
