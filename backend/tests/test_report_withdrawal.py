"""Report withdrawal and replacement (post-UAT D-19 / D-22): append-only withdrawal records next to the immutable report
and event tables. A withdrawn report keeps its number, revision, events and audit; no role receives its PDF or page images
afterwards; failed attempts are not recorded as previews or downloads; numbers are never reused; a replacement links back."""
import pytest
from django.db import connection, transaction

from apps.audit.models import AuditEvent
from apps.reports.models import PassportReport, PassportReportEvent, PassportReportReplacement, PassportReportWithdrawal
from apps.tenancy.context import tenant_context

from .conftest import dbid, login
from .test_passport_reports import gen, setup  # noqa: F401  (fixture)

REASON = "Captured confidential source values before containment"


def url(pid, rid, tail=""):
    return f"/api/v1/passports/{pid}/reports/{rid}/{tail}"


def events(world, rid):
    with tenant_context(world["a"]):
        return sorted(PassportReportEvent.objects.filter(report_id=rid).values_list("action", flat=True))


@pytest.fixture
def report(world, setup):  # noqa: F811
    eng = login(world["op_eng"], world["a"])
    r = gen(eng, setup["passport"]["id"], template="standard")
    assert r.status_code == 201, r.content
    return r.json()


def test_withdrawal_blocks_content_for_every_role_and_keeps_history(world, setup, report):  # noqa: F811
    pid, rid = setup["passport"]["id"], report["id"]
    eng, admin, user = login(world["op_eng"], world["a"]), login(world["a_admin"]), login(world["a_user"])
    assert admin.get(url(pid, rid, "pdf/")).status_code == 200 and user.get(url(pid, rid, "pages/1/")).status_code == 200
    before = events(world, rid)

    assert eng.post(url(pid, rid, "withdraw/"), {"reason": "short"}, format="json").status_code == 400  # reason is mandatory
    w = eng.post(url(pid, rid, "withdraw/"), {"reason": REASON}, format="json")
    assert w.status_code == 200, w.content
    body = w.json()
    assert body["withdrawal"]["reason"] == REASON and body["can_download"] is False and body["can_preview"] is False
    assert body["number"] == report["number"] and body["revision_number"] == report["revision_number"]
    assert eng.post(url(pid, rid, "withdraw/"), {"reason": REASON}, format="json").status_code == 409

    for c in (eng, admin, user):  # every file-content request is refused, nothing is logged for the refusal
        assert c.get(url(pid, rid, "pdf/")).status_code in (403, 410)
        r = c.get(url(pid, rid, "pages/1/"))
        assert r.status_code == 410 and r.json()["error"]["code"] == "report_withdrawn"
    assert events(world, rid) == before

    listed = {r["id"]: r for r in admin.get(f"/api/v1/passports/{pid}/reports/").json()}
    assert listed[rid]["withdrawal"]["at"] and "reason" not in listed[rid]["withdrawal"]  # the reason is Aries-internal
    with tenant_context(world["a"]):
        assert AuditEvent.objects.filter(action="passport_report.withdrawn", object_id=rid).count() == 1
        assert AuditEvent.objects.filter(action="passport_report.generated", object_id=rid).count() == 1


def test_only_aries_engineering_authority_can_withdraw(world, setup, report):  # noqa: F811
    pid, rid = setup["passport"]["id"], report["id"]
    for user, tenant in ((world["a_admin"], None), (world["a_eng"], None), (world["a_user"], None)):
        assert login(user, tenant).post(url(pid, rid, "withdraw/"), {"reason": REASON}, format="json").status_code == 403
    assert login(world["b_admin"]).post(url(pid, rid, "withdraw/"), {"reason": REASON}, format="json").status_code in (403, 404)


def test_withdrawal_records_are_append_only(world, setup, report):  # noqa: F811
    eng = login(world["op_eng"], world["a"])
    eng.post(url(setup["passport"]["id"], report["id"], "withdraw/"), {"reason": REASON}, format="json")
    with tenant_context(world["a"]):
        w = PassportReportWithdrawal.objects.get(report_id=report["id"])
        with pytest.raises(Exception, match="immutable_record"), transaction.atomic():
            with connection.cursor() as cur:
                cur.execute("UPDATE reports_passportreportwithdrawal SET reason = 'x' WHERE id = %s", [dbid(w.pk)])
        with pytest.raises(Exception, match="immutable_record"), transaction.atomic():
            with connection.cursor() as cur:
                cur.execute("DELETE FROM reports_passportreportwithdrawal WHERE id = %s", [dbid(w.pk)])


