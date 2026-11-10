"""Synthetic engineering documents for the demonstration dataset.

All documents are drafts marked "SAMPLE - NOT FOR MANUFACTURING". Inspection reports and the material test
certificate are blank templates: they list required characteristics and tests but contain no measured values,
no results, no signatures and no approval or certification statements.
"""
from __future__ import annotations

from .pdf import A4_LANDSCAPE, Document

NAVY = (0.08, 0.16, 0.30)
GREY = (0.35, 0.38, 0.42)
NOTE = ("This document is a synthetic sample created to demonstrate the Digital Passport software. It is not an "
        "approved engineering document and must not be used for manufacturing, inspection or certification.")


def _doc(title, number, rev, client, part, size=None):
    kw = {"size": size} if size else {}
    return Document(title, number, rev, client.name, f"{part.number} {part.name}", **kw)


def _section(page, y, title):
    page.text(36, y, title, size=11, bold=True, color=NAVY)
    page.line(36, y - 4, page.w - 36, y - 4, width=0.4, color=(0.7, 0.72, 0.76))
    return y - 20


def _size_text(model) -> str:
    x, y, z = model.size
    return f"{x:.1f} x {y:.1f} x {z:.1f} mm"


# ---- drawing ----------------------------------------------------------------------------------------------------

def drawing(client, part, model, edges, rev="A") -> bytes:
    """General-arrangement drawing sheet: three orthographic wireframe views projected from the B-rep edges."""
    d = _doc("Engineering drawing (general arrangement)", f"{part.number}-DRG", rev, client, part, size=A4_LANDSCAPE)
    p, top = d.new_page()
    x0, y0, z0, x1, y1, z1 = model.bbox
    views = [("FRONT VIEW (X-Z)", lambda q: (q[0], q[2]), (x0, z0, x1, z1)),
             ("TOP VIEW (X-Y)", lambda q: (q[0], q[1]), (x0, y0, x1, y1)),
             ("SIDE VIEW (Y-Z)", lambda q: (q[1], q[2]), (y0, z0, y1, z1))]
    cell_w, cell_h = (p.w - 72 - 20) / 3, top - 190
    span = max(x1 - x0, y1 - y0, z1 - z0) or 1
    scale = min(cell_w, cell_h) * 0.78 / span
    for i, (label, proj, (a0, b0, a1, b1)) in enumerate(views):
        cx = 36 + i * (cell_w + 10)
        p.rect(cx, 170, cell_w, cell_h, stroke=(0.6, 0.62, 0.66), width=0.4)
        p.text(cx + 6, 170 + cell_h - 14, label, size=8, bold=True, color=GREY)
        ox = cx + cell_w / 2 - (a0 + a1) / 2 * scale
        oy = 170 + cell_h / 2 - (b0 + b1) / 2 * scale - 6
        for poly in edges:
            p.polyline([(ox + proj(q)[0] * scale, oy + proj(q)[1] * scale) for q in poly], width=0.45, color=(0.1, 0.1, 0.12))
        # overall dimension lines
        ya = oy + b0 * scale - 14
        p.line(ox + a0 * scale, ya, ox + a1 * scale, ya, width=0.4, color=(0.1, 0.3, 0.7))
        p.text(ox + (a0 + a1) / 2 * scale - 14, ya - 10, f"{a1 - a0:.1f}", size=7.5, color=(0.1, 0.3, 0.7))
        xa = ox + a1 * scale + 10
        p.line(xa, oy + b0 * scale, xa, oy + b1 * scale, width=0.4, color=(0.1, 0.3, 0.7))
        p.text(xa + 3, oy + (b0 + b1) / 2 * scale, f"{b1 - b0:.1f}", size=7.5, color=(0.1, 0.3, 0.7))
    # title block
    rows = [["Part number", part.number, "Material (original)", part.material, "Scale", "NTS"],
            ["Description", part.name, "Proposed AM material", part.proposed, "Units", "mm"],
            ["Overall size", _size_text(model), "General tolerance", "ISO 2768-mK (sample)", "Sheet", "1 / 1"],
            ["Drawn by", "Demo generator", "Checked / approved", "Not checked - not approved", "Revision", rev]]
    p.table(36, 160, [85, 160, 105, 190, 60, p.w - 72 - 600], rows, size=7.5, header=False, min_row=13)
    p.text(36, 58, "Wireframe projection generated from the synthetic STEP model; hidden lines are shown. " + NOTE[:110] + "...", size=7, color=GREY)
    return d.build()


