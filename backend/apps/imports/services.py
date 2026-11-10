"""Bulk inventory import (CN-007 Phase 1): read Excel/CSV, map columns, analyse every row, commit safely.

Rules:
- Identity is (company, customer material number). A number already in the company is never created twice.
- Preview writes nothing to spare parts. Commit re-analyses inside one transaction, so the preview cannot go stale.
- Re-import: a field still holding the value an earlier import wrote may be updated (only when the importer chooses to
  apply updates); a field changed in the application since, or set outside an import, is never overwritten: the row
  is reported as a conflict and left as it is.
- New parts are drafts, "Not classified" and "Not assessed"; no passport, approval, eligibility or price is created.
  Client-side imports are held for Aries review like other client records (CN-003).
"""
import csv
import hashlib
import io
import zipfile

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.service import record
from apps.core.exceptions import DomainError
from apps.parts.models import SparePart
from apps.parts.submissions import display_name
from apps.projects.models import Project
from apps.projects.scoping import allowed_project_ids, restrict

from . import mapping as M
from .models import InventoryImport, InventoryImportRow

O = InventoryImportRow.Outcome
CSV_ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")


# ------------------------------------------------------------------ reading files

def _text(v) -> str:
    """Cell value as text exactly as shown; whole-number floats lose the ".0" Excel adds (material numbers)."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)


def _header_index(rows: list[list[str]]) -> int:
    for i, r in enumerate(rows[:20]):
        if sum(1 for c in r if c.strip()) >= 2:
            return i
    raise DomainError("no_header", "No header row was found in the first 20 rows.", http_status=400)


def read_file(name: str, data: bytes) -> dict:
    lower = name.lower()
    if len(data) > settings.IMPORT_MAX_BYTES:
        raise DomainError("file_too_large", f"The file is larger than {settings.IMPORT_MAX_BYTES // (1024 * 1024)} MB.", http_status=400)
    if lower.endswith(".xlsx"):
        if not zipfile.is_zipfile(io.BytesIO(data)):
            raise DomainError("invalid_file", "This is not a valid .xlsx workbook.", http_status=400)
        import openpyxl

        try:
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception:  # noqa: BLE001 - any parser failure is a user error here
            raise DomainError("invalid_file", "The workbook could not be read.", http_status=400)
        ws = wb.worksheets[0]
        rows = []
        for r in ws.iter_rows(values_only=True):
            rows.append([_text(c) for c in r])
            if len(rows) > settings.IMPORT_MAX_ROWS + 25:
                break
        kind, sheet = "xlsx", ws.title
        wb.close()
    elif lower.endswith(".csv"):
        for enc in CSV_ENCODINGS:
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t") if text.strip() else csv.excel
        rows = [list(r) for r in csv.reader(io.StringIO(text), dialect)]
        kind, sheet = "csv", ""
    else:
        raise DomainError("unsupported_file", "Upload an Excel workbook (.xlsx) or a CSV file.", http_status=400)
    rows = [[c if isinstance(c, str) else _text(c) for c in r] for r in rows]
    h = _header_index(rows)
    headers, seen = [], {}
    for i, c in enumerate(rows[h]):
        label = c.strip() or f"Column {i + 1}"
        if label in seen:  # duplicate header names stay distinguishable
            seen[label] += 1
            label = f"{label} ({seen[label]})"
        seen.setdefault(label, 1)
        headers.append(label)
    body = []
    for offset, r in enumerate(rows[h + 1:], start=h + 2):
        if not any(c.strip() for c in r):
            continue
        body.append((offset, {headers[i]: (r[i] if i < len(r) else "") for i in range(len(headers))}))
    if not body:
        raise DomainError("no_rows", "The file has a header row but no data rows.", http_status=400)
    if len(body) > settings.IMPORT_MAX_ROWS:
        raise DomainError("too_many_rows", f"The file has more than {settings.IMPORT_MAX_ROWS} rows.", http_status=400)
    return {"kind": kind, "sheet": sheet, "header_row": h + 1, "headers": headers, "rows": body}


# ------------------------------------------------------------------ batches

def next_reference(tenant) -> str:
    year = timezone.now().year
    n = InventoryImport.objects.filter(tenant=tenant, reference__startswith=f"IMP-{year}-").count() + 1
    while InventoryImport.objects.filter(tenant=tenant, reference=f"IMP-{year}-{n:05d}").exists():
        n += 1
    return f"IMP-{year}-{n:05d}"


def _side(request) -> str:
    return "aries" if request.membership.role.startswith("operator_") else "client"


def _check_project(request, project) -> None:
    allowed = allowed_project_ids(request)
    if allowed is not None and (project is None or project.pk not in allowed):
        raise DomainError("project_required", "Choose one of your assigned projects for this import.", http_status=400)


def create(request, upload, project_id=None, preset: str = "") -> InventoryImport:
    if request.tenant.kind != request.tenant.Kind.CLIENT:
        raise DomainError("client_only", "Inventory is imported inside a client company.", http_status=400)
    data = upload.read()
    parsed = read_file(upload.name, data)
    project = None
    if project_id:
        project = restrict(request, Project.objects.filter(tenant=request.tenant), "pk").filter(pk=project_id).first()
        if project is None:
            raise DomainError("not_found", "Project not found.", http_status=404)
    _check_project(request, project)
    preset = preset if preset in M.PRESETS else ""
    with transaction.atomic():
        batch = InventoryImport.objects.create(
            tenant=request.tenant, created_by=request.user, reference=next_reference(request.tenant),
            file_name=upload.name[:255], file_kind=parsed["kind"], file_size=len(data), file_sha256=hashlib.sha256(data).hexdigest(),
            sheet_name=parsed["sheet"][:120], header_row=parsed["header_row"], headers=parsed["headers"], preset=preset,
            mapping=M.auto_mapping(parsed["headers"], preset), project=project, importer_side=_side(request),
            row_count=len(parsed["rows"]))
        InventoryImportRow.objects.bulk_create([
            InventoryImportRow(tenant=request.tenant, created_by=request.user, batch=batch, row_number=n, source=src)
            for n, src in parsed["rows"]], batch_size=1000)
        analyse(request, batch)
        record(request, "inventory_import.previewed", obj=batch,
               data={"reference": batch.reference, "file": batch.file_name, "sha256": batch.file_sha256, "rows": batch.row_count})
    return batch


def update_mapping(request, batch, mapping: dict, project_id="__keep__") -> InventoryImport:
    _require_preview(batch)
    clean = {}
    for field, header in (mapping or {}).items():
        if field not in M.TARGETS:
            raise DomainError("unknown_field", f"'{field}' cannot be imported.", http_status=400)
        if header:
            if header not in batch.headers:
                raise DomainError("unknown_column", f"The file has no column '{header}'.", http_status=400)
            clean[field] = header
    if project_id != "__keep__":
        project = None
        if project_id:
            project = restrict(request, Project.objects.filter(tenant=request.tenant), "pk").filter(pk=project_id).first()
            if project is None:
                raise DomainError("not_found", "Project not found.", http_status=404)
        _check_project(request, project)
        batch.project = project
    batch.mapping = clean
    batch.save(update_fields=["mapping", "project", "updated_at"])
    analyse(request, batch)
    return batch


def _require_preview(batch):
    if batch.status != InventoryImport.Status.PREVIEW:
        raise DomainError("not_preview", "This import is closed. Upload the file again to start a new import.", http_status=409)


# ------------------------------------------------------------------ analysis

def _values(row, mapping) -> tuple[dict, list]:
    values, messages = {}, []
    for field, (label, required, limit, _note) in M.TARGETS.items():
        raw = row.source.get(mapping.get(field, ""), "") if mapping.get(field) else ""
        value = raw if field in ("manufacturer", "client_remarks") else raw.strip()
        if field == "manufacturer" and not raw.strip():
            value = ""
        if required and not value:
            messages.append({"level": "error", "code": f"missing_{field}", "text": f"{label} is required."})
        if len(value) > limit:
            messages.append({"level": "error", "code": f"too_long_{field}", "text": f"{label} is longer than {limit} characters."})
        values[field] = value
    return values, messages


def analyse(request, batch) -> None:
    """Fill each row's outcome, messages, flags and planned changes from the current mapping and current parts."""
    rows = list(batch.rows.all())
    mapping = batch.mapping
    if not mapping.get("part_number") or not mapping.get("name"):
        missing = [M.TARGETS[f][0] for f in ("part_number", "name") if not mapping.get(f)]
        for r in rows:
            r.values, r.flags, r.changes, r.conflicts, r.part = {}, [], {}, {}, None
            r.outcome = O.ERROR
            r.messages = [{"level": "error", "code": "mapping_incomplete", "text": f"Map a column to: {', '.join(missing)}."}]
        InventoryImportRow.objects.bulk_update(rows, ["values", "flags", "changes", "conflicts", "part", "outcome", "messages"], batch_size=1000)
        _count(batch, rows)
        return
    visible = restrict(request, SparePart.objects.filter(tenant=request.tenant), "project")
    all_numbers = {}
    numbers = set()
    prepared = []
    for r in rows:
        values, messages = _values(r, mapping)
        prepared.append((r, values, messages))
        if values.get("part_number"):
            numbers.add(values["part_number"])
    # existence is checked company-wide (the number is unique per company); details only for parts the importer may see
    for pk, number, project_id in SparePart.objects.filter(tenant=request.tenant, part_number__in=numbers).values_list("pk", "part_number", "project_id"):
        all_numbers[number] = pk
    parts = {p.part_number: p for p in visible.filter(part_number__in=numbers)}
    # possible duplicates: same description and manufacturer under another material number (company parts + this file)
    keys = {}
    for p in SparePart.objects.filter(tenant=request.tenant).only("part_number", "name", "manufacturer"):
        keys.setdefault((M.norm_description(p.name), M.clean_manufacturer(p.manufacturer)), set()).add(p.part_number)
    for _r, values, _m in prepared:
        if values.get("part_number") and values.get("name"):
            keys.setdefault((M.norm_description(values["name"]), M.clean_manufacturer(values.get("manufacturer", ""))), set()).add(values["part_number"])
    seen = {}
    for r, values, messages in prepared:
        raw_mfr = r.source.get(mapping.get("manufacturer", ""), "") if mapping.get("manufacturer") else ""
        flags = M.row_flags(values, raw_mfr, batch.preset)
        number = values.get("part_number")
        dup_key = (M.norm_description(values.get("name", "")), M.clean_manufacturer(values.get("manufacturer", "")))
        if number and values.get("name") and len(keys.get(dup_key, set()) - {number}) > 0:
            flags.append("possible_duplicate")
            others = sorted(keys[dup_key] - {number})[:5]
            messages.append({"level": "warning", "code": "possible_duplicate",
                             "text": f"Same description and manufacturer as material number(s) {', '.join(others)}. Not merged; review."})
        r.values, r.flags, r.changes, r.conflicts, r.part = values, flags, {}, {}, None
        if number and number in seen:
            messages.append({"level": "error", "code": "duplicate_in_file", "text": f"Material number already on row {seen[number]} of this file."})
        elif number:
            seen[number] = r.row_number
        if any(m["level"] == "error" for m in messages):
            r.outcome, r.messages = O.ERROR, messages
            continue
        part = parts.get(number)
        if part is None and number in all_numbers:
            r.outcome = O.CONFLICT
            r.messages = messages + [{"level": "warning", "code": "outside_scope",
                                      "text": "This material number already exists in a project you are not assigned to. Not changed."}]
            continue
        if part is None:
            r.outcome, r.messages = O.NEW, messages
            continue
        r.part = part
        last = (part.import_record or {}).get("values", {})
        for field in M.OWNED:
            incoming, current = values.get(field, ""), getattr(part, field) or ""
            if incoming == current or (not incoming and field not in last):
                continue  # identical, or the file has no value for a field it never supplied: leave it
            if (field in last and current == last[field]) or (not current and field not in last):
                r.changes[field] = {"current": current, "incoming": incoming}
            else:
                r.conflicts[field] = {"current": current, "last_imported": last.get(field), "incoming": incoming}
        if r.conflicts:
            r.outcome = O.CONFLICT
            messages.append({"level": "warning", "code": "edited_since_import",
                             "text": "Changed in the application since it was imported (or set outside an import); the current value is kept: "
                                     + ", ".join(M.TARGETS[f][0] for f in r.conflicts) + "."})
        r.outcome = O.CONFLICT if r.conflicts else (O.UPDATE if r.changes else O.UNCHANGED)
        r.messages = messages
    InventoryImportRow.objects.bulk_update([r for r, _v, _m in prepared],
                                           ["values", "flags", "changes", "conflicts", "part", "outcome", "messages"], batch_size=1000)
    _count(batch, [r for r, _v, _m in prepared])


