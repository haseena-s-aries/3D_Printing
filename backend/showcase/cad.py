"""Synthetic, parametric spare-part geometry for the demonstration dataset (OCCT via cadquery-ocp).

Every model is built here from primitives and Boolean operations: no third-party or customer CAD is used. Each
family is parameterised, so two parts of the same family (for example two impellers) are different solids.
Outputs: STEP AP214 text, plus a triangle mesh and sampled edges used for the synthetic renders and drawings.
"""
from __future__ import annotations

import contextlib
import math
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCone, BRepPrimAPI_MakeCylinder
from OCP.Bnd import Bnd_Box
from OCP.GProp import GProp_GProps
from OCP.IFSelect import IFSelect_RetDone
from OCP.Interface import Interface_Static
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_REVERSED
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS
from OCP.gp import gp_Ax1, gp_Ax2, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec

Z = gp_Dir(0, 0, 1)
X = gp_Dir(1, 0, 0)
Y = gp_Dir(0, 1, 0)


# ---- primitives -------------------------------------------------------------------------------------------------

def cyl(r, h, x=0.0, y=0.0, z=0.0, axis=Z):
    return BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(x, y, z), axis), r, h).Shape()


def cone(r1, r2, h, z=0.0):
    return BRepPrimAPI_MakeCone(gp_Ax2(gp_Pnt(0, 0, z), Z), r1, r2, h).Shape()


def box(dx, dy, dz, x=0.0, y=0.0, z=0.0):
    return BRepPrimAPI_MakeBox(gp_Pnt(x, y, z), dx, dy, dz).Shape()


def fuse(*shapes):
    out = shapes[0]
    for s in shapes[1:]:
        out = BRepAlgoAPI_Fuse(out, s).Shape()
    return out


def cut(base, *tools):
    for t in tools:
        base = BRepAlgoAPI_Cut(base, t).Shape()
    return base


def rotate_z(shape, degrees):
    t = gp_Trsf()
    t.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), Z), math.radians(degrees))
    return BRepBuilderAPI_Transform(shape, t, True).Shape()


def bolt_circle(n, pcd, r, h, z=0.0, start=0.0):
    holes = [cyl(r, h, (pcd / 2) * math.cos(math.radians(start + i * 360 / n)),
                 (pcd / 2) * math.sin(math.radians(start + i * 360 / n)), z) for i in range(n)]
    return fuse(*holes)


# ---- component families (all dimensions in mm) ------------------------------------------------------------------

def pump_impeller(d=160, hub_d=48, bore=22, blades=6, height=42):
    """Closed-back impeller: back shroud, hub with bore and keyway, straight radial-swept vanes."""
    shroud = cyl(d / 2, 6)
    hub = cyl(hub_d / 2, height)
    vane = box(d / 2 - hub_d / 2 + 2, 5, height * 0.7, hub_d / 2 - 2, -2.5, 6)
    vanes = [rotate_z(rotate_z(vane, 12), i * 360 / blades) for i in range(blades)]
    body = fuse(shroud, hub, *vanes)
    keyway = box(bore * 0.3, 6, height + 2, bore / 2 - 1, -3, -1)
    return cut(body, cyl(bore / 2, height + 2, z=-1), keyway)


def shaft_coupling(d=110, hub_d=60, bore=32, hub_len=55, flange_t=16, bolts=6):
    """Flanged rigid coupling half with keyway and bolt circle."""
    flange = cyl(d / 2, flange_t)
    hub = cyl(hub_d / 2, hub_len, z=flange_t)
    body = fuse(flange, hub)
    holes = bolt_circle(bolts, d * 0.72, 5.5, flange_t + 2, -1)
    keyway = box(bore * 0.35, 10, hub_len + flange_t + 2, bore / 2 - 2, -5, -1)
    return cut(body, cyl(bore / 2, hub_len + flange_t + 2, z=-1), holes, keyway)


def valve_body(dn=50, length=150, flange_d=165, flange_t=18, bolts=4):
    """Two-flange globe-style valve body with through bore and bonnet boss."""
    barrel = cyl(dn * 0.85, length - 2 * flange_t, -(length / 2 - flange_t), 0, 0, X)
    f1 = cyl(flange_d / 2, flange_t, -length / 2, 0, 0, X)
    f2 = cyl(flange_d / 2, flange_t, length / 2 - flange_t, 0, 0, X)
    boss = cyl(dn * 0.6, dn * 1.6, 0, 0, 0, Z)
    body = fuse(barrel, f1, f2, boss)
    bore = cyl(dn / 2, length + 2, -length / 2 - 1, 0, 0, X)
    stem = cyl(dn * 0.22, dn * 1.7, 0, 0, 0, Z)
    holes = []
    for i in range(bolts):
        a = math.radians(45 + i * 360 / bolts)
        for xs in (-length / 2 - 1, length / 2 - flange_t - 1):
            holes.append(cyl(9, flange_t + 2, xs, flange_d * 0.38 * math.cos(a), flange_d * 0.38 * math.sin(a), X))
    return cut(body, bore, stem, *holes)


