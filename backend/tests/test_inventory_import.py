"""Bulk inventory import and data quality (CN-007 Phase 1). Synthetic rows in the 573-part workbook layout; PostgreSQL
with RLS. The original customer workbook is never used here."""
import csv
import io

import openpyxl
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, transaction

from apps.audit.models import AuditEvent
from apps.imports.models import InventoryImport, InventoryImportRow
from apps.parts.models import SparePart
from apps.passports.models import DigitalPassport
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Membership, Role

from .conftest import login, make_user

HEADERS = ["S.No.", "Plant", "Sort field / equipment tag", "Func Loc.", "ABC indicator ", "Material", "Material Description",
           "Manufacturer Number", "Manufacturer Name", "Remarks 1"]
ROWS = [  # synthetic; same shapes as the reference workbook (numbers as numbers, 25-char manufacturer, blanks)
    [1, "UTIL", 91010000101, "S-071-02-XA18-PC220A", "C", 990100000101, "COVER,BRG HSG,CNTRFGL PMP", 29990101, "SYNTHETIC PUMPS ITALY SRL ", None],
    [2, None, None, None, None, 990100000102, "SEAL,MECH,CARTRIDGE", None, None, None],
    [3, "XLPE", 91010000103, "S-BO-0021-0000-PC02", "D", 990100000103, "INSERT,CTNGTL,CRBDE", 29990103, "SYNTHETIC TOOLING GMBH", None],
    [4, "LDPE-WET", 91010000104, "S-040-01-XA01-PC102A", "D", 990100000104, "RING,WEAR,90MM,130MM,30MM,A48-40", 29990104,
     "SYNTHETIC ROTATING EQUIPM", None],
]


