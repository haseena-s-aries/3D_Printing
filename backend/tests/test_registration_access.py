"""CN-002: company self-registration with email verification and Aries approval, password reset, Aries Engineer
company/project scoping, protection of Aries-controlled files, and client-to-client isolation (PostgreSQL with RLS)."""
import re

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from rest_framework.test import APIClient

from apps.projects.models import Project
from apps.registrations.models import CompanyRegistration, EmailToken
from apps.servicerequests.models import Notification
from apps.tenancy.context import USER_SETTING, tenant_context, write_setting
from apps.tenancy.models import Membership, Tenant

from .conftest import PASSWORD, login

PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj "
       b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")
NEW_PASSWORD = "Registrant-Pass-2026!"
FORM = {"company_name": "Synthetic Pumps FZE", "trade_licence_number": "TL-0001", "licence_authority": "Test Free Zone",
        "country": "United Arab Emirates", "state": "Sharjah", "city": "Sharjah",
        "address": "Plot 12, Synthetic Industrial Area", "contact_name": "Rana Tester", "job_title": "Engineering manager",
        "email": "rana@synthetic-pumps.test", "phone": "+971 50 000 0000", "password": NEW_PASSWORD,
        "password_confirm": NEW_PASSWORD, "accept_terms": True}


@pytest.fixture
def enabled(settings):
    settings.PUBLIC_REGISTRATION_ENABLED = True
    settings.WEB_BASE_URL = "http://web.test"


def anon():
    return APIClient()


def link_token(mail, kind):
    m = re.search(rf"http://web\.test/{kind}/([A-Za-z0-9_\-]+)", mail.body)
    assert m, mail.body
    return m.group(1)


def registrations():
    with tenant_context(Tenant.objects.get(kind="operator")):
        return list(CompanyRegistration.objects.all())


def unread_titles(user):
    write_setting(USER_SETTING, user.pk)
    return list(Notification.objects.filter(recipient=user).values_list("title", flat=True))


def submit(form=None):
    return anon().post("/api/v1/public/registrations/", form or FORM, format="json")


# ------------------------------------------------------------------ registration

def test_registration_is_disabled_by_default(world):
    r = submit()
    assert r.status_code == 403 and r.json()["error"]["code"] == "registration_disabled"
    assert anon().get("/api/v1/public/registration-config/").json()["registration_enabled"] is False


