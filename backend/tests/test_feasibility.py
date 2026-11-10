"""Manufacturing feasibility screening (CN-007 Phase 3): OEM / additive / conventional rules, evidence gaps, constraints
overriding AI views, versioned immutable history, caching and escalation, AI failure, isolation and engineering review
(technical review only, separation of duties, no approval or release path).
A fake provider stands in for Gemini: these tests never call an external service."""
import json

import pytest
from django.db import connection, transaction

from apps.audit.models import AuditEvent
from apps.files.models import EngineeringFile
from apps.intelligence import gemini
from apps.intelligence.models import AIUsageLog, FeasibilityAssessment, FeasibilityReview
from apps.parts.models import SparePart
from apps.passports.models import DigitalPassport
from apps.projects.models import EngineerAccess
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Membership, Role

from .conftest import dbid, login, make_user
from .test_part_intelligence import SECRET, pi  # noqa: F401  (fixture)


def view(**over):
    v = {
        "oem": {"considerations": ["OEM identity not confirmed."], "information_needed": ["OEM part number"]},
        "additive": {"suggested_status": "potentially_suitable", "candidate_processes": ["metal_powder_bed_fusion"],
                     "considerations": ["Simple prismatic geometry."], "post_processing": ["Heat treatment"],
                     "inspection_and_testing": ["Dimensional inspection"], "risks": ["Hardness"],
                     "information_needed": ["Drawing"],
                     "rationale": "The insert is certified for production use by AM. A printed insert costs about 40 USD."},
        "conventional": {"suggested_status": "potentially_suitable", "candidate_methods": ["powder_metallurgy"],
                         "considerations": ["Pressed and sintered."], "inspection_and_testing": ["Hardness test"], "risks": [],
                         "information_needed": ["Grade"], "rationale": "Typical route."},
        "qualification_requirements": ["Material qualification"], "confidence": 0.6, "uncertainty": "Grade unknown.",
    }
    for k, val in over.items():
        v[k] = {**v[k], **val} if isinstance(val, dict) else val
    return json.dumps(v)


@pytest.fixture
def fz(pi, settings):  # noqa: F811
    settings.AM_BUILD_ENVELOPE_MM = None
    pi["fake"].default = view()
    return pi


def furl(part, tail=""):
    return f"/api/v1/parts/{part.pk}/feasibility/{tail}"


def run(client, part, tier=None):
    return client.post(furl(part, "assess/"), {"tier": tier} if tier else {}, format="json")


