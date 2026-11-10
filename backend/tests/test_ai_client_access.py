"""CN-007 role-based AI access (AI_CLIENT_ACCESS_ENABLED): capabilities per role, the Aries Admin management dashboard
and client workspace switch, the disclosure workflow (separation of duties, frozen snapshots, nothing client-visible
without an explicit share, withdrawal and supersession), client views by role with commercial confidentiality, member
access, assessment requests through the existing request workflow, client reports, and company isolation. The fake AI
provider stands in for Gemini: client actions must never reach it."""
import json

import pytest
from django.db import connection, transaction

from apps.audit.models import AuditEvent
from apps.intelligence.models import DisclosureEvent, SharedAssessment
from apps.parts.models import SparePart
from apps.servicerequests.models import ClientRequest, Notification
from apps.tenancy.context import set_user_context, tenant_context
from apps.tenancy.models import Membership, Role

from .conftest import dbid, login, make_user
from .test_cost_comparison import scenario
from .test_feasibility import fz, run  # noqa: F401  (fixture and helper)
from .test_part_intelligence import pi  # noqa: F401  (fixture)
from .test_service_requests import envelope_for

PRICES = [{"option": "oem", "amount": "1450.5", "currency": "usd", "lead_time_days": 28, "valid_until": "2026-12-31",
           "quote_reference": "AQ-2026-001"}]
SECRET_FINDINGS = "Internal finding: check the casting supplier's margin"


@pytest.fixture
def ca(fz, world, settings):  # noqa: F811
    settings.AI_CLIENT_ACCESS_ENABLED = True
    settings.AI_CLIENT_SHARING_COMPANIES = ["client-a"]
    eng, ring = fz["eng"], fz["parts"]["990100000104"]
    run(eng, ring)
    eng.post(f"/api/v1/parts/{ring.pk}/cost-comparisons/", {"scenario": scenario()}, format="json")
    rec = eng.post(f"/api/v1/parts/{ring.pk}/recommendations/", {}, format="json").json()["recommendation"]
    eng2 = make_user("eng.share@example.test", world["operator"], Role.OPERATOR_ENGINEER)
    Membership.objects.create(user=eng2, tenant=world["a"], role=Role.OPERATOR_ENGINEER)
    rev = login(eng2, world["a"])
    r = rev.post(f"/api/v1/parts/{ring.pk}/recommendations/{rec['id']}/reviews/",
                 {"decision": "corrected", "option": "none", "findings": SECRET_FINDINGS}, format="json")
    assert r.status_code == 201, r.content
    admin = login(world["op_admin"])
    return {**fz, "eng": eng, "rev": rev, "ring": ring, "rec": rec, "admin": admin, "world": world}


def notes(user) -> list[str]:
    """Notification titles of one user (per-user row-level security)."""
    with transaction.atomic():
        set_user_context(user.pk)
        return list(Notification.objects.filter(recipient=user).values_list("title", flat=True))


def durl(part, tail=""):
    return f"/api/v1/parts/{part.pk}/disclosures/{tail}"


def curl(part=None, tail=""):
    return "/api/v1/client-intelligence/" + (f"parts/{part.pk}/{tail}" if part else tail)


def enable(ca, client="a", on=True):
    return ca["admin"].put(f"/api/v1/admin/ai-management/clients/{ca['world'][client].pk}/", {"enabled": on, "note": "pilot"}, format="json")


def approve(cl, ca, rec_id=None, **extra):
    return cl.post(durl(ca["ring"]), {"recommendation": rec_id or ca["rec"]["id"], "summary": "Wear ring: no qualified route yet; "
                                      "a drawing and the material grade are needed.", **extra}, format="json")