def test_full_registration_verification_approval_and_login(world, enabled, mailoutbox):
    from apps.accounts.models import User

    r = submit()
    assert r.status_code == 202 and r.json()["status"] == "submitted"
    assert not User.objects.filter(email=FORM["email"]).exists()  # no account before verification
    token = link_token(mailoutbox[-1], "register/verify")
    assert anon().get(f"/api/v1/public/registrations/verify/{token}/").json()["company_name"] == FORM["company_name"]

    # the mailbox holder alone cannot activate it: the registrant's password is required
    bad = anon().post(f"/api/v1/public/registrations/verify/{token}/", {"password": "Wrong-Password-123"}, format="json")
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "password_mismatch"
    ok = anon().post(f"/api/v1/public/registrations/verify/{token}/", {"password": NEW_PASSWORD}, format="json")
    assert ok.status_code == 200 and ok.json()["status"] == "pending_approval"
    again = anon().post(f"/api/v1/public/registrations/verify/{token}/", {"password": NEW_PASSWORD}, format="json")
    assert again.status_code == 400 and again.json()["error"]["code"] == "link_invalid"  # single use

    user = User.objects.get(email=FORM["email"])
    assert not Membership.objects.filter(user=user).exists()  # no tenant access before approval
    assert not Tenant.objects.filter(name=FORM["company_name"]).exists()
    r = anon().post("/api/v1/auth/token/", {"email": FORM["email"], "password": NEW_PASSWORD}, format="json")
    assert r.status_code == 403 and r.json()["error"]["code"] == "registration_pending"
    assert r.json()["error"]["details"]["company_name"] == FORM["company_name"]
    assert any(FORM["company_name"] in t for t in unread_titles(world["op_admin"]))

    admin = login(world["op_admin"])
    pending = admin.get("/api/v1/registrations/", {"status": "pending"}).json()["results"]
    assert [p["company_name"] for p in pending] == [FORM["company_name"]]
    assert "password_hash" not in pending[0]
    r = admin.post(f"/api/v1/registrations/{pending[0]['id']}/approve/", {}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "approved"

    client = Tenant.objects.get(slug=r.json()["client_slug"])
    assert client.kind == "client" and client.name == FORM["company_name"]
    assert Membership.objects.get(user=user, tenant=client).role == "client_admin"
    session = anon().post("/api/v1/auth/token/", {"email": FORM["email"], "password": NEW_PASSWORD}, format="json").json()["session"]
    assert session["tenant"]["slug"] == client.slug and session["membership"]["role"] == "client_admin"
    assert "users.manage" in session["capabilities"]
    assert any("approved" in m.subject for m in mailoutbox)


def test_existing_account_email_gets_identical_response_and_no_registration(world, enabled, mailoutbox):
    r = submit({**FORM, "email": world["a_admin"].email})
    assert r.status_code == 202 and r.json() == submit({**FORM, "email": "new.person@unknown.test"}).json()
    assert not any(reg.email == world["a_admin"].email for reg in registrations())
    assert "already exists" in [m for m in mailoutbox if world["a_admin"].email in m.to][0].body


def test_resubmission_replaces_unverified_and_old_link_stops_working(world, enabled, mailoutbox):
    submit()
    first = link_token(mailoutbox[-1], "register/verify")
    submit({**FORM, "company_name": "Synthetic Pumps Trading FZE"})
    second = link_token(mailoutbox[-1], "register/verify")
    assert anon().get(f"/api/v1/public/registrations/verify/{first}/").status_code == 400
    assert anon().get(f"/api/v1/public/registrations/verify/{second}/").json()["company_name"] == "Synthetic Pumps Trading FZE"
    assert len([r for r in registrations() if r.email == FORM["email"]]) == 1


def _pending(world, mailoutbox, form=None):
    submit(form)
    token = link_token(mailoutbox[-1], "register/verify")
    anon().post(f"/api/v1/public/registrations/verify/{token}/", {"password": (form or FORM)["password"]}, format="json")
    return next(r for r in registrations() if r.email == (form or FORM)["email"])


def test_rejection_shows_message_and_creates_no_organisation(world, enabled, mailoutbox):
    reg = _pending(world, mailoutbox)
    admin = login(world["op_admin"])
    assert admin.post(f"/api/v1/registrations/{reg.pk}/reject/", {}, format="json").json()["error"]["code"] == "message_required"
    r = admin.post(f"/api/v1/registrations/{reg.pk}/reject/", {"message": "Trade licence could not be confirmed.",
                                                               "internal_note": "checked registry"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    r = anon().post("/api/v1/auth/token/", {"email": FORM["email"], "password": NEW_PASSWORD}, format="json")
    err = r.json()["error"]
    assert err["code"] == "registration_rejected" and err["details"]["message"] == "Trade licence could not be confirmed."
    assert "checked registry" not in r.content.decode()  # internal note never shown to the registrant
    assert not Tenant.objects.filter(name=FORM["company_name"]).exists()
    assert admin.post(f"/api/v1/registrations/{reg.pk}/approve/", {}, format="json").status_code == 409


def test_wrong_password_on_login_reveals_nothing_about_registration(world, enabled, mailoutbox):
    _pending(world, mailoutbox)
    r = anon().post("/api/v1/auth/token/", {"email": FORM["email"], "password": "Not-The-Password-1"}, format="json")
    assert r.status_code == 401 and FORM["company_name"] not in r.content.decode()


def test_existing_company_name_is_never_joined_and_flagged_to_admin(world, enabled, mailoutbox):
    form = {**FORM, "company_name": "Client A Energy LLC", "email": "someone@client-a.test"}
    reg = _pending(world, mailoutbox, form)
    admin = login(world["op_admin"])
    detail = admin.get(f"/api/v1/registrations/{reg.pk}/").json()
    assert {"kind": "existing_organisation", "name": "Client A Energy", "slug": "client-a"} in detail["possible_duplicates"]
    r = admin.post(f"/api/v1/registrations/{reg.pk}/approve/", {}, format="json").json()
    assert r["client_slug"] != "client-a"  # approval creates a NEW organisation
    assert not Membership.objects.filter(tenant=world["a"], user__email=form["email"]).exists()


def test_only_aries_admins_review_and_registrations_stay_in_operator_tenant(world, enabled, mailoutbox):
    reg = _pending(world, mailoutbox)
    assert login(world["a_admin"]).get("/api/v1/registrations/").status_code == 403
    assert login(world["op_eng"], world["a"]).post(f"/api/v1/registrations/{reg.pk}/approve/").status_code == 403
    with tenant_context(world["a"]):
        assert CompanyRegistration.objects.count() == 0  # forced RLS: not visible from a client tenant
    with tenant_context(None):
        assert CompanyRegistration.objects.count() == 0


def test_aries_admin_cannot_approve_own_registration(world, enabled):
    op = world["operator"]
    with tenant_context(op):
        reg = CompanyRegistration.objects.create(tenant=op, company_name="Own Co", normalized_name="own", trade_licence_number="X",
                                                 country="AE", contact_name="Self", email=world["op_admin"].email, phone="+97100000000",
                                                 status="pending", user=world["op_admin"])
    r = login(world["op_admin"]).post(f"/api/v1/registrations/{reg.pk}/approve/", {}, format="json")
    assert r.status_code == 403 and r.json()["error"]["code"] == "separation_of_duties"


def test_registration_input_is_validated(world, enabled):
    r = submit({**FORM, "phone": "abc", "accept_terms": False})
    assert r.status_code == 400 and {"phone", "accept_terms"} <= set(r.json()["error"]["details"])
    mismatch = submit({**FORM, "password_confirm": "different-Password-1"})
    assert "password_confirm" in mismatch.json()["error"]["details"]
    weak = submit({**FORM, "password": "short", "password_confirm": "short"})
    assert "password" in weak.json()["error"]["details"]


def test_registration_is_rate_limited(world, enabled, monkeypatch):
    from django.core.cache import cache
    from rest_framework.throttling import ScopedRateThrottle

    cache.clear()
    monkeypatch.setattr(ScopedRateThrottle, "THROTTLE_RATES", {**ScopedRateThrottle.THROTTLE_RATES, "register": "2/hour"})
    codes = [submit({**FORM, "email": f"r{i}@rate.test"}).status_code for i in range(3)]
    cache.clear()
    assert codes == [202, 202, 429]


def test_dev_outbox_is_off_unless_enabled(world, settings):
    settings.DEV_OUTBOX_VIEW = False
    assert anon().get("/api/v1/public/dev-outbox/").status_code == 404


# ------------------------------------------------------------------ password reset

def test_password_reset_flow(world, enabled, mailoutbox):
    unknown = anon().post("/api/v1/public/password-reset/", {"email": "nobody@unknown.test"}, format="json")
    known = anon().post("/api/v1/public/password-reset/", {"email": world["a_user"].email}, format="json")
    assert unknown.status_code == known.status_code == 202 and unknown.json() == known.json()
    old_session = login(world["a_user"])
    token = link_token([m for m in mailoutbox if world["a_user"].email in m.to][-1], "reset-password")
    weak = anon().post(f"/api/v1/public/password-reset/{token}/", {"password": "short", "password_confirm": "short"}, format="json")
    assert weak.status_code == 400
    ok = anon().post(f"/api/v1/public/password-reset/{token}/", {"password": "Brand-New-Pass-2026", "password_confirm": "Brand-New-Pass-2026"}, format="json")
    assert ok.status_code == 200
    assert anon().post(f"/api/v1/public/password-reset/{token}/", {"password": "Another-New-Pass-26"}, format="json").status_code == 400
    assert anon().post("/api/v1/auth/token/", {"email": world["a_user"].email, "password": PASSWORD}, format="json").status_code == 401
    assert anon().post("/api/v1/auth/token/", {"email": world["a_user"].email, "password": "Brand-New-Pass-2026"}, format="json").status_code == 200
    refreshed = anon().post("/api/v1/auth/refresh/", {"refresh": old_session.refresh_token}, format="json")
    assert refreshed.status_code == 401  # earlier sessions were signed out


def test_reset_tokens_expire(world, enabled, mailoutbox):
    from django.utils import timezone

    anon().post("/api/v1/public/password-reset/", {"email": world["a_user"].email}, format="json")
    token = link_token(mailoutbox[-1], "reset-password")
    EmailToken.objects.update(expires_at=timezone.now())
    assert anon().get(f"/api/v1/public/password-reset/{token}/").status_code == 400


# ------------------------------------------------------------------ Aries Engineer scoping

@pytest.fixture
def projects(world):
    eng = login(world["op_eng"], world["a"])
    out = {}
    for code in ("P1", "P2"):
        proj = eng.post("/api/v1/projects/", {"code": code, "name": f"Scan {code}"}, format="json").json()
        part = eng.post("/api/v1/parts/", {"part_number": f"{code}-PART", "name": "x", "project": proj["id"]}, format="json").json()
        passport = eng.post("/api/v1/passports/", {"part": part["id"]}, format="json").json()
        f = eng.post("/api/v1/files/", {"part": part["id"], "file": SimpleUploadedFile(f"{code}.pdf", PDF), "category": "drawing",
                                        "client_visible": "true"},
                     format="multipart").json()
        out[code] = {"project": proj, "part": part, "passport": passport, "file": f}
    return out


def membership_of(world, user, tenant):
    return Membership.objects.get(user=world[user], tenant=world[tenant])


def test_engineer_project_scope_is_enforced_everywhere(world, projects):
    admin = login(world["op_admin"])
    mid = membership_of(world, "op_eng", "a").pk
    r = admin.put(f"/api/v1/clients/{world['a'].pk}/engineers/{mid}/access/",
                  {"scope": "projects", "project_ids": [projects["P1"]["project"]["id"]]}, format="json")
    assert r.status_code == 200 and [p["code"] for p in r.json()["projects"]] == ["P1"]

    eng = login(world["op_eng"], world["a"])
    assert [p["code"] for p in eng.get("/api/v1/projects/").json()["results"]] == ["P1"]
    assert [p["part_number"] for p in eng.get("/api/v1/parts/").json()["results"]] == ["P1-PART"]
    p2 = projects["P2"]
    assert eng.get(f"/api/v1/parts/{p2['part']['id']}/").status_code == 404
    assert eng.get(f"/api/v1/passports/{p2['passport']['id']}/").status_code == 404
    assert eng.get(f"/api/v1/files/{p2['file']['id']}/").status_code == 404
    assert eng.post(f"/api/v1/files/{p2['file']['id']}/versions/1/download-link/", {"variant": "original"}, format="json").status_code == 404
    r = eng.post("/api/v1/parts/", {"part_number": "NEW-P2", "name": "x", "project": p2["project"]["id"]}, format="json")
    assert r.status_code == 400
    r = eng.post("/api/v1/files/", {"part": p2["part"]["id"], "file": SimpleUploadedFile("x.pdf", PDF)}, format="multipart")
    assert r.status_code in (400, 404)
    assert eng.post("/api/v1/projects/", {"code": "P9", "name": "x"}, format="json").status_code == 403
    assert eng.get("/api/v1/dashboard/summary/").json()["parts"]["total"] == 1
    # the client and company-wide staff are unaffected
    assert len(login(world["a_user"]).get("/api/v1/parts/").json()["results"]) == 2
    r = admin.put(f"/api/v1/clients/{world['a'].pk}/engineers/{mid}/access/", {"scope": "company"}, format="json")
    assert r.json()["scope"] == "company" and r.json()["projects"] == []
    assert len(login(world["op_eng"], world["a"]).get("/api/v1/parts/").json()["results"]) == 2


def test_existing_assignments_stay_company_wide(world, projects):
    assert len(login(world["op_eng"], world["a"]).get("/api/v1/parts/").json()["results"]) == 2


def test_project_limited_engineer_cannot_open_requests_of_other_projects(world, projects):
    from apps.servicerequests.models import RequestEnvelope

    client = login(world["a_admin"])
    body = {"request_type": "manufacturing", "part": projects["P2"]["part"]["id"], "quantity": 1, "required_date": "2030-01-01",
            "delivery_location": "Site A", "services": ["Additive manufacturing"], "priority": "urgent", "remarks": "x",
            "client_reference": "PO-1"}
    r = client.post("/api/v1/requests/", body, format="json")
    assert r.status_code == 201, r.content
    ref = r.json()["reference"]
    login(world["op_admin"]).put(f"/api/v1/clients/{world['a'].pk}/engineers/{membership_of(world, 'op_eng', 'a').pk}/access/",
                                 {"scope": "projects", "project_ids": [projects["P1"]["project"]["id"]]}, format="json")
    with tenant_context(world["operator"]):
        env = RequestEnvelope.objects.get(reference=ref)
    r = login(world["op_eng"], world["a"]).get(f"/api/v1/operator/requests/{env.pk}/")
    assert r.status_code == 403 and r.json()["error"]["code"] == "not_assigned_project"


def test_assignment_rules(world, projects):
    admin = login(world["op_admin"])
    # no self-assignment
    r = admin.post(f"/api/v1/clients/{world['b'].pk}/members/", {"email": world["op_admin"].email, "role": "operator_engineer"}, format="json")
    assert r.status_code == 400
    # engineers cannot assign or change scopes, not even their own
    eng = login(world["op_eng"], world["a"])
    mid = membership_of(world, "op_eng", "a").pk
    assert eng.put(f"/api/v1/clients/{world['a'].pk}/engineers/{mid}/access/", {"scope": "company"}, format="json").status_code == 403
    # projects of another client cannot be assigned
    r = admin.put(f"/api/v1/clients/{world['b'].pk}/engineers/{mid}/access/",
                  {"scope": "projects", "project_ids": [projects["P1"]["project"]["id"]]}, format="json")
    assert r.status_code == 404  # op_eng is not assigned to client B at all
    Membership.objects.create(user=world["op_eng"], tenant=world["b"], role="operator_engineer")
    mid_b = membership_of(world, "op_eng", "b").pk
    r = admin.put(f"/api/v1/clients/{world['b'].pk}/engineers/{mid_b}/access/",
                  {"scope": "projects", "project_ids": [projects["P1"]["project"]["id"]]}, format="json")
    assert r.status_code == 400 and r.json()["error"]["code"] == "project_not_found"


def test_unassigned_engineer_cannot_enter_a_client(world, projects):
    r = anon().post("/api/v1/auth/token/", {"email": world["op_eng"].email, "password": PASSWORD, "tenant": "client-b"}, format="json")
    assert r.status_code == 403


def test_client_details_are_audited_and_contain_no_records(world, projects):
    from apps.audit.models import AuditEvent

    d = login(world["op_admin"]).get(f"/api/v1/clients/{world['a'].pk}/details/").json()
    assert d["counts"]["parts"] == 2 and d["aries_staff"][0]["email"] == world["op_eng"].email
    assert "P1-PART" not in str(d)
    with tenant_context(world["a"]):
        assert AuditEvent.objects.filter(action="client.details_viewed").exists()


# ------------------------------------------------------------------ client protection of Aries files

def test_clients_add_supporting_documents_but_cannot_change_aries_files(world, projects):
    client = login(world["a_admin"])
    aries_file = projects["P1"]["file"]
    step = client.post("/api/v1/files/", {"part": projects["P1"]["part"]["id"], "file": SimpleUploadedFile("x.stp", b"ISO-10303-21;\n")},
                       format="multipart")
    assert step.status_code == 403 and step.json()["error"]["code"] == "supporting_documents_only"
    as_drawing = client.post("/api/v1/files/", {"part": projects["P1"]["part"]["id"], "file": SimpleUploadedFile("d.pdf", PDF),
                                                "category": "drawing"}, format="multipart")
    assert as_drawing.status_code == 403
    own = client.post("/api/v1/files/", {"part": projects["P1"]["part"]["id"], "file": SimpleUploadedFile("site-photo-notes.pdf", PDF),
                                         "category": "other"}, format="multipart")
    assert own.status_code == 201
    # Aries-controlled file: no rename, reclassification or new version
    assert client.patch(f"/api/v1/files/{aries_file['id']}/", {"title": "renamed"}, format="json").json()["error"]["code"] == "aries_controlled_file"
    r = client.post(f"/api/v1/files/{aries_file['id']}/versions/", {"file": SimpleUploadedFile("v2.pdf", PDF)}, format="multipart")
    assert r.status_code == 403
    # own supporting document: may rename, may not turn it into an engineering document
    assert client.patch(f"/api/v1/files/{own.json()['id']}/", {"title": "Site notes"}, format="json").status_code == 200
    assert client.patch(f"/api/v1/files/{own.json()['id']}/", {"category": "drawing"}, format="json").status_code == 403
    assert login(world["a_user"]).post("/api/v1/files/", {"part": projects["P1"]["part"]["id"], "file": SimpleUploadedFile("u.pdf", PDF)},
                                       format="multipart").status_code == 403


def test_newly_approved_client_sees_only_its_own_data(world, enabled, mailoutbox, projects):
    reg = _pending(world, mailoutbox)
    slug = login(world["op_admin"]).post(f"/api/v1/registrations/{reg.pk}/approve/", {}, format="json").json()["client_slug"]
    c = APIClient()
    tok = c.post("/api/v1/auth/token/", {"email": FORM["email"], "password": NEW_PASSWORD}, format="json").json()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {tok['access']}")
    assert c.get("/api/v1/parts/").json()["results"] == []
    assert c.get(f"/api/v1/parts/{projects['P1']['part']['id']}/").status_code == 404
    assert c.get(f"/api/v1/files/{projects['P1']['file']['id']}/").status_code == 404
    assert tok["session"]["tenant"]["slug"] == slug
    with tenant_context(Tenant.objects.get(slug=slug)):
        assert Project.objects.count() == 0


def test_invitation_mail_failure_is_logged_and_does_not_undo_the_client(world, settings, caplog):
    """A mail server problem must be visible in the log (not swallowed) and must not roll back the new client."""
    from unittest import mock

    from .test_company_profile import CREATE

    settings.EMAIL_HOST, settings.EMAIL_PORT = "mail.invalid.test", 465
    admin = login(world["op_admin"])
    with mock.patch("apps.tenancy.invitations.send_mail", side_effect=OSError("connection refused")):
        r = admin.post("/api/v1/clients/", {**CREATE, "invite_contact": True}, format="json")
    assert r.status_code == 201, r.content
    assert Tenant.objects.filter(slug=CREATE["slug"]).exists()
    assert f"Invitation email to {CREATE['contact_email']} could not be sent via mail.invalid.test:465 (OSError: connection refused)" \
        in caplog.text
