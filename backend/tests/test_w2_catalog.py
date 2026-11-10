"""W2 catalog, dashboard and part photographs: behaviour and tenant isolation on PostgreSQL."""
import hashlib
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.files.models import Derivative, FileVersion
from apps.files.storage import get_storage
from apps.tenancy.context import tenant_context

from .conftest import login
from .test_files import DWG_BYTES, PDF_BYTES, STEP_BYTES, upload
from .test_w1_passport_workspace import RL2_FULL


def jpeg_with_gps() -> bytes:
    """A real JPEG carrying EXIF with a GPS block, to prove thumbnails drop metadata."""
    img = Image.new("RGB", (1200, 800), (120, 140, 160))
    exif = Image.Exif()
    exif[0x010F] = "TestCam"  # Make
    exif[0x8825] = {1: "N", 2: (51.0, 30.0, 0.0)}  # GPSInfo
    out = io.BytesIO()
    img.save(out, format="JPEG", exif=exif)
    return out.getvalue()


def png_bytes() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 10, 10)).save(out, format="PNG")
    return out.getvalue()


def results(c, **params):
    r = c.get("/api/v1/parts/", params)
    assert r.status_code == 200, r.content
    return r.json()["results"]


@pytest.fixture
def catalog(world):
    eng = login(world["op_eng"], world["a"])
    project = eng.post("/api/v1/projects/", {"code": "PRJ-1", "name": "Cooling upgrade"}, format="json").json()
    a = eng.post("/api/v1/parts/", {"part_number": "AAA-100", "name": "Impeller holder", "description": "stainless holder", "project": project["id"]}, format="json").json()
    b = eng.post("/api/v1/parts/", {"part_number": "BBB-200", "name": "Valve seat", "category": "electrical"}, format="json").json()
    c = eng.post("/api/v1/parts/", {"part_number": "CCC-300", "name": "Bracket"}, format="json").json()
    pa = eng.post("/api/v1/passports/", {"part": a["id"]}, format="json").json()
    pb = eng.post("/api/v1/passports/", {"part": b["id"]}, format="json").json()
    return {"eng": eng, "project": project, "a": a, "b": b, "c": c, "pa": pa, "pb": pb}


def test_search_covers_part_number_name_description_and_passport_number(catalog):
    eng = catalog["eng"]
    assert [p["part_number"] for p in results(eng, search="BBB")] == ["BBB-200"]
    assert [p["part_number"] for p in results(eng, search="stainless")] == ["AAA-100"]
    assert [p["part_number"] for p in results(eng, search=catalog["pa"]["passport_number"])] == ["AAA-100"]


def test_filters_project_category_passport_and_data_level(catalog):
    eng, pa = catalog["eng"], catalog["pa"]
    assert [p["part_number"] for p in results(eng, project=catalog["project"]["id"])] == ["AAA-100"]
    assert [p["part_number"] for p in results(eng, category="electrical")] == ["BBB-200"]
    assert [p["part_number"] for p in results(eng, has_passport="false")] == ["CCC-300"]
    # complete R-L1 and R-L2 on passport A: data level filters follow, official evidence level does not move
    rl1 = {"cad_3d_available": True, "drawings_2d_available": True, "original_material_grade": "316", "material_identification_method": "pmi",
           "technical_description": "x", "part_size": "Ø45", "application": "pump", "atmosphere": "corrosive", "motion": "static", "ip_status": "active"}
    eng.patch(f"/api/v1/passports/{pa['id']}/revisions/1/", {"content": {"rl1": rl1, "rl2": RL2_FULL}}, format="json")
    assert [p["part_number"] for p in results(eng, data_level="rl2")] == ["AAA-100"]
    assert [p["part_number"] for p in results(eng, data_level="rl1")] == ["AAA-100"]
    assert results(eng, data_level="rl3") == []
    assert {p["part_number"] for p in results(eng, data_level="none")} == {"BBB-200", "CCC-300"}
    row = results(eng, search="AAA")[0]
    assert row["data_captured"] == "rl2" and row["evidence_level"] == "none" and row["revision"] == {"number": 1, "status": "draft"}
    assert {p["part_number"] for p in results(eng, evidence_level="none")} == {"AAA-100", "BBB-200"}