def pipe_flange(d=215, bore=90, t=22, neck_d=120, neck_len=45, bolts=8):
    """Weld-neck flange: raised-face disc, tapered neck, bolt circle."""
    disc = cyl(d / 2, t)
    face = cyl(neck_d / 2 + 12, 3, z=-3)
    neck = cone(neck_d / 2, bore / 2 + 5, neck_len, z=t)
    body = fuse(disc, face, neck)
    return cut(body, cyl(bore / 2, t + neck_len + 10, z=-5), bolt_circle(bolts, d * 0.78, 9, t + 2, -1, 22.5))


def bearing_housing(bore=62, length=170, height=95, base_t=22, width=60):
    """Pillow-block housing: base plate with slotted mounting holes, cylindrical bearing seat."""
    base = box(length, width, base_t, -length / 2, -width / 2, 0)
    seat = cyl(bore * 0.9, width, 0, -width / 2, height * 0.55, Y)
    web = box(bore * 1.5, width, height * 0.55 - base_t + 5, -bore * 0.75, -width / 2, base_t - 5)
    body = fuse(base, web, seat)
    seat_bore = cyl(bore / 2, width + 2, 0, -width / 2 - 1, height * 0.55, Y)
    holes = [cyl(7, base_t + 2, xs, 0, -1) for xs in (-length / 2 + 18, length / 2 - 18)]
    grease = cyl(3, bore, 0, 0, height * 0.55)
    return cut(body, seat_bore, *holes, grease)


def spacer_sleeve(od=45, id_=30, length=40.5, chamfer=1.5):
    """Plain spacer sleeve with an outer step (chamfer approximated by a short cone)."""
    body = fuse(cyl(od / 2, length - chamfer), cone(od / 2, od / 2 - chamfer, chamfer, z=length - chamfer))
    return cut(body, cyl(id_ / 2, length + 2, z=-1))


def bracket(w=120, h=90, t=10, depth=60, holes=2):
    """L-bracket with a triangular gusset and mounting holes in both legs."""
    base = box(w, depth, t)
    upright = box(w, t, h, 0, 0, 0)
    gusset = rotate_gusset(t, depth, h, w)
    body = fuse(base, upright, gusset)
    tools = [cyl(5.5, t + 2, w * (i + 1) / (holes + 1), depth * 0.65, -1) for i in range(holes)]
    tools += [cyl(5.5, t + 2, w * (i + 1) / (holes + 1), -1, h * 0.7, Y) for i in range(holes)]
    return cut(body, *tools)


def rotate_gusset(t, depth, h, w):
    """Simple stepped gusset (three blocks) in the middle of the bracket."""
    blocks = [box(t, depth * f, h * (1 - f) * 0.9, w / 2 - t / 2, 0, t) for f in (0.25, 0.5, 0.75)]
    return fuse(*blocks)


def gear_housing(lx=200, ly=140, lz=110, wall=10, shafts=2):
    """Open-top gearbox housing: hollow shell, bearing bosses with bores, base flange."""
    shell = cut(box(lx, ly, lz), box(lx - 2 * wall, ly - 2 * wall, lz, wall, wall, wall))
    flange = cut(box(lx + 30, ly + 30, 12, -15, -15, 0), box(lx - 2 * wall, ly - 2 * wall, 14, wall, wall, -1))
    bosses, bores = [], []
    for i in range(shafts):
        x = lx * (i + 1) / (shafts + 1)
        r = 22 - i * 4
        bosses += [cyl(r + 10, 14, x, -14, lz * 0.6, Y), cyl(r + 10, 14, x, ly, lz * 0.6, Y)]
        bores.append(cyl(r, ly + 40, x, -20, lz * 0.6, Y))
    body = fuse(shell, flange, *bosses)
    return cut(body, *bores)


def fan_hub(d=140, hub_d=55, bore=25, arms=5, t=14, arm_w=18):
    """Fan hub: central boss with bore and radial blade-mounting arms with two holes each."""
    boss = cyl(hub_d / 2, t * 2.2)
    arm = box(d / 2 - hub_d / 2 + 6, arm_w, t, hub_d / 2 - 6, -arm_w / 2, 0)
    arms_ = [rotate_z(arm, i * 360 / arms) for i in range(arms)]
    body = fuse(boss, *arms_)
    holes = []
    for i in range(arms):
        a = math.radians(i * 360 / arms)
        for rr in (d / 2 - 10, d / 2 - 28):
            holes.append(cyl(3.5, t + 2, rr * math.cos(a), rr * math.sin(a), -1))
    return cut(body, cyl(bore / 2, t * 2.2 + 2, z=-1), *holes)


def pump_cover(d=230, t=20, boss_d=80, boss_h=30, bolts=10, seal_bore=40):
    """Pump casing cover: disc with raised spigot, central seal boss, bolt circle."""
    disc = cyl(d / 2, t)
    spigot = cyl(d / 2 - 14, 5, z=-5)
    boss = cyl(boss_d / 2, boss_h, z=t)
    body = fuse(disc, spigot, boss)
    return cut(body, cyl(seal_bore / 2, t + boss_h + 10, z=-6), bolt_circle(bolts, d - 24, 7, t + 10, -6, 18))


