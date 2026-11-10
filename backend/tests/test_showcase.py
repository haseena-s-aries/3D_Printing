"""Demonstration dataset (seed_showcase): synthetic geometry, sample-marked documents, idempotent seeding,
tenant isolation and untouched business gates (OQ-35/OQ-36)."""
import re
import zlib

import pytest
from django.core.management import CommandError, call_command

from apps.files.models import EngineeringFile
from apps.parts.models import SparePart
from apps.passports.models import DigitalPassport
from apps.projects.models import Project
from apps.tenancy.context import tenant_context
from apps.tenancy.models import Membership, Tenant

from .conftest import PASSWORD, login

pytest.importorskip("OCP", reason="CAD packages (requirements-cad.txt) generate the sample STEP files")

from showcase import cad, data, documents  # noqa: E402
from showcase.pdf import BANNER  # noqa: E402


def pdf_text(pdf: bytes) -> str:
    """Decompressed content streams of a generated PDF (enough to search for drawn text)."""
    out = []
    for m in re.finditer(rb"/Length (\d+) /Filter /FlateDecode >>\nstream\n", pdf):
        stream = zlib.decompress(pdf[m.end():m.end() + int(m.group(1))]).decode("cp1252")
        out += re.findall(r"\((.*?)\) Tj", stream)  # drawn text runs; wrapped lines are re-joined with spaces
    return " ".join(out)


def test_every_sample_part_has_its_own_valid_geometry():
    signatures = {}
    for c in data.CLIENTS:
        for p in c.parts:
            m = cad.build(p.family, **p.params)
            assert m.valid, p.number
            sig = (p.family, round(m.volume_mm3), tuple(round(v, 1) for v in m.size))
            assert sig not in signatures, f"{p.number} duplicates {signatures.get(sig)}"
            signatures[sig] = p.number
    assert len(signatures) == sum(len(c.parts) for c in data.CLIENTS) == 32


def test_step_export_is_real_step():
    m = cad.build("pump_impeller")
    step = cad.step_bytes(m, "test impeller")
    assert step.startswith(b"ISO-10303-21;") and b"MANIFOLD_SOLID_BREP" in step


def test_documents_are_marked_as_samples_and_templates_carry_no_results():
    c, part = data.MARITIME, data.MARITIME.parts[0]
    m = cad.build(part.family, **part.params)
    from apps.core.management.commands.seed_showcase import build_content

    content = build_content(part, m)
    edges = cad.edge_polylines(m)
    docs = {
        "drawing": documents.drawing(c, part, m, edges), "spec": documents.specification(c, part, m, content),
        "itp": documents.itp(c, part, content), "wi": documents.work_instruction(c, part, content),
        "machine": documents.machine_details(c, part, content), "orientation": documents.print_orientation(c, part, m, edges, content),
        "dir": documents.dimensional_inspection_template(c, part, m), "mtc": documents.mtc_template(c, part, content),
    }
    for name, pdf in docs.items():
        text = pdf_text(pdf)
        assert pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF"), name
        assert "NOT FOR MANUFACTURING" in text and "Status: DRAFT \\(not approved\\)" in text, name
    assert "THIS IS NOT A CERTIFICATE" in pdf_text(docs["mtc"]) and "No result - not tested" in pdf_text(docs["mtc"])
    assert "Not inspected" in pdf_text(docs["dir"])
    assert pdf_text(docs["spec"]).count("Page ") >= 3  # multi-page specification
    assert BANNER.encode("cp1252") in docs["spec"]  # also in the document metadata (/Subject)


def test_refuses_shared_database_without_explicit_flag(settings):
    settings.DEBUG = True
    with pytest.raises(CommandError, match="not a demo database"):
        call_command("seed_showcase", only=["demo-energy"])


@pytest.fixture
def seeded(db, settings, tmp_path):
    settings.DEBUG = True
    call_command("seed_showcase", only=["demo-energy"], allow_any_database=True, inventory=str(tmp_path / "inv.json"))
    return Tenant.objects.get(slug="demo-energy")


def counts(t):
    with tenant_context(t):
        return (Project.objects.count(), SparePart.objects.count(), DigitalPassport.objects.count(), EngineeringFile.objects.count(),
                sum(f.versions.count() for f in EngineeringFile.objects.all()))


def test_seed_is_idempotent_and_leaves_business_gates_untouched(seeded, settings, tmp_path):
    first = counts(seeded)
    assert first[:3] == (2, 10, 9) and first[3] > 40
    call_command("seed_showcase", only=["demo-energy"], allow_any_database=True, inventory=str(tmp_path / "inv2.json"))
    assert counts(seeded) == first  # nothing duplicated
    with tenant_context(seeded):
        states = set(DigitalPassport.objects.values_list("evidence_level", "publication_state", "manufacturing_eligibility"))
        levels = sorted(DigitalPassport.objects.values_list("data_captured", flat=True))
        statuses = {r.status for p in DigitalPassport.objects.all() for r in p.revisions.all()}
    assert states == {("none", "draft", "not_eligible")}  # OQ-35/OQ-36: never set by the seed
    assert statuses == {"draft"}  # no approvals
    assert {"none", "rl1", "rl2", "rl3"} <= set(levels)


def test_demo_accounts_see_only_their_organisation(world, seeded):
    client_admin = Membership.objects.get(tenant=seeded, role="client_admin").user
    client_admin.set_password(PASSWORD)
    client_admin.save()
    c = login(client_admin)
    numbers = [p["part_number"] for p in c.get("/api/v1/parts/", {"page_size": 200}).json()["results"]]
    assert len(numbers) == 10 and all(n.startswith("DES-") for n in numbers)
    # an unrelated organisation sees none of the showcase data, by search or by id
    other = login(world["a_admin"])
    assert other.get("/api/v1/parts/", {"search": "DES-3001"}).json()["count"] == 0
    with tenant_context(seeded):
        part_id = SparePart.objects.get(part_number="DES-3001").pk
    assert other.get(f"/api/v1/parts/{part_id}/").status_code == 404
    # the demo operator engineer is assigned to the showcase organisation; the operator admin is not
    assert Membership.objects.filter(tenant=seeded, user__email="engineer@operator.demo", role="operator_engineer").exists()
    assert not Membership.objects.filter(tenant=seeded, user__email="admin@operator.demo").exists()


def test_rl3_sample_evidence_is_attached_but_not_verified(seeded):
    with tenant_context(seeded):
        p = DigitalPassport.objects.get(part__part_number="DES-3001")
        rev = p.revisions.get()
        evidence = rev.content["rl3"]["evidence"]
        files = EngineeringFile.objects.filter(pk__in=evidence.values())
        assert len(evidence) == 5 and files.count() == 5 and all(f.passport_id == p.pk for f in files)
        assert p.data_captured == "rl3" and p.evidence_level == "none" and rev.status == "draft"
        spec = EngineeringFile.objects.get(part=p.part, title__endswith="manufacturing specification")
        assert spec.versions.count() == 2  # version history sample (rev B)
