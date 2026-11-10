"""CN-005 enhancement: report templates (Standard, Aries Internal, Manufacturing & Test Specification), report builder
attachments in a chosen order pinned to exact versions, assembled-PDF preview, supporting-document classes, client
visibility and PDF upload validation. Synthetic PDFs only; PostgreSQL + RLS; real local rendering."""
import io

import pypdfium2 as pdfium
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.audit.models import AuditEvent
from apps.reports.models import PassportReport
from apps.tenancy.context import tenant_context

from .conftest import login
from .test_passport_reports import setup, text  # noqa: F401  (fixture)


def text_pdf(marker: str, pages: int = 1, landscape: bool = False) -> bytes:
    """A small valid PDF whose every page carries `marker` and its page number (synthetic test documents)."""
    w, h = (842, 595) if landscape else (595, 842)
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for i in range(pages):
        stream = f"BT /F1 18 Tf 72 {h - 100} Td ({marker} page {i + 1} of {pages}) Tj ET".encode()
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream.decode()}\nendstream")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {w} {h}] /Resources << /Font << /F1 3 0 R >> >> /Contents {len(objs)} 0 R >>")
        kids.append(len(objs))
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {pages} >>"
    out, offsets = io.BytesIO(), []
    out.write(b"%PDF-1.4\n")
    for n, body in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(f"{n} 0 obj\n{body}\nendobj\n".encode())
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def add_doc(client, part, name, marker, category, pages=1, visible=None, landscape=False):
    body = {"part": part, "category": category, "file": SimpleUploadedFile(name, text_pdf(marker, pages, landscape))}
    if visible is not None:
        body["client_visible"] = "true" if visible else "false"
    r = client.post("/api/v1/files/", body, format="multipart")
    assert r.status_code == 201, r.content
    return r.json()


def page_texts(pdf: bytes) -> list[str]:
    doc = pdfium.PdfDocument(pdf)
    return [doc[i].get_textpage().get_text_range() for i in range(len(doc))]