def thrust_collar(od=120, id_=60, t=25, holes=4):
    """Bearing thrust collar: thick ring with axial tapped-hole pattern and set-screw hole."""
    body = cut(cyl(od / 2, t), cyl(id_ / 2, t + 2, z=-1))
    pcd = (od + id_) / 2
    return cut(body, bolt_circle(holes, pcd, 4.2, t + 2, -1, 45), cyl(3, od, 0, -od / 2 - 1, t / 2, Y))


FAMILIES = {
    "pump_impeller": pump_impeller, "shaft_coupling": shaft_coupling, "valve_body": valve_body,
    "pipe_flange": pipe_flange, "bearing_housing": bearing_housing, "spacer_sleeve": spacer_sleeve,
    "bracket": bracket, "gear_housing": gear_housing, "fan_hub": fan_hub, "pump_cover": pump_cover,
    "thrust_collar": thrust_collar,
}


# ---- outputs ----------------------------------------------------------------------------------------------------

@dataclass
class Model:
    shape: object
    volume_mm3: float
    bbox: tuple[float, float, float, float, float, float]
    faces: int
    valid: bool

    @property
    def size(self) -> tuple[float, float, float]:
        x0, y0, z0, x1, y1, z1 = self.bbox
        return (x1 - x0, y1 - y0, z1 - z0)


def build(family: str, **params) -> Model:
    shape = FAMILIES[family](**params)
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    b = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, b, False, False)
    faces = 0
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        faces += 1
        exp.Next()
    lo, hi = b.CornerMin(), b.CornerMax()
    bbox = (lo.X(), lo.Y(), lo.Z(), hi.X(), hi.Y(), hi.Z())
    return Model(shape, props.Mass(), bbox, faces, BRepCheck_Analyzer(shape).IsValid())


def step_bytes(model: Model, product_name: str) -> bytes:
    """STEP AP214 text of the model (the writer only writes to a path, so use a private temp file)."""
    Interface_Static.SetCVal_s("write.step.schema", "AP214IS")
    Interface_Static.SetCVal_s("write.step.product.name", product_name)
    with tempfile.TemporaryDirectory(prefix="showcase-step-") as d, _quiet():
        writer = STEPControl_Writer()
        writer.Transfer(model.shape, STEPControl_AsIs)
        path = Path(d) / "model.stp"
        if writer.Write(str(path)) != IFSelect_RetDone:
            raise RuntimeError("STEP export failed")
        return path.read_bytes()


@contextlib.contextmanager
def _quiet():
    """The OCCT STEP writer prints transfer statistics from C++; keep the command output readable."""
    sys.stdout.flush()
    saved = os.dup(1)
    with open(os.devnull, "w") as null:
        os.dup2(null.fileno(), 1)
        try:
            yield
        finally:
            sys.stdout.flush()
            os.dup2(saved, 1)
            os.close(saved)


def triangles(model: Model, deflection: float = 0.4):
    """World-space triangles [(p1, p2, p3), ...] with outward winding."""
    BRepMesh_IncrementalMesh(model.shape, deflection, False, 0.35, True)
    out = []
    exp = TopExp_Explorer(model.shape, TopAbs_FACE)
    while exp.More():
        face = TopoDS.Face(exp.Current())
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        if tri is not None:
            trsf = loc.Transformation()
            pts = [tri.Node(i).Transformed(trsf) for i in range(1, tri.NbNodes() + 1)]
            pts = [(p.X(), p.Y(), p.Z()) for p in pts]
            reverse = face.Orientation() == TopAbs_REVERSED
            for i in range(1, tri.NbTriangles() + 1):
                a, b, c = tri.Triangle(i).Get()
                t = (pts[a - 1], pts[c - 1], pts[b - 1]) if reverse else (pts[a - 1], pts[b - 1], pts[c - 1])
                out.append(t)
        exp.Next()
    return out


def edge_polylines(model: Model, samples: int = 24):
    """Every B-rep edge sampled as a 3D polyline (for orthographic drawing views)."""
    lines = []
    exp = TopExp_Explorer(model.shape, TopAbs_EDGE)
    while exp.More():
        curve = BRepAdaptor_Curve(TopoDS.Edge(exp.Current()))
        u0, u1 = curve.FirstParameter(), curve.LastParameter()
        pts = []
        for i in range(samples + 1):
            p = curve.Value(u0 + (u1 - u0) * i / samples)
            pts.append((p.X(), p.Y(), p.Z()))
        lines.append(pts)
        exp.Next()
    return lines


def translate(shape, dx, dy, dz):
    t = gp_Trsf()
    t.SetTranslation(gp_Vec(dx, dy, dz))
    return BRepBuilderAPI_Transform(shape, t, True).Shape()
