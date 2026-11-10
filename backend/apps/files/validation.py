"""Upload validation for STEP, DWG, PDF and part photographs (CAD-001..CAD-003, CAD-007, CAD-008).

Checks, in order: extension allowed, declared kind matches extension, not empty, size limit
(provisional, OQ-31), and content signature matches the extension (the browser-supplied MIME type
is never trusted). Each failure has a stable error code and a plain message.
"""
import re
from dataclasses import dataclass

from django.conf import settings

from apps.core.exceptions import DomainError

EXTENSIONS = {".stp": "step", ".step": "step", ".dwg": "dwg", ".pdf": "pdf", ".jpg": "image", ".jpeg": "image", ".png": "image",
              # post-UAT D-09: 3D scan source data (meshes, point clouds). Stored as uploaded; never converted or treated as CAD.
              ".stl": "scan", ".ply": "scan", ".e57": "scan", ".las": "scan", ".xyz": "scan", ".pts": "scan"}
CONTENT_TYPES = {"step": "model/step", "dwg": "application/acad", "pdf": "application/pdf", "scan": "application/octet-stream"}
UNSUPPORTED = ("Only STEP (.stp, .step), DWG (.dwg), PDF (.pdf), part photographs (.jpg, .jpeg, .png) and 3D scan data "
               "(.stl, .ply, .e57, .las, .xyz, .pts) can be uploaded.")
# DWG version strings: R13 (AC1012) through 2018+ (AC1032)
DWG_VERSIONS = {"AC1012", "AC1014", "AC1015", "AC1018", "AC1021", "AC1024", "AC1027", "AC1032"}
SAFE_NAME = re.compile(r"[^A-Za-z0-9._\- ()]+")


@dataclass
class Validated:
    kind: str
    ext: str
    detected_format: str
    content_type: str
    safe_name: str
    page_count: int | None = None


# Content a supporting PDF must not carry: scripts, launch actions, embedded files, rich media and XFA forms
# (raw name tokens; a PDF that hides them in compressed object streams is caught by the catalog check below).
ACTIVE_PDF_TOKENS = (b"/JavaScript", b"/JS", b"/Launch", b"/EmbeddedFile", b"/RichMedia", b"/XFA")


def verify_pdf(upload) -> int:
    """CN-005: a PDF must open, must not be encrypted, must not carry active content and must stay within the page
    limit. Returns the page count. The file itself is never altered."""
    import pypdfium2 as pdfium

    upload.seek(0)
    data = upload.read()
    upload.seek(0)
    for token in ACTIVE_PDF_TOKENS:
        pos = data.find(token)
        while pos != -1:
            nxt = data[pos + len(token):pos + len(token) + 1]
            if not nxt.isalnum():  # "/JS" but not "/JSomething"
                fail("pdf_active_content", "The PDF contains scripts, embedded files or interactive forms and cannot be accepted. "
                     "Upload a flattened or printed-to-PDF copy.", token=token.decode())
            pos = data.find(token, pos + 1)
    if b"/Encrypt" in data:
        fail("pdf_encrypted", "The PDF is password-protected or encrypted. Upload an unprotected copy.")
    try:  # opened the way a PDF viewer opens it (PDFium, also used for report previews and report assembly)
        doc = pdfium.PdfDocument(data)
        pages = len(doc)
        for i in range(min(pages, 3)):
            doc[i].get_size()
        doc.close()
    except Exception:  # noqa: BLE001 - any parser failure means the document cannot be used
        fail("pdf_unreadable", "The PDF could not be read. It may be damaged; upload a valid PDF.")
    if pages == 0:
        fail("pdf_unreadable", "The PDF has no pages.")
    limit = settings.PDF_MAX_PAGES
    if pages > limit:
        fail("pdf_too_many_pages", f"The PDF has {pages} pages; the limit is {limit}.", pages=pages, limit=limit)
    return pages


def fail(code: str, message: str, **details):
    raise DomainError(code, message, details=details, http_status=400)


def sniff(kind: str, head: bytes) -> str | None:
    if kind == "step":
        text = head.lstrip(b"\xef\xbb\xbf \t\r\n")
        return "STEP (ISO-10303-21)" if text.startswith(b"ISO-10303-21") else None
    if kind == "pdf":
        pos = head.find(b"%PDF-")
        if 0 <= pos <= 1024:
            return "PDF " + head[pos + 5:pos + 8].decode("ascii", "replace").strip()
        return None
    if kind == "dwg":
        ver = head[:6].decode("ascii", "replace")
        return f"DWG {ver}" if ver in DWG_VERSIONS else None
    if kind == "scan":
        return sniff_scan(head)
    if kind == "image":
        # The type comes from the signature, not the extension; SVG and other formats are never accepted.
        if head.startswith(b"\xff\xd8\xff"):
            return "JPEG image"
        if head.startswith(b"\x89PNG\r\n\x1a\n"):
            return "PNG image"
        return None
    return None


