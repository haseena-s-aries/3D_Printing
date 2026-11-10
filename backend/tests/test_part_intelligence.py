"""Part intelligence (CN-007 Phase 2): deterministic analysis, the optional external AI gate, payload whitelist,
schema validation, retries, caching, limits, cost logging and separation from engineer-verified values.
A fake provider stands in for Gemini: these tests never call an external service."""
import json

import pytest
from django.db import connection, transaction

from apps.audit.models import AuditEvent
from apps.intelligence import gemini, service
from apps.intelligence.models import AIUsageLog, PartAssessment
from apps.parts.models import SparePart
from apps.tenancy.context import tenant_context

from .conftest import login
from .test_inventory_import import parts, upload

SECRET = "AIzaTESTONLY-not-a-real-key-0000000000000"
GOOD = {
    "expanded_description": "Ring, wear, 95 mm, 135 mm, 30 mm, ASTM A48 class 40", "part_family": "wear ring", "category": "mechanical",
    "function": "Limits leakage between impeller and casing.", "is_assembly": "no",
    "material": {"value": "grey cast iron (stated)", "basis": "stated_in_description"},
    "am_screening": "possible_with_engineering_review", "am_process_options": ["metal_powder_bed_fusion"],
    "rationale": "Simple ring geometry. Typical replacement costs about 450 USD per piece.", "risks": ["Material substitution needed"],
    "information_needed": ["Drawing", "Operating temperature"], "confidence": 0.7, "uncertainty": "Dimension roles not stated.",
}


class FakeAdapter:
    """Records every prompt; answers from a queue of texts or AIErrors."""

    def __init__(self, answers, default=None):
        self.answers, self.prompts, self.default = list(answers), [], default

    def generate(self, *, model, tier, prompt, **kw):  # kw: schema, system (CN-007 Phase 3 feasibility view)
        self.prompts.append({"model": model, "tier": tier, "prompt": prompt, **kw})
        a = self.answers.pop(0) if self.answers else (self.default or json.dumps(GOOD))
        if isinstance(a, Exception):
            raise a
        return gemini.CallResult(text=a, model_version=model + "-001", prompt_tokens=400, output_tokens=200, thinking_tokens=0, latency_ms=900)


@pytest.fixture
def pi(settings, world, monkeypatch):
    settings.INVENTORY_IMPORT_ENABLED = True
    settings.PART_INTELLIGENCE_ENABLED = True
    settings.AI_PROVIDER = "gemini"
    settings.GEMINI_API_KEY = SECRET
    settings.AI_ALLOWED_COMPANIES = ["client-a"]
    settings.AI_CALLS_PER_MINUTE, settings.AI_CALLS_PER_DAY, settings.AI_DAILY_BUDGET_USD = 50, 100, 1.0
    monkeypatch.setattr(service.time, "sleep", lambda s: None)
    eng = login(world["op_eng"], world["a"])
    p1 = eng.post("/api/v1/projects/", {"code": "INV", "name": "Inventory pilot"}, format="json").json()
    eng.post("/api/v1/parts/", {"part_number": "990100000099", "name": "INSERT,CTNGTL,CRBDE", "manufacturer": "SYNTHETIC TOOLING GMBH",
                                "project": p1["id"]}, format="json")
    b = upload(eng, project=p1["id"]).json()
    assert eng.post(f"/api/v1/inventory-imports/{b['id']}/commit/", {"confirm": True}, format="json").status_code == 200
    fake = FakeAdapter([])
    monkeypatch.setattr(service, "_adapter", lambda: fake)
    return {"eng": eng, "parts": parts(world["a"]), "fake": fake, "tenant": world["a"]}


def url(part, tail=""):
    return f"/api/v1/parts/{part.pk}/intelligence/{tail}"