def test_rule_screening_of_the_four_synthetic_parts(fz):
    eng, p = fz["eng"], fz["parts"]
    out = {}
    for n in ("990100000101", "990100000102", "990100000103", "990100000104"):
        r = run(eng, p[n])
        assert r.status_code == 201, r.content
        out[n] = r.json()["assessment"]
    for n, a in out.items():
        assert a["version"] == 1 and a["ai_status"] == "none"
        assert a["authorisation"]["manufacturing_authorised"] is False
        # OEM availability stays unknown: never "unavailable"
        assert a["oem"]["status"] == "not_verified" and a["oem"]["status_label"] == "Identification / availability not verified"
        assert "unavailable" not in json.dumps(a["oem"]["evidence"]).lower()
        # evidence gaps are always listed; no part is potentially suitable without a drawing
        assert {"Engineering drawing", "Dimensional tolerances", "Surface finish"} <= set(a["missing_information"])
        assert a["additive"]["status"] != "potentially_suitable" and a["conventional"]["status"] != "potentially_suitable"
    cover, seal, insert, ring = (out[n] for n in sorted(out))
    assert cover["additive"]["status"] == "insufficient_information" and cover["conventional"]["status"] == "insufficient_information"
    assert "Material grade" in cover["missing_information"] and cover["conventional"]["candidate_methods"] == []
    # the seal is an assembly: never printable just because it is a mechanical component
    assert seal["additive"]["status"] == "specialist_assessment" and seal["conventional"]["status"] == "specialist_assessment"
    assert any(c["code"] == "assembly" for c in seal["constraints"])
    # carbide: no AM process; conventional route follows the stated material, still insufficient without a drawing
    assert insert["additive"]["status"] == "specialist_assessment" and insert["additive"]["candidate_processes"] == []
    assert any(c["code"] == "material_carbide" for c in insert["additive"]["constraints"])
    assert insert["conventional"]["status"] == "insufficient_information"
    assert [m["method"] for m in insert["conventional"]["candidate_methods"]] == ["powder_metallurgy", "grinding"]
    assert any("990100000099" in r for r in insert["oem"]["risks"])
    # wear ring: numbers are quoted, never given diameter/width roles
    dims = next(e for e in ring["additive"]["evidence"] if e["key"] == "dimensions")
    assert dims["state"] == "mentioned" and dims["value"] == "90 mm, 130 mm, 30 mm" and "roles" in dims["note"]
    assert "diameter" not in json.dumps(ring).lower().replace("(diameter, width, length)", "")
    assert ring["additive"]["status"] == "specialist_assessment"
    assert [c["code"] for c in ring["constraints"]] == ["material_grey_cast_iron"]  # one constraint per material reading
    assert "Material grade: verification needed (mentioned in description only)" in ring["missing_information"]
    assert {m["method"] for m in ring["conventional"]["candidate_methods"]} == {"casting", "cnc_machining"}
    assert ring["conventional"]["status"] == "insufficient_information"
    ref = next(e for e in ring["oem"]["evidence"] if e["key"] == "manufacturer_reference")
    assert ref["value"] == "29990104" and "not an OEM part number" in ref["note"]
    assert next(e for e in ring["oem"]["evidence"] if e["key"] == "oem_part_number")["state"] == "missing"
    assert fz["fake"].prompts == []  # rules only: no AI call
    with tenant_context(fz["tenant"]):  # nothing written to the part, no passport created
        assert SparePart.objects.get(pk=p["990100000104"].pk).category == "unknown"
        assert not DigitalPassport.objects.filter(part__in=p.values()).exists()


def _verify(tenant, part, **fields):
    with tenant_context(tenant):
        sp = SparePart.objects.get(pk=part.pk)
        prov = dict(sp.field_provenance or {})
        for k, v in fields.items():
            setattr(sp, k, v)
            prov[k] = {"source": "aries", "verified_by": "Engineer", "verified_at": "2026-10-27T00:00:00Z"}
        sp.field_provenance = prov
        sp.save()


def test_versions_follow_evidence_and_history_is_immutable(fz, settings):
    eng, cover, t = fz["eng"], fz["parts"]["990100000101"], fz["tenant"]
    v1 = run(eng, cover).json()["assessment"]
    again = run(eng, cover)
    assert again.status_code == 200 and again.json()["reused"] is True and again.json()["assessment"]["id"] == v1["id"]
    # verified evidence (material, dimensions, a drawing) moves the screening to "potentially suitable": still not approval
    _verify(t, cover, original_material="SS316", dimensions="Ø180 mm x 40 mm")
    with tenant_context(t):
        EngineeringFile.objects.create(tenant=t, part=cover, kind="dwg", category="drawing", title="Cover drawing")
    v2 = run(eng, cover).json()["assessment"]
    assert v2["version"] == 2
    assert v2["additive"]["status"] == "potentially_suitable" and v2["conventional"]["status"] == "potentially_suitable"
    assert v2["additive"]["status_label"] == "Potentially suitable: requires engineering qualification"
    assert {x["process"] for x in v2["additive"]["candidate_processes"]} >= {"metal_powder_bed_fusion"}
    assert "Verified AM build envelope" in v2["missing_information"]
    # a configured envelope and a verified dimension beyond it disqualify AM (verified constraint)
    settings.AM_BUILD_ENVELOPE_MM = [150.0, 150.0, 150.0]
    v3 = run(eng, cover).json()["assessment"]
    assert v3["version"] == 3 and v3["additive"]["status"] == "not_suitable_verified"
    settings.AM_BUILD_ENVELOPE_MM = None
    # a verified electrical category is a verified constraint; an unverified reading is not
    _verify(t, cover, category="electrical")
    v4 = run(eng, cover).json()["assessment"]
    assert v4["additive"]["status"] == "not_suitable_verified" and v4["conventional"]["status"] == "not_suitable_verified"
    hist = eng.get(furl(cover)).json()
    assert [a["version"] for a in hist["assessments"]] == [4, 3, 2, 1]
    assert hist["assessments"][3]["additive"]["status"] == "insufficient_information"  # v1 unchanged
    assert hist["assessments"][0]["inputs_current"] is True and hist["assessments"][3]["inputs_current"] is False
    with tenant_context(t):
        sid = FeasibilityAssessment.objects.get(pk=v1["id"]).pk
        for sql in ("UPDATE intelligence_feasibilityassessment SET additive_status = 'potentially_suitable' WHERE id = %s",
                    "DELETE FROM intelligence_feasibilityassessment WHERE id = %s"):
            with pytest.raises(Exception, match="immutable_record"), transaction.atomic(), connection.cursor() as c:
                c.execute(sql, [dbid(sid)])


