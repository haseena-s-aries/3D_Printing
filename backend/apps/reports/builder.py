"""Report content and HTML (CN-005 approved layout).

Source marks (never upgraded by printing):
  V  verified: value from an APPROVED passport revision (and not an unverified client value)
  D  draft: value from a revision that is not approved, or Aries-entered master data not yet in an approved revision
  C  client-submitted: client value not verified by Aries (part provenance or R-L1 value_sources)
  M  missing: not recorded; printed as "Not recorded", never filled in
Client variant (R3): identification, materials, dimensions, CAD views, quality requirements, permitted document
references. Never: BR-026 manufacturing specification, BR-041 process parameters, manufacturing solution or process,
job numbers or job sheets, engineering notes, original STEP/DWG files.
"""
import hashlib
import html
import json

from apps.files.models import EngineeringFile
from apps.parts.models import SparePart
from apps.passports.content import RL3_EVIDENCE, completeness
from apps.passports.models import PassportRevision

WATERMARK = "DRAFT — NOT APPROVED FOR MANUFACTURING"
LEGEND = [("V", "Verified (approved passport revision)"), ("D", "Draft (not approved)"),
          ("C", "Client-submitted (not verified by Aries)"), ("M", "Missing (not recorded)")]
E = html.escape

RL1_LABELS = [("original_material_grade", "Original material grade"), ("material_identification_method", "Material identification"),
              ("proposed_material", "Proposed material"), ("proposed_material_reason", "Reason for proposed material")]
RL1_CONTEXT = [("part_size", "Part size"), ("atmosphere", "Atmosphere"), ("operating_environment", "Operating environment"),
               ("motion", "Static or rotating"), ("rpm", "RPM"), ("ip_status", "IP consideration"),
               ("cad_3d_available", "3D CAD file available"), ("drawings_2d_available", "2D drawings available"),
               ("technical_description", "Technical description")]
CHOICE_TEXT = {"pmi": "PMI", "destructive": "Destructive", "oem": "OEM datasheet", "corrosive": "Corrosive",
               "non_corrosive": "Non-corrosive", "static": "Static", "rotating": "Rotating", "obsolete": "Obsolete", "active": "Active",
               "equivalent": "Equivalent", "superior": "Superior"}
QUALITY = [("applicable_standards", "Applicable standards"), ("dimensional_tolerances", "Dimensional tolerances"), ("ndt", "NDT"),
           ("mtc_required", "Material test certificate required"), ("test_coupons", "Test coupons"),
           ("inspection_test_plan", "Inspection and test plan (reference)")]
SPEC = [("material", "Material"), ("feedstock", "Feedstock"), ("machine", "Machine"), ("layer_thickness", "Layer thickness"),
        ("support_strategy", "Support strategy"), ("build_orientation", "Build orientation"), ("inert_gas", "Inert gas"),
        ("heat_treatment", "Heat treatment"), ("post_processing", "Post-processing"), ("machining", "Machining"),
        ("printing_hours", "Printing hours"), ("post_processing_hours", "Post-processing hours")]
EVIDENCE_NAMES = {"itp": "Inspection and test plan", "machine_details": "Manufacturing machine details",
                  "print_orientation": "Print orientation document", "dimensional_inspection": "Dimensional inspection report",
                  "material_test_certificate": "Material test certificate"}
CATEGORY_NAMES = dict(EngineeringFile.Category.choices)
PROPERTY_NAMES = {"tensile": "Tensile strength", "yield": "Yield strength", "elongation": "Elongation", "hardness": "Hardness",
                  "impact": "Impact", "other": "Other"}


def _filled(v) -> bool:
    return v not in (None, "", [], {})


def _text(v) -> str:
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, float):
        return f"{v:g}"
    return CHOICE_TEXT.get(v, str(v)) if isinstance(v, str) else str(v)


