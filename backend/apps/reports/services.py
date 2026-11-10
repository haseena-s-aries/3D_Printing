"""Generate, preview and download Digital Passport PDF reports (CN-005). Runs locally; no external service is used."""
import base64
import hashlib
import io
import json
import shutil
import subprocess
import tempfile
import re
import uuid
from pathlib import Path

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.audit.service import record
from apps.core.exceptions import DomainError
from apps.files.models import Derivative, EngineeringFile, FileVersion
from apps.files.storage import get_storage
from apps.passports.models import PassportRevision
from apps.tenancy.models import Role
from apps.tenancy.permissions import has_capability

from . import builder, mts
from .models import PassportReport, PassportReportEvent, PassportReportReplacement, PassportReportWithdrawal

RENDERER = Path(settings.BASE_DIR) / "scripts" / "report_render.mjs"
ROLE_NAMES = {Role.OPERATOR_ENGINEER: "Aries Engineer", Role.OPERATOR_QA: "Aries QA", Role.CLIENT_ADMIN: "Client Administrator",
              Role.CLIENT_ENGINEER: "Client Engineer", Role.CLIENT_USER: "Client User", Role.OPERATOR_ADMIN: "Aries Admin"}


def _run(job: dict, workdir: Path) -> dict:
    job_file = workdir / f"job-{job['mode']}.json"
    job_file.write_text(json.dumps(job), encoding="utf-8")
    try:
        out = subprocess.run([getattr(settings, "REPORT_NODE", "node"), str(RENDERER), str(job_file)], capture_output=True,
                             text=True, timeout=120)
        return json.loads(out.stdout.strip().splitlines()[-1])
    except (subprocess.SubprocessError, OSError, ValueError, IndexError) as e:
        return {"ok": False, "error": f"renderer unavailable: {type(e).__name__}"}


def model_for(passport, choice: dict | None = None, variant: str = "internal"):
    """The model whose views are printed (post-UAT D-03): the STEP version chosen in the builder, or by default the newest STEP
    version with a converted GLB (preferring files on the passport). A client-facing report only uses a version released to the
    client (D-02), so its renders never show an Aries-only model."""
    from apps.files.api import client_version_number

    def usable(f, number):
        v = f.versions.filter(version_number=number).first() if number else f.versions.order_by("-version_number").first()
        glb = v and Derivative.objects.filter(file_version=v, kind=Derivative.Kind.GLB).first()
        return (f, v, glb) if glb else None

    steps = EngineeringFile.objects.filter(tenant=passport.tenant, part=passport.part, kind=EngineeringFile.Kind.STEP)
    if choice:
        fid, number = choice.get("file"), choice.get("version")
        f = steps.filter(pk=fid).first() if _is_uuid(str(fid or "")) else None
        if f is None:
            raise DomainError("invalid_model", "Choose a STEP model of this passport's part.", http_status=400)
        if variant == "client":
            released = client_version_number(f)
            if released is None or (number and int(number) != released):
                raise DomainError("model_not_released", f"'{f.title}' v{number or released} is not released to the client, so it cannot be "
                                  "rendered in a client-facing report.", http_status=403)
            number = released
        found = usable(f, int(number) if number else None)
        if found is None:
            raise DomainError("model_not_converted", f"'{f.title}' has no converted 3D view for that version.", http_status=409)
        return found
    for qs in (steps.filter(passport=passport), steps):
        for f in qs.order_by("-updated_at"):
            number = client_version_number(f) if variant == "client" else None
            if variant == "client" and number is None:
                continue
            found = usable(f, number)
            if found:
                return found
    return None, None, None


def _views(passport, workdir: Path, choice: dict | None = None, variant: str = "internal"):
    f, v, glb = model_for(passport, choice, variant)
    if glb is None:
        reason = ("No STEP model released to the client with a converted 3D view." if variant == "client"
                  else "No STEP model with a converted 3D view on this passport.")
        return {}, None, reason, {n: {"label": reason} for n in ("front", "top", "iso")}, ""
    src = workdir / "model.glb"
    with get_storage().open(glb.storage_key) as fh, open(src, "wb") as out:
        shutil.copyfileobj(fh, out)
    result = _run({"mode": "views", "glb": str(src), "out": str(workdir / "views")}, workdir)
    model = f"{f.title} (STEP v{v.version_number}, SHA-256 {v.sha256[:8]}…)"
    if not result.get("ok"):
        reason = "Rendering unavailable; no image substituted."
        return {}, v, f"{reason} ({result.get('error', '')[:120]})", {n: {"label": reason} for n in ("front", "top", "iso")}, model
    images = {n: "data:image/png;base64," + base64.b64encode(Path(p).read_bytes()).decode() for n, p in result["views"].items()}
    return images, v, "rendered", {n: {"label": ""} for n in images}, model