def _count(batch, rows) -> None:
    counts = {o: 0 for o in O.values}
    flags = {}
    for r in rows:
        counts[r.outcome] += 1
        for f in r.flags:
            flags[f] = flags.get(f, 0) + 1
    batch.counts = {"outcomes": counts, "flags": flags}
    batch.analysed_at = timezone.now()
    batch.save(update_fields=["counts", "analysed_at", "updated_at"])


# ------------------------------------------------------------------ commit / discard

def commit(request, batch, apply_updates: bool) -> InventoryImport:
    _require_preview(batch)
    side = _side(request)
    now = timezone.now()
    with transaction.atomic():
        batch = InventoryImport.objects.select_for_update().get(pk=batch.pk)
        _require_preview(batch)
        analyse(request, batch)
        created = updated = 0
        rows = list(batch.rows.select_related("part"))
        for r in rows:
            stamp = {"batch": str(batch.pk), "reference": batch.reference, "row": r.row_number, "imported_at": now.isoformat(),
                     "imported_by": display_name(request.user)}
            if r.outcome == O.NEW:
                v = r.values
                fields = {f: v.get(f, "") for f in M.OWNED}
                part = SparePart(tenant=request.tenant, created_by=request.user, project=batch.project, part_number=v["part_number"],
                                 category=SparePart.Category.UNKNOWN, criticality=SparePart.Criticality.UNKNOWN,
                                 status=SparePart.Status.DRAFT, manufacturer_normalized=M.clean_manufacturer(fields["manufacturer"]),
                                 import_record={**stamp, "values": fields}, **fields)
                if side == "client":  # held for Aries review like any client record (CN-003); never engineering-approved
                    part.origin, part.review_state = SparePart.Origin.CLIENT, SparePart.Review.PENDING
                    part.submission_kind, part.submitted_by, part.submitted_at = SparePart.SubmissionKind.RECORD, request.user, now
                try:
                    with transaction.atomic():
                        part.save()
                except IntegrityError:  # created by someone else meanwhile: never a second record
                    r.applied = "skipped"
                    r.messages = r.messages + [{"level": "warning", "code": "created_meanwhile", "text": "Created by someone else meanwhile; not imported again."}]
                    continue
                r.part, r.applied = part, "created"
                created += 1
            elif r.outcome == O.UPDATE and apply_updates:
                part = r.part
                for f, ch in r.changes.items():
                    setattr(part, f, ch["incoming"])
                part.manufacturer_normalized = M.clean_manufacturer(part.manufacturer)
                prev = dict((part.import_record or {}).get("values", {}))
                prev.update({f: r.values.get(f, "") for f in M.OWNED})
                part.import_record = {**stamp, "values": prev}
                part.save(update_fields=[*r.changes, "manufacturer_normalized", "import_record", "updated_at"])
                r.applied = "updated"
                updated += 1
            else:
                r.applied = {O.UNCHANGED: "unchanged", O.UPDATE: "skipped"}.get(r.outcome, "skipped")
            r.final = True
        for r in rows:
            r.final = True
        InventoryImportRow.objects.bulk_update(rows, ["part", "applied", "messages", "final"], batch_size=1000)
        batch.status, batch.committed_at, batch.committed_by, batch.apply_updates = InventoryImport.Status.COMMITTED, now, request.user, apply_updates
        batch.result = {"created": created, "updated": updated,
                        "unchanged": sum(1 for r in rows if r.applied == "unchanged"),
                        "skipped": sum(1 for r in rows if r.applied == "skipped")}
        batch.save(update_fields=["status", "committed_at", "committed_by", "apply_updates", "result", "updated_at"])
        record(request, "inventory_import.committed", obj=batch,
               data={"reference": batch.reference, **batch.result, "apply_updates": apply_updates,
                     "conflicts": batch.counts["outcomes"].get(O.CONFLICT, 0), "errors": batch.counts["outcomes"].get(O.ERROR, 0)})
    return batch


