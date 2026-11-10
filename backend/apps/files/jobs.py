"""CAD conversion job handler: STEP original -> GLB derivative (runs in the CAD worker).

Runs under the job's tenant row-level security context (set by apps.jobs.queue.run_one).
The original is read from storage into a per-job temporary directory; the derivative is written
to a separate derivatives key; the temporary directory is always removed (HYB-011, AZC-004).
"""
import shutil
import tempfile
from pathlib import Path

from apps.audit.models import AuditEvent
from apps.jobs.queue import JobFailure, handler

from .models import Derivative, FileVersion
from .storage import ObjectExists, derivative_key, get_storage

GENERATOR = "occt-rwgltf (cadquery-ocp 8.0.1.1.0), linear deflection 0.05 mm, angular 0.35 rad"


@handler("cad.step_to_glb")
def step_to_glb(job):
    try:
        from . import cad_pipeline  # needs requirements-cad.txt; not installed in the API image
    except ImportError as e:
        raise JobFailure("worker_dependency_missing", f"OCCT is not installed in this worker: {e}")
    fv = FileVersion.objects.filter(pk=job.payload.get("file_version")).select_related("file").first()
    if fv is None:
        raise JobFailure("source_not_found", "File version not found in this tenant.")
    if fv.derivatives.filter(kind=Derivative.Kind.GLB).exists():
        return  # idempotent
    storage = get_storage()
    tmp = Path(tempfile.mkdtemp(prefix=f"cad-{fv.tenant_id}-"))
    try:
        src = tmp / "source.stp"
        with storage.open(fv.storage_key) as fh, open(src, "wb") as out:
            shutil.copyfileobj(fh, out, 1024 * 1024)
        out_glb = tmp / "derivative.glb"
        try:
            result = cad_pipeline.convert(src, out_glb)
        except cad_pipeline.ConversionError as e:
            raise JobFailure(e.code.lower(), e.detail)
        key = derivative_key(fv.tenant_id, fv.file_id, fv.version_number, "glb")

        def chunks():
            with open(out_glb, "rb") as fh:
                while block := fh.read(1024 * 1024):
                    yield block

        try:
            size, sha = storage.save_new(key, chunks())
        except ObjectExists:
            raise JobFailure("derivative_exists", key)
        Derivative.objects.create(
            tenant_id=fv.tenant_id, file_version=fv, kind=Derivative.Kind.GLB, storage_key=key, size_bytes=size,
            sha256=sha, generator=GENERATOR,
            details={"shapes": result.shapes, "valid_shapes": result.valid_shapes, "bbox_mm": result.bbox_mm,
                     "seconds_total": round(result.seconds_total, 3)},
        )
        AuditEvent.objects.create(tenant_id=fv.tenant_id, action="file.derivative_created", object_type="fileversion",
                                  object_id=str(fv.pk), actor_email="cad-worker", data={"kind": "glb", "sha256": sha})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