def collect(passport, revision: PassportRevision, variant: str, tenant_name: str, attachments: list, views: dict) -> dict:
    """The data printed in the report; also hashed as the report's content fingerprint."""
    part: SparePart = passport.part
    approved = revision.status == PassportRevision.Status.APPROVED
    content = revision.content or {}
    rl1, rl2 = content.get("rl1") or {}, content.get("rl2") or {}
    na = rl1.get("not_applicable") or {}
    sources = rl1.get("value_sources") or {}
    prov = part.field_provenance or {}

    def mark(value, client=False) -> str:
        if not _filled(value):
            return "M"
        if client:
            return "C"
        return "V" if approved else "D"

    def part_row(label, field, value, show=None):
        p = prov.get(field) or {}
        return [label, _text(show if show is not None else value) if _filled(value) else "Not recorded",
                mark(value, client=p.get("source") == "client" and not p.get("verified_by"))]

    def rl1_row(key, label):
        if key in na:
            return [label, f"Not applicable: {na[key]}", "V" if approved else "D"]
        v = rl1.get(key)
        return [label, _text(v) if _filled(v) else "Not recorded", mark(v, client=sources.get(key) == "client_submitted")]

    def rl2_row(key, label, data=rl2):
        v = data.get(key)
        return [label, _text(v) if _filled(v) else "Not recorded", mark(v)]

    ident = [part_row("Part number", "part_number", part.part_number), part_row("Part name", "name", part.name),
             part_row("Equipment / machinery", "equipment_reference", part.equipment_reference),
             part_row("Manufacturer / OEM", "manufacturer", part.manufacturer), part_row("Application", "application", part.application),
             part_row("Category", "category", part.category, part.get_category_display()),
             ["Criticality", part.get_criticality_display() if part.criticality != "unknown" else "Not assessed",
              "M" if part.criticality == "unknown" else ("V" if approved else "D")]]
    material = [rl1_row(k, label) for k, label in RL1_LABELS]
    if _filled(rl1.get("proposed_material")) or part.proposed_material:
        material.append(["Material suitability", "Not assessed by Aries Engineering", "M"])
    data = {
        "variant": variant, "tenant": tenant_name, "project": f"{part.project.code} · {part.project.name}" if part.project_id else "",
        "passport": passport.passport_number, "revision": revision.revision_number, "revision_status": revision.get_status_display(),
        "approved": approved, "publication": passport.get_publication_state_display(),
        "evidence": "Not assessed" if passport.evidence_level == "none" else passport.evidence_level,
        "eligibility": passport.get_manufacturing_eligibility_display(),
        "identification": ident, "material": material, "context": [rl1_row(k, label) for k, label in RL1_CONTEXT],
        "quality": [rl2_row(k, label) for k, label in QUALITY],
        "acceptance": [[PROPERTY_NAMES.get(r.get("property", ""), r.get("property", "")), r.get("requirement") or "Not recorded", r.get("unit", ""), r.get("standard", ""),
                        r.get("frequency") or "Not recorded", "V" if approved else "D"] for r in (rl2.get("mechanical_acceptance") or [])],
        "completeness": {k: [v["done"], v["total"]] for k, v in completeness(content).items()},
        "documents": documents(passport, rl2, content, attachments, client_only=variant == "client"),
        "attachments": _attachment_rows(attachments),
        "views": {k: v.get("label", "") for k, v in views.items()},
    }
    if variant == "internal":  # Aries-confidential sections (R3); never in the client variant
        spec = rl2.get("manufacturing_spec") or {}
        from .mts import collect_mts

        data["mts"] = collect_mts(part, revision, rl2, spec, approved, attachments)
        data["spec"] = [rl2_row("job_number", "Job number (passport specification)", spec)] + [rl2_row(k, label, spec) for k, label in SPEC]
        data["process"] = rl2_row("manufacturing_process", "Manufacturing process")
        data["params"] = [[p.get("name", ""), p.get("value", ""), p.get("unit", ""), "V" if approved else "D"]
                          for p in (spec.get("process_parameters") or [])]
        data["solution"] = rl2_row("manufacturing_solution", "Manufacturing solution")
    return data


def documents(passport, rl2, content, attachments, client_only: bool = False) -> list:
    evidence = (content.get("rl3") or {}).get("evidence") or {}
    roles = {}
    for key in RL3_EVIDENCE:
        if evidence.get(key):
            roles.setdefault(str(evidence[key]), []).append(EVIDENCE_NAMES[key])
    attached = {str(a["file"]) for a in attachments}
    files = (EngineeringFile.objects.filter(tenant=passport.tenant, part=passport.part)
             | EngineeringFile.objects.filter(tenant=passport.tenant, passport=passport)).distinct().order_by("category", "title")
    if client_only:  # CN-005: a client-facing report never names a document the client may not see
        files = files.filter(client_visible=True)
    rows = []
    for f in files:
        v = f.versions.order_by("-version_number").first()
        if v is None:
            continue
        rows.append([CATEGORY_NAMES.get(f.category, f.category), f.title, f.kind.upper(), f"v{v.version_number}",
                     v.created_at.strftime("%d %b %Y"), f"{v.sha256[:8]}…{v.sha256[-4:]}", ", ".join(roles.get(str(f.pk), [])),
                     "Attached" if str(f.pk) in attached else "Reference only"])
    for key in RL3_EVIDENCE:
        if not evidence.get(key):
            rows.append([EVIDENCE_NAMES[key] + " (R-L3)", "Not linked", "", "", "", "", "", "Missing"])
    return rows