def test_ai_view_is_whitelisted_cleaned_cached_and_never_upgrades(fz, settings):
    eng, insert, fake, t = fz["eng"], fz["parts"]["990100000103"], fz["fake"], fz["tenant"]
    r = run(eng, insert, "lite")
    assert r.status_code == 201, r.content
    a = r.json()["assessment"]
    assert a["ai_status"] == "ok" and a["ai"]["model"] == "gemini-3.1-flash-lite" and a["ai"]["prompt_version"]
    assert a["ai"]["usage"]["prompt_tokens"] == 400 and a["ai"]["usage"]["cost_usd"] > 0
    # the AI suggested "potentially suitable" for a carbide insert: the rule status stands
    assert a["additive"]["status"] == "specialist_assessment" and a["additive"]["rule_status"] == "specialist_assessment"
    assert {x["kind"] for x in a["ai"]["adjustments"]} == {"rule_status_kept"}
    assert a["additive"]["ai"]["suggested_status"] == "potentially_suitable"
    # unsupported certification claim and price removed
    assert "certified" not in a["additive"]["ai"]["rationale"] and "USD" not in a["additive"]["ai"]["rationale"]
    assert len(a["ai"]["removed"]) == 2
    # whitelist: schema and system prompt for feasibility; no reference codes, tags, plant, files or passport text
    sent = fake.prompts[0]
    assert sent["schema"] is gemini.FEASIBILITY_SCHEMA and sent["system"] is gemini.SYSTEM_FEASIBILITY
    for secret in ("29990103", "S-BO-0021", "XLPE", "91010000103", SECRET):
        assert secret not in sent["prompt"]
    payload = a["ai"]["sent"]
    assert payload["evidence"]["oem_part_number"] == {"state": "missing"}
    assert set(payload["evidence"]["manufacturer_reference"]) == {"state"}
    # cached for unchanged inputs; escalation is a separate version with its own model
    again = run(eng, insert, "lite")
    assert again.status_code == 200 and again.json()["reused"] is True and len(fake.prompts) == 1
    with tenant_context(t):
        assert AIUsageLog.objects.filter(tenant=t, outcome="cache_hit").count() == 1
    up = run(eng, insert, "pro").json()["assessment"]
    assert up["version"] == 2 and up["ai"]["model"] == "gemini-3.1-pro-preview" and len(fake.prompts) == 2
    assert AuditEvent.objects.filter(action="feasibility.assessed").count() == 2
    # where the rules say "potentially suitable", a more cautious AI view lowers it; "not suitable" needs verification
    cover = fz["parts"]["990100000101"]
    _verify(t, cover, original_material="SS316", dimensions="Ø180 mm x 40 mm")
    with tenant_context(t):
        EngineeringFile.objects.create(tenant=t, part=cover, kind="step", category="3d_model", title="Cover model")
    fake.answers = [view(additive={"suggested_status": "insufficient_information"},
                         conventional={"suggested_status": "not_suitable_verified"})]
    c = run(eng, cover, "lite").json()["assessment"]
    assert c["additive"]["status"] == "insufficient_information" and c["additive"]["rule_status"] == "potentially_suitable"
    assert c["conventional"]["status"] == "specialist_assessment"
    assert {x["kind"] for x in c["ai"]["adjustments"]} == {"ai_more_cautious"}
    assert "Cover model" not in fake.prompts[-1]["prompt"]  # file titles are never sent


