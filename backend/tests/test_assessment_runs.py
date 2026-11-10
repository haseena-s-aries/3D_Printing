"""Quarterly assessment runs and analytics (CN-007 Phase 6): first run, unchanged re-run (cached), changed-part
reassessment, run-to-run comparison, partial failure and retry, resumption, duplicate-run prevention, idempotency,
dashboard aggregation (estimated vs verified savings), missing/expired commercial evidence, reports, schedules,
isolation, the admin aggregate and no release bypass. Jobs run through the real queue (apps.jobs.queue.run_one).
A fake provider stands in for Gemini: these tests never call an external service."""
import io
import json

import pytest
from django.db import connection, transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.intelligence import runs as RUNS
from apps.intelligence.models import AssessmentRun, AssessmentRunItem, FeasibilityAssessment
from apps.jobs.queue import run_one
from apps.parts.models import SparePart
from apps.passports.models import DigitalPassport
from apps.projects.models import EngineerAccess
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Membership, Role

from .conftest import dbid, login, make_user
from .test_cost_comparison import c, scenario
from .test_feasibility import _verify, fz  # noqa: F401  (fixture and helper)
from .test_part_intelligence import pi  # noqa: F401  (fixture)

URL = "/api/v1/intelligence/assessments/"


@pytest.fixture(autouse=True)
def _worker_role(settings):
    settings.WORKER_DB_ROLE = "app_worker"  # claim jobs as the worker role (cross-tenant queue policy), as the worker does


def drain(limit=60):
    n = 0
    while run_one() is not None:
        n += 1
        assert n < limit, "job queue did not drain"
    return n


def ring_scenario():
    """OEM expensive, additive cheaper but not technically qualified: an estimated, never a verified, saving."""
    sc = scenario()
    sc["alternatives"]["oem"]["costs"]["unit_cost"] = c(1000, "EUR", "quotation", valid_until="2026-12-31")
    return sc


def start(cl, **body):
    return cl.post(URL, body, format="json")


def detail(cl, run_id):
    return cl.get(f"{URL}{run_id}/").json()


