"""STEP original -> validate -> OCCT read (XCAF) -> tessellate -> GLB derivative.

Carried over from the Phase 0 proof of concept (phase0/poc/cad_pipeline, 11/11 tests on synthetic STEP).
Imported only by the CAD worker; the API image does not need OCCT. Production CAD fidelity on real
engineering files is NOT yet verified (Phase 0 blocker B-01).
The pipeline is deliberately explicit, because STEP-to-GLB is not a single OCCT call:

  1. validate      file exists, non-empty, ISO-10303-21 header, size limit
  2. read          STEPCAFControl_Reader into an XCAF document (keeps names, colours, assembly)
  3. check         BRepCheck_Analyzer on every free shape; tight bounding box in source units
  4. tessellate    BRepMesh_IncrementalMesh (linear and angular deflection)
  5. write         RWGltf_CafWriter, binary GLB, input mm Z-up -> glTF metres Y-up
  6. verify        done by tests (test_pipeline.py) by reading the GLB back independently

Tenant isolation is handled by the worker handler (apps.files.jobs): each job runs under its tenant's
row-level security context, in its own temporary directory that is removed on success and on failure.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from OCP.BRepBndLib import BRepBndLib
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.Bnd import Bnd_Box
from OCP.IFSelect import IFSelect_RetDone
from OCP.Message import Message_ProgressRange
from OCP.RWGltf import RWGltf_CafWriter
from OCP.RWMesh import RWMesh_CoordinateSystem_Zup
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TCollection import TCollection_AsciiString, TCollection_ExtendedString
from OCP.collections import IndexedDataMap_TCollection_AsciiString_TCollection_AsciiString as FileInfoMap

try:  # name differs between OCP releases
    from OCP.TDF import TDF_LabelSequence
except ImportError:  # OCP 8
    from OCP.collections import Sequence_TDF_Label as TDF_LabelSequence
from OCP.TDocStd import TDocStd_Document
from OCP.XCAFApp import XCAFApp_Application
from OCP.XCAFDoc import XCAFDoc_DocumentTool

MAX_BYTES = 200 * 1024 * 1024  # provisional limit; real value is OQ-31


class ConversionError(Exception):
    """Conversion failure with a stable code that a UI can map to a message (CAD-008, VWR-009)."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass
class ConversionResult:
    source: str
    output: str
    source_bytes: int
    output_bytes: int
    shapes: int
    valid_shapes: int
    bbox_mm: list[float] = field(default_factory=list)  # xmin,ymin,zmin,xmax,ymax,zmax (source, Z-up)
    seconds_read: float = 0.0
    seconds_mesh: float = 0.0
    seconds_write: float = 0.0
    seconds_total: float = 0.0
    linear_deflection_mm: float = 0.0
    angular_deflection_rad: float = 0.0


def validate(path: Path) -> None:
    if not path.exists():
        raise ConversionError("FILE_NOT_FOUND", str(path))
    size = path.stat().st_size
    if size == 0:
        raise ConversionError("EMPTY_FILE", path.name)
    if size > MAX_BYTES:
        raise ConversionError("FILE_TOO_LARGE", f"{size} bytes > {MAX_BYTES}")
    with path.open("rb") as fh:
        head = fh.read(64)
    if not head.lstrip().startswith(b"ISO-10303-21"):
        raise ConversionError("NOT_STEP", "missing ISO-10303-21 header")


def _new_document() -> TDocStd_Document:
    app = XCAFApp_Application.GetApplication_s()
    doc = TDocStd_Document(TCollection_ExtendedString("XmlXCAF"))
    app.InitDocument(doc)
    return doc


def convert(step_path: Path, glb_path: Path, linear_deflection_mm: float = 0.05,
            angular_deflection_rad: float = 0.35) -> ConversionResult:
    t0 = time.perf_counter()
    validate(step_path)

    doc = _new_document()
    reader = STEPCAFControl_Reader()
    reader.SetColorMode(True)
    reader.SetNameMode(True)
    status = reader.ReadFile(str(step_path))
    if status != IFSelect_RetDone:
        raise ConversionError("STEP_READ_FAILED", f"reader status {status}")
    if not reader.Transfer(doc):
        raise ConversionError("STEP_TRANSFER_FAILED", "no shapes transferred")
    t_read = time.perf_counter()

    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    labels = TDF_LabelSequence()
    shape_tool.GetFreeShapes(labels)
    if labels.Length() == 0:
        raise ConversionError("NO_GEOMETRY", "STEP contains no free shapes")

    box = Bnd_Box()
    valid = 0
    shapes = []
    for i in range(1, labels.Length() + 1):
        shp = shape_tool.GetShape_s(labels.Value(i))
        shapes.append(shp)
        if BRepCheck_Analyzer(shp).IsValid():
            valid += 1
        BRepBndLib.AddOptimal_s(shp, box, False, False)
    if valid == 0:
        raise ConversionError("INVALID_GEOMETRY", "no valid shapes")

    for shp in shapes:
        mesher = BRepMesh_IncrementalMesh(shp, linear_deflection_mm, False, angular_deflection_rad, True)
        mesher.Perform()
        if not mesher.IsDone():
            raise ConversionError("MESH_FAILED", "tessellation did not complete")
    t_mesh = time.perf_counter()

    glb_path.parent.mkdir(parents=True, exist_ok=True)
    writer = RWGltf_CafWriter(TCollection_AsciiString(str(glb_path)), True)
    conv = writer.ChangeCoordinateSystemConverter()
    conv.SetInputLengthUnit(0.001)  # source in millimetres
    conv.SetInputCoordinateSystem(RWMesh_CoordinateSystem_Zup)
    ok = writer.Perform(doc, FileInfoMap(), Message_ProgressRange())
    if not ok or not glb_path.exists():
        raise ConversionError("GLB_WRITE_FAILED", "RWGltf_CafWriter returned failure")
    t_write = time.perf_counter()

    lo, hi = box.CornerMin(), box.CornerMax()  # Bnd_Box.Get() is not bound in OCP 8
    xmin, ymin, zmin, xmax, ymax, zmax = lo.X(), lo.Y(), lo.Z(), hi.X(), hi.Y(), hi.Z()
    return ConversionResult(
        source=step_path.name, output=glb_path.name,
        source_bytes=step_path.stat().st_size, output_bytes=glb_path.stat().st_size,
        shapes=labels.Length(), valid_shapes=valid,
        bbox_mm=[xmin, ymin, zmin, xmax, ymax, zmax],
        seconds_read=t_read - t0, seconds_mesh=t_mesh - t_read, seconds_write=t_write - t_mesh,
        seconds_total=t_write - t0,
        linear_deflection_mm=linear_deflection_mm, angular_deflection_rad=angular_deflection_rad,
    )
