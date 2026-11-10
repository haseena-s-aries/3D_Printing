"""Recommendation and engineering review (CN-007 Phase 5): mandatory technical/safety/certification/IP requirements
before commercial ranking, separate cheapest / fastest / potentially suitable / engineering-approved statuses, incomplete
costs never definitively cheaper, expired quotations never verified-current evidence, weights only after the mandatory
requirements, the "no qualified recommendation" outcome, AI explanations that cannot change or contradict the result,
versioning with source revisions, the review queue with separation of duties, isolation and no release bypass.
A fake provider stands in for Gemini: these tests never call an external service."""
import copy
import json
from datetime import date

import pytest
from django.db import connection, transaction

from apps.audit.models import AuditEvent
from apps.files.models import EngineeringFile
from apps.intelligence import costing as C
from apps.intelligence import recommendation as R
from apps.intelligence.models import Recommendation
from apps.parts.models import SparePart
from apps.passports.models import DigitalPassport
from apps.projects.models import EngineerAccess
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Membership, Role

from .conftest import dbid, login, make_user
from .test_cost_comparison import NA, c, lead, scenario
from .test_feasibility import _verify, fz, run  # noqa: F401  (fixtures and helpers)
from .test_part_intelligence import pi  # noqa: F401  (fixture)

TODAY = date(2026, 10, 28)
NO_QUALIFIED = "No qualified recommendation — additional engineering review required"


def tech(**over):
    base = {"oem": {"status": "not_verified", "status_label": "Identification / availability not verified", "qualified": False, "excluded": False},
            "additive": {"status": "insufficient_information", "status_label": "Insufficient technical information", "qualified": False, "excluded": False},
            "conventional": {"status": "insufficient_information", "status_label": "Insufficient technical information", "qualified": False, "excluded": False}}
    for k, v in over.items():
        base[k] = {**base[k], **v}
    return base


SUIT = {"status": "potentially_suitable", "status_label": "Potentially suitable: requires engineering qualification"}
HELD = {"evidence": [{"key": "standards", "state": "recorded", "value": "ASME B73.1"}, {"key": "ip", "state": "recorded", "value": "obsolete"}]}
PANELS = {"oem": {}, "additive": HELD, "conventional": HELD}


def costs(sc=None, today=date(2026, 10, 27)):
    return C.calculate(C.validate(sc or scenario(), today), {k: {"qualified": False} for k in C.ALTERNATIVES}, today)


def complete_scenario():
    sc = scenario()
    sc["alternatives"]["conventional"]["costs"]["testing_qualification"] = c(300)
    sc["alternatives"]["conventional"]["lead_time"]["engineering_days"] = lead(5)
    return sc


def test_no_option_qualified_gives_no_recommendation_and_no_weights():
    r = R.evaluate(tech(), PANELS, "unknown", costs(), {"cost": 1, "lead_time": 0, "evidence": 0}, TODAY)
    assert r["outcome"] == {"code": "no_qualified_recommendation", "label": NO_QUALIFIED, "option": None, "reasons": r["outcome"]["reasons"]}
    assert r["weights_applied"] is False and "no option meets the mandatory technical requirements" in r["weights_note"]
    assert r["ranking"] == [] and r["statuses"]["potentially_suitable"]["options"] == []
    assert r["statuses"]["engineering_approved"]["options"] == [] and "OQ-35" in r["statuses"]["engineering_approved"]["text"]
    am = r["options"]["additive"]
    failed = {q["code"] for q in am["requirements"] if not q["met"]}
    assert failed == {"screening", "safety"} and am["flags"]["engineering_approved"] is False
    # cheapest is a separate, informational status: OEM is lowest among complete totals, but conventional is incomplete
    ch = r["statuses"]["commercially_cheapest"]
    assert ch["option"] == "oem" and ch["definitive"] is False and "not definitive" in ch["text"]
    assert "Conventional manufacturing is incomplete" in ch["text"] and r["options"]["conventional"]["flags"]["commercially_cheapest"] is False
    assert r["statuses"]["fastest"]["option"] == "additive" and r["statuses"]["fastest"]["definitive"] is False


