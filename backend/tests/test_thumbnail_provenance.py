"""Provenance-aware contract route for Aries Admin inventory thumbnails (ADMIN_THUMBNAIL_PROVENANCE_ENABLED).

A photo reaches the Aries Admin without client consent only when its uploader claimed it as an Aries capture and Aries QA
(never the claimant) confirmed it, the company's contract authorization was recorded by an Aries Admin and verified by a
different person against the signed agreement, is within its dates and covers the part's project, no client objection is
unresolved (only a designated objection reviewer acting under the configured authority, independent of the recorder,
verifier and photo claimants, can resolve one), and the photo is released to the client. Client-uploaded and unknown-origin photos never qualify. Every
condition is re-checked on each thumbnail request, so earlier links die with any change; all records are append-only."""
import io
from datetime import date, timedelta

import pytest
from django.db import DatabaseError, transaction
from PIL import Image

from apps.audit.models import AuditEvent
from apps.files.models import ContractAuthorization, ContractAuthorizationEvent, ImageOriginEvent
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Membership, Role

from .conftest import login, make_user
from .test_files import upload
from .test_w2_catalog import jpeg_with_gps

CONSENT = "/api/v1/company/admin-thumbnail-consent/"
TODAY = date.today()
EXCERPT = "Clause 14.2 (synthetic): Aries may use images it captures during contracted scanning for internal administration."


@pytest.fixture
def pv(world, settings):
    settings.ADMIN_THUMBNAIL_CONSENT_ENABLED = True
    settings.ADMIN_THUMBNAIL_PROVENANCE_ENABLED = True
    settings.CONTRACT_OBJECTION_REVIEWERS = ["op.gov@example.test"]
    settings.CONTRACT_OBJECTION_AUTHORITY = "SYN-DELEGATION-T1 (synthetic test delegation)"
    w = world
    eng = login(w["op_eng"], w["a"])
    p1 = eng.post("/api/v1/projects/", {"code": "SCAN-1", "name": "Pump room scan"}, format="json").json()
    p2 = eng.post("/api/v1/projects/", {"code": "SCAN-2", "name": "Compressor scan"}, format="json").json()

    def part(number, project=None):
        body = {"part_number": number, "name": f"Part {number}", **({"project": project["id"]} if project else {})}
        r = eng.post("/api/v1/parts/", body, format="json")
        assert r.status_code == 201, r.content
        return r.json()

    parts = {n: part(n, pr) for n, pr in (("SC-100", p1), ("SC-200", p2), ("SC-300", p1), ("CU-400", p1), ("NO-500", p1))}
    photos = {
        "SC-100": upload(eng, parts["SC-100"]["id"], "scan1.jpg", jpeg_with_gps(), category="photo").json(),
        "SC-200": upload(eng, parts["SC-200"]["id"], "scan2.jpg", jpeg_with_gps(), category="photo").json(),
        "SC-300": upload(eng, parts["SC-300"]["id"], "scan3.jpg", jpeg_with_gps(), category="photo", client_visible="false").json(),
    }
    r = upload(login(w["a_eng"]), parts["CU-400"]["id"], "client.jpg", jpeg_with_gps(), category="photo")
    assert r.status_code == 201, r.content
    photos["CU-400"] = r.json()
    qa = make_user("op.qa@example.test", w["operator"], Role.OPERATOR_QA)
    Membership.objects.create(user=qa, tenant=w["a"], role=Role.OPERATOR_QA)
    eng2 = make_user("op.eng2@example.test", w["operator"], Role.OPERATOR_ENGINEER)
    Membership.objects.create(user=eng2, tenant=w["a"], role=Role.OPERATOR_ENGINEER)
    gov = make_user("op.gov@example.test", w["operator"], Role.OPERATOR_QA)  # designated objection reviewer
    return {"w": w, "eng": eng, "eng2": login(eng2, w["a"]), "qa": login(qa, w["a"]), "qa_op": login(qa, w["operator"]), "gov": login(gov),
            "admin": login(w["op_admin"]), "a_admin": login(w["a_admin"]), "b_admin": login(w["b_admin"]),
            "p1": p1, "p2": p2, "parts": parts, "photos": photos}


