"""Cost and lead-time comparison (CN-007 Phase 4): deterministic calculations (MOQ, quantities, currencies, missing
inputs, fixed vs variable costs, duties, lead times, source labels), validation, Phase 3 technical status, versioned
immutable history, previews, optional AI notes (whitelist, synthetic only, no prices or recommendations), isolation and
no release bypass. A fake provider stands in for Gemini: these tests never call an external service."""
import copy
import json
from datetime import date

import pytest
from django.db import connection, transaction

from apps.audit.models import AuditEvent
from apps.intelligence import costing as C
from apps.intelligence import gemini
from apps.intelligence.models import AIUsageLog, CostComparison
from apps.parts.models import SparePart
from apps.passports.models import DigitalPassport
from apps.projects.models import EngineerAccess
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Membership, Role

from .conftest import dbid, login, make_user
from .test_feasibility import _verify, fz, run  # noqa: F401  (fixtures and helpers)
from .test_part_intelligence import pi  # noqa: F401  (fixture)

TODAY = date(2026, 10, 27)
NA = {"not_applicable": True}
MISSING = {"source": "missing"}


def c(amount, cur="USD", source="engineering_estimate", **kw):
    ref = "REF-1" if source in ("quotation", "historical") else ""
    return {"amount": str(amount), "currency": cur, "source": source, "reference": kw.pop("reference", ref), **kw}


def lead(days, source="engineering_estimate", **kw):
    # a quoted lead time normally comes from the same quotation as the prices (REF-1)
    ref = {"quotation": "REF-1", "historical": "REF-L"}.get(source, "")
    return {"days": days, "source": source, "reference": kw.pop("reference", ref), **kw}


def scenario():
    return {
        "name": "SYNTHETIC TEST", "synthetic": True, "quantity": 3, "reporting_currency": "USD", "baseline": "oem",
        "exchange_rates": [{"from": "EUR", "to": "USD", "rate": "1.10", "rate_date": "2026-10-27", "source": "Entered test rate"},
                           {"from": "USD", "to": "AED", "rate": "3.6725", "rate_date": "2026-10-27", "source": "Entered test rate"}],
        "alternatives": {
            "oem": {"moq": 5, "costs": {"unit_cost": c(100, "EUR", "quotation", valid_until="2026-12-31"), "post_processing": NA,
                                        "engineering_setup": NA, "tooling": NA, "testing_qualification": NA,
                                        "logistics": {**c(50, "EUR", "quotation", valid_until="2026-12-31"), "basis": "per_order"},
                                        "duties": {"percent": "5", "source": "historical", "reference": "Customs 2025"}},
                    "lead_time": {"supplier_days": lead(30, "quotation"), "engineering_days": NA}},
            "additive": {"qualification_units": 1, "costs": {"unit_cost": c(80), "post_processing": c(20), "engineering_setup": c(300),
                                                             "tooling": NA, "testing_qualification": c(600),
                                                             "logistics": {**c(10), "basis": "per_unit"}, "duties": NA},
                         "lead_time": {"supplier_days": lead(7), "engineering_days": lead(21)}},
            "conventional": {"moq": 10, "costs": {"unit_cost": c(150, "AED", "historical"), "post_processing": NA,
                                                  "engineering_setup": c(200), "tooling": c(1000), "testing_qualification": MISSING,
                                                  "logistics": {**c(40), "basis": "per_order"}, "duties": NA},
                             "lead_time": {"supplier_days": lead(35, "historical"), "engineering_days": MISSING}},
        },
    }


QUALIFIED = {"oem": {"qualified": True}, "additive": {"qualified": False}, "conventional": {"qualified": False}}


def calc(sc, tech=QUALIFIED):
    return C.calculate(C.validate(sc, TODAY), tech, TODAY)


