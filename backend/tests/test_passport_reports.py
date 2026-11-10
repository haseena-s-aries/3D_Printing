"""Digital Passport PDF reports (CN-005, R1-R8 approved). Real rendering with the local Chromium renderer; PDF text is
checked with pypdfium2. Client reports never contain manufacturing parameters, engineering notes, job data or CAD
originals; drafts are watermarked; marks V/D/C/M are honest; permissions, isolation and history hold. PostgreSQL + RLS."""
from pathlib import Path

import pypdfium2 as pdfium
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.files.models import Derivative, EngineeringFile
from apps.files.storage import get_storage
from apps.passports.models import DigitalPassport, PassportRevision
from apps.reports.models import PassportReport, PassportReportEvent
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Membership

from .conftest import login

GLB = (Path(__file__).parent / "fixtures" / "sleeve_synthetic.glb").read_bytes()


def valid_pdf(pages=1) -> bytes:
    import io

    from pypdf import PdfWriter

    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=595, height=842)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()
STEP = (Path(__file__).parent / "fixtures" / "sleeve_d45_h40_5_synthetic.stp").read_bytes()
CONTENT = {
    "rl1": {"original_material_grade": "CF8M", "part_size": "Ø45 x 40.5 mm", "motion": "rotating", "rpm": "1450",
            "proposed_material": "Duplex 2205", "proposed_material_reason": "Chlorides",
            "value_sources": {"proposed_material": "client_submitted", "proposed_material_reason": "client_submitted"}},
    "rl2": {"applicable_standards": "ASTM F3184", "ndt": "Visual; Dye penetrant (PT)", "manufacturing_process": "L-PBF (laser powder bed fusion)",
            "manufacturing_solution": "SECRET-SOLUTION stress relieved",
            "mechanical_acceptance": [{"property": "tensile", "requirement": "≥ 485", "unit": "MPa", "standard": "ISO 6892-1", "frequency": "Per build"}],
            "manufacturing_spec": {"job_number": "JOB-SECRET-77", "machine": "EOS-SECRET-M290", "feedstock": "316L powder SECRET-LOT",
                                   "layer_thickness": "40 µm", "printing_hours": 6.5,
                                   "process_parameters": [{"name": "Laser power", "value": "285", "unit": "W"}]}},
    "notes": "SECRET-ENGINEERING-NOTE conflict on material",
}


def text(pdf_bytes: bytes) -> str:
    pdf = pdfium.PdfDocument(pdf_bytes)
    return " ".join(pdf[i].get_textpage().get_text_range() for i in range(len(pdf))).replace("\r\n", " ")


@pytest.fixture
def setup(settings, world):
    settings.CLIENT_PART_SUBMISSIONS_ENABLED = True
    w = world
    eng = login(w["op_eng"], w["a"])
    proj = eng.post("/api/v1/projects/", {"code": "P1", "name": "Pumps"}, format="json").json()
    part = eng.post("/api/v1/parts/", {"part_number": "SLV-45", "name": "Sleeve", "project": proj["id"]}, format="json").json()
    login(w["a_admin"])  # client value on the part master: equipment entered later by client would be C; keep Aries-entered here
    passport = eng.post("/api/v1/passports/", {"part": part["id"], "initial_content": CONTENT}, format="json").json()
    step = eng.post("/api/v1/files/", {"part": part["id"], "passport": passport["id"], "category": "3d_model", "client_visible": "true",
                                        "file": SimpleUploadedFile("sleeve.stp", STEP)}, format="multipart").json()  # released (D-02)
    drawing = eng.post("/api/v1/files/", {"part": part["id"], "category": "drawing", "client_visible": "true", "file": SimpleUploadedFile("drawing.pdf", valid_pdf())},
                       format="multipart").json()
    other = eng.post("/api/v1/files/", {"part": part["id"], "category": "inspection", "file": SimpleUploadedFile("qc.pdf", valid_pdf())},
                     format="multipart").json()
    with tenant_context(w["a"]):  # attach a converted GLB as the worker would
        fv = EngineeringFile.objects.get(pk=step["id"]).versions.first()
        key = f"tenants/{w['a'].pk}/derivatives/{step['id']}/v1/derivative.glb"
        size, sha = get_storage().save_new(key, [GLB])
        Derivative.objects.create(tenant=w["a"], file_version=fv, kind="glb", storage_key=key, size_bytes=size, sha256=sha, generator="test")
    return {"part": part, "passport": passport, "drawing": drawing, "other": other, "project": proj}


def gen(client, pid, **body):
    return client.post(f"/api/v1/passports/{pid}/reports/", body, format="json")