def origin(c, photo, n=1):
    return f"/api/v1/files/{photo['id']}/versions/{n}/origin/"


def claim(pv, key="SC-100", who="eng", **extra):
    body = {"action": "claim", "capture_reference": "SYN-SCAN-0001", "capture_date": TODAY.isoformat(), **extra}
    return pv[who].post(origin(None, pv["photos"][key]), body, format="json")


def qa(pv, key="SC-100", action="confirm", who="qa", note="Checked scan log SYN-SCAN-0001 and site sheet."):
    return pv[who].post(origin(None, pv["photos"][key]), {"action": action, "note": note}, format="json")


def contract_url(pv):
    return f"/api/v1/admin/clients/{pv['w']['a'].pk}/thumbnail-contract/"


def record_auth(pv, who="admin", **extra):
    body = {"contract_reference": "SYN-MSA-2026-001", "clause_excerpt": EXCERPT, "effective_from": (TODAY - timedelta(days=30)).isoformat(),
            "effective_until": (TODAY + timedelta(days=365)).isoformat(), "scope": "projects", "project_ids": [pv["p1"]["id"]], **extra}
    return pv[who].post(contract_url(pv), body, format="json")


def auth_event(pv, auth_id, action, who="qa_op", **extra):
    body = {"action": action, "note": "Checked against the signed synthetic agreement SYN-MSA-2026-001, page 9.", **extra}
    if action == "verify":
        body.setdefault("checked_against_signed_agreement", True)
    return pv[who].post(f"{contract_url(pv)}{auth_id}/events/", body, format="json")


def active_contract(pv):
    r = record_auth(pv)
    assert r.status_code == 201, r.content
    aid = r.json()["authorization"]["id"]
    assert auth_event(pv, aid, "verify").status_code == 201
    return aid


def rows(pv):
    r = pv["admin"].get("/api/v1/admin/inventory/", {"page_size": 200})
    assert r.status_code == 200, r.content
    return {x["part_number"]: x for x in r.json()["results"]}, {c["name"]: c for c in r.json()["clients"]}


def fetch(pv, token):
    return pv["admin"].get(f"/api/v1/admin/inventory/thumbnails/{token}/")


def confirmed_and_active(pv):
    assert claim(pv).status_code == 201
    assert qa(pv).status_code == 201
    return active_contract(pv)


def test_switched_off_closes_every_new_endpoint(pv, settings):
    settings.ADMIN_THUMBNAIL_PROVENANCE_ENABLED = False
    assert claim(pv).status_code == 404
    assert pv["admin"].get(contract_url(pv)).status_code == 403  # capability withdrawn with the flag
    assert pv["a_admin"].get(CONSENT).json()["contract"] == {"enabled": False}
    r, _ = rows(pv)
    assert all(x["preview"] is None for x in r.values())


def test_origin_claims_need_the_uploader_and_never_cover_client_photos(pv):
    r = claim(pv, "CU-400")  # client-uploaded photo: never an Aries capture
    assert r.status_code == 403 and r.json()["error"]["code"] == "client_uploaded"
    r = claim(pv, who="eng2")  # an Aries role is not proof: only the uploader of that version can claim
    assert r.status_code == 403 and r.json()["error"]["code"] == "not_uploader"
    for who in ("qa", "a_admin"):
        assert claim(pv, who=who).status_code == 403
    assert claim(pv, who="admin").status_code == 403  # the Aries Admin has no origin rights (and no client membership)
    r = claim(pv, capture_reference="", note="short")
    assert r.status_code == 400 and r.json()["error"]["code"] == "evidence_required"
    r = claim(pv, capture_reference="", note="Historical photo from the 2025 pump room scan, no job number in the app.")
    assert r.status_code == 201 and r.json()["state"] == "claimed"
    assert claim(pv).status_code == 409  # no duplicate claims
    with tenant_context(pv["w"]["a"]):  # nothing else was classified
        assert ImageOriginEvent.objects.count() == 1