def resolve_attachments(request, passport, variant: str, items: list) -> list:
    """Attachments in the chosen order, each pinned to one immutable file version.

    Items are file ids or {"file", "version"}; the latest version is used when none is given. Internal templates may
    attach any PDF document of this passport's part; client-facing reports only documents released to the client
    (client_visible) and only for users who may download originals (CN-005 R4/R5). Server-side, for preview too."""
    out, seen = [], set()
    for order, item in enumerate(items or [], start=1):
        fid = item.get("file") if isinstance(item, dict) else item
        number = item.get("version") if isinstance(item, dict) else None
        f = (EngineeringFile.objects.filter(tenant=passport.tenant, pk=fid, kind=EngineeringFile.Kind.PDF)
             .filter(Q(part=passport.part) | Q(passport=passport)).first()) if _is_uuid(fid) else None
        if f is None:
            raise DomainError("invalid_attachment", "Attachments must be PDF documents of this passport's part.", http_status=400)
        if str(f.pk) in seen:
            raise DomainError("duplicate_attachment", f"'{f.title}' is selected twice.", http_status=400)
        seen.add(str(f.pk))
        if variant == "client" and (not f.client_visible or not has_capability(request, "files.download_original")):
            raise DomainError("attachment_not_permitted", f"'{f.title}' is not released to the client, so it cannot be attached to a "
                              "client-facing report.", http_status=403)
        if variant == "client":  # post-UAT D-02: a client-facing report attaches exactly the version released to the client
            from apps.files.api import client_version_number

            released = client_version_number(f)
            if number and int(number) != released:
                raise DomainError("attachment_version_not_released", f"Version {number} of '{f.title}' is not the version released to the "
                                  f"client (v{released}).", http_status=403)
            number = released
        v = f.versions.filter(version_number=int(number)).first() if number else f.versions.order_by("-version_number").first()
        if v is None:
            raise DomainError("invalid_attachment", f"Version {number} of '{f.title}' does not exist.", http_status=400)
        out.append({"order": order, "file": str(f.pk), "version": v.version_number, "version_id": str(v.pk), "title": f.title,
                    "category": f.category, "sha256": v.sha256, "pages": v.page_count, "client_visible": f.client_visible,
                    "storage_key": v.storage_key})
    return out


def _is_uuid(value) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False


def _next_number(passport, revision_number: int, template: str) -> str:
    # Highest sequence ever issued for this passport + 1: report rows are never deleted, but a number must never be reused
    # even if records are archived or moved in future (withdrawn reports keep their number).
    seqs = [int(m.group(1)) for n in PassportReport.objects.filter(passport=passport).values_list("number", flat=True)
            if (m := re.search(r"-R\d+-(\d+)(?:-[A-Z]+)?$", n))]
    seq = max(seqs, default=0) + 1
    suffix = {"internal": "-INT", "mts": "-MTS"}.get(template, "")
    return f"RPT-{passport.passport_number}-R{revision_number}-{seq:03d}{suffix}"


def _check_rights(request, variant: str) -> None:
    if variant == PassportReport.Variant.INTERNAL and not has_capability(request, "reports.generate_internal"):
        raise DomainError("permission_denied", "Only Aries Engineers generate Aries-internal reports.", http_status=403)
    if variant == PassportReport.Variant.CLIENT and not has_capability(request, "reports.generate_client"):
        raise DomainError("permission_denied", "Your role can preview client reports but not generate them.", http_status=403)


