"""Engineering file upload and controlled download links."""
import secrets

from django.core import signing
from django.db.models import Max

from apps.audit.service import record
from apps.core.exceptions import DomainError
from apps.jobs.queue import enqueue

from .models import EngineeringFile, FileVersion
from .storage import ObjectExists, get_storage, original_key
from .validation import validate_upload

LINK_SALT = "files.download-link"
CONVERSION_JOB = "cad.step_to_glb"


def make_thumbnail(ef: EngineeringFile, fv: FileVersion, upload) -> None:
    """480 px JPEG thumbnail of a photograph, with orientation applied and all metadata (EXIF, GPS) removed.
    The original upload is kept unchanged (CAD-005); lists and catalogs show only the thumbnail."""
    import io

    from PIL import Image, ImageOps, __version__ as pillow_version

    from .models import Derivative
    from .storage import derivative_key

    upload.seek(0)
    with Image.open(upload) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((480, 480))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=82, optimize=True)  # no exif= argument: metadata is not copied
    key = derivative_key(ef.tenant_id, ef.pk, fv.version_number, "thumb")
    size, sha = get_storage().save_new(key, [out.getvalue()])
    Derivative.objects.create(tenant=ef.tenant, created_by=fv.created_by, file_version=fv, kind=Derivative.Kind.THUMB,
                              storage_key=key, size_bytes=size, sha256=sha, generator=f"Pillow {pillow_version} thumbnail 480px")


def current_revision_of(ef: EngineeringFile):
    """Passport revision in force when a version is uploaded (file-revision association)."""
    if not ef.passport_id:
        return None
    from apps.passports.models import PassportRevision

    return PassportRevision.objects.filter(passport_id=ef.passport_id).order_by("-revision_number").first()


def store_version(request, ef: EngineeringFile, upload, note: str = "", passport_revision=None) -> FileVersion:
    v = validate_upload(upload, declared_kind=ef.kind)
    passport_revision = passport_revision or current_revision_of(ef)
    # Serialise version numbering per file
    EngineeringFile.objects.select_for_update().filter(pk=ef.pk).first()
    number = (ef.versions.aggregate(m=Max("version_number"))["m"] or 0) + 1
    key = original_key(ef.tenant_id, ef.pk, number, v.ext)
    try:
        size, sha = get_storage().save_new(key, upload.chunks())
    except ObjectExists:
        raise DomainError("version_conflict", "This file version already exists. Please retry the upload.")
    if size != upload.size:
        raise DomainError("upload_incomplete", "The upload was incomplete. Please try again.", http_status=400)
    fv = FileVersion.objects.create(
        tenant=ef.tenant, created_by=request.user, file=ef, version_number=number, original_filename=v.safe_name,
        size_bytes=size, sha256=sha, detected_format=v.detected_format, content_type=v.content_type,
        storage_key=key, passport_revision=passport_revision, note=note[:300], page_count=v.page_count,
    )
    record(request, "file.version_uploaded", obj=fv, data={"file": str(ef.pk), "version": number, "sha256": sha, "size": size})
    if ef.kind == EngineeringFile.Kind.IMAGE:
        make_thumbnail(ef, fv, upload)
    if ef.kind == EngineeringFile.Kind.STEP:
        # The job row commits with the upload, so the worker only sees it once the version exists.
        enqueue(ef.tenant, CONVERSION_JOB, {"file_version": str(fv.pk)}, created_by=request.user)
    return fv


def make_link_token(request, *, storage_key: str, filename: str, variant: str, object_id: str) -> str:
    """Signed, short-lived, single-use link token bound to user, membership and tenant. The random nonce `n`
    is recorded on first use (LinkRedemption), so the same link cannot be opened twice."""
    return signing.dumps({"k": storage_key, "f": filename, "v": variant, "o": object_id, "n": secrets.token_urlsafe(18),
                          "t": str(request.tenant.pk), "m": str(request.membership.pk), "u": str(request.user.pk)},
                         salt=LINK_SALT, compress=True)


def read_link_token(token: str, max_age: int) -> dict:
    try:
        data = signing.loads(token, salt=LINK_SALT, max_age=max_age)
    except signing.SignatureExpired:
        raise DomainError("link_expired", "This download link has expired. Request a new one.", http_status=410)
    except signing.BadSignature:
        raise DomainError("link_invalid", "This download link is not valid.", http_status=403)
    if not data.get("n"):  # links issued before single-use links existed
        raise DomainError("link_invalid", "This download link is not valid.", http_status=403)
    return data


def redeem_link(data: dict, user) -> None:
    """Record the link's first use inside the link's tenant context; a second use is refused."""
    from django.db import IntegrityError, transaction

    from .models import LinkRedemption

    try:
        with transaction.atomic():  # savepoint: a duplicate must not break the request transaction
            LinkRedemption.objects.create(tenant_id=data["t"], created_by=user, nonce=data["n"], variant=data["v"], object_id=data["o"])
    except IntegrityError:
        raise DomainError("link_used", "This link has already been used. Request a new one.", http_status=410)