def test_only_qa_confirms_and_never_their_own_claim(pv):
    claim(pv)
    assert qa(pv, who="eng").status_code == 403  # the claimant cannot confirm (no confirm right)
    assert qa(pv, who="eng2").status_code == 403  # nor another Aries Engineer
    r = qa(pv, note="ok")
    assert r.status_code == 400 and r.json()["error"]["code"] == "note_required"
    queue = pv["qa"].get("/api/v1/files/origin-claims/").json()["results"]
    assert [x["part_number"] for x in queue] == ["SC-100"]
    r = qa(pv)
    assert r.status_code == 201 and r.json()["state"] == "confirmed"
    assert pv["qa"].get("/api/v1/files/origin-claims/").json()["results"] == []
    with tenant_context(pv["w"]["a"]):
        assert AuditEvent.objects.filter(action="files.image_origin_claimed").count() == 1
        assert AuditEvent.objects.filter(action="files.image_origin_confirmed").count() == 1


def test_contract_authorization_needs_an_independent_verifier(pv):
    for who in ("a_admin", "qa_op"):  # only an Aries Admin records; clients have no access at all
        assert record_auth(pv, who=who).status_code == 403
    r = record_auth(pv, clause_excerpt="too short")
    assert r.status_code == 400 and r.json()["error"]["code"] == "excerpt_required"
    r = record_auth(pv, effective_until=(TODAY - timedelta(days=60)).isoformat())
    assert r.status_code == 400 and r.json()["error"]["code"] == "dates_invalid"
    r = record_auth(pv)
    assert r.status_code == 201 and r.json()["status"] == "pending_verification"
    aid = r.json()["authorization"]["id"]
    assert record_auth(pv).status_code == 409  # one pending claim at a time
    r = auth_event(pv, aid, "verify", who="admin")  # self-verification attempt
    assert r.status_code == 403 and r.json()["error"]["code"] == "self_verification"
    r = auth_event(pv, aid, "verify", checked_against_signed_agreement=False)
    assert r.status_code == 400 and r.json()["error"]["code"] == "attestation_required"
    r = auth_event(pv, aid, "verify")
    assert r.status_code == 201 and r.json()["status"] == "active"
    with tenant_context(pv["w"]["a"]):
        assert AuditEvent.objects.filter(action="contracts.thumbnail_authorization_recorded").count() == 1
        assert AuditEvent.objects.filter(action="contracts.thumbnail_authorization_verified").count() == 1
    with tenant_context(pv["w"]["operator"]):
        assert AuditEvent.objects.filter(action="contracts.thumbnail_authorization_verified", object_id=aid).count() == 1


def test_unverified_origin_or_unverified_contract_shows_nothing(pv):
    claim(pv)  # claimed only
    active_contract(pv)
    r, clients = rows(pv)
    assert r["SC-100"]["preview"] is None and clients["Client A Energy"]["contract_status"] == "active"
    assert clients["Client A Energy"]["thumbnail_route"] == "contract"  # the route is open, but no photo is confirmed yet


