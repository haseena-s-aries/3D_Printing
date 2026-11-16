"""Manufacturing cost estimate (decision of 16 Nov 2026): Gemini estimates the work and finds web prices (with sources);
the money is calculated from Aries' rates; engineers correct, Admin/Manager choose the route; manual mode without AI."""
import json

import pytest

from apps.intelligence import estimate as est
from apps.intelligence import gemini, service
from apps.intelligence.models import AIUsageLog, ManufacturingEstimate
from apps.tenancy.context import tenant_context

from .conftest import login
from .test_manufacturing_flow import order  # noqa: F401 - fixture

DAYS = {"preparation": 2, "production": 3, "post_processing": 2, "inspection": 1, "shipping": 2}
WORK = {
    "oem": {"feasible": "yes", "reason": "Still listed by the manufacturer.", "lead_days": 30, "risks": ["Long lead time"]},
    "conventional": {"feasible": "yes", "reason": "Simple seat geometry.", "process": "CNC turning", "material": "stainless steel bar",
                     "kg_per_part": 2.0, "machine": "cnc", "machine_hours_per_part": 3, "setup_hours": 2,
                     "manpower": [{"role": "machinist", "hours_per_part": 3, "hours_per_batch": 2}, {"role": "qa", "hours_per_part": 1, "hours_per_batch": 0}],
                     "heat_treatment": False, "ndt": True, "days": DAYS, "risks": [], "assumptions": ["Bar stock available"]},
    "additive": {"feasible": "with_review", "reason": "Needs qualification.", "process": "laser powder bed fusion",
                 "material": "stainless steel 316L powder", "kg_per_part": 1.0, "machine": "metal_am", "machine_hours_per_part": 6,
                 "setup_hours": 1, "manpower": [{"role": "am_operator", "hours_per_part": 1, "hours_per_batch": 1}],
                 "heat_treatment": True, "ndt": True, "days": DAYS, "risks": ["Porosity"], "assumptions": []},
    "missing_information": ["Drawing"], "confidence": 0.6,
}
PRICES = {"materials": [{"material": "stainless steel 316L powder", "price_per_kg": 50, "source_title": "Metal powder shop",
                         "source_url": "https://example.test/316l", "note": ""}],
          "oem": {"price_per_part": 400, "source_title": "Distributor", "source_url": "https://example.test/oem", "note": ""}}


class FakeAdapter:
    def __init__(self, prices=PRICES):
        self.calls, self.prices = [], prices

    def generate(self, *, model, tier, prompt, schema=None, system=None, search=False):
        self.calls.append({"search": search, "prompt": prompt})
        if search:
            if isinstance(self.prices, Exception):
                raise self.prices
            return gemini.CallResult(text="Here you go:\n```json\n" + json.dumps(self.prices) + "\n```", model_version=model,
                                     prompt_tokens=300, output_tokens=200,
                                     extra={"sources": [{"title": "Metal powder shop", "url": "https://example.test/316l"}]})
        return gemini.CallResult(text=json.dumps(WORK), model_version=model, prompt_tokens=500, output_tokens=400)


@pytest.fixture
def ai(settings, monkeypatch):
    settings.PART_INTELLIGENCE_ENABLED = True
    settings.AI_PROVIDER = "gemini"
    settings.GEMINI_API_KEY = "test-key"
    settings.AI_ALLOWED_COMPANIES = ["client-a"]
    settings.AI_CALLS_PER_MINUTE, settings.AI_CALLS_PER_DAY, settings.AI_DAILY_BUDGET_USD = 50, 100, 5.0
    fake = FakeAdapter()
    monkeypatch.setattr(service, "_adapter", lambda: fake)
    monkeypatch.setattr(service.time, "sleep", lambda s: None)
    return fake


def url(order):
    return f"/api/v1/operator/requests/{order['env'].pk}/estimate/"


def test_gemini_estimate_compares_the_three_routes_with_web_prices(world, order, ai):
    eng = login(world["op_eng"], world["a"])
    r = eng.post(url(order), {"action": "run"}, format="json")
    assert r.status_code == 200, r.content
    e = r.json()["latest"]
    assert e["mode"] == "ai" and e["version"] == 1 and e["quantity"] == 1
    routes = e["result"]["routes"]
    # 3D printing: material from the web search, machine and labour from the default rates
    am = routes["additive"]
    assert am["material_price_per_kg"] == 50 and am["material_price_source"]["url"] == "https://example.test/316l"
    rates = est.DEFAULT_RATES
    direct = 1 * 50 + (6 + 1) * rates["machine_rates"]["metal_am"] + 2 * rates["labour_rates"]["am_operator"] \
        + rates["heat_treatment_per_batch"] + rates["ndt_per_part"] + rates["shipping_per_order"]
    total = direct * (1 + rates["overhead_pct"] / 100) * (1 + rates["margin_pct"] / 100)
    assert am["cost"]["total"] == pytest.approx(total, abs=0.02)
    assert am["cost"]["low"] < am["cost"]["total"] < am["cost"]["high"]
    assert am["manpower_hours"] == 2 and am["total_days"] == 10
    # conventional: no web price for bar stock -> the Aries rate table, shown as such
    assert routes["conventional"]["material_price_source"]["source"] == "rate_table"
    assert routes["conventional"]["manpower_hours"] == 6
    # OEM: public price plus shipping, with its source
    assert routes["oem"]["price_per_part"] == 400 and routes["oem"]["cost"]["total"] == 400 + rates["oem_shipping_per_order"]
    assert e["result"]["cheapest"] in ("conventional", "additive", "oem") and e["result"]["fastest"]
    assert e["ai"]["price_search"]["sources"][0]["url"] == "https://example.test/316l"
    assert [c["search"] for c in ai.calls] == [False, True]  # work first, then the web prices
    assert "price" not in ai.calls[0]["prompt"].lower()  # the work call asks for no money
    with tenant_context(world["a"]):
        part_id = ManufacturingEstimate.objects.get(pk=e["id"]).part_id
        log = AIUsageLog.objects.get(part_id=part_id)  # one usage record for both calls (limits and daily budget)
        assert log.outcome == "ok" and log.prompt_tokens == 800 and log.output_tokens == 600