def build(request, passport, *, template: str, revision_number: int | None, attachment_items: list, model: dict | None = None) -> dict:
    """Render the template, then append the attachments in order. Returns the PDF and what went into it; stores nothing."""
    if template not in PassportReport.TEMPLATE_VARIANT:
        raise DomainError("invalid_template", "Choose a report template.", http_status=400)
    variant = PassportReport.TEMPLATE_VARIANT[template]
    _check_rights(request, variant)
    revisions = passport.revisions.order_by("-revision_number")
    revision = revisions.filter(revision_number=revision_number).first() if revision_number else revisions.first()
    if revision is None:
        raise DomainError("not_found", "Revision not found.", http_status=404)
    if variant == "client" and request.membership.role not in (Role.OPERATOR_ENGINEER, Role.OPERATOR_QA) and revision != revisions.first():
        raise DomainError("current_revision_only", "Client reports are generated from the current revision.", http_status=400)
    attachments = resolve_attachments(request, passport, variant, attachment_items)
    sources = _load_attachments(attachments)
    workdir = Path(tempfile.mkdtemp(prefix="passport-report-"))
    try:
        images, model_version, views_status, view_labels, model = _views(passport, workdir, model, variant)
        now = timezone.localtime()
        meta = {"generated": now.strftime("%d %b %Y, %H:%M %Z"), "by_role": ROLE_NAMES.get(request.membership.role, request.membership.role),
                "model": model, "attachments": attachments, "number": _next_number(passport, revision.revision_number, template)}
        body = None
        for _pass in range(2):  # pass 2 knows the body length, so attachment start pages and "of N" totals are exact
            data = builder.collect(passport, revision, variant, request.tenant.name, attachments, view_labels)
            meta["fingerprint"] = builder.fingerprint(data)
            if template == "mts":
                html, footer = mts.render_mts(data, meta, images, branding()), mts.mts_footer(meta, data)
            else:
                html, footer = builder.render_html(data, meta, images, branding()), builder.footer(meta, data)
            (workdir / "report.html").write_text(html, encoding="utf-8")
            result = _run({"mode": "pdf", "html": str(workdir / "report.html"), "out": str(workdir / "report.pdf"), "footer": footer}, workdir)
            if not result.get("ok"):
                raise DomainError("report_render_failed", "The report could not be rendered. Try again later.",
                                  details={"reason": result.get("error", "")[:200]}, http_status=503)
            body = (workdir / "report.pdf").read_bytes()
            body_pages = _page_count(body)
            start = body_pages + 1
            for a in attachments:
                a["first_page"] = start
                start += a["pages"]
            total = start - 1
            if not attachments or meta.get("total_pages") == total:
                break
            meta["total_pages"] = total
        if total > settings.REPORT_MAX_PAGES:
            raise DomainError("report_too_long", f"The assembled report would have {total} pages; the limit is {settings.REPORT_MAX_PAGES}.",
                              http_status=400)
        pdf_bytes, pages = _merge(body, attachments, sources)
        return {"pdf": pdf_bytes, "pages": pages, "variant": variant, "revision": revision, "meta": meta, "attachments": attachments,
                "model_version": model_version, "views_status": views_status}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _page_count(pdf: bytes) -> int:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(pdf)
    n = len(doc)
    doc.close()
    return n


def _load_attachments(attachments: list) -> list:
    """Read each pinned version, check it is intact (SHA-256) and readable, and record its page count. A file that fails
    stops the report before anything is stored, so a damaged attachment never produces a half-assembled report."""
    import pypdfium2 as pdfium

    sources = []
    for a in attachments:
        with get_storage().open(a["storage_key"]) as fh:
            data = fh.read()
        if hashlib.sha256(data).hexdigest() != a["sha256"]:
            raise DomainError("attachment_integrity", f"The stored copy of '{a['title']}' does not match its recorded checksum.",
                              http_status=409)
        try:
            doc = pdfium.PdfDocument(data)
            pages = len(doc)
        except Exception as e:  # noqa: BLE001 - PDFium refuses damaged or encrypted files
            raise DomainError("attachment_unreadable", f"The attachment '{a['title']}' could not be read as a PDF.",
                              details={"reason": type(e).__name__}, http_status=400)
        if pages > settings.REPORT_ATTACHMENT_MAX_PAGES:
            raise DomainError("attachment_too_long", f"'{a['title']}' has {pages} pages; the limit per attachment is "
                              f"{settings.REPORT_ATTACHMENT_MAX_PAGES}.", http_status=400)
        a["pages"] = pages
        sources.append(doc)
    return sources


def generate(request, passport, *, template: str, revision_number: int | None, attachment_items: list,
             replaces: PassportReport | None = None, model: dict | None = None) -> PassportReport:
    if replaces is not None:
        if replaces.passport_id != passport.pk:
            raise DomainError("invalid_replacement", "A replacement must be generated for the same passport.", http_status=400)
        if not hasattr(replaces, "withdrawal"):
            raise DomainError("not_withdrawn", "Only a withdrawn report can be replaced. Withdraw it first.", http_status=409)
        if PassportReportReplacement.objects.filter(withdrawn=replaces).exists():
            raise DomainError("already_replaced", f"{replaces.number} already has a replacement report.", http_status=409)
    built = build(request, passport, template=template, revision_number=revision_number, attachment_items=attachment_items, model=model)
    meta, revision, attachments, variant = built["meta"], built["revision"], built["attachments"], built["variant"]
    try:
        with transaction.atomic():
            key = f"tenants/{passport.tenant_id}/reports/{passport.pk}/{uuid.uuid4().hex}.pdf"
            size, sha = get_storage().save_new(key, [built["pdf"]])
            report = PassportReport.objects.create(
                tenant=passport.tenant, created_by=request.user, passport=passport, revision_number=revision.revision_number,
                revision_status=revision.status, variant=variant, template=template, number=meta["number"],
                model_file_version=built["model_version"], views_status=built["views_status"][:300],
                attachments=[{k: a[k] for k in ("order", "file", "version", "version_id", "title", "category", "sha256", "pages",
                                                "first_page", "client_visible")} for a in attachments],
                content_sha256=meta["fingerprint"], storage_key=key, pdf_sha256=sha, size_bytes=size, page_count=built["pages"],
                watermarked=revision.status != PassportRevision.Status.APPROVED)
            PassportReportEvent.objects.create(tenant=passport.tenant, created_by=request.user, report=report,
                                               action=PassportReportEvent.Action.GENERATED)
            if replaces is not None:
                PassportReportReplacement.objects.create(tenant=passport.tenant, created_by=request.user, withdrawn=replaces,
                                                         replacement=report)
    except IntegrityError:  # two reports numbered at the same moment; the printed number must stay true
        raise DomainError("report_number_conflict", "Another report was generated at the same moment. Try again.", http_status=409)
    record(request, "passport_report.generated", obj=report, data={
        "number": report.number, "template": template, "variant": variant, "revision": revision.revision_number,
        "views": built["views_status"][:60], "attachments": [[a["order"], a["file"], a["version"], a["sha256"][:12]] for a in attachments],
        **({"replaces": replaces.number} if replaces is not None else {})})
    return report