def test_contract_route_shows_only_confirmed_released_in_scope_aries_photos(pv):
    for key in ("SC-200", "SC-300"):
        claim(pv, key)
        qa(pv, key)
    aid = confirmed_and_active(pv)
    r, clients = rows(pv)
    assert clients["Client A Energy"]["thumbnail_route"] == "contract" and clients["Client B Marine"]["thumbnails_allowed"] is False
    assert r["SC-100"]["preview"]["route"] == "contract"
    assert r["SC-200"]["preview"] is None  # confirmed, but its project is outside the authorization's scope
    assert r["SC-300"]["preview"] is None  # confirmed, but not released to the client
    assert r["CU-400"]["preview"] is None  # client-uploaded: consent route only
    assert r["NO-500"]["preview"] is None  # no photo: neutral fallback
    t = fetch(pv, r["SC-100"]["preview"]["token"])
    assert t.status_code == 200 and "no-store" in t["Cache-Control"]
    with Image.open(io.BytesIO(b"".join(t.streaming_content))) as img:
        assert max(img.size) <= 480 and not img.getexif()
    with tenant_context(pv["w"]["a"]):
        ev = AuditEvent.objects.get(action="inventory.admin_thumbnail_viewed")
        assert ev.data["route"] == "contract" and ev.data["authorization"] == aid
    state = pv["a_admin"].get(CONSENT).json()["contract"]
    assert state["status"] == "active" and state["photos"] == {"confirmed_aries_captures": 2, "shown_through_contract": 1}
    assert state["authorization"]["recorded_by"] == "Aries Admin" and "op.admin" not in str(state)  # roles, not staff identities
    assert pv["b_admin"].get(CONSENT).json()["contract"]["status"] == "none"  # company isolation


def test_explicit_client_objection_holds_the_route_until_independent_review(pv):
    aid = confirmed_and_active(pv)
    old = rows(pv)[0]["SC-100"]["preview"]["token"]
    r = pv["a_admin"].post(CONSENT, {"allow": False, "note": "We do not want Aries Admin to see our photos."}, format="json")
    assert r.status_code == 201 and r.json()["contract"]["status"] == "on_hold"  # explicit "Not allowed" with no earlier grant
    assert fetch(pv, old).status_code == 404
    assert rows(pv)[0]["SC-100"]["preview"] is None
    r = auth_event(pv, aid, "review", who="admin", outcome="proceed", note="x" * 40)
    assert r.status_code == 403 and r.json()["error"]["code"] == "no_review_authority"  # recorder, and not designated
    r = auth_event(pv, aid, "review", outcome="proceed", note="x" * 40)  # the verifier: verification gives no such right
    assert r.status_code == 403 and r.json()["error"]["code"] == "no_review_authority"
    r = auth_event(pv, aid, "review", who="gov", outcome="proceed", note="too short")
    assert r.status_code == 400
    r = auth_event(pv, aid, "review", who="gov", outcome="sustain", note="Client objection reviewed with the account owner; it is upheld.")
    assert r.status_code == 201 and r.json()["status"] == "objection_sustained"
    assert rows(pv)[0]["SC-100"]["preview"] is None
    # a later client decision needs a fresh review: allow, then object again
    from apps.files.admin_thumbnails import TERMS_VERSION
    pv["a_admin"].post(CONSENT, {"allow": True, "confirm_terms_version": TERMS_VERSION}, format="json")
    assert rows(pv)[0]["SC-100"]["preview"]["route"] == "consent"
    pv["a_admin"].post(CONSENT, {"allow": False}, format="json")
    assert pv["admin"].get(contract_url(pv)).json()["status"] == "on_hold"
    r = auth_event(pv, aid, "review", who="gov", outcome="proceed", note="Signed clause 14.2 covers internal use; objection discussed and documented.")
    assert r.status_code == 201 and r.json()["status"] == "active"
    assert r.json()["history"][0]["events"][0]["authority"].startswith("SYN-DELEGATION-T1")
    new = rows(pv)[0]["SC-100"]["preview"]
    assert new["route"] == "contract" and fetch(pv, new["token"]).status_code == 200
    assert fetch(pv, old).status_code == 404  # links from before the objection never come back
    client = pv["a_admin"].get(CONSENT).json()["contract"]
    assert client["review"]["outcome"].startswith("Client objection reviewed") and client["objection"] is not None
    assert client["review"]["authority"].startswith("SYN-DELEGATION-T1")
    with tenant_context(pv["w"]["a"]):
        assert AuditEvent.objects.filter(action__startswith="contracts.thumbnail_authorization_conflict").count() == 2


