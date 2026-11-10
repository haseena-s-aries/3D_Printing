"""Engineering file management: validation, preservation, integrity, isolation and downloads.

Fixtures are synthetic: the STEP is OCCT-generated (Phase 0), the DWG has a valid header only
(no real DWG supplied yet, blocker B-01), the PDF is a minimal valid PDF.
"""
import hashlib
from pathlib import Path

import pytest
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.files.models import Derivative, FileVersion
from apps.files.storage import LocalStorage, ObjectExists, StorageError, get_storage
from apps.jobs.models import Job
from apps.jobs.queue import run_one
from apps.tenancy.context import tenant_context

from .conftest import login

FIX = Path(__file__).parent / "fixtures"
STEP_BYTES = (FIX / "sleeve_d45_h40_5_synthetic.stp").read_bytes()
PDF_BYTES = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj "
             b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")
DWG_BYTES = b"AC1032" + b"\x00" * 2042  # header-only synthetic DWG (validation test, not a drawing)


def upload(client, part_id, name, data, **extra):
    f = SimpleUploadedFile(name, data, content_type="application/octet-stream")
    extra.setdefault("client_visible", "true")  # released to the client (CN-005: Aries PDFs are hidden by default)
    return client.post("/api/v1/files/", {"part": part_id, "file": f, **extra}, format="multipart")


@pytest.fixture
def setup(world):
    c = login(world["op_eng"], world["a"])
    part = c.post("/api/v1/parts/", {"part_number": "SLEEVE-45", "name": "Distance sleeve"}, format="json").json()
    return c, part


@pytest.mark.parametrize("name,data,kind,fmt", [
    ("sleeve.stp", STEP_BYTES, "step", "STEP (ISO-10303-21)"),
    ("sleeve.STEP", STEP_BYTES, "step", "STEP (ISO-10303-21)"),
    ("drawing.dwg", DWG_BYTES, "dwg", "DWG AC1032"),
    ("spec.pdf", PDF_BYTES, "pdf", "PDF 1.4"),
], ids=["stp", "STEP-uppercase", "dwg", "pdf"])
def test_upload_preserves_original_with_checksum(world, setup, name, data, kind, fmt):
    c, part = setup
    r = upload(c, part["id"], name, data, category="drawing", title=f"{kind} file")
    assert r.status_code == 201, r.content
    body = r.json()
    v = body["latest_version"]
    assert body["kind"] == kind and v["version_number"] == 1 and v["detected_format"] == fmt
    assert v["sha256"] == hashlib.sha256(data).hexdigest() and v["size_bytes"] == len(data)
    with tenant_context(world["a"]):
        fv = FileVersion.objects.get(pk=v["id"])
    assert fv.storage_key.startswith(f"tenants/{world['a'].pk}/originals/")
    with get_storage().open(fv.storage_key) as fh:
        assert fh.read() == data  # byte-for-byte original preserved
    if kind == "dwg":
        assert v["conversion"]["status"] == "not_available" and "OQ-27" in v["conversion"]["reason"]
    if kind == "step":
        assert v["conversion"]["status"] == "queued"


@pytest.mark.parametrize("name,data,code", [
    ("malware.exe", b"MZ....", "unsupported_file_type"),
    ("notes.txt", b"hello", "unsupported_file_type"),
    ("fake.stp", PDF_BYTES, "content_mismatch"),
    ("fake.pdf", STEP_BYTES, "content_mismatch"),
    ("fake.dwg", b"AC9999" + b"\x00" * 100, "content_mismatch"),
    ("empty.pdf", b"", "empty_file"),
], ids=["exe", "txt", "pdf-as-stp", "stp-as-pdf", "bad-dwg-version", "empty"])
def test_upload_validation_errors(world, setup, name, data, code):
    c, part = setup
    r = upload(c, part["id"], name, data)
    assert r.status_code == 400, r.content
    assert r.json()["error"]["code"] == code
    with tenant_context(world["a"]):
        assert not FileVersion.objects.exists()


def test_size_limit_enforced(world, setup, settings):
    settings.MAX_UPLOAD_BYTES = {**settings.MAX_UPLOAD_BYTES, "pdf": 100}
    c, part = setup
    r = upload(c, part["id"], "big.pdf", PDF_BYTES)
    assert r.status_code == 400 and r.json()["error"]["code"] == "file_too_large"


def test_declared_kind_must_match_extension(world, setup):
    c, part = setup
    r = upload(c, part["id"], "spec.pdf", PDF_BYTES, kind="step")
    assert r.status_code == 400 and r.json()["error"]["code"] == "kind_mismatch"


def test_new_version_keeps_previous_original(world, setup):
    c, part = setup
    f = upload(c, part["id"], "spec.pdf", PDF_BYTES).json()
    v2 = PDF_BYTES.replace(b"200 200", b"300 300")
    r = c.post(f"/api/v1/files/{f['id']}/versions/", {"file": SimpleUploadedFile("spec-v2.pdf", v2)}, format="multipart")
    assert r.status_code == 201 and r.json()["version_number"] == 2
    versions = c.get(f"/api/v1/files/{f['id']}/versions/").json()
    assert [v["version_number"] for v in versions] == [2, 1]
    assert versions[1]["sha256"] == hashlib.sha256(PDF_BYTES).hexdigest()
    with tenant_context(world["a"]):
        keys = list(FileVersion.objects.order_by("version_number").values_list("storage_key", flat=True))
    assert keys[0] != keys[1]
    with get_storage().open(keys[0]) as fh:
        assert fh.read() == PDF_BYTES


def download(client_obj, file_id, variant="original", version=1):
    return client_obj.post(f"/api/v1/files/{file_id}/versions/{version}/download-link/", {"variant": variant}, format="json")