def test_rule_based_analysis_of_the_synthetic_records(pi):
    eng, p = pi["eng"], pi["parts"]
    ring = eng.get(url(p["990100000104"])).json()["analysis"]
    assert ring["classification"]["family"] == "Wear ring" and ring["classification"]["category"] == "mechanical"
    assert [d["mm"] for d in ring["mentions"]["dimensions"]] == [90.0, 130.0, 30.0]
    assert ring["mentions"]["materials"][0]["class"] == "grey cast iron"
    assert ring["manufacturer"]["possibly_truncated"] is True
    codes = {c["code"] for c in ring["constraints"]}
    assert {"material_grey_cast_iron", "insufficient_data"} <= codes and ring["screening"] == "insufficient_information"
    seal = eng.get(url(p["990100000102"])).json()["analysis"]
    assert seal["classification"]["family"] == "Mechanical seal, cartridge type" and seal["classification"]["assembly"] is True
    assert "Real manufacturer name" in seal["completeness"]["missing"]
    insert = eng.get(url(p["990100000103"])).json()["analysis"]
    assert insert["duplicates"]["same_description_and_manufacturer"] == ["990100000099"]
    assert insert["description"]["expanded"] == ["insert", "cutting tool", "carbide"]
    cover = eng.get(url(p["990100000101"])).json()["analysis"]
    assert cover["classification"]["family"] == "Bearing housing cover"
    assert cover["completeness"]["score"] > seal["completeness"]["score"]
    # nothing is written to the part by the analysis
    with tenant_context(pi["tenant"]):
        assert SparePart.objects.get(pk=p["990100000104"].pk).category == "unknown"


def test_ai_is_optional_and_gated_server_side(pi, settings, world):
    eng, ring = pi["eng"], pi["parts"]["990100000104"]
    settings.AI_PROVIDER = ""
    view = eng.get(url(ring)).json()
    assert view["ai"]["enabled"] is False and view["analysis"]["classification"]["family"] == "Wear ring"
    r = eng.post(url(ring, "assess/"), {"tier": "lite"}, format="json")
    assert r.status_code == 403 and r.json()["error"]["code"] == "ai_not_permitted"
    settings.AI_PROVIDER = "gemini"
    settings.AI_ALLOWED_COMPANIES = ["some-other-company"]  # a company not cleared for external AI
    assert eng.post(url(ring, "assess/"), {}, format="json").json()["error"]["code"] == "ai_not_permitted"
    settings.AI_ALLOWED_COMPANIES = ["client-a"]
    manual = pi["parts"]["990100000099"]  # created by hand, not an imported inventory record
    assert eng.post(url(manual, "assess/"), {}, format="json").json()["error"]["code"] == "ai_not_permitted_for_part"
    for user in ("a_admin", "a_eng", "a_user"):  # clients never see suggestions or request them
        c = login(world[user], world["a"])
        assert c.get(url(ring)).status_code == 403
        assert c.post(url(ring, "assess/"), {}, format="json").status_code == 403
        assert c.get("/api/v1/intelligence/overview/").status_code == 403
    settings.PART_INTELLIGENCE_ENABLED = False
    assert eng.get(url(ring)).status_code == 403
    assert pi["fake"].prompts == []


def test_ai_suggestion_is_whitelisted_validated_cached_and_kept_apart(pi):
    eng, ring, fake = pi["eng"], pi["parts"]["990100000104"], pi["fake"]
    r = eng.post(url(ring, "assess/"), {"tier": "lite"}, format="json")
    assert r.status_code == 201, r.content
    a = r.json()["assessment"]
    assert a["status"] == "ok" and a["model"] == "gemini-3.1-flash-lite" and a["model_version"] == "gemini-3.1-flash-lite-001"
    assert a["result"]["category"] == "mechanical" and a["confidence"] == 0.7
    assert a["usage"]["prompt_tokens"] == 400 and a["usage"]["output_tokens"] == 200 and a["usage"]["attempts"] == 1
    assert a["usage"]["cost_usd"] == pytest.approx(400 * 0.25 / 1e6 + 200 * 1.50 / 1e6)
    # a stated amount of money is removed from the suggestion and recorded as removed
    assert "450 USD" not in a["result"]["rationale"] and "[price or cost statement removed]" in a["result"]["rationale"]
    assert any("450 USD" in x for x in a["removed"])
    # only whitelisted fields were sent: no location, tag, ABC, manufacturer reference, ids or company
    sent = fake.prompts[0]["prompt"]
    assert set(a["inputs"]) == {"material_description", "manufacturer_name", "rule_based_findings"}
    for secret in (ring.plant, ring.functional_location, ring.equipment_tag, ring.manufacturer_reference, str(ring.pk), "Client A"):
        assert secret and secret not in sent
    assert "RING,WEAR,90MM,130MM,30MM,A48-40" in sent
    # the suggestion never changes the part (engineer-verified values stay as they are)
    with tenant_context(pi["tenant"]):
        part = SparePart.objects.get(pk=ring.pk)
        assert part.category == "unknown" and part.original_material == "" and part.dimensions == ""
    # unchanged input: reused without a new call; a stronger tier is a new call
    again = eng.post(url(ring, "assess/"), {"tier": "lite"}, format="json")
    assert again.status_code == 200 and again.json()["reused"] is True and len(fake.prompts) == 1
    assert eng.post(url(ring, "assess/"), {"tier": "flash"}, format="json").status_code == 201 and len(fake.prompts) == 2
    assert fake.prompts[1]["model"] == "gemini-3.8-flash"
    with tenant_context(pi["tenant"]):  # the usage log is under tenant RLS
        assert sorted(AIUsageLog.objects.values_list("outcome", flat=True)) == ["cache_hit", "ok", "ok"]
    view = eng.get(url(ring)).json()
    assert len(view["assessments"]) == 2 and all(x["current"] for x in view["assessments"])
    with tenant_context(pi["tenant"]):
        ev = AuditEvent.objects.filter(action="part_intelligence.ai_assessed").first()
        assert ev.data["model"] and ev.data["input_hash"] and "RING" not in json.dumps(ev.data)
        # stored suggestions never change
        with pytest.raises(Exception, match="immutable_record"), transaction.atomic():
            PartAssessment.objects.filter(tenant=pi["tenant"]).update(confidence=1.0)