def test_expired_or_ended_contract_blocks_earlier_links(pv, monkeypatch):
    aid = confirmed_and_active(pv)
    token = rows(pv)[0]["SC-100"]["preview"]["token"]
    from apps.files import thumbnail_provenance
    monkeypatch.setattr(thumbnail_provenance.timezone, "localdate", lambda: TODAY + timedelta(days=400))
    assert fetch(pv, token).status_code == 404  # expired
    assert pv["admin"].get(contract_url(pv)).json()["status"] == "expired" and rows(pv)[0]["SC-100"]["preview"] is None
    monkeypatch.undo()
    assert fetch(pv, token).status_code == 200
    assert auth_event(pv, aid, "end", who="admin", note="Synthetic contract terminated.").status_code == 201
    assert fetch(pv, token).status_code == 404
    assert rows(pv)[0]["SC-100"]["preview"] is None


def test_an_already_expired_authorization_never_activates(pv):
    claim(pv)
    qa(pv)
    r = record_auth(pv, effective_from=(TODAY - timedelta(days=400)).isoformat(), effective_until=(TODAY - timedelta(days=1)).isoformat())
    auth_event(pv, r.json()["authorization"]["id"], "verify")
    assert pv["admin"].get(contract_url(pv)).json()["status"] == "expired"
    assert rows(pv)[0]["SC-100"]["preview"] is None


def test_withdrawn_origin_new_version_or_lost_scope_block_earlier_links(pv):
    confirmed_and_active(pv)
    token = rows(pv)[0]["SC-100"]["preview"]["token"]
    assert qa(pv, action="withdraw", note="Photo turned out to be from the client's own archive.").status_code == 201
    assert fetch(pv, token).status_code == 404
    claim(pv)
    qa(pv)
    token = rows(pv)[0]["SC-100"]["preview"]["token"]
    assert fetch(pv, token).status_code == 200
    # part moved to a project the authorization does not cover
    assert pv["eng"].patch(f"/api/v1/parts/{pv['parts']['SC-100']['id']}/", {"project": pv["p2"]["id"]}, format="json").status_code == 200
    assert fetch(pv, token).status_code == 404
    pv["eng"].patch(f"/api/v1/parts/{pv['parts']['SC-100']['id']}/", {"project": pv["p1"]["id"]}, format="json")
    assert fetch(pv, token).status_code == 200
    # client visibility removed
    assert pv["eng"].patch(f"/api/v1/files/{pv['photos']['SC-100']['id']}/", {"client_visible": False}, format="json").status_code == 200
    assert fetch(pv, token).status_code == 404
    pv["eng"].patch(f"/api/v1/files/{pv['photos']['SC-100']['id']}/", {"client_visible": True}, format="json")
    assert fetch(pv, token).status_code == 200
    # a new, unclaimed version replaces the confirmed one
    from django.core.files.uploadedfile import SimpleUploadedFile
    r = pv["eng"].post(f"/api/v1/files/{pv['photos']['SC-100']['id']}/versions/",
                       {"file": SimpleUploadedFile("scan1b.jpg", jpeg_with_gps(), content_type="image/jpeg")}, format="multipart")
    assert r.status_code == 201, r.content
    assert fetch(pv, token).status_code == 404 and rows(pv)[0]["SC-100"]["preview"] is None