def test_hand_calculated_example_moq_currency_duties_and_savings():
    r = calc(scenario())
    oem, am, cv = (r["alternatives"][k] for k in ("oem", "additive", "conventional"))
    # OEM: MOQ 5 for 3 required; 100 EUR x 1.10 = 110 USD; goods 550; logistics 55 per order; duties 5% x 605 = 30.25
    assert oem["ordered_quantity"] == 5 and oem["surplus_units"] == 2
    assert oem["categories"]["material_production"]["amount"] == "550.00"
    assert oem["categories"]["logistics"]["amount"] == "55.00" and oem["categories"]["duties_taxes"]["amount"] == "30.25"
    assert oem["total"] == "635.25" and oem["effective_unit_cost"] == "211.75" and oem["cost_per_ordered_unit"] == "127.05"
    assert oem["one_time_total"] == "55.00" and oem["quantity_dependent_total"] == "550.00" and oem["duties_total"] == "30.25"
    assert oem["confidence"] == "Medium: includes historical costs" and oem["lead_time"]["total_days"] == 30
    assert oem["exchange_rates_used"][0]["rate"] == "1.10" and oem["exchange_rates_used"][0]["rate_date"] == "2026-10-27"
    # AM: 3 required + 1 qualification unit = 4 ordered; (80 + 20 + 10 logistics per unit) x 4 + 300 + 600 = 1340
    assert am["ordered_quantity"] == 4 and am["total"] == "1340.00" and am["effective_unit_cost"] == "446.67"
    assert am["setup_tooling_per_usable_unit"] == "100.00" and am["one_time_total"] == "900.00"
    assert am["quantity_dependent_total"] == "440.00" and am["confidence"] == "Low: includes engineering estimates"
    assert am["lead_time"]["total_days"] == 28
    cmp = am["comparison"]
    assert cmp["savings"] == "-704.75" and cmp["savings_percent"] == "-110.9" and cmp["lead_time_difference_days"] == -2
    assert cmp["provisional"] is True and "not technically qualified" in cmp["reason"]
    # conventional: AED via the inverse of USD->AED (shown as such); missing testing cost and engineering time
    line = next(x for x in cv["lines"] if x["key"] == "unit_cost")
    assert line["conversion"]["inverse"] is True and line["reporting_unit_amount"] == "40.84"
    assert cv["complete"] is False and cv["total"] is None and cv["effective_unit_cost"] is None
    assert "Testing and qualification" in cv["missing_inputs"]
    assert "Lead time: additional engineering / qualification time" in cv["missing_inputs"]
    assert cv["comparison"]["savings"] is None and "incomplete" in cv["comparison"]["reason"]
    assert cv["lead_time"]["total_days"] is None and cv["confidence"] == "Incomplete: missing inputs"


def test_quantities_pack_sizes_and_what_if():
    sc = scenario()
    sc["alternatives"]["oem"].update(moq=10, order_multiple=10, qualification_units=2)
    for q, ordered in ((1, 10), (8, 10), (9, 20), (25, 30)):
        sc["quantity"] = q
        assert calc(sc)["alternatives"]["oem"]["ordered_quantity"] == ordered
    sc["quantity"] = 3
    small = calc(sc)["alternatives"]["conventional"]
    sc["alternatives"]["conventional"]["costs"]["testing_qualification"] = c(0)
    sc["alternatives"]["conventional"]["lead_time"]["engineering_days"] = NA
    one, many = [], []
    for q, out in ((3, one), (30, many)):
        sc["quantity"] = q
        out.append(calc(sc)["alternatives"]["conventional"])
    # one-time tooling spread over more usable units lowers the effective unit cost
    assert C.Decimal(many[0]["effective_unit_cost"]) < C.Decimal(one[0]["effective_unit_cost"])
    assert one[0]["one_time_total"] == many[0]["one_time_total"] == "1240.00"
    assert small["complete"] is False and one[0]["complete"] is True


