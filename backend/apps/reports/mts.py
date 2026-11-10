"""Manufacturing & Test Specification template and the attached-documents index (CN-005 enhancement, 27 Oct 2026).

The MTS layout follows the structure of the supplied 8-page sample (header block with document number and revision,
title line, manufacturing-specification grid, three views, quantities, manufacturing process steps, inspection and
test specifications, CONFIDENTIAL stamp, attached documents after the body). It prints only values recorded in the
passport: missing values read "Not recorded" and are never filled in. The template is Aries-internal: it contains the
manufacturing specification and is never produced for clients. Job sheets and engineering notes are not included.
"""
import base64
from functools import lru_cache
from pathlib import Path

from django.conf import settings

from apps.files.models import EngineeringFile

from .builder import CATEGORY_NAMES, CSS, LEGEND, PROPERTY_NAMES, WATERMARK, E, _filled, _text, mark_html

ATTACH_NOTE = ("Attached documents are reproduced as uploaded. Attaching a certificate, test or inspection report does not mean "
               "Aries has verified it; verification and approval rules are pending (OQ-35).")


# Report-builder class names (same wording as the builder UI); other categories keep their file-category label.
CLASS_NAMES = {**CATEGORY_NAMES, "drawing": "Engineering drawing", "inspection": "QC / inspection report", "other": "Other supporting document"}


LOGO = Path(__file__).resolve().parent / "assets" / "aries_logo.png"


@lru_cache(maxsize=4)
def _logo_data_uri(path: str) -> str:
    """The logo as a data: URI (the renderer loads nothing from outside the HTML); blank when the file is missing."""
    try:
        return "data:image/png;base64," + base64.b64encode(Path(path).read_bytes()).decode("ascii")
    except OSError:
        return ""


def logo_data_uri() -> str:
    return _logo_data_uri(str(getattr(settings, "REPORT_LOGO_PATH", "") or LOGO))


def attachment_rows(attachments: list) -> list:
    return [[a["order"], CLASS_NAMES.get(a["category"], a["category"]), a["title"], f'v{a["version"]}',
             f'{a["sha256"][:8]}…{a["sha256"][-4:]}', a["pages"], a.get("first_page") or ""] for a in attachments]


def attachment_index(data: dict, heading: str) -> str:
    rows = data.get("attachments") or []
    if not rows:
        return f'<section><h2>{E(heading)}</h2><p class="notice">No documents are attached to this report.</p></section>'
    body = "".join(f"<tr><td>{o}</td><td>{E(c)}</td><td>{E(t)}</td><td>{E(v)}</td><td>{E(h)}</td><td>{p}</td><td>{f}</td></tr>"
                   for o, c, t, v, h, p, f in rows)
    cols = "".join(f'<col style="width:{w}%">' for w in (5, 20, 37, 7, 15, 7, 9))
    return (f'<section><h2>{E(heading)}</h2><table class="wide docs"><colgroup>{cols}</colgroup><tr><th>#</th><th>Document class</th>'
            f'<th>Title</th><th>Version</th><th>SHA-256</th><th>Pages</th><th>From page</th></tr>{body}</table>'
            f'<p class="notice">{E(ATTACH_NOTE)}</p></section>')


def company_location(tenant) -> str:
    """The client company's location from its profile (post-UAT D-08); blank when the profile has none."""
    return ", ".join(x for x in (tenant.address, tenant.city, tenant.state, tenant.country) if (x or "").strip())