# ---- manufacturing specification ----------------------------------------------------------------------------------

def specification(client, part, model, content, rev="A", change_note="") -> bytes:
    rl1, rl2 = content.get("rl1", {}), content.get("rl2", {})
    spec = rl2.get("manufacturing_spec", {})
    d = _doc("Manufacturing specification", f"{part.number}-MTS", rev, client, part)
    p, y = d.new_page()
    y = _section(p, y, "1. Scope")
    y = p.paragraph(36, y, f"This specification describes the proposed additive manufacturing route for the spare part "
                           f"{part.number} ({part.name}) used in: {part.application}. {NOTE}", p.w - 72, size=9.5)
    y = _section(p, y - 8, "2. Part identification")
    y = p.table(36, y, [170, p.w - 72 - 170], [
        ["Field", "Value"], ["Part number", part.number], ["Description", part.name],
        ["Equipment reference", part.equipment or "-"], ["Overall size", _size_text(model)],
        ["Original material", rl1.get("original_material_grade", part.material)],
        ["Proposed material", f"{part.proposed} ({rl2.get('material_category', '-')})"],
        ["Reason for proposal", rl1.get("proposed_material_reason", "-")],
        ["Criticality (AMSL, provisional)", rl2.get("criticality_amsl", "-")],
        ["Operating conditions", f"{rl1.get('motion', '-')}, {('rpm ' + rl1['rpm']) if rl1.get('rpm') else 'no rotation'}, {rl1.get('atmosphere', '-')}"],
    ], size=9)
    y = _section(p, y - 14, "3. Manufacturing solution")
    p.paragraph(36, y, rl2.get("manufacturing_solution", "-"), p.w - 72, size=9.5)

    p, y = d.new_page()
    y = _section(p, y, "4. Build and process parameters (BR-026, BR-041)")
    rows = [["Parameter", "Value"]] + [[k.replace("_", " ").capitalize(), str(spec.get(k, "-"))] for k in (
        "job_number", "material", "feedstock", "machine", "layer_thickness", "support_strategy", "build_orientation",
        "inert_gas", "heat_treatment", "post_processing", "machining", "printing_hours", "post_processing_hours")]
    y = p.table(36, y, [170, p.w - 72 - 170], rows, size=9)
    y = _section(p, y - 14, "5. Process parameter set (sample)")
    y = p.table(36, y, [200, 120, p.w - 72 - 320], [["Parameter", "Value", "Unit"]] +
                [[r["name"], r["value"], r["unit"]] for r in spec.get("process_parameters", [])], size=9)

    p, y = d.new_page()
    y = _section(p, y, "6. Acceptance criteria (requirements only - no results)")
    y = p.table(36, y, [110, 110, 70, 140, p.w - 72 - 430], [["Property", "Requirement", "Unit", "Standard", "Result"]] +
                [[r["property"], r["requirement"], r["unit"], r["standard"], "Not tested"] for r in rl2.get("mechanical_acceptance", [])], size=9)
    y = p.table(36, y - 12, [170, p.w - 72 - 170], [["Item", "Requirement"],
                ["Dimensional tolerances", rl2.get("dimensional_tolerances", "-")], ["NDT", rl2.get("ndt", "-")],
                ["Inspection and test plan", rl2.get("inspection_test_plan", "-")],
                ["Material test certificate", "Required" if rl2.get("mtc_required") else "Not required"],
                ["Test coupons", rl2.get("test_coupons", "-")], ["Applicable standards", rl2.get("applicable_standards", "-")]], size=9)
    y = _section(p, y - 14, "7. Revision record")
    p.table(36, y, [60, 120, p.w - 72 - 180], [["Rev", "Status", "Change"],
            ["A", "Draft", "First issue for passport data capture (sample)."]] +
            ([[rev, "Draft", change_note]] if rev != "A" else []), size=9)
    return d.build()