def test_missing_rates_prices_and_quotation_status():
    sc = scenario()
    sc["exchange_rates"] = sc["exchange_rates"][1:]  # no EUR rate: never assumed
    oem = calc(sc)["alternatives"]["oem"]
    assert oem["total"] is None and "Exchange rate EUR to USD (for unit purchase / manufacturing cost)" in oem["missing_inputs"]
    sc = scenario()
    sc["alternatives"]["oem"]["costs"]["unit_cost"] = MISSING
    oem = calc(sc)["alternatives"]["oem"]
    assert oem["total"] is None and "Unit purchase / manufacturing cost" in oem["missing_inputs"]
    assert "Duties and taxes (goods value or logistics unknown)" in oem["missing_inputs"]
    assert all(a["comparison"]["savings"] is None for a in calc(sc)["alternatives"].values())  # no baseline total
    sc = scenario()
    sc["alternatives"]["oem"]["costs"]["unit_cost"]["valid_until"] = "2026-09-30"
    oem = calc(sc)["alternatives"]["oem"]
    assert oem["warnings"] == ["Unit purchase / manufacturing cost: quotation expired on 2026-09-30.",
                               "Supplier / manufacturer lead time: quoted lead time expired on 2026-09-30 (with quotation REF-1)."]
    assert oem["lead_time"]["confidence"] == "Medium: includes historical costs"
    assert oem["total"] == "635.25" and oem["confidence"] == "Medium: includes historical costs"
    sc = scenario()
    sc["alternatives"]["oem"]["costs"]["duties"] = NA
    assert calc(sc)["alternatives"]["oem"]["confidence"] == "High: verified supplier quotations"
    sc["alternatives"]["additive"]["costs"]["unit_cost"] = c(80, source="ai_estimate")
    am = calc(sc)["alternatives"]["additive"]
    assert am["confidence"] == "Very low: includes AI-assisted preliminary estimates"
    assert next(x for x in am["lines"] if x["key"] == "unit_cost")["source_label"] == "AI-assisted preliminary estimate"


@pytest.mark.parametrize("path,value,field", [
    (("quantity",), 0, "quantity"),
    (("quantity",), "2.5", "quantity"),
    (("alternatives", "oem", "costs", "unit_cost", "amount"), "0", "alternatives.oem.costs.unit_cost.amount"),
    (("alternatives", "additive", "costs", "tooling"), {"amount": "-5", "currency": "USD", "source": "engineering_estimate"},
     "alternatives.additive.costs.tooling.amount"),
    (("alternatives", "oem", "costs", "unit_cost", "valid_until"), None, "alternatives.oem.costs.unit_cost.valid_until"),
    (("alternatives", "oem", "costs", "unit_cost", "reference"), "", "alternatives.oem.costs.unit_cost.reference"),
    (("alternatives", "oem", "costs", "unit_cost", "currency"), "EURO", "alternatives.oem.costs.unit_cost.currency"),
    (("alternatives", "oem", "costs", "unit_cost"), {"source": "missing", "amount": "5"}, "alternatives.oem.costs.unit_cost.amount"),
    (("alternatives", "oem", "costs", "unit_cost"), NA, "alternatives.oem.costs.unit_cost"),
    (("alternatives", "oem", "costs", "duties", "percent"), "120", "alternatives.oem.costs.duties.percent"),
    (("alternatives", "oem", "moq"), 0, "alternatives.oem.moq"),
    (("alternatives", "additive", "lead_time", "supplier_days", "days"), -1, "alternatives.additive.lead_time.supplier_days.days"),
    (("exchange_rates", 0, "rate_date"), "2027-01-01", "exchange_rates[0].rate_date"),
    (("exchange_rates", 0, "rate"), "0", "exchange_rates[0].rate"),
    (("reporting_currency",), "usd1", "reporting_currency"),
])
def test_invalid_inputs_are_refused(path, value, field):
    sc = scenario()
    target = sc
    for k in path[:-1]:
        target = target[k]
    target[path[-1]] = value
    with pytest.raises(C.CostInputError) as e:
        C.validate(sc, TODAY)
    assert field in [x["field"] for x in e.value.errors], e.value.errors