def test_tokens_cross_company_and_originals(pv):
    confirmed_and_active(pv)
    token = rows(pv)[0]["SC-100"]["preview"]["token"]
    for c in (pv["a_admin"], pv["b_admin"], pv["eng"], pv["qa"]):
        assert c.get(f"/api/v1/admin/inventory/thumbnails/{token}/").status_code == 403
    w = pv["w"]
    assert pv["admin"].get(f"/api/v1/admin/clients/{w['b'].pk}/thumbnail-contract/").json()["status"] == "none"
    aid = pv["admin"].get(contract_url(pv)).json()["authorization"]["id"]
    assert pv["admin"].post(f"/api/v1/admin/clients/{w['b'].pk}/thumbnail-contract/{aid}/events/",
                            {"action": "end", "note": "cross-company attempt"}, format="json").status_code == 404
    photo = pv["photos"]["SC-100"]
    admin = pv["admin"]
    assert admin.get(f"/api/v1/files/{photo['id']}/").status_code == 404
    assert admin.get(f"/api/v1/files/{photo['id']}/versions/1/thumbnail/").status_code == 404
    assert admin.post(f"/api/v1/files/{photo['id']}/versions/1/download-link/", {"variant": "original"}, format="json").status_code == 404
    assert admin.get(origin(None, photo)).status_code == 403
    assert pv["a_admin"].get(origin(None, photo)).status_code == 403  # origin records are Aries-internal
    assert "SC-100" not in str(pv["b_admin"].get(CONSENT).json())


def test_evidence_is_append_only_and_isolated(pv):
    confirmed_and_active(pv)
    w = pv["w"]
    with tenant_context(w["a"]):
        for model in (ImageOriginEvent, ContractAuthorization, ContractAuthorizationEvent):
            row = model.objects.first()
            with pytest.raises(DatabaseError), transaction.atomic():
                model.objects.filter(pk=row.pk).update(created_at=row.created_at)
            with pytest.raises(DatabaseError), transaction.atomic():
                model.objects.filter(pk=row.pk).delete()
    with tenant_context(w["b"]):
        assert not ImageOriginEvent.objects.exists() and not ContractAuthorization.objects.exists()


def object_and_activate(pv):
    aid = confirmed_and_active(pv)
    pv["a_admin"].post(CONSENT, {"allow": False, "note": "We object."}, format="json")
    return aid


def test_without_a_configured_authority_disputed_routes_stay_on_hold(pv, settings):
    settings.CONTRACT_OBJECTION_AUTHORITY = ""
    aid = object_and_activate(pv)
    for who in ("gov", "qa_op", "admin"):
        r = auth_event(pv, aid, "review", who=who, outcome="proceed", note="x" * 40)
        assert r.status_code == 403 and r.json()["error"]["code"] == "no_review_authority"
    body = pv["admin"].get(contract_url(pv)).json()
    assert body["status"] == "on_hold" and body["objection_authority"] == {"configured": False, "reference": ""}
    assert body["can"]["review"] is False and "No objection-review authority" in body["review_block"]
    assert rows(pv)[0]["SC-100"]["preview"] is None


def test_designated_reviewers_must_be_independent_of_recorder_verifier_and_claimants(pv, settings, world):
    # make the recorder and the verifier designated reviewers too: still refused for this authorization
    settings.CONTRACT_OBJECTION_REVIEWERS = ["op.gov@example.test", "op.admin@example.test", "op.qa@example.test", "op.dual@example.test"]
    # a person who is Aries QA in the Aries organisation and also uploaded and claimed a covered photo as an engineer
    dual = make_user("op.dual@example.test", world["operator"], Role.OPERATOR_QA)
    Membership.objects.create(user=dual, tenant=world["a"], role=Role.OPERATOR_ENGINEER)
    dual_eng = login(dual, world["a"])
    photo = upload(dual_eng, pv["parts"]["NO-500"]["id"], "dual.jpg", jpeg_with_gps(), category="photo").json()
    assert dual_eng.post(origin(None, photo), {"action": "claim", "capture_reference": "SYN-SCAN-0002"}, format="json").status_code == 201
    aid = object_and_activate(pv)
    r = auth_event(pv, aid, "review", who="admin", outcome="proceed", note="x" * 40)
    assert r.status_code == 403 and r.json()["error"]["code"] == "self_review"
    r = auth_event(pv, aid, "review", who="qa_op", outcome="proceed", note="x" * 40)
    assert r.status_code == 403 and r.json()["error"]["code"] == "not_independent"
    r = login(dual, world["operator"]).post(f"{contract_url(pv)}{aid}/events/", {"action": "review", "outcome": "proceed", "note": "x" * 40}, format="json")
    assert r.status_code == 403 and r.json()["error"]["code"] == "not_independent"
    assert pv["gov"].get(contract_url(pv)).json()["can"]["review"] is True
    assert pv["qa_op"].get(contract_url(pv)).json()["can"]["review"] is False


