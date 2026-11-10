"""Assessment-run reports (CN-007 Phase 6): Excel (openpyxl) and PDF (the existing CN-005 renderer, run locally).

Both are built from the same run detail the viewer may see (project scope applied), state that the figures are
preliminary and that estimated savings are not validated, and contain no files, drawings, CAD or AI prompts.
"""
import html
import io
import shutil
import tempfile
from pathlib import Path

from django.utils import timezone

from apps.core.exceptions import DomainError

STATEMENT = ("Preliminary analytics. No passport, manufacturing job or release has been approved. Estimated savings include "
             "options that are not technically qualified; only verified savings meet every mandatory requirement with "
             "verified-current quotations on both sides.")
OPT = {"oem": "OEM", "additive": "Additive", "conventional": "Conventional"}


def _money(bucket: dict) -> str:
    return "; ".join(f"{cur} {float(v):,.2f}" for cur, v in sorted((bucket or {}).items())) or "none"


def _summary_rows(s: dict) -> list[tuple[str, object]]:
    return [
        ("Total parts (company, your scope)", s["total_parts"]), ("In assessment scope (imported inventory)", s["in_scope"]),
        ("Assessed", s["assessed"]), ("Unassessed in scope", s["unassessed"]), ("Outside the run scope", s["outside_scope"]),
        ("Insufficient technical data", s["insufficient_technical_data"]),
        ("Potential AM candidates (screening potentially suitable)", s["am_candidates"]),
        ("AM: specialist assessment required", s["am_specialist"]),
        ("Potential conventional candidates", s["conventional_candidates"]),
        ("Conventional: specialist assessment required", s["conventional_specialist"]),
        ("OEM identity verified / not verified", f"{s['oem']['identity_verified']} / {s['oem']['identity_not_verified']}"),
        ("OEM cost evidence", "; ".join(f"{v['label']}: {v['count']}" for v in s["oem"]["cost_evidence"].values()) or "none"),
        ("Parts with expired OEM evidence", s["oem"]["with_expired_evidence"]),
        ("OEM availability / obsolescence not documented", s["oem"]["availability_not_documented"]),
        ("Potentially obsolete items", s["potentially_obsolete"]),
        ("Review backlog (preliminary + information requested)", s["review_backlog"]["total"]),
        ("Estimated savings (provisional)", _money(s["savings"]["estimated"])),
        ("Verified savings", _money(s["savings"]["verified"])),
        ("Open evidence gaps (all parts)", s["evidence_gaps_total"]),
    ]


def _change_rows(c: dict) -> list[list[str]]:
    if not c or c.get("previous_run") is None:
        return [["—", "First run for this scope: nothing to compare.", "", ""]]
    rows = []
    for n in c["new_am_candidates"]:
        rows.append([n, "New AM candidate", "", ""])
    for n in c["new_conventional_candidates"]:
        rows.append([n, "New conventional candidate", "", ""])
    for x in c["technical_changes"]:
        rows.append([x["part"], f"{OPT[x['option']]} screening", x["before"], x["after"]])
    for x in c["evidence_gaps"]:
        rows.append([x["part"], "Evidence gaps", str(x["before"]), f"{x['after']} (new: {', '.join(x['new']) or '-'}; closed: {', '.join(x['closed']) or '-'})"])
    for x in c["oem_changes"]:
        rows.append([x["part"], x["what"], str(x["before"]), str(x["after"])])
    for x in c["cost_changes"]:
        rows.append([x["part"], f"{OPT[x['option']]} total ({x['currency']}, scenario {x['scenario']})", str(x["before"]), f"{x['after']} (Δ {x['delta']})"])
    for x in c["lead_time_changes"]:
        rows.append([x["part"], f"{OPT[x['option']]} lead time (days)", str(x["before"]), str(x["after"])])
    for x in c["outcome_changes"]:
        rows.append([x["part"], "Recommendation outcome", x["before"], x["after"]])
    for n in c["unchanged"]:
        rows.append([n, "Unchanged", "", ""])
    return rows


def _part_row(i: dict) -> list:
    r = i.get("result") or {}
    if not r:
        return [i["part_number"], i["name"], i["status_label"], i.get("error_message", "")] + [""] * 12
    com = r.get("commercial") or {}
    opts = com.get("options") or {}
    est, ver = r["savings"]["estimated"], r["savings"]["verified"]
    return [i["part_number"], i["name"], i["status_label"], r["recommendation"]["label"],
            r["feasibility"]["oem"]["label"], r["feasibility"]["additive"]["label"], r["feasibility"]["conventional"]["label"],
            "yes" if r["insufficient_technical_data"] else "no", len(r["evidence_gaps"]), r["oem"]["cost_evidence"],
            com.get("currency", ""), *[opts.get(k, {}).get("total") or "incomplete" for k in ("oem", "additive", "conventional")],
            f"{est['amount']} ({OPT[est['option']]}, {'qualified' if est['qualified'] else 'not technically qualified'})" if est else "",
            f"{ver['amount']} ({OPT[ver['option']]})" if ver else "", (i.get("review_state") or {}).get("label", "")]


PART_HEADERS = ["Material number", "Description", "Run status", "Recommendation outcome", "OEM screening", "AM screening",
                "Conventional screening", "Insufficient technical data", "Evidence gaps", "OEM cost evidence", "Currency",
                "OEM total", "AM total", "Conventional total", "Estimated saving", "Verified saving", "Review state"]