def test_hard_requirements_safety_certification_ip_and_exclusion():
    t = tech(additive=SUIT, conventional=SUIT)
    r = R.evaluate(t, PANELS, "non_critical", costs(complete_scenario()), None, TODAY)
    assert r["statuses"]["potentially_suitable"]["options"] == ["additive", "conventional"]
    for crit, code in (("unknown", "safety"), ("critical", "safety")):
        assert {q["code"] for q in R.evaluate(t, PANELS, crit, None, None, TODAY)["options"]["additive"]["requirements"] if not q["met"]} == {code}
    no_std = {"evidence": [{"key": "ip", "state": "recorded", "value": "obsolete"}]}
    ip_active = {"evidence": [HELD["evidence"][0], {"key": "ip", "state": "verified", "value": "active"}]}
    r2 = R.evaluate(t, {"oem": {}, "additive": no_std, "conventional": ip_active}, "non_critical", None, None, TODAY)
    assert [q["code"] for q in r2["options"]["additive"]["requirements"] if not q["met"]] == ["certification"]
    assert [q["detail"] for q in r2["options"]["conventional"]["requirements"] if not q["met"]] == [
        "OEM IP active: reproduction needs OEM permission or legal clearance"]
    # a verified exclusion: never eligible and never "cheapest", even with the lowest total
    sc = complete_scenario()
    sc["alternatives"]["additive"]["costs"]["unit_cost"] = c(1)
    r3 = R.evaluate(tech(additive={"status": "not_suitable_verified", "status_label": "Not suitable", "excluded": True}, conventional=SUIT),
                    PANELS, "non_critical", costs(sc), None, TODAY)
    assert r3["options"]["additive"]["eligible"] is False and r3["statuses"]["commercially_cheapest"]["option"] != "additive"


def test_weights_only_rank_qualified_options_with_complete_figures():
    t = tech(additive=SUIT, conventional=SUIT)
    full = costs(complete_scenario())
    by_cost = R.evaluate(t, PANELS, "non_critical", full, {"cost": 1, "lead_time": 0, "evidence": 0}, TODAY)
    by_lead = R.evaluate(t, PANELS, "non_critical", full, {"cost": 0, "lead_time": 1, "evidence": 0}, TODAY)
    # conventional 4,105.44 total vs additive 1,340.00; lead 40 vs 28 days
    assert by_cost["outcome"]["code"] == "preliminary_recommendation" and by_cost["outcome"]["option"] == "additive"
    assert [x["option"] for x in by_lead["ranking"]] == ["additive", "conventional"]
    assert by_cost["weights"] == {"cost": "1.0000", "lead_time": "0.0000", "evidence": "0.0000"} and by_cost["weights_applied"] is True
    assert "not engineering-approved" in by_cost["outcome"]["label"]
    assert "oem" not in [x["option"] for x in by_cost["ranking"]]  # OEM fails its mandatory requirement: never ranked
    incomplete = R.evaluate(tech(conventional=SUIT), PANELS, "non_critical", costs(), None, TODAY)
    assert incomplete["outcome"]["code"] == "qualified_commercial_incomplete" and incomplete["ranking"] == []
    for bad in ({"cost": -1}, {"cost": 0, "lead_time": 0, "evidence": 0}, {"price": 1}, {"cost": "x"}):
        with pytest.raises(R.WeightError):
            R.weights(bad)


def test_expired_quotations_are_not_verified_current_evidence():
    sc = scenario()
    sc["alternatives"]["oem"]["costs"]["duties"] = NA
    valid_then = costs(sc)  # quotations valid until 2026-12-31 when the comparison was made
    assert R.commercial(valid_then["alternatives"]["oem"], TODAY)["evidence"] == "verified_current"
    later = R.commercial(valid_then["alternatives"]["oem"], date(2027, 1, 5))  # re-checked on the recommendation date
    assert later["evidence"] == "includes_expired_quotation" and later["expired_quotations"][0].endswith("expired on 2026-12-31")
    assert "not verified-current" in later["evidence_label"]
    # the quoted lead time follows its quotation: current then, expired later (re-checked on the recommendation date)
    assert R.commercial(valid_then["alternatives"]["oem"], TODAY)["lead_evidence"] == "verified_current"
    assert later["lead_evidence"] == "includes_expired_quotation"
    assert later["expired_lead_times"] == ["Supplier / manufacturer lead time: quoted lead time expired on 2026-12-31 (with quotation REF-1)"]