def test_mts_template_with_ordered_attachments_pinned_versions_and_preview(world, setup):
    eng = login(world["op_eng"], world["a"])
    pid, part = setup["passport"]["id"], setup["part"]["id"]
    dwg = add_doc(eng, part, "synthetic-drawing.pdf", "SYN-DRAWING", "drawing", landscape=True)
    qc = add_doc(eng, part, "synthetic-qc.pdf", "SYN-QC", "inspection", pages=2, landscape=True)
    lab = add_doc(eng, part, "synthetic-lab.pdf", "SYN-LAB-V1", "lab_test")
    # a newer version of the lab report exists, but the report pins version 1
    eng.post(f"/api/v1/files/{lab['id']}/versions/", {"file": SimpleUploadedFile("synthetic-lab.pdf", text_pdf("SYN-LAB-V2"))}, format="multipart")
    order = [{"file": dwg["id"]}, {"file": qc["id"]}, {"file": lab["id"], "version": 1}]
    pv = eng.post(f"/api/v1/passports/{pid}/reports/preview/", {"template": "mts", "attachments": order}, format="json")
    assert pv.status_code == 200 and pv["Content-Type"] == "application/pdf"
    with tenant_context(world["a"]):
        assert not PassportReport.objects.exists()  # preview stores nothing
        assert AuditEvent.objects.filter(action="passport_report.draft_previewed").exists()
    r = eng.post(f"/api/v1/passports/{pid}/reports/", {"template": "mts", "attachments": order}, format="json")
    assert r.status_code == 201, r.content
    rep = r.json()
    assert rep["template"] == "mts" and rep["variant"] == "internal" and rep["number"].endswith("-MTS")
    pdf = eng.get(f"/api/v1/passports/{pid}/reports/{rep['id']}/pdf/").content
    pages = page_texts(pdf)
    body = rep["page_count"] - 4
    assert len(pages) == rep["page_count"] == len(page_texts(pv.content))  # preview = generated document
    tail = pages[body:]
    assert "SYN-DRAWING page 1" in tail[0] and "SYN-QC page 1" in tail[1] and "SYN-QC page 2" in tail[2] and "SYN-LAB-V1" in tail[3]
    assert "SYN-LAB-V2" not in " ".join(pages)  # exact pinned version, not the latest
    head = " ".join(" ".join(pages[:body]).split())
    for s in ("Manufacturing & Test Specifications Report", "Manufacturing Specifications", "Manufacturing Process",
              "Inspection and Test Specifications", "CONFIDENTIAL", "NOT APPROVED FOR MANUFACTURING", "JOB-SECRET-77",
              "Substrate plate material", "Not recorded", "does not mean Aries has verified it", "ISO 6892-1"):
        assert s in head, s
    assert "SECRET-ENGINEERING-NOTE" not in " ".join(pages)  # engineering notes never printed
    # footer: centred "Page N" only (Project 1 sample); no report number, status line or "of N"
    assert all(f"Page {n}" in t for n, t in enumerate(pages[:body], 1))
    assert not any(f"of {rep['page_count']}" in t or "ARIES CONFIDENTIAL" in t for t in pages[:body])
    att = rep["attachments"]
    assert [a["order"] for a in att] == [1, 2, 3] and [a["file"] for a in att] == [dwg["id"], qc["id"], lab["id"]]
    assert att[2]["version"] == 1 and att[1]["pages"] == 2 and att[0]["first_page"] == body + 1 and att[2]["first_page"] == body + 4
    assert all(len(a["sha256"]) == 64 and a["version_id"] for a in att)
    with tenant_context(world["a"]):
        ev = AuditEvent.objects.filter(action="passport_report.generated").first()
        assert [x[0] for x in ev.data["attachments"]] == [1, 2, 3] and ev.data["template"] == "mts"
    # a different order and an excluded attachment
    r2 = eng.post(f"/api/v1/passports/{pid}/reports/", {"template": "internal", "attachments": [lab["id"], dwg["id"]]}, format="json").json()
    p2 = page_texts(eng.get(f"/api/v1/passports/{pid}/reports/{r2['id']}/pdf/").content)
    assert "SYN-LAB-V2" in p2[-2] and "SYN-DRAWING" in p2[-1] and not any("SYN-QC" in t for t in p2)
    assert eng.post(f"/api/v1/passports/{pid}/reports/", {"template": "mts", "attachments": [dwg["id"], dwg["id"]]},
                    format="json").json()["error"]["code"] == "duplicate_attachment"