def test_capabilities_follow_the_flag_and_the_role_matrix(fz, world, settings):  # noqa: F811
    settings.AI_CLIENT_SHARING_COMPANIES = ["client-a"]
    caps = lambda u, t=None: set(login(world[u], t).session_payload["capabilities"])  # noqa: E731
    assert not {c for c in caps("a_admin") if c.startswith("ai.")}  # flag off: nothing
    settings.AI_CLIENT_ACCESS_ENABLED = True
    assert {c for c in caps("op_admin") if c.startswith("ai.")} == {"ai.management"}
    assert {c for c in caps("op_eng", world["a"]) if c.startswith("ai.")} == {"ai.share"}
    assert {c for c in caps("op_eng", world["operator"]) if c.startswith("ai.")} == set()  # operator tenant: no client sharing
    assert {c for c in caps("a_admin") if c.startswith("ai.")} == {"ai.workspace", "ai.request", "ai.prices", "ai.reports", "ai.members"}
    assert {c for c in caps("a_eng") if c.startswith("ai.")} == {"ai.workspace", "ai.request", "ai.reports"}
    assert {c for c in caps("a_proc") if c.startswith("ai.")} == {"ai.workspace", "ai.prices", "ai.reports"}
    assert {c for c in caps("a_user") if c.startswith("ai.")} == {"ai.workspace"}
    # the Aries Admin gains no technical review or sharing authority, clients no internal AI access
    assert "intelligence.review" not in caps("op_admin") and "ai.share" not in caps("op_admin")
    assert not {c for c in caps("a_admin") if c.startswith("intelligence.")}


def test_admin_dashboard_is_aggregate_and_switches_only_approved_companies(ca):
    admin, w = ca["admin"], ca["world"]
    d = admin.get("/api/v1/admin/ai-management/")
    assert d.status_code == 200
    body = json.dumps(d.json())
    row = next(c for c in d.json()["companies"] if c["company"] == "Client A Energy")
    assert row["inventory"]["imported"] == 5 and row["feasibility"]["assessed"] == 1 and row["reviews"]["with_recommendation"] == 1
    assert row["workspace_enabled"] is False and row["sharing_permitted"] is True and row["external_ai_permitted"] is True
    assert "990100000104" not in body and "RING" not in body and SECRET_FINDINGS not in body  # no part-level records
    assert "usage" in d.json() and "by_company" in d.json()["usage"]
    r = enable(ca, "b")
    assert r.status_code == 409 and r.json()["error"]["code"] == "sharing_not_permitted"
    assert enable(ca).status_code == 200 and admin.get("/api/v1/admin/ai-management/").json()["companies"][0]["workspace_enabled"] is True
    for t in (w["operator"], w["a"]):  # recorded in the operator's and the client's audit trail
        with tenant_context(t):
            assert AuditEvent.objects.filter(tenant=t, action="ai_workspace.switched").count() == 1
    # engineers and clients cannot use the admin dashboard; the Admin cannot approve or share results
    assert ca["eng"].get("/api/v1/admin/ai-management/").status_code == 403
    assert login(w["a_admin"]).get("/api/v1/admin/ai-management/").status_code == 403
    assert admin.get(durl(ca["ring"])).status_code == 403