def test_sorting_and_last_activity(catalog):
    eng = catalog["eng"]
    assert [p["part_number"] for p in results(eng, ordering="part_number")] == ["AAA-100", "BBB-200", "CCC-300"]
    assert [p["part_number"] for p in results(eng, ordering="-part_number")] == ["CCC-300", "BBB-200", "AAA-100"]
    upload(eng, catalog["b"]["id"], "spec.pdf", PDF_BYTES)  # activity on B makes it the most recent
    assert results(eng)[0]["part_number"] == "BBB-200"
    assert results(eng, ordering="bogus")[0]["part_number"] == "BBB-200"  # unknown ordering falls back safely


def test_document_summary_and_3d_flag(world, catalog):
    eng, a = catalog["eng"], catalog["a"]
    for name, data in (("p.stp", STEP_BYTES), ("d.dwg", DWG_BYTES), ("s.pdf", PDF_BYTES)):
        upload(eng, a["id"], name, data, passport=catalog["pa"]["id"])
    row = results(eng, search="AAA")[0]
    assert row["documents"] == {"total": 3, "step": 1, "dwg": 1, "pdf": 1, "image": 0} and row["has_3d"] is False
    with tenant_context(world["a"]):  # simulate a finished conversion
        fv = FileVersion.objects.get(file__part_id=a["id"], file__kind="step")
        Derivative.objects.create(tenant=world["a"], file_version=fv, kind="glb", storage_key=f"tenants/{world['a'].pk}/derivatives/x/v1/derivative.glb",
                                  size_bytes=1, sha256="0" * 64, generator="test")
    assert [p["part_number"] for p in results(eng, has_3d="true")] == ["AAA-100"]
    # file-revision association
    assert eng.get("/api/v1/files/", {"part": a["id"], "kind": "pdf"}).json()["results"][0]["latest_version"]["passport_revision_number"] == 1


def test_photo_upload_keeps_original_and_makes_metadata_free_thumbnail(world, catalog, client):
    eng, a = catalog["eng"], catalog["a"]
    data = jpeg_with_gps()
    f = upload(eng, a["id"], "holder.jpg", data, category="photo").json()
    v = f["latest_version"]
    assert f["kind"] == "image" and v["detected_format"] == "JPEG image" and v["sha256"] == hashlib.sha256(data).hexdigest()
    with tenant_context(world["a"]):
        fv = FileVersion.objects.get(pk=v["id"])
        thumb = Derivative.objects.get(file_version=fv, kind="thumb")
    with get_storage().open(fv.storage_key) as fh:
        assert fh.read() == data  # original preserved
    t = eng.get(f"/api/v1/files/{f['id']}/versions/1/thumbnail/")
    assert t.status_code == 200 and t["Content-Type"] == "image/jpeg" and t["X-Content-Type-Options"] == "nosniff"
    body = b"".join(t.streaming_content)
    with Image.open(io.BytesIO(body)) as img:
        assert max(img.size) <= 480 and not img.getexif()  # small and metadata-free
    assert thumb.sha256 == hashlib.sha256(body).hexdigest()
    row = results(eng, search="AAA")[0]
    assert row["thumbnail"] == {"file": f["id"], "version": 1} and row["documents"]["image"] == 1
    # inline preview of the full photo, single use
    link = eng.post(f"/api/v1/files/{f['id']}/versions/1/download-link/", {"variant": "preview"}, format="json").json()["url"]
    r = client.get(link.replace("http://testserver", ""))
    assert r.status_code == 200 and r["Content-Type"] == "image/jpeg" and r["Content-Disposition"].startswith("inline")
    # another organisation can see none of it
    b = login(world["b_admin"])
    assert b.get(f"/api/v1/files/{f['id']}/versions/1/thumbnail/").status_code == 404