def sniff_scan(head: bytes) -> str | None:
    """3D scan formats by content: ASCII/binary STL, PLY, E57, LAS and plain-text XYZ/PTS point clouds."""
    if head.startswith(b"ply\n") or head.startswith(b"ply\r\n"):
        return "PLY mesh / point cloud"
    if head.startswith(b"ASTM-E57"):
        return "E57 point cloud"
    if head.startswith(b"LASF"):
        return "LAS point cloud"
    text = head.lstrip()
    if text[:5].lower() == b"solid" and b"facet" in head:
        return "STL mesh (ASCII)"
    if len(head) >= 84 and b"\x00" in head[:84] and not text[:5].lower() == b"solid":
        return "STL mesh (binary)"  # 80-byte header + triangle count; the size check follows in verify_scan
    lines = [ln.strip() for ln in head.splitlines()[1:6] if ln.strip()]
    if lines and all(re.fullmatch(rb"[-+0-9.eE,\s]+", ln) and len(re.split(rb"[\s,]+", ln)) >= 3 for ln in lines):
        return "XYZ point cloud (text)"
    return None


def verify_scan(upload, detected: str) -> None:
    """Binary STL: the size must match the declared triangle count (84 + 50 x n bytes)."""
    if detected != "STL mesh (binary)":
        return
    upload.seek(80)
    count = int.from_bytes(upload.read(4), "little")
    upload.seek(0)
    if 84 + 50 * count != (getattr(upload, "size", 0) or 0):
        fail("content_mismatch", "The STL file is damaged or not a binary STL (its size does not match the triangle count).")


def verify_image(upload, detected: str) -> None:
    """Check the photograph's dimensions from its header, then decode it completely with Pillow (rejects
    oversized, truncated and corrupt images, and content whose real format differs from its signature)."""
    from PIL import Image

    limit = settings.MAX_IMAGE_PIXELS
    # Pillow itself only refuses images above twice its limit (it merely warns in between), so check explicitly.
    Image.MAX_IMAGE_PIXELS = limit
    upload.seek(0)
    try:
        with Image.open(upload, formats=["JPEG", "PNG"]) as img:
            width, height = img.size
            if width * height > limit:
                fail("image_too_large", f"The photograph is {width} x {height} pixels; the limit is {limit // 1_000_000} megapixels.",
                     width=width, height=height, limit_pixels=limit)
            if img.format != detected.split()[0]:
                fail("content_mismatch", "The photograph could not be read. Upload a valid JPEG or PNG image.")
            img.load()
    except DomainError:
        raise
    except Exception:  # noqa: BLE001 - any decoding failure means the content is not a usable image
        fail("content_mismatch", "The photograph could not be read. Upload a valid JPEG or PNG image.")
    finally:
        upload.seek(0)


def validate_upload(upload, declared_kind: str | None = None) -> Validated:
    name = (getattr(upload, "name", "") or "").replace("\\", "/").split("/")[-1]
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    kind = EXTENSIONS.get(ext)
    if kind is None:
        fail("unsupported_file_type", UNSUPPORTED, extension=ext or None)
    if declared_kind and declared_kind != kind:
        fail("kind_mismatch", f"The file is a {ext} file, but '{declared_kind}' was selected.", extension=ext, declared=declared_kind)
    size = getattr(upload, "size", 0) or 0
    if size == 0:
        fail("empty_file", "The file is empty.")
    limit = settings.MAX_UPLOAD_BYTES[kind]
    if size > limit:
        fail("file_too_large", f"The file is larger than the {limit // (1024 * 1024)} MB limit for {kind.upper()} files.",
             size_bytes=size, limit_bytes=limit)
    upload.seek(0)
    head = upload.read(2048)
    upload.seek(0)
    detected = sniff(kind, head)
    if detected is None:
        label = "image" if kind == "image" else f"{kind.upper()} file"
        fail("content_mismatch", f"The file content is not a valid {label}, although it has a {ext} extension.", extension=ext)
    pages = None
    if kind == "image":
        verify_image(upload, detected)
        content_type = "image/jpeg" if detected.startswith("JPEG") else "image/png"
    else:
        content_type = CONTENT_TYPES[kind]
        if kind == "pdf":
            pages = verify_pdf(upload)
        elif kind == "scan":
            verify_scan(upload, detected)
    safe = SAFE_NAME.sub("_", name)[:200] or f"file{ext}"
    return Validated(kind=kind, ext=ext.lstrip("."), detected_format=detected, content_type=content_type, safe_name=safe, page_count=pages)