def test_disclosure_workflow_with_separation_of_duties_and_frozen_snapshots(ca):
    eng, rev, ring, w = ca["eng"], ca["rev"], ca["ring"], ca["world"]
    v = eng.get(durl(ring)).json()
    assert v["state"]["code"] == "engineering_reviewed" and v["can_approve"] is False and "not switched on" in v["approve_block"]
    assert approve(rev, ca).json()["error"]["code"] == "not_shareable"
    enable(ca)
    # the engineer who generated the version cannot approve it for sharing
    r = approve(eng, ca)
    assert r.status_code == 403 and r.json()["error"]["code"] == "self_approval"
    assert approve(rev, ca, summary="").json()["error"]["code"] == "summary_required"
    assert approve(rev, ca, released_prices=[{"option": "oem", "amount": "-1", "currency": "USD"}]).json()["error"]["code"] == "invalid_prices"
    r = approve(rev, ca, released_prices=PRICES)
    assert r.status_code == 201, r.content
    s = r.json()["shared_assessment"]
    assert s["status"] == "approved" and s["released_prices"][0]["amount"] == "1450.50" and s["released_prices"][0]["currency"] == "USD"
    assert approve(rev, ca).json()["error"]["code"] == "approval_pending"
    client = login(w["a_admin"])
    assert client.get(curl(ring)).json()["shared"] is None  # approved is not shared
    assert client.get(curl(ring)).json()["status"]["code"] == "preparing"
    # share -> visible; a newer internal version never becomes visible by itself
    assert eng.post(durl(ring, f"{s['id']}/share/"), {}, format="json").status_code == 200
    seen = client.get(curl(ring)).json()["shared"]
    assert seen["recommendation_version"] == 1 and seen["released_prices"][0]["quote_reference"] == "AQ-2026-001"
    sc = scenario()
    sc["quantity"] = 7
    eng.post(f"/api/v1/parts/{ring.pk}/cost-comparisons/", {"scenario": sc}, format="json")
    rec2 = eng.post(f"/api/v1/parts/{ring.pk}/recommendations/", {}, format="json").json()["recommendation"]
    assert rec2["version"] == 2 and client.get(curl(ring)).json()["shared"]["recommendation_version"] == 1
    st = eng.get(durl(ring)).json()["state"]
    assert st["code"] == "shared" and "newer internal version" in st["label"]
    assert approve(rev, ca, rec_id=rec2["id"]).json()["error"]["code"] == "not_shareable"  # not reviewed yet
    rev.post(f"/api/v1/parts/{ring.pk}/recommendations/{rec2['id']}/reviews/", {"decision": "information_requested", "findings": "x"}, format="json")
    # post-UAT D-20: a version whose latest review is "information requested" is not shareable
    assert approve(rev, ca, rec_id=rec2["id"]).json()["error"]["code"] == "not_shareable"
    rec3 = eng.post(f"/api/v1/parts/{ring.pk}/recommendations/", {"weights": {"cost": "0.6", "lead_time": "0.2", "evidence": "0.2"}},
                    format="json").json()["recommendation"]
    assert rev.post(f"/api/v1/parts/{ring.pk}/recommendations/{rec3['id']}/reviews/", {"decision": "approved_for_further_study",
                    "option": "additive", "findings": "Revised weights reviewed."}, format="json").status_code == 201
    s2 = approve(rev, ca, rec_id=rec3["id"]).json()["shared_assessment"]
    assert rev.post(durl(ring, f"{s2['id']}/share/"), {}, format="json").status_code == 200
    with tenant_context(w["a"]):
        assert SharedAssessment.objects.get(pk=s["id"]).status == "superseded"
        assert list(DisclosureEvent.objects.filter(part=ring).values_list("event", flat=True)) == [
            "approved", "shared", "approved", "superseded", "shared"]
    assert client.get(curl(ring)).json()["shared"]["recommendation_version"] == 3
    # withdrawal needs a reason; the client then sees no result, only the withdrawal
    assert eng.post(durl(ring, f"{s2['id']}/withdraw/"), {}, format="json").json()["error"]["code"] == "reason_required"
    assert eng.post(durl(ring, f"{s2['id']}/withdraw/"), {"reason": "Material grade under re-check"}, format="json").status_code == 200
    v = client.get(curl(ring)).json()
    assert v["shared"] is None and v["status"]["code"] == "withdrawn" and "Material grade under re-check" in json.dumps(v["history"])
    assert eng.post(durl(ring, f"{s2['id']}/share/"), {}, format="json").json()["error"]["code"] == "transition_not_allowed"
    # snapshots are immutable in the database; history rows cannot be changed or deleted
    with tenant_context(w["a"]):
        for sql in (f"UPDATE intelligence_sharedassessment SET snapshot = '{{}}' WHERE id = '{dbid(s['id'])}'",
                    f"UPDATE intelligence_sharedassessment SET status = 'shared' WHERE id = '{dbid(s2['id'])}'",
                    f"DELETE FROM intelligence_sharedassessment WHERE id = '{dbid(s['id'])}'",
                    "UPDATE intelligence_disclosureevent SET note = 'x'"):
            with pytest.raises(Exception, match="immutable_record"), transaction.atomic(), connection.cursor() as cur:
                cur.execute(sql)
    with tenant_context(w["a"]):
        assert AuditEvent.objects.filter(tenant=w["a"], action__startswith="ai_disclosure.").count() == 5
    # notifications to the client administrators on share and withdrawal
    assert sum(t.startswith("Assessment results") for t in notes(w["a_admin"])) == 3


