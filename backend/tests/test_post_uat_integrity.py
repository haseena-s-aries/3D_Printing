"""Post-UAT Phase 1: confidentiality (D-18, D-16), review integrity (D-07), outdated inputs never reused for an approval
(D-13 follow-through to cost and recommendations) and the sharing guard (D-20). PostgreSQL + RLS."""
from apps.parts.models import SparePart
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Membership, Role

from .conftest import login, make_user
from .test_cost_comparison import scenario
from .test_feasibility import fz, run  # noqa: F401  (fixtures and helpers)
from .test_part_intelligence import pi  # noqa: F401  (fixture)
from .test_passport_reports import setup  # noqa: F401  (fixture)
from .test_recommendation import _prepare, rurl

SECRETS = ("JOB-SECRET-77", "EOS-SECRET-M290", "SECRET-SOLUTION", "L-PBF")


def test_client_roles_never_receive_the_aries_manufacturing_specification(world, setup):  # noqa: F811
    pid = setup["passport"]["id"]
    eng = login(world["op_eng"], world["a"])
    assert "JOB-SECRET-77" in str(eng.get(f"/api/v1/passports/{pid}/").json()["current_revision"]["content"])
    for user in ("a_admin", "a_eng", "a_user"):
        c = login(world[user])
        body = str(c.get(f"/api/v1/passports/{pid}/").json()) + str(c.get(f"/api/v1/passports/{pid}/revisions/").json())
        for secret in SECRETS:
            assert secret not in body, (user, secret)
        rl2 = c.get(f"/api/v1/passports/{pid}/").json()["current_revision"]["content"]["rl2"]
        assert "manufacturing_spec" not in rl2 and rl2["applicable_standards"] == "ASTM F3184"  # quality data stays visible


def test_client_edit_requests_cannot_see_or_request_aries_only_fields(world, setup, settings):  # noqa: F811
    settings.EDIT_REQUESTS_ENABLED = True
    part, pid = setup["part"]["id"], setup["passport"]["id"]
    admin = login(world["a_admin"])
    fields = admin.get(f"/api/v1/edit-requests/fields/?part={part}&passport={pid}").json()
    assert fields and not any(f["field"].startswith(("rl2.manufacturing_spec", "rl2.manufacturing_process", "rl2.manufacturing_solution"))
                              for f in fields)
    assert "JOB-SECRET" not in str(fields)
    r = admin.post("/api/v1/edit-requests/", {"part": part, "passport": pid, "reason": "x",
                                              "changes": [{"field": "rl2.manufacturing_spec.job_number", "proposed": "J-1"}]}, format="json")
    assert r.status_code == 400 and r.json()["error"]["code"] == "field_not_editable"
    eng = login(world["op_eng"], world["a"])
    assert any(f["field"] == "rl2.manufacturing_spec.job_number"
               for f in eng.get(f"/api/v1/edit-requests/fields/?part={part}&passport={pid}").json())


def test_client_summaries_count_only_released_documents(world, setup):  # noqa: F811
    part = setup["part"]["id"]
    eng, client = login(world["op_eng"], world["a"]), login(world["a_admin"])
    aries = eng.get(f"/api/v1/parts/{part}/").json()
    mine = client.get(f"/api/v1/parts/{part}/").json()
    released = len(client.get(f"/api/v1/files/?part={part}").json()["results"])
    assert aries["documents"]["total"] == 3 and mine["documents"]["total"] == released == 2  # drawing + released STEP
    assert mine["documents"]["pdf"] == 1 and aries["documents"]["pdf"] == 2  # the unreleased QC report is not counted
    eng.patch(f"/api/v1/files/{setup['other']['id']}/", {"client_visible": False}, format="json")
    step = next(f for f in eng.get(f"/api/v1/files/?part={part}").json()["results"] if f["kind"] == "step")
    eng.patch(f"/api/v1/files/{step['id']}/", {"client_visible": False}, format="json")  # withdraw the model
    mine = client.get(f"/api/v1/parts/{part}/").json()
    assert mine["documents"]["step"] == 0 and mine["has_3d"] is False  # an unreleased STEP and its 3D view are not hinted
    dash = client.get("/api/v1/dashboard/summary/").json()["documents"]
    assert dash["total"] == 1 and dash["parts_with_3d"] == 0


