"""Server-side permission and tenant checks on document endpoints and PDF previews, and the provisional AMSL field."""
import pytest

from apps.tenancy.models import Membership

from .conftest import login
from .test_files import DWG_BYTES, PDF_BYTES, STEP_BYTES, upload


@pytest.fixture
def docs(world):
    eng = login(world["op_eng"], world["a"])
    part = eng.post("/api/v1/parts/", {"part_number": "DOC-1", "name": "Bracket"}, format="json").json()
    p = eng.post("/api/v1/passports/", {"part": part["id"]}, format="json").json()
    files = {name: upload(eng, part["id"], name, data, passport=p["id"]).json()
             for name, data in (("spec.pdf", PDF_BYTES), ("part.stp", STEP_BYTES), ("drawing.dwg", DWG_BYTES))}
    return eng, p, files


def link(c, f, variant):
    return c.post(f"/api/v1/files/{f['id']}/versions/1/download-link/", {"variant": variant}, format="json")


@pytest.mark.parametrize("who,original,preview", [
    ("op_eng", 200, 200), ("a_admin", 200, 200), ("a_eng", 200, 200), ("a_user", 403, 200), ("a_proc", 403, 403),
], ids=["operator-engineer", "client-admin", "client-engineer", "client-user", "procurement"])
def test_document_rights_per_role(world, docs, who, original, preview):
    _, _, files = docs
    c = login(world[who], world["a"]) if who == "op_eng" else login(world[who])
    assert link(c, files["spec.pdf"], "original").status_code == original
    assert link(c, files["spec.pdf"], "preview").status_code == preview


def test_other_organisation_gets_404_on_every_document_endpoint(world, docs):
    _, p, files = docs
    b = login(world["b_admin"])
    f = files["spec.pdf"]
    for r in (b.get(f"/api/v1/files/{f['id']}/"), b.get(f"/api/v1/files/{f['id']}/versions/"),
              link(b, f, "preview"), link(b, f, "original"), b.get(f"/api/v1/passports/{p['id']}/")):
        assert r.status_code == 404
    assert b.get("/api/v1/files/", {"passport": p["id"]}).json()["results"] == []


def test_preview_only_for_pdf_and_derivatives_only_when_present(world, docs):
    _, _, files = docs
    admin = login(world["a_admin"])
    for name in ("part.stp", "drawing.dwg"):
        r = link(admin, files[name], "preview")
        assert r.status_code == 400 and r.json()["error"]["code"] == "preview_not_available"
    assert link(admin, files["drawing.dwg"], "glb").json()["error"]["code"] == "derivative_not_available"


def test_preview_link_is_revoked_with_the_membership_and_cannot_be_forged(world, docs, client):
    _, _, files = docs
    url = link(login(world["a_user"]), files["spec.pdf"], "preview").json()["url"].replace("http://testserver", "")
    assert client.get(url).status_code == 200
    token = url.rstrip("/").rsplit("/", 1)[1]
    assert client.get(url.replace(token, token[:-4] + "AAAA")).json()["error"]["code"] == "link_invalid"
    Membership.objects.filter(user=world["a_user"], tenant=world["a"]).update(is_active=False)
    assert client.get(url).status_code == 403


def test_amsl_criticality_is_provisional_and_changes_no_state(world, docs):
    eng, p, _ = docs
    r = eng.patch(f"/api/v1/passports/{p['id']}/revisions/1/", {"content": {"rl2": {"criticality_amsl": "AMSL-1 critical, approved"}}}, format="json")
    assert r.status_code == 200
    after = eng.get(f"/api/v1/passports/{p['id']}/").json()
    assert (after["publication_state"], after["evidence_level"], after["manufacturing_eligibility"]) == ("draft", "none", "not_eligible")
    assert after["current_revision"]["status"] == "draft"
    # gated actions are still refused regardless of the AMSL text
    assert eng.post(f"/api/v1/passports/{p['id']}/revisions/1/approve/", {}, format="json").json()["error"]["code"] == "policy_not_configured"
    # the state fields cannot be set directly either
    eng.patch(f"/api/v1/passports/{p['id']}/", {"manufacturing_eligibility": "eligible", "evidence_level": "R-L3"}, format="json")
    again = eng.get(f"/api/v1/passports/{p['id']}/").json()
    assert (again["evidence_level"], again["manufacturing_eligibility"]) == ("none", "not_eligible")