def pdf_of(client, pid, rid):
    r = client.get(f"/api/v1/passports/{pid}/reports/{rid}/pdf/")
    assert r.status_code == 200, r.content
    return b"".join(r) if hasattr(r, "streaming_content") else r.content


def test_client_and_internal_variants_content(world, setup):
    eng = login(world["op_eng"], world["a"])
    pid = setup["passport"]["id"]
    c = gen(eng, pid, variant="client")
    assert c.status_code == 201, c.content
    cr = c.json()
    assert cr["number"].startswith(f"RPT-{setup['passport']['passport_number']}-R1-") and not cr["number"].endswith("-INT")
    assert cr["views_status"] == "rendered" and cr["watermarked"] is True and cr["revision_status"] == "draft"
    t = text(pdf_of(eng, pid, cr["id"]))
    for must in ("DRAFT — NOT APPROVED FOR MANUFACTURING", setup["passport"]["passport_number"], "rev 1", cr["number"],
                 "Verified (approved passport revision)", "Client-submitted (not verified by Aries)", "Front view", "Isometric view",
                 "Duplex 2205", "Not assessed by Aries Engineering", "Per build", "sleeve.stp"):
        assert must in t, must
    for never in ("SECRET", "EOS-SECRET", "JOB-SECRET", "Laser power", "Manufacturing specification (BR-026)", "L-PBF"):
        assert never not in t, never
    i = gen(eng, pid, variant="internal").json()
    assert i["number"].endswith("-INT")
    ti = text(pdf_of(eng, pid, i["id"]))
    for must in ("ARIES CONFIDENTIAL", "EOS-SECRET-M290", "JOB-SECRET-77", "Laser power", "SECRET-SOLUTION", "L-PBF"):
        assert must in ti, must
    assert "SECRET-ENGINEERING-NOTE" not in ti and "SECRET-ENGINEERING-NOTE" not in t  # notes never printed


def test_marks_are_honest(world, setup):
    eng = login(world["op_eng"], world["a"])
    pid = setup["passport"]["id"]
    rid = gen(eng, pid, variant="client").json()["id"]
    with tenant_context(world["a"]):
        report = PassportReport.objects.get(pk=rid)
    # data is fingerprinted; reconstruct the printed marks from the builder for the stored revision
    from apps.reports import builder

    with tenant_context(world["a"]):
        p = DigitalPassport.objects.get(pk=pid)
        data = builder.collect(p, p.revisions.first(), "client", "Client A Energy", [], {})
    marks = {row[0]: row[2] for row in data["material"] + data["context"] + data["identification"]}
    assert marks["Proposed material"] == "C" and marks["Original material grade"] == "D"  # draft revision: never V
    assert marks["Material identification"] == "M" and marks["Criticality"] == "M"
    assert "V" not in marks.values()
    assert len(report.content_sha256) == 64 and len(report.pdf_sha256) == 64


def test_no_model_means_view_unavailable(world, setup):
    eng = login(world["op_eng"], world["a"])
    p2 = eng.post("/api/v1/parts/", {"part_number": "NOVIEW", "name": "x", "project": setup["project"]["id"]}, format="json").json()
    pp = eng.post("/api/v1/passports/", {"part": p2["id"]}, format="json").json()
    r = gen(eng, pp["id"], variant="client").json()
    assert r["views_status"].startswith("No STEP model")
    t = text(pdf_of(eng, pp["id"], r["id"]))
    assert "View not available" in t and t.count("View not available") == 3


def test_roles_and_server_side_permissions(world, setup):
    pid = setup["passport"]["id"]
    admin = login(world["a_admin"])
    assert gen(admin, pid, variant="internal").status_code == 403
    rid = gen(admin, pid, variant="client").json()["id"]
    assert gen(login(world["a_eng"]), pid, variant="client").status_code == 201
    user = login(world["a_user"])
    assert gen(user, pid, variant="client").status_code == 403
    assert user.get(f"/api/v1/passports/{pid}/reports/{rid}/pdf/").status_code == 403  # preview only
    page = user.get(f"/api/v1/passports/{pid}/reports/{rid}/pages/1/")
    assert page.status_code == 200 and page["Content-Type"] == "image/png"
    assert login(world["a_proc"]).get(f"/api/v1/passports/{pid}/reports/").status_code == 403
    iid = gen(login(world["op_eng"], world["a"]), pid, variant="internal").json()["id"]
    listed = {x["variant"] for x in admin.get(f"/api/v1/passports/{pid}/reports/").json()}
    assert listed == {"client"}  # internal reports are invisible to clients
    assert admin.get(f"/api/v1/passports/{pid}/reports/{iid}/pdf/").status_code == 403
    assert admin.get(f"/api/v1/passports/{pid}/reports/{iid}/pages/1/").status_code == 403
    # the Aries Admin has no access to client passports at all
    assert login(world["op_admin"]).get(f"/api/v1/passports/{pid}/reports/").status_code in (403, 404)