def test_first_run_repeat_changed_part_and_comparison(fz):  # noqa: F811
    eng, p, t = fz["eng"], fz["parts"], fz["tenant"]
    ring = p["990100000104"]
    # the run needs feasibility to exist for a cost comparison: create the ring's scenario after a first feasibility pass
    eng.post(f"/api/v1/parts/{ring.pk}/feasibility/assess/", {}, format="json")
    assert eng.post(f"/api/v1/parts/{ring.pk}/cost-comparisons/", {"scenario": ring_scenario()}, format="json").status_code == 201
    r1 = start(eng)
    assert r1.status_code == 201, r1.content
    run1 = r1.json()["run"]
    assert run1["status"] == "queued" and run1["part_count"] == 5 and run1["quarter"].startswith(str(timezone.localdate().year))
    dup = start(eng)  # duplicate-run prevention: one active run per company scope
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "assessment_run_in_progress"
    drain()
    d1 = detail(eng, run1["id"])
    assert d1["run"]["status"] == "completed" and d1["run"]["done_count"] == 5 and d1["run"]["reused_count"] == 0
    s = d1["summary"]
    assert (s["total_parts"], s["in_scope"], s["outside_scope"], s["assessed"], s["unassessed"]) == (5, 5, 0, 5, 0)
    assert s["insufficient_technical_data"] == 5 and s["am_candidates"] == 0 and s["conventional_candidates"] == 0
    assert s["am_specialist"] == 4 and s["conventional_specialist"] == 1, s  # + the Aries-created insert (D-01 scope)
    assert s["oem"]["identity_not_verified"] == 5 and s["oem"]["cost_evidence"]["no_comparison"]["count"] == 4
    assert s["oem"]["availability_not_documented"] == 5 and s["potentially_obsolete"] == 0
    assert s["review_backlog"] == {"preliminary": 5, "information_requested": 0, "total": 5, "reviewed": 0}
    # a cheaper option that is not technically qualified is an estimated saving only, never a verified one
    assert s["savings"]["estimated"] == {"USD": "4492.75"} and s["savings"]["verified"] == {} and s["savings"]["verified_parts"] == 0
    ring_item = next(i for i in d1["items"] if i["part_number"] == "990100000104")
    assert ring_item["result"]["savings"]["estimated"]["qualified"] is False and ring_item["sources"]["cost_comparison"]["version"] == 1
    assert d1["comparison"]["previous_run"] is None
    # repeated run without changes: every part reuses its previous result (no new versions)
    with tenant_context(t):
        before = FeasibilityAssessment.objects.filter(tenant=t).count()
    run2 = start(eng).json()["run"]
    drain()
    d2 = detail(eng, run2["id"])
    assert d2["run"]["reused_count"] == 5 and d2["run"]["done_count"] == 0 and d2["run"]["previous_run"] == 1
    assert sorted(d2["comparison"]["unchanged"]) == ["990100000099", "990100000101", "990100000102", "990100000103", "990100000104"]
    with tenant_context(t):
        assert FeasibilityAssessment.objects.filter(tenant=t).count() == before
    # changed parts: a verified material on the ring; a new cost scenario for the cover
    _verify(t, ring, original_material="ASTM A48 class 40 grey cast iron")
    cover = p["990100000101"]
    eng.post(f"/api/v1/parts/{cover.pk}/cost-comparisons/", {"scenario": scenario()}, format="json")
    run3 = start(eng).json()["run"]
    drain()
    d3 = detail(eng, run3["id"])
    status = {i["part_number"]: i["status"] for i in d3["items"]}
    assert status == {"990100000099": "reused", "990100000101": "done", "990100000102": "reused", "990100000103": "reused", "990100000104": "done"}
    cmp = d3["comparison"]
    assert cmp["previous_run"] == 2 and sorted(cmp["unchanged"]) == ["990100000099", "990100000102", "990100000103"]
    gap = next(x for x in cmp["evidence_gaps"] if x["part"] == "990100000104")
    assert "Material grade: verification needed (mentioned in description only)" in gap["closed"]
    cost = [x for x in cmp["cost_changes"] if x["part"] == "990100000101"]
    assert {x["option"] for x in cost} == {"oem", "additive"} and cost[0]["before"] is None
    assert any(x["part"] == "990100000101" and x["what"] == "OEM cost evidence" for x in cmp["oem_changes"])
    assert any(x["part"] == "990100000101" for x in cmp["lead_time_changes"])
    # history: finished runs are immutable; no passport, approval or release state changed
    with tenant_context(t):
        rid = AssessmentRun.objects.get(pk=run1["id"]).pk
        with pytest.raises(Exception, match="immutable_record"), transaction.atomic(), connection.cursor() as cur:
            cur.execute("UPDATE intelligence_assessmentrun SET part_count = 9 WHERE id = %s", [dbid(rid)])
        item = AssessmentRunItem.objects.filter(run_id=rid).first().pk
        with pytest.raises(Exception, match="immutable_record"), transaction.atomic(), connection.cursor() as cur:
            cur.execute("UPDATE intelligence_assessmentrunitem SET status = 'failed' WHERE id = %s", [dbid(item)])
        assert not DigitalPassport.objects.filter(tenant=t).exists()
        assert set(SparePart.objects.filter(tenant=t).values_list("status", flat=True)) == {"draft"}
    assert AuditEvent.objects.filter(action="assessment_run.completed").count() == 3
    hist = eng.get(URL).json()
    assert [r["number"] for r in hist["runs"]] == [3, 2, 1] and hist["latest"]["run"]["number"] == 3