def collect_mts(part, revision, rl2: dict, spec: dict, approved: bool, attachments: list) -> dict:
    def v(x):
        return [_text(x), "V" if approved else "D"] if _filled(x) else ["Not recorded", "M"]

    drawings = [a for a in attachments if a["category"] == EngineeringFile.Category.DRAWING]
    if drawings:
        dwg = ", ".join(f'{a["title"]} (v{a["version"]})' for a in drawings)
    else:
        f = (EngineeringFile.objects.filter(tenant=part.tenant, part=part, category=EngineeringFile.Category.DRAWING)
             .order_by("-updated_at").first())
        latest = f.versions.order_by("-version_number").first() if f else None
        dwg = f"{f.title} (v{latest.version_number})" if latest else ""
    process = rl2.get("manufacturing_process") or ""
    params = "; ".join(f'{p.get("name")}: {p.get("value", "")} {p.get("unit", "")}'.strip() for p in (spec.get("process_parameters") or []))
    printing = "; ".join(x for x in (spec.get("machine") and f'Machine: {spec["machine"]}',
                                     spec.get("layer_thickness") and f'Layer thickness: {spec["layer_thickness"]}',
                                     spec.get("inert_gas") and f'Inert gas: {spec["inert_gas"]}', params) if x)
    design = "; ".join(x for x in (spec.get("support_strategy") and f'Supports: {spec["support_strategy"]}',
                                   spec.get("build_orientation") and f'Orientation: {spec["build_orientation"]}') if x)
    tests = [[PROPERTY_NAMES.get(r.get("property", ""), r.get("property", "")) + " testing", r.get("standard") or "",
              " ".join(x for x in (r.get("requirement"), r.get("unit")) if x), r.get("frequency") or ""]
             for r in (rl2.get("mechanical_acceptance") or [])]
    if rl2.get("ndt"):
        tests.append(["Non-destructive testing", "", rl2["ndt"], ""])
    if rl2.get("dimensional_tolerances"):
        tests.append(["Dimensional inspection", rl2.get("inspection_test_plan") or "", rl2["dimensional_tolerances"], ""])
    return {
        "title": ("In this document manufacturing and testing requirements are mentioned to produce "
                  f"{part.name}" + (f" via {process}" if process else "") + "."),
        "grid": [("Job No", v(spec.get("job_number"))),
                 ("Revision", [f"Passport rev {revision.revision_number} ({revision.get_status_display()})", "V" if approved else "D"]),
                 ("Company name", v(getattr(settings, "REPORT_COMPANY_NAME", "") or part.tenant.name)),
                 ("Location", v(getattr(settings, "REPORT_COMPANY_LOCATION", "") or company_location(part.tenant))),
                 ("Part name", v(part.name)), ("Dwg No", v(dwg)),
                 ("3D printing technology", v(process)), ("Feedstock specification", v(spec.get("feedstock") or rl2.get("feedstock"))),
                 ("Applicable standards", v(rl2.get("applicable_standards"))), ("Substrate plate material", ["Not recorded (no passport field)", "M"])],
        "quantities": [("Part", ["Not recorded (job-specific; see the manufacturing job)", "M"]),
                       ("Test coupons / specimens", v(rl2.get("test_coupons")))],
        "process": [("Feedstock", v(spec.get("feedstock") or rl2.get("feedstock"))), ("Design for additive manufacturing", v(design)),
                    ("3D printing", v(printing)), ("Heat treatment", v(spec.get("heat_treatment"))),
                    ("Support removal and post-processing", v(spec.get("post_processing"))), ("Machining", v(spec.get("machining")))],
        "tests": tests,
    }