def test_excluded_option_shows_no_savings():
    r = calc(scenario(), {**QUALIFIED, "additive": {"qualified": False, "excluded": True}})
    am = r["alternatives"]["additive"]
    assert am["total"] == "1340.00" and am["comparison"]["savings"] is None and "Excluded" in am["comparison"]["reason"]


# ------------------------------------------------------------------ API, storage and integration with Phase 3

def curl(part, tail=""):
    return f"/api/v1/parts/{part.pk}/cost-comparisons/{tail}"


def test_comparisons_need_feasibility_are_versioned_and_immutable(fz):  # noqa: F811
    eng, ring, t = fz["eng"], fz["parts"]["990100000104"], fz["tenant"]
    r = eng.post(curl(ring), {"scenario": scenario()}, format="json")
    assert r.status_code == 409 and r.json()["error"]["code"] == "feasibility_required"
    run(eng, ring)
    bad = scenario()
    bad["quantity"] = -1
    r = eng.post(curl(ring), {"scenario": bad}, format="json")
    assert r.status_code == 400 and r.json()["error"]["details"]["errors"][0]["field"] == "quantity"
    r = eng.post(curl(ring), {"scenario": scenario()}, format="json")
    assert r.status_code == 201, r.content
    v1 = r.json()["comparison"]
    assert v1["version"] == 1 and v1["feasibility_version"] == 1 and v1["synthetic"] is True
    tech = v1["technical"]
    assert tech["oem"]["label"] == "Not verified: OEM identity / availability"
    assert tech["additive"]["label"] == "Not technically qualified: specialist engineering assessment required"
    assert tech["conventional"]["label"] == "Not technically qualified: insufficient technical information"
    assert v1["results"]["alternatives"]["additive"]["comparison"]["provisional"] is True
    again = eng.post(curl(ring), {"scenario": scenario()}, format="json")
    assert again.status_code == 200 and again.json()["reused"] is True
    # a what-if quantity is calculated without storing; saving it is a new version linked to the original
    sc = scenario()
    sc["quantity"] = 12
    p = eng.post(curl(ring, "calculate/"), {"scenario": sc}, format="json")
    assert p.status_code == 200 and p.json()["stored"] is False
    assert p.json()["results"]["alternatives"]["oem"]["ordered_quantity"] == 12
    with tenant_context(t):
        assert CostComparison.objects.filter(tenant=t).count() == 1
    v2 = eng.post(curl(ring), {"scenario": sc, "derived_from": v1["id"]}, format="json").json()["comparison"]
    assert v2["version"] == 2 and v2["derived_from_version"] == 1 and v2["quantity"] == 12
    view = eng.get(curl(ring)).json()
    assert [x["version"] for x in view["comparisons"]] == [2, 1] and view["comparisons"][1]["quantity"] == 3
    assert view["template"]["alternatives"]["oem"]["costs"]["unit_cost"]["source"] == "missing"
    # a newer feasibility version is flagged on the older comparison, which keeps its link
    _verify(t, ring, original_material="A48 class 40")
    run(eng, ring)
    view = eng.get(curl(ring)).json()
    assert view["comparisons"][0]["feasibility_superseded"] is True and view["feasibility"]["version"] == 2
    with tenant_context(t):
        cid = CostComparison.objects.get(pk=v1["id"]).pk
        for sql in ("UPDATE intelligence_costcomparison SET quantity = 99 WHERE id = %s",
                    "DELETE FROM intelligence_costcomparison WHERE id = %s"):
            with pytest.raises(Exception, match="immutable_record"), transaction.atomic(), connection.cursor() as cur:
                cur.execute(sql, [dbid(cid)])
    assert AuditEvent.objects.filter(action="cost_comparison.created").count() == 2