def withdraw(request, report: PassportReport, reason: str) -> PassportReportWithdrawal:
    """Withdraw a generated report: from now on no role receives its PDF or page images. Record and history are kept."""
    reason = (reason or "").strip()
    if len(reason) < 10:
        raise DomainError("reason_required", "Give the reason for the withdrawal (at least 10 characters).", http_status=400)
    if not has_capability(request, "reports.withdraw"):
        raise DomainError("permission_denied", "Your role cannot withdraw reports.", http_status=403)
    try:
        with transaction.atomic():
            w = PassportReportWithdrawal.objects.create(tenant=report.tenant, created_by=request.user, report=report, reason=reason[:2000])
    except IntegrityError:
        raise DomainError("already_withdrawn", f"{report.number} is already withdrawn.", http_status=409)
    record(request, "passport_report.withdrawn", obj=report, data={"number": report.number, "variant": report.variant,
                                                                     "revision": report.revision_number, "reason": w.reason})
    return w


def ensure_available(report: PassportReport) -> None:
    """Checked on every request for report content (PDF or page image), before anything is read or logged."""
    if PassportReportWithdrawal.objects.filter(report_id=report.pk).exists():
        raise DomainError("report_withdrawn", f"{report.number} was withdrawn and is no longer available.", http_status=410)


def preview(request, passport, *, template: str, revision_number: int | None, attachment_items: list, model: dict | None = None) -> bytes:
    """The complete assembled PDF exactly as it would be generated, without storing a report (audited)."""
    built = build(request, passport, template=template, revision_number=revision_number, attachment_items=attachment_items, model=model)
    record(request, "passport_report.draft_previewed", obj=passport, data={
        "template": template, "revision": built["revision"].revision_number, "pages": built["pages"],
        "attachments": [[a["order"], a["file"], a["version"]] for a in built["attachments"]]})
    return built["pdf"]


def _merge(body: bytes, attachments: list, sources: list):
    """Append each attachment's pages after the report body with PDFium (originals are only read, never changed)."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(body)
    for src in sources:
        doc.import_pages(src)
    buf = io.BytesIO()
    doc.save(buf)
    pages = len(doc)
    doc.close()
    for src in sources:
        src.close()
    return buf.getvalue(), pages


def branding() -> dict:
    """R8: text-only branding until Aries supplies an approved logo and company details."""
    return {"name": getattr(settings, "REPORT_BRAND_NAME", "ARIES")}


def log(request, report: PassportReport, action: str) -> None:
    """Record a successful preview or download (call only after the content was read)."""
    PassportReportEvent.objects.create(tenant=report.tenant, created_by=request.user, report=report, action=action)
    record(request, f"passport_report.{action}", obj=report, data={"number": report.number, "variant": report.variant,
                                                                    "revision": report.revision_number})


def read_pdf(report: PassportReport) -> bytes:
    ensure_available(report)
    try:
        with get_storage().open(report.storage_key) as fh:
            return fh.read()
    except FileNotFoundError:
        raise DomainError("report_file_unavailable", f"The stored file of {report.number} is not available.", http_status=410)


def page_png(report: PassportReport, page: int) -> bytes:
    """Preview image of one page (preview-only roles never receive the PDF file, R5)."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(read_pdf(report))
    if not 1 <= page <= len(pdf):
        raise DomainError("not_found", "Page not found.", http_status=404)
    img = pdf[page - 1].render(scale=1.4).to_pil()
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
