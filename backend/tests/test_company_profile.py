"""One company profile for both creation routes: self-registration (verified, then approved) and direct creation by an
Aries Admin (contact invited, never marked verified). Existing organisations stay as they are and show what is missing."""
import importlib
import re
from types import SimpleNamespace

import pytest
from django.db import connection

from apps.audit.models import AuditEvent
from apps.registrations.models import CompanyRegistration
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Invitation, Membership, Tenant
from apps.tenancy.profile import REQUIRED

from .conftest import login
from .test_registration_access import FORM, NEW_PASSWORD, anon, enabled, link_token, submit  # noqa: F401

PROFILE = {"name": "Synthetic Valves LLC", "trade_licence_number": "TL-7788", "licence_authority": "Synthetic Economic Department",
           "country": "United Arab Emirates", "state": "Abu Dhabi", "city": "Mussafah", "address": "Warehouse 4, Synthetic Road",
           "contact_name": "Lina Contact", "contact_title": "Maintenance manager", "contact_email": "lina@synthetic-valves.test",
           "contact_phone": "+971 2 000 0000"}
CREATE = {**PROFILE, "slug": "synthetic-valves", "hosting_model": "shared", "region_code": "uaenorth"}
FIELD_FROM_FORM = {"name": "company_name", "trade_licence_number": "trade_licence_number", "licence_authority": "licence_authority",
                   "country": "country", "state": "state", "city": "city", "address": "address", "contact_name": "contact_name",
                   "contact_title": "job_title", "contact_email": "email", "contact_phone": "phone"}


def details(admin, client_id):
    r = admin.get(f"/api/v1/clients/{client_id}/details/")
    assert r.status_code == 200, r.content
    return r.json()


def test_self_registration_profile_becomes_the_organisation_profile(world, enabled, mailoutbox):
    assert submit().status_code == 202
    token = link_token(mailoutbox[-1], "register/verify")
    assert anon().post(f"/api/v1/public/registrations/verify/{token}/", {"password": NEW_PASSWORD}, format="json").status_code == 200
    admin = login(world["op_admin"])
    reg_id = admin.get("/api/v1/registrations/", {"status": "pending"}).json()["results"][0]["id"]
    r = admin.post(f"/api/v1/registrations/{reg_id}/approve/", {}, format="json")
    client = Tenant.objects.get(slug=r.json()["client_slug"])
    d = details(admin, client.pk)
    assert d["origin"] == "self_registration" and d["profile"]["complete"] is True and d["profile"]["missing"] == []
    for field, form_key in FIELD_FROM_FORM.items():
        assert d["profile"]["values"][field] == FORM[form_key], field
    assert d["contact"]["state"] == "registered" and d["contact"]["email_verified"] is True
    assert d["registration"]["state"] == FORM["state"] and d["registration"]["address"] == FORM["address"]


def test_registration_requires_the_same_profile_fields(world, enabled):
    form = {k: v for k, v in FORM.items() if k not in ("licence_authority", "state", "address", "job_title")}
    r = submit(form)
    assert r.status_code == 400
    assert {"licence_authority", "state", "address", "job_title"} <= set(r.json()["error"]["details"])
    bad = submit({**FORM, "phone": "call me"})
    assert bad.status_code == 400 and "phone" in bad.json()["error"]["details"]