def test_authorised_download_of_original(world, setup, client):
    c, part = setup
    f = upload(c, part["id"], "spec.pdf", PDF_BYTES).json()
    a_admin = login(world["a_admin"])
    link = download(a_admin, f["id"])
    assert link.status_code == 200, link.content
    r = client.get(link.json()["url"].replace("http://testserver", ""))
    assert r.status_code == 200
    assert b"".join(r.streaming_content) == PDF_BYTES
    assert r["X-Content-SHA256"] == hashlib.sha256(PDF_BYTES).hexdigest()
    assert r["Cache-Control"] == "no-store"
    actions = {e["action"] for e in a_admin.get("/api/v1/audit-events/").json()["results"]}
    assert {"file.download_link_issued", "file.downloaded", "file.version_uploaded"} <= actions


def test_role_without_original_rights_refused(world, setup):
    c, part = setup
    f = upload(c, part["id"], "spec.pdf", PDF_BYTES).json()
    for who in ("a_user", "a_proc"):
        r = download(login(world[who]), f["id"])
        assert r.status_code == 403
    r = download(login(world["a_user"]), f["id"], variant="glb")
    assert r.status_code == 404 and r.json()["error"]["code"] == "derivative_not_available"


def test_other_tenant_cannot_see_or_download(world, setup, client):
    c, part = setup
    f = upload(c, part["id"], "spec.pdf", PDF_BYTES).json()
    b_admin = login(world["b_admin"])
    assert b_admin.get(f"/api/v1/files/{f['id']}/").status_code == 404
    assert b_admin.get("/api/v1/files/").json()["results"] == []
    assert download(b_admin, f["id"]).status_code == 404
    assert b_admin.post(f"/api/v1/files/{f['id']}/versions/", {"file": SimpleUploadedFile("x.pdf", PDF_BYTES)}, format="multipart").status_code == 404


def test_link_rejected_when_forged_expired_or_revoked(world, setup, client, settings):
    c, part = setup
    f = upload(c, part["id"], "spec.pdf", PDF_BYTES).json()
    url = download(login(world["a_admin"]), f["id"]).json()["url"].replace("http://testserver", "")
    token = url.rstrip("/").rsplit("/", 1)[1]
    forged = url.replace(token, token[:-3] + ("xyz" if not token.endswith("xyz") else "abc"))
    assert client.get(forged).json()["error"]["code"] == "link_invalid"
    settings.DOWNLOAD_LINK_SECONDS = -1
    assert client.get(url).status_code == 410
    settings.DOWNLOAD_LINK_SECONDS = 300
    from apps.tenancy.models import Membership

    Membership.objects.filter(user=world["a_admin"], tenant=world["a"]).update(is_active=False)
    assert client.get(url).status_code == 403


def test_local_storage_is_write_once_and_contained(tmp_path):
    s = LocalStorage(tmp_path)
    key = "tenants/00000000-0000-0000-0000-000000000001/originals/f/v1/original.pdf"
    assert s.save_new(key, [b"abc"]) == (3, hashlib.sha256(b"abc").hexdigest())
    with pytest.raises(ObjectExists):
        s.save_new(key, [b"other"])
    with s.open(key) as fh:
        assert fh.read() == b"abc"
    for bad in ("../etc/passwd", "tenants/not-a-uuid/x/y", "tenants/00000000-0000-0000-0000-000000000001/../../x/y"):
        with pytest.raises((StorageError, ValueError)):
            s.save_new(bad, [b"x"])


def test_worker_reports_missing_cad_dependency(world, setup, monkeypatch, settings):
    settings.WORKER_DB_ROLE = "app_worker"
    c, part = setup
    upload(c, part["id"], "sleeve.stp", STEP_BYTES)
    import builtins

    real_import = builtins.__import__

    def no_occt(name, *args, **kwargs):
        if name.endswith("cad_pipeline") or (args and len(args) > 2 and args[2] and "cad_pipeline" in args[2]):
            raise ImportError("OCP not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_occt)
    assert run_one() == "failed"
    with tenant_context(world["a"]):
        job = Job.objects.get()
    assert job.error_code == "worker_dependency_missing"


@pytest.mark.cad
def test_step_converted_to_glb_and_access_controlled(world, setup, client, settings):
    pytest.importorskip("OCP")
    settings.WORKER_DB_ROLE = "app_worker"  # claim as the worker role (cross-tenant queue policy)
    c, part = setup
    f = upload(c, part["id"], "sleeve.stp", STEP_BYTES, category="3d_model").json()
    assert run_one() == "succeeded"
    assert run_one() is None  # queue empty
    v = c.get(f"/api/v1/files/{f['id']}/versions/").json()[0]
    assert v["conversion"]["status"] == "succeeded"
    glb = v["derivatives"][0]
    assert glb["kind"] == "glb" and glb["size_bytes"] > 1000
    with tenant_context(world["a"]):
        d = Derivative.objects.get()
        assert d.storage_key.startswith(f"tenants/{world['a'].pk}/derivatives/")
        assert d.details["bbox_mm"][3] - d.details["bbox_mm"][0] == pytest.approx(45.0, abs=0.06)
    with get_storage().open(d.storage_key) as fh:
        assert fh.read(4) == b"glTF"
    # client user may view the derivative but not the original
    a_user = login(world["a_user"])
    link = download(a_user, f["id"], variant="glb")
    assert link.status_code == 200
    body = b"".join(client.get(link.json()["url"].replace("http://testserver", "")).streaming_content)
    assert body[:4] == b"glTF" and hashlib.sha256(body).hexdigest() == glb["sha256"]
    assert download(a_user, f["id"]).status_code == 403
    # other tenant: no access to the derivative either
    assert download(login(world["b_admin"]), f["id"], variant="glb").status_code == 404