def _attachment_rows(attachments: list) -> list:
    from .mts import attachment_rows

    return attachment_rows(attachments)


def fingerprint(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


CSS = """
* { box-sizing: border-box; } body { font: 9.5pt/1.35 "Segoe UI", Arial, sans-serif; color: #1d2433; margin: 0; }
section { break-inside: avoid; }
.wm { position: fixed; top: 46%; left: 50%; transform: translate(-50%, -50%) rotate(-30deg); font-size: 19pt; font-weight: 800;
  color: rgba(200,40,40,.13); white-space: nowrap; z-index: 0; }
header { display: grid; grid-template-columns: 30mm minmax(0,1fr) 70mm; border: 1px solid #1d2433; }
header > div { padding: 6px 8px; } .brand { background: #1f3a5f; color: #fff; font-weight: 700; font-size: 13pt; display: flex; align-items: center; }
.title { font-size: 13pt; font-weight: 700; display: flex; flex-direction: column; align-items: center; justify-content: center; background: #e7edf5; text-align: center; }
.title small { font-size: 8.5pt; font-weight: 600; color: #8a1c15; } .meta { font-size: 8pt; border-left: 1px solid #1d2433; }
.meta b { display: inline-block; width: 18mm; }
.status { margin: 6px 0; padding: 6px 8px; border: 1.5px solid #b3261e; color: #8a1c15; background: #fdecea; font-weight: 600; }
.status.ok { border-color: #1c6b34; color: #1c6b34; background: #e6f4ea; } .status small { font-weight: 400; display: block; }
.conf { margin: 6px 0; padding: 5px 8px; background: #1d2433; color: #fff; font-weight: 700; }
h2 { font-size: 10.5pt; margin: 10px 0 4px; padding: 3px 6px; background: #cfe3ef; border-left: 4px solid #1f3a5f; }
table { width: calc(100% - 1px); border-collapse: collapse; table-layout: fixed; } th, td { border: 1px solid #b8c2d0; padding: 3px 6px; vertical-align: top; text-align: left; overflow-wrap: break-word; hyphens: auto; }
table.docs { font-size: 8pt; } table.docs td, table.docs th { padding: 3px 4px; }
th { width: 42%; background: #f4f6f9; font-weight: 600; } td.m { width: 9mm; text-align: center; } td.missing, span.missing { color: #8a5a00; font-style: italic; }
.grid2 { display: grid; grid-template-columns: minmax(0,1fr) minmax(0,1fr); gap: 8px; } .wide th { width: auto; }
.views { display: grid; grid-template-columns: repeat(3, minmax(0,1fr)); gap: 6px; }
.frame { height: 44mm; border: 1px solid #b8c2d0; display: flex; align-items: center; justify-content: center; text-align: center; background: #fff; padding: 2px; }
.frame img { max-width: 100%; max-height: 100%; } .frame.na { color: #8a5a00; font-style: italic; background: #fafbfd; border-style: dashed; }
.cap { text-align: center; font-size: 8pt; margin-top: 2px; }
.mk { display: inline-block; min-width: 4.5mm; border-radius: 2px; font-size: 7.5pt; font-weight: 700; text-align: center; }
.mk-V { background: #d9f2df; color: #1c6b34; } .mk-D { background: #fff0cc; color: #8a5a00; } .mk-C { background: #fde2d0; color: #8a3b00; } .mk-M { background: #eceff3; color: #5a677a; }
.legend { font-size: 8pt; margin-top: 4px; } .legend span { margin-right: 10px; white-space: nowrap; }
.notice { font-size: 8.5pt; border: 1px solid #b8c2d0; padding: 6px 8px; background: #f7f9fc; }
.bar { display: inline-block; height: 6px; background: #d5dbe4; width: 26mm; vertical-align: middle; } .bar > i { display: block; height: 100%; background: #3f6fb0; }
"""


def mark_html(m: str) -> str:
    title = dict(LEGEND)[m]
    return f'<span class="mk mk-{m}" title="{E(title)}">{m}</span>'


def _rows(rows) -> str:
    return "".join(f'<tr><th>{E(label)}</th><td class="{"missing" if m == "M" else ""}">{E(value)}</td><td class="m">{mark_html(m)}</td></tr>'
                   for label, value, m in rows)


def _kv(label, value, m=None, marks=True) -> str:
    """One label/value(/mark) group of cells in the framed (MTS-style) layout."""
    cls = "c missing" if m == "M" or value in ("Not recorded", "Not linked") else "c"
    if not marks:
        return f'<td class="k">{E(label)}</td><td class="{cls}" colspan="2">{E(value)}</td>'
    return f'<td class="k">{E(label)}</td><td class="{cls}">{E(value)}</td><td class="m">{mark_html(m) if m else ""}</td>'


def _pairs(left: list, right: list) -> str:
    """Two label/value lists side by side (left: label, value, mark; right: label, value[, mark]). The shorter side ends
    in one merged blank cell instead of empty label/value rows."""
    cols = ('<colgroup><col style="width:19%"><col style="width:24%"><col style="width:7%"><col style="width:19%"><col style="width:24%">'
            '<col style="width:7%"></colgroup>')
    n = max(len(left), len(right))

    def side(items, i):
        if i < len(items):
            it = items[i]
            return _kv(it[0], it[1], it[2] if len(it) > 2 else None, marks=len(it) > 2)
        if i == len(items):
            return f'<td class="blank" colspan="3" rowspan="{n - len(items)}"></td>'
        return ""
    rows = "".join(f"<tr>{side(left, i)}{side(right, i)}</tr>" for i in range(n))
    return f'<table class="grid">{cols}{rows}</table>'


def _single(rows: list) -> str:
    cols = '<colgroup><col style="width:32%"><col><col style="width:7%"></colgroup>'
    return f'<table class="grid">{cols}{"".join(f"<tr>{_kv(label, value, m)}</tr>" for label, value, m in rows)}</table>'


def _hdr(headers: list) -> str:
    return f'<tr class="hdr">{"".join(f"<th>{E(h)}</th>" for h in headers)}</tr>'


PASSPORT_CSS = """
.mts-frame .bar2 { font-size: 9.5pt; }
.mts-frame td.blank { background: #fff; }
.mts-frame td.m { width: auto; text-align: center; padding: 3px 2px; }
.mts-frame > .conf, .mts-frame > .status { margin: 0; border: 0; border-bottom: 1px solid #1d2433; }
.mts-frame > .note { font-size: 8.5pt; padding: 5px 6px; background: #f7f9fc; border-top: 1px solid #1d2433; }
.mts-frame > .note.first { border-top: 0; }
.mts-frame table.docs td, .mts-frame table.docs th { font-size: 8pt; padding: 3px 4px; }
.mts-title small { display: block; font-size: 7.5pt; font-weight: 600; color: #8a1c15; margin-top: 2px; }
.mts-title { flex-direction: column; }
.views3 .v { flex-direction: column; } .views3 .v .vi { flex: 1 1 auto; min-height: 0; display: flex; align-items: center; justify-content: center; }
.views3 .v .vi img { max-width: 100%; max-height: 100%; } .views3 .cap { font-size: 8pt; font-style: normal; color: #1d2433; margin-top: 2px; }
.mts-frame .bar { display: inline-block; height: 6px; background: #d5dbe4; width: 22mm; vertical-align: middle; }
.wm { position: fixed; top: 46%; left: 50%; transform: translate(-50%, -50%) rotate(-30deg); font-size: 19pt; font-weight: 800;
  color: rgba(200,40,40,.13); white-space: nowrap; z-index: 0; }
"""


def render_html(data: dict, meta: dict, view_images: dict, branding: dict) -> str:
    """Standard (client) and Aries-internal Digital Passport report, in the framed layout of the MTS template (same
    header, logo, line weights, tables and footer); the content is unchanged."""
    from .mts import ATTACH_NOTE, MTS_CSS, logo_data_uri

    internal = data["variant"] == "internal"
    approved = data["approved"]
    hr = '<div class="hr"></div>'
    views_html = '<div class="vsep"></div>'.join(
        f'<div class="v"><div class="vi"><img src="{view_images[n]}" alt="{label} view"></div><div class="cap">{label} view</div></div>'
        if n in view_images else
        f'<div class="v na"><div class="vi">View not available<br>{E(data["views"].get(n) or "")}</div><div class="cap">{label} view</div></div>'
        for n, label in (("front", "Front"), ("top", "Top"), ("iso", "Isometric")))
    status = (f'<div class="status ok">Passport revision {data["revision"]} is APPROVED.<small>This report is not a manufacturing '
              f'authorisation. {E(data["eligibility"])}.</small></div>') if approved else (
        f'<div class="status">Passport revision {data["revision"]} is not approved ({E(data["revision_status"])}). '
        f'It is not verified by QA.<small>{WATERMARK}. This report is not a manufacturing authorisation, not a QA certificate and '
        f'not a material certificate. Evidence level: {E(data["evidence"])}. {E(data["eligibility"])}. Values marked D, C or M '
        f'are not verified engineering data.</small></div>')
    info = [("Client company", data["tenant"]), ("Project", data["project"] or "No project"), ("Passport number", data["passport"]),
            ("Passport revision", f'rev {data["revision"]} · {data["revision_status"]}'), ("Publication", data["publication"]),
            ("Evidence level", data["evidence"]), ("Manufacturing", data["eligibility"]),
            ("Generated", meta["generated"]), ("By", meta["by_role"])]
    logo = logo_data_uri()
    brand = (f'<img src="{logo}" alt="{E(branding["name"])}">' if logo else f'<span class="txt">{E(branding["name"])}</span>')
    out = [f'<!doctype html><html><head><meta charset="utf-8"><style>{CSS}{MTS_CSS}{PASSPORT_CSS}</style></head><body class="mts">']
    if internal:
        out.append('<div class="wm-conf">CONFIDENTIAL</div>')
    if not approved:
        out.append(f'<div class="wm"{" style=\"top:80%\"" if internal else ""}>{WATERMARK}</div>')
    out.append(
        f'<div class="mts-frame">{hr}<div class="mts-head"><div class="mts-brand">{brand}</div>'
        f'<div class="mts-title">Digital Passport Report<small>{"Aries internal · confidential" if internal else "Client-facing"}</small></div>'
        f'<div class="mts-doc"><table><colgroup><col style="width:62%"><col></colgroup>'
        f'<tr><td><b>Document No.</b></td><td><b>Revision No</b></td></tr>'
        f'<tr><td class="num">{E(meta["number"])}</td><td>{data["revision"]}{"" if approved else " (draft)"}</td></tr></table></div></div>{hr}')
    if internal:
        out.append('<div class="conf">ARIES CONFIDENTIAL · contains manufacturing parameters · not for client or third-party distribution</div>')
    out.append(status + hr)
    out.append(f'<div class="bar2">1. Part identification</div>{_pairs(data["identification"], info)}{hr}')
    model_note = f'<div class="note">Views rendered from {E(meta["model"])}.</div>' if meta.get("model") else ""
    out.append(f'<div class="bar2">2. Model views</div><div class="views3">{views_html}</div>{model_note}{hr}')
    out.append(f'<div class="bar2">3. Material and dimensions</div>{_pairs(data["material"], data["context"])}{hr}')
    acc_cols = ('<colgroup><col style="width:21%"><col style="width:18%"><col style="width:10%"><col style="width:22%">'
                '<col style="width:22%"><col style="width:7%"></colgroup>')
    acc = "".join(f'<tr><td class="c">{E(a)}</td><td class="c{" missing" if b == "Not recorded" else ""}">{E(b)}</td><td class="c">{E(c)}</td>'
                  f'<td class="c">{E(st)}</td><td class="c{" missing" if f == "Not recorded" else ""}">{E(f)}</td><td class="m">{mark_html(m)}</td></tr>'
                  for a, b, c, st, f, m in data["acceptance"]) or '<tr><td colspan="6" class="c missing">No acceptance criteria recorded</td></tr>'
    out.append(f'<div class="bar2">4. Quality and acceptance requirements</div>{_single(data["quality"])}{hr}'
               f'<table class="acc">{acc_cols}{_hdr(["Mechanical property", "Requirement", "Unit", "Standard", "Inspection frequency", ""])}'
               f'{acc}</table>{hr}')
    n = 5
    if internal:
        p_cols = '<colgroup><col style="width:38%"><col style="width:30%"><col style="width:25%"><col style="width:7%"></colgroup>'
        params = "".join(f'<tr><td class="c">{E(a)}</td><td class="c">{E(b)}</td><td class="c">{E(c)}</td><td class="m">{mark_html(m)}</td></tr>'
                         for a, b, c, m in data["params"]) or '<tr><td colspan="4" class="c missing">No process parameters recorded</td></tr>'
        out.append(f'<div class="bar2">{n}. Manufacturing specification (BR-026) · Aries confidential</div>{_single([data["process"]] + data["spec"])}{hr}'
                   f'<table>{p_cols}{_hdr(["Process parameter (BR-041)", "Value", "Unit", ""])}{params}</table>{hr}'
                   f'<div class="bar2">{n + 1}. Manufacturing solution · Aries confidential</div>{_single([data["solution"]])}{hr}')
        n += 2
    d_cols = "<colgroup>" + "".join(f'<col style="width:{w}%">' for w in (21, 17, 6, 7, 10, 12, 9, 8, 10)) + "</colgroup>"
    docs = "".join(f'<tr><td>{E(a)}</td><td class="{"missing" if b == "Not linked" else ""}">{E(b)}</td><td>{E(c)}</td><td>{E(v)}</td>'
                   f'<td>{E(u)}</td><td>{E(h)}</td><td>{E(r)}</td><td>{"<span class=missing>Missing</span>" if st == "Missing" else E(st)}</td>'
                   f'<td>{"" if st == "Missing" else "Pending (OQ-35)"}</td></tr>' for a, b, c, v, u, h, r, st in data["documents"])
    out.append(f'<div class="bar2">{n}. Document references</div>'
               f'<table class="docs">{d_cols}{_hdr(["Document", "Title", "Type", "Version", "Uploaded", "SHA-256", "R-L3 evidence", "In report", "QA verification"])}'
               f'{docs}</table>'
               '<div class="note">Files are listed as references. Original STEP and DWG files are never attached; engineering notes and '
               f'job sheets are never included.</div>{hr}')
    a_cols = "<colgroup>" + "".join(f'<col style="width:{w}%">' for w in (5, 20, 37, 7, 15, 7, 9)) + "</colgroup>"
    rows = data.get("attachments") or []
    out.append(f'<div class="bar2">{n + 1}. Attached documents (in page order)</div>')
    if rows:
        body = "".join(f'<tr><td class="c">{o}</td><td>{E(c)}</td><td>{E(t)}</td><td class="c">{E(v)}</td><td>{E(h)}</td><td class="c">{pg}</td>'
                       f'<td class="c">{f}</td></tr>' for o, c, t, v, h, pg, f in rows)
        out.append(f'<table class="docs">{a_cols}{_hdr(["#", "Document class", "Title", "Version", "SHA-256", "Pages", "From page"])}{body}</table>'
                   f'<div class="note">{E(ATTACH_NOTE)}</div>{hr}')
    else:
        out.append(f'<div class="note first">No documents are attached to this report.</div>{hr}')
    n += 1
    comp = "".join(f'<td class="c"><b>{k.upper().replace("RL", "R-L")}</b> {a}/{b} <span class="bar"><i style="width:{round(100 * a / b) if b else 0}%"></i></span></td>'
                   for k, (a, b) in data["completeness"].items())
    out.append(f'<div class="bar2">{n + 1}. Data completeness (guidance only) and verification legend</div><table><tr>{comp}</tr></table>'
               f'<div class="note legend">{"".join(f"<span>{mark_html(m)} {E(t)}</span>" for m, t in LEGEND)}</div>'
               f'<div class="note">Content fingerprint {meta["fingerprint"][:16]}… · generated from passport {E(data["passport"])} rev {data["revision"]} '
               f'({E(data["revision_status"])}) · {"Aries-internal variant" if internal else "client-facing variant: excludes Aries manufacturing parameters, job numbers, job sheets and engineering notes"}. '
               f'External sharing is subject to the open IP and redistribution rules (OQ-33, OQ-38).</div>{hr}</div></body></html>')
    return "".join(out)


def footer(meta: dict, data: dict) -> str:
    """Same footer as the MTS template: "Page N", centred, Times New Roman."""
    from .mts import mts_footer

    return mts_footer(meta, data)