def xlsx(rows=ROWS, headers=HEADERS, name="inventory.xlsx"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "573 Spare Parts"
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return SimpleUploadedFile(name, buf.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def csv_file(rows=ROWS, headers=HEADERS, name="inventory.csv"):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)
    for r in rows:
        w.writerow(["" if c is None else c for c in r])
    return SimpleUploadedFile(name, buf.getvalue().encode("utf-8"), content_type="text/csv")


@pytest.fixture
def env(settings, world):
    settings.INVENTORY_IMPORT_ENABLED = True
    settings.CLIENT_PART_SUBMISSIONS_ENABLED = True
    eng = login(world["op_eng"], world["a"])
    p1 = eng.post("/api/v1/projects/", {"code": "INV", "name": "Inventory pilot"}, format="json").json()
    p2 = eng.post("/api/v1/projects/", {"code": "OTH", "name": "Other project"}, format="json").json()
    # an existing Aries part with the same description and manufacturer as row 3 (possible duplicate)
    eng.post("/api/v1/parts/", {"part_number": "990100000099", "name": "INSERT,CTNGTL,CRBDE", "manufacturer": "SYNTHETIC TOOLING GMBH",
                                "project": p1["id"]}, format="json")
    return {"eng": eng, "p1": p1, "p2": p2}


def upload(client, f=None, project=None, preset="sap_material_list"):
    body = {"file": f or xlsx(), "preset": preset}
    if project:
        body["project"] = project
    return client.post("/api/v1/inventory-imports/", body, format="multipart")


def rows(client, batch):
    return {r["row_number"]: r for r in client.get(f"/api/v1/inventory-imports/{batch}/rows/", {"page_size": 100}).json()["results"]}


def parts(tenant):
    with tenant_context(tenant):
        return {p.part_number: p for p in SparePart.objects.filter(tenant=tenant)}


def test_disabled_by_default(world):
    r = login(world["op_eng"], world["a"]).post("/api/v1/inventory-imports/", {"file": xlsx()}, format="multipart")
    assert r.status_code == 403


def test_preview_maps_the_workbook_layout_and_writes_no_parts(world, env):
    r = upload(env["eng"], project=env["p1"]["id"])
    assert r.status_code == 201, r.content
    b = r.json()
    assert b["status"] == "preview" and b["row_count"] == 4 and b["sheet_name"] == "573 Spare Parts"
    assert b["mapping"]["part_number"] == "Material" and b["mapping"]["manufacturer_reference"] == "Manufacturer Number"
    assert b["mapping"]["customer_abc_class"] == "ABC indicator" and "oem_part_number" not in b["mapping"]  # never guessed
    assert b["counts"]["outcomes"] == {"new": 4, "unchanged": 0, "update": 0, "conflict": 0, "error": 0}
    assert set(parts(world["a"])) == {"990100000099"}  # preview writes nothing
    rr = rows(env["eng"], b["id"])
    assert rr[2]["values"]["part_number"] == "990100000101"  # spreadsheet row 2; numbers kept as text, no ".0"
    assert rr[2]["source"]["Manufacturer Name"] == "SYNTHETIC PUMPS ITALY SRL "  # original preserved exactly
    assert "manufacturer_spacing" in rr[2]["flags"]
    assert {"missing_manufacturer", "missing_plant", "missing_equipment_tag", "missing_abc"} <= set(rr[3]["flags"])
    assert "possible_duplicate" in rr[4]["flags"] and any("990100000099" in m["text"] for m in rr[4]["messages"])
    assert {"mentions_dimensions", "mentions_material", "possibly_truncated_manufacturer"} <= set(rr[5]["flags"])


def test_commit_creates_unclassified_unassessed_inventory_without_passports(world, env):
    b = upload(env["eng"], project=env["p1"]["id"]).json()
    assert env["eng"].post(f"/api/v1/inventory-imports/{b['id']}/commit/", {}, format="json").status_code == 400  # confirmation needed
    r = env["eng"].post(f"/api/v1/inventory-imports/{b['id']}/commit/", {"confirm": True}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "committed" and r.json()["result"]["created"] == 4
    ps = parts(world["a"])
    p = ps["990100000101"]
    assert p.name == "COVER,BRG HSG,CNTRFGL PMP" and p.manufacturer == "SYNTHETIC PUMPS ITALY SRL " and p.manufacturer_normalized == "SYNTHETIC PUMPS ITALY SRL"
    assert p.manufacturer_reference == "29990101" and p.oem_part_number == ""  # reference is never an OEM part number
    assert p.plant == "UTIL" and p.functional_location == "S-071-02-XA18-PC220A" and p.equipment_tag == "91010000101"
    assert p.customer_abc_class == "C" and p.criticality == "unknown" and p.category == "unknown" and p.status == "draft"
    assert p.original_material == "" and p.dimensions == ""  # nothing extracted from the description
    assert p.import_record["reference"] == b["reference"] and p.import_record["row"] == 2 and p.origin == "aries"
    with tenant_context(world["a"]):
        assert not DigitalPassport.objects.exists()
        assert AuditEvent.objects.filter(action="inventory_import.committed").exists()
    detail = env["eng"].get(f"/api/v1/parts/{p.pk}/").json()
    assert detail["manufacturer_reference"] == "29990101" and detail["customer_abc_class"] == "C" and detail["passport_id"] is None


def test_reimport_is_idempotent_updates_only_untouched_values_and_reports_conflicts(world, env):
    eng = env["eng"]
    b = upload(eng, project=env["p1"]["id"]).json()
    eng.post(f"/api/v1/inventory-imports/{b['id']}/commit/", {"confirm": True}, format="json")
    again = upload(eng, project=env["p1"]["id"]).json()
    assert again["counts"]["outcomes"]["unchanged"] == 4 and again["counts"]["outcomes"]["new"] == 0
    eng.post(f"/api/v1/inventory-imports/{again['id']}/commit/", {"confirm": True}, format="json")
    assert len(parts(world["a"])) == 5  # no duplicates
    # an engineer corrects row 1's name in the application; the source changes rows 1 and 4
    p1 = parts(world["a"])["990100000101"]
    assert eng.patch(f"/api/v1/parts/{p1.pk}/", {"name": "COVER,BEARING HOUSING,PUMP"}, format="json").status_code == 200
    changed = [list(r) for r in ROWS]
    changed[0][6] = "COVER,BRG HSG,CNTRFGL PMP,REV"
    changed[3][1] = "LDPE-DRY"
    third = upload(eng, xlsx(changed), project=env["p1"]["id"]).json()
    rr = rows(eng, third["id"])
    assert rr[2]["outcome"] == "conflict" and rr[2]["conflicts"]["name"]["current"] == "COVER,BEARING HOUSING,PUMP"
    assert rr[5]["outcome"] == "update" and rr[5]["changes"] == {"plant": {"current": "LDPE-WET", "incoming": "LDPE-DRY"}}
    done = eng.post(f"/api/v1/inventory-imports/{third['id']}/commit/", {"confirm": True}, format="json").json()
    assert done["result"]["updated"] == 0  # updates are applied only when asked for
    fourth = upload(eng, xlsx(changed), project=env["p1"]["id"]).json()
    done = eng.post(f"/api/v1/inventory-imports/{fourth['id']}/commit/", {"confirm": True, "apply_updates": True}, format="json").json()
    ps = parts(world["a"])
    assert done["result"]["updated"] == 1 and ps["990100000104"].plant == "LDPE-DRY"
    assert ps["990100000101"].name == "COVER,BEARING HOUSING,PUMP"  # the edit is never overwritten
    q = eng.get("/api/v1/inventory-imports/quality/").json()
    assert any(c["part_number"] == "990100000101" and "name" in c["fields"] for c in q["conflicts"])
    # once the part matches the file again, the conflict is no longer open (it stays in that import's history)
    eng.patch(f"/api/v1/parts/{p1.pk}/", {"name": "COVER,BRG HSG,CNTRFGL PMP,REV"}, format="json")
    assert not eng.get("/api/v1/inventory-imports/quality/").json()["conflicts"]
    # a conflict is also superseded by a later import that finds the part up to date
    eng.patch(f"/api/v1/parts/{p1.pk}/", {"name": "COVER,BEARING HOUSING,PUMP"}, format="json")
    assert eng.get("/api/v1/inventory-imports/quality/").json()["conflicts"]
    eng.patch(f"/api/v1/parts/{p1.pk}/", {"name": "COVER,BRG HSG,CNTRFGL PMP"}, format="json")
    later = upload(eng, xlsx(), project=env["p1"]["id"]).json()
    eng.post(f"/api/v1/inventory-imports/{later['id']}/commit/", {"confirm": True, "apply_updates": True}, format="json")
    assert not eng.get("/api/v1/inventory-imports/quality/").json()["conflicts"]
    # committed imports are frozen in the database
    with tenant_context(world["a"]), pytest.raises(Exception), transaction.atomic():
        InventoryImport.objects.filter(pk=b["id"]).update(file_name="x")
    with tenant_context(world["a"]), pytest.raises(Exception), transaction.atomic():
        InventoryImportRow.objects.filter(batch_id=b["id"]).update(outcome="new")


def test_validation_errors_and_duplicates_in_file(world, env):
    bad = [list(r) for r in ROWS] + [[5, "UTIL", 1, "X", "C", None, "NO NUMBER", 1, "M", None],
                                     [6, "UTIL", 1, "X", "C", 990100000101, "DUPLICATE ROW", 1, "M", None]]
    b = upload(env["eng"], csv_file(bad), project=env["p1"]["id"]).json()
    rr = rows(env["eng"], b["id"])
    assert rr[6]["outcome"] == "error" and rr[6]["messages"][0]["code"] == "missing_part_number"
    assert rr[7]["outcome"] == "error" and any(m["code"] == "duplicate_in_file" for m in rr[7]["messages"])
    r = env["eng"].patch(f"/api/v1/inventory-imports/{b['id']}/", {"mapping": {"name": "Material Description"}}, format="json").json()
    assert r["counts"]["outcomes"]["error"] == 6  # identity column unmapped: nothing importable
    assert env["eng"].patch(f"/api/v1/inventory-imports/{b['id']}/", {"mapping": {"part_number": "Nope"}}, format="json").status_code == 400
    assert upload(env["eng"], SimpleUploadedFile("x.xlsx", b"not a workbook")).status_code == 400
    assert upload(env["eng"], SimpleUploadedFile("x.pdf", b"%PDF")).status_code == 400
    env["eng"].post(f"/api/v1/inventory-imports/{b['id']}/discard/", {}, format="json")
    assert env["eng"].post(f"/api/v1/inventory-imports/{b['id']}/commit/", {"confirm": True}, format="json").status_code == 409


def test_permissions_scope_and_isolation(world, env):
    a = world["a"]
    # Client Administrator: not without explicit permission; with it, imports become client records awaiting review
    assert upload(login(world["a_admin"])).status_code == 403
    assert login(world["a_eng"]).post("/api/v1/inventory-imports/", {"file": xlsx()}, format="multipart").status_code == 403
    admin = login(world["op_admin"])
    m = Membership.objects.get(user=world["a_admin"], tenant=a)
    second = make_user("a.admin2@example.test", a, Role.CLIENT_ADMIN)
    m2 = Membership.objects.get(user=second, tenant=a)
    r = login(world["a_admin"]).patch(f"/api/v1/users/{m2.pk}/", {"inventory_import_allowed": True}, format="json")
    assert r.status_code == 403 and r.json()["error"]["code"] == "not_permitted"  # only an Aries Admin may allow it
    u = Membership.objects.get(user=world["a_user"], tenant=a)
    assert admin.patch(f"/api/v1/clients/{a.pk}/members/{u.pk}/", {"inventory_import_allowed": True}, format="json").status_code == 400
    assert admin.patch(f"/api/v1/clients/{a.pk}/members/{m.pk}/", {"inventory_import_allowed": True}, format="json").status_code == 200
    ca = login(world["a_admin"])
    b = upload(ca).json()
    ca.post(f"/api/v1/inventory-imports/{b['id']}/commit/", {"confirm": True}, format="json")
    p = parts(a)["990100000101"]
    assert p.origin == "client" and p.review_state == "pending_review" and p.submission_kind == "record"
    # project-limited engineer: must choose an assigned project; sees only those imports; other company sees nothing
    lim = make_user("lim@example.test", world["operator"], Role.OPERATOR_ENGINEER)
    lm = Membership.objects.create(user=lim, tenant=a, role=Role.OPERATOR_ENGINEER)
    admin.put(f"/api/v1/clients/{a.pk}/engineers/{lm.pk}/access/", {"scope": "projects", "project_ids": [env["p2"]["id"]]}, format="json")
    le = login(lim, a)
    assert upload(le).status_code == 400 and upload(le, project=env["p1"]["id"]).status_code == 404
    lb = upload(le, project=env["p2"]["id"]).json()
    rr = rows(le, lb["id"])
    assert all(r["outcome"] == "conflict" and r["messages"][-1]["code"] == "outside_scope" for r in rr.values())  # no second record
    assert b["id"] not in {x["id"] for x in le.get("/api/v1/inventory-imports/").json()["results"]}
    other = login(world["b_admin"])
    assert other.get(f"/api/v1/inventory-imports/{b['id']}/").status_code in (403, 404)
    with connection.cursor() as cur:  # RLS: the other company's context sees no rows at all
        with tenant_context(world["b"]):
            assert InventoryImport.objects.count() == 0 and InventoryImportRow.objects.count() == 0
    # Aries Admin: summaries across companies and discarding an open preview, never an import of their own
    s = admin.get("/api/v1/admin/inventory-imports/", {"client": str(a.pk)}).json()
    assert {i["reference"] for i in s["clients"][0]["imports"]} >= {b["reference"], lb["reference"]}
    assert "rows" not in str(s["clients"][0]["imports"][0].keys())
    assert admin.post("/api/v1/admin/inventory-imports/", {"client": str(a.pk), "import": lb["id"]}, format="json").json()["status"] == "discarded"
    assert admin.post("/api/v1/inventory-imports/", {"file": xlsx()}, format="multipart").status_code == 403
    assert login(world["a_eng"]).get("/api/v1/admin/inventory-imports/").status_code == 403


def test_quality_summary(world, env):
    b = upload(env["eng"], project=env["p1"]["id"]).json()
    env["eng"].post(f"/api/v1/inventory-imports/{b['id']}/commit/", {"confirm": True}, format="json")
    q = env["eng"].get("/api/v1/inventory-imports/quality/").json()
    assert q["totals"]["imported_parts"] == 4 and q["totals"]["not_classified"] == 4 and q["totals"]["not_assessed"] == 4
    assert q["totals"]["possible_duplicates"] == 1 and q["flags"]["missing_manufacturer"] == 1
    assert q["flags"]["no_oem_part_number"] == 4 and q["flag_labels"]["possible_duplicate"]["level"] == "warning"
    dup = next(x for x in q["parts"] if x["part_number"] == "990100000103")
    assert dup["duplicates"] == ["990100000099"]