def test_reviews_count_only_under_authority_and_while_the_reviewer_is_designated(pv, settings):
    aid = object_and_activate(pv)
    w = pv["w"]
    with tenant_context(w["a"]):  # a review recorded without any authority (as before this rule) resolves nothing
        auth = ContractAuthorization.objects.get(pk=aid)
        from apps.files.admin_thumbnails import current
        ContractAuthorizationEvent.objects.create(tenant=w["a"], authorization=auth, event="conflict_proceed", objection=current(w["a"]),
                                                  note="legacy review", actor_name="x", actor_role="operator_qa", sequence=99,
                                                  created_by=w["op_admin"])
    assert pv["admin"].get(contract_url(pv)).json()["status"] == "on_hold"
    r = auth_event(pv, aid, "review", who="gov", outcome="proceed", note="Objection weighed against clause 14.2 under delegation T1.")
    assert r.status_code == 201 and r.json()["status"] == "active"
    token = rows(pv)[0]["SC-100"]["preview"]["token"]
    assert fetch(pv, token).status_code == 200
    settings.CONTRACT_OBJECTION_REVIEWERS = []  # the designation is withdrawn: the route is disputed again
    assert pv["admin"].get(contract_url(pv)).json()["status"] == "on_hold"
    assert fetch(pv, token).status_code == 404 and rows(pv)[0]["SC-100"]["preview"] is None
    with tenant_context(w["a"]):
        ev = AuditEvent.objects.filter(action="contracts.thumbnail_authorization_conflict_proceed").latest("created_at")
        assert ev.data["authority"].startswith("SYN-DELEGATION-T1") and ev.data["rationale"].startswith("Objection weighed")


def test_contract_list_shows_waiting_actions_per_person(pv):
    r = record_auth(pv)
    rows_admin = {c["name"]: c for c in pv["admin"].get("/api/v1/admin/thumbnail-contracts/").json()["results"]}
    rows_qa = {c["name"]: c for c in pv["qa_op"].get("/api/v1/admin/thumbnail-contracts/").json()["results"]}
    a = "Client A Energy"
    assert rows_admin[a]["status"] == "pending_verification" and rows_admin[a]["awaiting_verification"] is False  # the recorder
    assert rows_qa[a]["awaiting_verification"] is True and rows_qa["Client B Marine"]["status"] == "none"
    auth_event(pv, r.json()["authorization"]["id"], "verify")
    pv["a_admin"].post(CONSENT, {"allow": False}, format="json")
    rows_gov = {c["name"]: c for c in pv["gov"].get("/api/v1/admin/thumbnail-contracts/").json()["results"]}
    assert rows_gov[a]["objection_on_hold"] is True and rows_gov[a]["awaiting_my_review"] is True
    for c in (pv["a_admin"], pv["eng"], pv["qa"]):
        assert c.get("/api/v1/admin/thumbnail-contracts/").status_code == 403



def test_assigned_qa_is_offered_the_aries_organisation_only_for_contract_duties(pv, settings):
    from rest_framework.test import APIClient

    from .conftest import PASSWORD
    body = {"email": "op.qa@example.test", "password": PASSWORD}
    r = APIClient().post("/api/v1/auth/token/", body, format="json")
    assert r.status_code == 400 and {t["slug"] for t in r.json()["error"]["details"]["tenants"]} == {"operator", "client-a"}
    settings.ADMIN_THUMBNAIL_PROVENANCE_ENABLED = False  # without contract duties the assigned QA works inside clients only
    r = APIClient().post("/api/v1/auth/token/", body, format="json")
    assert r.status_code == 200 and r.json()["session"]["tenant"]["slug"] == "client-a"