def test_stored_results_without_lead_validity_are_rechecked_not_changed():
    """Comparisons stored before the lead-time rule carry no lead validity; the recommendation derives it from the
    stored quotation references on its own date, and the stored result is not modified."""
    sc = scenario()
    sc["alternatives"]["oem"]["costs"]["duties"] = NA
    stored = costs(sc)
    for comp in stored["alternatives"]["oem"]["lead_time"]["components"]:
        comp.pop("quotation_validity", None)  # as written by cost-method .2
    before = json.dumps(stored, sort_keys=True)
    r = R.evaluate(tech(), PANELS, "unknown", stored, None, date(2027, 2, 1))
    assert r["options"]["oem"]["commercial"]["lead_evidence"] == "includes_expired_quotation"
    assert r["statuses"]["commercially_cheapest"]["option"] == "oem"
    assert "cost evidence: includes an expired quotation" in r["statuses"]["commercially_cheapest"]["text"]
    assert r["options"]["oem"]["commercial"]["expired_lead_times"][0].endswith("(with quotation REF-1)")
    assert json.dumps(stored, sort_keys=True) == before


# ------------------------------------------------------------------ API, versions, AI and review

def rurl(part, tail=""):
    return f"/api/v1/parts/{part.pk}/recommendations/{tail}"


def _prepare(fz, number="990100000104"):  # noqa: F811
    eng, part = fz["eng"], fz["parts"][number]
    run(eng, part)
    eng.post(f"/api/v1/parts/{part.pk}/cost-comparisons/", {"scenario": scenario()}, format="json")
    return eng, part


def test_versions_keep_their_source_revisions(fz):  # noqa: F811
    eng, ring, t = fz["eng"], fz["parts"]["990100000104"], fz["tenant"]
    r = eng.post(rurl(ring), {}, format="json")
    assert r.status_code == 409 and r.json()["error"]["code"] == "feasibility_required"
    run(eng, ring)
    eng.post(f"/api/v1/parts/{ring.pk}/cost-comparisons/", {"scenario": scenario()}, format="json")
    v1 = eng.post(rurl(ring), {}, format="json").json()["recommendation"]
    assert v1["version"] == 1 and v1["outcome"] == "no_qualified_recommendation"
    assert v1["results"]["outcome"]["label"] == NO_QUALIFIED and v1["review_state"]["label"] == "Preliminary: not reviewed"
    assert v1["feasibility_version"] == 1 and v1["cost_comparison_version"] == 1 and v1["engineering_approved"] is False
    assert v1["results"]["phase2"]["family"] == "Wear ring" and v1["results"]["sources"]["cost_comparison"]["synthetic"] is True
    assert eng.post(rurl(ring), {}, format="json").json()["reused"] is True
    sc = scenario()
    sc["quantity"] = 8
    eng.post(f"/api/v1/parts/{ring.pk}/cost-comparisons/", {"scenario": sc}, format="json")
    view = eng.get(rurl(ring)).json()
    assert view["recommendations"][0]["stale"] == ["A newer cost comparison exists."]
    v2 = eng.post(rurl(ring), {"weights": {"cost": 2, "lead_time": 1, "evidence": 1}}, format="json").json()["recommendation"]
    assert v2["version"] == 2 and v2["cost_comparison_version"] == 2
    old = eng.get(rurl(ring)).json()["recommendations"][1]
    assert old["cost_comparison_version"] == 1 and old["results"]["sources"]["cost_comparison"]["quantity"] == 3
    r = eng.post(rurl(ring), {"weights": {"cost": -1}}, format="json")
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_weights"
    with tenant_context(t):
        rid = Recommendation.objects.get(pk=v1["id"]).pk
        for sql in ("UPDATE intelligence_recommendation SET outcome = 'preliminary_recommendation' WHERE id = %s",
                    "DELETE FROM intelligence_recommendation WHERE id = %s"):
            with pytest.raises(Exception, match="immutable_record"), transaction.atomic(), connection.cursor() as cur:
                cur.execute(sql, [dbid(rid)])


EXPL = {"outcome_code": "no_qualified_recommendation",
        "summary": "No option meets the mandatory requirements. The OEM route costs about 900 USD. We recommend the OEM route.",
        "oem": {"technical_status": "not_verified", "technical_explanation": "OEM identity not verified.",
                "commercial_explanation": "Lowest relative cost index among complete totals.", "evidence_gaps": ["OEM part number"], "risks": []},
        "additive": {"technical_status": "specialist_assessment", "technical_explanation": "Specialist assessment required.",
                     "commercial_explanation": "Higher relative cost.", "evidence_gaps": [], "risks": []},
        "conventional": {"technical_status": "insufficient_information",
                         "technical_explanation": "Conventional casting needs specialist engineering assessment.",
                         "commercial_explanation": "Costs incomplete.", "evidence_gaps": ["Testing cost"], "risks": []},
        "information_to_obtain": ["Drawing", "Material grade"], "confidence": 0.6}