def _second_engineer(world):
    eng2 = make_user("eng.two@example.test", world["operator"], Role.OPERATOR_ENGINEER)
    Membership.objects.create(user=eng2, tenant=world["a"], role=Role.OPERATOR_ENGINEER)
    return login(eng2, world["a"])


def test_material_change_requires_reassessment_before_any_approval(fz, world):  # noqa: F811
    eng, ring = _prepare(fz)
    rec = eng.post(rurl(ring), {}, format="json").json()["recommendation"]
    c2 = _second_engineer(world)
    with tenant_context(fz["tenant"]):  # a proposed material change after the assessment (Case C)
        SparePart.objects.filter(pk=ring.pk).update(proposed_material="Duplex 2205", material_change_reason="Chlorides")
    view = eng.get(rurl(ring)).json()
    assert any("changed after the feasibility" in b for b in view["approval_blockers"])
    r = c2.post(rurl(ring, f"{rec['id']}/reviews/"), {"decision": "approved_for_further_study", "option": "conventional", "findings": "x"},
                format="json")
    assert r.status_code == 409 and r.json()["error"]["code"] == "recommendation_outdated"
    # reassessment: a new feasibility version sees the proposed material; the old cost comparison is not reused for approval
    fa = run(eng, ring).json()["assessment"]
    material = next(e for e in fa["additive"]["evidence"] if e["key"] == "material")
    assert material["value"] == "Duplex 2205" and material["state"] != "verified"
    # D-23: the cost comparison still belongs to the old feasibility version, so no recommendation version is generated at all
    refused = eng.post(rurl(ring), {}, format="json")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "inputs_not_aligned"
    assert "was calculated with feasibility v1, not the current v2" in refused.json()["error"]["message"]
    sc = scenario()
    sc["quantity"] = 5
    assert eng.post(f"/api/v1/parts/{ring.pk}/cost-comparisons/", {"scenario": sc}, format="json").status_code == 201
    rec3 = eng.post(rurl(ring), {}, format="json").json()["recommendation"]
    r = c2.post(rurl(ring, f"{rec3['id']}/reviews/"), {"decision": "approved_for_further_study", "option": "conventional",
                                                        "findings": "Re-assessed with the proposed material."}, format="json")
    assert r.status_code == 201, r.content
    assert eng.get(rurl(ring)).json()["approval_blockers"] == []


def test_sharing_summary_guard_knows_the_aries_only_passport_values(world, setup):  # noqa: F811
    from apps.intelligence.disclosure import confidential_terms

    with tenant_context(world["a"]):
        terms = confidential_terms(SparePart.objects.get(pk=setup["part"]["id"]))
    assert {"JOB-SECRET-77", "EOS-SECRET-M290", "SECRET-SOLUTION stress relieved", "L-PBF (laser powder bed fusion)"} <= set(terms)
    assert "ASTM F3184" not in terms  # client-visible quality data may be summarised


def test_intake_numbers_are_unique_across_companies_and_client_references_unchanged(world):
    from apps.servicerequests.models import RequestEnvelope

    refs = {}
    for client, tenant in (("a_admin", "a"), ("b_admin", "b")):
        with tenant_context(world[tenant]):
            part = SparePart.objects.create(tenant=world[tenant], part_number=f"{tenant.upper()}-1", name="Bush")
        body = {"request_type": "manufacturing", "quantity": 1, "required_date": "2030-01-01", "delivery_location": "Site",
                "priority": "routine", "remarks": "x", "part": str(part.pk)}
        r = login(world[client]).post("/api/v1/requests/", body, format="json")
        assert r.status_code == 201, r.content
        refs[client] = r.json()["reference"]
    assert refs["a_admin"] == refs["b_admin"]  # per-company client references (unchanged behaviour)
    with tenant_context(world["operator"]):
        numbers = list(RequestEnvelope.objects.values_list("intake_number", flat=True))
    assert len(numbers) == 2 and len(set(numbers)) == 2 and all(n.startswith("ARQ-") for n in numbers)
    admin = login(world["op_admin"], world["operator"])
    rows = admin.get("/api/v1/operator/requests/").json()
    assert sorted(r["intake_number"] for r in rows) == sorted(numbers)
    row = next(r for r in rows if r["client_tenant"] == str(world["a"].pk))
    detail = login(world["op_eng"], world["operator"]).get(f"/api/v1/operator/requests/{row['id']}/")  # assigned engineer (OQ-37 for admin)
    assert detail.status_code == 200, detail.content
    assert detail.json()["intake_number"] == row["intake_number"] and detail.json()["reference"] == row["reference"]