def test_admin_creates_company_directly_and_contact_is_only_invited(world, mailoutbox):
    from apps.accounts.models import User

    admin = login(world["op_admin"])
    r = admin.post("/api/v1/clients/", CREATE, format="json")
    assert r.status_code == 201, r.content
    client = Tenant.objects.get(pk=r.json()["id"])
    assert client.slug == "synthetic-valves" and client.hosting_model == "shared" and client.region_code == "uaenorth"
    assert r.json()["profile_complete"] is True
    d = details(admin, client.pk)
    assert d["origin"] == "aries_admin" and d["registration"] is None
    assert d["profile"]["values"] == {**PROFILE}
    # no approval step, but nothing is activated or verified on the contact's behalf
    assert d["contact"]["state"] == "invited" and d["contact"]["email_verified"] is False
    assert not User.objects.filter(email=PROFILE["contact_email"]).exists()
    assert not Membership.objects.filter(tenant=client).exists()
    inv = Invitation.objects.get(tenant=client)
    assert inv.email == PROFILE["contact_email"] and inv.role == "client_admin" and inv.status == "pending"
    assert any(PROFILE["contact_email"] in m.to for m in mailoutbox)
    # the contact proves the mailbox by opening the link; only then is the account active and the email confirmed
    token = re.search(r"/invite/(\S+)", mailoutbox[-1].body).group(1)
    assert anon().post(f"/api/v1/invitation-acceptance/{token}/", {"password": "Contact-Pass-2026!"}, format="json").status_code == 200
    d = details(admin, client.pk)
    assert d["contact"]["state"] == "accepted" and d["contact"]["email_verified"] is True
    assert Membership.objects.get(tenant=client, user__email=PROFILE["contact_email"]).role == "client_admin"
    with tenant_context(client):
        assert set(AuditEvent.objects.values_list("action", flat=True)) >= {"client.created", "invitation.created"}


def test_admin_create_without_invitation_and_validation(world):
    admin = login(world["op_admin"])
    r = admin.post("/api/v1/clients/", {**CREATE, "invite_contact": False}, format="json")
    assert r.status_code == 201
    client = Tenant.objects.get(pk=r.json()["id"])
    assert not Invitation.objects.filter(tenant=client).exists()
    assert details(admin, client.pk)["contact"]["state"] == "not_invited"
    missing = admin.post("/api/v1/clients/", {"name": "Thin Co", "slug": "thin-co"}, format="json")
    assert missing.status_code == 400 and set(REQUIRED) - {"name"} <= set(missing.json()["error"]["details"])
    dup = admin.post("/api/v1/clients/", {**CREATE, "name": "Other"}, format="json")
    assert dup.status_code == 400 and "slug" in dup.json()["error"]["details"]
    phone = admin.post("/api/v1/clients/", {**CREATE, "slug": "phone-co", "contact_phone": "n/a"}, format="json")
    assert phone.status_code == 400 and "contact_phone" in phone.json()["error"]["details"]


def test_existing_company_shows_missing_fields_and_admin_updates_keep_identifiers(world):
    a = world["a"]
    members_before = sorted(Membership.objects.filter(tenant=a).values_list("user__email", "role", "is_active"))
    admin = login(world["op_admin"])
    d = details(admin, a.pk)
    assert d["profile"]["complete"] is False and set(d["profile"]["missing"]) == set(REQUIRED) - {"name"}
    assert d["profile"]["values"]["trade_licence_number"] == ""  # nothing invented
    r = admin.patch(f"/api/v1/clients/{a.pk}/profile/", {"trade_licence_number": "TL-A-1", "country": "Oman"}, format="json")
    assert r.status_code == 200 and "trade_licence_number" not in r.json()["missing"]
    a.refresh_from_db()
    assert a.trade_licence_number == "TL-A-1" and a.country == "Oman" and a.contact_email == "" and a.slug == "client-a"
    blank = admin.patch(f"/api/v1/clients/{a.pk}/profile/", {"country": ""}, format="json")
    assert blank.status_code == 400
    # the short identifier is fixed after creation
    admin.patch(f"/api/v1/clients/{a.pk}/", {"slug": "renamed", "hosting_model": "dedicated"}, format="json")
    a.refresh_from_db()
    assert a.slug == "client-a" and a.hosting_model == "dedicated"
    assert sorted(Membership.objects.filter(tenant=a).values_list("user__email", "role", "is_active")) == members_before
    with tenant_context(a):
        ev = AuditEvent.objects.filter(action="client.profile_updated").first()
        assert ev is not None and ev.data["fields"] == ["country", "trade_licence_number"]