def test_attachments_limited_by_variant(world, setup):
    pid = setup["passport"]["id"]
    admin = login(world["a_admin"])
    r = gen(admin, pid, variant="client", attachments=[setup["drawing"]["id"]])
    assert r.status_code == 201 and r.json()["attachments"][0]["title"] == "drawing.pdf"
    base = gen(admin, pid, variant="client").json()
    assert r.json()["page_count"] == base["page_count"] + 1
    bad = gen(admin, pid, variant="client", attachments=[setup["other"]["id"]])
    assert bad.status_code == 403 and bad.json()["error"]["code"] == "attachment_not_permitted"
    eng = login(world["op_eng"], world["a"])
    assert gen(eng, pid, variant="internal", attachments=[setup["other"]["id"]]).status_code == 201


def test_isolation_and_project_scope(world, setup):
    pid = setup["passport"]["id"]
    assert login(world["b_admin"]).get(f"/api/v1/passports/{pid}/reports/").status_code == 404
    assert gen(login(world["b_admin"]), pid, variant="client").status_code == 404
    eng = login(world["op_eng"], world["a"])
    p2 = eng.post("/api/v1/projects/", {"code": "P2", "name": "x"}, format="json").json()
    mid = Membership.objects.get(user=world["op_eng"], tenant=world["a"]).pk
    login(world["op_admin"]).put(f"/api/v1/clients/{world['a'].pk}/engineers/{mid}/access/", {"scope": "projects", "project_ids": [p2["id"]]}, format="json")
    assert login(world["op_eng"], world["a"]).get(f"/api/v1/passports/{pid}/reports/").status_code == 404


def test_history_audit_immutability_and_unchanged_gates(world, setup):
    pid = setup["passport"]["id"]
    eng = login(world["op_eng"], world["a"])
    with tenant_context(world["a"]):
        before = PassportRevision.objects.get(passport_id=pid, revision_number=1)
        before_content, before_upd = dict(before.content), before.updated_at
    rid = gen(eng, pid, variant="client").json()["id"]
    pdf_of(eng, pid, rid)
    login(world["a_user"]).get(f"/api/v1/passports/{pid}/reports/{rid}/pages/1/")
    rows = eng.get(f"/api/v1/passports/{pid}/reports/").json()
    events = {e["action"] for e in rows[0]["events"]}
    assert events == {"generated", "downloaded", "previewed"} and rows[0]["generated_by"]
    with tenant_context(world["a"]):
        from apps.audit.models import AuditEvent

        assert {"passport_report.generated", "passport_report.downloaded", "passport_report.previewed"} <= set(
            AuditEvent.objects.values_list("action", flat=True))
        report = PassportReport.objects.get(pk=rid)
        report.number = "changed"
        with pytest.raises(Exception):
            from django.db import transaction

            with transaction.atomic():
                report.save()
        ev = PassportReportEvent.objects.filter(report_id=rid).first()
        with pytest.raises(Exception):
            from django.db import transaction

            with transaction.atomic():
                ev.delete()
        after = PassportRevision.objects.get(passport_id=pid, revision_number=1)
        assert after.content == before_content and after.updated_at == before_upd
        p = DigitalPassport.objects.get(pk=pid)
        assert p.manufacturing_eligibility == "not_eligible" and p.publication_state == "draft"


def test_client_reports_use_the_current_revision(world, setup):
    pid = setup["passport"]["id"]
    eng = login(world["op_eng"], world["a"])
    with tenant_context(world["a"]):
        PassportRevision.objects.filter(passport_id=pid).update(status="approved")  # stored state only; no approval API (OQ-35)
    eng.post(f"/api/v1/passports/{pid}/revisions/", {"change_summary": "rev 2"}, format="json")
    r = gen(login(world["a_admin"]), pid, variant="client", revision=1)
    assert r.status_code == 400 and r.json()["error"]["code"] == "current_revision_only"
    old = gen(eng, pid, variant="client", revision=1).json()
    assert old["watermarked"] is False and old["revision_number"] == 1
    t = text(pdf_of(eng, pid, old["id"]))
    assert "DRAFT — NOT APPROVED FOR MANUFACTURING" not in t and "not a manufacturing authorisation" in t
    rows = eng.get(f"/api/v1/passports/{pid}/reports/").json()
    assert next(x for x in rows if x["id"] == old["id"])["superseded"] is True