def test_parenthesised_remark_is_not_the_part_noun():
    from apps.intelligence import rules

    assert rules.family(rules.expand("Impeller (SYNTHETIC UAT)")["expanded"])["noun"] == "impeller"
    assert rules.family(rules.expand("Wear ring, pump casing")["expanded"])["noun"] == "ring"


def test_a_similar_new_part_does_not_make_the_original_assessment_outdated(fz, world):  # noqa: F811
    """Post-demo-readiness fix: company-wide duplicate context (e.g. a clone with the same description) is not a change of the
    original part's own inputs, so its reviewed recommendation stays current; a change of its own data still blocks."""
    eng, ring = _prepare(fz)
    eng.post(rurl(ring), {}, format="json")
    with tenant_context(fz["tenant"]):
        src = SparePart.objects.get(pk=ring.pk)
        SparePart.objects.create(tenant=fz["tenant"], part_number=f"{src.part_number}-M1", name=src.name, description=src.description,
                                 manufacturer=src.manufacturer, origin="client", review_state="accepted", submission_kind="clone", source_part=src)
    assert eng.get(rurl(ring)).json()["approval_blockers"] == []
    with tenant_context(fz["tenant"]):
        SparePart.objects.filter(pk=ring.pk).update(dimensions="Ø130 x 30 mm")
    assert any("changed after the feasibility" in b for b in eng.get(rurl(ring)).json()["approval_blockers"])


def test_d23_recommendations_use_an_aligned_chain_and_stale_versions_are_marked(fz, world, settings):  # noqa: F811
    """D-23: a recommendation is generated only from the current feasibility and a cost comparison calculated on that same
    version; it records the exact versions; earlier versions are kept unchanged and marked as requiring reassessment; review
    and sharing refuse them."""
    from apps.intelligence import runs
    from apps.intelligence.models import Recommendation

    eng, ring = _prepare(fz)
    rec1 = eng.post(rurl(ring), {}, format="json").json()["recommendation"]
    assert rec1["inputs"]["versions"] == {"feasibility": 1, "cost_comparison": 1, "cost_comparison_feasibility": 1, "passport_revision": None}
    with tenant_context(fz["tenant"]):
        SparePart.objects.filter(pk=ring.pk).update(dimensions="Ø140 x 30 mm")
    # stale feasibility: refused before generation
    r = eng.post(rurl(ring), {}, format="json")
    assert r.status_code == 409 and r.json()["error"]["code"] == "inputs_not_aligned" and "run the feasibility" in r.json()["error"]["message"]
    run(eng, ring)  # feasibility v2
    # an explicitly chosen cost comparison of the old feasibility is refused as well
    r = eng.post(rurl(ring), {"cost_comparison": rec1["inputs"]["cost_comparison"]}, format="json")
    assert r.status_code == 409 and r.json()["error"]["code"] == "inputs_not_aligned"
    view = eng.get(rurl(ring)).json()
    old = next(x for x in view["recommendations"] if x["version"] == 1)
    assert old["requires_reassessment"] is True and any("newer feasibility" in s for s in old["stale"])
    # quarterly / batch path: the run recalculates the stored scenario on the run's feasibility and generates an aligned version
    from .test_assessment_runs import detail, drain, start

    settings.WORKER_DB_ROLE = "app_worker"  # jobs are claimed as the worker role, as in the run tests

    with tenant_context(fz["tenant"]):
        before = {str(x.pk): (x.version, x.feasibility_id, x.cost_comparison_id) for x in Recommendation.objects.filter(part=ring)}
    run_ = start(eng).json()["run"]
    drain()
    item = next(i for i in detail(eng, run_["id"])["items"] if i["part_number"] == ring.part_number)
    src = item["sources"]
    assert item["status"] == "done"
    assert src["cost_comparison"]["feasibility_version"] == src["feasibility"]["version"] == 2
    assert any("recalculated on feasibility v2" in n for n in src["notes"])
    with tenant_context(fz["tenant"]):
        new = Recommendation.objects.get(pk=src["recommendation"]["id"])
        assert new.cost_comparison.feasibility_id == new.feasibility_id
        assert {str(x.pk): (x.version, x.feasibility_id, x.cost_comparison_id)
                for x in Recommendation.objects.filter(part=ring).exclude(pk=new.pk)} == before  # history unchanged
    assert eng.get(rurl(ring)).json()["approval_blockers"] == []
    # the old version can be neither approved nor shared
    c2 = _second_engineer(world)
    r = c2.post(rurl(ring, f"{rec1['id']}/reviews/"), {"decision": "approved_for_further_study", "option": "conventional", "findings": "x"},
                format="json")
    assert r.status_code == 409 and r.json()["error"]["code"] == "recommendation_superseded"