def test_only_aries_admin_creates_or_updates_profiles(world):
    for user, tenant in ((world["op_eng"], world["operator"]), (world["a_admin"], None)):
        c = login(user, tenant)
        assert c.post("/api/v1/clients/", CREATE, format="json").status_code == 403
        assert c.patch(f"/api/v1/clients/{world['a'].pk}/profile/", {"country": "X"}, format="json").status_code in (403, 404)
        assert c.get(f"/api/v1/clients/{world['b'].pk}/details/").status_code in (403, 404)


def test_backfill_copies_only_submitted_values_into_blank_fields(world):
    op, a, b = world["operator"], world["a"], world["b"]
    a.country = "Kept Country"
    a.save(update_fields=["country"])
    with tenant_context(op):
        CompanyRegistration.objects.create(tenant=op, company_name="Client A Energy", normalized_name="client a energy",
                                           trade_licence_number="TL-REG", licence_authority="Reg Authority", country="Submitted Country",
                                           city="Reg City", contact_name="Reg Person", job_title="", email="reg@a.test",
                                           phone="+971 4 000 0000", status="approved", client_tenant=a)
    mod = importlib.import_module("apps.registrations.migrations.0004_backfill_company_profile")
    mod.backfill(None, SimpleNamespace(connection=connection))
    a.refresh_from_db()
    b.refresh_from_db()
    assert a.trade_licence_number == "TL-REG" and a.contact_email == "reg@a.test" and a.city == "Reg City"
    assert a.country == "Kept Country"  # an existing value is never overwritten
    assert a.contact_title == "" and a.state == "" and a.address == ""  # not submitted: stays missing
    assert b.trade_licence_number == "" and b.contact_email == ""  # other organisations untouched


def test_audit_history_filter_for_one_client(world):
    """Client Management → Audit History: events this organisation recorded about one company, same tenant scope."""
    admin = login(world["op_admin"])
    r = admin.post("/api/v1/clients/", CREATE, format="json")
    cid = r.json()["id"]
    admin.post(f"/api/v1/clients/{cid}/members/", {"email": "member@synthetic-valves.test", "role": "client_user",
                                                     "password": "Member-Pass-2026!"}, format="json")
    admin.get(f"/api/v1/clients/{cid}/details/")
    admin.get(f"/api/v1/clients/{world['b'].pk}/details/")
    events = admin.get("/api/v1/audit-events/", {"client": cid, "page_size": 100}).json()["results"]
    actions = {e["action"] for e in events}
    assert {"client.created", "invitation.created", "membership.created", "client.details_viewed"} <= actions
    assert all(e["object_id"] != str(world["b"].pk) for e in events)  # another company's events are not included
    quiet = admin.get("/api/v1/audit-events/", {"client": cid, "exclude_views": "true", "page_size": 100}).json()["results"]
    assert quiet and not any(e["action"].endswith("_viewed") for e in quiet)
    assert admin.get("/api/v1/audit-events/", {"client": "not-a-uuid"}).json()["results"] == []
    # a client administrator only ever sees its own organisation's trail, whatever company is named
    a_admin = login(world["a_admin"])
    leaked = a_admin.get("/api/v1/audit-events/", {"client": cid, "page_size": 100}).json()["results"]
    assert all(e["action"] != "invitation.created" or "synthetic-valves" not in str(e["data"]) for e in leaked)
    assert login(world["op_eng"], world["operator"]).get("/api/v1/audit-events/", {"client": cid}).status_code == 403


def test_client_admin_reads_own_company_profile_only(world):
    """Post-UAT 2.2: read-only for the Client Administrator; other roles are refused; editing stays with the Aries Admin."""
    world["a"].city = "Sharjah"
    world["a"].save(update_fields=["city"])
    r = login(world["a_admin"]).get("/api/v1/organisation/profile/")
    assert r.status_code == 200 and r.json()["values"]["name"] == "Client A Energy" and r.json()["editable"] is False
    assert r.json()["values"]["city"] == "Sharjah"
    assert login(world["a_user"]).get("/api/v1/organisation/profile/").status_code == 403
    assert login(world["op_eng"], world["a"]).get("/api/v1/organisation/profile/").status_code == 403
