"""Post-UAT Phase 3 (D-02, D-09): Aries documents (STEP, PDF, scans) never become client-visible automatically; an Aries
Engineer releases one exact version and can withdraw it, audited; clients see and open only the released version, and a
withdrawal also revokes download links issued before it. 3D scan data is accepted by content signature, stored as uploaded and
never converted or treated as CAD."""
import struct
from urllib.parse import urlsplit

from django.core.files.uploadedfile import SimpleUploadedFile

from apps.audit.models import AuditEvent
from apps.jobs.models import Job
from apps.tenancy.context import tenant_context

from .conftest import login
from .test_passport_reports import STEP, valid_pdf


def binary_stl(triangles=2) -> bytes:
    return b"SYNTHETIC STL".ljust(80, b" ") + struct.pack("<I", triangles) + b"\x00" * (50 * triangles)


def _part(world):
    eng = login(world["op_eng"], world["a"])
    part = eng.post("/api/v1/parts/", {"part_number": "DOC-1", "name": "Sleeve"}, format="json").json()
    return eng, part


def test_release_is_version_specific_and_withdrawal_revokes_links(world):
    eng, part = _part(world)
    client = login(world["a_admin"])
    f = eng.post("/api/v1/files/", {"part": part["id"], "category": "3d_model", "file": SimpleUploadedFile("m.stp", STEP)},
                 format="multipart").json()
    assert f["client_visible"] is False and f["released_version"] is None  # never visible automatically
    assert client.get(f"/api/v1/files/?part={part['id']}").json()["results"] == []
    r = eng.patch(f"/api/v1/files/{f['id']}/", {"client_visible": True}, format="json").json()
    assert r["client_visible"] is True and r["released_version"] == 1
    eng.post(f"/api/v1/files/{f['id']}/versions/", {"file": SimpleUploadedFile("m2.stp", STEP)}, format="multipart")
    mine = client.get(f"/api/v1/files/{f['id']}/").json()
    assert mine["latest_version"]["version_number"] == 1 and mine["version_count"] == 1  # v2 stays Aries-only
    assert [v["version_number"] for v in client.get(f"/api/v1/files/{f['id']}/versions/").json()] == [1]
    assert client.post(f"/api/v1/files/{f['id']}/versions/2/download-link/", {"variant": "original"}, format="json").status_code == 404
    assert eng.get(f"/api/v1/files/{f['id']}/").json()["latest_version"]["version_number"] == 2
    assert eng.patch(f"/api/v1/files/{f['id']}/", {"released_version": 9}, format="json").status_code == 400
    assert eng.patch(f"/api/v1/files/{f['id']}/", {"released_version": 2}, format="json").json()["released_version"] == 2
    link = client.post(f"/api/v1/files/{f['id']}/versions/2/download-link/", {"variant": "original"}, format="json")
    assert link.status_code == 200
    assert client.post(f"/api/v1/files/{f['id']}/versions/1/download-link/", {"variant": "original"}, format="json").status_code == 404
    w = eng.patch(f"/api/v1/files/{f['id']}/", {"client_visible": False}, format="json").json()
    assert w["client_visible"] is False and w["released_version"] is None
    path = urlsplit(link.json()["url"]).path  # links use WEB_BASE_URL; only the path matters to the test client
    redeemed = client.get(path)  # issued before the withdrawal
    assert redeemed.status_code == 403 and redeemed.json()["error"]["code"] == "link_invalid"
    assert client.get(f"/api/v1/files/?part={part['id']}").json()["results"] == []
    with tenant_context(world["a"]):
        actions = list(AuditEvent.objects.filter(object_id=f["id"]).values_list("action", flat=True))
    assert actions.count("engineering_file.client_visibility_changed") == 2 and "engineering_file.version_released" in actions