def test_verified_constraint_and_review_correction_flow_into_the_comparison(fz, world):  # noqa: F811
    eng, cover, ring, t = fz["eng"], fz["parts"]["990100000101"], fz["parts"]["990100000104"], fz["tenant"]
    _verify(t, cover, category="electrical")
    run(eng, cover)
    r = eng.post(curl(cover), {"scenario": scenario()}, format="json").json()["comparison"]
    am = r["results"]["alternatives"]["additive"]
    assert r["technical"]["additive"]["label"] == "Excluded: not suitable based on verified constraints"
    assert am["total"] == "1340.00" and am["comparison"]["savings"] is None  # a cost is shown; it is never compared
    a = run(eng, ring).json()["assessment"]
    eng.post(f"/api/v1/parts/{ring.pk}/feasibility/{a['id']}/reviews/", {"alternative": "conventional", "decision": "corrected",
             "corrected_status": "specialist_assessment", "findings": "Pressure boundary: specialist review."}, format="json")
    tech = eng.post(curl(ring), {"scenario": scenario()}, format="json").json()["comparison"]["technical"]["conventional"]
    assert tech["corrected_by_review"] is True and tech["status"] == "specialist_assessment"
    assert tech["label"] == "Not technically qualified: specialist engineering assessment required"


NOTES = {"oem": {"technical_status": "not_verified", "cost_drivers": ["Purchase price dominates."], "assumptions_to_verify": ["Duty rate from 2025 customs."],
                 "missing_inputs": [], "lead_time_considerations": ["Quoted lead time."], "uncertainty": "low"},
         "additive": {"technical_status": "specialist_assessment", "cost_drivers": ["Qualification testing is the largest share. A printed ring costs about 900 USD."],
                      "assumptions_to_verify": ["Engineering estimates need quotations."], "missing_inputs": [],
                      "lead_time_considerations": [], "uncertainty": "high"},
         "conventional": {"technical_status": "insufficient_information", "cost_drivers": ["Tooling."], "assumptions_to_verify": [], "missing_inputs": ["Testing cost."],
                          "lead_time_considerations": [], "uncertainty": "high"},
         "general_notes": ["We recommend the OEM route because it is cheapest."], "confidence": 0.5}


def test_ai_notes_are_whitelisted_synthetic_only_and_carry_no_prices_or_recommendations(fz):  # noqa: F811
    eng, ring, fake, t = fz["eng"], fz["parts"]["990100000104"], fz["fake"], fz["tenant"]
    run(eng, ring)
    sc = scenario()
    sc["alternatives"]["oem"]["costs"]["unit_cost"].update(amount="1234.56", reference="QUOTE-XYZ-77")
    real = copy.deepcopy(sc)
    real["synthetic"] = False
    r = eng.post(curl(ring), {"scenario": real, "tier": "lite"}, format="json")
    assert r.status_code == 403 and r.json()["error"]["code"] == "ai_not_permitted_for_scenario"
    fake.answers = [json.dumps(NOTES)]
    r = eng.post(curl(ring), {"scenario": sc, "tier": "lite"}, format="json")
    assert r.status_code == 201, r.content
    cmp = r.json()["comparison"]
    assert cmp["ai_status"] == "ok" and cmp["ai"]["model"] == "gemini-3.1-flash-lite" and cmp["ai"]["usage"]["cost_usd"] > 0
    sent = fake.prompts[-1]
    assert sent["schema"] is gemini.COST_SCHEMA and sent["system"] is gemini.SYSTEM_COST
    for secret in ("1234.56", "1358", "QUOTE-XYZ-77", "1.10", "3.6725", "Customs 2025", "29990104"):
        assert secret not in sent["prompt"], secret
    assert "share_of_known_cost_percent" in sent["prompt"]
    text = json.dumps(cmp["ai"]["response"])
    assert "900 USD" not in text and "recommend" not in text.replace("recommendation removed", "")
    assert len(cmp["ai"]["removed"]) == 2
    # the deterministic results are unchanged by the AI notes
    plain = C.calculate(C.validate(sc, TODAY), {k: v for k, v in cmp["technical"].items()}, TODAY)
    assert cmp["results"]["alternatives"]["oem"]["total"] == plain["alternatives"]["oem"]["total"]
    again = eng.post(curl(ring), {"scenario": sc, "tier": "lite"}, format="json")
    assert again.status_code == 200 and again.json()["reused"] is True
    with tenant_context(t):
        assert AIUsageLog.objects.filter(tenant=t, outcome="cache_hit").count() == 1
    fake.answers = [gemini.AIError("timeout", "No answer", True)] * 3
    sc["quantity"] = 4
    f = eng.post(curl(ring), {"scenario": sc, "tier": "lite"}, format="json").json()["comparison"]
    assert f["ai_status"] == "failed" and f["results"]["alternatives"]["oem"]["total"] is not None