def test_client_views_by_role_never_leak_internal_records(ca):
    eng, rev, ring, w = ca["eng"], ca["rev"], ca["ring"], ca["world"]
    enable(ca)
    s = approve(rev, ca, released_prices=PRICES).json()["shared_assessment"]
    eng.post(durl(ring, f"{s['id']}/share/"), {}, format="json")
    prompts_before = len(ca["fake"].prompts)
    admin, cl_eng, proc, user = (login(w[u]) for u in ("a_admin", "a_eng", "a_proc", "a_user"))
    v = admin.get(curl(ring)).json()
    assert v["access"]["can_see_prices"] is True and v["shared"]["released_prices"][0]["amount"] == "1450.50"
    assert v["shared"]["options"]["additive"]["suitability"] in {"not_qualified", "potentially_suitable", "excluded"}
    blob = json.dumps(v)
    for secret in (SECRET_FINDINGS, "REF-1", "Customs 2025", "gemini", "unit_cost", "engineering_estimate", "op.eng@", "eng.share@",
                   "\"inputs\"", "\"results\"", "\"ai\"", "savings"):
        assert secret not in blob, secret
    e = cl_eng.get(curl(ring)).json()
    assert e["shared"]["released_prices"] == [] and e["shared"]["prices_hidden"] is True and e["access"]["can_request"] is True
    # Procurement and Client User need the Client Admin's grant; Client Engineers can be removed
    for c in (proc, user):
        r = c.get(curl(ring))
        assert r.status_code == 403 and r.json()["error"]["code"] == "ai_access_not_granted"
    members = {m["email"]: m for m in admin.get(curl(tail="members/")).json()["members"]}
    assert members["a.eng@example.test"]["allowed"] is True and members["a.proc@example.test"]["allowed"] is False
    assert admin.put(curl(tail="members/"), {"user": members["a.admin@example.test"]["user"], "allowed": False}, format="json").status_code == 400
    assert cl_eng.get(curl(tail="members/")).status_code == 403
    for email in ("a.proc@example.test", "a.user@example.test"):
        assert admin.put(curl(tail="members/"), {"user": members[email]["user"], "allowed": True}, format="json").status_code == 200
    p = proc.get(curl(ring)).json()
    assert p["shared"]["released_prices"][0]["currency"] == "USD" and p["access"]["can_request"] is False
    u = user.get(curl(ring)).json()
    assert u["shared"]["released_prices"] == [] and u["access"]["can_download"] is False and u["access"]["can_request"] is False
    assert user.post(curl(ring, "request/"), {"reason": "assessment"}, format="json").status_code == 403
    assert user.get(curl(ring, "report.pdf")).status_code == 403
    admin.put(curl(tail="members/"), {"user": members["a.eng@example.test"]["user"], "allowed": False}, format="json")
    assert cl_eng.get(curl(ring)).status_code == 403
    # clients never reach the internal AI endpoints
    for c in (admin, proc):
        for url in (f"/api/v1/parts/{ring.pk}/recommendations/", f"/api/v1/parts/{ring.pk}/cost-comparisons/", durl(ring),
                    "/api/v1/intelligence/assessments/", "/api/v1/intelligence/disclosures/"):
            assert c.get(url).status_code == 403, url
    d = admin.get(curl(tail="dashboard/")).json()
    assert d["results_available"] == 1 and d["released_quotes"] == 1 and d["parts_in_scope"] == 5
    assert user.get(curl(tail="dashboard/")).json()["released_quotes"] is None
    assert len(ca["fake"].prompts) == prompts_before  # no external AI call from any client action