def discard(request, batch, tenant=None) -> InventoryImport:
    _require_preview(batch)
    batch.status = InventoryImport.Status.DISCARDED
    batch.save(update_fields=["status", "updated_at"])
    record(request, "inventory_import.discarded", obj=batch, tenant=tenant, data={"reference": batch.reference})
    return batch


# ------------------------------------------------------------------ data quality (live, over the company's imported parts)

def quality(request) -> dict:
    parts = list(restrict(request, SparePart.objects.filter(tenant=request.tenant).exclude(import_record={}), "project")
                 .only("id", "part_number", "name", "manufacturer", "manufacturer_reference", "oem_part_number", "plant",
                       "functional_location", "equipment_tag", "customer_abc_class", "import_record", "category", "criticality"))
    keys = {}
    for p in SparePart.objects.filter(tenant=request.tenant).only("part_number", "name", "manufacturer"):
        keys.setdefault((M.norm_description(p.name), M.clean_manufacturer(p.manufacturer)), set()).add(p.part_number)
    presets = {str(pk): preset for pk, preset in InventoryImport.objects.filter(tenant=request.tenant).values_list("pk", "preset")}
    out, totals = [], {}
    for p in parts:
        values = {f: getattr(p, f) or "" for f in M.OWNED}
        rec = p.import_record or {}
        flags = M.row_flags(values, p.manufacturer, presets.get(str(rec.get("batch")), ""))
        others = keys.get((M.norm_description(p.name), M.clean_manufacturer(p.manufacturer)), set()) - {p.part_number}
        if others:
            flags.append("possible_duplicate")
        edited = sorted(f for f, v in (rec.get("values") or {}).items() if (getattr(p, f, "") or "") != v)
        for f in flags:
            totals[f] = totals.get(f, 0) + 1
        out.append({"id": str(p.pk), "part_number": p.part_number, "name": p.name, "flags": flags, "duplicates": sorted(others)[:5],
                    "edited_since_import": edited, "import_reference": rec.get("reference", ""), "category": p.category,
                    "criticality": p.criticality})
    # Open conflicts only: a part's most recent committed import row is a conflict and the part still differs from the
    # file. A later import (unchanged or updated) supersedes it; every conflict stays in its own import's history.
    by_pk = {p.pk: p for p in parts}
    open_conflicts, decided = [], set()
    for r in (InventoryImportRow.objects.filter(tenant=request.tenant, batch__status=InventoryImport.Status.COMMITTED, part__in=list(by_pk))
              .exclude(outcome=O.ERROR).select_related("batch").order_by("-batch__committed_at", "row_number")):
        if r.part_id in decided:
            continue
        decided.add(r.part_id)
        part = by_pk[r.part_id]
        fields = {f: v for f, v in (r.conflicts or {}).items() if (getattr(part, f, "") or "") != (v.get("incoming") or "")}
        if r.outcome == O.CONFLICT and fields:
            r.conflicts = fields
            open_conflicts.append(r)
    issue_codes = {c for c, (_l, level) in M.FLAGS.items() if level == "warning"}
    return {
        "totals": {"imported_parts": len(out), "with_warnings": sum(1 for x in out if set(x["flags"]) & issue_codes),
                   "possible_duplicates": totals.get("possible_duplicate", 0), "not_classified": sum(1 for x in out if x["category"] == "unknown"),
                   "not_assessed": sum(1 for x in out if x["criticality"] == "unknown"),
                   "edited_since_import": sum(1 for x in out if x["edited_since_import"])},
        "flags": totals,
        "flag_labels": {c: {"label": l, "level": lv} for c, (l, lv) in M.FLAGS.items()},
        "parts": out,
        "conflicts": [{"import_reference": r.batch.reference, "row_number": r.row_number, "part_number": r.values.get("part_number", ""),
                       "fields": r.conflicts, "messages": r.messages, "committed_at": r.batch.committed_at} for r in open_conflicts],
    }