# ---- inspection and test plan (also R-L3 evidence "itp") ---------------------------------------------------------

def itp(client, part, content, rev="A") -> bytes:
    rl2 = content.get("rl2", {})
    d = _doc("Inspection and test plan (ITP)", f"{part.number}-ITP", rev, client, part)
    p, y = d.new_page()
    p.paragraph(36, y, "Legend: H = hold point, W = witness point, R = record review. Responsible and sign-off columns "
                       "are intentionally blank in this sample; no inspection has been performed. " + NOTE, p.w - 72, size=8.5)
    steps = [
        ("1", "Feedstock receipt", "Certificate review, lot traceability", "Lot matches specification", "R"),
        ("2", "Build preparation", "Build file and orientation check", "Per manufacturing specification", "H"),
        ("3", "Build", "Machine log review, coupon placement", f"{rl2.get('test_coupons', 'Coupons per specification')}", "R"),
        ("4", "Heat treatment", "Furnace chart review", rl2.get("manufacturing_spec", {}).get("heat_treatment", "-"), "R"),
        ("5", "Support removal and machining", "Visual, dimensional check of machined features", rl2.get("dimensional_tolerances", "-"), "W"),
        ("6", "Non-destructive testing", rl2.get("ndt", "-"), "No relevant indications", "H"),
        ("7", "Mechanical testing of coupons", "Tensile, yield, elongation, hardness", "Per acceptance table in specification", "H"),
        ("8", "Final dimensional inspection", "CMM or gauges", "Per drawing", "H"),
        ("9", "Documentation review", "Records complete and linked to passport", "All records present", "H"),
    ]
    p.table(36, y - 46, [22, 105, 140, 140, 28, 45, p.w - 72 - 480], [["#", "Activity", "Method", "Acceptance", "Point", "Responsible", "Sign-off"]] +
            [[a, b, c, e, f, "", ""] for a, b, c, e, f in steps], size=8)
    return d.build()


def work_instruction(client, part, content, rev="A") -> bytes:
    spec = content.get("rl2", {}).get("manufacturing_spec", {})
    d = _doc("Manufacturing work instruction", f"{part.number}-WI", rev, client, part)
    p, y = d.new_page()
    y = p.paragraph(36, y, NOTE, p.w - 72, size=8.5) - 8
    steps = [
        ("Prepare build file", f"Load the approved build file for job {spec.get('job_number', '-')}. Confirm layer thickness "
                               f"{spec.get('layer_thickness', '-')} and orientation: {spec.get('build_orientation', '-')}."),
        ("Machine set-up", f"Machine: {spec.get('machine', '-')}. Inert gas: {spec.get('inert_gas', '-')}. Verify oxygen level before start."),
        ("Feedstock", f"Use feedstock {spec.get('feedstock', '-')}. Record the lot number on the build record."),
        ("Supports", spec.get("support_strategy", "-")),
        ("Build", "Start the build and monitor the machine log. Record start and end times and any interruptions."),
        ("Heat treatment", spec.get("heat_treatment", "-")),
        ("Post-processing", spec.get("post_processing", "-")),
        ("Machining", spec.get("machining", "-")),
        ("Hand-over to inspection", "Transfer the part and coupons to inspection with the build record. Do not release."),
    ]
    for i, (title, body) in enumerate(steps, 1):
        if y < 120:
            p, y = d.new_page()
        p.text(36, y, f"Step {i}. {title}", size=10, bold=True, color=NAVY)
        y = p.paragraph(48, y - 14, body, p.w - 96, size=9.5) - 8
    return d.build()


# ---- other R-L3 evidence documents (templates and descriptions; no results) ---------------------------------------

def machine_details(client, part, content, rev="A") -> bytes:
    spec = content.get("rl2", {}).get("manufacturing_spec", {})
    d = _doc("Manufacturing machine details", f"{part.number}-MCH", rev, client, part)
    p, y = d.new_page()
    y = p.paragraph(36, y, NOTE, p.w - 72, size=8.5) - 8
    p.table(36, y, [180, p.w - 72 - 180], [["Item", "Value (sample)"],
            ["Machine type", spec.get("machine", "-")], ["Process", "Laser powder bed fusion (L-PBF)"],
            ["Build volume", "250 x 250 x 300 mm (sample)"], ["Laser", "Single fibre laser, 400 W class (sample)"],
            ["Inert gas", spec.get("inert_gas", "-")], ["Layer thickness used", spec.get("layer_thickness", "-")],
            ["Machine qualification status", "Not recorded - sample document"], ["Calibration records", "Not attached - sample document"]], size=9)
    return d.build()