def test_ai_explanation_cannot_change_or_contradict_the_result(fz):  # noqa: F811
    eng, ring = _prepare(fz)
    fake = fz["fake"]
    wrong = copy.deepcopy(EXPL)
    wrong["outcome_code"] = "preliminary_recommendation"
    fake.answers = [json.dumps(wrong)] * 3
    bad = eng.post(rurl(ring), {"tier": "lite"}, format="json").json()["recommendation"]
    assert bad["ai_status"] == "invalid_response" and bad["ai"]["error_code"] == "contradicts_outcome"
    assert bad["outcome"] == "no_qualified_recommendation"  # the deterministic result is stored either way
    fake.answers = [json.dumps(EXPL)]
    ok = eng.post(rurl(ring), {"tier": "lite", "weights": {"cost": 1, "lead_time": 1, "evidence": 1}}, format="json").json()["recommendation"]
    assert ok["ai_status"] == "ok"
    text = json.dumps(ok["ai"]["response"])
    assert "900 USD" not in text and "We recommend" not in text and "Conventional casting needs specialist" not in text
    assert ok["ai"]["contradictions"][0]["alternative"] == "conventional" and ok["ai_consistency"] == []
    sent = fake.prompts[-1]["prompt"]
    for secret in ("635.25", "1340", "REF-1", "Customs", "990100000104", "1.10"):
        assert secret not in sent, secret
    assert "relative_cost_index" in sent


def test_review_queue_separation_of_duties_and_no_release(fz, world):  # noqa: F811
    eng, ring = _prepare(fz)
    t = fz["tenant"]
    rec = eng.post(rurl(ring), {}, format="json").json()["recommendation"]
    rv = rurl(ring, f"{rec['id']}/reviews/")

    def post(cl, **body):
        return cl.post(rv, body, format="json")

    for word in ("approved", "release", "publish", "approve_for_manufacture"):
        r = post(eng, decision=word, findings="x")
        assert r.status_code == 403 and r.json()["error"]["code"] == "formal_approval_not_available"
    assert post(eng, decision="approved_for_further_study", option="additive", findings="x").json()["error"]["code"] == "self_review"
    assert post(eng, decision="information_requested").json()["error"]["code"] == "findings_required"
    r = post(eng, decision="information_requested", findings="Need drawing, grade and the role of each dimension.")
    assert r.status_code == 201 and r.json()["review"]["independent"] is False
    eng2 = make_user("eng.rev@example.test", world["operator"], Role.OPERATOR_ENGINEER)
    Membership.objects.create(user=eng2, tenant=world["a"], role=Role.OPERATOR_ENGINEER)
    c2 = login(eng2, world["a"])
    # post-UAT D-07: after "information requested" the same version cannot be approved; a revised version is required
    for decision, option in (("approved_for_further_study", "conventional"), ("corrected", "none")):
        assert post(c2, decision=decision, option=option, findings="x").json()["error"]["code"] == "revision_required"
    rec = eng.post(rurl(ring), {"weights": {"cost": "0.6", "lead_time": "0.2", "evidence": "0.2"}}, format="json").json()["recommendation"]
    assert rec["version"] == 2
    rv = rurl(ring, f"{rec['id']}/reviews/")
    assert post(c2, decision="corrected", option="conventional", findings="x").json()["error"]["code"] == "option_not_eligible"
    r = post(c2, decision="approved_for_further_study", option="conventional", findings="Obtain a drawing and casting quotation.",
             evidence_references=[{"reference": "Site note 7"}])
    assert r.status_code == 201 and r.json()["review"]["independent"] is True and r.json()["review"]["option_eligible"] is False
    state = r.json()["recommendations"][0]["review_state"]
    assert state["code"] == "approved_for_further_study" and "(independent)" in state["label"]
    assert r.json()["recommendations"][0]["engineering_approved"] is False
    assert post(c2, decision="corrected", option="none", findings="No route until evidence exists.").status_code == 201
    q = eng.get("/api/v1/intelligence/recommendations/").json()
    row = next(x for x in q["parts"] if x["part_number"] == "990100000104")
    assert row["review_state"]["code"] == "corrected" and q["counts"]["not_generated"] == 4
    assert [x["part_number"] for x in eng.get("/api/v1/intelligence/recommendations/?state=not_generated").json()["parts"]] == [
        "990100000099", "990100000101", "990100000102", "990100000103"]  # D-01: the Aries-created part is in scope
    # superseded versions cannot be reviewed; reviews never change the part, a passport or eligibility
    sc = scenario()
    sc["quantity"] = 6
    eng.post(f"/api/v1/parts/{ring.pk}/cost-comparisons/", {"scenario": sc}, format="json")
    eng.post(rurl(ring), {}, format="json")
    assert post(c2, decision="rejected", findings="x").json()["error"]["code"] == "recommendation_superseded"
    with tenant_context(t):
        sp = SparePart.objects.get(pk=ring.pk)
        assert sp.status == "draft" and not DigitalPassport.objects.filter(part=sp).exists()
    for user in ("a_admin", "a_eng", "a_user", "a_proc"):
        cl = login(world[user], world["a"])
        assert cl.get(rurl(ring)).status_code == 403 and post(cl, decision="rejected", findings="x").status_code == 403
        assert cl.get("/api/v1/intelligence/recommendations/").status_code == 403
    other = make_user("eng.b3@example.test", world["operator"], Role.OPERATOR_ENGINEER)
    Membership.objects.create(user=other, tenant=world["b"], role=Role.OPERATOR_ENGINEER)
    assert login(other, world["b"]).get(rurl(ring)).status_code == 404
    scoped = make_user("eng.scoped3@example.test", world["operator"], Role.OPERATOR_ENGINEER)
    Membership.objects.create(user=scoped, tenant=world["a"], role=Role.OPERATOR_ENGINEER)
    with tenant_context(world["a"]):
        EngineerAccess.objects.create(tenant=world["a"], user=scoped, scope=EngineerAccess.Scope.PROJECTS)
    cs = login(scoped, world["a"])
    assert cs.get(rurl(ring)).status_code == 404 and cs.get("/api/v1/intelligence/recommendations/").json()["parts"] == []
    assert AuditEvent.objects.filter(action="recommendation.reviewed").count() == 3


