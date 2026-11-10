"""P1 visual client catalog: stored manufacturing eligibility in the catalog, the eligibility filter (MOB-010) and the
published / in-digitisation sections. States are read-only; nothing here changes evidence, publication or eligibility."""
import pytest

from apps.passports.models import DigitalPassport
from apps.tenancy.context import tenant_context

from .conftest import login


@pytest.fixture
def parts(world):
    eng = login(world["op_eng"], world["a"])
    ids = {}
    for number in ("P1-A", "P1-B", "P1-C"):
        ids[number] = eng.post("/api/v1/parts/", {"part_number": number, "name": f"Part {number}"}, format="json").json()["id"]
    for number in ("P1-A", "P1-B"):
        eng.post("/api/v1/passports/", {"part": ids[number]}, format="json")
    return eng, ids


def numbers(c, **params):
    r = c.get("/api/v1/parts/", params)
    assert r.status_code == 200, r.content
    return sorted(p["part_number"] for p in r.json()["results"])


def test_catalog_rows_carry_the_stored_eligibility(parts):
    eng, _ = parts
    rows = {p["part_number"]: p for p in eng.get("/api/v1/parts/").json()["results"]}
    assert rows["P1-A"]["manufacturing_eligibility"] == "not_eligible"
    assert rows["P1-C"]["manufacturing_eligibility"] is None  # no passport


def test_eligibility_filter(world, parts):
    eng, _ = parts
    assert numbers(eng, eligibility="not_eligible") == ["P1-A", "P1-B", "P1-C"]  # parts without a passport are not eligible
    assert numbers(eng, eligibility="eligible") == []
    with tenant_context(world["a"]):  # a stored state (set here directly; there is no API transition, OQ-36)
        DigitalPassport.objects.filter(part__part_number="P1-B").update(manufacturing_eligibility="suspended")
    assert numbers(eng, eligibility="suspended") == ["P1-B"]
    assert numbers(eng, eligibility="not_eligible") == ["P1-A", "P1-C"]
    assert numbers(eng, eligibility="bogus") == ["P1-A", "P1-B", "P1-C"]  # unknown value is ignored


def test_published_and_in_digitisation_sections(world, parts):
    eng, _ = parts
    assert numbers(eng, catalog="published") == []
    assert numbers(eng, catalog="in_digitisation") == ["P1-A", "P1-B", "P1-C"]  # drafts and parts without passport are listed
    with tenant_context(world["a"]):
        DigitalPassport.objects.filter(part__part_number="P1-A").update(publication_state="published")
    assert numbers(eng, catalog="published") == ["P1-A"]
    assert numbers(eng, catalog="in_digitisation") == ["P1-B", "P1-C"]


def test_client_users_see_draft_parts_marked_but_not_other_tenants(world, parts):
    for who in ("a_admin", "a_user"):
        c = login(world[who])
        rows = c.get("/api/v1/parts/", {"catalog": "in_digitisation"}).json()["results"]
        assert {p["part_number"] for p in rows} >= {"P1-A", "P1-B", "P1-C"}
        assert all(p["publication_state"] in (None, "draft") for p in rows)
    other = login(world["b_admin"])
    for params in ({"catalog": "in_digitisation"}, {"catalog": "published"}, {"eligibility": "not_eligible"}):
        assert numbers(other, **params) == []


def test_catalog_offers_no_state_changes(parts):
    eng, ids = parts
    r = eng.patch(f"/api/v1/parts/{ids['P1-A']}/", {"manufacturing_eligibility": "eligible", "publication_state": "published"}, format="json")
    assert r.status_code == 200
    assert r.json()["manufacturing_eligibility"] == "not_eligible" and r.json()["publication_state"] == "draft"