def test_invalid_responses_retries_and_failures(pi, settings):
    eng, fake, p = pi["eng"], pi["fake"], pi["parts"]
    fake.answers = ["not json", json.dumps({**GOOD, "category": "hydraulic"}), json.dumps(GOOD)]
    a = eng.post(url(p["990100000101"], "assess/"), {}, format="json").json()["assessment"]
    assert a["status"] == "ok" and a["usage"]["attempts"] == 3 and a["usage"]["prompt_tokens"] == 1200
    fake.answers = ["{}", "{}", "{}"]
    a = eng.post(url(p["990100000102"], "assess/"), {}, format="json").json()["assessment"]
    assert a["status"] == "invalid_response" and a["error_code"] == "schema_mismatch" and a["usage"]["attempts"] == 3
    assert a["result"] == {} and a["confidence"] is None
    fake.answers = [gemini.AIError("provider_rate_limited", "quota", True, 429), gemini.AIError("model_not_available", "gone", False, 404)]
    a = eng.post(url(p["990100000103"], "assess/"), {}, format="json").json()["assessment"]
    assert a["status"] == "failed" and a["error_code"] == "model_not_available" and a["usage"]["attempts"] == 2
    # a failed or invalid result is not cached: the next request calls again
    before = len(fake.prompts)
    assert eng.post(url(p["990100000102"], "assess/"), {}, format="json").json()["assessment"]["status"] == "ok"
    assert len(fake.prompts) == before + 1


def test_rate_limit_daily_budget_and_batch(pi, settings):
    eng, p, fake = pi["eng"], pi["parts"], pi["fake"]
    settings.AI_CALLS_PER_MINUTE = 2
    r = eng.post("/api/v1/intelligence/assess-batch/", {"tier": "lite", "parts": [str(p[n].pk) for n in
                 ("990100000101", "990100000102", "990100000103", "990100000099")]}, format="json")
    res = r.json()["results"]
    assert [bool(x.get("assessment")) for x in res] == [True, True, False]
    assert res[2]["error"]["code"] == "ai_rate_limited" and len(fake.prompts) == 2
    with tenant_context(pi["tenant"]):  # refusal is logged
        assert AIUsageLog.objects.filter(outcome="refused", error_code="ai_rate_limited").count() == 1
    settings.AI_CALLS_PER_MINUTE = 50
    settings.AI_DAILY_BUDGET_USD = 0.0001
    r = eng.post(url(p["990100000104"], "assess/"), {}, format="json")
    assert r.status_code == 429 and r.json()["error"]["code"] == "ai_budget_exhausted"
    ov = eng.get("/api/v1/intelligence/overview/").json()
    assert [x["part_number"] for x in ov["parts"]] == ["990100000099", "990100000101", "990100000102", "990100000103", "990100000104"]
    assert ov["usage"]["total"]["calls"] == 2 and ov["usage"]["total"]["refused"] == 2
    assert ov["usage"]["total"]["cost_usd"] == pytest.approx(2 * (400 * 0.25 + 200 * 1.5) / 1e6)