MTS_CSS = """
.mts-head { display: grid; grid-template-columns: 38mm minmax(0,1fr) 66mm; height: 40pt; border: 1px solid #1d2433; overflow: hidden; }
.mts-head > div { padding: 0 6px; display: flex; align-items: center; min-height: 0; }
.mts-brand { justify-content: center; border-right: 1px solid #1d2433; }
.mts-brand img { max-height: 32pt; max-width: 100%; display: block; }
.mts-brand .txt { font-weight: 800; font-size: 12pt; color: #b3261e; letter-spacing: .04em; }
.mts-title { justify-content: center; font-size: 10.5pt; white-space: nowrap; font-weight: 600; background: #d9d2e9; text-align: center; line-height: 1.1; }
.mts-doc { border-left: 1px solid #1d2433; padding: 0 !important; align-items: stretch !important; }
.mts .mts-doc table { width: 100%; height: 100%; border-collapse: collapse; table-layout: fixed; }
.mts .mts-doc td { border: 0; padding: 0 3px; text-align: center; vertical-align: middle; font-size: 7pt; line-height: 1; white-space: nowrap;
  overflow: hidden; height: 50%; }
.mts .mts-doc td + td { border-left: 1px solid #1d2433; } .mts .mts-doc tr + tr td { border-top: 1px solid #1d2433; }
.mts .mts-doc b { font-weight: 600; } .mts .mts-doc td.num { font-size: 6.5pt; }
.mts table { width: 100%; border-collapse: collapse; table-layout: fixed; }
.mts td, .mts th { border: 1px solid #1d2433; padding: 4px 6px; vertical-align: middle; width: auto; background: transparent; }
.bar2 { background: #b7dde8; font-weight: 600; padding: 4px 6px; border: 1px solid #1d2433; border-top: 0; }
.mts td.k { background: #fce4d6; width: 22%; font-weight: 600; } .mts tr.hdr th { background: #fce4d6; text-align: center; font-weight: 600; }
.mts td.c { text-align: center; } .titleline { border: 1px solid #1d2433; border-top: 0; padding: 5px 6px; }
.mts table.views3 td { width: 33.33%; padding: 3px; text-align: center; vertical-align: bottom; border-top: 0; }
.mts table.views3 .vimg { height: 46mm; display: flex; align-items: center; justify-content: center; }
.mts table.views3 .vimg img { max-width: 100%; max-height: 100%; }
.mts table.views3 .vimg.na { color: #8a5a00; font-style: italic; font-size: 8.5pt; }
.mts table.views3 .cap { margin-top: 2px; }
/* Line weights as in the Project 1 sample: heavy outer frame and section separators, thin lines under the section bars */
.mts-frame { border: 2px solid #1d2433; }
.mts-frame > div, .mts-frame > table { border-left: 0 !important; border-right: 0 !important; }
.mts-frame > .mts-head { border-top: 0; border-bottom: 2px solid #1d2433; }
.mts-frame > .mts-head .mts-brand { border-right: 2px solid #1d2433; }
.mts-frame td:first-child, .mts-frame th:first-child { border-left: 0; }
.mts-frame td:last-child, .mts-frame th:last-child { border-right: 0; }
.mts-frame tr.qty1 td:first-child + td, .mts-frame tr.qty2 td:first-child { border-left: 1px solid #1d2433; }
.mts-frame > table:last-child tr:last-child td { border-bottom: 0; }
.titleline { border-bottom: 2px solid #1d2433; }
.mts .bar2 { border-top: 0; border-bottom: 1px solid #1d2433; }
.mts-frame > .bar2 + table tr:first-child td, .mts-frame > .bar2 + table tr:first-child th { border-top: 0; }
.mts table.grid tr:last-child td { border-bottom: 2px solid #1d2433; }
.mts table.views3 td { border-bottom: 2px solid #1d2433; }
.mts-frame > table.qty tr:last-child td { border-bottom: 2px solid #1d2433; }
.mts tr.hdr th { border-bottom: 2px solid #1d2433; }
.mts-frame > table.proc tr:last-child td { border-bottom: 2px solid #1d2433; }
.wm-conf { position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%) rotate(-52deg) scaleX(.9); z-index: 0; white-space: nowrap;
  font: 900 66pt/1.05 Rockwell, "Rockwell Extra Bold", Georgia, "Times New Roman", serif; letter-spacing: 0;
  color: rgba(225,80,80,.07); -webkit-text-stroke: 1.2px rgba(214,50,50,.26);
  border: 4px solid rgba(214,50,50,.22); border-radius: 24px; padding: 6px 26px 2px; }
"""