@pytest.mark.parametrize("name,data,code", [
    ("fake.jpg", b"\xff\xd8\xff" + b"not really a jpeg" * 20, "content_mismatch"),
    ("fake.png", PDF_BYTES, "content_mismatch"),
    ("anim.gif", b"GIF89a" + b"\x00" * 50, "unsupported_file_type"),
    ("vector.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>", "unsupported_file_type"),
], ids=["corrupt-jpeg", "pdf-as-png", "gif", "svg"])
def test_photo_validation(catalog, name, data, code):
    r = upload(catalog["eng"], catalog["a"]["id"], name, data)
    assert r.status_code == 400 and r.json()["error"]["code"] == code


def test_photo_pixel_limit_is_enforced_below_pillows_own_threshold(catalog, settings):
    # 64 x 64 = 4096 px is only 1.4x this limit: Pillow alone would merely warn (it refuses above 2x).
    settings.MAX_IMAGE_PIXELS = 3000
    r = upload(catalog["eng"], catalog["a"]["id"], "big.png", png_bytes())
    assert r.status_code == 400 and r.json()["error"]["code"] == "image_too_large"
    assert r.json()["error"]["details"] == {"width": 64, "height": 64, "limit_pixels": 3000}


def test_photo_size_limit_in_bytes(catalog, settings):
    settings.MAX_UPLOAD_BYTES = {**settings.MAX_UPLOAD_BYTES, "image": 100}
    r = upload(catalog["eng"], catalog["a"]["id"], "holder.jpg", jpeg_with_gps())
    assert r.status_code == 400 and r.json()["error"]["code"] == "file_too_large"


def test_truncated_image_is_rejected(catalog):
    data = jpeg_with_gps()
    r = upload(catalog["eng"], catalog["a"]["id"], "cut.jpg", data[: len(data) // 2])
    assert r.status_code == 400 and r.json()["error"]["code"] == "content_mismatch"


def test_png_photo_supported(catalog):
    r = upload(catalog["eng"], catalog["a"]["id"], "side.png", png_bytes())
    assert r.status_code == 201 and r.json()["latest_version"]["detected_format"] == "PNG image"


def test_catalog_and_dashboard_do_not_disclose_other_tenants(world, catalog):
    upload(catalog["eng"], catalog["a"]["id"], "s.pdf", PDF_BYTES)
    b = login(world["b_admin"])
    for params in ({}, {"search": "AAA"}, {"search": catalog["pa"]["passport_number"]}, {"project": catalog["project"]["id"]},
                   {"data_level": "none"}, {"has_passport": "true"}, {"ordering": "-last_activity"}):
        assert results(b, **params) == [], params
    s = b.get("/api/v1/dashboard/summary/").json()
    assert s["parts"]["total"] == 0 and s["passports"]["total"] == 0 and s["documents"]["total"] == 0 and s["recent_parts"] == []


def test_dashboard_summary_counts(world, catalog):
    eng = catalog["eng"]
    upload(eng, catalog["a"]["id"], "p.stp", STEP_BYTES, passport=catalog["pa"]["id"], category="3d_model")
    upload(eng, catalog["a"]["id"], "d.dwg", DWG_BYTES, category="drawing")
    upload(eng, catalog["b"]["id"], "s.pdf", PDF_BYTES, category="specification")
    s = login(world["a_user"]).get("/api/v1/dashboard/summary/").json()  # client users can see the summary
    assert s["parts"] == {"total": 3, "with_passport": 2, "by_category": {"mechanical": 2, "electrical": 1, "electronic": 0, "other": 0}}
    assert s["passports"]["total"] == 2 and s["passports"]["open_drafts"] == 2
    assert s["passports"]["by_evidence_level"]["none"] == 2 and s["passports"]["by_data_captured"]["none"] == 2
    assert s["documents"]["by_kind"]["step"] == 1 and s["documents"]["parts_with_drawing"] == 1 and s["documents"]["parts_with_specification"] == 1
    assert s["documents"]["parts_without_documents"] == 1
    assert s["conversions"]["queued"] == 1 and s["conversions"]["failed_items"] == []
    assert [p["part_number"] for p in s["recent_parts"]][0] in {"AAA-100", "BBB-200"}
    assert "orders" not in s and "manufacturing" not in str(sorted(s))  # no fabricated production statistics
