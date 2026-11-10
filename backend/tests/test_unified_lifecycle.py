"""Post-UAT Phase 2 (D-01): one engineering lifecycle for every part, whatever its origin. Parts created by Aries, accepted
client records / proposals / clones, parts created from a scanning request and imported inventory all reach intelligence,
feasibility, cost, recommendation, review and sharing without a re-import; client submissions still awaiting Aries review are
excluded. External AI (Gemini) stays limited to imported synthetic records (data-protection rule)."""
from apps.parts.models import SparePart
from apps.tenancy.context import tenant_context

from .test_cost_comparison import scenario
from .test_feasibility import fz, run  # noqa: F401  (fixtures and helpers)
from .test_part_intelligence import pi  # noqa: F401  (fixture)

ORIGINS = {
    "LC-ARIES": {"origin": "aries", "review_state": "not_required"},
    "LC-RECORD": {"origin": "client", "review_state": "accepted", "submission_kind": "record"},
    "LC-PROPOSAL": {"origin": "client", "review_state": "accepted", "submission_kind": "proposal"},
    "LC-CLONE": {"origin": "client", "review_state": "accepted", "submission_kind": "clone", "proposed_material": "Duplex 2205"},
    "LC-PENDING": {"origin": "client", "review_state": "pending_review", "submission_kind": "proposal"},
    "LC-DECLINED": {"origin": "client", "review_state": "declined", "submission_kind": "proposal"},
}


def _make(fz):
    t = fz["tenant"]
    out = {}
    with tenant_context(t):
        for number, extra in ORIGINS.items():
            out[number] = SparePart.objects.create(tenant=t, part_number=number, name="Wear ring, pump casing", original_material="CF8M",
                                                   dimensions="Ø120 x 30 mm", **extra)
    return out


def test_every_origin_reaches_the_lifecycle_without_reimport(fz):  # noqa: F811
    eng, parts = fz["eng"], _make(fz)
    listed = {r["part_number"] for r in eng.get("/api/v1/intelligence/overview/").json()["parts"]}
    assert {"LC-ARIES", "LC-RECORD", "LC-PROPOSAL", "LC-CLONE", "990100000104"} <= listed
    assert not {"LC-PENDING", "LC-DECLINED"} & listed
    for number in ("LC-ARIES", "LC-RECORD", "LC-PROPOSAL", "LC-CLONE"):
        p = parts[number]
        assert eng.get(f"/api/v1/parts/{p.pk}/").json()["in_lifecycle"] is True
        r = run(eng, p)
        assert r.status_code in (200, 201), (number, r.content)
        assert eng.post(f"/api/v1/parts/{p.pk}/cost-comparisons/", {"scenario": scenario()}, format="json").status_code == 201, number
        rec = eng.post(f"/api/v1/parts/{p.pk}/recommendations/", {}, format="json")
        assert rec.status_code in (200, 201), (number, rec.content)
        assert rec.json()["recommendation"]["engineering_approved"] is False
    clone = run(eng, parts["LC-CLONE"]).json()["assessment"]
    assert next(e for e in clone["additive"]["evidence"] if e["key"] == "material")["value"] == "Duplex 2205"


def test_submissions_awaiting_review_are_refused_and_external_ai_stays_import_only(fz):  # noqa: F811
    eng, parts = fz["eng"], _make(fz)
    for number in ("LC-PENDING", "LC-DECLINED"):
        p = parts[number]
        assert eng.get(f"/api/v1/parts/{p.pk}/").json()["in_lifecycle"] is False
        r = run(eng, p)
        assert r.status_code == 409 and r.json()["error"]["code"] == "part_not_in_lifecycle"
    r = run(eng, parts["LC-ARIES"], tier="lite")  # rules are available, external AI is not (no import record)
    assert r.status_code == 403 and r.json()["error"]["code"] == "ai_not_permitted_for_part"
    view = eng.get(f"/api/v1/parts/{parts['LC-ARIES'].pk}/feasibility/").json()
    assert view["ai"]["enabled"] is False and "rules-based assessment is available" in view["ai"]["reason"]