def xlsx(detail: dict, company: str) -> bytes:
    import openpyxl
    from openpyxl.styles import Font

    run, s = detail["run"], detail["summary"]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append([f"Inventory assessment run {run['number']} — {company} ({run['quarter']})"])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append([STATEMENT])
    ws.append([])
    for k, v in _summary_rows(s):
        ws.append([k, v])
    ws.column_dimensions["A"].width = 58
    ws.column_dimensions["B"].width = 60
    parts = wb.create_sheet("Parts")
    parts.append(PART_HEADERS)
    for i in detail["items"]:
        parts.append(_part_row(i))
    for cell in parts[1]:
        cell.font = Font(bold=True)
    changes = wb.create_sheet("Changes")
    changes.append(["Material number", "Change", "Before", "After"])
    for row in _change_rows(detail["comparison"]):
        changes.append(row)
    meta = wb.create_sheet("Run")
    for k, v in (("Run", run["number"]), ("Kind", run["kind_label"]), ("Quarter", run["quarter"]), ("Status", run["status_label"]),
                 ("Started", _when(run["started_at"])), ("Finished", _when(run["finished_at"])), ("Requested by", run["requested_by"]),
                 ("Parts", run["part_count"]), ("Assessed / reused / failed", f"{run['done_count']} / {run['reused_count']} / {run['failed_count']}"),
                 ("Previous run", run["previous_run"] or "—"), ("AI tier", run["ai_tier"] or "none (rules only)"),
                 *[(f"Methodology: {k}", v) for k, v in run["methodology"].items()], ("Generated", timezone.localtime().isoformat())):
        meta.append([k, str(v)])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _when(dt) -> str:
    return timezone.localtime(dt).strftime("%d %b %Y %H:%M %Z") if dt else "—"


def _currency(detail: dict) -> str:
    curs = sorted({(i.get("result") or {}).get("commercial", {}).get("currency") for i in detail["items"]
                   if (i.get("result") or {}).get("commercial")} - {None})
    return "amounts in " + ", ".join(curs) if curs else "no cost comparisons"


def _table(headers, rows) -> str:
    h = "".join(f"<th>{html.escape(str(x))}</th>" for x in headers)
    b = "".join("<tr>" + "".join(f"<td>{html.escape(str(c if c is not None else ''))}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table>"


def pdf(detail: dict, company: str) -> bytes:
    from apps.reports.services import _run

    run, s = detail["run"], detail["summary"]
    doc = f"""<!doctype html><html><head><meta charset="utf-8"><style>
body {{ font-family: Arial, sans-serif; font-size: 9.5pt; color: #1f2933; }} h1 {{ font-size: 15pt; margin: 0 0 4px; }}
h2 {{ font-size: 11.5pt; margin: 16px 0 6px; border-bottom: 1px solid #cbd2d9; }} .note {{ background: #fff8e1; padding: 6px 8px; }}
table {{ border-collapse: collapse; width: 100%; margin-bottom: 8px; }} th, td {{ border: 1px solid #d9e2ec; padding: 3px 5px; text-align: left;
vertical-align: top; }} th {{ background: #f0f4f8; }} .kv td:first-child {{ width: 45%; }}
table.parts {{ table-layout: fixed; font-size: 7.5pt; }} table.parts td, table.parts th {{ overflow-wrap: anywhere; padding: 2px 3px; }}
</style></head><body>
<h1>Inventory assessment run {run['number']}: {html.escape(company)}</h1>
<div>{html.escape(run['quarter'])} · {html.escape(run['kind_label'])} · {html.escape(run['status_label'])} · finished {html.escape(_when(run['finished_at']))}
 · requested by {html.escape(run['requested_by'])} · previous run {run['previous_run'] or '—'}</div>
<p class="note">{html.escape(STATEMENT)}</p>
<h2>Dashboard</h2>{_table(["Measure", "Value"], _summary_rows(s)).replace("<table>", '<table class="kv">')}
<h2>Changes since the preceding run</h2>{_table(["Material number", "Change", "Before", "After"], _change_rows(detail["comparison"]))}
<h2>Parts ({html.escape(_currency(detail))})</h2>{_table(PART_HEADERS[:4] + PART_HEADERS[5:7] + PART_HEADERS[11:17], [r[:4] + r[5:7] + r[11:17] for r in map(_part_row, detail["items"])]).replace("<table>", '<table class="parts">')}
<h2>Methodology</h2>{_table(["Component", "Version"], list(run["methodology"].items()))}
</body></html>"""
    footer = ('<div style="font-size:7pt;width:100%;padding:0 12mm;color:#52606d">Preliminary analytics · not an approval or release'
              ' · page <span class="pageNumber"></span> of <span class="totalPages"></span></div>')
    workdir = Path(tempfile.mkdtemp(prefix="assessment-report-"))
    try:
        (workdir / "report.html").write_text(doc, encoding="utf-8")
        result = _run({"mode": "pdf", "html": str(workdir / "report.html"), "out": str(workdir / "report.pdf"), "footer": footer}, workdir)
        if not result.get("ok"):
            raise DomainError("report_render_failed", "The report could not be rendered. Try again later.",
                              details={"reason": str(result.get("error", ""))[:200]}, http_status=503)
        return (workdir / "report.pdf").read_bytes()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