def test_engineer_records_the_verified_classification(pi, world):
    eng, ring = pi["eng"], pi["parts"]["990100000104"]
    a = eng.post(url(ring, "assess/"), {}, format="json").json()["assessment"]
    r = eng.post(url(ring, "classification/"), {"category": "mechanical", "note": "Checked against description", "assessment": a["id"]},
                 format="json")
    assert r.status_code == 200, r.content
    prov = r.json()["classification"]["provenance"]
    assert r.json()["classification"]["category"] == "mechanical" and prov["verified_by"] and a["id"] in prov["basis"]
    c = login(world["a_admin"], world["a"])
    assert c.post(url(ring, "classification/"), {"category": "other"}, format="json").status_code == 403
    with tenant_context(pi["tenant"]):
        assert AuditEvent.objects.filter(action="part_intelligence.classification_recorded").exists()


def test_key_never_leaves_the_backend_and_admin_sees_only_usage(pi, world):
    eng, ring = pi["eng"], pi["parts"]["990100000104"]
    pi["fake"].answers = [gemini.AIError("provider_rejected", gemini.scrub(f"bad request for key {SECRET}"), False, 400)]
    bodies = [eng.post(url(ring, "assess/"), {}, format="json").content, eng.get(url(ring)).content,
              eng.get("/api/v1/intelligence/overview/").content, eng.get("/api/v1/auth/me/").content]
    admin = login(world["op_admin"], world["operator"])
    usage = admin.get("/api/v1/admin/intelligence-usage/")
    assert usage.status_code == 200 and usage.json()["usage"]["by_company"][0]["company"] == "Client A Energy"
    bodies.append(usage.content)
    assert all(SECRET.encode() not in b for b in bodies)
    with connection.cursor() as cur, tenant_context(pi["tenant"]):
        text = "CAST(data AS nvarchar(max))" if connection.vendor == "microsoft" else "data::text"
        cur.execute(f"SELECT count(*) FROM audit_auditevent WHERE {text} LIKE %s", [f"%{SECRET}%"])
        assert cur.fetchone()[0] == 0
    assert eng.get("/api/v1/admin/intelligence-usage/").status_code == 403


class SlowAdapter(FakeAdapter):
    """Answers after `delays` seconds per call (a cold start, then normal)."""

    def __init__(self, delays, answer):
        super().__init__([])
        self.delays, self.answer = list(delays), answer

    def generate(self, *, model, tier, prompt, **kw):
        import threading  # time.sleep is patched out by the fixture (no back-off waits)
        threading.Event().wait(self.delays.pop(0) if self.delays else 0)
        return gemini.CallResult(text=self.answer, model_version=model, prompt_tokens=400, output_tokens=200, latency_ms=10)


def test_ai_calls_have_a_true_total_deadline(pi, settings, monkeypatch):
    """A cold start cannot block processing: a slow attempt is abandoned at AI_TIMEOUT_SECONDS and the whole request,
    retries included, ends within AI_TOTAL_DEADLINE_SECONDS."""
    import time as _t
    settings.AI_TIMEOUT_SECONDS, settings.AI_TOTAL_DEADLINE_SECONDS, settings.AI_MAX_RETRIES = 1, 3, 2
    slow = SlowAdapter([1.6, 0], json.dumps(GOOD))  # first attempt hangs past its timeout, the retry answers
    monkeypatch.setattr(service, "_adapter", lambda: slow)
    t0 = _t.monotonic()
    result, call, totals, attempts, err = service.call_ai("gemini-3.1-flash-lite", "lite", "x")
    assert result is not None and attempts == 2 and err is None and _t.monotonic() - t0 < 2.5
    stuck = SlowAdapter([2.5, 2.5, 2.5], json.dumps(GOOD))  # never answers in time
    monkeypatch.setattr(service, "_adapter", lambda: stuck)
    t0 = _t.monotonic()
    result, call, totals, attempts, err = service.call_ai("gemini-3.1-flash-lite", "lite", "x")
    elapsed = _t.monotonic() - t0
    assert result is None and err.code == "deadline_exceeded" and elapsed < 3.6, (err.code, elapsed, attempts)
    # through the API the part still gets a stored, failed suggestion with the deadline recorded (no hang)
    monkeypatch.setattr(service, "_adapter", lambda: SlowAdapter([2.5, 2.5, 2.5], json.dumps(GOOD)))
    ring = pi["parts"]["990100000104"]
    r = pi["eng"].post(f"/api/v1/parts/{ring.pk}/intelligence/assess/", {"tier": "lite"}, format="json").json()["assessment"]
    assert r["status"] == "failed" and r["error_code"] == "deadline_exceeded"