def test_isolation_access_and_no_release_bypass(fz, world):  # noqa: F811
    eng, ring, t = fz["eng"], fz["parts"]["990100000104"], fz["tenant"]
    run(eng, ring)
    eng.post(curl(ring), {"scenario": scenario()}, format="json")
    for user in ("a_admin", "a_eng", "a_user", "a_proc"):
        cl = login(world[user], world["a"])
        assert cl.get(curl(ring)).status_code == 403
        assert cl.post(curl(ring), {"scenario": scenario()}, format="json").status_code == 403
        assert cl.post(curl(ring, "calculate/"), {"scenario": scenario()}, format="json").status_code == 403
        assert cl.get("/api/v1/intelligence/cost-comparisons/").status_code == 403
    other = make_user("eng.b2@example.test", world["operator"], Role.OPERATOR_ENGINEER)
    Membership.objects.create(user=other, tenant=world["b"], role=Role.OPERATOR_ENGINEER)
    cb = login(other, world["b"])
    assert cb.get(curl(ring)).status_code == 404 and cb.post(curl(ring), {"scenario": scenario()}, format="json").status_code == 404
    scoped = make_user("eng.scoped2@example.test", world["operator"], Role.OPERATOR_ENGINEER)
    Membership.objects.create(user=scoped, tenant=world["a"], role=Role.OPERATOR_ENGINEER)
    with tenant_context(world["a"]):
        EngineerAccess.objects.create(tenant=world["a"], user=scoped, scope=EngineerAccess.Scope.PROJECTS)
    cs = login(scoped, world["a"])
    assert cs.get(curl(ring)).status_code == 404 and cs.get("/api/v1/intelligence/cost-comparisons/").json()["parts"] == []
    ov = eng.get("/api/v1/intelligence/cost-comparisons/").json()["parts"]
    row = next(x for x in ov if x["part_number"] == "990100000104")
    assert row["comparison"]["alternatives"]["oem"]["total"] == "635.25"
    # comparison only: no recommendation field, and nothing about the part, passport or release changes
    res = eng.get(curl(ring)).json()["comparisons"][0]["results"]
    assert set(res) == {"method_version", "as_of", "quantity", "reporting_currency", "baseline", "alternatives",
                        "exchange_rates", "statement"}
    with tenant_context(t):
        sp = SparePart.objects.get(pk=ring.pk)
        assert sp.status == "draft" and sp.category == "unknown"
        assert not DigitalPassport.objects.filter(part=sp).exists()