def test_client_report_attaches_only_the_released_version(world):
    eng, part = _part(world)
    pp = eng.post("/api/v1/passports/", {"part": part["id"]}, format="json").json()
    f = eng.post("/api/v1/files/", {"part": part["id"], "category": "drawing", "client_visible": "true",
                                    "file": SimpleUploadedFile("d.pdf", valid_pdf())}, format="multipart").json()
    eng.post(f"/api/v1/files/{f['id']}/versions/", {"file": SimpleUploadedFile("d2.pdf", valid_pdf(2))}, format="multipart")
    client = login(world["a_admin"])
    body = {"template": "standard", "attachments": [{"file": f["id"], "version": 2}]}
    r = client.post(f"/api/v1/passports/{pp['id']}/reports/preview/", body, format="json")
    assert r.status_code == 403 and r.json()["error"]["code"] == "attachment_version_not_released"


def test_scan_data_is_stored_as_uploaded_and_never_converted(world):
    eng, part = _part(world)
    ok = eng.post("/api/v1/files/", {"part": part["id"], "category": "scan_source", "file": SimpleUploadedFile("impeller.stl", binary_stl())},
                  format="multipart")
    assert ok.status_code == 201, ok.content
    body = ok.json()
    assert body["kind"] == "scan" and body["latest_version"]["detected_format"] == "STL mesh (binary)" and body["client_visible"] is False
    ply = eng.post("/api/v1/files/", {"part": part["id"], "category": "scan_source",
                                      "file": SimpleUploadedFile("cloud.ply", b"ply\nformat ascii 1.0\nelement vertex 1\nend_header\n0 0 0\n")},
                   format="multipart")
    assert ply.status_code == 201 and ply.json()["latest_version"]["detected_format"].startswith("PLY")
    xyz = eng.post("/api/v1/files/", {"part": part["id"], "category": "scan_source",
                                      "file": SimpleUploadedFile("cloud.xyz", b"x y z\n1.0 2.0 3.0\n1.5 2.5 3.5\n")}, format="multipart")
    assert xyz.status_code == 201
    broken = eng.post("/api/v1/files/", {"part": part["id"], "file": SimpleUploadedFile("bad.stl", binary_stl()[:-10])}, format="multipart")
    assert broken.status_code == 400 and broken.json()["error"]["code"] == "content_mismatch"
    fake = eng.post("/api/v1/files/", {"part": part["id"], "file": SimpleUploadedFile("evil.stl", b"<script>alert(1)</script>")},
                    format="multipart")
    assert fake.status_code == 400
    with tenant_context(world["a"]):
        assert not Job.objects.filter(payload__file=body["id"]).exists()  # no CAD conversion for scan data
    client = login(world["a_admin"])
    r = client.post("/api/v1/files/", {"part": part["id"], "file": SimpleUploadedFile("mine.stl", binary_stl())}, format="multipart")
    assert r.status_code in (403, 404)  # clients add supporting documents and photographs only


def test_client_submits_cad_with_an_open_submission_only(world, settings):
    """Post-UAT D-14: a client that has CAD attaches STEP/DWG to its spare-part submission while Aries reviews it."""
    from apps.parts.models import SparePart

    settings.CLIENT_PART_SUBMISSIONS_ENABLED = True
    with tenant_context(world["a"]):
        pending = SparePart.objects.create(tenant=world["a"], part_number="CL-1", name="Bush", origin="client", review_state="pending_review",
                                           submission_kind="record", submitted_by=world["a_admin"])
        accepted = SparePart.objects.create(tenant=world["a"], part_number="CL-2", name="Bush", origin="client", review_state="accepted",
                                            submission_kind="record", submitted_by=world["a_admin"])
    client = login(world["a_admin"])
    r = client.post("/api/v1/files/", {"part": str(pending.pk), "file": SimpleUploadedFile("mine.stp", STEP)}, format="multipart")
    assert r.status_code == 201, r.content
    assert r.json()["kind"] == "step" and r.json()["category"] == "3d_model"
    assert client.get(f"/api/v1/files/{r.json()['id']}/").status_code == 200  # the client sees its own submitted CAD
    late = client.post("/api/v1/files/", {"part": str(accepted.pk), "file": SimpleUploadedFile("late.stp", STEP)}, format="multipart")
    assert late.status_code == 403 and late.json()["error"]["code"] == "supporting_documents_only"