def test_ai_unavailable_or_failing_keeps_the_rule_results(fz, settings):
    eng, ring, fake = fz["eng"], fz["parts"]["990100000104"], fz["fake"]
    settings.AI_PROVIDER = ""
    r = run(eng, ring, "lite")
    assert r.status_code == 403 and r.json()["error"]["code"] == "ai_not_permitted"
    assert run(eng, ring).status_code == 201  # rules only still work
    assert eng.get(furl(ring)).json()["ai"]["enabled"] is False
    settings.AI_PROVIDER = "gemini"
    fake.answers = [gemini.AIError("timeout", "No answer", True)] * 3
    a = run(eng, ring, "lite").json()["assessment"]
    assert a["ai_status"] == "failed" and a["ai"]["error_code"] == "timeout" and a["ai"]["usage"]["attempts"] == 3
    assert a["additive"]["status"] == "specialist_assessment" and a["conventional"]["status"] == "insufficient_information"
    fake.answers = ["not json", json.dumps({"oem": {}}), "{}"]
    b = run(eng, ring, "lite").json()["assessment"]  # a failed attempt is not reused: a new attempt is made
    assert b["version"] == a["version"] + 1 and b["ai_status"] == "invalid_response"
    manual = fz["parts"]["990100000099"]  # not an imported record: rules yes, external AI no
    assert run(eng, manual).status_code == 201
    assert run(eng, manual, "lite").json()["error"]["code"] == "ai_not_permitted_for_part"
    settings.AI_ALLOWED_COMPANIES = ["another-company"]
    assert run(eng, ring, "lite").json()["error"]["code"] == "ai_not_permitted"
    settings.AI_ALLOWED_COMPANIES, settings.AI_CALLS_PER_MINUTE = ["client-a"], 0
    r = run(eng, fz["parts"]["990100000101"], "lite")
    assert r.status_code == 429 and r.json()["error"]["code"] == "ai_rate_limited"


def test_isolation_and_access(fz, world):
    eng, ring = fz["eng"], fz["parts"]["990100000104"]
    run(eng, ring)
    for user in ("a_admin", "a_eng", "a_user", "a_proc"):  # clients see and do nothing here
        c = login(world[user], world["a"])
        assert c.get(furl(ring)).status_code == 403
        assert run(c, ring).status_code == 403
        assert c.get("/api/v1/intelligence/feasibility/").status_code == 403
    other = make_user("eng.b@example.test", world["operator"], Role.OPERATOR_ENGINEER)
    Membership.objects.create(user=other, tenant=world["b"], role=Role.OPERATOR_ENGINEER)
    cb = login(other, world["b"])  # another company's engineer: the part does not exist for them
    assert cb.get(furl(ring)).status_code == 404 and run(cb, ring).status_code == 404
    scoped = make_user("eng.scoped@example.test", world["operator"], Role.OPERATOR_ENGINEER)
    Membership.objects.create(user=scoped, tenant=world["a"], role=Role.OPERATOR_ENGINEER)
    with tenant_context(world["a"]):
        EngineerAccess.objects.create(tenant=world["a"], user=scoped, scope=EngineerAccess.Scope.PROJECTS)
    cs = login(scoped, world["a"])  # project-scoped engineer without this project
    assert cs.get(furl(ring)).status_code == 404
    assert cs.get("/api/v1/intelligence/feasibility/").json()["parts"] == []
    ov = eng.get("/api/v1/intelligence/feasibility/").json()
    assert [r["part_number"] for r in ov["parts"]] == ["990100000099", "990100000101", "990100000102", "990100000103", "990100000104"]
    assert ov["parts"][4]["assessment"]["additive"]["status"] == "specialist_assessment" and ov["parts"][1]["assessment"] is None