def test_assessment_requests_reports_and_company_isolation(ca, monkeypatch):
    eng, rev, ring, w = ca["eng"], ca["rev"], ca["ring"], ca["world"]
    cl_eng = login(w["a_eng"])
    assert cl_eng.get(curl()).json()["access"]["enabled"] is False
    assert cl_eng.post(curl(ring, "request/"), {"reason": "assessment"}, format="json").json()["error"]["code"] == "ai_workspace_off"
    enable(ca)
    ov = cl_eng.get(curl()).json()
    assert {p["part_number"]: p["status"]["code"] for p in ov["parts"]}["990100000104"] == "in_assessment"
    assert ov["counts"] == {"not_assessed": 4, "in_assessment": 1}  # post-UAT D-01: the Aries-created part is in scope too
    r = cl_eng.post(curl(ring, "request/"), {"reason": "reassessment", "remarks": "Drawing DWG-77 now available."}, format="json")
    assert r.status_code == 201 and r.json()["reference"].startswith("AR-")
    assert cl_eng.post(curl(ring, "request/"), {"reason": "assessment"}, format="json").json()["error"]["code"] == "request_open"
    assert cl_eng.post(curl(ring, "request/"), {"reason": "approve"}, format="json").status_code in (400, 409)
    with tenant_context(w["a"]):
        req = ClientRequest.objects.get(reference=r.json()["reference"])
        assert req.kind == "assessment" and req.part_id == ring.pk and "Reassessment requested" in req.remarks
    assert any("assessment request" in t for t in notes(w["op_eng"]))
    # Aries handles it in the existing intake (acknowledge / respond), and the client tracks it on the part
    env = envelope_for(w, r.json()["reference"])
    assert env.kind == "assessment" and env.part_number == "990100000104"
    assert eng.post(f"/api/v1/operator/requests/{env.pk}/act/", {"action": "acknowledge"}, format="json").status_code == 200
    assert eng.post(f"/api/v1/operator/requests/{env.pk}/act/", {"action": "schedule"}, format="json").status_code == 409
    part_view = cl_eng.get(curl(ring)).json()
    assert part_view["requests"][0]["status"] == "acknowledged"
    # reports: shared results only, client-facing content, prices only for the price roles
    assert cl_eng.get(curl(ring, "report.pdf")).json()["error"]["code"] == "not_shared"
    s = approve(rev, ca, released_prices=PRICES).json()["shared_assessment"]
    eng.post(durl(ring, f"{s['id']}/share/"), {}, format="json")
    seen = []

    def fake_run(job, workdir):
        seen.append(open(job["html"], encoding="utf-8").read())
        open(job["out"], "wb").write(b"%PDF-1.4 test")
        return {"ok": True}
    monkeypatch.setattr("apps.reports.services._run", fake_run)
    a = login(w["a_admin"]).get(curl(ring, "report.pdf"))
    assert a.status_code == 200 and a.content.startswith(b"%PDF") and "AQ-2026-001" in seen[-1] and SECRET_FINDINGS not in seen[-1]
    assert cl_eng.get(curl(ring, "report.pdf")).status_code == 200 and "AQ-2026-001" not in seen[-1]
    with tenant_context(w["a"]):
        assert AuditEvent.objects.filter(tenant=w["a"], action="ai_workspace.report_downloaded").count() == 2
    # company isolation: client B and an engineer of client B see nothing of client A
    b = login(w["b_admin"])
    assert b.get(curl(ring)).status_code == 403  # B's workspace is off
    ca["world"]["b"].slug  # noqa: B018
    from django.test import override_settings
    with override_settings(AI_CLIENT_SHARING_COMPANIES=["client-a", "client-b"]):
        assert ca["admin"].put(f"/api/v1/admin/ai-management/clients/{w['b'].pk}/", {"enabled": True}, format="json").status_code == 200
        assert b.get(curl(ring)).status_code == 404 and b.post(curl(ring, "request/"), {"reason": "assessment"}, format="json").status_code == 404
        assert b.get(curl()).json()["parts"] == []
    other = make_user("eng.b9@example.test", w["operator"], Role.OPERATOR_ENGINEER)
    Membership.objects.create(user=other, tenant=w["b"], role=Role.OPERATOR_ENGINEER)
    assert login(other, w["b"]).get(durl(ring)).status_code == 404


def test_sharing_refuses_a_reviewed_recommendation_whose_inputs_became_stale(ca):
    """D-23: a reviewed version whose part data changed afterwards (or whose cost belongs to another feasibility) cannot be
    approved for client sharing; it is marked as requiring reassessment."""
    enable(ca)
    with tenant_context(ca["world"]["a"]):
        SparePart.objects.filter(pk=ca["ring"].pk).update(dimensions="Ø150 x 30 mm")
    r = approve(ca["rev"], ca)
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_shareable"
    assert "changed after the feasibility" in r.json()["error"]["message"]
    view = ca["eng"].get(f"/api/v1/parts/{ca['ring'].pk}/recommendations/").json()
    assert view["recommendations"][0]["requires_reassessment"] is True