def test_qualified_options_are_ranked_and_reviewed_without_touching_the_passport(fz, world):  # noqa: F811
    eng, cover, t = fz["eng"], fz["parts"]["990100000101"], fz["tenant"]
    _verify(t, cover, original_material="SS316", dimensions="Ø180 mm x 40 mm", criticality="non_critical")
    with tenant_context(t):
        EngineeringFile.objects.create(tenant=t, part=cover, kind="dwg", category="drawing", title="Cover drawing")
    passport = eng.post("/api/v1/passports/", {"part": str(cover.pk), "initial_content": {
        "rl1": {"ip_status": "obsolete"}, "rl2": {"applicable_standards": "ASME B73.1; ISO 2768-m"}}}, format="json")
    assert passport.status_code == 201, passport.content
    run(eng, cover)
    eng.post(f"/api/v1/parts/{cover.pk}/cost-comparisons/", {"scenario": complete_scenario()}, format="json")
    rec = eng.post(rurl(cover), {"weights": {"cost": 1, "lead_time": 0, "evidence": 0}}, format="json").json()["recommendation"]
    res = rec["results"]
    assert res["statuses"]["potentially_suitable"]["options"] == ["additive", "conventional"]
    assert rec["outcome"] == "preliminary_recommendation" and rec["recommended_option"] == "additive"
    assert res["statuses"]["commercially_cheapest"]["option"] == "oem" and res["statuses"]["commercially_cheapest"]["definitive"] is True
    assert "OEM procurement does not meet the mandatory technical requirements" in res["statuses"]["commercially_cheapest"]["text"]
    assert rec["passport_number"] and rec["passport_revision_number"] == 1
    eng2 = make_user("eng.rev2@example.test", world["operator"], Role.OPERATOR_ENGINEER)
    Membership.objects.create(user=eng2, tenant=world["a"], role=Role.OPERATOR_ENGINEER)
    c2 = login(eng2, world["a"])
    r = c2.post(rurl(cover, f"{rec['id']}/reviews/"), {"decision": "approved_for_further_study", "option": "additive",
                                                       "findings": "Proceed to qualification planning."}, format="json")
    assert r.status_code == 201 and r.json()["review"]["option_eligible"] is True
    with tenant_context(t):
        pp = DigitalPassport.objects.get(part=cover)
        assert pp.publication_state == "draft" and pp.manufacturing_eligibility == "not_eligible" and pp.evidence_level == "none"