def render_mts(data: dict, meta: dict, view_images: dict, branding: dict) -> str:
    m = data["mts"]
    approved = data["approved"]

    def val(cell):
        text, mk = cell
        return f'<span class="{"missing" if mk == "M" else ""}">{E(text)}</span> {mark_html(mk)}'

    views = "".join(
        f'<td><div class="vimg"><img src="{view_images[n]}" alt="{lbl} view"></div><div class="cap">{lbl} view</div></td>' if n in view_images
        else f'<td><div class="vimg na">View not available<br>{E(data["views"].get(n) or "")}</div><div class="cap">{lbl} view</div></td>'
        for n, lbl in (("front", "Front"), ("top", "Top"), ("iso", "Isometric")))
    grid = m["grid"]
    grid_rows = "".join(f'<tr><td class="k">{E(grid[i][0])}</td><td class="c">{val(grid[i][1])}</td>'
                        f'<td class="k">{E(grid[i + 1][0])}</td><td class="c">{val(grid[i + 1][1])}</td></tr>' for i in range(0, len(grid), 2))
    q = m["quantities"]
    first = f'<td class="k c" rowspan="{len(q)}">Qty to be produced</td>'
    qty = "".join(f'<tr class="qty{1 if i == 0 else 2}">{first if i == 0 else ""}<td class="c">{E(k)}</td><td class="c">{val(c)}</td></tr>' for i, (k, c) in enumerate(q))
    proc = "".join(f'<tr><td class="c">{i}</td><td class="c"><b>{E(k)}</b></td><td>{val(c)}</td></tr>'
                   for i, (k, c) in enumerate(m["process"], 1))
    tests = "".join(f'<tr><td class="c">{i}</td><td class="c">{E(a) or "—"}</td><td class="c">{E(b) or "Not recorded"}</td>'
                    f'<td class="c">{E(c) or "Not recorded"}</td><td class="c">{E(d) or "Not recorded"}</td></tr>'
                    for i, (a, b, c, d) in enumerate(m["tests"], 1))
    if not tests:
        tests = '<tr><td colspan="5" class="missing c">No inspection and test specifications recorded in the passport</td></tr>'
    logo = logo_data_uri()
    brand = (f'<img src="{logo}" alt="{E(branding["name"])}">' if logo else f'<span class="txt">{E(branding["name"])}</span>')
    out = [f'<!doctype html><html><head><meta charset="utf-8"><style>{CSS}{MTS_CSS}</style></head><body class="mts">',
           '<div class="wm-conf">CONFIDENTIAL</div>']
    out.append(
        f'<div class="mts-frame"><div class="mts-head"><div class="mts-brand">{brand}</div>'
        f'<div class="mts-title">Manufacturing &amp; Test Specifications Report</div>'
        f'<div class="mts-doc"><table><colgroup><col style="width:62%"><col></colgroup>'
        f'<tr><td><b>Document No.</b></td><td><b>Revision No</b></td></tr>'
        f'<tr><td class="num">{E(meta["number"])}</td><td>{data["revision"]}{"" if approved else " (draft)"}</td></tr></table></div></div>'
        f'<div class="titleline"><b>Title:</b> {E(m["title"])}</div>'
        f'<div class="bar2">Manufacturing Specifications:</div><table class="grid">{grid_rows}</table>'
        f'<table class="views3"><tr>{views}</tr></table>'
        f'<table class="qty">{qty}</table>'
        f'<div class="bar2">Manufacturing Process:</div>'
        f'<table class="proc"><colgroup><col style="width:9%"><col style="width:22%"><col></colgroup>'
        f'<tr class="hdr"><th>Sr. No</th><th>Process</th><th>Description</th></tr>{proc}</table>'
        f'<div class="bar2">Inspection and Test Specifications:</div>'
        f'<table><colgroup><col style="width:9%"><col style="width:22%"><col style="width:21%"><col style="width:24%"><col></colgroup>'
        f'<tr class="hdr"><th>Sr. No</th><th>Test Method</th><th>Reference Document</th><th>Acceptance Criteria</th>'
        f'<th>Inspection frequency</th></tr>{tests}</table></div>')
    if not approved:
        out.append(f'<div class="status">Passport revision {data["revision"]} is not approved ({E(data["revision_status"])}).'
                   f'<small>{WATERMARK}. Values marked D, C or M are not verified engineering data. This document is not a '
                   'manufacturing authorisation, QA certificate or material certificate.</small></div>')
    out.append(attachment_index(data, "Attached documents (in page order)"))
    out.append(f'<div class="legend">{"".join(f"<span>{mark_html(k)} {E(t)}</span>" for k, t in LEGEND)}</div>'
               f'<p class="notice">Aries confidential: contains manufacturing parameters; not for client or third-party distribution. '
               f'Generated from passport {E(data["passport"])} rev {data["revision"]} ({E(data["revision_status"])}) · content fingerprint '
               f'{meta["fingerprint"][:16]}… · {E(meta["generated"])} · {E(meta["by_role"])}. Job sheets and engineering notes are not included.</p>'
               '</body></html>')
    return "".join(out)


def mts_footer(meta: dict, data: dict) -> str:
    """Page number only, centred, in Times New Roman ("Page 1", "Page 2", as in the Project 1 sample). The report number
    and the confidentiality and draft status are printed on the page body and its watermarks, not in the footer."""
    return ('<div style="width:100%;text-align:center;font-family:\'Times New Roman\',Times,serif;font-size:8pt;color:#000">'
            'Page <span class="pageNumber"></span></div>')