def test_wear_ring_oem_reconciliation():
    """Regression (Phase 4 review): the wear-ring OEM total of 3,375.75 USD is 780.00 USD x 4 + 95.00 logistics + 5 % duty
    on goods and logistics. All in USD, no conversion; no 3,780 component exists. The arithmetic is returned with the result."""
    sc = scenario()
    sc["quantity"] = 4
    sc["alternatives"]["oem"] = {
        "moq": 1, "costs": {"unit_cost": c(780, "USD", "quotation", valid_until="2026-09-30"), "post_processing": NA,
                            "engineering_setup": NA, "tooling": NA, "testing_qualification": NA,
                            "logistics": {**c(95, "USD", "quotation", valid_until="2026-09-30"), "basis": "per_order"},
                            "duties": {"percent": "5", "source": "historical", "reference": "SYN-CUSTOMS-2025"}},
        "lead_time": {"supplier_days": lead(70, "quotation"), "engineering_days": NA}}
    oem = calc(sc)["alternatives"]["oem"]
    lines = {x["key"]: x for x in oem["lines"]}
    assert (lines["unit_cost"]["amount"], lines["unit_cost"]["currency"], lines["unit_cost"]["multiplier"]) == ("780.00", "USD", 4)
    assert lines["unit_cost"]["conversion"] is None and lines["unit_cost"]["reporting_amount"] == "3120.00"
    assert lines["logistics"]["reporting_amount"] == "95.00" and lines["duties"]["reporting_amount"] == "160.75"
    assert oem["total"] == "3375.75" and oem["effective_unit_cost"] == "843.94" and oem["exchange_rates_used"] == []
    assert sum(C.Decimal(v["amount"]) for v in oem["categories"].values()) == C.Decimal("3375.75")
    assert oem["explanation"] == [
        "Unit purchase / manufacturing cost: 780.00 USD × 4 ordered = 3,120.00 USD",
        "Packaging and logistics: 95.00 USD",
        "Duties and taxes: 5% × (3,120.00 goods + 95.00 logistics) = 160.75 USD",
        "Total: 3,120.00 + 95.00 + 160.75 = 3,375.75 USD (each figure rounded for display; the total uses unrounded values)",
        "Effective cost per usable unit: 3,375.75 ÷ 4 required = 843.94 USD"]
    assert "3,780" not in json.dumps(oem) and "3780" not in json.dumps(oem)
    # a converted, multiplied line shows its rate; the half-up rounding of the explanation matches the stored figures
    cv = calc(scenario())["alternatives"]["conventional"]
    assert cv["explanation"][0] == "Unit purchase / manufacturing cost: 150.00 AED ÷ 3.6725 (entered USD→AED rate) = 40.84 USD × 10 ordered = 408.44 USD"
    assert cv["explanation"][-1].startswith("Total not calculated: Testing and qualification")


# ------------------------------------------------------------------ AI notes never contradict the technical status

from apps.intelligence import consistency  # noqa: E402

RING = {"oem": "not_verified", "additive": "specialist_assessment", "conventional": "insufficient_information"}


def test_contradiction_rules():
    # the sentence Gemini wrote for the wear ring in Phase 4: conventional is "insufficient information", not specialist
    phase4 = "Technical status for additive and conventional methods requires specialist engineering assessment."
    hits = consistency.contradictions(phase4, RING)
    assert [(h["alternative"], h["stated"]) for h in hits] == [("conventional", "specialist_assessment")]
    for ok in ("Grey cast iron is not suitable for direct AM; specialist assessment is required.",
               "Conventional routes: insufficient technical information to assess.", "Not technically qualified yet.",
               "OEM identity not verified.", "Tooling dominates the conventional cost."):
        assert consistency.contradictions(ok, RING) == [], ok
    for bad, alt in (("Casting is technically qualified for this ring.", "conventional"),
                     ("The verified OEM part number simplifies procurement.", "oem"),
                     ("AM is potentially suitable here.", "additive")):
        assert [h["alternative"] for h in consistency.contradictions(bad, RING)] == [alt], bad
    # text under an alternative's own key is checked against that alternative even without naming it
    cleaned, found = consistency.scrub({"conventional": {"cost_drivers": ["Requires specialist assessment first."]}}, RING)
    assert cleaned["conventional"]["cost_drivers"] == [consistency.MARKER] and found[0]["alternative"] == "conventional"
    # a list of what is still needed states a need, not a claim (Phase 5 integration finding)
    needs = {"information_to_obtain": ["Verified OEM part number and identity"], "oem": {"evidence_gaps": ["Verified OEM part number"]}}
    assert consistency.scrub(needs, RING) == (needs, [])
    assert consistency.contradictions("The OEM part number is verified.", RING)[0]["alternative"] == "oem"
    stored = {"general_notes": [phase4]}
    assert consistency.check_stored(stored, RING) and stored == {"general_notes": [phase4]}  # flagged, never changed