def test_client_reports_never_receive_restricted_documents_or_internal_templates(world, setup):
    eng = login(world["op_eng"], world["a"])
    pid, part = setup["passport"]["id"], setup["part"]["id"]
    hidden = add_doc(eng, part, "hidden-cert.pdf", "SYN-HIDDEN-CERT", "mat_cert")  # Aries PDF: hidden by default
    released = add_doc(eng, part, "released-test.pdf", "SYN-RELEASED-TEST", "mech_test", visible=True)
    assert hidden["client_visible"] is False and released["client_visible"] is True
    client = login(world["a_admin"])
    ids = {f["id"] for f in client.get("/api/v1/files/", {"part": part}).json()["results"]}
    assert released["id"] in ids and hidden["id"] not in ids
    assert client.get(f"/api/v1/files/{hidden['id']}/").status_code == 404
    # neither Aries nor the client can put an unreleased document into a client-facing report (generate or preview)
    for who in (eng, client):
        for path in ("reports/", "reports/preview/"):
            r = who.post(f"/api/v1/passports/{pid}/{path}", {"template": "standard", "attachments": [hidden["id"]]}, format="json")
            assert r.status_code in (403, 400) and r.json()["error"]["code"] in ("attachment_not_permitted", "invalid_attachment"), r.content
    # clients cannot build Aries-internal templates, not even as a preview
    for template in ("mts", "internal"):
        assert client.post(f"/api/v1/passports/{pid}/reports/", {"template": template}, format="json").status_code == 403
        assert client.post(f"/api/v1/passports/{pid}/reports/preview/", {"template": template}, format="json").status_code == 403
    rep = client.post(f"/api/v1/passports/{pid}/reports/", {"template": "standard", "attachments": [released["id"]]}, format="json")
    assert rep.status_code == 201, rep.content
    pdf = client.get(f"/api/v1/passports/{pid}/reports/{rep.json()['id']}/pdf/").content
    t = " ".join(text(pdf).split())
    assert "SYN-RELEASED-TEST" in t and "hidden-cert" not in t and "SYN-HIDDEN-CERT" not in t
    for secret in ("JOB-SECRET-77", "EOS-SECRET-M290", "SECRET-SOLUTION", "Manufacturing specification (BR-026)", "SECRET-ENGINEERING-NOTE"):
        assert secret not in t, secret
    assert "does not mean Aries has verified it" in t
    mts = eng.post(f"/api/v1/passports/{pid}/reports/", {"template": "mts"}, format="json").json()
    assert mts["id"] not in {x["id"] for x in client.get(f"/api/v1/passports/{pid}/reports/").json()}
    assert client.get(f"/api/v1/passports/{pid}/reports/{mts['id']}/pdf/").status_code == 403
    # releasing is an explicit, audited Aries action; clients cannot change it
    assert client.patch(f"/api/v1/files/{released['id']}/", {"client_visible": False}, format="json").status_code == 403
    assert eng.patch(f"/api/v1/files/{hidden['id']}/", {"client_visible": True}, format="json").json()["client_visible"] is True
    with tenant_context(world["a"]):
        assert AuditEvent.objects.filter(action="engineering_file.client_visibility_changed").exists()


def test_upload_and_attachment_validation(world, setup, settings):
    eng = login(world["op_eng"], world["a"])
    part = setup["part"]["id"]

    def up(name, data, category="lab_test"):
        return eng.post("/api/v1/files/", {"part": part, "category": category, "file": SimpleUploadedFile(name, data)}, format="multipart")

    for cat in ("mat_cert", "mech_test", "chem_analysis", "lab_test", "inspection", "drawing", "other"):
        assert up(f"{cat}.pdf", text_pdf(cat), cat).status_code == 201, cat
    enc = text_pdf("X").replace(b"/Root 1 0 R", b"/Root 1 0 R /Encrypt << /Filter /Standard >>")
    assert up("enc.pdf", enc).json()["error"]["code"] == "pdf_encrypted"
    js = text_pdf("X").replace(b"<< /Type /Catalog", b"<< /OpenAction << /S /JavaScript /JS (app.alert(1)) >> /Type /Catalog")
    assert up("js.pdf", js).json()["error"]["code"] == "pdf_active_content"
    assert up("broken.pdf", b"%PDF-1.4\n garbage without any objects").json()["error"]["code"] == "pdf_unreadable"
    settings.PDF_MAX_PAGES = 2
    assert up("long.pdf", text_pdf("LONG", pages=3)).json()["error"]["code"] == "pdf_too_many_pages"
    settings.PDF_MAX_PAGES = 300
    ok = up("three.pdf", text_pdf("THREE", pages=3)).json()
    assert ok["latest_version"]["page_count"] == 3
    settings.REPORT_ATTACHMENT_MAX_PAGES = 2
    r = eng.post(f"/api/v1/passports/{setup['passport']['id']}/reports/", {"template": "mts", "attachments": [ok["id"]]}, format="json")
    assert r.status_code == 400 and r.json()["error"]["code"] == "attachment_too_long"
    with tenant_context(world["a"]):
        assert not PassportReport.objects.exists()  # a refused attachment never leaves a partial report