def test_partial_failure_retry_resume_and_idempotency(fz, settings):  # noqa: F811
    eng, t = fz["eng"], fz["tenant"]
    r = start(eng, fault_injection={"fail_attempts": {"990100000102": 2}})
    assert r.status_code == 400 and r.json()["error"]["code"] == "fault_injection_disabled"
    settings.ASSESSMENT_FAULT_INJECTION = True
    r = start(eng, fault_injection={"fail_attempts": {"990100000102": 2}}, idempotency_key="q4-manual-1")
    run = r.json()["run"]
    same = start(eng, idempotency_key="q4-manual-1")
    assert same.status_code == 200 and same.json()["existing"] is True and same.json()["run"]["id"] == run["id"]
    drain()
    d = detail(eng, run["id"])
    assert d["run"]["status"] == "completed_with_errors" and d["run"]["failed_count"] == 1 and d["run"]["done_count"] == 4
    seal = next(i for i in d["items"] if i["part_number"] == "990100000102")
    assert seal["status"] == "failed" and seal["attempts"] == 2 and seal["error_code"] == "RuntimeError"
    assert d["summary"]["assessed"] == 4 and d["summary"]["unassessed"] == 1
    assert AuditEvent.objects.filter(action="assessment_run.part_failed").count() == 2
    rr = eng.post(f"{URL}{run['id']}/retry/", format="json")
    assert rr.status_code == 200 and rr.json()["run"]["status"] == "running"
    drain()
    d = detail(eng, run["id"])
    assert d["run"]["status"] == "completed" and d["run"]["failed_count"] == 0
    seal = next(i for i in d["items"] if i["part_number"] == "990100000102")
    assert seal["status"] == "done" and seal["attempts"] == 3
    assert eng.post(f"{URL}{run['id']}/retry/", format="json").json()["error"]["code"] == "not_retryable"
    # resumable: a stalled run (worker stopped after one part) is resumed without repeating finished parts
    settings.ASSESSMENT_FAULT_INJECTION = False
    stalled = start(eng).json()["run"]
    assert run_one() == "succeeded"  # one part processed; its follow-up job is "lost" below
    with tenant_context(t):
        from apps.jobs.models import Job
        Job.objects.filter(tenant=t, status="queued").update(status="failed", error_code="worker_stopped")
        assert AssessmentRunItem.objects.filter(run_id=stalled["id"]).exclude(status="pending").count() == 1
    eng.post(f"{URL}{stalled['id']}/retry/", format="json")
    drain()
    d = detail(eng, stalled["id"])
    assert d["run"]["status"] == "completed" and d["run"]["reused_count"] == 5 and d["progress"]["pending"] == 0


def test_expired_and_missing_commercial_evidence_in_the_dashboard(fz):  # noqa: F811
    eng, p = fz["eng"], fz["parts"]
    ring, insert = p["990100000104"], p["990100000103"]
    for part in (ring, insert):
        eng.post(f"/api/v1/parts/{part.pk}/feasibility/assess/", {}, format="json")
    expired = scenario()
    expired["alternatives"]["oem"]["costs"]["unit_cost"]["valid_until"] = "2026-09-30"
    expired["alternatives"]["oem"]["costs"]["logistics"]["valid_until"] = "2026-09-30"
    eng.post(f"/api/v1/parts/{ring.pk}/cost-comparisons/", {"scenario": expired}, format="json")
    missing = scenario()
    missing["alternatives"]["oem"]["costs"]["unit_cost"] = {"source": "missing"}
    eng.post(f"/api/v1/parts/{insert.pk}/cost-comparisons/", {"scenario": missing}, format="json")
    run = start(eng).json()["run"]
    drain()
    d = detail(eng, run["id"])
    s = d["summary"]
    assert s["oem"]["cost_evidence"]["includes_expired_quotation"]["count"] == 1
    assert s["oem"]["cost_evidence"]["incomplete"]["count"] == 1 and s["oem"]["with_expired_evidence"] == 1
    r = next(i for i in d["items"] if i["part_number"] == "990100000104")["result"]
    assert r["oem"]["lead_evidence"] == "includes_expired_quotation" and len(r["oem"]["expired"]) == 3
    assert s["savings"]["verified"] == {}  # neither an expired quotation nor an unqualified option can verify a saving