def test_failed_price_search_falls_back_to_the_rate_table(world, order, ai):
    ai.prices = gemini.AIError("provider_unavailable", "down", True)
    e = login(world["op_eng"], world["a"]).post(url(order), {"action": "run"}, format="json").json()["latest"]
    assert e["result"]["routes"]["additive"]["material_price_source"]["source"] == "rate_table"
    assert e["result"]["routes"]["oem"]["cost"] is None  # no public OEM price: ask for a quotation
    assert e["ai"]["price_search"]["ok"] is False


def test_manual_estimate_correction_and_route_choice(world, order, settings):
    settings.AI_PROVIDER = ""  # AI off: the engineer fills in the estimate
    eng = login(world["op_eng"], world["a"])
    d = eng.get(url(order)).json()
    assert d["latest"] is None and d["ai"]["enabled"] is False and d["can_prepare"] is True and d["can_choose"] is False
    assert eng.post(url(order), {"action": "run"}, format="json").status_code == 403  # AI not permitted
    e = eng.post(url(order), {"action": "manual"}, format="json").json()["latest"]
    assert e["mode"] == "manual" and e["work"]["conventional"]["kg_per_part"] == 0
    work = {k: v for k, v in WORK.items() if k in est.ROUTES}
    prices = {"materials": {"stainless steel bar": {"price_per_kg": 7, "source": "quotation", "note": "Supplier X"}},
              "oem": {"price_per_part": 380, "source": "quotation"}}
    e2 = eng.post(url(order), {"action": "adjust", "work": work, "prices": prices, "note": "From supplier quotes"}, format="json").json()
    assert e2["latest"]["version"] == 2 and e2["latest"]["mode"] == "adjusted"
    assert e2["latest"]["result"]["routes"]["conventional"]["material_price_per_kg"] == 7
    assert [v["version"] for v in e2["versions"]] == [2, 1]  # the earlier version is kept
    bad = {**work, "conventional": {**work["conventional"], "kg_per_part": -1}}
    assert eng.post(url(order), {"action": "adjust", "work": bad}, format="json").status_code == 400
    # only Admin or Manager choose; QA can read but not prepare
    assert eng.post(url(order), {"action": "choose", "route": "conventional"}, format="json").status_code == 403
    qa = login(world["op_qa"], world["a"])
    assert qa.get(url(order)).json()["can_prepare"] is False
    assert qa.post(url(order), {"action": "manual"}, format="json").status_code == 403
    chosen = login(world["op_mgr"]).post(url(order), {"action": "choose", "route": "conventional", "note": "Cheapest, 10 days"}, format="json").json()
    assert chosen["latest"]["chosen_route"] == "conventional" and chosen["latest"]["chosen_by"] == "op.mgr@example.test"
    # the client never sees the estimate
    detail = login(world["a_admin"]).get(f"/api/v1/requests/{order['ref']['id']}/").json()
    assert "estimate" not in json.dumps(detail).lower()


def test_rules_veto_a_route_the_ai_calls_feasible(world, order, ai, monkeypatch):
    monkeypatch.setattr(est, "feasibility_of", lambda part: {"additive": {"status": "not_suitable_verified", "label": "Not suitable",
                                                                         "disqualified": True}})
    e = login(world["op_eng"], world["a"]).post(url(order), {"action": "run"}, format="json").json()["latest"]
    assert e["result"]["routes"]["additive"]["feasible"] == "no"
    assert e["result"]["cheapest"] != "additive"
    r = login(world["op_admin"]).post(url(order), {"action": "choose", "route": "additive"}, format="json")
    assert r.status_code == 409


def test_rates_are_edited_by_admin_or_manager_and_used_by_new_estimates(world, order, ai):
    admin = login(world["op_admin"])
    r = admin.get("/api/v1/operator/estimate-rates/").json()
    assert r["rates"]["currency"] == "USD" and r["can_edit"] is True
    assert login(world["op_eng"]).put("/api/v1/operator/estimate-rates/", {"rates": {"currency": "INR"}}, format="json").status_code == 403
    assert admin.put("/api/v1/operator/estimate-rates/", {"rates": {"currency": "rupees"}}, format="json").status_code == 400
    saved = admin.put("/api/v1/operator/estimate-rates/", {"rates": {"currency": "INR", "machine_rates": {"metal_am": 5000}}}, format="json")
    assert saved.status_code == 200 and saved.json()["rates"]["machine_rates"]["metal_am"] == 5000
    e = login(world["op_eng"], world["a"]).post(url(order), {"action": "run"}, format="json").json()["latest"]
    assert e["result"]["currency"] == "INR" and e["rates"]["machine_rates"]["metal_am"] == 5000
    assert "INR" in ai.calls[-1]["prompt"]  # prices are asked in the Aries currency