def print_orientation(client, part, model, edges, content, rev="A") -> bytes:
    spec = content.get("rl2", {}).get("manufacturing_spec", {})
    d = _doc("Print orientation document", f"{part.number}-ORI", rev, client, part)
    p, y = d.new_page()
    y = p.paragraph(36, y, f"Proposed build orientation: {spec.get('build_orientation', '-')}. Supports: "
                           f"{spec.get('support_strategy', '-')}. {NOTE}", p.w - 72, size=9) - 10
    x0, _, z0, x1, _, z1 = model.bbox
    box_w, box_h = p.w - 72, 330
    p.rect(36, y - box_h, box_w, box_h, stroke=(0.6, 0.62, 0.66), width=0.4)
    scale = min(box_w, box_h) * 0.62 / (max(x1 - x0, z1 - z0) or 1)
    ox = 36 + box_w / 2 - (x0 + x1) / 2 * scale
    plate = y - box_h + 40
    oy = plate - z0 * scale
    p.rect(36 + 40, plate - 10, box_w - 80, 10, fill=(0.75, 0.77, 0.80), stroke=None)
    p.text(36 + 46, plate - 24, "Build plate", size=8, color=GREY)
    for poly in edges:
        p.polyline([(ox + q[0] * scale, oy + q[2] * scale) for q in poly], width=0.45)
    p.line(36 + box_w - 40, plate, 36 + box_w - 40, plate + 120, width=1.2, color=(0.7, 0.13, 0.13))
    p.text(36 + box_w - 90, plate + 128, "Build direction +Z", size=8, bold=True, color=(0.7, 0.13, 0.13))
    return d.build()


def dimensional_inspection_template(client, part, model, rev="A") -> bytes:
    sx, sy, sz = model.size
    d = _doc("Dimensional inspection report - TEMPLATE", f"{part.number}-DIR", rev, client, part)
    p, y = d.new_page()
    y = p.paragraph(36, y, "TEMPLATE ONLY. No part has been inspected. Measured values are intentionally empty. " + NOTE, p.w - 72, size=8.5) - 8
    chars = [("Overall length / diameter (X)", f"{sx:.1f}", "± 0.3"), ("Overall width (Y)", f"{sy:.1f}", "± 0.3"),
             ("Overall height (Z)", f"{sz:.1f}", "± 0.3"), ("Main bore", "per drawing", "H7"),
             ("Bolt circle / hole positions", "per drawing", "± 0.2"), ("Surface roughness, functional faces", "Ra 3.2", "max")]
    p.table(36, y, [24, 190, 80, 60, 80, p.w - 72 - 434], [["#", "Characteristic", "Nominal", "Tolerance", "Measured", "Status"]] +
            [[str(i), c, n, t, "", "Not inspected"] for i, (c, n, t) in enumerate(chars, 1)], size=8.5)
    return d.build()


def mtc_template(client, part, content, rev="A") -> bytes:
    rl2 = content.get("rl2", {})
    d = _doc("Material test certificate - TEMPLATE (no results)", f"{part.number}-MTC", rev, client, part)
    p, y = d.new_page()
    y = p.paragraph(36, y, "TEMPLATE ONLY - THIS IS NOT A CERTIFICATE. It lists the tests the specification requires. "
                           "No material has been tested, no results are recorded and nothing is certified or signed. " + NOTE,
                    p.w - 72, size=9, bold=False) - 10
    p.table(36, y, [110, 110, 70, 140, p.w - 72 - 430], [["Property", "Requirement", "Unit", "Standard", "Result"]] +
            [[r["property"], r["requirement"], r["unit"], r["standard"], "No result - not tested"] for r in rl2.get("mechanical_acceptance", [])], size=9)
    return d.build()