def test_isolation_permissions_admin_summary_reports_and_schedule(fz, world, monkeypatch):  # noqa: F811
    eng, t = fz["eng"], fz["tenant"]
    run = start(eng).json()["run"]
    drain()
    for user in ("a_admin", "a_eng", "a_user", "a_proc"):
        cl = login(world[user], world["a"])
        assert cl.get(URL).status_code == 403 and start(cl).status_code == 403
        assert cl.get(f"{URL}{run['id']}/").status_code == 403
    other = make_user("eng.b4@example.test", world["operator"], Role.OPERATOR_ENGINEER)
    Membership.objects.create(user=other, tenant=world["b"], role=Role.OPERATOR_ENGINEER)
    cb = login(other, world["b"])
    assert cb.get(f"{URL}{run['id']}/").status_code == 404 and cb.get(URL).json()["runs"] == []
    scoped = make_user("eng.scoped4@example.test", world["operator"], Role.OPERATOR_ENGINEER)
    Membership.objects.create(user=scoped, tenant=world["a"], role=Role.OPERATOR_ENGINEER)
    with tenant_context(world["a"]):
        EngineerAccess.objects.create(tenant=world["a"], user=scoped, scope=EngineerAccess.Scope.PROJECTS)
    cs = login(scoped, world["a"])
    assert detail(cs, run["id"])["items"] == [] and start(cs).json()["error"]["code"] == "nothing_to_assess"
    assert cs.put("/api/v1/intelligence/assessment-schedule/", {"enabled": True, "months": [1], "day_of_month": 1},
                  format="json").json()["error"]["code"] == "company_access_required"
    # Aries Admin: aggregate counts only, no engineering records
    adm = login(world["op_admin"])
    summ = adm.get("/api/v1/admin/assessment-summary/").json()
    row = next(x for x in summ["companies"] if x["company"] == "Client A Energy")
    assert row["counts"]["assessed"] == 5 and row["latest_run"] == 1  # post-UAT D-01: every part in the lifecycle, not only imported
    assert "9901" not in json.dumps(summ) and "INSERT" not in json.dumps(summ)
    assert eng.get("/api/v1/admin/assessment-summary/").status_code == 403
    # reports: Excel built here; PDF through the existing renderer (stubbed: no browser in unit tests)
    x = eng.get(f"{URL}{run['id']}/report.xlsx")
    assert x.status_code == 200 and x["Content-Type"].startswith("application/vnd.openxmlformats")
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(x.content))
    assert wb.sheetnames == ["Summary", "Parts", "Changes", "Run"] and wb["Parts"].max_row == 6
    rows = {r[0]: r[1] for r in wb["Summary"].iter_rows(min_row=4, values_only=True) if r[0]}
    assert rows["Assessed"] == 5 and rows["Verified savings"] == "none" and rows["Insufficient technical data"] == 5

    def fake_run(job, workdir):
        html = open(job["html"], encoding="utf-8").read()
        assert "Inventory assessment run 1" in html and "not technically qualified" in html
        open(job["out"], "wb").write(b"%PDF-1.4 test")
        return {"ok": True}
    monkeypatch.setattr("apps.reports.services._run", fake_run)
    pdf = eng.get(f"{URL}{run['id']}/report.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF") and pdf["Content-Type"] == "application/pdf"
    assert AuditEvent.objects.filter(action="assessment_run.report_downloaded").count() == 2
    # schedule: due this month -> one scheduled run per quarter, idempotent
    today = timezone.localdate()
    sch = eng.put("/api/v1/intelligence/assessment-schedule/", {"enabled": True, "months": [today.month], "day_of_month": 1}, format="json")
    assert sch.status_code == 200 and sch.json()["enabled"] is True
    first = RUNS.run_due_schedules(today)
    assert first == ["client-a: run 2"]
    drain()
    assert RUNS.run_due_schedules(today) == []
    with tenant_context(t):
        sched = AssessmentRun.objects.get(tenant=t, kind="scheduled")
        assert sched.status == "completed" and sched.reused_count == 5 and sched.idempotency_key.startswith("scheduled:")