def test_engineering_review_is_technical_only_with_separation_of_duties(fz, world):
    eng, ring, t = fz["eng"], fz["parts"]["990100000104"], fz["tenant"]
    a = run(eng, ring).json()["assessment"]
    rv = furl(ring, f"{a['id']}/reviews/")

    def post(c, **body):
        return c.post(rv, body, format="json")

    # no approval or release path
    for word in ("approved", "release", "authorised"):
        r = post(eng, alternative="additive", decision=word)
        assert r.status_code == 403 and r.json()["error"]["code"] == "formal_approval_not_available"
    # the engineer who ran it cannot confirm it or correct it to a more favourable status
    assert post(eng, alternative="additive", decision="confirmed").json()["error"]["code"] == "self_confirmation"
    assert post(eng, alternative="conventional", decision="corrected", corrected_status="potentially_suitable",
                findings="Drawing found", evidence_references=[{"reference": "Customer drawing D-1"}]).json()["error"]["code"] == "self_confirmation"
    assert post(eng, alternative="conventional", decision="corrected", corrected_status="potentially_suitable",
                findings="x").json()["error"]["code"] == "evidence_required"
    assert post(eng, alternative="additive", decision="corrected", findings="x").json()["error"]["code"] == "invalid_corrected_status"
    assert post(eng, alternative="overall", decision="more_information_required").json()["error"]["code"] == "findings_required"
    with tenant_context(t):
        other_file = EngineeringFile.objects.create(tenant=t, part=fz["parts"]["990100000101"], kind="pdf", category="drawing", title="Other")
    assert post(eng, alternative="overall", decision="finding", findings="x",
                evidence_references=[{"file": str(other_file.pk)}]).json()["error"]["code"] == "invalid_references"
    # what the engineer can record: findings, a request for information, a more cautious correction
    r = post(eng, alternative="overall", decision="more_information_required", findings="Need drawing, grade and roles of 90/130/30 mm.")
    assert r.status_code == 201 and r.json()["review"]["independent"] is False
    r = post(eng, alternative="additive", decision="corrected", corrected_status="insufficient_information", findings="No drawing.")
    assert r.status_code == 201
    # an independent assigned engineer may confirm
    eng2 = make_user("eng.two@example.test", world["operator"], Role.OPERATOR_ENGINEER)
    Membership.objects.create(user=eng2, tenant=world["a"], role=Role.OPERATOR_ENGINEER)
    c2 = login(eng2, world["a"])
    r = post(c2, alternative="oem", decision="confirmed", note="No OEM record held.")
    assert r.status_code == 201 and r.json()["review"]["independent"] is True
    view_ = r.json()["assessments"][0]
    assert view_["oem"]["review"]["decision"] == "confirmed" and view_["additive"]["review"]["corrected_status"] == "insufficient_information"
    assert view_["overall_review"]["decision"] == "more_information_required"
    # the preliminary statuses and the part are unchanged by reviews; no passport, eligibility or release state appears
    assert view_["additive"]["status"] == "specialist_assessment"
    with tenant_context(t):
        sp = SparePart.objects.get(pk=ring.pk)
        assert sp.status == "draft" and sp.category == "unknown"
        assert not DigitalPassport.objects.filter(part=sp).exists()
        rid = FeasibilityReview.objects.filter(tenant=t).first().pk
        with pytest.raises(Exception, match="immutable_record"), transaction.atomic(), connection.cursor() as c:
            c.execute("UPDATE intelligence_feasibilityreview SET decision = 'confirmed' WHERE id = %s", [dbid(rid)])
    # clients cannot review; a superseded version cannot be reviewed
    assert post(login(world["a_admin"], world["a"]), alternative="oem", decision="finding", findings="x").status_code == 403
    _verify(t, ring, original_material="A48 class 40")
    run(eng, ring)
    r = post(c2, alternative="oem", decision="confirmed")
    assert r.status_code == 409 and r.json()["error"]["code"] == "assessment_superseded"
    assert AuditEvent.objects.filter(action="feasibility.reviewed").count() == 3


def test_batch_runs_rules_for_the_imported_parts(fz):
    eng, p = fz["eng"], fz["parts"]
    ids = [str(p[n].pk) for n in ("990100000101", "990100000102", "990100000103", "990100000104")]
    r = eng.post("/api/v1/intelligence/feasibility/assess-batch/", {"parts": ids}, format="json")
    assert r.status_code == 200
    res = r.json()["results"]
    assert [x["additive"] for x in res] == ["insufficient_information", "specialist_assessment", "specialist_assessment",
                                            "specialist_assessment"]
    assert all(x["oem"] == "not_verified" for x in res)
    assert eng.post("/api/v1/intelligence/feasibility/assess-batch/", {"parts": ids * 3}, format="json").status_code == 400