def test_d23_a_previous_run_result_built_on_a_misaligned_chain_is_not_reused(fz, settings, monkeypatch):  # noqa: F811
    """D-23: results of runs made before the fix (recommendation on a cost comparison of an older feasibility) are recomputed
    on an aligned chain by the next run instead of being carried forward unchanged."""
    from apps.intelligence import cost_service, recommendation_service, runs
    from apps.intelligence.models import CostComparison, Recommendation

    from .test_assessment_runs import detail, drain, start

    settings.WORKER_DB_ROLE = "app_worker"
    eng, ring = _prepare(fz)
    with tenant_context(fz["tenant"]):
        SparePart.objects.filter(pk=ring.pk).update(dimensions="Ø140 x 30 mm")
        old_cc = CostComparison.objects.get(part=ring)
    # simulate the pre-fix behaviour for one run: no recalculation, no alignment check
    monkeypatch.setattr(cost_service, "create", lambda ctx, part, inputs: (old_cc, True))
    monkeypatch.setattr(recommendation_service, "alignment_problems", lambda part, fa, cc: [])
    first = start(eng).json()["run"]
    drain()
    src1 = next(i for i in detail(eng, first["id"])["items"] if i["part_number"] == ring.part_number)["sources"]
    assert src1["cost_comparison"]["version"] == 1 and src1["feasibility"]["version"] == 2  # misaligned, as in run #20
    monkeypatch.undo()
    settings.WORKER_DB_ROLE = "app_worker"
    second = start(eng).json()["run"]
    drain()
    item = next(i for i in detail(eng, second["id"])["items"] if i["part_number"] == ring.part_number)
    src = item["sources"]
    assert item["status"] == "done" and "reused_from_run" not in src
    assert any(n.startswith(f"not reused from run #{first['number']}") for n in src["notes"])
    assert src["cost_comparison"]["feasibility_version"] == src["feasibility"]["version"] == 2
    with tenant_context(fz["tenant"]):
        rec = Recommendation.objects.get(pk=src["recommendation"]["id"])
        assert rec.cost_comparison.feasibility_id == rec.feasibility_id
    # later runs keep the aligned result: no new recommendation version, and the run after that reuses the item
    third = start(eng).json()["run"]
    drain()
    src3 = next(i for i in detail(eng, third["id"])["items"] if i["part_number"] == ring.part_number)["sources"]
    assert src3["recommendation"] == src["recommendation"] and src3["cost_comparison"]["id"] == src["cost_comparison"]["id"]
    fourth = start(eng).json()["run"]
    drain()
    assert next(i for i in detail(eng, fourth["id"])["items"] if i["part_number"] == ring.part_number)["status"] == "reused"