def test_replacement_links_back_and_numbers_are_never_reused(world, setup, report):  # noqa: F811
    pid, rid = setup["passport"]["id"], report["id"]
    eng = login(world["op_eng"], world["a"])
    assert gen(eng, pid, template="standard", replaces=rid).status_code == 409  # not withdrawn yet
    eng.post(url(pid, rid, "withdraw/"), {"reason": REASON}, format="json")
    new = gen(eng, pid, template="standard", replaces=rid)
    assert new.status_code == 201, new.content
    nj = new.json()
    assert nj["replaces"] == report["number"] and nj["number"] != report["number"] and nj["can_download"] is True
    assert gen(eng, pid, template="standard", replaces=rid).status_code == 409  # one replacement per withdrawn report
    listed = {r["id"]: r for r in eng.get(f"/api/v1/passports/{pid}/reports/").json()}
    assert listed[rid]["replaced_by"] == nj["number"]
    with tenant_context(world["a"]):
        numbers = list(PassportReport.objects.filter(passport_id=pid).values_list("number", flat=True))
        assert len(numbers) == len(set(numbers)) == 2
        assert PassportReportReplacement.objects.filter(withdrawn_id=rid, replacement_id=nj["id"]).exists()


def test_missing_file_is_a_clear_error_and_not_logged(world, setup, report, settings):  # noqa: F811
    pid, rid = setup["passport"]["id"], report["id"]
    with tenant_context(world["a"]):
        key = PassportReport.objects.get(pk=rid).storage_key
    (settings.LOCAL_STORAGE_ROOT / key).unlink()
    before = events(world, rid)
    admin = login(world["a_admin"])
    r = admin.get(url(pid, rid, "pdf/"))
    assert r.status_code == 410 and r.json()["error"]["code"] == "report_file_unavailable"
    assert admin.get(url(pid, rid, "pages/1/")).status_code == 410
    assert events(world, rid) == before


def test_quarantine_command_records_existing_withdrawal(world, setup, report):  # noqa: F811
    from django.core.management import call_command

    call_command("withdraw_report", tenant=world["a"].slug, number=report["number"], reason=REASON, actor=world["op_eng"].email,
                 file_state="quarantined", file_note="moved to quarantine (test)")
    with tenant_context(world["a"]):
        w = PassportReportWithdrawal.objects.get(report_id=report["id"])
        assert w.file_state == "quarantined" and w.created_by == world["op_eng"]
    with pytest.raises(Exception):  # a second record is refused
        call_command("withdraw_report", tenant=world["a"].slug, number=report["number"], reason=REASON, actor=world["op_eng"].email)


def test_builder_model_choice_and_client_renders_only_released_models(world, setup):  # noqa: F811
    """Post-UAT D-03 / D-08: the builder prints the chosen STEP version; client reports never render an unreleased model;
    the MTS prints the client company's name and location from its profile."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.files.models import Derivative, EngineeringFile
    from apps.files.storage import get_storage

    from .test_passport_reports import GLB, STEP, text

    pid, part = setup["passport"]["id"], setup["part"]["id"]
    eng = login(world["op_eng"], world["a"])
    second = eng.post("/api/v1/files/", {"part": part, "category": "3d_model", "file": SimpleUploadedFile("variant.stp", STEP)},
                      format="multipart").json()
    with tenant_context(world["a"]):
        fv = EngineeringFile.objects.get(pk=second["id"]).versions.first()
        key = f"tenants/{world['a'].pk}/derivatives/{second['id']}/v1/derivative.glb"
        size, sha = get_storage().save_new(key, [GLB])
        Derivative.objects.create(tenant=world["a"], file_version=fv, kind="glb", storage_key=key, size_bytes=size, sha256=sha, generator="test")
    r = gen(eng, pid, template="internal", model={"file": second["id"], "version": 1})
    assert r.status_code == 201, r.content
    with tenant_context(world["a"]):
        assert str(PassportReport.objects.get(pk=r.json()["id"]).model_file_version_id) == str(fv.pk)
    assert "variant.stp" in text(eng.get(url(pid, r.json()["id"], "pdf/")).content)
    refused = gen(eng, pid, template="standard", model={"file": second["id"], "version": 1})  # Aries-only model, client report
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "model_not_released"
    assert gen(eng, pid, template="internal", model={"file": setup["drawing"]["id"]}).status_code == 400  # not a STEP model
    world["a"].city, world["a"].country = "Sharjah", "United Arab Emirates"
    world["a"].save(update_fields=["city", "country"])
    mts = gen(eng, pid, template="mts")
    assert mts.status_code == 201, mts.content
    t = text(eng.get(url(pid, mts.json()["id"], "pdf/")).content)
    assert "Client A Energy" in t and "Sharjah, United Arab Emirates" in t