def test_ai_notes_cannot_contradict_the_technical_status(fz):  # noqa: F811
    eng, ring, fake = fz["eng"], fz["parts"]["990100000104"], fz["fake"]
    run(eng, ring)
    sc = scenario()
    wrong = copy.deepcopy(NOTES)
    wrong["conventional"]["technical_status"] = "specialist_assessment"
    fake.answers = [json.dumps(wrong)] * 3  # repeats the wrong status every time: rejected
    bad = eng.post(curl(ring), {"scenario": sc, "tier": "lite"}, format="json").json()["comparison"]
    assert bad["ai_status"] == "invalid_response" and bad["ai"]["error_code"] == "contradicts_technical_status", (bad["technical"], bad["ai"]["response"], bad["ai"]["usage"])
    assert bad["ai"]["usage"]["attempts"] == 3 and bad["results"]["alternatives"]["oem"]["total"] == "635.25"
    mixed = copy.deepcopy(NOTES)
    mixed["general_notes"] = ["Technical status for additive and conventional methods requires specialist engineering assessment.",
                              "Lead times differ."]
    fake.answers = [json.dumps(wrong), json.dumps(mixed)]  # second answer echoes correctly; its contradicting note is removed
    sc["quantity"] = 5
    ok = eng.post(curl(ring), {"scenario": sc, "tier": "lite"}, format="json").json()["comparison"]
    assert ok["ai_status"] == "ok" and ok["ai"]["usage"]["attempts"] == 2
    assert ok["ai"]["response"]["general_notes"][0] == consistency.MARKER and ok["ai"]["response"]["general_notes"][1] == "Lead times differ."
    assert ok["ai"]["contradictions"][0]["alternative"] == "conventional" and ok["ai_consistency"] == []


def test_quoted_lead_time_expires_with_its_quotation():
    """Regression (Phase 5 review): a lead time quoted by a supplier is not current evidence once the quotation that
    states it has expired, unless the lead time has its own current validity date."""
    sc = scenario()
    sc["alternatives"]["oem"]["costs"]["unit_cost"]["valid_until"] = "2026-09-30"
    sc["alternatives"]["oem"]["costs"]["logistics"]["valid_until"] = "2026-09-30"
    sc["alternatives"]["oem"]["costs"]["duties"] = NA
    oem = calc(sc)["alternatives"]["oem"]
    comp = oem["lead_time"]["components"][0]
    assert comp["quotation_validity"] == {"valid_until": "2026-09-30", "basis": "quotation REF-1", "expired": True, "unknown": False}
    assert oem["lead_time"]["confidence"] == "Medium: includes historical costs" and oem["lead_time"]["total_days"] == 30
    # independently supported by current evidence: the lead time has its own, still valid date
    sc["alternatives"]["oem"]["lead_time"]["supplier_days"] = lead(30, "quotation", reference="SUPPLIER-EMAIL-7", valid_until="2026-12-01")
    oem = calc(sc)["alternatives"]["oem"]
    assert oem["lead_time"]["components"][0]["quotation_validity"]["expired"] is False
    assert oem["lead_time"]["confidence"] == "High: verified supplier quotations"
    # a quoted lead time with neither a date nor a matching quotation is not current evidence
    sc["alternatives"]["oem"]["lead_time"]["supplier_days"] = lead(30, "quotation", reference="PHONE-CALL")
    oem = calc(sc)["alternatives"]["oem"]
    assert oem["lead_time"]["components"][0]["quotation_validity"]["unknown"] is True
    assert oem["lead_time"]["confidence"] == "Medium: includes historical costs"
    assert any("no validity date" in w for w in oem["warnings"])
